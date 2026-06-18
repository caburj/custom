# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools.sql import create_index, drop_index

_logger = logging.getLogger(__name__)


# Retention GC tuning: root threads idle past the retention window (no
# write_date activity -- new loops bump it via the stored loop_count) are
# reaped (subtree included) in daily autovacuum batches. Loops frozen as
# "running"/"confirmation" past the zombie cap no longer protect their thread.
GC_RETENTION_DAYS = 30
GC_ZOMBIE_DAYS = 7
GC_BATCH_SIZE = 1000


# --- Debug-helper module-level constants ---------------------------------

# Status reasons that mark a loop as having reached a terminal state. The
# ``confirmation`` reason is intentionally excluded -- a confirmation loop is
# pending user input, not finished.
_DEBUG_TERMINAL_REASONS = ('success', 'max_iterations', 'error')

# Whitelist for ``debug_expand``: kind -> {model, allowed fields}. Keeps the
# helper from becoming an arbitrary attribute reader. ``messages_sent`` is a
# real stored field (the full provider-format messages list sent that
# iteration); for legacy rows captured before that field existed it falls back
# to a synthesized concatenation of preceding ``messages_delta`` deltas.
_DEBUG_EXPAND_WHITELIST = {
    'tool_call': {
        'model': 'ai.debug.tool.call',
        'fields': ('result', 'arguments', 'confirmation_message'),
    },
    'iteration': {
        'model': 'ai.debug.iteration',
        'fields': (
            'instructions', 'output_message', 'messages_delta',
            'messages_sent', 'raw_request', 'raw_response',
        ),
    },
    'loop': {
        'model': 'ai.debug.loop',
        'fields': ('output_message', 'error_message'),
    },
}


def _debug_iso(dt):
    """Render an Odoo datetime (naive UTC) as an ISO-8601 string with a UTC tag."""
    if not dt:
        return None
    if hasattr(dt, 'isoformat'):
        return dt.replace(tzinfo=None).isoformat() + '+00:00'
    return str(dt)


def _debug_truncate_plain(value, max_chars):
    """Plain text truncation with an ellipsis, no expand marker."""
    if value is None:
        return ''
    if not isinstance(value, str):
        value = str(value)
    if len(value) > max_chars:
        return value[:max_chars] + '…'
    return value


def _debug_truncate_with_marker(value, max_chars, kind, record_id, field):
    """Truncate ``value`` to ``max_chars`` chars and append a marker pointing at
    ``debug_expand(kind, record_id, field)`` so the evaluator can fetch the
    full body. Non-string values are JSON-stringified first. Returns ``None``
    for unset Odoo fields (which read as ``False``) so JSON output doesn't
    surface a literal ``"false"`` for empty Text columns.
    """
    if value is None or value is False:
        return None
    if not isinstance(value, str):
        try:
            value = json.dumps(value, default=str, ensure_ascii=False)
        except Exception:
            value = str(value)
    if max_chars and len(value) > max_chars:
        marker = f"<truncated; expand('{kind}', {record_id}, '{field}')>"
        return value[:max_chars] + '...' + marker
    return value


