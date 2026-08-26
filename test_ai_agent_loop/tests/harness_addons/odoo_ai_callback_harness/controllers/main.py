import json
from datetime import timedelta

from werkzeug.exceptions import NotFound
from werkzeug.wrappers import Response

from odoo import fields, http


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
        from odoo.addons.odoo_ai import dispatcher

        runner = dispatcher.PROCESS_DISPATCHER.runner
        return _json_response({
            'dispatcher_alive': bool(runner and not runner.dead),
            'provider_patched': (
                dispatcher.run_completion.__module__
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
        body = http.request.httprequest.get_json(silent=True) or {}
        database_uuid = body.get('database_uuid')
        callback_url = body.get('callback_url')
        if not database_uuid or callback_url != 'http://127.0.0.1:18281':
            raise NotFound()
        env = http.request.env
        env['ir.config_parameter'].sudo().set_bool('odoo_ai.use_credits', False)
        Database = env['iap_tools.database'].sudo()
        Database.search([('db_uuid', '=', database_uuid)]).unlink()
        Database.create({
            'db_uuid': database_uuid,
            'db_name': 'ai_callback_consumer_test',
            'url': callback_url,
            'expiration_date': fields.Datetime.now() + timedelta(days=1),
        })
        env['odoo_ai.completion.request'].sudo().search([]).unlink()
        return _json_response({'database_uuid': database_uuid, 'ready': True})

    @http.route(
        '/odoo_ai_callback_harness/status',
        type='http', auth='public', methods=['POST'], csrf=False,
        save_session=False,
    )
    def status(self):
        _require_loopback()
        body = http.request.httprequest.get_json(silent=True) or {}
        request_uuid = body.get('request_uuid')
        request = http.request.env['odoo_ai.completion.request'].sudo().search([
            ('request_uuid', '=', request_uuid),
        ], limit=1)
        if not request:
            return _json_response({'known': False})
        return _json_response({
            'known': True,
            'request_uuid': request.request_uuid,
            'state': request.state,
            'callback_state': request.callback_state,
            'callback_attempts': request.callback_attempts,
            'error': request.error or False,
        })
