import copy
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
    "set_cookie",
    "thought_signature",
}
_SENSITIVE_KEY_NAMES = frozenset(key.replace('_', '') for key in _SENSITIVE_KEYS)


class AiSession(models.Model):
    _inherit = 'ai.session'

    def _ai_debug_bus_send(self, notification_type, payload, *, target_user_id=None):
        """Publish sanitized facts only after the enclosing transaction commits.

        The Bus row is inserted in the current transaction, so both full and
        savepoint rollbacks remove it.  Only the lightweight PostgreSQL wake-up
        remains post-commit; a stale wake-up has no row to deliver.  Payload
        building and Bus writes run in a savepoint so debugger failures cannot
        poison the business transaction.
        """
        try:
            with self.env.cr.savepoint(flush=False):
                target_user_id = target_user_id or self.env.uid
                target_user = self.env['res.users'].sudo().browse(target_user_id).exists()
                if not target_user or not target_user._is_internal():
                    return
                sanitized_payload = self._ai_debug_sanitize(payload)
                encoded = json.dumps(sanitized_payload, ensure_ascii=False, separators=(",", ":"))
                if len(encoded.encode()) > _MAX_EVENT_BYTES:
                    correlation_keys = (
                        'type', 'trace_id', 'exchange_uuid', 'request_uuid',
                        'round_no', 'iteration_id', 'iteration_index',
                        'session_id', 'request_state', 'is_final', 'error', 'duration_ms',
                        'duration_kind', 'termination_reason', 'iteration_count',
                        'tool_call_count', 'provider', 'model_name', 'provider_api',
                    )
                    sanitized_payload = {
                        key: self._ai_debug_sanitize(payload[key], key=key)
                        for key in correlation_keys
                        if key in payload
                    }
                    sanitized_payload.setdefault('type', notification_type)
                    sanitized_payload['_payload_excluded'] = True

                bus = self.env['bus.bus'].sudo()
                channel = channel_with_db(self.env.cr.dbname, target_user)
                bus_row = bus.create({
                    'channel': json_dump(channel),
                    'message': json_dump({
                        'type': notification_type,
                        'payload': sanitized_payload,
                    }),
                })
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

                channels.add(channel)

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

                rows.append((bus_row.id, target_user.id))
        except Exception:
            _logger.exception("ai_debug: failed to queue bus event '%s'", notification_type)

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
        """Run one instrumentation-only builder inside a recoverable savepoint."""
        try:
            with self.env.cr.savepoint(flush=False):
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
                    content = part.get('content') or {}
                    mime = (
                        content.get('mimetype')
                        or content.get('mimeType')
                        or content.get('mime_type')
                        or ''
                    )
                    if self._ai_debug_is_image_type(mime):
                        normalized_parts.append({
                            **{key: value for key, value in part.items() if key != 'content'},
                            'content': self._ai_debug_image_data(mime, content.get('data', '')),
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

    def _ai_debug_normalized_part(self, part, *, depth=0):
        """Allowlist one Enterprise message part without provider continuity blobs."""
        if not isinstance(part, dict) or depth >= _MAX_DEPTH:
            return {'_details_excluded': True}
        part_type = part.get('type')
        if part_type == 'text':
            content = part.get('content') or {}
            normalized = {
                'type': 'text',
                'content': {
                    'data': self._ai_debug_sanitize(
                        content.get('data') if isinstance(content, dict) else None,
                        key='data',
                    ),
                },
            }
            if 'sources' in part:
                normalized['sources'] = self._ai_debug_sanitize(part['sources'], key='sources')
            if 'provider_data' in part:
                normalized['_provider_data_excluded'] = True
            return normalized
        if part_type == 'inline_data':
            content = part.get('content') or {}
            mime = ''
            data = None
            if isinstance(content, dict):
                mime = (
                    content.get('mimetype')
                    or content.get('mimeType')
                    or content.get('mime_type')
                    or ''
                )
                data = content.get('data')
            image = self._ai_debug_image_data(mime, data)
            normalized_content = {'mimetype': mime}
            if image.get('data'):
                normalized_content['data'] = image['data']
            else:
                normalized_content['_binary_excluded'] = True
            normalized = {'type': 'inline_data', 'content': normalized_content}
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
            content = part.get('content') or {}
            text = content.get('data') if isinstance(content, dict) else None
            if isinstance(text, str):
                text_parts.append(text)
        return '\n'.join(text_parts)

    def _ai_debug_user_query(self, request):
        """Return the durable exchange prompt without its appended Odoo context."""
        if request.origin_message_id:
            query = html2plaintext(
                request.origin_message_id.body or '', include_references=False,
            ).strip()
            if query:
                return query
        for message in reversed((request.payload or {}).get('messages') or []):
            if not isinstance(message, dict) or message.get('role') != 'user':
                continue
            query_parts = []
            for part in message.get('content') or []:
                text = self._ai_debug_text_from_parts([part])
                if text and not text.lstrip().startswith('<odoo_current_context>'):
                    query_parts.append(text)
            if query_parts:
                return '\n'.join(query_parts).strip()
        return ''

    def _ai_debug_normalized_request(self, request):
        """Rebuild the credential-free normalized payload submitted to IAP."""
        payload = copy.deepcopy(request.payload or {})
        normalized = {
            'request_uuid': request.request_uuid,
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
        """Copy the authoritative fetched IAP envelope and bound binary parts."""
        if not isinstance(response, dict):
            return {'_details_excluded': True}
        normalized = {
            key: self._ai_debug_sanitize(response.get(key), key=key)
            for key in ('request_uuid', 'status', 'error')
            if key in response
        }
        if isinstance(response.get('result'), dict):
            normalized['result'] = self._ai_debug_normalized_message(response['result'])
        return normalized

    @staticmethod
    def _ai_debug_request_duration_ms(request):
        """Measure durable request creation through its latest committed transition."""
        if not request.create_date or not request.write_date:
            return None
        return max(0, round((request.write_date - request.create_date).total_seconds() * 1000))

    def _ai_debug_trace_request_prepared(self, request):
        """Queue the single exchange trace created by a durable first round."""
        self.ensure_one()
        request.ensure_one()
        if request.round_no != 1:
            return
        payload = request.payload or {}
        self._ai_debug_bus_send('new_trace', {
            'type': 'new_trace',
            'trace_id': request.exchange_uuid,
            'exchange_uuid': request.exchange_uuid,
            'request_uuid': request.request_uuid,
            'round_no': request.round_no,
            'request_state': request.state,
            'session_id': self.id,
            'agent_name': self.agent_id.name if self.agent_id else None,
            'user_query': self._ai_debug_user_query(request),
            'instructions': payload.get('instructions') or '',
            'state_snapshot': {
                'request_state': request.state,
                'round_limit': request.round_limit,
                'message_summary': self._ai_debug_message_summary(payload.get('messages')),
            },
        }, target_user_id=request.user_id.id)

    def _ai_debug_trace_request_result(self, request, response, outcome, previous_state):
        """Queue authoritative request facts accepted by `_apply_iap_response`."""
        current_state = request.state
        if current_state != previous_state:
            self._ai_debug_bus_send('request_state', {
                'type': 'request_state',
                'trace_id': request.exchange_uuid,
                'exchange_uuid': request.exchange_uuid,
                'request_uuid': request.request_uuid,
                'round_no': request.round_no,
                'previous_state': previous_state,
                'state': current_state,
            }, target_user_id=request.user_id.id)

        if not outcome.get('applied') or previous_state in ('done', 'failed'):
            return
        if current_state not in ('done', 'failed'):
            return

        normalized_request = self._ai_debug_normalized_request(request)
        normalized_response = self._ai_debug_normalized_response(response)
        result = normalized_response.get('result') if isinstance(normalized_response, dict) else None
        provider_metadata = result.get('provider_metadata') or {} if isinstance(result, dict) else {}
        content = result.get('content') or [] if isinstance(result, dict) else []
        has_tool_calls = any(
            isinstance(part, dict) and part.get('type') == 'tool_call'
            for part in content
        )
        error = request.error or None
        duration_ms = self._ai_debug_request_duration_ms(request)
        self._ai_debug_bus_send('iteration', {
            'type': 'iteration',
            'trace_id': request.exchange_uuid,
            'exchange_uuid': request.exchange_uuid,
            'request_uuid': request.request_uuid,
            'round_no': request.round_no,
            'iteration_id': request.request_uuid,
            'iteration_index': request.round_no,
            'request_body': normalized_request,
            'request_label': 'Normalized IAP Submission',
            'raw_response': normalized_response,
            'response_label': 'Normalized IAP Result',
            'has_tool_calls': has_tool_calls,
            'is_final': current_state == 'done',
            'error': error,
            'request_state': current_state,
            'provider': provider_metadata.get('provider'),
            'model_name': provider_metadata.get('model'),
            'provider_api': provider_metadata.get('api'),
            'duration_ms': duration_ms,
            'duration_kind': 'request_lifecycle',
        }, target_user_id=request.user_id.id)
        self._ai_debug_bus_send('loop_end', {
            'type': 'loop_end',
            'trace_id': request.exchange_uuid,
            'exchange_uuid': request.exchange_uuid,
            'request_uuid': request.request_uuid,
            'round_no': request.round_no,
            'termination_reason': 'success' if current_state == 'done' else 'error',
            'error': error,
            'iteration_count': request.round_no,
            'tool_call_count': 0,
            'duration_ms': duration_ms,
            'duration_kind': 'request_lifecycle',
        }, target_user_id=request.user_id.id)

    def _apply_iap_response(self, request, response, *, try_lock=False):
        """Trace only durable results that the Enterprise ledger actually accepts."""
        previous_state = request.state
        outcome = super()._apply_iap_response(request, response, try_lock=try_lock)
        self._ai_debug_try(
            lambda: self._ai_debug_trace_request_result(
                request, response, outcome, previous_state,
            )
        )
        return outcome

    def _generate_next_response(self, message, pending_tool_response=None):
        """Keep the synchronous stateful entry point signature compatible."""
        yield from super()._generate_next_response(message, pending_tool_response=pending_tool_response)

    @api.model
    def _get_direct_response(self, instructions, message, tools=None,
            record=None, agent_id=None, tool_results_collector=None, **completion_options):
        """Preserve current one-shot callers while `_run_agentic_loop` traces them."""
        return super()._get_direct_response(
            instructions, message, tools=tools, record=record, agent_id=agent_id,
            tool_results_collector=tool_results_collector,
            **completion_options,
        )

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
        self._ai_debug_bus_send('new_trace', {
            'type': 'new_trace',
            'trace_id': trace_id,
            'session_id': self.id if len(self) == 1 else None,
            'parent_trace_id': self.env.context.get('ai_parent_trace_id'),
            'parent_tool_call_id': self.env.context.get('ai_parent_tool_call_id'),
            'agent_name': self.agent_id.name if len(self) == 1 and self.agent_id else None,
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
                    iteration_id = uuid.uuid4().hex
                    _debug_ctx['iteration_id'] = iteration_id
                    parts = item.get('tool_calls') or item.get('final_message') or []
                    self._ai_debug_bus_send('iteration', {
                        'type': 'iteration',
                        'trace_id': trace_id,
                        'iteration_id': iteration_id,
                        'iteration_index': iteration_count,
                        'response_summary': self._ai_debug_message_summary([{
                            'role': 'assistant',
                            'content': parts,
                        }]),
                        'has_tool_calls': 'tool_calls' in item,
                        'is_final': 'final_message' in item,
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
            pending_tool_response=None, refuse_all=False):
        """Override to emit tool_call_started and tool_call_completed bus events per tool.

        Each tool call emits two events:
          - tool_call_started: fired BEFORE super() delegation with tool name, args, and a
            stable tool_call_id UUID (pre-generated so started and completed share the same ID)
          - tool_call_completed: fired AFTER super() yields tool_results with the same
            tool_call_id, result, success, and error fields

        Also injects ai_parent_trace_id into env.context so any subagent sessions spawned
        during tool execution can identify their parent trace in their new_trace bus event.

        State capture (state_before/state_after via deepcopy) is disabled — no built-in
        Odoo AI tool modifies tools_context['state'], so the diff is always empty. The
        commented-out lines can be re-enabled if custom tools begin mutating state.

        If _debug_ctx is not in context (instrumentation not active), delegates to super()
        without any instrumentation overhead.
        """
        _debug_ctx = self.env.context.get('_debug_ctx')
        if not _debug_ctx:
            # Instrumentation not active — skip all overhead
            yield from super()._handle_tool_calls(
                tool_calls, tools_by_name, tools_context, record,
                pending_tool_response, refuse_all,
            )
            return

        # Thread parent trace ID via tools_context (mutable dict passed to tool functions)
        # rather than env.context, because tool records (ir.actions.server) are fetched
        # in _generate_next_response BEFORE _run_agentic_loop sets _debug_ctx, so they
        # never carry _debug_ctx in their env. tools_context reaches the agent via the
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

        # Record start time per call_id just before tool execution begins.
        # For batch execution these are all the same moment, giving us the
        # aggregate duration from batch start to each individual result.
        _tc_start_times = {tc['call_id']: time.monotonic() for tc in tool_calls}

        for item in super()._handle_tool_calls(
            tool_calls, tools_by_name, tools_context, record,
            pending_tool_response, refuse_all,
        ):
            if tool_results := item.get('tool_results'):
                # state_after_batch = copy.deepcopy(tools_context.get('state') or {})

                for result_item in tool_results:
                    tool_call_data = result_item.get('tool_call', {})
                    tool_name = tool_call_data.get('name')
                    call_id = tool_call_data.get('call_id')  # LLM's original call ID
                    result = result_item.get('result')
                    success = result_item.get('success', True)
                    error = str(result) if not success and result is not None else None

                    _debug_ctx['tool_call_count'] += 1

                    _tc_start = _tc_start_times.get(call_id, time.monotonic())
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
                        'duration_ms': int((time.monotonic() - _tc_start) * 1000),
                    })

            elif confirmation := item.get('tool_confirmation_request'):
                call_id = confirmation.get('call_id')
                originating_tc = tool_calls_by_id.get(call_id, {})
                _debug_ctx['tool_call_count'] += 1

                _tc_start = _tc_start_times.get(call_id, time.monotonic())
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
                    'confirmation_message': confirmation.get('message', ''),
                    'duration_ms': int((time.monotonic() - _tc_start) * 1000),
                })

            yield item
