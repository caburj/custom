from odoo import http
from odoo.http import request


class AiDebugController(http.Controller):

    @http.route('/ai-debug', type='http', auth='user')
    def debug_client(self, **kwargs):
        session_info = request.env['ir.http'].session_info()
        session_info['db'] = request.db
        return request.render('ai_debug.layout', {
            'session_info': session_info,
        })
