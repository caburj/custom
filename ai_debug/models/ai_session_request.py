import copy
import logging
import uuid

from odoo import api, models


_AI_DEBUG_EXCHANGE_UUID_CONTEXT_KEY = 'ai_debug_exchange_uuid'
_logger = logging.getLogger(__name__)


class AiSessionRequest(models.Model):
    _inherit = 'ai.session.request'

    @staticmethod
    def _ai_debug_prepare_create_vals(vals):
        """Copy and correlate only explicit dictionary context snapshots."""
        raw_context_snapshot = vals.get('context_snapshot')
        if not isinstance(raw_context_snapshot, dict):
            return vals
        prepared_vals = dict(vals)
        context_snapshot = copy.deepcopy(raw_context_snapshot)
        exchange_uuid = context_snapshot.get(
            _AI_DEBUG_EXCHANGE_UUID_CONTEXT_KEY
        )
        if not isinstance(exchange_uuid, str) or not exchange_uuid:
            context_snapshot[_AI_DEBUG_EXCHANGE_UUID_CONTEXT_KEY] = uuid.uuid4().hex
        prepared_vals['context_snapshot'] = context_snapshot
        return prepared_vals

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for vals in vals_list:
            try:
                prepared_vals = self._ai_debug_prepare_create_vals(vals)
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "ai_debug: failed to inject callback exchange correlation"
                )
                prepared_vals = vals
            prepared_vals_list.append(prepared_vals)

        requests = super().create(prepared_vals_list)
        for request in requests:
            if request.round_no != 1:
                continue
            request.session_id._ai_debug_try(
                lambda request=request: request.session_id._ai_debug_trace_request_prepared(request)
            )
        return requests
