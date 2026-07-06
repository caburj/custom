# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class AiDebugIteration(models.Model):
    _name = 'ai.debug.iteration'
    _description = 'AI Debug Iteration'
    _order = 'loop_id, sequence'

    loop_id = fields.Many2one('ai.debug.loop', required=True, ondelete='cascade')
    sequence = fields.Integer()
    is_running = fields.Boolean(default=False)
    # Augmented system prompt actually sent to the provider for this iteration:
    # the base instructions arg passed into _advance_one_step with
    # <loaded_skills>...</loaded_skills> appended by
    # ai.session._append_loaded_skills. Captured per-iteration because
    # load_skills can mutate tools_context["state"]["loaded_skills"] mid-loop,
    # so the prompt differs between iterations of the same loop.
    instructions = fields.Text()
    # Messages this iteration appended to the running history. Kept for the
    # confirmation-followup heuristic and as a reconstruction fallback for
    # rows without messages_sent.
    messages_delta = fields.Json()
    # The complete provider-format messages list actually sent to the LLM this
    # iteration (binary-stripped), extracted from the captured request body --
    # ground truth, not a client-side reconstruction.
    messages_sent = fields.Json()
    # The full request envelope POSTed to the provider API this iteration
    # (binary-stripped): model, messages, tools, generation config / system
    # instruction. Superset of messages_sent.
    raw_request = fields.Json()
    # The provider HTTP response payload (parsed JSON the API returned).
    raw_response = fields.Json()
    output_message = fields.Text()
    tokens_in = fields.Integer()
    tokens_cached = fields.Integer()
    tokens_out = fields.Integer()
    duration_ms = fields.Integer()
    tool_call_ids = fields.One2many('ai.debug.tool.call', 'iteration_id')
    tool_call_count = fields.Integer(compute='_compute_tool_call_count', store=True)
    available_tool_ids = fields.Many2many(
        'ir.actions.server',
        'ai_debug_iteration_tool_rel',
        'iteration_id',
        'tool_id',
    )

    @api.depends('tool_call_ids')
    def _compute_tool_call_count(self):
        for iteration in self:
            iteration.tool_call_count = len(iteration.tool_call_ids)
