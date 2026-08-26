import json

from werkzeug.exceptions import NotFound
from werkzeug.wrappers import Response

from odoo import api, http, SUPERUSER_ID


def _require_loopback():
    if http.request.httprequest.remote_addr not in ('127.0.0.1', '::1'):
        raise NotFound()


def _json_response(payload):
    return Response(json.dumps(payload), content_type='application/json')


class AICallbackConsumerHarness(http.Controller):
    @http.route(
        '/ai_callback_consumer_harness/setup',
        type='http', auth='public', methods=['POST'], csrf=False,
        save_session=False,
    )
    def setup(self):
        _require_loopback()
        body = http.request.httprequest.get_json(silent=True) or {}
        endpoint = body.get('iap_endpoint')
        scenario = body.get('scenario', 'plain')
        if (
            endpoint != 'http://127.0.0.1:18270'
            or scenario not in (
                'plain', 'server-tool', 'confirmation-tools', 'question',
                'tool-failure', 'terminal-error',
            )
        ):
            raise NotFound()

        env = api.Environment(http.request.env.cr, SUPERUSER_ID, {})
        parameters = env['ir.config_parameter'].sudo()
        parameters.set_str('ai.endpoint', endpoint)
        service = env.ref('ai.iap_service_odoo_ai')
        account = env['iap.account'].sudo().search([
            ('service_id', '=', service.id),
            ('company_ids', '=', False),
        ], limit=1)
        if not account:
            account = env['iap.account'].sudo().create({
                'service_id': service.id,
            })
        account.with_context(disable_iap_update=True).write({
            'account_token': 'callback-harness-fixture-token',
        })
        agent = env['ai.agent'].create({
            'name': 'Paired Callback Harness Agent',
            'system_prompt': 'Answer the user plainly.',
        })
        channel = agent._create_ai_chat_channel('Paired Callback Harness')
        session = env['ai.session'].sudo().create({
            'agent_id': agent.id,
            'channel_id': channel.id,
        })
        confirmation_skill_ids = []
        if scenario == 'server-tool':
            env['res.partner'].create({'name': 'Callback Harness Contact'})
            tool = env['ir.actions.server'].create({
                'name': 'Count callback harness contacts',
                'ai_tool_name': 'ai_tool_callback_count_contacts',
                'ai_tool_thinking_text': 'Counting callback harness contacts',
                'ai_tool_description': 'Count the callback harness contacts.',
                'ai_tool_schema': (
                    '{"type": "object", "properties": {}, "required": []}'
                ),
                'model_id': env.ref('ai.model_ai_tool').id,
                'state': 'code',
                'use_in_ai': True,
                'code': (
                    "ai['result'] = env['res.partner'].search_count("
                    "[('name', '=', 'Callback Harness Contact')])"
                ),
            })
            session.state = {'available_tools': [tool.id]}
            prompt = 'How many callback harness contacts do I have?'
        elif scenario == 'confirmation-tools':
            env['res.partner'].create({'name': 'Callback Harness Before Update'})
            confirmation_skill_ids = [
                env.ref('ai.ai_skill_create_records').id,
                env.ref('ai.ai_skill_update_records').id,
            ]
            agent.sudo().write({'skill_ids': [(6, 0, confirmation_skill_ids)]})
            prompt = (
                'Create Callback Harness Created, then rename '
                'Callback Harness Before Update to Callback Harness After Update.'
            )
        elif scenario == 'question':
            prompt = (
                'Use the ask-user-question tool to ask whether I prefer Draft '
                'or Send. After I answer, tell me which option I selected.'
            )
        elif scenario == 'tool-failure':
            prompt = 'Try the callback harness tool and explain any failure.'
        elif scenario == 'terminal-error':
            prompt = 'Trigger the callback harness provider failure.'
        else:
            prompt = 'Hi'
        message = channel.message_post(body=prompt, message_type='comment')
        return _json_response({
            'database_uuid': parameters.get_str('database.uuid'),
            'channel_id': channel.id,
            'session_id': session.id,
            'message_id': message.id,
            'confirmation_skill_ids': confirmation_skill_ids,
        })

    @http.route(
        '/ai_callback_consumer_harness/status',
        type='http', auth='public', methods=['POST'], csrf=False,
        save_session=False,
    )
    def status(self):
        _require_loopback()
        body = http.request.httprequest.get_json(silent=True) or {}
        session_id = body.get('session_id')
        if not isinstance(session_id, int):
            raise NotFound()
        session = http.request.env['ai.session'].sudo().browse(session_id).exists()
        if not session:
            raise NotFound()
        requests = http.request.env['ai.session.request'].sudo().search([
            ('session_id', '=', session.id),
        ], order='id')
        request = requests[-1:]
        pending_tool_call = session.pending_tool_call or {}
        partners = http.request.env['res.partner'].sudo()
        return _json_response({
            'session_id': session.id,
            'request_uuid': request.request_uuid or False,
            'request_state': request.state or False,
            'request_uuids': requests.mapped('request_uuid'),
            'request_states': requests.mapped('state'),
            'round_nos': requests.mapped('round_no'),
            'response_state': request._get_response_state() if request else 'idle',
            'pending_call_id': pending_tool_call.get('call_id') or False,
            'resume_token': request.resume_token or False,
            'created_contact_count': partners.search_count([
                ('name', '=', 'Callback Harness Created'),
            ]),
            'before_update_count': partners.search_count([
                ('name', '=', 'Callback Harness Before Update'),
            ]),
            'after_update_count': partners.search_count([
                ('name', '=', 'Callback Harness After Update'),
            ]),
            'event_roles': [
                event.metadata.get('role')
                for event in session.event_ids.sorted('id')
            ],
            'messages': [{
                'id': message.id,
                'author_id': message.author_id.id,
                'body': str(message.body or ''),
                'attachment_count': len(message.attachment_ids),
            } for message in session.channel_id.message_ids.sorted('id')],
        })
