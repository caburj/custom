from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.utils import ensure_db, is_user_internal


class AiDebugController(http.Controller):

    @http.route('/ai-debug', type='http', auth='user', readonly=True)
    def ai_debug(self, **kw):
        ensure_db()
        if not is_user_internal(request.session.uid):
            return request.redirect('/web/login', 303)
        session_info = request.env['ir.http'].session_info()
        return request.render('ai_debug.index', {
            'session_info': session_info,
        })
