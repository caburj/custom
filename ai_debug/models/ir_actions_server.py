# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models

from odoo.addons.ai.models.ai_session import make_tool_name
from odoo.addons.ai_debug.models.agent_runtime_tracker import ai_debug_tracker


class IrActionsServer(models.Model):
    _inherit = "ir.actions.server"

    llm_name = fields.Char(compute='_compute_llm_name')

    @api.depends('name')
    def _compute_llm_name(self):
        for action in self:
            action.llm_name = make_tool_name(action) or ''

    def _ai_tool_run(self, record, arguments, tools_context):
        """Track the currently-executing tool call on the shared tracker so that any
        nested _run_agentic_loop invocations (e.g. generate_image or
        start_session) can link their synthetic thread to the ai.debug.tool.call
        row that spawned them.

        The outer _handle_tool_calls has already created the row and committed
        it on the same debug_env we read here, so a same-cursor lookup by
        call_id always hits.

        Also forces ``tool_request_confirmed`` to True when the current user
        has the per-user "bypass tool confirmation" toggle enabled (the
        switch in the backend user menu). Tools (e.g. _tool_update_records,
        _tool_create_records, custom server-action tools) gate their write
        side-effects on this flag, so flipping it here makes them execute in
        the same iteration without surfacing a confirmation prompt.
        """
        debug_env = ai_debug_tracker.debug_env
        call_id = tools_context.get('tool_call_id')
        previous = ai_debug_tracker.current_tool_call_db_id
        if debug_env and call_id:
            tc_record = debug_env['ai.debug.tool.call'].sudo().search(
                [('call_id', '=', call_id)], limit=1,
            )
            if tc_record:
                ai_debug_tracker.current_tool_call_db_id = tc_record.id
        try:
            if self.env.user.sudo().ai_debug_bypass_confirmation:
                tools_context['tool_request_confirmed'] = True
        except Exception:  # noqa: BLE001
            # Debug overrides must never crash the core ai methods.
            pass
        try:
            result = super()._ai_tool_run(record, arguments, tools_context)
        except Exception:
            ai_debug_tracker.current_tool_call_db_id = previous
            raise
        ai_debug_tracker.current_tool_call_db_id = previous
        return result
