import json

from odoo import api, fields, models


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

    # Computed display fields
    duration_human = fields.Char(string='Duration', compute='_compute_duration_human')
    tool_call_count = fields.Integer(string='Tool Call Count', compute='_compute_tool_call_count')
    messages_sent_pretty = fields.Text(compute='_compute_messages_sent_pretty')
    raw_response_pretty = fields.Text(compute='_compute_raw_response_pretty')
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

    @api.depends('tool_call_ids')
    def _compute_tool_call_count(self):
        for record in self:
            record.tool_call_count = len(record.tool_call_ids)

    @api.depends('messages_sent')
    def _compute_messages_sent_pretty(self):
        for record in self:
            record.messages_sent_pretty = (
                json.dumps(record.messages_sent, indent=2, ensure_ascii=False)
                if record.messages_sent else ''
            )

    @api.depends('raw_response')
    def _compute_raw_response_pretty(self):
        for record in self:
            record.raw_response_pretty = (
                json.dumps(record.raw_response, indent=2, ensure_ascii=False)
                if record.raw_response else ''
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
