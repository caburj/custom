from odoo import fields, models


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
