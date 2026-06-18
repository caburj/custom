# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestExportTranscript(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = cls.env['ai.agent'].create({
            'name': 'Test Agent',
            'system_prompt': 'Test system prompt',
        })
        cls.thread = cls.env['ai.debug.thread'].create({
            'session_id': 'test-session-1',
            'agent_id': cls.agent.id,
            'user_id': cls.env.user.id,
        })
        cls.loop = cls.env['ai.debug.loop'].create({
            'thread_id': cls.thread.id,
            'model_name': 'test-model',
            'input_message': 'hello',
            'output_message': 'hi',
            'duration_ms': 1234,
            'termination_reason': 'success',
        })
        cls.iteration = cls.env['ai.debug.iteration'].create({
            'loop_id': cls.loop.id,
            'sequence': 0,
            'output_message': 'thinking...',
            'duration_ms': 500,
        })
        cls.tool_action = cls.env['ir.actions.server'].search([], limit=1)
        cls.tool_call = cls.env['ai.debug.tool.call'].create({
            'iteration_id': cls.iteration.id,
            'tool_id': cls.tool_action.id,
            'name': 'search_records',
            'arguments': {'domain': []},
            'result': '[]',
            'duration_ms': 100,
        })

    def test_export_returns_envelope(self):
        bundle = self.thread.export_transcript()
        self.assertEqual(bundle['schema_version'], 2)
        self.assertEqual(bundle['root_thread_id'], self.thread.id)
        self.assertEqual(bundle['source_db'], self.env.cr.dbname)
        self.assertIn('exported_at', bundle)
        self.assertEqual(len(bundle['threads']), 1)
        self.assertEqual(len(bundle['loops']), 1)
        self.assertEqual(len(bundle['iterations']), 1)
        self.assertEqual(len(bundle['tool_calls']), 1)

    def test_export_carries_is_background_flag(self):
        # The is_background flag must survive export so imported traces render
        # the same background indicator on their tree nodes as live ones.
        bg_thread = self.env['ai.debug.thread'].create({
            'session_id': 'test-session-bg',
            'agent_id': self.agent.id,
            'user_id': self.env.user.id,
            'is_background': True,
        })
        thread_row = bg_thread.export_transcript()['threads'][0]
        self.assertIn('is_background', thread_row)
        self.assertTrue(thread_row['is_background'])

    def test_export_resolves_m2o_as_id_name_tuple(self):
        bundle = self.thread.export_transcript()
        thread_row = bundle['threads'][0]
        # Odoo .read() shape: m2o -> [id, name]
        self.assertEqual(thread_row['agent_id'][0], self.agent.id)
        self.assertEqual(thread_row['agent_id'][1], 'Test Agent')

    def test_export_includes_referenced_tool_actions(self):
        bundle = self.thread.export_transcript()
        tool_ids = {t['id'] for t in bundle['tools']}
        self.assertIn(self.tool_action.id, tool_ids)
        # Frontend "Available Tools" tab needs these four:
        tool_row = next(t for t in bundle['tools'] if t['id'] == self.tool_action.id)
        for f in ('display_name', 'llm_name', 'ai_tool_description', 'ai_tool_schema'):
            self.assertIn(f, tool_row)

    def test_export_includes_subagent_subtree(self):
        """3-level descendant tree: root -> child -> grandchild.

        Pins the BFS walk in export_transcript: a regression that does
        ``frontier |= children`` instead of ``frontier = children`` would
        still pass at depth 1 but stall at depth 2+.
        """
        # Level 1: child of self.tool_call. The thread <-> parent-tool-call
        # link lives on the loop now (one link per spawn / ask call), so
        # parent_thread_id derives from the loop's parent_tool_call_id.
        child_thread = self.env['ai.debug.thread'].create({
            'session_id': 'test-session-1-child',
            'agent_id': self.agent.id,
            'user_id': self.env.user.id,
        })
        child_loop = self.env['ai.debug.loop'].create({
            'thread_id': child_thread.id,
            'parent_tool_call_id': self.tool_call.id,
            'model_name': 'test-model',
            'input_message': 'subagent task',
            'duration_ms': 50,
            'termination_reason': 'success',
        })
        child_iteration = self.env['ai.debug.iteration'].create({
            'loop_id': child_loop.id,
            'sequence': 0,
            'duration_ms': 25,
        })
        child_tool_call = self.env['ai.debug.tool.call'].create({
            'iteration_id': child_iteration.id,
            'tool_id': self.tool_action.id,
            'name': 'start_session',
            'arguments': {},
            'result': '[]',
            'duration_ms': 10,
        })
        # Level 2: grandchild of child_tool_call.
        grandchild_thread = self.env['ai.debug.thread'].create({
            'session_id': 'test-session-1-grandchild',
            'agent_id': self.agent.id,
            'user_id': self.env.user.id,
        })
        grandchild_loop = self.env['ai.debug.loop'].create({
            'thread_id': grandchild_thread.id,
            'parent_tool_call_id': child_tool_call.id,
            'model_name': 'test-model',
            'input_message': 'grand-subagent task',
            'duration_ms': 25,
            'termination_reason': 'success',
        })

        bundle = self.thread.export_transcript()
        thread_ids = {t['id'] for t in bundle['threads']}
        loop_ids = {l['id'] for l in bundle['loops']}
        self.assertIn(child_thread.id, thread_ids)
        self.assertIn(child_loop.id, loop_ids)
        self.assertIn(grandchild_thread.id, thread_ids)
        self.assertIn(grandchild_loop.id, loop_ids)

    def test_export_orders_siblings_by_spawn_order(self):
        """Sibling subagents under one parent ship in id-asc (spawn) order.

        Cosmetic for the bundle JSON -- the frontend re-sorts on read --
        but a regression here would re-introduce the desc-id ordering
        that ai.debug.thread's _order falls back to.
        """
        first_child = self.env['ai.debug.thread'].create({
            'session_id': 'test-session-sib-first',
            'agent_id': self.agent.id,
            'user_id': self.env.user.id,
        })
        self.env['ai.debug.loop'].create({
            'thread_id': first_child.id,
            'parent_tool_call_id': self.tool_call.id,
            'model_name': 'test-model',
            'input_message': 'first subagent',
            'duration_ms': 10,
            'termination_reason': 'success',
        })
        second_child = self.env['ai.debug.thread'].create({
            'session_id': 'test-session-sib-second',
            'agent_id': self.agent.id,
            'user_id': self.env.user.id,
        })
        self.env['ai.debug.loop'].create({
            'thread_id': second_child.id,
            'parent_tool_call_id': self.tool_call.id,
            'model_name': 'test-model',
            'input_message': 'second subagent',
            'duration_ms': 10,
            'termination_reason': 'success',
        })

        bundle = self.thread.export_transcript()
        siblings = [
            t['id'] for t in bundle['threads']
            if t['id'] in (first_child.id, second_child.id)
        ]
        self.assertEqual(siblings, [first_child.id, second_child.id])

    def test_round_trip_preserves_field_values(self):
        """Exported per-record fields match a direct read() of the source records.

        Catches mid-pipeline mutation in export_transcript -- e.g. a future
        truncation or rewrite that diverges from the read() shape the
        frontend store consumes.
        """
        Thread = self.env['ai.debug.thread']
        bundle = self.thread.export_transcript()

        cases = [
            ('thread', self.thread, bundle['threads']),
            ('loop', self.loop, bundle['loops']),
            ('iteration', self.iteration, bundle['iterations']),
            ('tool_call', self.tool_call, bundle['tool_calls']),
        ]
        for kind, source, exported_rows in cases:
            original = source.read(Thread._EXPORT_FIELDS[kind])[0]
            exported = next(r for r in exported_rows if r['id'] == source.id)
            for f in Thread._EXPORT_FIELDS[kind]:
                self.assertEqual(
                    exported[f], original[f], f"{kind}.{f} mismatch",
                )
