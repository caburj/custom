import copy
from contextlib import contextmanager
import json
import logging
import math
import time
import uuid

import odoo
from odoo import api, models
from odoo.addons.bus.models.bus import (
    ODOO_NOTIFY_FUNCTION,
    channel_with_db,
    get_notify_payloads,
)
from odoo.addons.bus.tools.notifications import json_dump
from odoo.exceptions import UserError
from odoo.tools import SQL, config, html2plaintext
from odoo.tools.misc import OrderedSet

_logger = logging.getLogger(__name__)

_PRECOMMIT_BUS_ROWS_KEY = "ai_debug.bus_rows"
_POSTCOMMIT_BUS_CHANNELS_KEY = "ai_debug.bus_channels"
_MAX_COLLECTION_ITEMS = 100
_MAX_DEPTH = 12
_MAX_EVENT_BYTES = 512_000
_MAX_IMAGE_DATA_BYTES = 48_000
_MAX_STRING_CHARS = 64_000
_REDACTED = "[REDACTED]"
_AI_DEBUG_EXCHANGE_UUID_CONTEXT_KEY = 'ai_debug_exchange_uuid'
_AI_DEBUG_ROUND_START_CONTEXT_KEY = '_ai_debug_round_started_at_ms'
_AI_DEBUG_TOOL_TIMINGS_CONTEXT_KEY = '_ai_debug_tool_timings'
_AI_DEBUG_CALLBACK_CONTEXT_KEY = '_ai_debug_callback_ctx'
_AI_DEBUG_STORE_CONTEXT_KEY = '_ai_debug_store_ctx'
_AI_DEBUG_DIRECT_TRACE_CONTEXT_KEY = '_ai_debug_direct_trace'
_SAFE_IAP_ERROR_CODES = frozenset({'insufficient_credit', 'request_failed'})
_ALLOWED_IMAGE_MIMETYPES = frozenset({
    'image/gif',
    'image/jpeg',
    'image/png',
    'image/webp',
})
_NORMALIZED_COMPLETION_OPTION_KEYS = (
    'schema',
    'web_grounding',
    'aspect_ratio',
    'timeout',
    'resolve_web_sources',
    'usage',
    'image_generation',
)
_SENSITIVE_KEYS = {
    "access_token",
    "account_token",
    "api_key",
    "authorization",
    "connection",
    "cookie",
    "cookies",
    "csrf_token",
    "database_uuid",
    "dbuuid",
    "encrypted_content",
    "header",
    "headers",
    "password",
    "provider_data",
    "refresh_token",
    "resume_token",
    "secret",
    "webhook_secret",
    "signature",
    "set_cookie",
    "thought_signature",
}
_SENSITIVE_KEY_NAMES = frozenset(key.replace('_', '') for key in _SENSITIVE_KEYS)


