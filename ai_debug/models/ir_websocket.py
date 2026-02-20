from odoo import models


class IrWebsocket(models.AbstractModel):
    """IrWebsocket override for ai_debug channel security.

    Prevents non-system users from subscribing to ai_debug:trace: bus channels.
    Follows the spreadsheet_edition pattern — system users retain full access,
    all other users have ai_debug channels stripped from the subscription list.
    """

    _inherit = 'ir.websocket'

    def _build_bus_channel_list(self, channels):
        channels = list(channels)
        if not self.env.user.has_group('base.group_system'):
            channels = [
                ch for ch in channels
                if not (isinstance(ch, str) and ch.startswith('ai_debug:trace:'))
            ]
        return super()._build_bus_channel_list(channels)
