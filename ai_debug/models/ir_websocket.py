from odoo import models


class IrWebsocket(models.AbstractModel):
    """Expose only the current internal user's private debugger channel."""

    _inherit = 'ir.websocket'

    def _build_bus_channel_list(self, channels):
        channels = [
            channel for channel in channels
            if not (isinstance(channel, str) and channel == 'ai_debug')
        ]
        channels = super()._build_bus_channel_list(channels)
        if self.env.user._is_internal():
            channels.append((self.env.user, 'ai_debug'))
        return channels
