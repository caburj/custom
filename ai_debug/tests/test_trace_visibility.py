# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestTraceVisibility(TransactionCase):
    """AI Debug trace visibility is strictly by identity on every access path.

    An administrator (Settings/Administration access == ``base.group_system``)
    sees all users' traces; a regular internal user sees only their own -- a run
    and all its subagent sub-runs belong to the initiating user. A regular user
    asking for another user's trace by identifier gets no data, treated as not
    found. Covers the acceptance scenarios that
    concern the four programmatic/export methods on ``ai.debug.thread``:
    ``debug_recent``, ``debug_transcript``, ``debug_expand``,
    ``export_transcript``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Thread = cls.env['ai.debug.thread']

        # A regular internal user, another regular user (whose trace the first
        # must never reach), and an administrator (group_system, NOT superuser
        # -- so the record rules, not an su bypass, must grant the all-traces
        # visibility).
        cls.regular_user = new_test_user(
            cls.env, login='trace_regular', groups='base.group_user',
        )
        cls.other_user = new_test_user(
            cls.env, login='trace_other', groups='base.group_user',
        )
        cls.admin_user = new_test_user(
            cls.env, login='trace_admin',
            groups='base.group_user,base.group_system',
        )

        cls.agent = cls.env['ai.agent'].create({
            'name': 'Visibility Agent',
            'system_prompt': 'x',
        })
        # A shared tool (ir.actions.server) that a regular user cannot read
        # directly -- referenced by the run so the transcript/export paths
        # exercise the shared-metadata reads.
        cls.tool_action = cls.env['ir.actions.server'].search([], limit=1)
        assert cls.tool_action, "expected at least one ir.actions.server to reference"

        # Regular user's run: root thread + loop + iteration + tool_call, plus
        # a subagent child thread (same owner, linked through the tool_call).
        cls.reg_thread, cls.reg_loop, cls.reg_iteration, cls.reg_tool_call = (
            cls._make_run('reg', cls.regular_user)
        )
        cls.reg_child_thread = cls.env['ai.debug.thread'].create({
            'session_id': 'reg-child',
            'agent_id': cls.agent.id,
            'user_id': cls.regular_user.id,
        })
        cls.reg_child_loop = cls.env['ai.debug.loop'].create({
            'thread_id': cls.reg_child_thread.id,
            'parent_tool_call_id': cls.reg_tool_call.id,
            'model_name': 'test-model',
            'input_message': 'subagent task',
            'output_message': 'subagent done',
            'duration_ms': 5,
            'termination_reason': 'success',
        })

        # Another user's run: root thread + loop + iteration + tool_call.
        cls.other_thread, cls.other_loop, cls.other_iteration, cls.other_tool_call = (
            cls._make_run('other', cls.other_user)
        )

    @classmethod
    def _make_run(cls, tag, user):
        thread = cls.env['ai.debug.thread'].create({
            'session_id': f'{tag}-session',
            'agent_id': cls.agent.id,
            'user_id': user.id,
        })
        loop = cls.env['ai.debug.loop'].create({
            'thread_id': thread.id,
            'model_name': 'test-model',
            'input_message': f'{tag} hello',
            'output_message': f'{tag} hi',
            'duration_ms': 100,
            'termination_reason': 'success',
        })
        iteration = cls.env['ai.debug.iteration'].create({
            'loop_id': loop.id,
            'sequence': 0,
            'output_message': f'{tag} thinking',
            'duration_ms': 50,
            # Reference the shared tool so transcript/export must read
            # ir.actions.server metadata the owner cannot read directly.
            'available_tool_ids': [(6, 0, cls.tool_action.ids)],
        })
        tool_call = cls.env['ai.debug.tool.call'].create({
            'iteration_id': iteration.id,
            'tool_id': cls.tool_action.id,
            'name': 'search_records',
            'arguments': {'domain': []},
            'result': f'{tag}-result',
            'duration_ms': 10,
        })
        return thread, loop, iteration, tool_call

    # -- Scenario 2 / 6: regular user's list is scoped to own -----------------

    def test_debug_recent_regular_user_sees_only_own(self):
        rows = self.Thread.with_user(self.regular_user).debug_recent()
        thread_ids = {r['thread_id'] for r in rows}
        self.assertIn(self.reg_thread.id, thread_ids,
            "regular user sees their own root thread")
        self.assertNotIn(self.other_thread.id, thread_ids,
            "regular user must not see another user's thread")

    def test_debug_recent_regular_user_filter_by_other_leaks_nothing(self):
        # Scenario 5 (mirror) / behaviour rule 5: the user filter used by a
        # regular user never reveals another user's traces.
        rows = self.Thread.with_user(self.regular_user).debug_recent(
            user_id=self.other_user.login,
        )
        self.assertEqual(rows, [],
            "a regular user filtering by another login gets no rows")

    # -- Scenario 1 / 5 / 6: administrator sees everything --------------------

    def test_debug_recent_admin_sees_all_users(self):
        rows = self.Thread.with_user(self.admin_user).debug_recent()
        thread_ids = {r['thread_id'] for r in rows}
        self.assertIn(self.reg_thread.id, thread_ids)
        self.assertIn(self.other_thread.id, thread_ids,
            "an administrator sees every user's traces")

    def test_debug_recent_admin_filter_by_user(self):
        rows = self.Thread.with_user(self.admin_user).debug_recent(
            user_id=self.other_user.login,
        )
        thread_ids = {r['thread_id'] for r in rows}
        self.assertIn(self.other_thread.id, thread_ids,
            "an administrator can filter recent traces by a specific user")
        self.assertNotIn(self.reg_thread.id, thread_ids)

    # -- Scenario 4: regular user cannot obtain another user's trace ----------

    def test_debug_transcript_regular_user_other_thread_not_found(self):
        result = self.other_thread.with_user(self.regular_user).debug_transcript()
        self.assertEqual(result, {},
            "another user's transcript yields no trace data (treated as not found)")

    def test_debug_expand_regular_user_other_records_not_found(self):
        Thread = self.Thread.with_user(self.regular_user)
        for kind, record_id, field in (
            ('loop', self.other_loop.id, 'output_message'),
            ('iteration', self.other_iteration.id, 'output_message'),
            ('tool_call', self.other_tool_call.id, 'result'),
        ):
            with self.assertRaises(ValueError, msg=f'{kind} must be not found'):
                Thread.debug_expand(kind, record_id, field)

    def test_export_transcript_regular_user_other_thread_no_bundle(self):
        bundle = self.other_thread.with_user(self.regular_user).export_transcript()
        self.assertFalse(bundle,
            "another user's export produces no bundle (no partial, no other-user data)")

    # -- Scenario 3: regular user fully inspects and exports their OWN run -----

    def test_debug_transcript_regular_user_own_thread_full(self):
        result = self.reg_thread.with_user(self.regular_user).debug_transcript()
        self.assertEqual(result.get('kind'), 'thread')
        self.assertEqual(result.get('thread_id'), self.reg_thread.id)
        # The subagent sub-run belongs to the same user and is counted here;
        # this also proves the transcript build reads the shared tool metadata
        # (ir.actions.server llm_name) the owner cannot read directly, without
        # raising.
        self.assertEqual(result['summary']['subagent_count'], 1,
            "own transcript includes the subagent sub-run")

    def test_debug_expand_regular_user_own_record(self):
        result = self.Thread.with_user(self.regular_user).debug_expand(
            'loop', self.reg_loop.id, 'output_message',
        )
        self.assertEqual(result['value'], 'reg hi',
            "regular user reads the full field of their own trace")

    def test_export_transcript_regular_user_own_thread_includes_subagent(self):
        bundle = self.reg_thread.with_user(self.regular_user).export_transcript()
        self.assertTrue(bundle, "own export produces a bundle")
        thread_ids = {t['id'] for t in bundle['threads']}
        self.assertIn(self.reg_thread.id, thread_ids)
        self.assertIn(self.reg_child_thread.id, thread_ids,
            "own export includes the subagent sub-run subtree")
        # Shared tool metadata stays complete in the owner's bundle.
        tool_ids = {t['id'] for t in bundle['tools']}
        self.assertIn(self.tool_action.id, tool_ids,
            "own export still resolves referenced tool metadata")

    # -- Scenario 5: administrator exports (and reaches) another user's run ----

    def test_debug_transcript_admin_other_thread_full(self):
        result = self.other_thread.with_user(self.admin_user).debug_transcript()
        self.assertEqual(result.get('kind'), 'thread')
        self.assertEqual(result.get('thread_id'), self.other_thread.id)

    def test_debug_expand_admin_other_record(self):
        result = self.Thread.with_user(self.admin_user).debug_expand(
            'loop', self.other_loop.id, 'output_message',
        )
        self.assertEqual(result['value'], 'other hi',
            "an administrator reads any user's trace field")

    def test_export_transcript_admin_other_thread_bundle(self):
        bundle = self.other_thread.with_user(self.admin_user).export_transcript()
        self.assertTrue(bundle, "an administrator exports another user's trace")
        thread_ids = {t['id'] for t in bundle['threads']}
        self.assertIn(self.other_thread.id, thread_ids)
