# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import tagged, TransactionCase

from odoo.addons.ai_website.models.ai_session import WEBSITE_BUILDER_TIMEOUT
from odoo.addons.ai.utils.ai_utils import UserInputResponse


@tagged('post_install', '-at_install')
class TestAIWebsiteCallback(TransactionCase):
    def _create_session(self):
        session_data = self.env['ai.agent'].action_launch_ai_chat(
            interface_key='website_builder_ai',
        )
        return self.env['ai.session'].sudo().search([
            ('channel_id', '=', session_data['ai_channel_id']),
        ])

    def test_website_builder_session_advance_stops_before_iap_when_page_is_unavailable(self):
        session = self._create_session()
        request_count = self.env['ai.session.request'].sudo().search_count([])

        request = session.with_context(current_view_info={})._prepare_session_request()

        self.assertFalse(request)
        self.assertEqual(
            self.env['ai.session.request'].sudo().search_count([]), request_count,
        )
        self.assertIn(
            'Please open the website builder',
            session.channel_id.message_ids[0].body,
        )

    def test_website_builder_contributes_model_round_options_context_and_tools(self):
        session = self._create_session()
        current_view_info = {
            'website_page': {'is_page_ai_editable': True},
        }
        snapshot = {
            'active_company_ids': self.env.companies.ids,
            'allowed_company_ids': self.env.companies.ids,
            'current_view_info': current_view_info,
        }
        session = session.with_context(**snapshot)

        request = session._prepare_session_request(context_snapshot=snapshot)
        tools_context = session._build_tools_context()

        self.assertEqual(request.payload['timeout'], WEBSITE_BUILDER_TIMEOUT)
        self.assertEqual(tools_context['ai_session_id'], session.id)
        self.assertIn('## AI JavaScript', str(request.payload['messages']))
        self.assertEqual(request.context_snapshot, snapshot)

    def test_website_builder_resume_waits_until_the_editor_is_available(self):
        session = self._create_session()
        tool = self.env['ir.actions.server'].create({
            'name': 'Website callback confirmation',
            'ai_tool_name': 'website_callback_confirmation',
            'ai_tool_thinking_text': 'Checking the website',
            'ai_tool_description': 'Website callback test fixture.',
            'ai_tool_schema': '{"type": "object", "properties": {}, "required": []}',
            'model_id': self.env.ref('ai.model_ai_tool').id,
            'state': 'code',
            'use_in_ai': True,
            'code': """
if not ai['tool_request_confirmed']:
    ai['user_input_request'] = {
        'type': 'confirmation',
        'body': 'Change the website?',
        'choices': [
            {'label': 'Yes', 'value': 'confirm_once'},
            {'label': 'Always', 'value': 'auto_confirm'},
            {'label': 'No', 'value': 'decline'},
        ],
    }
else:
    ai['state']['website_runs'] = ai['state'].get('website_runs', 0) + 1
    ai['result'] = 'changed'
""",
        })
        current_view_info = {
            'website_page': {'is_page_ai_editable': True},
        }
        snapshot = {
            'active_company_ids': self.env.companies.ids,
            'allowed_company_ids': self.env.companies.ids,
            'current_view_info': current_view_info,
        }
        session.state = {'available_tools': tool.ids}
        session = session.with_context(**snapshot)
        request = session._prepare_session_request(context_snapshot=snapshot)
        waiting = session._apply_iap_result(request, {
            'request_uuid': request.request_uuid,
            'status': 'success',
            'result': {
                'role': 'assistant',
                'content': [{
                    'type': 'tool_call',
                    'call_id': 'website-confirmation',
                    'name': tool.ai_tool_name,
                    'args': {},
                }],
            },
        })
        resume_token = request.resume_token
        message_count = len(session.channel_id.message_ids)

        unavailable = session.with_context(current_view_info={})._resume_pending_interaction(
            request,
            resume_token,
            {'value': UserInputResponse.CONFIRM_ONCE},
            context_snapshot={'current_view_info': {}},
        )

        self.assertEqual(waiting['responseState'], 'waiting_user')
        self.assertEqual(unavailable['responseState'], 'waiting_user')
        self.assertFalse(unavailable['interactionConsumed'])
        self.assertEqual(request.state, 'waiting_input')
        self.assertEqual(request.resume_token, resume_token)
        self.assertNotIn('website_runs', session.state)
        self.assertEqual(len(session.channel_id.message_ids), message_count + 1)
        self.assertIn(
            'Please open the website builder',
            session.channel_id.message_ids[0].body,
        )

        resumed = session._resume_pending_interaction(
            request,
            resume_token,
            {'value': UserInputResponse.CONFIRM_ONCE},
            context_snapshot=snapshot,
        )
        self.assertEqual(resumed['responseState'], 'running')
        self.assertEqual(session.state['website_runs'], 1)
