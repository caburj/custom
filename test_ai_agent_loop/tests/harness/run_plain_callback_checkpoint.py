#!/usr/bin/env python3
"""Run hermetic paired Enterprise/IAP callback checkpoints."""

import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests


CUSTOM = Path(__file__).resolve().parents[3]
ENTERPRISE = Path('/Users/joseph/.wt/worktrees/odoo/enterprise/master-ai-callback-driven-loop')
CORE = Path('/Users/joseph/.wt/worktrees/odoo/odoo/master-odoo-ai-iap-service-lba')
IAP_CORE = Path('/Users/joseph/.wt/worktrees/odoo/odoo/saas-19.4-odoo-ai-iap-service-lba')
IAP_ENTERPRISE = Path('/Users/joseph/.wt/worktrees/odoo/enterprise/saas-19.4-odoo-ai-iap-service-lba')
IAP_APPS = Path('/Users/joseph/.wt/worktrees/odoo/iap-apps/saas-19.4-odoo-ai-async-jcb')
HARNESS_ADDONS = CUSTOM / 'test_ai_agent_loop/tests/harness_addons'
MASTER_PYTHON = Path('/Users/joseph/.venvs/master/bin/python3')
IAP_PYTHON = Path('/Users/joseph/.venvs/saas-19.4/bin/python3')
RUN_SUFFIX = uuid.uuid4().hex[:8]
CONSUMER_DB = f'ai_callback_consumer_test_{RUN_SUFFIX}'
IAP_DB = f'ai_callback_iap_test_{RUN_SUFFIX}'
CONSUMER_PORT = 18269
CONSUMER_GEVENT_PORT = 18272
IAP_PORT = 18270
IAP_EVENTED_PORT = 18273
PROVIDER_PORT = 18280
CALLBACK_SHIM_PORT = 18281
CONSUMER_URL = f'http://127.0.0.1:{CONSUMER_PORT}'
IAP_URL = f'http://127.0.0.1:{IAP_PORT}'
IAP_EVENTED_URL = f'http://127.0.0.1:{IAP_EVENTED_PORT}'
PROVIDER_URL = f'http://127.0.0.1:{PROVIDER_PORT}'
CALLBACK_SHIM_URL = f'http://127.0.0.1:{CALLBACK_SHIM_PORT}'
PLAIN_SCENARIO = 'plain'
SERVER_TOOL_SCENARIO = 'server-tool'
CONFIRMATION_TOOLS_SCENARIO = 'confirmation-tools'
QUESTION_SCENARIO = 'question'
TOOL_FAILURE_SCENARIO = 'tool-failure'
TERMINAL_ERROR_SCENARIO = 'terminal-error'
SERVER_TOOL_NAME = 'ai_tool_callback_count_contacts'
QUESTION_TOOL_NAME = 'ai_tool_ask_user_question'
LOAD_SKILLS_TOOL_NAME = 'ai_tool_load_skills'
CREATE_TOOL_NAME = 'ai_tool_create_records'
UPDATE_TOOL_NAME = 'ai_tool_update_records'
LOOPBACK_PORTS = {
    'consumer HTTP': CONSUMER_PORT,
    'consumer gevent': CONSUMER_GEVENT_PORT,
    'IAP HTTP': IAP_PORT,
    'IAP evented': IAP_EVENTED_PORT,
    'fake provider': PROVIDER_PORT,
    'callback shim': CALLBACK_SHIM_PORT,
}


def append_jsonl(path, payload):
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(payload, sort_keys=True) + '\n')


class LoopbackState:
    def __init__(self, evidence_dir, scenario):
        self.provider_journal = evidence_dir / 'provider-requests.jsonl'
        self.callback_journal = evidence_dir / 'callback-shim.jsonl'
        self.scenario = scenario
        self.confirmation_skill_ids = []


