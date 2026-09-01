# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestAIAutomationCallback(HttpCase):
    def test_automation_run_prepares_then_submits_after_commit(self):
        agent = self.env['ai.agent'].create({
            'name': 'Callback Automation Agent',
            'system_prompt': 'Run the requested automation.',
        })
        partner = self.env['res.partner'].create({
            'name': 'Callback Automation Contact',
        })
        action = self.env['ir.actions.server'].create({
            'name': 'Callback Automation Action',
            'model_id': self.env['ir.model']._get_id('res.partner'),
            'state': 'ai',
            'ai_action_prompt': 'Summarize this contact.',
        })

        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=lambda _connection, _route, payload, **_kwargs: {
                'request_uuid': payload['request_uuid'],
                'status': 'queued',
            },
        ) as transport:
            action._ai_action_run_agent(partner, agent)
            session = self.env['ai.session'].sudo().search([
                ('agent_id', '=', agent.id),
                ('res_model', '=', partner._name),
                ('res_id', '=', partner.id),
            ])

            self.assertEqual(len(session), 1)
            self.assertEqual(session.loop_state, 'waiting_model')
            self.assertEqual(session.request_phase, 'prepared')
            self.assertTrue(session.auto_confirm)
            self.assertTrue(session.request_context['ai_automation_run'])
            transport.assert_not_called()

            request_uuid = session.request_uuid
            self.env.cr.postcommit.run()

        transport.assert_called_once()
        self.assertEqual(transport.call_args.args[1], '1/submit_completions')
        self.assertEqual(
            transport.call_args.args[2]['request_uuid'],
            request_uuid,
        )
        session.invalidate_recordset()
        self.assertEqual(session.request_phase, 'submitted')

        session._apply_iap_result(request_uuid, {
            'request_uuid': request_uuid,
            'status': 'success',
            'result': {
                'role': 'assistant',
                'content': [{'type': 'text', 'text': 'Automation complete'}],
            },
        })

        self.assertEqual(session.loop_state, 'ready')
        self.assertFalse(session.request_uuid)
        self.assertFalse(session.auto_confirm)
        self.assertIn(
            'Automation complete',
            session.channel_id.message_ids[0].body,
        )
