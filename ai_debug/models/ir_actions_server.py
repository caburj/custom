# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class IrActionsServer(models.Model):
    _inherit = "ir.actions.server"

    def _ai_tool_run(self, record, arguments, tools_context):
        parent_trace_id = tools_context.get('_debug_trace_id')
        if parent_trace_id:
            self = self.with_context(
                ai_parent_trace_id=parent_trace_id,
                ai_parent_tool_call_id=tools_context.get('tool_call_id'),
            )
        return super()._ai_tool_run(record, arguments, tools_context)
