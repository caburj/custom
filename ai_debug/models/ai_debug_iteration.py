from odoo import fields, models


class AiDebugIteration(models.Model):
    _name = 'ai.debug.iteration'
    _description = 'AI Debug Iteration'
    _order = 'index asc'

    trace_id = fields.Many2one('ai.debug.trace', string='Trace', required=True,
                               ondelete='cascade', index=True)
    index = fields.Integer(string='Index', required=True)  # 0-based iteration number

    # Full LLM input/output (Json = JSONB, verbatim, no truncation)
    messages_sent = fields.Json(string='Messages Sent')
    raw_response = fields.Json(string='Raw Provider Response')

    # State snapshots at iteration level
    state_before = fields.Json(string='State Before')
    state_after = fields.Json(string='State After')

    # Termination
    final_message = fields.Json(string='Final Message')

    # Timing
    duration_ms = fields.Integer(string='Duration (ms)')

    tool_call_ids = fields.One2many('ai.debug.tool.call', 'iteration_id', string='Tool Calls')
