import ast
import atexit
import io
import json
import logging
import os
import socket
import sys
import threading
import traceback

_logger = logging.getLogger(__name__)

SOCKET_DIR = '/tmp'
SOCKET_PREFIX = 'odoo_eval_'


def _eval_code(dbname, code, commit=False):
    """Execute Python code with an Odoo environment and return the result."""
    from odoo import api  # noqa: PLC0415
    from odoo.modules.registry import Registry  # noqa: PLC0415

    registry = Registry(dbname)
    with registry.cursor() as cr:
        uid = api.SUPERUSER_ID
        ctx = api.Environment(cr, uid, {})['res.users'].context_get()
        env = api.Environment(cr, uid, ctx)

        local_vars = {'env': env, 'self': env.user, 'odoo': __import__('odoo')}
        stdout_capture = io.StringIO()
        old_stdout = sys.stdout

        try:
            # Try to parse as an expression first (for single expressions that
            # return a value), fall back to exec for statements/multi-line code.
            sys.stdout = stdout_capture
            try:
                tree = ast.parse(code, mode='eval')
                result = eval(compile(tree, '<eval>', 'eval'), local_vars)
            except SyntaxError:
                tree = ast.parse(code, mode='exec')
                # If the last statement is an expression, capture its value
                last_expr_result = None
                if tree.body and isinstance(tree.body[-1], ast.Expr):
                    last = tree.body.pop()
                    exec(compile(tree, '<eval>', 'exec'), local_vars)
                    last_expr_result = eval(
                        compile(ast.Expression(last.value), '<eval>', 'eval'),
                        local_vars,
                    )
                else:
                    exec(compile(tree, '<eval>', 'exec'), local_vars)
                result = last_expr_result
        finally:
            sys.stdout = old_stdout

        output = stdout_capture.getvalue()

        if commit:
            cr.commit()
        else:
            cr.rollback()

        return {'ok': True, 'output': output, 'result': repr(result) if result is not None else None}


def _handle_client(conn):
    """Handle a single client connection."""
    try:
        data = b''
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
            if b'\n' in data:
                break

        if not data:
            return

        request = json.loads(data.decode('utf-8').strip())
        dbname = request.get('db')
        code = request.get('code', '')
        commit = request.get('commit', False)

        if not dbname:
            response = {'ok': False, 'error': 'Missing "db" in request'}
        elif not code:
            response = {'ok': False, 'error': 'Missing "code" in request'}
        else:
            try:
                response = _eval_code(dbname, code, commit=commit)
            except Exception:
                response = {'ok': False, 'error': traceback.format_exc()}

        conn.sendall(json.dumps(response).encode('utf-8') + b'\n')
    except Exception:
        _logger.exception('eval_server: error handling client')
    finally:
        conn.close()


def _socket_path(dbname):
    return os.path.join(SOCKET_DIR, f'{SOCKET_PREFIX}{dbname}.sock')


def _listener(stop_event, sock_path):
    """Main listener loop for the Unix socket server."""
    if os.path.exists(sock_path):
        os.unlink(sock_path)

    server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server_sock.bind(sock_path)
    server_sock.listen(5)
    server_sock.settimeout(1.0)  # allow periodic stop_event checks

    _logger.info('eval_server: listening on %s', sock_path)

    while not stop_event.is_set():
        try:
            conn, _ = server_sock.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        thread = threading.Thread(target=_handle_client, args=(conn,), daemon=True)
        thread.start()

    server_sock.close()
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    _logger.info('eval_server: stopped')


def _cleanup_socket(sock_path):
    """Ensure socket file is removed on exit."""
    if os.path.exists(sock_path):
        try:
            os.unlink(sock_path)
        except OSError:
            pass


def start_eval_server():
    """post_load hook: spawn the eval server daemon thread."""
    from odoo.service.server import CommonServer  # noqa: PLC0415
    from odoo.tools import config  # noqa: PLC0415

    dbnames = config['db_name']
    if not dbnames:
        _logger.warning('eval_server: no database configured, skipping')
        return

    dbname = dbnames[0]
    sock_path = _socket_path(dbname)
    stop_event = threading.Event()

    thread = threading.Thread(target=_listener, args=(stop_event, sock_path), daemon=True)
    thread.start()

    def _stop():
        stop_event.set()
        _cleanup_socket(sock_path)

    CommonServer.on_stop(_stop)
    atexit.register(_cleanup_socket, sock_path)
    _logger.info('eval_server: daemon thread started (db=%s)', dbname)
