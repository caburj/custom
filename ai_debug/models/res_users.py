# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    # Per-user toggle exposed in the /ai-debug header. When True, the
    # ai_debug override of ir.actions.server._ai_tool_run pre-flips
    # tools_context['tool_request_confirmed'] so destructive AI tools
    # (update/create previews, custom server-action tools that gate on
    # the same flag) skip their preview block and execute in the same
    # iteration -- no second turn, no confirmation chip.
    ai_debug_bypass_confirmation = fields.Boolean(
        string="AI Debug: bypass tool confirmation",
        default=False,
    )

    @api.model
    def get_ai_debug_bypass_confirmation(self):
        return self.env.user.sudo().ai_debug_bypass_confirmation

    @api.model
    def set_ai_debug_bypass_confirmation(self, value):
        self.env.user.sudo().write({
            "ai_debug_bypass_confirmation": bool(value),
        })
        return bool(value)
