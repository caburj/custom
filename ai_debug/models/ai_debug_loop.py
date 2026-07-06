# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.addons.ai.utils.ai_utils import markdown_format


class AiDebugLoop(models.Model):
    _name = 'ai.debug.loop'
    _description = 'AI Debug Loop'
    _order = 'id desc'

    thread_id = fields.Many2one('ai.debug.thread', required=True, ondelete='cascade')
    agent_id = fields.Many2one('ai.agent', related='thread_id.agent_id', store=True)
    # The parent tool call that triggered this loop (only for child threads):
    # ``start_session`` for the very first loop, ``continue_session`` for each
    # follow-up. Null for root-thread loops and for the synthetic confirmation
    # follow-up loop. The link lives on the loop -- not the thread -- because a
    # subagent session is reused across many tool calls in the parent thread.
    parent_tool_call_id = fields.Many2one(
        'ai.debug.tool.call', ondelete='set null', index=True,
    )
    model_name = fields.Char()
    input_message = fields.Text()
    # Display-only HTML rendering of input_message. Mirrors what
    # markdown_format does for output_message so subagent threads (where
    # input_message is the parent agent's markdown prompt) render with
    # paragraphs/lists/tables instead of collapsing into a wall of text.
    # Not stored: debug_transcript() and other Python consumers keep
    # reading plain text from input_message.
    input_message_html = fields.Html(compute='_compute_input_message_html', sanitize=False)
    output_message = fields.Text()
    is_running = fields.Boolean(default=False)
    termination_reason = fields.Selection([
        ('success', 'Success'),
        ('max_iterations', 'Max Iterations'),
        ('confirmation', 'Confirmation'),
        ('error', 'Error'),
        # A turn paused awaiting subagents defers its loop finalize; if the user
        # then refuses with free text, that turn is folded and a NEW root turn
        # begins on the same session. The still-running loop never reached a
        # terminal answer, so it is closed as 'superseded' (see ai_session.py
        # _ai_debug_supersede_stale_loop) and the refusal opens its own loop.
        ('superseded', 'Superseded'),
        # A cancel/Stop terminates the session at the TOP of the tick, before
        # _advance_one_step runs, so the loop's own finally never finalizes it.
        # ai_debug closes the still-running loop here so the viewer's spinner
        # stops and the loop reads 'cancelled' (see ai_session.py
        # _consume_cancel_signal / _ai_debug_close_cancelled_loop).
        ('cancelled', 'Cancelled'),
    ])
    error_message = fields.Text()
    start_time = fields.Datetime()
    duration_ms = fields.Integer()
    tokens_in = fields.Integer(compute='_compute_tokens', store=True)
    tokens_cached = fields.Integer(compute='_compute_tokens', store=True)
    tokens_out = fields.Integer(compute='_compute_tokens', store=True)
    iteration_ids = fields.One2many('ai.debug.iteration', 'loop_id')
    iteration_count = fields.Integer(compute='_compute_iteration_count', store=True)

    @api.depends('iteration_ids.tokens_in', 'iteration_ids.tokens_cached', 'iteration_ids.tokens_out')
    def _compute_tokens(self):
        for loop in self:
            loop.tokens_in = sum(loop.iteration_ids.mapped('tokens_in'))
            loop.tokens_cached = sum(loop.iteration_ids.mapped('tokens_cached'))
            loop.tokens_out = sum(loop.iteration_ids.mapped('tokens_out'))

    @api.depends('iteration_ids')
    def _compute_iteration_count(self):
        for loop in self:
            loop.iteration_count = len(loop.iteration_ids)

    @api.depends('input_message')
    def _compute_input_message_html(self):
        for loop in self:
            if not loop.input_message:
                loop.input_message_html = False
                continue
            try:
                loop.input_message_html = markdown_format(loop.input_message)
            except Exception:
                loop.input_message_html = loop.input_message
