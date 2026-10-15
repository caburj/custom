from odoo import api, fields, models


class AiSessionEvent(models.Model):
    _inherit = 'ai.session.event'

    exchange_id = fields.Many2one(
        'ai.debug.exchange', readonly=True, ondelete='set null', index='btree_not_null',
    )
    request_uuid = fields.Char(readonly=True)
    request_round = fields.Integer(readonly=True)
    usage = fields.Json(
        readonly=True,
        help="Completion token usage and its reported cost in IAP credits. "
        "Empty for events without recorded usage.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        events = super().create(vals_list)
        for session, session_events in events.grouped('ai_session_id').items():
            session_events.exchange_id = session.current_exchange_id
        return events
