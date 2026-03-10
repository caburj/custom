#!/usr/bin/env python3
"""CLI client for the Odoo eval server.

Usage:
    python client.py <dbname> "<python code>"
    python client.py <dbname> script.py
    python client.py <dbname> --commit "<python code>"

Examples:
    python client.py mydb "env['res.partner'].search_count([])"
    python client.py mydb "print(env['sale.order'].browse(1).name)"
    python client.py mydb my_script.py
    python client.py mydb --commit "env['res.partner'].browse(1).name = 'New Name'"
"""
import json
import os
import socket
import sys

SOCKET_DIR = '/tmp'
SOCKET_PREFIX = 'odoo_eval_'


def socket_path(dbname):
    return os.path.join(SOCKET_DIR, f'{SOCKET_PREFIX}{dbname}.sock')


def send_eval(dbname, code, commit=False):
    sock_path = socket_path(dbname)

    if not os.path.exists(sock_path):
        print(f'Error: socket not found at {sock_path}', file=sys.stderr)
        print('Is the Odoo server running with eval_server loaded?', file=sys.stderr)
        sys.exit(1)

    request = json.dumps({'db': dbname, 'code': code, 'commit': commit}) + '\n'

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(sock_path)
    except (ConnectionRefusedError, OSError) as e:
        print(f'Error: cannot connect to eval server: {e}', file=sys.stderr)
        print('Is the Odoo server running with eval_server loaded?', file=sys.stderr)
        sys.exit(1)
    sock.sendall(request.encode('utf-8'))
    sock.shutdown(socket.SHUT_WR)

    data = b''
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    sock.close()

    if not data:
        print('Error: no response from eval server', file=sys.stderr)
        sys.exit(1)

    response = json.loads(data.decode('utf-8').strip())

    if response.get('ok'):
        if response.get('output'):
            print(response['output'], end='')
        if response.get('result'):
            print(response['result'])
    else:
        print(response.get('error', 'Unknown error'), file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    args = sys.argv[1:]
    dbname = args.pop(0)

    commit = False
    if args[0] == '--commit':
        commit = True
        args.pop(0)

    if not args:
        print('Error: missing code argument', file=sys.stderr)
        sys.exit(1)

    code = args[0]

    # If the argument is a file path, read its contents
    if os.path.isfile(code):
        with open(code, encoding='utf-8') as f:
            code = f.read()

    send_eval(dbname, code, commit=commit)


if __name__ == '__main__':
    main()
