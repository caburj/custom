from odoo import api, models


class AiSessionRequest(models.Model):
    _inherit = 'ai.session.request'

    @api.model_create_multi
    def create(self, vals_list):
        requests = super().create(vals_list)
        for request in requests:
            if request.round_no != 1:
                continue
            request.session_id._ai_debug_try(
                lambda request=request: request.session_id._ai_debug_trace_request_prepared(request)
            )
        return requests
