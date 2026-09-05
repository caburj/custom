# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

from odoo import Command
from odoo.addons.ai.utils.ai_utils import get_odoo_ai_connection_data
from odoo.tests import HttpCase, tagged

from .common import apply_iap_result


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
        actor = self.env.ref('base.user_admin')
        company = self.env['res.company'].create({'name': 'Headless AI Company'})
        actor.company_ids = [Command.link(company.id)]
        action = action.with_user(actor).with_context(allowed_company_ids=company.ids)
        observed = {}

        def observe_submission_environment(env):
            observed.update({
                'actor_uid': env.uid,
                'sudo': env.su,
                'context': dict(env.context),
                'default_environment': env.transaction.default_env is env,
            })
            return get_odoo_ai_connection_data(env)

        with (
            patch(
                'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
                return_value=None,
            ) as transport,
            patch(
                'odoo.addons.ai.models.ai_session.get_odoo_ai_connection_data',
                side_effect=observe_submission_environment,
            ),
        ):
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
        self.assertEqual(observed['actor_uid'], actor.id)
        self.assertFalse(observed['sudo'])
        self.assertTrue(observed['default_environment'])
        self.assertEqual(observed['context'], session.request_context)
        self.assertEqual(observed['context']['allowed_company_ids'], company.ids)
        self.assertEqual(transport.call_args.args[1], '1/get_completions')
        self.assertEqual(
            transport.call_args.args[2]['request_uuid'],
            request_uuid,
        )
        self.assertEqual(
            transport.call_args.args[2]['webhook_url'],
            session.request_callback_url,
        )
        self.assertIs(transport.call_args.args[2]['llm_retry'], False)
        self.assertNotIn('callback_url', transport.call_args.args[2])
        session.invalidate_recordset()
        self.assertEqual(session.request_phase, 'submitted')

        apply_iap_result(session, request_uuid, {
            'request_uuid': request_uuid,
            'status': 'success',
            'result': {
                'role': 'assistant',
                'content': [{'type': 'text', 'text': 'Automation complete'}],
            },
        })

        self.assertEqual(session.loop_state, 'ready')
        self.assertEqual(session.request_uuid, request_uuid)
        self.assertTrue(session.request_result)
        self.assertFalse(session.auto_confirm)
        self.assertIn(
            'Automation complete',
            session.channel_id.message_ids[0].body,
        )
