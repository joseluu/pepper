"""qi bridge client - Python 3 client for the qi bridge server.

Usage:
    from qi_bridge_client import QiSession

    session = QiSession()
    session.connect('tcp://127.0.0.1:9559')
    tts = session.service('ALTextToSpeech')
    tts.call('say', 'Hello from Python 3!')
"""
import json
import socket


SOCKET_PATH = '/tmp/qi_bridge.sock'


class QiServiceProxy:
    def __init__(self, session, name):
        self._session = session
        self._name = name

    def call(self, method, *args):
        return self._session._send({
            'cmd': 'call',
            'service': self._name,
            'method': method,
            'args': list(args),
        })

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)

        def method_proxy(*args):
            return self.call(name, *args)
        return method_proxy


class QiSession:
    def __init__(self, socket_path=SOCKET_PATH):
        self._socket_path = socket_path
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(socket_path)
        self._buf = b''

    def connect(self, url='tcp://127.0.0.1:9559'):
        self._send({'cmd': 'connect', 'url': url})

    def service(self, name):
        self._send({'cmd': 'service', 'name': name})
        return QiServiceProxy(self, name)

    def close(self):
        try:
            self._send({'cmd': 'quit'})
        except Exception:
            pass
        self._sock.close()

    def _send(self, data):
        msg = json.dumps(data).encode('utf-8') + b'\n'
        self._sock.sendall(msg)
        response = self._recv()
        if 'error' in response:
            raise RuntimeError(response['error'])
        return response.get('result')

    def _recv(self):
        while b'\n' not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError('Bridge server disconnected')
            self._buf += chunk
        line, self._buf = self._buf.split(b'\n', 1)
        return json.loads(line.decode('utf-8'))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        try:
            self._sock.close()
        except Exception:
            pass
