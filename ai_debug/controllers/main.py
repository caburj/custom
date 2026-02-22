from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.utils import is_user_internal


class AiDebugController(http.Controller):

    @http.route('/ai-debug', type='http', auth='user', readonly=True)
    def ai_debug(self, **kw):
        if not is_user_internal(request.session.uid):
            return request.redirect('/web/login', 303)
        context = request.env['ir.http'].webclient_rendering_context()
        return request.render('ai_debug.index', context)