class ProviderHandler(BaseHTTPRequestHandler):
    state = None

    def do_GET(self):
        if self.path != '/ready':
            self.send_error(404)
            return
        self._json(200, {'ready': True})

    def do_POST(self):
        if self.path != '/completion':
            self.send_error(404)
            return
        payload = self._read_json()
        append_jsonl(self.state.provider_journal, {
            'messages': payload.get('messages'),
            'instructions': payload.get('instructions'),
            'tools': payload.get('tools'),
            'options': payload.get('options'),
        })
        if self.state.scenario == TERMINAL_ERROR_SCENARIO:
            self._json(500, {'error': 'fixture provider failure'})
            return
        if self.state.scenario == TOOL_FAILURE_SCENARIO:
            has_tool_result = any(
                part.get('type') == 'tool_results'
                for message in payload.get('messages') or ()
                for part in message.get('content') or ()
            )
            if has_tool_result:
                result = {
                    'role': 'assistant',
                    'content': [{
                        'type': 'text',
                        'content': {
                            'data': 'I could not run the requested tool.',
                        },
                    }],
                }
            else:
                result = {
                    'role': 'assistant',
                    'content': [{
                        'type': 'tool_call',
                        'call_id': 'missing-callback-harness-tool',
                        'name': 'ai_tool_callback_missing',
                        'args': {},
                    }],
                }
        elif self.state.scenario == CONFIRMATION_TOOLS_SCENARIO:
            available_tool_names = {
                tool.get('name') for tool in payload.get('tools') or ()
            }
            completed_tool_names = {
                part['tool_results']['tool_call']['name']
                for message in payload.get('messages') or ()
                for part in message.get('content') or ()
                if part.get('type') == 'tool_results'
            }
            if not {CREATE_TOOL_NAME, UPDATE_TOOL_NAME}.issubset(
                available_tool_names,
            ):
                result = {
                    'role': 'assistant',
                    'content': [{
                        'type': 'tool_call',
                        'call_id': 'load-callback-confirmation-skills',
                        'name': LOAD_SKILLS_TOOL_NAME,
                        'args': {
                            'skill_ids': self.state.confirmation_skill_ids,
                        },
                    }],
                }
            elif {CREATE_TOOL_NAME, UPDATE_TOOL_NAME} & completed_tool_names:
                result = {
                    'role': 'assistant',
                    'content': [{
                        'type': 'text',
                        'content': {
                            'data': 'The callback confirmation tools completed.',
                        },
                    }],
                }
            else:
                result = {
                    'role': 'assistant',
                    'content': [
                        {
                            'type': 'tool_call',
                            'call_id': 'create-callback-harness-contact',
                            'name': CREATE_TOOL_NAME,
                            'args': {
                                'explanation': 'Create the callback harness contact?',
                                'model_name': 'res.partner',
                                'preview_menu_id': False,
                                'values': [{
                                    'field_values': [{
                                        'field': 'name',
                                        'value': 'Callback Harness Created',
                                    }],
                                }],
                            },
                        },
                        {
                            'type': 'tool_call',
                            'call_id': 'update-callback-harness-contact',
                            'name': UPDATE_TOOL_NAME,
                            'args': {
                                'explanation': 'Rename the callback harness contact?',
                                'preview_menus': [],
                                'updates': [{
                                    'model_name': 'res.partner',
                                    'domain': (
                                        "[('name', '=', "
                                        "'Callback Harness Before Update')]"
                                    ),
                                    'changes': [{
                                        'field': 'name',
                                        'value': 'Callback Harness After Update',
                                    }],
                                }],
                            },
                        },
                    ],
                }
        elif self.state.scenario == QUESTION_SCENARIO:
            question_results = [
                part['tool_results']
                for message in payload.get('messages') or ()
                for part in message.get('content') or ()
                if part.get('type') == 'tool_results'
                and part['tool_results']['tool_call']['name'] == QUESTION_TOOL_NAME
            ]
            if question_results:
                result = {
                    'role': 'assistant',
                    'content': [{
                        'type': 'text',
                        'content': {'data': 'You selected Draft.'},
                    }],
                }
            else:
                result = {
                    'role': 'assistant',
                    'content': [{
                        'type': 'tool_call',
                        'call_id': 'callback-harness-question',
                        'name': QUESTION_TOOL_NAME,
                        'args': {
                            'question': 'Do you prefer Draft or Send?',
                            'choices': ['Draft', 'Send'],
                            'multi_select': False,
                            'allow_free_text': False,
                        },
                    }],
                }
        elif self.state.scenario == SERVER_TOOL_SCENARIO:
            has_tool_result = any(
                part.get('type') == 'tool_results'
                for message in payload.get('messages') or ()
                for part in message.get('content') or ()
            )
            if has_tool_result:
                result = {
                    'role': 'assistant',
                    'content': [{
                        'type': 'text',
                        'content': {
                            'data': 'You have one callback harness contact.',
                        },
                    }],
                }
            else:
                result = {
                    'role': 'assistant',
                    'content': [{
                        'type': 'tool_call',
                        'call_id': 'count-callback-harness-contacts',
                        'name': SERVER_TOOL_NAME,
                        'args': {},
                    }],
                }
        else:
            result = {
                'role': 'assistant',
                'content': [{
                    'type': 'text',
                    'content': {'data': 'Hello from the paired fake provider.'},
                }],
            }
        self._json(200, {'result': result})

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length) or b'{}')

    def _json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format, *_args):
        return


