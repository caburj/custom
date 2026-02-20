import json

from odoo import api, fields, models


class AiDebugToolCall(models.Model):
    _name = 'ai.debug.tool.call'
    _description = 'AI Debug Tool Call'
    _order = 'id asc'

    iteration_id = fields.Many2one('ai.debug.iteration', string='Iteration', required=True,
                                   ondelete='cascade', index=True)

    # Tool identity
    tool_name = fields.Char(string='Tool Name', index=True)
    call_id = fields.Char(string='Call ID')

    # Payload (Json = JSONB, verbatim)
    args = fields.Json(string='Arguments')
    result = fields.Text(string='Result')  # Text, not Json — result may be plain string
    success = fields.Boolean(string='Success', default=True)

    # Confirmation
    triggered_confirmation = fields.Boolean(string='Required Confirmation')
    confirmation_message = fields.Text(string='Confirmation Message')

    # State snapshots per tool call (locked decision)
    state_before = fields.Json(string='State Before')
    state_after = fields.Json(string='State After')

    # Timing
    duration_ms = fields.Integer(string='Duration (ms)')

    # Computed display fields
    duration_human = fields.Char(string='Duration', compute='_compute_duration_human')
    args_pretty = fields.Text(compute='_compute_args_pretty')
    state_before_pretty = fields.Text(compute='_compute_state_pretty')
    state_after_pretty = fields.Text(compute='_compute_state_pretty')

    @api.depends('duration_ms')
    def _compute_duration_human(self):
        for record in self:
            ms = record.duration_ms or 0
            if ms < 1000:
                record.duration_human = f'{ms}ms'
            elif ms < 60000:
                record.duration_human = f'{ms / 1000:.1f}s'
            else:
                minutes = ms // 60000
                seconds = (ms % 60000) // 1000
                record.duration_human = f'{minutes}m {seconds}s'

    @api.depends('args')
    def _compute_args_pretty(self):
        for record in self:
            record.args_pretty = (
                json.dumps(record.args, indent=2, ensure_ascii=False)
                if record.args else ''
            )

    @api.depends('state_before', 'state_after')
    def _compute_state_pretty(self):
        for record in self:
            record.state_before_pretty = (
                json.dumps(record.state_before, indent=2, ensure_ascii=False)
                if record.state_before else ''
            )
            record.state_after_pretty = (
                json.dumps(record.state_after, indent=2, ensure_ascii=False)
                if record.state_after else ''
            )
