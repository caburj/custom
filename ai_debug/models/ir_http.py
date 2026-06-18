# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        # Surface the per-user bypass flag so the user-menu switch can
        # render with the right initial state on the very first open --
        # no extra ORM round trip on every page load.
        result = super().session_info()
        try:
            result["ai_debug_bypass_confirmation"] = bool(
                self.env.user.sudo().ai_debug_bypass_confirmation
            )
        except Exception:  # noqa: BLE001
            # Public/portal user, or schema not yet migrated. Default off.
            result["ai_debug_bypass_confirmation"] = False
        return result
