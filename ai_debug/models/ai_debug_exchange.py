import uuid

from odoo import api, fields, models


class AiDebugExchange(models.Model):
    _name = 'ai.debug.exchange'
    _description = 'AI Debug Exchange'
    _rec_name = 'uuid'
    _order = 'id desc'

    session_id = fields.Many2one(
        'ai.session', required=True, ondelete='cascade', index=True,
    )
    uuid = fields.Char(required=True, default=lambda self: uuid.uuid4().hex)
    parent_exchange_id = fields.Many2one(
        'ai.debug.exchange', ondelete='cascade', index='btree_not_null',
    )
    child_exchange_ids = fields.One2many('ai.debug.exchange', 'parent_exchange_id')
    event_ids = fields.One2many('ai.session.event', 'exchange_id')
    state = fields.Selection(
        [
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('declined', 'Declined'),
            ('failed', 'Failed'),
            ('superseded', 'Superseded'),
        ],
        required=True,
        default='running',
    )
    started_at = fields.Datetime(required=True, default=fields.Datetime.now)
    finished_at = fields.Datetime()
    credits_used = fields.Float(
        compute='_compute_credits_used',
        help="Recorded IAP credits for this exchange's own agent-loop completions.",
    )
    total_credits_used = fields.Float(
        compute='_compute_total_credits_used',
        recursive=True,
        help="Recorded IAP credits for this exchange and all its delegated exchanges.",
    )

    _uuid_unique = models.UniqueIndex('(uuid)', 'The exchange UUID must be unique.')

    @api.depends('event_ids.usage')
    def _compute_credits_used(self):
        for exchange in self:
            exchange.credits_used = sum(
                usage['cost'] for usage in exchange.event_ids.mapped('usage') if usage
            )

    @api.depends('credits_used', 'child_exchange_ids.total_credits_used')
    def _compute_total_credits_used(self):
        for exchange in self:
            exchange.total_credits_used = exchange.credits_used + sum(
                exchange.child_exchange_ids.mapped('total_credits_used'),
            )
