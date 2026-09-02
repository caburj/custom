import json

from werkzeug.exceptions import NotFound
from werkzeug.wrappers import Response

from odoo import http


def _require_loopback():
    if http.request.httprequest.remote_addr not in ('127.0.0.1', '::1'):
        raise NotFound()


def _json_response(payload):
    return Response(json.dumps(payload), content_type='application/json')


class OdooAICallbackHarness(http.Controller):
    @http.route(
        '/odoo_ai_callback_harness/ready',
        type='http', auth='public', methods=['GET'], save_session=False,
    )
    def ready(self):
        _require_loopback()
        from odoo.addons.odoo_ai import ai_broker, ai_service

        broker = ai_broker._ai_brokers.get(http.request.db)
        return _json_response({
            'broker_alive': bool(broker and broker.started and not broker.stopped),
            'provider_patched': (
                ai_service.get_completions.__module__
                == 'odoo.addons.odoo_ai_callback_harness.provider'
            ),
        })

    @http.route(
        '/odoo_ai_callback_harness/setup',
        type='http', auth='public', methods=['POST'], csrf=False,
        save_session=False,
    )
    def setup(self):
        _require_loopback()
        env = http.request.env
        env['ir.config_parameter'].sudo().set_bool('odoo_ai.use_credits', False)
        env['odoo_ai.step'].sudo().search([]).unlink()
        return _json_response({'ready': True})

    @http.route(
        '/odoo_ai_callback_harness/status',
        type='http', auth='public', methods=['POST'], csrf=False,
        save_session=False,
    )
    def status(self):
        _require_loopback()
        body = http.request.httprequest.get_json(silent=True) or {}
        if body.get('all') is True:
            requests = http.request.env['odoo_ai.step'].sudo().search(
                [], order='id',
            )
            return _json_response({
                'requests': [{
                    'request_uuid': request.request_uuid,
                    'state': request.state,
                    'webhook_url': request.webhook_url,
                    'llm_result': request.llm_result or False,
                    'llm_error': request.llm_error or False,
                    'odoo_error': request.odoo_error or False,
                    'odoo_retry_count': request.odoo_retry_count,
                } for request in requests],
            })
        request_uuid = body.get('request_uuid')
        request = http.request.env['odoo_ai.step'].sudo().search([
            ('request_uuid', '=', request_uuid),
        ], limit=1)
        if not request:
            return _json_response({'known': False})
        return _json_response({
            'known': True,
            'request_uuid': request.request_uuid,
            'state': request.state,
            'webhook_url': request.webhook_url,
            'llm_result': request.llm_result or False,
            'llm_error': request.llm_error or False,
            'odoo_error': request.odoo_error or False,
            'odoo_retry_count': request.odoo_retry_count,
        })
