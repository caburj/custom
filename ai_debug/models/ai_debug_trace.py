import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AiDebugTrace(models.Model):
    _name = 'ai.debug.trace'
    _description = 'AI Debug Trace'
    _order = 'create_date desc, id desc'

    # Agent context (may be None for _get_direct_response calls)
    agent_id = fields.Many2one('ai.agent', string='Agent', ondelete='set null', index=True)
    llm_model = fields.Char(string='LLM Model', index=True)

    # System prompt + RAG (captured from _generate_next_response)
    instructions = fields.Text(string='System Instructions')
    rag_context = fields.Text(string='RAG Context')

    # Loop outcome
    state = fields.Selection([
        ('running', 'Running'),
        ('done', 'Done'),
        ('error', 'Error'),
        ('paused', 'Awaiting Confirmation'),
    ], string='State', default='running', index=True, required=True)
    termination_reason = fields.Char(string='Termination Reason')
    error_message = fields.Text(string='Error Message')

    # Timing
    start_time = fields.Datetime(string='Started', default=fields.Datetime.now)
    total_duration_ms = fields.Integer(string='Duration (ms)')
    iteration_count = fields.Integer(string='Iterations')

    iteration_ids = fields.One2many('ai.debug.iteration', 'trace_id', string='Iterations')

    @api.autovacuum
    def _gc_ai_debug_traces(self):
        retention_days = int(
            self.env["ir.config_parameter"].sudo().get_param("ai_debugger.retention_days", "7")
        )
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=retention_days)
        self.search([('create_date', '<=', cutoff)]).unlink()
