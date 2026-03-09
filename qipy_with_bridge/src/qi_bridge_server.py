#!/usr/bin/env python2
"""qi bridge server - exposes NAOqi services to Python 3 via Unix socket.

Runs as Python 2, accepts JSON commands from Python 3 clients.
Protocol: newline-delimited JSON over Unix socket.

Commands:
  {"cmd": "connect", "url": "tcp://127.0.0.1:9559"}
  {"cmd": "service", "name": "ALTextToSpeech"}
  {"cmd": "call", "service": "ALTextToSpeech", "method": "say", "args": ["Hello"]}
  {"cmd": "get", "service": "ALMemory", "method": "getData", "args": ["key"]}
  {"cmd": "quit"}
"""
import json
import os
import socket
import sys
import threading
import traceback

PYTHONPATH = '/opt/aldebaran/lib/python2.7/site-packages'
if PYTHONPATH not in sys.path:
    sys.path.insert(0, PYTHONPATH)

import qi

SOCKET_PATH = '/tmp/qi_bridge.sock'

session = None
services = {}


def handle_command(data):
    global session, services
    cmd = data.get('cmd')

    if cmd == 'connect':
        url = data.get('url', 'tcp://127.0.0.1:9559')
        session = qi.Session()
        session.connect(url)
        return {'ok': True}

    elif cmd == 'service':
        name = data['name']
        if session is None:
            return {'error': 'Not connected'}
        svc = session.service(name)
        services[name] = svc
        return {'ok': True}

    elif cmd == 'call':
        svc_name = data['service']
        method = data['method']
        args = data.get('args', [])
        if svc_name not in services:
            svc = session.service(svc_name)
            services[svc_name] = svc
        svc = services[svc_name]
        fn = getattr(svc, method)
        result = fn(*args)
        # Convert result to JSON-serializable form
        return {'ok': True, 'result': _serialize(result)}

    elif cmd == 'quit':
        return {'ok': True, 'quit': True}

    else:
        return {'error': 'Unknown command: %s' % cmd}


def _serialize(obj):
    """Convert qi types to JSON-serializable Python types."""
    if obj is None:
        return None
    if isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, bytes):
        return obj.decode('utf-8', errors='replace')
    if isinstance(obj, unicode):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {_serialize(k): _serialize(v) for k, v in obj.items()}
    # qi objects - convert to string representation
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def handle_client(conn):
    buf = b''
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                try:
                    data = json.loads(line.decode('utf-8'))
                    response = handle_command(data)
                except Exception as e:
                    response = {'error': str(e), 'traceback': traceback.format_exc()}
                conn.sendall(json.dumps(response).encode('utf-8') + b'\n')
                if response.get('quit'):
                    return
    finally:
        conn.close()


def main():
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(5)
    os.chmod(SOCKET_PATH, 0o777)

    print('qi bridge server listening on %s' % SOCKET_PATH)
    sys.stdout.flush()

    try:
        while True:
            conn, _ = server.accept()
            t = threading.Thread(target=handle_client, args=(conn,))
            t.daemon = True
            t.start()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)


if __name__ == '__main__':
    main()