class CallbackShimHandler(ProviderHandler):
    def do_POST(self):
        if self.path != '/ai/completion_result_ready':
            self.send_error(404)
            return
        payload = self._read_json()
        params = payload.get('params') or {}
        response = requests.post(
            CONSUMER_URL + '/ai/completion_result_ready',
            json=payload,
            timeout=15,
            allow_redirects=False,
        )
        append_jsonl(self.state.callback_journal, {
            'request_uuid': params.get('request_uuid'),
            'forwarded_to': CONSUMER_URL + '/ai/completion_result_ready',
            'consumer_status': response.status_code,
        })
        self._json(response.status_code, response.json())


def start_loopback_server(port, handler, state):
    handler.state = state
    server = ThreadingHTTPServer(('127.0.0.1', port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def require_free_loopback_ports():
    """Fail before database setup when another process owns a harness port."""
    for label, port in LOOPBACK_PORTS.items():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            # Match the servers' restart behavior: a recently closed connection
            # in TIME_WAIT is safe, while an active listener still rejects bind.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(('127.0.0.1', port))
            except OSError as error:
                raise RuntimeError(
                    f'{label} port {port} is already in use; refusing to '
                    'accept readiness from an unrelated process'
                ) from error


def require_processes_alive(processes):
    dead = [
        f'{name} (exit {process.returncode})'
        for name, process in processes
        if process.poll() is not None
    ]
    if dead:
        raise RuntimeError(f'Owned harness process exited: {", ".join(dead)}')


def wait_json(
    url, predicate=lambda payload: True, timeout=45, *, process=None,
    process_name=None,
):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(
                f'Owned {process_name} process exited with code '
                f'{process.returncode} while waiting for {url}'
            )
        try:
            response = requests.get(url, timeout=2)
            response.raise_for_status()
            payload = response.json() if response.content else {}
            if predicate(payload):
                return payload
        except Exception as error:  # noqa: BLE001
            last_error = error
        time.sleep(0.2)
    raise RuntimeError(f'Timed out waiting for {url}: {last_error}')


def start_process(command, cwd, log_path):
    stream = log_path.open('wb')
    process = subprocess.Popen(
        command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
    )
    return process, stream


def json_post(url, payload, session=None):
    response = (session or requests).post(url, json=payload, timeout=15)
    response.raise_for_status()
    return response.json() if response.content else {}


def jsonrpc_post(url, params, session=None):
    response = (session or requests).post(
        url,
        json={
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'call',
            'params': params,
        },
        timeout=15,
    )
    response.raise_for_status()
    return response, response.json()


def resume_pending_confirmation(session, channel_id, status):
    _response, payload = jsonrpc_post(
        CONSUMER_URL + '/ai/resume_pending_interaction',
        {
            'channel_id': channel_id,
            'request_uuid': status['request_uuid'],
            'resume_token': status['resume_token'],
            'response': {'value': 'confirm_once'},
        },
        session=session,
    )
    if payload.get('error'):
        raise RuntimeError(f'Confirmation resume failed: {payload["error"]}')
    return payload['result']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--scenario', choices=(
            PLAIN_SCENARIO,
            SERVER_TOOL_SCENARIO,
            CONFIRMATION_TOOLS_SCENARIO,
            QUESTION_SCENARIO,
            TOOL_FAILURE_SCENARIO,
            TERMINAL_ERROR_SCENARIO,
        ),
        default=PLAIN_SCENARIO,
    )
    scenario = parser.parse_args().scenario
    required = (
        ENTERPRISE, CORE, CUSTOM, IAP_CORE, IAP_ENTERPRISE, IAP_APPS,
        HARNESS_ADDONS, MASTER_PYTHON, IAP_PYTHON,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f'Missing paired harness prerequisites: {missing}')
    require_free_loopback_ports()

    root = Path(tempfile.mkdtemp(prefix=f'ai-callback-{scenario}-'))
    evidence_dir = root / 'evidence'
    runtime_dir = root / 'runtime'
    evidence_dir.mkdir()
    runtime_dir.mkdir()
    print(json.dumps({'phase': 'start', 'runtime_root': str(root)}), flush=True)
    evidence = {
        name: evidence_dir / name
        for name in (
            'consumer-http-state.jsonl',
            'iap-dispatch-state.jsonl',
            'provider-requests.jsonl',
            'callback-shim.jsonl',
        )
    }
    for path in evidence.values():
        path.touch()

    state = LoopbackState(evidence_dir, scenario)
    provider = start_loopback_server(PROVIDER_PORT, ProviderHandler, state)
    shim = start_loopback_server(CALLBACK_SHIM_PORT, CallbackShimHandler, state)
    processes = []
    streams = []
    try:
        for database in (CONSUMER_DB, IAP_DB):
            subprocess.run(['dropdb', '--if-exists', database], check=True)

        consumer_addons = ','.join(map(str, (
            CUSTOM, ENTERPRISE, CORE / 'addons', HARNESS_ADDONS,
        )))
        iap_addons = ','.join(map(str, (
            IAP_CORE / 'addons', IAP_ENTERPRISE,
            IAP_APPS / 'iap_ai', IAP_APPS / 'iap_common',
            IAP_APPS / 'iap_services', IAP_APPS / 'iap_odoo', HARNESS_ADDONS,
        )))
        consumer_init = [
            str(MASTER_PYTHON), str(CORE / 'odoo-bin'), '-d', CONSUMER_DB,
            '-i', 'ai_app,ai_callback_consumer_harness', '--stop-after-init',
            f'--http-port={CONSUMER_PORT}',
            f'--gevent-port={CONSUMER_GEVENT_PORT}', '--workers=0',
            '--addons-path', consumer_addons, '--without-demo',
        ]
        iap_init = [
            str(IAP_PYTHON), str(IAP_CORE / 'odoo-bin'), '-d', IAP_DB,
            '-i', 'odoo_ai', '--stop-after-init', f'--http-port={IAP_PORT}',
            f'--gevent-port={IAP_EVENTED_PORT}', '--workers=0',
            '--addons-path', iap_addons,
            '--load=base,web,odoo_ai,odoo_ai_callback_harness',
            '--without-demo',
        ]
        with (runtime_dir / 'consumer-init.log').open('wb') as stream:
            subprocess.run(
                consumer_init, cwd=ENTERPRISE, stdout=stream,
                stderr=subprocess.STDOUT, check=True,
            )
        with (runtime_dir / 'iap-init.log').open('wb') as stream:
            subprocess.run(
                iap_init, cwd=IAP_APPS, stdout=stream,
                stderr=subprocess.STDOUT, check=True,
            )

        commands = [
            ('consumer', [
                str(MASTER_PYTHON), str(CORE / 'odoo-bin'), '-d', CONSUMER_DB,
                f'--http-port={CONSUMER_PORT}',
                f'--gevent-port={CONSUMER_GEVENT_PORT}', '--workers=0',
                '--addons-path', consumer_addons,
            ], ENTERPRISE),
            ('iap-http', [
                str(IAP_PYTHON), str(IAP_CORE / 'odoo-bin'), '-d', IAP_DB,
                f'--http-port={IAP_PORT}',
                f'--gevent-port={IAP_EVENTED_PORT}', '--workers=0',
                '--addons-path', iap_addons,
                '--load=base,web,odoo_ai,odoo_ai_callback_harness',
            ], IAP_APPS),
            ('iap-evented', [
                str(IAP_PYTHON), str(IAP_CORE / 'odoo-bin'), 'gevent',
                '-d', IAP_DB, f'--gevent-port={IAP_EVENTED_PORT}',
                '--addons-path', iap_addons,
                '--load=base,web,odoo_ai,odoo_ai_callback_harness',
            ], IAP_APPS),
        ]
        for name, command, cwd in commands:
            process, stream = start_process(
                command, cwd, runtime_dir / f'{name}.log',
            )
            processes.append((name, process))
            streams.append(stream)

        owned_processes = dict(processes)
        wait_json(
            CONSUMER_URL + '/web/health?db_server_status=1',
            process=owned_processes['consumer'], process_name='consumer',
        )
        wait_json(
            IAP_URL + '/web/health?db_server_status=1',
            process=owned_processes['iap-http'], process_name='IAP HTTP',
        )
        wait_json(PROVIDER_URL.removesuffix('/completion') + '/ready')
        wait_json(CALLBACK_SHIM_URL + '/ready')
        wait_json(
            IAP_EVENTED_URL + '/odoo_ai_callback_harness/ready',
            lambda payload: payload.get('dispatcher_alive')
            and payload.get('provider_patched'),
            process=owned_processes['iap-evented'], process_name='IAP evented',
        )

        consumer_setup = json_post(
            CONSUMER_URL + '/ai_callback_consumer_harness/setup',
            {'iap_endpoint': IAP_URL, 'scenario': scenario},
        )
        state.confirmation_skill_ids = consumer_setup['confirmation_skill_ids']
        iap_setup = json_post(
            IAP_URL + '/odoo_ai_callback_harness/setup',
            {
                'database_uuid': consumer_setup['database_uuid'],
                'callback_url': CALLBACK_SHIM_URL,
            },
        )
        append_jsonl(evidence['consumer-http-state.jsonl'], {
            'phase': 'setup',
            'channel_id': consumer_setup['channel_id'],
            'session_id': consumer_setup['session_id'],
            'message_id': consumer_setup['message_id'],
        })
        append_jsonl(evidence['iap-dispatch-state.jsonl'], {
            'phase': 'setup', 'database_uuid_matches': bool(iap_setup.get('ready')),
        })

        session = requests.Session()
        _authentication_response, authentication_payload = jsonrpc_post(
            CONSUMER_URL + '/web/session/authenticate',
            {
                'db': CONSUMER_DB, 'login': 'admin', 'password': 'admin',
            },
            session=session,
        )
        if not authentication_payload.get('result', {}).get('uid'):
            raise RuntimeError('Could not authenticate the disposable consumer admin')
        advance_response, advance_payload = jsonrpc_post(
            CONSUMER_URL + '/ai/start_session_advance',
            {
                'channel_id': consumer_setup['channel_id'],
                'mail_message_id': consumer_setup['message_id'],
            },
            session=session,
        )
        if advance_payload.get('error'):
            raise RuntimeError(f'Session advance failed: {advance_payload["error"]}')
        acknowledgement = advance_payload['result']
        request_uuid = acknowledgement['request_uuid']
        append_jsonl(evidence['consumer-http-state.jsonl'], {
            'phase': 'session_advance',
            'http_status': advance_response.status_code,
            'request_uuid': request_uuid,
            'response_state': acknowledgement['responseState'],
        })

        if scenario == CONFIRMATION_TOOLS_SCENARIO:
            confirmation_steps = (
                (
                    'create-callback-harness-contact',
                    {
                        'created_contact_count': 0,
                        'before_update_count': 1,
                        'after_update_count': 0,
                    },
                ),
                (
                    'update-callback-harness-contact',
                    {
                        'created_contact_count': 1,
                        'before_update_count': 1,
                        'after_update_count': 0,
                    },
                ),
            )
            previous_token = None
            first_confirmation_status = None
            for step_number, (expected_call_id, expected_counts) in enumerate(
                confirmation_steps, start=1,
            ):
                deadline = time.monotonic() + 45
                confirmation_status = None
                while time.monotonic() < deadline:
                    require_processes_alive(processes)
                    confirmation_status = json_post(
                        CONSUMER_URL + '/ai_callback_consumer_harness/status',
                        {'session_id': consumer_setup['session_id']},
                    )
                    if (
                        confirmation_status.get('request_state') == 'waiting_input'
                        and confirmation_status.get('pending_call_id') == expected_call_id
                        and confirmation_status.get('resume_token')
                    ):
                        break
                    time.sleep(0.2)
                else:
                    raise RuntimeError(
                        'Consumer did not reach confirmation step '
                        f'{step_number}: {confirmation_status}'
                    )

                for key, expected_value in expected_counts.items():
                    if confirmation_status[key] != expected_value:
                        raise AssertionError(confirmation_status)
                current_token = confirmation_status['resume_token']
                if previous_token is not None and current_token == previous_token:
                    raise AssertionError('Sequential confirmation reused its resume token')
                if step_number == 1:
                    first_confirmation_status = confirmation_status
                else:
                    _stale_response, stale_payload = jsonrpc_post(
                        CONSUMER_URL + '/ai/resume_pending_interaction',
                        {
                            'channel_id': consumer_setup['channel_id'],
                            'request_uuid': first_confirmation_status['request_uuid'],
                            'resume_token': first_confirmation_status['resume_token'],
                            'response': {'value': 'confirm_once'},
                        },
                        session=session,
                    )
                    if not stale_payload.get('error'):
                        raise AssertionError(stale_payload)
                    after_stale_resume = json_post(
                        CONSUMER_URL + '/ai_callback_consumer_harness/status',
                        {'session_id': consumer_setup['session_id']},
                    )
                    if (
                        after_stale_resume['pending_call_id'] != expected_call_id
                        or after_stale_resume['resume_token'] != current_token
                        or any(
                            after_stale_resume[key] != value
                            for key, value in expected_counts.items()
                        )
                    ):
                        raise AssertionError(after_stale_resume)

                resume_acknowledgement = resume_pending_confirmation(
                    session,
                    consumer_setup['channel_id'],
                    confirmation_status,
                )
                append_jsonl(evidence['consumer-http-state.jsonl'], {
                    'phase': f'confirmation-{step_number}',
                    'pending_call_id': expected_call_id,
                    'response_state': resume_acknowledgement['responseState'],
                })
                previous_token = current_token

            if resume_acknowledgement['responseState'] != 'running':
                raise AssertionError(resume_acknowledgement)
        elif scenario == QUESTION_SCENARIO:
            deadline = time.monotonic() + 45
            question_status = None
            while time.monotonic() < deadline:
                require_processes_alive(processes)
                question_status = json_post(
                    CONSUMER_URL + '/ai_callback_consumer_harness/status',
                    {'session_id': consumer_setup['session_id']},
                )
                if (
                    question_status.get('request_state') == 'waiting_input'
                    and question_status.get('pending_call_id')
                    == 'callback-harness-question'
                    and question_status.get('resume_token')
                ):
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError(
                    f'Consumer did not reach the question: {question_status}'
                )
            _resume_response, resume_payload = jsonrpc_post(
                CONSUMER_URL + '/ai/resume_pending_interaction',
                {
                    'channel_id': consumer_setup['channel_id'],
                    'request_uuid': question_status['request_uuid'],
                    'resume_token': question_status['resume_token'],
                    'response': {'values': ['Draft']},
                },
                session=session,
            )
            if resume_payload.get('error'):
                raise RuntimeError(f'Question resume failed: {resume_payload["error"]}')
            if resume_payload['result']['responseState'] != 'running':
                raise AssertionError(resume_payload)

        expected_round_count = (
            3 if scenario == CONFIRMATION_TOOLS_SCENARIO
            else 2 if scenario in (
                SERVER_TOOL_SCENARIO, QUESTION_SCENARIO, TOOL_FAILURE_SCENARIO,
            )
            else 1
        )
        expected_request_state = (
            'failed' if scenario == TERMINAL_ERROR_SCENARIO else 'done'
        )
        deadline = time.monotonic() + 45
        consumer_status = None
        iap_statuses = []
        while time.monotonic() < deadline:
            require_processes_alive(processes)
            consumer_status = json_post(
                CONSUMER_URL + '/ai_callback_consumer_harness/status',
                {'session_id': consumer_setup['session_id']},
            )
            request_uuids = consumer_status.get('request_uuids') or []
            iap_statuses = [
                json_post(
                    IAP_URL + '/odoo_ai_callback_harness/status',
                    {'request_uuid': current_request_uuid},
                )
                for current_request_uuid in request_uuids
            ]
            if (
                len(request_uuids) == expected_round_count
                and consumer_status.get('request_states')
                == [expected_request_state] * expected_round_count
                and all(
                    status.get('callback_state') == 'delivered'
                    for status in iap_statuses
                )
            ):
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(f'Consumer did not reach done: {consumer_status}')
        require_processes_alive(processes)

        if scenario == CONFIRMATION_TOOLS_SCENARIO:
            replayed_callback, replayed_payload = jsonrpc_post(
                CONSUMER_URL + '/ai/completion_result_ready',
                {'request_uuid': request_uuid},
            )
            if replayed_callback.status_code != 200 or replayed_payload.get('result') is not None:
                raise AssertionError(replayed_payload)
            status_after_replay = json_post(
                CONSUMER_URL + '/ai_callback_consumer_harness/status',
                {'session_id': consumer_setup['session_id']},
            )
            if (
                status_after_replay['request_states']
                != ['done'] * expected_round_count
                or status_after_replay['created_contact_count'] != 1
                or status_after_replay['before_update_count'] != 0
                or status_after_replay['after_update_count'] != 1
            ):
                raise AssertionError(status_after_replay)
            consumer_status = status_after_replay

        append_jsonl(evidence['consumer-http-state.jsonl'], {
            'phase': 'terminal', **consumer_status,
        })
        append_jsonl(evidence['iap-dispatch-state.jsonl'], {
            'phase': 'terminal', 'requests': iap_statuses,
        })
        bodies = [message['body'] for message in consumer_status['messages']]
        expected_roles = (
            ['user', 'assistant', 'user', 'assistant', 'user', 'assistant']
            if scenario == CONFIRMATION_TOOLS_SCENARIO
            else ['user', 'assistant', 'user', 'assistant']
            if scenario in (
                SERVER_TOOL_SCENARIO, QUESTION_SCENARIO, TOOL_FAILURE_SCENARIO,
            )
            else ['user']
            if scenario == TERMINAL_ERROR_SCENARIO
            else ['user', 'assistant']
        )
        if consumer_status['event_roles'] != expected_roles:
            raise AssertionError(consumer_status['event_roles'])
        if scenario == SERVER_TOOL_SCENARIO:
            final_text = 'You have one callback harness contact.'
        elif scenario == CONFIRMATION_TOOLS_SCENARIO:
            final_text = 'The callback confirmation tools completed.'
        elif scenario == QUESTION_SCENARIO:
            final_text = 'You selected Draft.'
        elif scenario == TOOL_FAILURE_SCENARIO:
            final_text = 'I could not run the requested tool.'
        elif scenario == TERMINAL_ERROR_SCENARIO:
            final_text = 'Oops, it looks like our AI is unreachable'
        else:
            final_text = 'Hello from the paired fake provider.'
        if not any(final_text in body for body in bodies):
            raise AssertionError(bodies)
        expected_iap_state = (
            'error' if scenario == TERMINAL_ERROR_SCENARIO else 'success'
        )
        if any(
            status.get('state') != expected_iap_state
            for status in iap_statuses
        ):
            raise AssertionError(iap_statuses)
        if consumer_status['round_nos'] != list(range(1, expected_round_count + 1)):
            raise AssertionError(consumer_status['round_nos'])
        provider_requests = [
            json.loads(line)
            for line in evidence['provider-requests.jsonl'].read_text().splitlines()
        ]
        if len(provider_requests) != expected_round_count:
            raise AssertionError(
                f'Expected {expected_round_count} provider executions'
            )
        callback_count = len(
            evidence['callback-shim.jsonl'].read_text().splitlines()
        )
        if callback_count != expected_round_count:
            raise AssertionError(
                f'Expected {expected_round_count} callback deliveries'
            )
        if scenario == SERVER_TOOL_SCENARIO:
            tools = provider_requests[0].get('tools') or []
            if SERVER_TOOL_NAME not in {tool.get('name') for tool in tools}:
                raise AssertionError(tools)
            tool_results = [
                part['tool_results']
                for message in provider_requests[1]['messages']
                for part in message.get('content') or ()
                if part.get('type') == 'tool_results'
            ]
            if (
                len(tool_results) != 1
                or not tool_results[0].get('success')
                or tool_results[0]['result'][0]['content']['data'] != '1'
            ):
                raise AssertionError(tool_results)
        elif scenario == QUESTION_SCENARIO:
            tools = provider_requests[0].get('tools') or []
            if QUESTION_TOOL_NAME not in {tool.get('name') for tool in tools}:
                raise AssertionError(tools)
            question_results = [
                part['tool_results']
                for message in provider_requests[1]['messages']
                for part in message.get('content') or ()
                if part.get('type') == 'tool_results'
                and part['tool_results']['tool_call']['name'] == QUESTION_TOOL_NAME
            ]
            if (
                len(question_results) != 1
                or not question_results[0].get('success')
                or 'USER ANSWER: Draft' not in str(question_results[0]['result'])
            ):
                raise AssertionError(question_results)
        elif scenario == TOOL_FAILURE_SCENARIO:
            tool_results = [
                part['tool_results']
                for message in provider_requests[1]['messages']
                for part in message.get('content') or ()
                if part.get('type') == 'tool_results'
            ]
            if (
                len(tool_results) != 1
                or tool_results[0].get('success')
                or tool_results[0]['tool_call']['call_id']
                != 'missing-callback-harness-tool'
            ):
                raise AssertionError(tool_results)
        elif scenario == CONFIRMATION_TOOLS_SCENARIO:
            initial_tools = provider_requests[0].get('tools') or []
            if LOAD_SKILLS_TOOL_NAME not in {
                tool.get('name') for tool in initial_tools
            }:
                raise AssertionError(initial_tools)
            tools = provider_requests[1].get('tools') or []
            tool_names = {tool.get('name') for tool in tools}
            if not {CREATE_TOOL_NAME, UPDATE_TOOL_NAME}.issubset(tool_names):
                raise AssertionError(tools)
            skill_results = [
                part['tool_results']
                for message in provider_requests[1]['messages']
                for part in message.get('content') or ()
                if part.get('type') == 'tool_results'
                and part['tool_results']['tool_call']['name']
                == LOAD_SKILLS_TOOL_NAME
            ]
            if len(skill_results) != 1 or not skill_results[0].get('success'):
                raise AssertionError(skill_results)
            tool_results = [
                part['tool_results']
                for message in provider_requests[2]['messages']
                for part in message.get('content') or ()
                if part.get('type') == 'tool_results'
                and part['tool_results']['tool_call']['name']
                in (CREATE_TOOL_NAME, UPDATE_TOOL_NAME)
            ]
            if (
                [result['tool_call']['call_id'] for result in tool_results]
                != [
                    'create-callback-harness-contact',
                    'update-callback-harness-contact',
                ]
                or not all(result.get('success') for result in tool_results)
            ):
                raise AssertionError(tool_results)
            if (
                consumer_status['created_contact_count'] != 1
                or consumer_status['before_update_count'] != 0
                or consumer_status['after_update_count'] != 1
            ):
                raise AssertionError(consumer_status)

        print(json.dumps({
            'status': 'passed',
            'scenario': scenario,
            'request_uuid': request_uuid,
            'evidence_dir': str(evidence_dir),
            'runtime_dir': str(runtime_dir),
        }, sort_keys=True))
    finally:
        for _name, process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for _name, process in reversed(processes):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in streams:
            stream.close()
        provider.shutdown()
        provider.server_close()
        shim.shutdown()
        shim.server_close()
        for database in (CONSUMER_DB, IAP_DB):
            subprocess.run(['dropdb', '--if-exists', database], check=False)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # noqa: BLE001
        print(json.dumps({'status': 'failed', 'error': str(error)}), file=sys.stderr)
        raise
