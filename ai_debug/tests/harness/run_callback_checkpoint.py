#!/usr/bin/env python3
"""Run the paired Slice 5A callback path with committed ai_debug evidence."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import psycopg2
import requests


CUSTOM = Path('/Users/joseph/.wt/worktrees/caburj/custom/master-ai-callback-driven-loop-ai-debug')
ENTERPRISE = Path('/Users/joseph/.wt/worktrees/odoo/enterprise/master-ai-callback-driven-loop-ai-debug')
CORE = Path('/Users/joseph/clones/odoo/odoo')
IAP_CORE = Path('/Users/joseph/.wt/worktrees/odoo/odoo/saas-19.4-odoo-ai-iap-service-lba')
IAP_ENTERPRISE = Path('/Users/joseph/.wt/worktrees/odoo/enterprise/saas-19.4-odoo-ai-iap-service-lba')
IAP_APPS = Path('/Users/joseph/.wt/worktrees/odoo/iap-apps/saas-19.4-odoo-ai-async-jcb')
HARNESS_ADDONS = ENTERPRISE / 'ai/tests/harness_addons'
CUSTOM_HARNESS_ADDONS = CUSTOM / 'ai_debug/tests/harness_addons'
MASTER_PYTHON = Path('/Users/joseph/.venvs/master/bin/python3')
IAP_PYTHON = Path('/Users/joseph/.venvs/saas-19.4/bin/python3')
RUN_SUFFIX = uuid.uuid4().hex[:10]
CONSUMER_DB = f'ai_debug_callback_e2e_{RUN_SUFFIX}'
IAP_DB = f'ai_debug_iap_e2e_{RUN_SUFFIX}'
CONSUMER_PORT = int(os.environ.get('AI_DEBUG_E2E_CONSUMER_PORT', '18069'))
CONSUMER_GEVENT_PORT = int(os.environ.get('AI_DEBUG_E2E_CONSUMER_GEVENT_PORT', '18072'))
IAP_PORT = int(os.environ.get('AI_DEBUG_E2E_IAP_PORT', '18170'))
IAP_GEVENT_PORT = int(os.environ.get('AI_DEBUG_E2E_IAP_GEVENT_PORT', '18173'))
CONSUMER_URL = f'http://127.0.0.1:{CONSUMER_PORT}'
IAP_URL = f'http://127.0.0.1:{IAP_PORT}'
IAP_EVENTED_URL = f'http://127.0.0.1:{IAP_GEVENT_PORT}'


def append_jsonl(path, payload):
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(payload, sort_keys=True) + '\n')


class LoopbackState:
    def __init__(self, evidence_dir):
        self.provider_journal = evidence_dir / 'provider-requests.jsonl'
        self.callback_journal = evidence_dir / 'callback-shim.jsonl'
        self.provider_payloads = []


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
        self.state.provider_payloads.append(payload)
        append_jsonl(self.state.provider_journal, {
            'message_count': len(payload.get('messages') or []),
            'tool_count': len(payload.get('tools') or []),
        })
        self._json(200, {'result': {
            'role': 'assistant',
            'content': [{
                'type': 'text',
                'content': {'data': 'Hello from the paired fake provider.'},
            }],
            'provider_metadata': {
                'provider': 'callback_harness',
                'model': 'deterministic-fixture',
                'api': 'loopback',
            },
        }})

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
        response = requests.post(
            CONSUMER_URL + '/ai/completion_result_ready',
            json=payload,
            timeout=15,
            allow_redirects=False,
        )
        append_jsonl(self.state.callback_journal, {
            'request_uuid': payload.get('request_uuid'),
            'consumer_status': response.status_code,
        })
        self.send_response(response.status_code)
        self.send_header('Content-Length', '0')
        self.end_headers()


def start_loopback_server(port, handler, state):
    handler.state = state
    server = ThreadingHTTPServer(('127.0.0.1', port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def wait_json(url, predicate=lambda payload: True, timeout=45):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
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


def start_process(command, cwd, log_path, env):
    stream = log_path.open('wb')
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
    )
    return process, stream


def json_post(url, payload, session=None):
    response = (session or requests).post(url, json=payload, timeout=15)
    response.raise_for_status()
    return response.json() if response.content else {}


def read_debug_events():
    with psycopg2.connect(dbname=CONSUMER_DB) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT message FROM bus_bus ORDER BY id')
            messages = [json.loads(row[0]) for row in cursor.fetchall()]
    return [
        message for message in messages
        if message.get('type') in {
            'new_trace', 'request_state', 'iteration', 'tool_call_started',
            'tool_call_completed', 'loop_end',
        }
    ]


def wait_debug_events(timeout=20):
    deadline = time.monotonic() + timeout
    events = []
    while time.monotonic() < deadline:
        events = read_debug_events()
        types = [event['type'] for event in events]
        if types.count('new_trace') == 1 and types.count('iteration') == 1 and types.count('loop_end') == 1:
            return events
        time.sleep(0.2)
    raise RuntimeError(f'Debug events did not settle: {[event["type"] for event in events]}')


def collect_normalized_keys(value):
    keys = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(''.join(character for character in key.casefold() if character.isalnum()))
            keys.update(collect_normalized_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(collect_normalized_keys(item))
    return keys


def assert_debug_events(events, request_uuid, exchange_uuid, provider_payload):
    types = [event['type'] for event in events]
    if types.count('new_trace') != 1:
        raise AssertionError(types)
    if types.count('iteration') != 1:
        raise AssertionError(types)
    if types.count('loop_end') != 1:
        raise AssertionError(types)
    trace = next(event['payload'] for event in events if event['type'] == 'new_trace')
    iteration = next(event['payload'] for event in events if event['type'] == 'iteration')
    terminal = next(event['payload'] for event in events if event['type'] == 'loop_end')
    if trace['trace_id'] != exchange_uuid or trace['exchange_uuid'] != exchange_uuid:
        raise AssertionError(trace)
    if trace['request_uuid'] != request_uuid or trace['round_no'] != 1:
        raise AssertionError(trace)
    if trace['user_query'] != 'Hi':
        raise AssertionError(trace)
    if trace['instructions'] != provider_payload['instructions']:
        raise AssertionError(trace)
    if iteration['trace_id'] != exchange_uuid or iteration['iteration_id'] != request_uuid:
        raise AssertionError(iteration)
    if iteration['request_uuid'] != request_uuid or iteration['round_no'] != 1:
        raise AssertionError(iteration)
    request_body = iteration['request_body']
    if request_body['request_uuid'] != request_uuid:
        raise AssertionError(request_body)
    for key in ('messages', 'instructions', 'tools'):
        if request_body[key] != provider_payload[key]:
            raise AssertionError((key, request_body[key], provider_payload[key]))
    for key, value in provider_payload['options'].items():
        if request_body.get(key) != value:
            raise AssertionError((key, request_body, provider_payload['options']))
    if 'messages_sent' in iteration or 'tools' in iteration:
        raise AssertionError('Callback event must not duplicate request messages/tools')
    tool_names = {tool['name'] for tool in request_body['tools']}
    if tool_names != {'ai_tool_ask_user_question', 'ai_tool_load_skills'}:
        raise AssertionError(tool_names)
    expected_result = {
        'request_uuid': request_uuid,
        'status': 'success',
        'result': {
            'role': 'assistant',
            'content': [{
                'type': 'text',
                'content': {'data': 'Hello from the paired fake provider.'},
            }],
            'provider_metadata': {
                'provider': 'callback_harness',
                'model': 'deterministic-fixture',
                'api': 'loopback',
            },
        },
    }
    if iteration['raw_response'] != expected_result:
        raise AssertionError(iteration['raw_response'])
    if iteration.get('provider') != 'callback_harness':
        raise AssertionError(iteration)
    if iteration.get('model_name') != 'deterministic-fixture':
        raise AssertionError(iteration)
    if iteration.get('provider_api') != 'loopback':
        raise AssertionError(iteration)
    if iteration.get('duration_kind') != 'request_lifecycle':
        raise AssertionError(iteration)
    if not isinstance(iteration.get('duration_ms'), int) or iteration['duration_ms'] < 0:
        raise AssertionError(iteration)
    if 'tokens' in iteration:
        raise AssertionError('Callback contract must not fabricate token metrics')
    if terminal['trace_id'] != exchange_uuid or terminal['request_uuid'] != request_uuid:
        raise AssertionError(terminal)
    if terminal['termination_reason'] != 'success':
        raise AssertionError(terminal)
    forbidden = {
        'accounttoken', 'cookie', 'databaseuuid', 'dbuuid', 'headers',
        'connection',
    }
    leaked = sorted(forbidden & collect_normalized_keys(events))
    if leaked:
        raise AssertionError(f'Forbidden debugger fields: {leaked}')
    encoded = json.dumps(events).lower()
    if 'ai-debug-callback-harness-fixture' in encoded or 'forged-callback-field' in encoded:
        raise AssertionError('Debugger events exposed a harness credential fixture')


def main():
    required = (
        CUSTOM, ENTERPRISE, CORE, IAP_CORE, IAP_ENTERPRISE, IAP_APPS,
        HARNESS_ADDONS, CUSTOM_HARNESS_ADDONS, MASTER_PYTHON, IAP_PYTHON,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f'Missing paired harness prerequisites: {missing}')

    root = Path(tempfile.mkdtemp(prefix='ai-debug-callback-e2e-'))
    evidence_dir = root / 'evidence'
    runtime_dir = root / 'runtime'
    evidence_dir.mkdir()
    runtime_dir.mkdir()
    for name in ('provider-requests.jsonl', 'callback-shim.jsonl'):
        (evidence_dir / name).touch()
    print(json.dumps({
        'phase': 'start',
        'runtime_root': str(root),
        'consumer_db': CONSUMER_DB,
        'iap_db': IAP_DB,
    }), flush=True)

    state = LoopbackState(evidence_dir)
    provider = start_loopback_server(18080, ProviderHandler, state)
    shim = start_loopback_server(18081, CallbackShimHandler, state)
    processes = []
    streams = []
    try:
        child_env = os.environ.copy()
        child_env['AI_DEBUG_CALLBACK_IAP_ENDPOINT'] = IAP_URL
        consumer_addons = ','.join(map(str, (
            CUSTOM, ENTERPRISE, CORE / 'addons', CUSTOM_HARNESS_ADDONS, HARNESS_ADDONS,
        )))
        iap_addons = ','.join(map(str, (
            IAP_CORE / 'addons', IAP_ENTERPRISE,
            IAP_APPS / 'iap_ai', IAP_APPS / 'iap_common',
            IAP_APPS / 'iap_services', IAP_APPS / 'iap_odoo', HARNESS_ADDONS,
        )))
        consumer_init = [
            str(MASTER_PYTHON), str(CORE / 'odoo-bin'), '-d', CONSUMER_DB,
            '-i', 'ai_app,ai_debug,ai_debug_callback_consumer_harness', '--stop-after-init',
            f'--http-port={CONSUMER_PORT}', f'--gevent-port={CONSUMER_GEVENT_PORT}',
            '--addons-path', consumer_addons, '--without-demo',
        ]
        iap_init = [
            str(IAP_PYTHON), str(IAP_CORE / 'odoo-bin'), '-d', IAP_DB,
            '-i', 'odoo_ai', '--stop-after-init', f'--http-port={IAP_PORT}',
            f'--gevent-port={IAP_GEVENT_PORT}', '--addons-path', iap_addons,
            '--load=base,web,odoo_ai,odoo_ai_callback_harness', '--without-demo',
        ]
        with (runtime_dir / 'consumer-init.log').open('wb') as stream:
            subprocess.run(
                consumer_init, cwd=ENTERPRISE, env=child_env,
                stdout=stream, stderr=subprocess.STDOUT, check=True,
            )
        with (runtime_dir / 'iap-init.log').open('wb') as stream:
            subprocess.run(
                iap_init, cwd=IAP_APPS, env=child_env,
                stdout=stream, stderr=subprocess.STDOUT, check=True,
            )

        commands = [
            ('consumer', [
                str(MASTER_PYTHON), str(CORE / 'odoo-bin'), '-d', CONSUMER_DB,
                f'--http-port={CONSUMER_PORT}',
                f'--gevent-port={CONSUMER_GEVENT_PORT}', '--addons-path', consumer_addons,
            ], ENTERPRISE),
            ('iap-http', [
                str(IAP_PYTHON), str(IAP_CORE / 'odoo-bin'), '-d', IAP_DB,
                f'--http-port={IAP_PORT}', f'--gevent-port={IAP_GEVENT_PORT}',
                '--addons-path', iap_addons,
                '--load=base,web,odoo_ai,odoo_ai_callback_harness',
            ], IAP_APPS),
            ('iap-evented', [
                str(IAP_PYTHON), str(IAP_CORE / 'odoo-bin'), 'gevent', '-d', IAP_DB,
                f'--gevent-port={IAP_GEVENT_PORT}', '--addons-path', iap_addons,
                '--load=base,web,odoo_ai,odoo_ai_callback_harness',
            ], IAP_APPS),
        ]
        for name, command, cwd in commands:
            process, stream = start_process(
                command, cwd, runtime_dir / f'{name}.log', child_env,
            )
            processes.append((name, process))
            streams.append(stream)

        wait_json(CONSUMER_URL + '/web/health?db_server_status=1')
        wait_json(IAP_URL + '/web/health?db_server_status=1')
        wait_json('http://127.0.0.1:18080/ready')
        wait_json('http://127.0.0.1:18081/ready')
        wait_json(
            IAP_EVENTED_URL + '/odoo_ai_callback_harness/ready',
            lambda payload: payload.get('dispatcher_alive') and payload.get('provider_patched'),
        )

        consumer_setup = json_post(
            CONSUMER_URL + '/ai_debug_callback_consumer_harness/setup',
            {'iap_endpoint': IAP_URL},
        )
        json_post(IAP_URL + '/odoo_ai_callback_harness/setup', {
            'database_uuid': consumer_setup['database_uuid'],
            'callback_url': 'http://127.0.0.1:18081',
        })

        session = requests.Session()
        authentication = json_post(CONSUMER_URL + '/web/session/authenticate', {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'call',
            'params': {'db': CONSUMER_DB, 'login': 'admin', 'password': 'admin'},
        }, session=session)
        if not authentication.get('result', {}).get('uid'):
            raise RuntimeError('Could not authenticate the disposable consumer admin')
        csrf = session.get(
            CONSUMER_URL + '/ai_debug_callback_consumer_harness/csrf', timeout=15,
        ).json()['csrf_token']
        kickoff = session.post(CONSUMER_URL + '/ai/generate_response', data={
            'csrf_token': csrf,
            'channel_id': consumer_setup['channel_id'],
            'mail_message_id': consumer_setup['message_id'],
            'callback_driven': 'true',
        }, timeout=15)
        kickoff.raise_for_status()
        acknowledgement = kickoff.json()
        request_uuid = acknowledgement['request_uuid']

        deadline = time.monotonic() + 30
        consumer_status = None
        while time.monotonic() < deadline:
            consumer_status = json_post(
                CONSUMER_URL + '/ai_debug_callback_consumer_harness/status',
                {'session_id': consumer_setup['session_id']},
            )
            if consumer_status.get('request_state') == 'done':
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(f'Consumer did not reach done: {consumer_status}')

        with psycopg2.connect(dbname=CONSUMER_DB) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT exchange_uuid FROM ai_session_request WHERE request_uuid = %s',
                    (request_uuid,),
                )
                exchange_uuid = cursor.fetchone()[0]
        events = wait_debug_events()
        if len(state.provider_payloads) != 1:
            raise AssertionError(state.provider_payloads)
        assert_debug_events(events, request_uuid, exchange_uuid, state.provider_payloads[0])
        before_replay = json.dumps(events, sort_keys=True)

        replay = requests.post(
            CONSUMER_URL + '/ai/completion_result_ready',
            json={
                'request_uuid': request_uuid,
                'status': 'success',
                'result': {'role': 'assistant', 'content': [{'type': 'text', 'content': {'data': 'forged'}}]},
                'account_token': 'forged-callback-field',
            },
            timeout=15,
            allow_redirects=False,
        )
        if replay.status_code != 204:
            raise AssertionError(replay.status_code)
        time.sleep(0.5)
        after_replay = json.dumps(read_debug_events(), sort_keys=True)
        if after_replay != before_replay:
            raise AssertionError('Replay created debugger events')

        bodies = [message['body'] for message in consumer_status['messages']]
        if consumer_status['event_roles'] != ['user', 'assistant']:
            raise AssertionError(consumer_status['event_roles'])
        if not any('Hello from the paired fake provider.' in body for body in bodies):
            raise AssertionError(bodies)
        debug_page = session.get(CONSUMER_URL + '/ai-debug', timeout=15)
        if debug_page.status_code != 200 or 'AI Debugger' not in debug_page.text:
            raise AssertionError(debug_page.status_code)
        provider_count = len(state.provider_journal.read_text().splitlines())
        callback_count = len(state.callback_journal.read_text().splitlines())
        if provider_count != 1 or callback_count != 1:
            raise AssertionError((provider_count, callback_count))

        evidence = {
            'status': 'passed',
            'request_uuid': request_uuid,
            'exchange_uuid': exchange_uuid,
            'debug_event_types': [event['type'] for event in events],
            'visible_reply': True,
            'debug_page_status': debug_page.status_code,
            'replay_status': replay.status_code,
            'provider_count': provider_count,
            'callback_count': callback_count,
            'pane_data_verified': True,
            'tokens_unavailable': True,
            'request_lifecycle_verified': True,
            'provider_metadata_verified': True,
            'replay_idempotent': True,
            'consumer_db': CONSUMER_DB,
            'iap_db': IAP_DB,
            'evidence_dir': str(evidence_dir),
            'runtime_dir': str(runtime_dir),
        }
        (evidence_dir / 'result.json').write_text(json.dumps(evidence, indent=2, sort_keys=True))
        print(json.dumps(evidence, sort_keys=True))
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
        shim.shutdown()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # noqa: BLE001
        print(json.dumps({'status': 'failed', 'error': str(error)}), file=sys.stderr)
        raise