class AiDebugThread(models.Model):
    _name = 'ai.debug.thread'
    _description = 'AI Debug Thread'
    _order = 'id desc'

    session_id = fields.Char(index=True, required=True)
    agent_id = fields.Many2one('ai.agent')
    name = fields.Char()
    user_id = fields.Many2one('res.users', index=True)
    loop_ids = fields.One2many('ai.debug.loop', 'thread_id')
    # parent_thread_id is derived from the first loop's parent tool call. The
    # link is anchored on the loop (not the thread) because a single subagent
    # session is reused across many parent tool calls -- but every loop in a
    # given child thread points back into the same parent thread.
    parent_thread_id = fields.Many2one(
        'ai.debug.thread',
        compute='_compute_parent_thread_id',
        store=True,
        index=True,
    )
    child_thread_ids = fields.One2many(
        'ai.debug.thread', 'parent_thread_id',
    )
    loop_count = fields.Integer(compute='_compute_loop_count', store=True)
    # Captured once at thread creation from the spawning ``ai.session``. The
    # flag is fixed at spawn (a session never flips background<->foreground),
    # so a snapshot is correct -- no need to re-read the live session.
    is_background = fields.Boolean()

    @api.depends('loop_ids')
    def _compute_loop_count(self):
        for thread in self:
            thread.loop_count = len(thread.loop_ids)

    @api.depends('loop_ids.parent_tool_call_id')
    def _compute_parent_thread_id(self):
        for thread in self:
            first_loop = thread.loop_ids.sorted('id')[:1]
            parent_call = first_loop.parent_tool_call_id
            thread.parent_thread_id = parent_call.iteration_id.loop_id.thread_id

    def init(self):
        super().init()
        # superseded by the write_date variant when the GC switched from
        # age-based to idle-based retention
        drop_index(self.env.cr, 'ai_debug_thread_root_create_date_idx', self._table)
        create_index(
            self.env.cr,
            indexname='ai_debug_thread_root_write_date_idx',
            tablename=self._table,
            expressions=['write_date'],
            where='parent_thread_id IS NULL',
        )

    def unlink(self):
        # The loops' ``parent_tool_call_id`` is ondelete='set null', so
        # subagent threads are NOT cascaded when their spawning thread is
        # deleted -- they would be silently orphaned. Walk the subtree and
        # delete it along with self.
        threads = self
        frontier = self
        while frontier:
            children = self.search([('parent_thread_id', 'in', frontier.ids)])
            frontier = children - threads
            threads |= frontier
        return super(AiDebugThread, threads).unlink()

    @api.model
    def fetch_threads(self, before_id=None, limit=10):
        """Return a page of root threads plus their full descendant subtree.

        Cursor-based pagination on ROOT threads only (those without
        ``parent_thread_id``). For each returned root, the full descendant
        hierarchy is also loaded so the frontend can render the sidebar tree
        without additional round-trips.
        """
        fields_list = [
            'session_id', 'name', 'agent_id', 'user_id',
            'loop_count', 'parent_thread_id', 'is_background',
        ]

        domain = [('parent_thread_id', '=', False)]
        if before_id:
            domain.append(('id', '<', before_id))

        roots = self.search_read(
            domain, fields_list, order='id desc', limit=limit,
        )

        # Walk descendants level-by-level. Can't use the ORM's `child_of`
        # operator -- it walks the `_parent_name` field, which we haven't
        # declared (and shouldn't, to avoid Odoo's parent-store side-effects).
        # Order doesn't affect rendering (the JS store re-sorts on read via
        # ``getBy`` -- see ``MODELS`` in ``static/src/store.js``); ``id desc``
        # is kept here for consistency with the root cursor above.
        descendants = []
        if roots:
            queue = [r['id'] for r in roots]
            seen = set(queue)
            while queue:
                batch = self.search_read(
                    [('parent_thread_id', 'in', queue)],
                    fields_list,
                    order='id desc',
                )
                batch = [t for t in batch if t['id'] not in seen]
                if not batch:
                    break
                seen.update(t['id'] for t in batch)
                descendants.extend(batch)
                queue = [t['id'] for t in batch]

        total = self.search_count([('parent_thread_id', '=', False)])

        # Subagent loop stubs: child threads link back to their parent's tool
        # call via loop.parent_tool_call_id, so the parent's tool-call card
        # can show "↗ <agent>" badges. The full loop body (iterations, tool
        # calls, output) only loads when the user navigates to that thread,
        # but the stub here is enough for the badge to appear immediately.
        descendant_ids = [d['id'] for d in descendants]
        subagent_loops = self.env['ai.debug.loop'].search_read(
            [('thread_id', 'in', descendant_ids),
             ('parent_tool_call_id', '!=', False)],
            ['thread_id', 'parent_tool_call_id', 'model_name'],
            order='id asc',
        ) if descendant_ids else []

        return {
            'threads': roots + descendants,
            'subagent_loops': subagent_loops,
            'total': total,
        }

    def fetch_loops(self, before_id=None, limit=10):
        """Return loops and their full subtrees (iterations, tool calls).

        Uses cursor-based pagination (newest-first): when *before_id* is
        given, only loops with ``id < before_id`` are returned.
        """
        self.ensure_one()
        domain = [('thread_id', '=', self.id)]
        if before_id:
            domain.append(('id', '<', before_id))
        return self._read_loops_subtree(domain, limit=limit)

    @api.model
    def fetch_loops_through(self, tool_call_id, until_loop_id=None):
        """Load the loop containing *tool_call_id* (plus any intermediate
        loops up to but not including *until_loop_id*), with iterations
        and tool calls.

        Used by the focus-jump flow: when the spawning tool call lives in
        a loop the regular newest-first pagination hasn't reached yet,
        passing *until_loop_id* (the oldest currently loaded loop id)
        bridges the gap so the conversation view stays contiguous instead
        of showing a silent hole between the target loop and the loaded
        recent ones.
        """
        tool_call = self.env['ai.debug.tool.call'].browse(tool_call_id).exists()
        if not tool_call:
            return {'loops': [], 'iterations': [], 'tool_calls': []}
        return self._fetch_loops_from_target(
            tool_call.iteration_id.loop_id, until_loop_id,
        )

    @api.model
    def fetch_loops_through_loop(self, loop_id, until_loop_id=None):
        """Variant of ``fetch_loops_through`` that takes a loop id directly.

        Used when jumping into a child subagent's specific loop (driven by a
        parent tool call's ``child_loop_ids`` badge) -- the loop need not
        contain any tool calls (e.g. a synthetic confirmation follow-up),
        so anchoring on a tool_call as ``fetch_loops_through`` does isn't
        always possible.
        """
        loop = self.env['ai.debug.loop'].browse(loop_id).exists()
        if not loop:
            return {'loops': [], 'iterations': [], 'tool_calls': []}
        return self._fetch_loops_from_target(loop, until_loop_id)

    @api.model
    def _fetch_loops_from_target(self, target_loop, until_loop_id):
        domain = [
            ('thread_id', '=', target_loop.thread_id.id),
            ('id', '>=', target_loop.id),
        ]
        if until_loop_id is not None:
            domain.append(('id', '<', until_loop_id))
        return self._read_loops_subtree(domain)

    def _read_loops_subtree(self, loop_domain, limit=None):
        """Read loops matching *loop_domain* plus their iterations and
        tool calls. Shared by fetch_loops and fetch_loops_through so the
        client always receives the same record shape.

        ``available_tool_ids`` ships as plain id lists on iterations; the
        referenced ``ir.actions.server`` rows are fetched on demand by the
        client when the user opens the "Available Tools" tab.
        """
        Loop = self.env['ai.debug.loop']
        Iteration = self.env['ai.debug.iteration']
        ToolCall = self.env['ai.debug.tool.call']

        loops = Loop.search_read(
            loop_domain,
            ['thread_id', 'agent_id', 'model_name', 'parent_tool_call_id',
             'input_message', 'input_message_html', 'output_message',
             'is_running', 'termination_reason', 'error_message',
             'start_time', 'duration_ms', 'tokens_in', 'tokens_cached',
             'tokens_out', 'iteration_count'],
            order='id desc',
            limit=limit,
        )

        loop_ids = [l['id'] for l in loops]

        iterations = Iteration.search_read(
            [('loop_id', 'in', loop_ids)],
            ['loop_id', 'sequence', 'is_running', 'instructions',
             'messages_delta', 'messages_sent', 'raw_request', 'raw_response',
             'output_message', 'tokens_in',
             'tokens_cached', 'tokens_out', 'duration_ms', 'tool_call_count',
             'available_tool_ids'],
            order='loop_id asc, sequence asc',
        ) if loop_ids else []

        iteration_ids = [it['id'] for it in iterations]

        tool_calls = ToolCall.search_read(
            [('iteration_id', 'in', iteration_ids)],
            ['iteration_id', 'tool_id', 'call_id', 'name', 'arguments',
             'result', 'duration_ms', 'triggered_confirmation',
             'confirmation_message', 'refused'],
            order='iteration_id asc, id asc',
        ) if iteration_ids else []

        # available_tool_ids links ir.actions.server, which the triggering user
        # can't read -- the user-scoped read above silently drops the ids. The
        # iterations are already record-rule scoped, so re-read the link ids
        # under sudo and ship the referenced tool rows alongside, so the client
        # renders them without its own (forbidden) ir.actions.server read.
        tools = []
        if iterations:
            sudo_tools = {
                r['id']: r['available_tool_ids']
                for r in Iteration.browse(iteration_ids).sudo().read(['available_tool_ids'])
            }
            for it in iterations:
                it['available_tool_ids'] = sudo_tools.get(it['id'], [])
            tool_action_ids = sorted({tid for ids in sudo_tools.values() for tid in ids})
            if tool_action_ids:
                tools = self.env['ir.actions.server'].sudo().browse(tool_action_ids).read(
                    ['display_name', 'llm_name', 'ai_tool_description', 'ai_tool_schema'],
                )

        return {
            'loops': loops,
            'iterations': iterations,
            'tool_calls': tool_calls,
            'tools': tools,
        }

    # ------------------------------------------------------------------
    # Debug helpers (odev eval only -- unstable, may change without notice)
    # ------------------------------------------------------------------
    #
    # These three methods exist so an evaluator can read a completed (or
    # in-progress) AI agent run from a Python script run via ``odev eval``,
    # without needing the OWL viewer. They are NOT a stable API: the JSON
    # shapes returned here are subject to change as the underlying debug
    # data model evolves.
    #
    # The intended workflow is:
    #
    #   1. ``debug_recent(...)``      -- pick a thread to investigate.
    #   2. ``thread.debug_transcript()`` -- read the full hierarchical trace
    #      with previews + ``expand`` markers.
    #   3. ``debug_expand(kind, id, field)`` -- pull the full body of one
    #      truncated field when a preview isn't enough.
    #
    # All three call ``sudo()`` internally so that an ``odev eval`` script
    # running as a non-system user still works.

    @api.model
    def debug_recent(self, limit=20, agent_id=None, user_id=None,
                     since=None, status=None):
        """[DEBUG ONLY -- unstable] Return one-line summaries of recent root threads.

        Filter args:
          - ``agent_id``: int (id) or str (agent name).
          - ``user_id``:  int (id) or str (user login).
          - ``since``:    datetime/str; only threads with a loop started
                          on or after this point are returned.
          - ``status``:   string matching the most-recent terminal loop's
                          ``termination_reason`` (``success``, ``error``,
                          ``max_iterations``, ``confirmation``); applied
                          post-fetch.

        Returns a list of dicts with stable keys (see plan / inline below).
        """
        domain = [('parent_thread_id', '=', False)]
        if agent_id is not None:
            if isinstance(agent_id, str):
                domain.append(('agent_id.name', '=', agent_id))
            else:
                domain.append(('agent_id', '=', int(agent_id)))
        if user_id is not None:
            if isinstance(user_id, str):
                domain.append(('user_id.login', '=', user_id))
            else:
                domain.append(('user_id', '=', int(user_id)))
        if since is not None:
            domain.append(('loop_ids.start_time', '>=', since))

        threads = self.sudo().search(domain, order='id desc', limit=limit)

        if status is not None:
            kept = []
            for t in threads:
                last_term = next(
                    (
                        l for l in reversed(t.loop_ids.sorted('id'))
                        if l.termination_reason
                    ),
                    None,
                )
                if last_term and last_term.termination_reason == status:
                    kept.append(t.id)
            threads = self.sudo().browse(kept)

        return [t._debug_recent_row() for t in threads]

    def _debug_recent_row(self):
        """Build a single ``debug_recent`` row for ``self``."""
        self.ensure_one()
        loops = self.loop_ids.sorted('id')  # ascending = chronological

        iter_total = sum(loops.mapped('iteration_count'))
        tool_call_total = sum(
            len(it.tool_call_ids) for l in loops for it in l.iteration_ids
        )
        in_progress = any(loops.mapped('is_running'))

        last_terminal = next(
            (l for l in reversed(loops) if l.termination_reason), None,
        )
        last_status = last_terminal.termination_reason if last_terminal else None

        first_loop = loops[:1]
        last_with_output = next(
            (l for l in reversed(loops) if not l.is_running and l.output_message),
            None,
        )

        return {
            'thread_id': self.id,
            'session_id': self.session_id or '',
            'agent': self.agent_id.name or '',
            'user': self.user_id.login or '',
            'started_at': _debug_iso(first_loop.start_time) if first_loop else None,
            'loop_count': self.loop_count,
            'iteration_count': iter_total,
            'tool_call_count': tool_call_total,
            'subagent_count': len(self.child_thread_ids),
            'last_status': last_status,
            'first_user_message': _debug_truncate_plain(
                first_loop.input_message if first_loop else '', 200,
            ),
            'last_assistant_preview': _debug_truncate_plain(
                last_with_output.output_message if last_with_output else '', 200,
            ),
            'has_subagents': bool(self.child_thread_ids),
            'in_progress': in_progress,
        }

    def debug_transcript(self, preview_chars=500, max_depth=4):
        """[DEBUG ONLY -- unstable] Full hierarchical transcript of this thread.

        Returns a JSON-serializable dict. Large fields (tool_call.result,
        loop/iteration output_message) are truncated to ``preview_chars``
        with an embedded marker the evaluator can use to call
        ``debug_expand``. ``messages_delta``, ``raw_response``, and
        ``instructions`` are excluded by default and only available via
        ``debug_expand``.

        Subagent threads are inlined under their spawning tool_call up to
        ``max_depth``; beyond that, a ``thread_ref`` stub is emitted so the
        caller can recurse explicitly.
        """
        self.ensure_one()
        return self.sudo()._debug_build_thread_node(
            preview_chars, max_depth, _seen=set(),
        )

    def _debug_build_thread_node(self, preview_chars, depth_remaining, _seen):
        """Recursive builder for ``debug_transcript`` thread nodes."""
        self.ensure_one()
        if self.id in _seen:
            return {'kind': 'thread_ref', 'thread_id': self.id, 'truncated': True}
        _seen = _seen | {self.id}

        loops = self.loop_ids.sorted('id')

        loop_nodes = []
        prev_confirmation_idx = None
        for loop in loops:
            node = self._debug_build_loop_node(
                loop, preview_chars, depth_remaining, _seen,
            )
            if prev_confirmation_idx is not None:
                loop_nodes[prev_confirmation_idx]['next_loop_id'] = node['loop_id']
                prev_confirmation_idx = None
            if node.get('status') == 'confirmation':
                prev_confirmation_idx = len(loop_nodes)
            loop_nodes.append(node)

        # Wall-clock duration: span between first loop start and last loop's
        # end, NOT the sum of loop durations -- gaps between loops (user think
        # time during a follow-up turn) matter for evaluation.
        if loops:
            first = loops[0]
            last = loops[-1]
            started_at = first.start_time
            ended_at = (
                last.start_time + timedelta(milliseconds=last.duration_ms or 0)
                if last.start_time else None
            )
            duration_ms = (
                int((ended_at - started_at).total_seconds() * 1000)
                if started_at and ended_at else 0
            )
        else:
            started_at = None
            ended_at = None
            duration_ms = 0

        last_terminal = next(
            (
                l for l in reversed(loops)
                if l.termination_reason in _DEBUG_TERMINAL_REASONS
            ),
            None,
        )

        summary = {
            'loop_count': len(loops),
            'iteration_count': sum(loops.mapped('iteration_count')),
            'tool_call_count': sum(
                len(it.tool_call_ids) for l in loops for it in l.iteration_ids
            ),
            'subagent_count': len(self.child_thread_ids),
            'duration_ms': duration_ms,
            'tokens': {
                'in': sum(loops.mapped('tokens_in')),
                'cached': sum(loops.mapped('tokens_cached')),
                'out': sum(loops.mapped('tokens_out')),
            },
            'outcome': last_terminal.termination_reason if last_terminal else None,
            'in_progress': any(loops.mapped('is_running')),
            'started_at': _debug_iso(started_at),
            'ended_at': _debug_iso(ended_at),
        }

        return {
            'kind': 'thread',
            'thread_id': self.id,
            'session_id': self.session_id or '',
            'agent': self.agent_id.name or '',
            'user': self.user_id.login or '',
            'summary': summary,
            'loops': loop_nodes,
        }

    def _debug_build_loop_node(self, loop, preview_chars, depth_remaining, _seen):
        """Build one loop node. Detects synthetic confirmation-followup loops."""
        iterations = loop.iteration_ids.sorted('sequence')

        # Heuristic: the synthetic confirmation-followup loop created by
        # ai_session._ai_debug_record_confirmation_final has duration_ms=0,
        # exactly one iteration, no tool calls, and no messages_delta. A real
        # loop with all four properties is implausible (any LLM round-trip
        # produces messages_delta).
        is_followup = (
            (loop.duration_ms or 0) == 0
            and len(iterations) == 1
            and not iterations[0].tool_call_ids
            and not iterations[0].messages_delta
        )

        if loop.is_running:
            status = 'running'
        else:
            status = loop.termination_reason or 'running'

        return {
            'kind': 'confirmation_followup' if is_followup else 'loop',
            'loop_id': loop.id,
            'parent_tool_call_id': loop.parent_tool_call_id.id or None,
            'model': loop.model_name or '',
            'status': status,
            'user_message': loop.input_message or '',
            'assistant_message': _debug_truncate_with_marker(
                loop.output_message, preview_chars, 'loop', loop.id, 'output_message',
            ),
            'error_message': loop.error_message or None,
            'duration_ms': loop.duration_ms or 0,
            'tokens': {
                'in': loop.tokens_in or 0,
                'cached': loop.tokens_cached or 0,
                'out': loop.tokens_out or 0,
            },
            'next_loop_id': None,  # filled in by caller for confirmation chains
            'iterations': [
                self._debug_build_iter_node(it, preview_chars, depth_remaining, _seen)
                for it in iterations
            ],
        }

    def _debug_build_iter_node(self, iteration, preview_chars, depth_remaining, _seen):
        """Build one iteration node."""
        tool_calls = iteration.tool_call_ids.sorted('id')
        return {
            'kind': 'iteration',
            'iteration_id': iteration.id,
            'sequence': iteration.sequence,
            'status': 'running' if iteration.is_running else 'complete',
            'assistant_text': _debug_truncate_with_marker(
                iteration.output_message, preview_chars,
                'iteration', iteration.id, 'output_message',
            ),
            'available_tools': [
                a.llm_name for a in iteration.available_tool_ids if a.llm_name
            ],
            'duration_ms': iteration.duration_ms or 0,
            'tokens': {
                'in': iteration.tokens_in or 0,
                'cached': iteration.tokens_cached or 0,
                'out': iteration.tokens_out or 0,
            },
            'tool_calls': [
                self._debug_build_tool_call_node(tc, preview_chars, depth_remaining, _seen)
                for tc in tool_calls
            ],
        }

    def _debug_build_tool_call_node(self, tc, preview_chars, depth_remaining, _seen):
        """Build one tool_call node, inlining the child subagent loop(s) it
        triggered. Only the loops linked to this specific tool call are
        rendered -- not the whole subagent thread -- so the transcript
        attributes work to the call that produced it.
        """
        child_loops = tc.child_loop_ids.sorted('id')
        if child_loops and depth_remaining > 0:
            subagent_loops = [
                {
                    'kind': 'subagent_loop',
                    'thread_id': loop.thread_id.id,
                    'agent': loop.thread_id.agent_id.name or '',
                    'loop': loop.thread_id._debug_build_loop_node(
                        loop, preview_chars, depth_remaining - 1, _seen,
                    ),
                }
                for loop in child_loops
            ]
        elif child_loops:
            subagent_loops = [
                {
                    'kind': 'subagent_loop_ref',
                    'thread_id': loop.thread_id.id,
                    'loop_id': loop.id,
                    'truncated': True,
                }
                for loop in child_loops
            ]
        else:
            subagent_loops = []

        return {
            'kind': 'tool_call',
            'tool_call_id': tc.id,
            'name': tc.name or '',
            'arguments': tc.arguments,
            'result_preview': _debug_truncate_with_marker(
                tc.result, preview_chars, 'tool_call', tc.id, 'result',
            ),
            'duration_ms': tc.duration_ms or 0,
            'triggered_confirmation': tc.triggered_confirmation,
            'confirmation_message': tc.confirmation_message or None,
            'refused': tc.refused,
            'subagent_loops': subagent_loops,
        }

    @api.model
    def debug_expand(self, kind, record_id, field):
        """[DEBUG ONLY -- unstable] Return the full body of one truncated field.

        ``kind`` is one of ``tool_call``, ``iteration``, ``loop``. ``field``
        must be in the per-kind whitelist (see _DEBUG_EXPAND_WHITELIST).
        Unknown kinds/fields raise ``ValueError`` naming the offender.

        ``messages_sent`` on iteration is normally the stored full
        provider-format messages list captured at the HTTP dispatch moment;
        for legacy rows captured before that field existed it falls back to the
        concatenated ``messages_delta`` of every sibling iteration with
        sequence <= this one (mirroring messages_reconstruction.js), so the
        evaluator can audit the exact provider-format conversation the LLM
        saw at any point in a loop.

        Returns ``{kind, id, field, value, size}`` where ``size`` is the
        serialized length so the caller can decide whether to chunk further.
        """
        spec = _DEBUG_EXPAND_WHITELIST.get(kind)
        if spec is None:
            raise ValueError(
                f"debug_expand: unknown kind {kind!r}; "
                f"allowed: {sorted(_DEBUG_EXPAND_WHITELIST)}"
            )
        if field not in spec['fields']:
            raise ValueError(
                f"debug_expand: field {field!r} not allowed for kind {kind!r}; "
                f"allowed: {list(spec['fields'])}"
            )

        record = self.env[spec['model']].sudo().browse(record_id).exists()
        if not record:
            raise ValueError(f"debug_expand: {kind} {record_id} not found")

        if kind == 'iteration' and field == 'messages_sent' and not record.messages_sent:
            # Row without a stored messages_sent (legacy capture, or capture
            # failure): fall back to delta reconstruction. A NULL jsonb column
            # reads back as ``False``, never ``None`` -- test falsiness, not
            # ``is None``, or this fallback never fires.
            value = self._debug_messages_sent(record)
        else:
            value = record[field]

        if isinstance(value, str):
            size = len(value)
        elif value is None:
            size = 0
        else:
            try:
                size = len(json.dumps(value, default=str, ensure_ascii=False))
            except Exception:
                size = -1

        return {
            'kind': kind,
            'id': record_id,
            'field': field,
            'value': value,
            'size': size,
        }

    @api.model
    def _debug_messages_sent(self, iteration):
        """Legacy fallback: concatenate ``messages_delta`` of preceding sibling
        iterations to reconstruct the full messages list.

        Only used for rows captured before ``messages_sent`` became a stored
        field (new captures store the real provider request messages directly).
        Mirrors ``ai_debug/static/src/components/messages_reconstruction.js``
        so the Python and JS reconstructions stay in sync.
        """
        siblings = iteration.loop_id.iteration_ids.sorted('sequence')
        result = []
        for sib in siblings:
            if sib.sequence > iteration.sequence:
                break
            if sib.messages_delta:
                result.extend(sib.messages_delta)
        return result

    # ------------------------------------------------------------------
    # Export -- single-file transcript bundle for offline viewing
    # ------------------------------------------------------------------
    #
    # The output is a JSON-serializable dict in a shape that matches what
    # ``fetch_threads`` / ``fetch_loops`` already return, so the frontend
    # can hand the records to the same ``store.insert`` path that consumes
    # live RPC responses. Many2one fields ship as ``[id, name]`` tuples
    # (Odoo's standard ``read()`` shape), Many2many ``available_tool_ids``
    # ships as a list of ids whose target rows are bundled under ``tools``.
    #
    # Image content embedded in ``messages_delta`` / ``raw_response`` is
    # already inlined as base64 data URIs by ``_ai_debug_strip_binary`` at
    # capture time; non-image binaries are already stubbed out. So the
    # bundle is fully self-contained -- no sidecar files needed.

    # v2: iterations carry the captured ``messages_sent`` (full provider-format
    # messages list) and ``raw_request`` (full request envelope) fields. v1
    # bundles lack them; the viewer falls back to delta reconstruction for
    # Messages Sent and shows an empty Raw Request tab on v1 imports.
    _EXPORT_SCHEMA_VERSION = 2

    _EXPORT_FIELDS = {
        'thread': [
            'session_id', 'name', 'agent_id', 'user_id',
            'loop_count', 'parent_thread_id', 'is_background',
        ],
        'loop': [
            'thread_id', 'agent_id', 'model_name', 'parent_tool_call_id',
            'input_message', 'input_message_html', 'output_message',
            'is_running', 'termination_reason', 'error_message',
            'start_time', 'duration_ms',
            'tokens_in', 'tokens_cached', 'tokens_out', 'iteration_count',
        ],
        'iteration': [
            'loop_id', 'sequence', 'is_running', 'instructions',
            'messages_delta', 'messages_sent', 'raw_request', 'raw_response',
            'output_message',
            'tokens_in', 'tokens_cached', 'tokens_out',
            'duration_ms', 'tool_call_count', 'available_tool_ids',
        ],
        'tool_call': [
            'iteration_id', 'tool_id', 'call_id', 'name',
            'arguments', 'result', 'duration_ms',
            'triggered_confirmation', 'confirmation_message', 'refused',
        ],
        'tool_action': [
            'display_name', 'llm_name',
            'ai_tool_description', 'ai_tool_schema',
        ],
    }

    def export_transcript(self):
        """[DEBUG ONLY -- unstable] Bundle this thread + its full subtree.

        Returns a JSON-serializable dict suitable for download as a ``.json``
        file and re-import via the ``/ai-debug`` viewer. Walks descendant
        threads (via ``parent_thread_id``), then collects all loops /
        iterations / tool_calls beneath them. Resolves every referenced
        ``ir.actions.server`` (from ``tool_id`` Many2one and
        ``available_tool_ids`` Many2many) into a ``tools`` array so the
        frontend's "Available Tools" tab works without server access.

        Schema is intentionally unstable -- the contract is shared between
        this method and the JS importer; bump ``_EXPORT_SCHEMA_VERSION``
        on incompatible changes.

        Sensitive content
            The bundle inlines raw LLM responses, augmented system prompts
            (``iteration.instructions``), tool arguments, and tool
            results. Treat exported files as sensitive -- they may
            contain customer data, API key echoes, or business secrets
            depending on what the agent ran against.

        Bundle size
            No upper bound. A long-running trace with many iterations of
            large ``messages_delta`` / ``raw_response`` payloads can
            produce a multi-hundred-MB JSON; ``JSON.stringify`` on the
            browser side may choke before the download starts. If this
            becomes a practical problem, switch to a streaming /
            chunked export.
        """
        self.ensure_one()

        # 1. Walk descendant threads (BFS via parent_thread_id). ``id asc`` so
        # the bundle JSON reads in spawn order for humans inspecting it -- the
        # frontend re-sorts on read, so this is cosmetic, not load-bearing.
        threads = self
        frontier = self
        while frontier:
            children = self.env['ai.debug.thread'].sudo().search(
                [('parent_thread_id', 'in', frontier.ids)], order='id asc',
            )
            children = children - threads
            threads |= children
            frontier = children

        loops = self.env['ai.debug.loop'].sudo().search([
            ('thread_id', 'in', threads.ids),
        ])
        iterations = self.env['ai.debug.iteration'].sudo().search([
            ('loop_id', 'in', loops.ids),
        ])
        tool_calls = self.env['ai.debug.tool.call'].sudo().search([
            ('iteration_id', 'in', iterations.ids),
        ])

        # 2. Resolve referenced ir.actions.server (tool_id m2o + available_tool_ids m2m).
        tool_action_ids = set(tool_calls.mapped('tool_id').ids)
        for it in iterations:
            tool_action_ids.update(it.available_tool_ids.ids)
        tool_actions = self.env['ir.actions.server'].sudo().browse(
            sorted(tool_action_ids),
        )

        return {
            'schema_version': self._EXPORT_SCHEMA_VERSION,
            'exported_at': _debug_iso(fields.Datetime.now()),
            'source_db': self.env.cr.dbname,
            'root_thread_id': self.id,
            'threads': threads.read(self._EXPORT_FIELDS['thread']),
            'loops': loops.read(self._EXPORT_FIELDS['loop']),
            'iterations': iterations.read(self._EXPORT_FIELDS['iteration']),
            'tool_calls': tool_calls.read(self._EXPORT_FIELDS['tool_call']),
            'tools': tool_actions.read(self._EXPORT_FIELDS['tool_action']),
        }

    # ------------------------------------------------------------------
    # Retention GC
    # ------------------------------------------------------------------

    @api.autovacuum
    def _gc_threads(self):
        """Reap root threads idle past the retention window, subtrees included.

        Idleness keys on the root's ``write_date``: each new agentic turn
        creates a loop, which bumps it through the stored ``loop_count``
        recompute -- so an actively reused session is never reaped mid-use.
        A root is kept while any loop in its subtree is still running or
        awaiting confirmation -- unless that loop has been frozen in that
        state past the zombie cap (a crashed run stuck as "running").
        """
        now = fields.Datetime.now()
        candidates = self.search([
            ('parent_thread_id', '=', False),
            ('write_date', '<', now - timedelta(days=GC_RETENTION_DAYS)),
        ], limit=GC_BATCH_SIZE)
        if not candidates:
            return 0, False

        # One walk over all candidate subtrees, mapping each descendant back
        # to its candidate root so a single loop search can protect roots.
        root_of = {t.id: t.id for t in candidates}
        all_threads = candidates
        frontier = candidates
        while frontier:
            children = self.search([('parent_thread_id', 'in', frontier.ids)])
            frontier = children - all_threads
            for child in frontier:
                root_of[child.id] = root_of[child.parent_thread_id.id]
            all_threads |= frontier

        protecting_loops = self.env['ai.debug.loop'].search([
            ('thread_id', 'in', all_threads.ids),
            '|',
            ('is_running', '=', True),
            ('termination_reason', '=', 'confirmation'),
            ('write_date', '>=', now - timedelta(days=GC_ZOMBIE_DAYS)),
        ])
        protected = {root_of[loop.thread_id.id] for loop in protecting_loops}

        reaped = candidates.filtered(lambda t: t.id not in protected)
        count = len(reaped)
        if reaped:
            _logger.info('GC reaped %d ai.debug.thread root(s)', count)
            reaped.unlink()
        # Re-queue on the REAPED count, not the candidate count -- a full
        # batch that is mostly protected would otherwise re-fetch the same
        # rows and spin for the rest of the autovacuum run.
        return count, count == GC_BATCH_SIZE