class AiSession(models.Model):
    _inherit = 'ai.session'

    def _ai_debug_bus_send(
        self, notification_type, payload, *, target_user_id=None,
    ):
        """Publish sanitized facts only after the enclosing transaction commits.

        The Bus row is inserted in the current transaction, so both full and
        savepoint rollbacks remove it.  Only the lightweight PostgreSQL wake-up
        remains post-commit; a stale wake-up has no row to deliver.  Payload
        building and Bus writes run in a savepoint so debugger failures cannot
        poison the business transaction. Events are private to the originating
        internal user; public/portal/guest actors are deliberately not traced.
        """
        try:
            with self.env.cr.savepoint(flush=False):
                target_user = (
                    self.env['res.users'].sudo()
                    .browse(target_user_id or self.env.uid)
                    .exists()
                )
                if target_user and target_user._is_internal():
                    channel_target = (target_user, 'ai_debug')
                    revalidate_user_id = target_user.id
                else:
                    return False
                sanitized_payload = self._ai_debug_sanitize(payload)
                encoded = json.dumps(sanitized_payload, ensure_ascii=False, separators=(",", ":"))
                if len(encoded.encode()) > _MAX_EVENT_BYTES:
                    correlation_keys = (
                        'type', 'trace_id', 'exchange_uuid', 'request_uuid',
                        'round_no', 'iteration_id', 'iteration_index',
                        'session_id', 'request_state', 'is_final', 'error', 'duration_ms',
                        'duration_kind', 'termination_reason', 'iteration_count',
                        'tool_call_count', 'provider', 'model_name', 'provider_api',
                        'trace_kind', 'trace_label', 'phase', 'state', 'request_phase',
                        'parent_trace_id', 'parent_session_id', 'parent_request_uuid',
                        'parent_tool_call_id', 'tool_call_id', 'call_id', 'tool_name',
                        'status', 'success', 'child_session_id', 'child_request_uuid',
                    )
                    sanitized_payload = {
                        key: self._ai_debug_sanitize(payload[key], key=key)
                        for key in correlation_keys
                        if key in payload
                    }
                    sanitized_payload.setdefault('type', notification_type)
                    sanitized_payload['_payload_excluded'] = True

                postcommit = self.env.cr.postcommit
                channels = postcommit.data.get(_POSTCOMMIT_BUS_CHANNELS_KEY)
                if channels is None:
                    channels = postcommit.data[_POSTCOMMIT_BUS_CHANNELS_KEY] = OrderedSet()

                    @postcommit.add
                    def notify_ai_debug_channels():
                        queued = postcommit.data.pop(_POSTCOMMIT_BUS_CHANNELS_KEY, OrderedSet())
                        try:
                            payloads = get_notify_payloads(list(queued))
                            with odoo.sql_db.db_connect(config['db_system']).cursor() as cr:
                                for notify_payload in payloads:
                                    cr.execute(SQL(
                                        "SELECT %s('imbus', %s)",
                                        SQL.identifier(ODOO_NOTIFY_FUNCTION),
                                        notify_payload,
                                    ))
                        except Exception:
                            _logger.exception(
                                "ai_debug: failed to wake Bus after committed events"
                            )

                precommit = self.env.cr.precommit
                rows = precommit.data.get(_PRECOMMIT_BUS_ROWS_KEY)
                if rows is None:
                    rows = precommit.data[_PRECOMMIT_BUS_ROWS_KEY] = []

                    @precommit.add
                    def revalidate_ai_debug_targets():
                        queued = precommit.data.pop(_PRECOMMIT_BUS_ROWS_KEY, [])
                        for bus_id, user_id in queued:
                            try:
                                with self.env.cr.savepoint(flush=False):
                                    user = self.env['res.users'].sudo().browse(user_id).exists()
                                    if not user or not user._is_internal():
                                        self.env['bus.bus'].sudo().browse(bus_id).unlink()
                            except Exception:
                                _logger.exception(
                                    "ai_debug: failed to revalidate Bus target; dropping event"
                                )
                                try:
                                    with self.env.cr.savepoint(flush=False):
                                        self.env['bus.bus'].sudo().browse(bus_id).unlink()
                                except Exception:
                                    _logger.exception(
                                        "ai_debug: failed to drop Bus event after target check"
                                    )

                bus = self.env['bus.bus'].sudo()
                message = json_dump({
                    'type': notification_type,
                    'payload': sanitized_payload,
                })
                channel = channel_with_db(self.env.cr.dbname, channel_target)
                bus_row = bus.create({
                    'channel': json_dump(channel),
                    'message': message,
                })
                channels.add(channel)
                if revalidate_user_id:
                    rows.append((bus_row.id, revalidate_user_id))
                return True
        except Exception:
            _logger.exception("ai_debug: failed to queue bus event '%s'", notification_type)
            return False

    @classmethod
    def _ai_debug_sanitize(cls, value, *, key=None, depth=0):
        """Return a bounded JSON value and redact credential-bearing keys."""
        normalized_key = ''.join(
            character for character in str(key or '').casefold()
            if character.isalnum()
        )
        if (
            normalized_key in _SENSITIVE_KEY_NAMES
            or normalized_key.endswith(('apikey', 'password', 'secret', 'token'))
        ):
            return _REDACTED
        if depth >= _MAX_DEPTH:
            return "[MAX_DEPTH]"
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else str(value)
        if isinstance(value, str):
            return value[:_MAX_STRING_CHARS]
        if isinstance(value, bytes):
            return {"_binary_excluded": True, "size": len(value)}
        if isinstance(value, dict):
            return {
                str(item_key): cls._ai_debug_sanitize(
                    item_value, key=item_key, depth=depth + 1,
                )
                for item_key, item_value in list(value.items())[:_MAX_COLLECTION_ITEMS]
            }
        if isinstance(value, (list, tuple)):
            return [
                cls._ai_debug_sanitize(item, depth=depth + 1)
                for item in value[:_MAX_COLLECTION_ITEMS]
            ]
        return "[UNSUPPORTED]"

    def _ai_debug_try(self, builder):
        """Preserve pending business writes and restore ORM state on observer failure."""
        # Flush business work before catching optional observer errors. A business
        # flush failure must reach the caller and its ordinary transaction retry.
        savepoint = self.env.cr.savepoint()
        try:
            with savepoint:
                return builder()
        except Exception:
            _logger.exception("ai_debug: instrumentation builder failed")
            return None

    def _ai_debug_state_snapshot(self, tools_context):
        """Return a JSON-safe snapshot of the current session environment and tool state."""
        return {
            'tool_state': copy.deepcopy(tools_context.get('state') or {}),
            'uid': self.env.uid,
            'company_id': self.env.company.id,
            'lang': self.env.lang,
            'res_model': tools_context.get('res_model'),
            'res_id': tools_context.get('res_id'),
            'channel_id': self.channel_id.id if self.channel_id else None,
            'agent_id': self.agent_id.id if self.agent_id else None,
            'agent_name': self.agent_id.name if self.agent_id else None,
            'llm_model': tools_context.get('llm_model'),
        }

    @staticmethod
    def _ai_debug_is_image_type(mime):
        return isinstance(mime, str) and mime.lower() in _ALLOWED_IMAGE_MIMETYPES

    @staticmethod
    def _ai_debug_image_data(mime, data):
        mime = mime.lower() if isinstance(mime, str) else ''
        if (
            mime not in _ALLOWED_IMAGE_MIMETYPES
            or not isinstance(data, str)
            or len(data.encode()) > _MAX_IMAGE_DATA_BYTES
        ):
            return {'mimeType': mime, '_binary_excluded': True}
        if data.startswith('data:'):
            prefix = f'data:{mime};base64,'
            if not data.lower().startswith(prefix):
                return {'mimeType': mime, '_binary_excluded': True}
            return {'mimeType': mime, 'data': data}
        return {'mimeType': mime, 'data': f'data:{mime};base64,{data}'}

    @staticmethod
    def _ai_debug_part_text(part):
        """Read current flat parts while tolerating the previous nested shape."""
        if not isinstance(part, dict):
            return None
        if 'text' in part:
            return part.get('text')
        content = part.get('content')
        return content.get('data') if isinstance(content, dict) else None

    @staticmethod
    def _ai_debug_part_inline_data(part):
        """Return one inline part's mimetype and data across both contracts."""
        if not isinstance(part, dict):
            return '', None
        content = part.get('content')
        if not isinstance(content, dict):
            content = {}
        mime = (
            part.get('mimetype')
            or part.get('mimeType')
            or part.get('mime_type')
            or content.get('mimetype')
            or content.get('mimeType')
            or content.get('mime_type')
            or ''
        )
        data = part.get('data') if 'data' in part else content.get('data')
        return mime, data

    def _ai_debug_strip_binary(self, messages):
        """Return a copy of messages with non-image binary content replaced by
        metadata stubs and image data normalized to data URIs.

        Images are preserved as data URIs so the frontend can render previews.
        Non-image files (PDFs, etc.) are replaced with lightweight stubs to
        avoid bloating bus payloads.
        """
        result = []
        for msg in messages:
            msg_copy = dict(msg)

            # Provider image generation result: retain only a bounded preview.
            if msg_copy.get('type') == 'image_generation_call' and 'result' in msg_copy:
                fmt = msg_copy.get('output_format', 'png')
                image = self._ai_debug_image_data(f'image/{fmt}', msg_copy['result'])
                msg_copy['result'] = image.get('data')
                if image.get('_binary_excluded'):
                    msg_copy.pop('result', None)
                    msg_copy['_binary_excluded'] = True

            # OpenAI format: content is a list of typed parts
            if isinstance(msg_copy.get('content'), list):
                msg_copy['content'] = self._ai_debug_process_openai_parts(msg_copy['content'])

            # OpenAI function_call_output: output list has the same part structure
            if isinstance(msg_copy.get('output'), list):
                msg_copy['output'] = self._ai_debug_process_openai_parts(msg_copy['output'])

            # Google and normalized Enterprise format: inline_data parts.
            if isinstance(msg_copy.get('parts'), list):
                new_parts = []
                for part in msg_copy['parts']:
                    if isinstance(part, dict) and 'inline_data' in part:
                        mime = part['inline_data'].get('mimeType', '')
                        if self._ai_debug_is_image_type(mime):
                            data = part['inline_data'].get('data', '')
                            new_parts.append({'inline_data': self._ai_debug_image_data(mime, data)})
                        else:
                            new_parts.append({
                                'inline_data': {
                                    'mimeType': mime,
                                    '_binary_excluded': True,
                                },
                            })
                    else:
                        new_parts.append(part)
                msg_copy['parts'] = new_parts

            # Enterprise normalized messages put inline_data in content[].
            if isinstance(msg_copy.get('content'), list):
                normalized_parts = []
                for part in msg_copy['content']:
                    if not isinstance(part, dict) or part.get('type') != 'inline_data':
                        normalized_parts.append(part)
                        continue
                    mime, data = self._ai_debug_part_inline_data(part)
                    if self._ai_debug_is_image_type(mime):
                        normalized_parts.append({
                            'type': 'inline_data',
                            'content': self._ai_debug_image_data(mime, data),
                        })
                    else:
                        normalized_parts.append({
                            'type': 'inline_data',
                            'content': {'mimeType': mime, '_binary_excluded': True},
                        })
                msg_copy['content'] = normalized_parts

            result.append(msg_copy)
        return result

    def _ai_debug_process_openai_parts(self, parts):
        """Process a list of OpenAI-format parts: keep images, strip other binary."""
        new_parts = []
        for part in parts:
            if not isinstance(part, dict):
                new_parts.append(part)
                continue
            ptype = part.get('type', '')
            if ptype in ('input_image', 'output_image'):
                image_url = part.get('image_url') or part.get('url')
                if isinstance(image_url, str) and len(image_url.encode()) <= _MAX_IMAGE_DATA_BYTES:
                    new_parts.append(part)
                else:
                    new_parts.append({'type': ptype, '_binary_excluded': True})
            elif ptype in ('input_file', 'output_file'):
                new_parts.append({'type': ptype, '_binary_excluded': True})
            else:
                new_parts.append(part)
        return new_parts

    def _ai_debug_sources(self, sources):
        return {
            self._ai_debug_sanitize(source_id): {
                key: self._ai_debug_sanitize(source[key], key=key)
                for key in ('url', 'source_name') if key in source
            }
            for source_id, source in list(sources.items())[:_MAX_COLLECTION_ITEMS]
            if isinstance(source, dict) and isinstance(source.get('url'), str)
            and source['url'].startswith(('https://', 'http://'))
        }

    def _ai_debug_normalized_part(self, part, *, depth=0):
        """Allowlist one Enterprise message part without provider continuity blobs."""
        if not isinstance(part, dict) or depth >= _MAX_DEPTH:
            return {'_details_excluded': True}
        part_type = part.get('type')
        if part_type == 'text':
            normalized = {
                'type': 'text',
                'content': {
                    'data': self._ai_debug_sanitize(
                        self._ai_debug_part_text(part),
                        key='data',
                    ),
                },
            }
            if isinstance(part.get('sources'), dict):
                normalized['sources'] = self._ai_debug_sources(part['sources'])
            if 'provider_data' in part:
                normalized['_provider_data_excluded'] = True
            return normalized
        if part_type == 'inline_data':
            mime, data = self._ai_debug_part_inline_data(part)
            image = self._ai_debug_image_data(mime, data)
            normalized_content = {'mimetype': mime}
            if image.get('data'):
                normalized_content['data'] = image['data']
            else:
                normalized_content['_binary_excluded'] = True
            normalized = {'type': 'inline_data', 'content': normalized_content}
            metadata = part.get('metadata') or {}
            normalized['metadata'] = {
                key: self._ai_debug_sanitize(metadata[key], key=key)
                for key in ('attachment_id', 'attachment_ids', 'image_path') if key in metadata
            }
            if 'provider_data' in part:
                normalized['_provider_data_excluded'] = True
            return normalized
        if part_type == 'tool_call':
            normalized = {
                'type': 'tool_call',
                'name': self._ai_debug_sanitize(part.get('name'), key='name'),
                'args': self._ai_debug_sanitize(part.get('args') or {}, key='args'),
                'call_id': self._ai_debug_sanitize(part.get('call_id'), key='call_id'),
            }
            if 'provider_data' in part:
                normalized['_provider_data_excluded'] = True
            return normalized
        if part_type == 'tool_results':
            tool_result = part.get('tool_results') or {}
            if not isinstance(tool_result, dict):
                return {'type': 'tool_results', '_details_excluded': True}
            result_parts = tool_result.get('result') or []
            return {
                'type': 'tool_results',
                'tool_results': {
                    'tool_call': self._ai_debug_normalized_part(
                        tool_result.get('tool_call') or {}, depth=depth + 1,
                    ),
                    'result': [
                        self._ai_debug_normalized_part(result_part, depth=depth + 1)
                        for result_part in result_parts[:_MAX_COLLECTION_ITEMS]
                    ] if isinstance(result_parts, list) else [],
                    'success': bool(tool_result.get('success')),
                },
            }
        if part_type == 'tool_result':
            result_parts = part.get('result') or []
            return {
                'type': 'tool_result',
                'tool_name': self._ai_debug_sanitize(
                    part.get('tool_name'), key='tool_name',
                ),
                'tool_call_id': self._ai_debug_sanitize(
                    part.get('tool_call_id'), key='tool_call_id',
                ),
                'result': [
                    self._ai_debug_normalized_part(
                        result_part, depth=depth + 1,
                    )
                    for result_part in result_parts[:_MAX_COLLECTION_ITEMS]
                ] if isinstance(result_parts, list) else [],
                'success': bool(part.get('success')),
            }
        return {
            'type': self._ai_debug_sanitize(part_type, key='type'),
            '_details_excluded': True,
        }

    def _ai_debug_normalized_message(self, message):
        """Allowlist one normalized user/assistant message for debugger display."""
        if not isinstance(message, dict):
            return {'_details_excluded': True}
        content = message.get('content') or []
        normalized = {
            'role': self._ai_debug_sanitize(message.get('role'), key='role'),
            'content': [
                self._ai_debug_normalized_part(part)
                for part in content[:_MAX_COLLECTION_ITEMS]
            ] if isinstance(content, list) else [],
        }
        provider_metadata = message.get('provider_metadata')
        if isinstance(provider_metadata, dict):
            normalized['provider_metadata'] = {
                key: self._ai_debug_sanitize(provider_metadata.get(key), key=key)
                for key in ('provider', 'model', 'api')
                if key in provider_metadata
            }
        return normalized

    def _ai_debug_normalized_messages(self, messages):
        if not isinstance(messages, list):
            return []
        return [
            self._ai_debug_normalized_message(message)
            for message in messages[:_MAX_COLLECTION_ITEMS]
        ]

    def _ai_debug_normalized_tools(self, tools):
        if not isinstance(tools, list):
            return []
        return [
            {
                key: self._ai_debug_sanitize(tool.get(key), key=key)
                for key in ('name', 'instructions', 'schema')
                if key in tool
            }
            for tool in tools[:_MAX_COLLECTION_ITEMS]
            if isinstance(tool, dict)
        ]

    def _ai_debug_serialize_tools(self, tools):
        """Return the normalized tool definitions sent by current Enterprise."""
        if not tools:
            return []
        try:
            tools_by_name = {tool.sudo().ai_tool_name: tool for tool in tools}
            return self._prepare_tools(tools_by_name)
        except Exception:
            _logger.exception("ai_debug: failed to serialize tools for iteration event")
            return []

    def _ai_debug_current_tools(self, tools_context):
        """Resolve the current tools recordset from tools_context["state"]["available_tools"].

        Mirrors the parent _run_agentic_loop lookup so serialized tools in each
        iteration event reflect the exact set available to the LLM at that point.
        Returns an empty recordset on any failure.
        """
        try:
            tool_ids = (tools_context.get('state') or {}).get('available_tools') or []
            # Mirror parent's search() so serialized order matches what the LLM
            # actually sees (model _order), not the available_tools list order.
            return self.env['ir.actions.server'].sudo().search([('id', 'in', tool_ids)])
        except Exception:
            _logger.exception("ai_debug: failed to resolve current tools from tools_context")
            return self.env['ir.actions.server']

    @staticmethod
    def _ai_debug_message_summary(messages):
        """Describe normalized messages without exporting their content."""
        summary = []
        for message in messages or []:
            if not isinstance(message, dict):
                continue
            parts = message.get('content') or message.get('parts') or []
            summary.append({
                'role': message.get('role'),
                'part_types': [
                    part.get('type') or ('inline_data' if 'inline_data' in part else None)
                    for part in parts
                    if isinstance(part, dict)
                ],
                'part_count': len(parts) if isinstance(parts, list) else 0,
            })
        return summary

    @staticmethod
    def _ai_debug_text_from_parts(parts):
        """Return normalized text parts without interpreting their markup."""
        text_parts = []
        for part in parts or []:
            if not isinstance(part, dict) or part.get('type') != 'text':
                continue
            text = AiSession._ai_debug_part_text(part)
            if isinstance(text, str):
                text_parts.append(text)
        return '\n'.join(text_parts)

    def _ai_debug_request_snapshot(self, request_uuid=None):
        """Copy the active immutable request intent before Enterprise replaces it."""
        self.ensure_one()
        if not self.request_uuid or (
            request_uuid is not None and self.request_uuid != request_uuid
        ):
            return None
        return {
            'request_uuid': self.request_uuid,
            'round_no': self.request_round,
            'round_limit': self.request_round_limit,
            'payload': copy.deepcopy(self.request_payload or {}),
            'user_id': self.request_user_id.id,
            'guest_id': self.request_guest_id.id,
            'context_snapshot': copy.deepcopy(self.request_context),
            'loop_state': self.loop_state,
            'pending': copy.deepcopy(self.pending_tool_call or {}),
            'continuation_type': (self.state or {}).get('callback_type'),
            'parent_session_id': self.parent_session_id.id,
        }

    def _get_request_context_snapshot(self, context=None):
        snapshot = super()._get_request_context_snapshot(context)
        # Keep this session's private correlation; business values come from the event.
        store_context = self.env.context.get(_AI_DEBUG_STORE_CONTEXT_KEY)
        correlation = (store_context['correlation']
                       if store_context and store_context['session_id'] == self.id
                       else self.request_context or {})
        for key in (_AI_DEBUG_EXCHANGE_UUID_CONTEXT_KEY, '_ai_debug_parent_link',
                    _AI_DEBUG_ROUND_START_CONTEXT_KEY, _AI_DEBUG_TOOL_TIMINGS_CONTEXT_KEY):
            if key in correlation:
                snapshot[key] = copy.deepcopy(correlation[key])
        return snapshot

    def _ai_debug_prepare_request_context(self, context_snapshot, *, continuation):
        """Add private correlation without trusting a browser-supplied value."""
        if context_snapshot is None:
            context_snapshot = self._get_request_context_snapshot()
        if not isinstance(context_snapshot, dict):
            return context_snapshot
        prepared_snapshot = copy.deepcopy(context_snapshot)
        exchange_uuid = None
        if continuation and isinstance(self.request_context, dict):
            exchange_uuid = self.request_context.get(
                _AI_DEBUG_EXCHANGE_UUID_CONTEXT_KEY
            )
        if not isinstance(exchange_uuid, str) or not exchange_uuid:
            exchange_uuid = (
                self.request_uuid
                if continuation and self.request_uuid
                else uuid.uuid4().hex
            )
        prepared_snapshot[_AI_DEBUG_EXCHANGE_UUID_CONTEXT_KEY] = exchange_uuid
        return prepared_snapshot

    def _ai_debug_user_query(self, request):
        """Return the durable exchange prompt without its appended Odoo context."""
        for message in reversed((request.get('payload') or {}).get('messages') or []):
            if not isinstance(message, dict) or message.get('role') != 'user':
                continue
            query_parts = []
            for part in message.get('content') or []:
                text = self._ai_debug_text_from_parts([part])
                if text and not text.lstrip().startswith('<odoo_current_context>'):
                    query_parts.append(text)
            if query_parts:
                return html2plaintext(
                    '\n'.join(query_parts), include_references=False,
                ).strip()
        return ''

    @staticmethod
    def _ai_debug_exchange_uuid(request):
        """Return the Custom correlation copied across session-owned rounds."""
        context_snapshot = request.get('context_snapshot')
        if not isinstance(context_snapshot, dict):
            return request['request_uuid']
        exchange_uuid = context_snapshot.get(_AI_DEBUG_EXCHANGE_UUID_CONTEXT_KEY)
        return (
            exchange_uuid
            if isinstance(exchange_uuid, str) and exchange_uuid
            else request['request_uuid']
        )

    @staticmethod
    def _ai_debug_callback_tool_call_id(request_uuid, call_id):
        """Return a stable debugger identity for one durable callback tool call."""
        encoded_call_id = json.dumps(
            call_id, ensure_ascii=False, sort_keys=True, default=str,
        )
        return uuid.uuid5(
            uuid.NAMESPACE_URL,
            f'odoo-ai-debug:{request_uuid}:{encoded_call_id}',
        ).hex

    def _ai_debug_callback_context(self, request, *, continuing=False):
        """Build transaction-local buffering state for one authoritative callback seam."""
        context = {
            'session_id': self.id,
            'trace_id': self._ai_debug_exchange_uuid(request),
            'iteration_id': request['request_uuid'],
            'request_uuid': request['request_uuid'],
            'round_no': request['round_no'],
            'target_user_id': request['user_id'],
            'events': [],
            'started_tool_call_ids': set(),
            'tool_timings': copy.deepcopy(request['context_snapshot'].get(_AI_DEBUG_TOOL_TIMINGS_CONTEXT_KEY, {})),
        }
        if continuing:
            pending_tool_call = self.pending_tool_call or {}
            if 'call_id' in pending_tool_call:
                try:
                    context['pending_tool_call'] = (
                        self._ai_debug_find_tool_call(
                            self._get_last_tool_calls(),
                            pending_tool_call['call_id'],
                        )
                        or {'call_id': pending_tool_call['call_id']}
                    )
                    user_input_request = (
                        pending_tool_call.get('user_input_request') or {}
                    )
                    context['pending_interaction_type'] = (
                        user_input_request.get('type')
                        or ('client_tool' if pending_tool_call.get('client_tool') else None)
                    )
                    context['pending_interaction_message'] = (
                        user_input_request.get('body') or ''
                    )
                    context['started_tool_call_ids'].add(
                        self._ai_debug_callback_tool_call_id(
                            request['request_uuid'],
                            pending_tool_call['call_id'],
                        )
                    )
                except Exception:  # noqa: BLE001
                    _logger.exception(
                        "ai_debug: failed to restore callback tool identity"
                    )
        return context

    @staticmethod
    def _ai_debug_find_tool_call(tool_calls, call_id):
        return next(
            (
                tool_call for tool_call in tool_calls
                if tool_call.get('call_id') == call_id
            ),
            None,
        )

    def _ai_debug_tool_call_from_result(self, tool_calls, result_item):
        """Correlate current flat tool results with their original model call."""
        if not isinstance(result_item, dict):
            return {}
        legacy_tool_call = result_item.get('tool_call') or {}
        call_id = (
            legacy_tool_call.get('call_id')
            if isinstance(legacy_tool_call, dict)
            else None
        ) or result_item.get('tool_call_id')
        return (
            self._ai_debug_find_tool_call(tool_calls, call_id)
            or legacy_tool_call
            or {
                'call_id': call_id,
                'name': result_item.get('tool_name'),
            }
        )

    @contextmanager
    def _ai_debug_time_tool(self, timings, call_id, *, durable):
        def now_ms():
            return time.time_ns() // 1_000_000 if durable else int(time.monotonic() * 1000)

        timing = timings.setdefault(call_id, {'started_at_ms': now_ms()})
        try:
            yield
        finally:
            timing['finished_at_ms'] = now_ms()

    @staticmethod
    def _ai_debug_tool_duration(timings, call_id):
        timing = timings.get(call_id)
        if not timing or 'finished_at_ms' not in timing:
            return None
        return max(0, timing['finished_at_ms'] - timing['started_at_ms'])

    @staticmethod
    def _ai_debug_end_tool_wait(context, call_id):
        if context and (timing := context['tool_timings'].get(call_id)):
            timing.setdefault('finished_at_ms', time.time_ns() // 1_000_000)

    def _ai_debug_buffer_callback_tool_started(self, context, tool_call):
        """Buffer one start fact without affecting the parent tool generator."""
        try:
            if not isinstance(tool_call, dict) or 'call_id' not in tool_call:
                return None
            tool_call_id = self._ai_debug_callback_tool_call_id(
                context['request_uuid'], tool_call['call_id'],
            )
            if tool_call_id in context['started_tool_call_ids']:
                return tool_call_id
            context['started_tool_call_ids'].add(tool_call_id)
            context['events'].append(('tool_call_started', {
                'type': 'tool_call_started',
                'trace_id': context['trace_id'],
                'exchange_uuid': context['trace_id'],
                'request_uuid': context['request_uuid'],
                'round_no': context['round_no'],
                'iteration_id': context['iteration_id'],
                'tool_call_id': tool_call_id,
                'call_id': tool_call['call_id'],
                'tool_name': tool_call.get('name', 'unknown'),
                'args': copy.deepcopy(tool_call.get('args') or {}),
            }))
            return tool_call_id
        except Exception:  # noqa: BLE001
            _logger.exception("ai_debug: failed to buffer callback tool start")
            return None

    def _ai_debug_buffer_callback_tool_completed(
        self, context, tool_call, *, result=None, success=None,
        triggered_confirmation=False, confirmation_message=None,
    ):
        """Buffer one completion fact paired to its stable callback start."""
        try:
            if not isinstance(tool_call, dict) or 'call_id' not in tool_call:
                return
            tool_call_id = self._ai_debug_callback_tool_call_id(context['request_uuid'], tool_call['call_id'])
            completed = context.setdefault('completed_tool_call_ids', set())
            if tool_call_id in completed and not triggered_confirmation:
                return
            self._ai_debug_buffer_callback_tool_started(context, tool_call)
            if not triggered_confirmation:
                completed.add(tool_call_id)
            normalized_result = ([self._ai_debug_normalized_part(part) for part in result[:_MAX_COLLECTION_ITEMS]]
                                 if isinstance(result, list) else self._ai_debug_sanitize(result))
            error = str(normalized_result) if success is False and result is not None else None
            context['events'].append(('tool_call_completed', {
                'type': 'tool_call_completed',
                'trace_id': context['trace_id'],
                'exchange_uuid': context['trace_id'],
                'request_uuid': context['request_uuid'],
                'round_no': context['round_no'],
                'iteration_id': context['iteration_id'],
                'tool_call_id': tool_call_id,
                'call_id': tool_call['call_id'],
                'tool_name': tool_call.get('name', 'unknown'),
                'args': copy.deepcopy(tool_call.get('args') or {}),
                'result': normalized_result,
                'success': success,
                'error': error,
                'triggered_confirmation': triggered_confirmation,
                'confirmation_message': confirmation_message,
                'duration_ms': (None if triggered_confirmation else
                                self._ai_debug_tool_duration(context['tool_timings'], tool_call['call_id'])),
                'status': 'waiting_confirmation' if triggered_confirmation else 'completed',
            }))
        except Exception:  # noqa: BLE001
            _logger.exception("ai_debug: failed to buffer callback tool completion")

    def _ai_debug_tool_progress(self, item):
        if 'tool_status' in item:
            return {'tool_status': self._ai_debug_sanitize(item['tool_status'])}
        if item.get('is_tool_summary'):
            return {'summary': self._ai_debug_sanitize(html2plaintext(item['intermediary_message']))}
        return {}

    def _ai_debug_buffer_callback_tool_items(
        self, items, tool_calls, tools_context, context,
    ):
        """Buffer tool observations within the enclosing business transaction."""
        for item in items:
            try:
                if progress := self._ai_debug_tool_progress(item):
                    current_tool_call = self._ai_debug_find_tool_call(tool_calls, tools_context['tool_call_id'])
                    tool_call_id = self._ai_debug_buffer_callback_tool_started(context, current_tool_call)
                    if tool_call_id:
                        context['events'].append(('tool_call_progress', {
                            'type': 'tool_call_progress', 'trace_id': context['trace_id'],
                            'request_uuid': context['request_uuid'], 'round_no': context['round_no'],
                            'iteration_id': context['iteration_id'], 'tool_call_id': tool_call_id,
                            **progress,
                        }))

                for result_item in item.get('tool_results') or ():
                    tool_call = self._ai_debug_tool_call_from_result(
                        tool_calls, result_item,
                    )
                    if 'child_session_id' in result_item:
                        context['tool_timings'].get(tool_call['call_id'], {}).pop('finished_at_ms', None)
                        self._ai_debug_buffer_callback_tool_started(context, tool_call)
                        continue
                    self._ai_debug_buffer_callback_tool_completed(
                        context,
                        tool_call,
                        result=result_item.get('result'),
                        success=result_item.get('success', True),
                    )

                pending_tool_call = item.get('pending_tool_call') or {}
                if 'call_id' in pending_tool_call:
                    context['tool_timings'].get(pending_tool_call['call_id'], {}).pop('finished_at_ms', None)
                user_input_request = item.get('user_input_request') or {}
                for result_item in pending_tool_call.get('pending_results') or ():
                    tool_call = self._ai_debug_tool_call_from_result(
                        tool_calls, result_item,
                    )
                    if 'child_session_id' in result_item:
                        context['tool_timings'].get(tool_call['call_id'], {}).pop('finished_at_ms', None)
                        self._ai_debug_buffer_callback_tool_started(context, tool_call)
                        continue
                    self._ai_debug_buffer_callback_tool_completed(
                        context,
                        tool_call,
                        result=result_item.get('result'),
                        success=result_item.get('success', True),
                    )
                if (
                    'call_id' in pending_tool_call
                    and user_input_request.get('type') == 'confirmation'
                ):
                    tool_call = self._ai_debug_find_tool_call(
                        tool_calls, pending_tool_call['call_id'],
                    )
                    self._ai_debug_buffer_callback_tool_completed(
                        context,
                        tool_call,
                        triggered_confirmation=True,
                        confirmation_message=user_input_request.get('body') or '',
                    )
            except Exception:  # noqa: BLE001
                _logger.exception("ai_debug: failed to observe callback tool item")
            yield item

    def _ai_debug_flush_callback_tool_events(self, context):
        """Queue buffered callback tool facts after parent application succeeds."""
        events = list(context.get('events') or ())
        context['events'] = []
        for event_type, payload in events:
            self._ai_debug_bus_send(
                event_type,
                payload,
                target_user_id=context['target_user_id'],
            )

    def _save_and_submit_request(self, payload, *, callback_type,
                         request_round, request_round_limit, state):
        # Correlation is part of immutable request intent; instrumentation is optional.
        def prepare_context():
            prepared_context = self._ai_debug_prepare_request_context(
                {}, continuation=request_round > 1,
            )
            parent_link = None
            if request_round == 1 and self.parent_session_id and callback_type == 'agent_loop':
                parent_link = self.parent_session_id._ai_debug_parent_link(self.env.context['ai_parent_tool_call_id'])
            if request_round > 1:
                parent_link = (self.request_context or {}).get('_ai_debug_parent_link')
            if parent_link:
                prepared_context['_ai_debug_parent_link'] = parent_link
            else:
                prepared_context.pop('_ai_debug_parent_link', None)
            # Wall time survives the transaction/worker boundary to the callback.
            prepared_context[_AI_DEBUG_ROUND_START_CONTEXT_KEY] = time.time_ns() // 1_000_000
            return prepared_context

        correlation = self._ai_debug_try(prepare_context) or {}
        session = self.with_context(**{_AI_DEBUG_STORE_CONTEXT_KEY: {
            'session_id': self.id, 'correlation': correlation,
        }})
        result = super(AiSession, session)._save_and_submit_request(
            payload, callback_type=callback_type,
            request_round=request_round, request_round_limit=request_round_limit,
            state=state,
        )
        request = self._ai_debug_try(self._ai_debug_request_snapshot)
        if request:
            self._ai_debug_try(lambda: self._ai_debug_trace_request_prepared(request))
            self._ai_debug_try(lambda: self._ai_debug_trace_request_result(request, {}, {}, None))
        return result

    def _ai_debug_parent_link(self, call_id):
        request = self._ai_debug_request_snapshot()
        if not request:
            return None
        return {
            'parent_trace_id': self._ai_debug_exchange_uuid(request),
            'parent_session_id': self.id,
            'parent_request_uuid': request['request_uuid'],
            'parent_tool_call_id': self._ai_debug_callback_tool_call_id(request['request_uuid'], call_id),
        }

    def _ai_debug_normalized_request(self, request):
        """Rebuild the credential-free normalized payload submitted to IAP."""
        payload = copy.deepcopy(request.get('payload') or {})
        normalized = {
            'request_uuid': request['request_uuid'],
            'messages': self._ai_debug_normalized_messages(payload.get('messages')),
            'instructions': self._ai_debug_sanitize(
                payload.get('instructions'), key='instructions',
            ),
            'tools': self._ai_debug_normalized_tools(payload.get('tools')),
        }
        for key in _NORMALIZED_COMPLETION_OPTION_KEYS:
            if key in payload:
                normalized[key] = self._ai_debug_sanitize(payload[key], key=key)
        return normalized

    def _ai_debug_normalized_response(self, response):
        """Copy the accepted callback envelope and bound binary parts."""
        if not isinstance(response, dict):
            return {'_details_excluded': True}
        normalized = {
            key: self._ai_debug_sanitize(response.get(key), key=key)
            for key in ('request_uuid', 'status')
            if key in response
        }
        if 'error' in response:
            error = response.get('error')
            normalized['error'] = (
                error if error in _SAFE_IAP_ERROR_CODES
                else 'request_failed' if error
                else None
            )
        if isinstance(response.get('result'), dict):
            normalized['result'] = self._ai_debug_normalized_message(response['result'])
        return normalized

    @staticmethod
    def _ai_debug_result_error(response):
        """Normalize only enough of the IAP envelope to label debugger output."""
        if not isinstance(response, dict) or response.get('status') != 'success':
            error = response.get('error') if isinstance(response, dict) else None
            return error if error in _SAFE_IAP_ERROR_CODES else 'request_failed'
        result = response.get('result')
        content = result.get('content') if isinstance(result, dict) else None
        if not isinstance(content, list) or not any(
            isinstance(part, dict)
            and part.get('type') in ('tool_call', 'text', 'inline_data')
            for part in content
        ):
            return 'request_failed'
        return None

    def _ai_debug_trace_request_prepared(self, request):
        """Queue the single exchange trace created by a durable first round."""
        self.ensure_one()
        if request['round_no'] != 1:
            return False
        payload = request.get('payload') or {}
        exchange_uuid = self._ai_debug_exchange_uuid(request)
        return self._ai_debug_bus_send('new_trace', {
            'type': 'new_trace',
            'trace_id': exchange_uuid,
            'exchange_uuid': exchange_uuid,
            'request_uuid': request['request_uuid'],
            'round_no': request['round_no'],
            'request_state': request['loop_state'],
            'session_id': self.id,
            'trace_kind': request['continuation_type'],
            'trace_label': {'channel_name': 'Conversation Title'}.get(request['continuation_type']),
            **(request['context_snapshot'].get('_ai_debug_parent_link') or {}),
            'agent_name': self.agent_id.name if self.agent_id else None,
            'user_query': self._ai_debug_user_query(request),
            'instructions': payload.get('instructions') or '',
            'state_snapshot': {
                'loop_state': request['loop_state'],
                    'round_limit': request['round_limit'],
                'message_summary': self._ai_debug_message_summary(payload.get('messages')),
            },
        }, target_user_id=request['user_id'])

    def _ai_debug_trace_exchange_end(
        self, request, outcome, *, error=None, termination_reason=None, request_state=None,
    ):
        """Close a trace from the accepted reducer outcome, not a removed ledger state."""
        if outcome.get('responseState') != 'idle':
            return False
        exchange_uuid = self._ai_debug_exchange_uuid(request)
        return self._ai_debug_bus_send('loop_end', {
            'type': 'loop_end',
            'trace_id': exchange_uuid,
            'exchange_uuid': exchange_uuid,
            'request_uuid': request['request_uuid'],
            'round_no': request['round_no'],
            'termination_reason': (
                termination_reason or ('error' if error else 'success')
            ),
            'termination_source': 'committed_session_state',
            'exchange_result': self._ai_debug_sanitize(
                (self._ai_debug_active_callback_context() or {}).get('child_result'),
            ),
            'final_output': (self._ai_debug_active_callback_context() or {}).get('final_output'),
            'request_state': request_state or self.loop_state,
            'phase': 'child_settled' if request['parent_session_id'] else 'completed',
            'error': error,
            'iteration_count': request['round_no'],
            'duration_ms': None,
            'duration_kind': None,
        }, target_user_id=request['user_id'])

    def _ai_debug_trace_request_result(self, request, response, outcome, error):
        """Queue one normalized iteration after Enterprise accepts the active UUID."""
        started_at_ms = request['context_snapshot'].get(_AI_DEBUG_ROUND_START_CONTEXT_KEY)
        # Capture before normalization and, on callbacks, before any tool execution.
        duration_ms = (
            max(0, time.time_ns() // 1_000_000 - started_at_ms)
            if response and started_at_ms is not None else None
        )
        normalized_request = self._ai_debug_normalized_request(request)
        normalized_response = self._ai_debug_normalized_response(response)
        result = (
            normalized_response.get('result')
            if isinstance(normalized_response, dict)
            else None
        )
        provider_metadata = (
            result.get('provider_metadata') or {}
            if isinstance(result, dict)
            else {}
        )
        content = result.get('content') or [] if isinstance(result, dict) else []
        has_tool_calls = any(
            isinstance(part, dict) and part.get('type') == 'tool_call'
            for part in content
        )
        exchange_uuid = self._ai_debug_exchange_uuid(request)
        return self._ai_debug_bus_send('iteration', {
            'type': 'iteration',
            'trace_id': exchange_uuid,
            'exchange_uuid': exchange_uuid,
            'request_uuid': request['request_uuid'],
            'round_no': request['round_no'],
            'iteration_id': request['request_uuid'],
            'iteration_index': request['round_no'],
            'request_body': normalized_request,
            'request_label': 'Normalized IAP Submission',
            'raw_response': normalized_response if response else None,
            'response_label': 'Normalized IAP Result',
            'has_tool_calls': has_tool_calls,
            'is_final': False,
            'phase': 'result_received' if response else 'prepared',
            'error': error,
            'request_state': request['loop_state'],
            'outcome_response_state': outcome.get('responseState'),
            'provider': provider_metadata.get('provider'),
            'model_name': provider_metadata.get('model'),
            'provider_api': provider_metadata.get('api'),
            'duration_ms': duration_ms,
            'duration_kind': 'model_round_trip' if duration_ms is not None else None,
        }, target_user_id=request['user_id'])

    def _ai_debug_emit_state(self, request, phase, **values):
        return self._ai_debug_bus_send('request_state', {
            'type': 'request_state', 'trace_id': self._ai_debug_exchange_uuid(request),
            'exchange_uuid': self._ai_debug_exchange_uuid(request),
            'session_id': self.id, 'request_uuid': request['request_uuid'],
            'iteration_id': request['request_uuid'], 'round_no': request['round_no'],
            'state': self.loop_state,
            'phase': phase, **values,
        }, target_user_id=request['user_id'])

    def _ai_debug_transition_snapshot(self, completion_result=None):
        request = self._ai_debug_request_snapshot()
        if not request:
            return None
        request['result'] = copy.deepcopy(completion_result)
        context = self._ai_debug_callback_context(request, continuing=True)
        context['tool_calls'] = ([part for part in completion_result.get('message', {}).get('content', [])
                                  if part.get('type') == 'tool_call'] if completion_result is not None
                                 else self._get_last_tool_calls() if self.pending_tool_call else [])
        pending = request['pending'].get('pending_results', [])
        context['started_tool_call_ids'].update(
            self._ai_debug_callback_tool_call_id(request['request_uuid'], item.get('tool_call_id'))
            for item in pending
        )
        context['completed_tool_call_ids'] = {
            self._ai_debug_callback_tool_call_id(request['request_uuid'], item.get('tool_call_id'))
            for item in pending if 'result' in item
        }
        return request, context, set(self.event_ids.ids)

    def _ai_debug_active_callback_context(self):
        # A helper can advance its parent in the same continuation. Each session
        # must keep its own tool events and final output during that nested span.
        context = self.env.context.get(_AI_DEBUG_CALLBACK_CONTEXT_KEY)
        while context and context['session_id'] != self.id:
            context = context.get('outer_context')
        return context

    @contextmanager
    def _ai_debug_transition(self, completion_result=None):
        snapshot = self._ai_debug_try(lambda: self._ai_debug_transition_snapshot(completion_result))
        if not snapshot:
            yield self
            return
        request, context, history_ids = snapshot
        context['outer_context'] = self.env.context.get(_AI_DEBUG_CALLBACK_CONTEXT_KEY)
        session = self.with_context(**{_AI_DEBUG_CALLBACK_CONTEXT_KEY: context})
        if completion_result is not None:
            session._ai_debug_try(lambda: session._ai_debug_record_callback(request, completion_result))
        yield session
        session._ai_debug_try(lambda: session._ai_debug_observe_transition(request, context, history_ids))

    def _finish_exchange(self, status='completed', *, content=None):
        # Submission rescue uses a fresh environment, outside a callback span.
        if not self._ai_debug_active_callback_context():
            with self._ai_debug_transition() as session:
                return session._ai_debug_finish_exchange(status, content=content)
        return self._ai_debug_finish_exchange(status, content=content)

    def _ai_debug_finish_exchange(self, status, *, content):
        def capture():
            context = self._ai_debug_active_callback_context()
            if context:
                context['finish_status'] = status
                if content is not None:
                    parts = content if isinstance(content, list) else [{'type': 'text', 'text': str(content)}]
                    context['final_output'] = self._ai_debug_normalized_message({'role': 'assistant', 'content': parts})
        self._ai_debug_try(capture)
        return super()._finish_exchange(status, content=content)

    def _abort_pending_tools(self):
        # New messages abort their pending interaction in the controller, before
        # preparing the next exchange. Resume already owns an observation span.
        if context := self._ai_debug_active_callback_context():
            self._ai_debug_end_tool_wait(context, (self.pending_tool_call or {}).get('call_id'))
            return super()._abort_pending_tools()
        with self._ai_debug_transition() as session:
            session._ai_debug_end_tool_wait(session._ai_debug_active_callback_context(),
                                            (session.pending_tool_call or {}).get('call_id'))
            return super(AiSession, session)._abort_pending_tools()

    def _ai_debug_observe_transition(self, request, context, history_ids):
        if (request['request_uuid'] == self.request_uuid and request['loop_state'] == self.loop_state
                and request['pending'] == (self.pending_tool_call or {})
                and history_ids == set(self.event_ids.ids) and not context['events']):
            return
        # Completed results may be persisted without passing through the tool generator
        # (notably a foreground child merge while another interaction is pending).
        results = list((self.pending_tool_call or {}).get('pending_results', []))
        for event in self.event_ids:
            if event.id not in history_ids:
                results += [part for part in event.metadata.get('content', []) if part.get('type') == 'tool_result']
        for item in results:
            call = self._ai_debug_tool_call_from_result(context['tool_calls'], item)
            if 'child_session_id' in item:
                self._ai_debug_buffer_callback_tool_started(context, call)
            elif 'result' in item:
                self._ai_debug_buffer_callback_tool_completed(
                    context, call, result=item['result'], success=item.get('success', True),
                )
        if self.request_uuid == request['request_uuid'] and self.loop_state != 'ready' and context['tool_timings']:
            self.request_context = {
                **self.request_context, _AI_DEBUG_TOOL_TIMINGS_CONTEXT_KEY: context['tool_timings'],
            }
        self._ai_debug_flush_callback_tool_events(context)
        if not (context.get('finish_status') == 'failed' and request['result'] is None):
            self._ai_debug_emit_state(request, 'result_consumed')
        if context.get('finish_status') or (request['request_uuid'] == self.request_uuid
                and request['loop_state'] != 'ready' and self.loop_state == 'ready'):
            result = request['result'] or {}
            error = result.get('code') if result.get('kind') == 'failure' else (
                'request_failed' if context.get('finish_status') == 'failed' else None)
            reason = context.get('finish_status') or request['pending'].get('exchange_status')
            self._ai_debug_trace_exchange_end(
                request, {'responseState': 'idle'}, error=error, request_state='ready',
                termination_reason='failed' if error and reason == 'completed' else 'success' if reason == 'completed' else reason,
            )

    def _ai_debug_record_callback(self, request, result):
        response = ({'status': 'success', 'result': result['message']}
                    if result['kind'] == 'success' else {'status': 'error', 'error': result['code']})
        self._ai_debug_trace_request_result(request, response, {}, self._ai_debug_result_error(response))
        self._ai_debug_emit_state(request, 'result_received')

    def _continue_agent_loop(self, completion_result):
        with self._ai_debug_transition(completion_result) as session:
            return super(AiSession, session)._continue_agent_loop(completion_result)

    def _continue_channel_name(self, completion_result):
        # The core title handler deletes its temporary session. Keep the facts
        # needed to close the trace before handing over ownership.
        request = self._ai_debug_try(self._ai_debug_request_snapshot)
        if request:
            self._ai_debug_try(lambda: self._ai_debug_record_callback(request, completion_result))
        result = super(AiSession, self.with_context(_ai_debug_title_callback=True))._continue_channel_name(completion_result)
        if request:
            self._ai_debug_try(lambda: self._ai_debug_trace_exchange_end(
                request, {'responseState': 'idle'}, request_state='ready',
                error=completion_result.get('code'),
                termination_reason='failed' if completion_result['kind'] == 'failure' else 'success',
            ))
        return result

    def unlink(self):
        # Submission rescue deletes title sessions without a completion callback.
        requests = []
        if not self.env.context.get('_ai_debug_title_callback'):
            for session in self:
                if session.loop_state == 'waiting_model' and session.state.get('callback_type') == 'channel_name':
                    request = session._ai_debug_try(session._ai_debug_request_snapshot)
                    if request:
                        requests.append((session, request))
        result = super().unlink()
        for session, request in requests:
            session._ai_debug_try(lambda: session._ai_debug_trace_exchange_end(
                request, {'responseState': 'idle'}, request_state='ready',
                termination_reason='failed', error='request_failed',
            ))
        return result

    def _resume_pending_interaction(self, response, ai_session_config=None, *, automatic=False):
        with self._ai_debug_transition() as session:
            session._ai_debug_end_tool_wait(session._ai_debug_active_callback_context(),
                                            (session.pending_tool_call or {}).get('call_id'))
            return super(AiSession, session)._resume_pending_interaction(
                response, ai_session_config=ai_session_config, automatic=automatic,
            )

    @contextmanager
    def _ai_debug_child_application(self, child):
        marker = next((item for item in (self.pending_tool_call or {}).get('pending_results', [])
                       if item.get('child_session_id') == child.id), None)
        if not marker or child.parent_session_id != self:
            yield self
            return
        request = self._ai_debug_try(self._ai_debug_request_snapshot)
        with self._ai_debug_transition() as session:
            session._ai_debug_end_tool_wait(session._ai_debug_active_callback_context(), marker['tool_call_id'])
            yield session
        still_pending = any(item.get('child_session_id') == child.id
                            for item in (self.pending_tool_call or {}).get('pending_results', []))
        if request and not still_pending:
            self._ai_debug_try(lambda: self._ai_debug_emit_state(
                request, 'child_applied', child_session_id=child.id,
                child_request_uuid=child.request_uuid,
                tool_call_id=self._ai_debug_callback_tool_call_id(request['request_uuid'], marker['tool_call_id']),
            ))

    def _merge_child_result(self, child, result):
        def capture():
            context = child._ai_debug_active_callback_context()
            if context:
                context['child_result'] = copy.deepcopy(result)
        self._ai_debug_try(capture)
        with self._ai_debug_child_application(child) as session:
            return super(AiSession, session)._merge_child_result(child, result)

    @api.model
    def _get_direct_response(self, instructions, message, tools=None,
            record=None, agent_id=None, on_item_callback=None, **completion_options):
        """Preserve the originating session metadata across the direct-call seam."""
        agent = self.env['ai.agent']
        if len(self) == 1 and self.agent_id:
            agent = self.agent_id
        elif isinstance(agent_id, int):
            agent = agent.browse(agent_id).exists()
        trace_kind = ('image_generation' if completion_options.get('image_generation') else
                      completion_options.get('usage') if completion_options.get('usage') in ('channel_name', 'web_search')
                      else 'direct')
        parent_link = {}
        callback_context = self.env.context.get(_AI_DEBUG_CALLBACK_CONTEXT_KEY)
        if callback_context and self.env.context.get('ai_parent_trace_id') == callback_context['trace_id']:
            parent_link = {
                'parent_trace_id': callback_context['trace_id'],
                'parent_session_id': callback_context['session_id'],
                'parent_request_uuid': callback_context['request_uuid'],
                'parent_tool_call_id': self._ai_debug_callback_tool_call_id(
                    callback_context['request_uuid'], self.env.context['ai_parent_tool_call_id'],
                ),
            }
        direct_self = self.with_context(**{
            _AI_DEBUG_DIRECT_TRACE_CONTEXT_KEY: {
                **parent_link,
                'session_id': self.id if len(self) == 1 else None,
                'agent_name': agent.name if agent else None,
                'trace_kind': trace_kind,
                'trace_label': {'channel_name': 'Conversation Title', 'web_search': 'Web Search',
                                'image_generation': 'Image Generation', 'direct': 'Direct Completion'}[trace_kind],
            },
        })
        return super(AiSession, direct_self)._get_direct_response(
            instructions, message, tools=tools, record=record, agent_id=agent_id,
            on_item_callback=on_item_callback,
            **completion_options,
        )

    def _get_completions(self, messages, instructions, tools=None, **options):
        context = self.env.context.get('_debug_ctx')
        if context is not None:
            context['prepared_iteration_id'] = uuid.uuid4().hex
            context['request_body'] = self._ai_debug_try(lambda: self._ai_debug_normalized_request({
                'request_uuid': context['prepared_iteration_id'],
                'payload': {'messages': messages, 'instructions': instructions, 'tools': tools, **options},
            }))
        started_at = time.monotonic()
        result = super()._get_completions(messages, instructions, tools, **options)
        if context is not None:
            context['model_duration_ms'] = int((time.monotonic() - started_at) * 1000)
            context['raw_response'] = self._ai_debug_try(
                lambda: self._ai_debug_normalized_messages([result['result']]))
        return result

    @api.model
    def _run_agentic_loop(self, instructions, message, tools_context, record=None, **completion_options):
        """Preserve coarse tracing for callers that still use the synchronous loop."""
        trace_id = uuid.uuid4().hex
        _debug_ctx = {
            'trace_id': trace_id,
            'iteration_id': None,
            'tool_call_count': 0,
        }

        self = self.with_context(_debug_ctx=_debug_ctx)
        iteration_count = 0
        started_at = time.monotonic()
        direct_trace = self.env.context.get(_AI_DEBUG_DIRECT_TRACE_CONTEXT_KEY)
        if not isinstance(direct_trace, dict):
            direct_trace = {}
        self._ai_debug_bus_send('new_trace', {
            'type': 'new_trace',
            'trace_id': trace_id,
            'session_id': (
                self.id if len(self) == 1 else direct_trace.get('session_id')
            ),
            'parent_trace_id': self.env.context.get('ai_parent_trace_id'),
            'parent_tool_call_id': self.env.context.get('ai_parent_tool_call_id'),
            **{key: value for key, value in direct_trace.items() if key.startswith('parent_')},
            'user_query': self._ai_debug_text_from_parts(message),
            'instructions': instructions,
            'agent_name': (
                self.agent_id.name
                if len(self) == 1 and self.agent_id
                else direct_trace.get('agent_name')
            ),
            'trace_kind': direct_trace.get('trace_kind'),
            'trace_label': direct_trace.get('trace_label'),
            'state_snapshot': {
                'uid': self.env.uid,
                'company_id': self.env.company.id,
                'res_model': tools_context.get('res_model'),
                'res_id': tools_context.get('res_id'),
            },
        })
        termination_reason = 'success'
        termination_error = None
        completed = False

        try:
            for item in super()._run_agentic_loop(
                instructions, message,
                tools_context=tools_context, record=record,
                **completion_options,
            ):
                if 'tool_calls' in item or 'final_message' in item:
                    iteration_count += 1
                    prepared_id = _debug_ctx.pop('prepared_iteration_id', None)
                    iteration_id = prepared_id or uuid.uuid4().hex
                    _debug_ctx['iteration_id'] = iteration_id
                    duration_ms = _debug_ctx.pop('model_duration_ms', None) if prepared_id else None
                    parts = item.get('tool_calls') or item.get('final_message') or []
                    normalized_response = self._ai_debug_normalized_messages([{
                        'role': 'assistant',
                        'content': parts,
                    }])
                    self._ai_debug_bus_send('iteration', {
                        'type': 'iteration',
                        'trace_id': trace_id,
                        'iteration_id': iteration_id,
                        'iteration_index': iteration_count,
                        'request_body': _debug_ctx.get('request_body') if prepared_id else None,
                        'raw_response': _debug_ctx.pop('raw_response', normalized_response) if prepared_id else normalized_response,
                        'response_summary': self._ai_debug_message_summary([{
                            'role': 'assistant',
                            'content': parts,
                        }]),
                        'has_tool_calls': 'tool_calls' in item,
                        'is_final': 'final_message' in item,
                        'duration_ms': duration_ms,
                        'duration_kind': 'model_round_trip' if duration_ms is not None else None,
                    })
                    if 'final_message' in item:
                        completed = True
                yield item

            if not completed:
                termination_reason = 'error'
                termination_error = 'no_final_response'

        except UserError as e:
            termination_reason = 'max_iterations' if 'successive' in str(e).lower() else 'error'
            termination_error = type(e).__name__
            iteration_count += 1
            self._ai_debug_bus_send('iteration', {
                'type': 'iteration',
                'trace_id': trace_id,
                'iteration_id': uuid.uuid4().hex,
                'iteration_index': iteration_count,
                'error': termination_error,
                'has_tool_calls': False,
                'is_final': False,
            })
            raise

        except Exception as e:
            termination_reason = 'error'
            termination_error = type(e).__name__
            iteration_count += 1
            self._ai_debug_bus_send('iteration', {
                'type': 'iteration',
                'trace_id': trace_id,
                'iteration_id': uuid.uuid4().hex,
                'iteration_index': iteration_count,
                'error': termination_error,
                'has_tool_calls': False,
                'is_final': False,
            })
            raise

        finally:
            self._ai_debug_bus_send('loop_end', {
                'type': 'loop_end',
                'trace_id': trace_id,
                'termination_reason': termination_reason,
                'error': termination_error,
                'iteration_count': iteration_count,
                'tool_call_count': _debug_ctx['tool_call_count'],
                'duration_ms': int((time.monotonic() - started_at) * 1000),
            })

    def _handle_tool_calls(self, tool_calls, tools_by_name, tools_context, record,
            pending_tool_response=None, previous_results=None):
        """Observe tool calls without changing Enterprise execution semantics.

        The synchronous loop keeps its existing immediate events:
          - tool_call_started: fired BEFORE super() delegation with tool name, args, and a
            stable tool_call_id UUID (pre-generated so started and completed share the same ID)
          - tool_call_completed: fired AFTER super() yields tool_results with the same
            tool_call_id, result, success, and error fields

        The callback path instead buffers committed-tip tool items. Its authoritative
        apply/resume wrappers flush them only after the parent reducer succeeds and the
        corresponding iteration has been queued.

        Also injects ai_parent_trace_id into env.context so any subagent sessions spawned
        during tool execution can identify their parent trace in their new_trace bus event.

        State capture (state_before/state_after via deepcopy) is disabled — no built-in
        Odoo AI tool modifies tools_context['state'], so the diff is always empty. The
        commented-out lines can be re-enabled if custom tools begin mutating state.

        Without either private debugger context, delegate without instrumentation.
        """
        _debug_ctx = self.env.context.get('_debug_ctx')
        callback_context = (
            self._ai_debug_active_callback_context()
            if not _debug_ctx
            else None
        )
        tool_timings = callback_context['tool_timings'] if callback_context else {}
        if callback_context or _debug_ctx:
            def time_tool(call_id):
                return self._ai_debug_time_tool(tool_timings, call_id, durable=bool(callback_context))
            tools_by_name = {name: tool.with_context(_ai_debug_tool_timer=time_tool)
                             for name, tool in tools_by_name.items()}
        if callback_context:
            tools_context['_debug_trace_id'] = callback_context['trace_id']
            yield from self._ai_debug_buffer_callback_tool_items(
                super()._handle_tool_calls(
                    tool_calls, tools_by_name, tools_context, record,
                    pending_tool_response=pending_tool_response,
                    previous_results=previous_results,
                ),
                tool_calls,
                tools_context,
                callback_context,
            )
            return
        if not _debug_ctx:
            # Instrumentation not active — skip all overhead
            yield from super()._handle_tool_calls(
                tool_calls, tools_by_name, tools_context, record,
                pending_tool_response=pending_tool_response,
                previous_results=previous_results,
            )
            return

        # Thread parent trace ID via tools_context (mutable dict passed to tool functions)
        # rather than env.context, because tool records (ir.actions.server) are fetched
        # before _run_agentic_loop sets _debug_ctx, so they never carry _debug_ctx in
        # their env. tools_context reaches the agent via the
        # tool_context parameter in _ai_tool_request_sub_agent.
        tools_context['_debug_trace_id'] = _debug_ctx['trace_id']

        # State capture disabled — no built-in Odoo AI tool modifies
        # tools_context['state'], so the diff is always empty.
        # state_before_batch = copy.deepcopy(tools_context.get('state') or {})

        # Build a call_id -> tool_call lookup so confirmation events (which only
        # carry call_id) can recover tool_name and args from the original request.
        tool_calls_by_id = {tc['call_id']: tc for tc in tool_calls}

        # Pre-generate stable tool_call_id UUIDs keyed by LLM call_id.
        # Same UUID is used in tool_call_started and tool_call_completed events
        # so the JS can link them together.
        _tc_id_map = {tc['call_id']: uuid.uuid4().hex for tc in tool_calls}

        # Emit tool_call_started for each tool in the batch — fires BEFORE
        # tool execution begins. This ensures the parent tool call node exists
        # in the JS tree before any subagent trace event arrives.
        for tc in tool_calls:
            self._ai_debug_bus_send('tool_call_started', {
                'type': 'tool_call_started',
                'trace_id': _debug_ctx['trace_id'],
                'iteration_id': _debug_ctx['iteration_id'],
                'tool_call_id': _tc_id_map[tc['call_id']],
                'call_id': tc['call_id'],
                'tool_name': tc['name'],
                'args': tc.get('args', {}),
            })

        for item in super()._handle_tool_calls(
            tool_calls, tools_by_name, tools_context, record,
            pending_tool_response=pending_tool_response,
            previous_results=previous_results,
        ):
            progress = self._ai_debug_try(lambda: self._ai_debug_tool_progress(item))
            if progress:
                self._ai_debug_bus_send('tool_call_progress', {
                    'type': 'tool_call_progress', 'trace_id': _debug_ctx['trace_id'],
                    'iteration_id': _debug_ctx['iteration_id'],
                    'tool_call_id': _tc_id_map[tools_context['tool_call_id']], **progress,
                })
            if tool_results := item.get('tool_results'):
                # state_after_batch = copy.deepcopy(tools_context.get('state') or {})

                for result_item in tool_results:
                    tool_call_data = self._ai_debug_tool_call_from_result(
                        tool_calls, result_item,
                    )
                    tool_name = tool_call_data.get('name')
                    call_id = tool_call_data.get('call_id')  # LLM's original call ID
                    result = result_item.get('result')
                    success = result_item.get('success', True)
                    error = str(result) if not success and result is not None else None

                    _debug_ctx['tool_call_count'] += 1

                    self._ai_debug_bus_send('tool_call_completed', {
                        'type': 'tool_call_completed',
                        'trace_id': _debug_ctx['trace_id'],
                        'iteration_id': _debug_ctx['iteration_id'],
                        'tool_call_id': _tc_id_map.get(call_id, uuid.uuid4().hex),
                        'call_id': call_id,
                        'tool_name': tool_name,
                        'result': result,
                        'success': success,
                        'error': error,
                        'duration_ms': self._ai_debug_tool_duration(tool_timings, call_id),
                    })

            elif (
                (pending_tool_call := item.get('pending_tool_call'))
                and (
                    user_input_request := item.get('user_input_request') or {}
                ).get('type') == 'confirmation'
            ):
                call_id = pending_tool_call.get('call_id')
                originating_tc = tool_calls_by_id.get(call_id, {})
                _debug_ctx['tool_call_count'] += 1

                self._ai_debug_bus_send('tool_call_completed', {
                    'type': 'tool_call_completed',
                    'trace_id': _debug_ctx['trace_id'],
                    'iteration_id': _debug_ctx['iteration_id'],
                    'tool_call_id': _tc_id_map.get(call_id, uuid.uuid4().hex),
                    'call_id': call_id,
                    'tool_name': originating_tc.get('name', 'unknown'),
                    'args': originating_tc.get('args', {}),
                    'result': None,
                    'success': None,
                    'error': None,
                    'triggered_confirmation': True,
                    'confirmation_message': user_input_request.get('body', ''),
                    'duration_ms': None,
                })

            yield item
