# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class AiDebugToolCall(models.Model):
    _name = 'ai.debug.tool.call'
    _description = 'AI Debug Tool Call'
    _order = 'iteration_id, id'

    iteration_id = fields.Many2one('ai.debug.iteration', required=True, ondelete='cascade')
    tool_id = fields.Many2one('ir.actions.server')
    call_id = fields.Char()
    name = fields.Char()
    arguments = fields.Json()
    result = fields.Text()
    duration_ms = fields.Integer()
    triggered_confirmation = fields.Boolean(default=False)
    confirmation_message = fields.Text()
    # Set (data-driven, never by row position) when this call was refused: either
    # a confirmation call the user declined, or a spawn/ask call resolved by a
    # superseded fold (the user redirected away from the turn). Persisted at fold
    # time from the call_ids the fold closes (see ai_session.py
    # _on_tool_calls_refused / _ai_debug_update_confirmation_tool_results).
    refused = fields.Boolean(default=False)
    # Loops triggered by this tool call (typically zero or one per call):
    # start_session links the very first loop of a child thread, continue_session
    # links a follow-up loop on the same child thread.
    child_loop_ids = fields.One2many(
        'ai.debug.loop', 'parent_tool_call_id',
    )
