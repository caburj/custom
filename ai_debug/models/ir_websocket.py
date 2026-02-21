from odoo import models


class IrWebsocket(models.AbstractModel):
    """Gate the ai_debug bus channel to internal users only."""

    _inherit = 'ir.websocket'

    def _build_bus_channel_list(self, channels):
        channels = list(channels)
        if not self.env.user._is_internal():
            channels = [
                ch for ch in channels
                if not (isinstance(ch, str) and ch == 'ai_debug')
            ]
        return super()._build_bus_channel_list(channels)
