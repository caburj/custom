import json
import os

from werkzeug.exceptions import NotFound
from werkzeug.wrappers import Response

from odoo import SUPERUSER_ID, api, http


IAP_ENDPOINT = os.environ.get(
    'AI_DEBUG_CALLBACK_IAP_ENDPOINT',
    'http://127.0.0.1:18170',
)


def _require_loopback():
    if http.request.httprequest.remote_addr not in ('127.0.0.1', '::1'):
        raise NotFound()


def _json_response(payload):
    return Response(json.dumps(payload), content_type='application/json')


class AiDebugCallbackConsumerHarness(http.Controller):
    @http.route(
        '/ai_debug_callback_consumer_harness/setup',
        type='http', auth='public', methods=['POST'], csrf=False,
        save_session=False,
    )
    def setup(self):
        _require_loopback()
        body = http.request.httprequest.get_json(silent=True) or {}
        if body.get('iap_endpoint') != IAP_ENDPOINT:
            raise NotFound()

        env = api.Environment(http.request.env.cr, SUPERUSER_ID, {})
        parameters = env['ir.config_parameter'].sudo()
        parameters.set_str('ai.endpoint', IAP_ENDPOINT)
        service = env.ref('ai.iap_service_odoo_ai')
        account = env['iap.account'].sudo().search([
            ('service_id', '=', service.id),
            ('company_ids', '=', False),
        ], limit=1)
        if not account:
            account = env['iap.account'].sudo().create({'service_id': service.id})
        if body.get('use_linked_account'):
            if not account.account_token:
                raise NotFound()
        else:
            account.with_context(disable_iap_update=True).write({
                'account_token': 'ai-debug-callback-harness-fixture',
            })
        agent = env['ai.agent'].create({
            'name': 'AI Debug Paired Callback Agent',
            'system_prompt': 'Answer the user plainly.',
        })
        channel = agent._create_ai_chat_channel('AI Debug Paired Callback')
        session = env['ai.session'].sudo().create({
            'agent_id': agent.id,
            'channel_id': channel.id,
        })
        message = channel.message_post(body='Hi', message_type='comment')
        return _json_response({
            'database_uuid': parameters.get_str('database.uuid'),
            'channel_id': channel.id,
            'session_id': session.id,
            'message_id': message.id,
        })

    @http.route(
        '/ai_debug_callback_consumer_harness/csrf',
        type='http', auth='user', methods=['GET'], save_session=False,
    )
    def csrf(self):
        _require_loopback()
        return _json_response({'csrf_token': http.request.csrf_token()})

    @http.route(
        '/ai_debug_callback_consumer_harness/status',
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
        return _json_response({
            'session_id': session.id,
            'request_uuid': session.request_uuid or False,
            'loop_state': session.loop_state,
            'request_phase': session.request_phase or False,
            'response_state': session._get_response_state(),
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
