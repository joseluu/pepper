#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
vigiclient.py - Vigibot client for Pepper robot
Direct NAOqi access via qi SDK (no bridge needed)
Python 2.7 compatible - 2.7-specific items marked with # PY2
"""

import sys
import os
import json
import time
import math
import struct
import socket as socket_mod
import threading
import subprocess
import re
import ssl

# Local lib path for websocket-client
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
import websocket

# NAOqi SDK
sys.path.insert(0, '/opt/aldebaran/lib/python2.7/site-packages')
import qi

# --- Config ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.abspath(__file__)
VERSION = int(os.path.getmtime(SCRIPT_PATH) * 1000)

PROCESS_TIME = int(time.time() * 1000)
try:
    with open('/proc/uptime') as f:
        _uptime = float(f.read().split()[0])
    OS_TIME = PROCESS_TIME - int(_uptime * 1000)
except Exception:
    OS_TIME = PROCESS_TIME

with open(os.path.join(SCRIPT_DIR, 'sys.json')) as f:
    SYS = json.load(f)

with open('/home/nao/robot.json') as f:
    USER = json.load(f)

# Defaults
if 'SERVERS' not in USER:
    USER['SERVERS'] = SYS['SERVERS']
if 'CMDDIFFUSION' not in USER:
    USER['CMDDIFFUSION'] = SYS['CMDDIFFUSION']
if 'CMDDIFFAUDIO' not in USER:
    USER['CMDDIFFAUDIO'] = SYS.get('CMDDIFFAUDIO', [])
if 'CMDTTS' not in USER:
    USER['CMDTTS'] = SYS.get('CMDTTS', '')

LOGFILE = SYS.get('LOGFILE', '/home/nao/vigiclient.log')
DEBUG = True

# --- Logging ---

def trace(message, mandatory=False):
    if not mandatory and not DEBUG:
        return
    now = time.localtime()
    ms = int((time.time() % 1) * 1000)
    line = '%02d:%02d:%02d:%03d | %s' % (now.tm_hour, now.tm_min, now.tm_sec, ms, message)
    try:
        with open(LOGFILE, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass
    print(line)  # PY2: print() works as function call
    sys.stdout.flush()  # PY2: stdout buffered when not a TTY


# --- Utility functions ---

def constrain(n, n_min, n_max):
    if n > n_max:
        return n_max
    if n < n_min:
        return n_min
    return n

def map_float(n, in_min, in_max, out_min, out_max):
    return (n - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

def map_trunc(n, in_min, in_max, out_min, out_max):
    return int(map_float(n, in_min, in_max, out_min, out_max))

def get_ip():
    try:
        return subprocess.check_output(
            'hostname -I 2>/dev/null || echo unknown', shell=True
        ).strip()
    except Exception:
        return 'unknown'

def get_ssid():
    try:
        return subprocess.check_output(
            'iwgetid -r 2>/dev/null || echo unknown', shell=True
        ).strip()
    except Exception:
        return 'unknown'


# --- Binary Frame Protocol (port of trame.js) ---

class TxFrame(object):
    """Incoming command frame from vigibot server"""

    def __init__(self, conftx):
        self.conftx = conftx
        nb32 = len(conftx['COMMANDS32'])
        nb16 = len(conftx['COMMANDS16'])
        nb8_total = len(conftx['SYNC']) + len(conftx['CAMERACHOICES']) + len(conftx['COMMANDS8'])
        nb1_bytes = int(math.ceil(len(conftx['COMMANDS1']) / 8.0))

        self.byte_length = nb32 * 4 + nb16 * 2 + nb8_total + nb1_bytes
        self.buf = bytearray(self.byte_length)

        # Calculate field offsets
        p = 0
        self.sync_off = p
        self.sync_len = len(conftx['SYNC'])
        for i, ch in enumerate(conftx['SYNC']):
            self.buf[p + i] = ord(ch)
        p += self.sync_len

        self.cmd32_off = p
        self.cmd32_len = nb32
        p += nb32 * 4

        self.cmd16_off = p
        self.cmd16_len = nb16
        p += nb16 * 2

        self.cam_off = p
        self.cam_len = len(conftx['CAMERACHOICES'])
        for i, v in enumerate(conftx['CAMERACHOICES']):
            self.buf[p + i] = v
        p += self.cam_len

        self.cmd8_off = p
        self.cmd8_len = len(conftx['COMMANDS8'])
        p += self.cmd8_len

        self.cmd1_off = p
        self.cmd1_len = nb1_bytes

        # Init values
        for i in range(nb32):
            self.set_float_command32(i, conftx['COMMANDS32'][i]['INIT'])
        for i in range(nb16):
            self.set_float_command16(i, conftx['COMMANDS16'][i]['INIT'])
        for i in range(self.cmd8_len):
            self.set_float_command8(i, conftx['COMMANDS8'][i]['INIT'])
        for i in range(len(conftx['COMMANDS1'])):
            self.set_command1(i, conftx['COMMANDS1'][i]['INIT'])

    def load_from(self, data):
        """Load frame bytes from received binary data"""
        ba = bytearray(data)
        for i in range(min(len(ba), self.byte_length)):
            self.buf[i] = ba[i]

    def get_camera_choice(self, idx):
        return self.buf[self.cam_off + idx]

    # --- Raw accessors ---
    def set_command32(self, idx, val):
        fmt = '<i' if self.conftx['COMMANDS32'][idx].get('SIGNED') else '<I'
        struct.pack_into(fmt, self.buf, self.cmd32_off + idx * 4, int(val))

    def set_command16(self, idx, val):
        fmt = '<h' if self.conftx['COMMANDS16'][idx].get('SIGNED') else '<H'
        struct.pack_into(fmt, self.buf, self.cmd16_off + idx * 2, int(val))

    def set_command8(self, idx, val):
        fmt = '<b' if self.conftx['COMMANDS8'][idx].get('SIGNED') else '<B'
        struct.pack_into(fmt, self.buf, self.cmd8_off + idx, int(val))

    def set_command1(self, idx, val):
        pos = idx // 8  # PY2: use // for integer division
        off = self.cmd1_off + pos
        if val:
            self.buf[off] |= 1 << (idx % 8)
        else:
            self.buf[off] &= ~(1 << (idx % 8)) & 0xFF

    def get_command32(self, idx):
        fmt = '<i' if self.conftx['COMMANDS32'][idx].get('SIGNED') else '<I'
        return struct.unpack_from(fmt, self.buf, self.cmd32_off + idx * 4)[0]

    def get_command16(self, idx):
        fmt = '<h' if self.conftx['COMMANDS16'][idx].get('SIGNED') else '<H'
        return struct.unpack_from(fmt, self.buf, self.cmd16_off + idx * 2)[0]

    def get_command8(self, idx):
        fmt = '<b' if self.conftx['COMMANDS8'][idx].get('SIGNED') else '<B'
        return struct.unpack_from(fmt, self.buf, self.cmd8_off + idx)[0]

    def get_command1(self, idx):
        pos = idx // 8
        return (self.buf[self.cmd1_off + pos] >> (idx % 8)) & 1

    # --- Scale computation ---
    def compute_raw_command32(self, idx, value):
        c = self.conftx['COMMANDS32'][idx]
        if c.get('SIGNED'):
            mn, mx = -2147483647, 2147483647
        else:
            mn, mx = 0, 4294967295
        value = constrain(value, c['SCALEMIN'], c['SCALEMAX'])
        return map_trunc(value, c['SCALEMIN'], c['SCALEMAX'], mn, mx)

    def compute_raw_command16(self, idx, value):
        c = self.conftx['COMMANDS16'][idx]
        if c.get('SIGNED'):
            mn, mx = -32767, 32767
        else:
            mn, mx = 0, 65535
        value = constrain(value, c['SCALEMIN'], c['SCALEMAX'])
        return map_trunc(value, c['SCALEMIN'], c['SCALEMAX'], mn, mx)

    def compute_raw_command8(self, idx, value):
        c = self.conftx['COMMANDS8'][idx]
        if c.get('SIGNED'):
            mn, mx = -127, 127
        else:
            mn, mx = 0, 255
        value = constrain(value, c['SCALEMIN'], c['SCALEMAX'])
        return map_trunc(value, c['SCALEMIN'], c['SCALEMAX'], mn, mx)

    # --- Float setters/getters ---
    def set_float_command32(self, idx, value):
        self.set_command32(idx, self.compute_raw_command32(idx, value))

    def set_float_command16(self, idx, value):
        self.set_command16(idx, self.compute_raw_command16(idx, value))

    def set_float_command8(self, idx, value):
        self.set_command8(idx, self.compute_raw_command8(idx, value))

    def get_float_command32(self, idx):
        c = self.conftx['COMMANDS32'][idx]
        if c.get('SIGNED'):
            return map_float(struct.unpack_from('<i', self.buf, self.cmd32_off + idx * 4)[0],
                             -2147483648, 2147483648, c['SCALEMIN'], c['SCALEMAX'])
        return map_float(struct.unpack_from('<I', self.buf, self.cmd32_off + idx * 4)[0],
                         0, 4294967295, c['SCALEMIN'], c['SCALEMAX'])

    def get_float_command16(self, idx):
        c = self.conftx['COMMANDS16'][idx]
        if c.get('SIGNED'):
            return map_float(struct.unpack_from('<h', self.buf, self.cmd16_off + idx * 2)[0],
                             -32768, 32768, c['SCALEMIN'], c['SCALEMAX'])
        return map_float(struct.unpack_from('<H', self.buf, self.cmd16_off + idx * 2)[0],
                         0, 65535, c['SCALEMIN'], c['SCALEMAX'])

    def get_float_command8(self, idx):
        c = self.conftx['COMMANDS8'][idx]
        if c.get('SIGNED'):
            return map_float(struct.unpack_from('<b', self.buf, self.cmd8_off + idx)[0],
                             -128, 128, c['SCALEMIN'], c['SCALEMAX'])
        return map_float(struct.unpack_from('<B', self.buf, self.cmd8_off + idx)[0],
                         0, 255, c['SCALEMIN'], c['SCALEMAX'])


class RxFrame(object):
    """Outgoing response frame to vigibot server"""

    def __init__(self, conftx, confrx):
        self.conftx = conftx
        self.confrx = confrx

        nb32 = len(conftx['COMMANDS32']) + len(confrx['VALUES32'])
        nb16 = len(conftx['COMMANDS16']) + len(confrx['VALUES16'])
        nb8_total = (len(confrx['SYNC']) + len(conftx['CAMERACHOICES']) +
                     len(conftx['COMMANDS8']) + len(confrx['VALUES8']))
        nb1_bytes = int(math.ceil(len(conftx['COMMANDS1']) / 8.0))

        self.byte_length = nb32 * 4 + nb16 * 2 + nb8_total + nb1_bytes
        self.buf = bytearray(self.byte_length)

        # Layout: sync | cmd32 | val32 | cmd16 | val16 | cam | cmd8 | cmd1 | val8
        p = 0
        self.sync_off = p
        self.sync_len = len(confrx['SYNC'])
        for i, ch in enumerate(confrx['SYNC']):
            self.buf[p + i] = ord(ch)
        p += self.sync_len

        self.cmd32_off = p
        self.cmd32_len = len(conftx['COMMANDS32'])
        p += self.cmd32_len * 4

        self.val32_off = p
        self.val32_len = len(confrx['VALUES32'])
        p += self.val32_len * 4

        self.cmd16_off = p
        self.cmd16_len = len(conftx['COMMANDS16'])
        p += self.cmd16_len * 2

        self.val16_off = p
        self.val16_len = len(confrx['VALUES16'])
        p += self.val16_len * 2

        self.cam_off = p
        self.cam_len = len(conftx['CAMERACHOICES'])
        for i, v in enumerate(conftx['CAMERACHOICES']):
            self.buf[p + i] = v
        p += self.cam_len

        self.cmd8_off = p
        self.cmd8_len = len(conftx['COMMANDS8'])
        p += self.cmd8_len

        self.cmd1_off = p
        self.cmd1_len = nb1_bytes
        p += nb1_bytes

        self.val8_off = p
        self.val8_len = len(confrx['VALUES8'])

        # Init all fields
        for i in range(self.cmd32_len):
            self._set_float_cmd32(i, conftx['COMMANDS32'][i]['INIT'])
        for i in range(self.val32_len):
            self.set_float_value32(i, confrx['VALUES32'][i]['INIT'])
        for i in range(self.cmd16_len):
            self._set_float_cmd16(i, conftx['COMMANDS16'][i]['INIT'])
        for i in range(self.val16_len):
            self.set_float_value16(i, confrx['VALUES16'][i]['INIT'])
        for i in range(self.cmd8_len):
            self._set_float_cmd8(i, conftx['COMMANDS8'][i]['INIT'])
        for i in range(len(conftx['COMMANDS1'])):
            self._set_cmd1(i, conftx['COMMANDS1'][i]['INIT'])
        for i in range(self.val8_len):
            self.set_float_value8(i, confrx['VALUES8'][i]['INIT'])

    # --- Command echo (write computed raw values from servo loop) ---
    def set_cmd16_raw(self, idx, val):
        struct.pack_into('<h', self.buf, self.cmd16_off + idx * 2, int(val))

    def set_cmd8_raw(self, idx, val):
        struct.pack_into('<b', self.buf, self.cmd8_off + idx, int(val))

    def set_camera_choice(self, idx, val):
        self.buf[self.cam_off + idx] = val & 0xFF

    def set_cmd1_byte(self, byte_idx, val):
        self.buf[self.cmd1_off + byte_idx] = val & 0xFF

    # --- Internal float command setters (for init) ---
    def _set_float_cmd32(self, idx, value):
        c = self.conftx['COMMANDS32'][idx]
        if c.get('SIGNED'):
            mn, mx = -2147483647, 2147483647
        else:
            mn, mx = 0, 4294967295
        value = constrain(value, c['SCALEMIN'], c['SCALEMAX'])
        raw = map_trunc(value, c['SCALEMIN'], c['SCALEMAX'], mn, mx)
        fmt = '<i' if c.get('SIGNED') else '<I'
        struct.pack_into(fmt, self.buf, self.cmd32_off + idx * 4, raw)

    def _set_float_cmd16(self, idx, value):
        c = self.conftx['COMMANDS16'][idx]
        if c.get('SIGNED'):
            mn, mx = -32767, 32767
        else:
            mn, mx = 0, 65535
        value = constrain(value, c['SCALEMIN'], c['SCALEMAX'])
        raw = map_trunc(value, c['SCALEMIN'], c['SCALEMAX'], mn, mx)
        fmt = '<h' if c.get('SIGNED') else '<H'
        struct.pack_into(fmt, self.buf, self.cmd16_off + idx * 2, raw)

    def _set_float_cmd8(self, idx, value):
        c = self.conftx['COMMANDS8'][idx]
        if c.get('SIGNED'):
            mn, mx = -127, 127
        else:
            mn, mx = 0, 255
        value = constrain(value, c['SCALEMIN'], c['SCALEMAX'])
        raw = map_trunc(value, c['SCALEMIN'], c['SCALEMAX'], mn, mx)
        fmt = '<b' if c.get('SIGNED') else '<B'
        struct.pack_into(fmt, self.buf, self.cmd8_off + idx, raw)

    def _set_cmd1(self, idx, val):
        pos = idx // 8
        off = self.cmd1_off + pos
        if val:
            self.buf[off] |= 1 << (idx % 8)
        else:
            self.buf[off] &= ~(1 << (idx % 8)) & 0xFF

    # --- Value setters (sensor readings to send to server) ---
    def set_float_value32(self, idx, value):
        c = self.confrx['VALUES32'][idx]
        if c.get('SIGNED'):
            mn, mx = -2147483647, 2147483647
        else:
            mn, mx = 0, 4294967295
        value = constrain(value, c['SCALEMIN'], c['SCALEMAX'])
        raw = map_trunc(value, c['SCALEMIN'], c['SCALEMAX'], mn, mx)
        fmt = '<i' if c.get('SIGNED') else '<I'
        struct.pack_into(fmt, self.buf, self.val32_off + idx * 4, raw)

    def set_float_value16(self, idx, value):
        c = self.confrx['VALUES16'][idx]
        if c.get('SIGNED'):
            mn, mx = -32767, 32767
        else:
            mn, mx = 0, 65535
        value = constrain(value, c['SCALEMIN'], c['SCALEMAX'])
        raw = map_trunc(value, c['SCALEMIN'], c['SCALEMAX'], mn, mx)
        fmt = '<h' if c.get('SIGNED') else '<H'
        struct.pack_into(fmt, self.buf, self.val16_off + idx * 2, raw)

    def set_float_value8(self, idx, value):
        c = self.confrx['VALUES8'][idx]
        if c.get('SIGNED'):
            mn, mx = -127, 127
        else:
            mn, mx = 0, 255
        value = constrain(value, c['SCALEMIN'], c['SCALEMAX'])
        raw = map_trunc(value, c['SCALEMIN'], c['SCALEMAX'], mn, mx)
        fmt = '<b' if c.get('SIGNED') else '<B'
        struct.pack_into(fmt, self.buf, self.val8_off + idx, raw)

    # --- Compute raw command for echo (matches TX scaling) ---
    def compute_raw_cmd16(self, idx, value):
        c = self.conftx['COMMANDS16'][idx]
        if c.get('SIGNED'):
            mn, mx = -32767, 32767
        else:
            mn, mx = 0, 65535
        value = constrain(value, c['SCALEMIN'], c['SCALEMAX'])
        return map_trunc(value, c['SCALEMIN'], c['SCALEMAX'], mn, mx)

    def compute_raw_cmd8(self, idx, value):
        c = self.conftx['COMMANDS8'][idx]
        if c.get('SIGNED'):
            mn, mx = -127, 127
        else:
            mn, mx = 0, 255
        value = constrain(value, c['SCALEMIN'], c['SCALEMAX'])
        return map_trunc(value, c['SCALEMIN'], c['SCALEMAX'], mn, mx)


# --- Socket.IO 2.x Client (Engine.IO 3) ---

class VigiSocket(object):
    """Manual Socket.IO 2.x client over WebSocket (EIO=3)"""

    def __init__(self, url, port):
        self.url = url
        self.port = port
        self.ws = None
        self.sid = None
        self.ping_interval = 25000
        self.ping_timeout = 60000
        self.handlers = {}
        self.connected = False
        self._running = False
        self._pending_binary = None
        self._binary_attachments = []
        self._binary_count = 0
        self._lock = threading.Lock()

    def on(self, event, handler):
        self.handlers[event] = handler

    def connect(self):
        base = self.url.replace('https://', 'wss://').replace('http://', 'ws://')
        ws_url = '%s/%d/socket.io/?EIO=3&transport=websocket' % (base, self.port)
        trace('Connecting to %s' % ws_url, True)

        self.ws = websocket.WebSocket(sslopt={'cert_reqs': ssl.CERT_NONE})
        self.ws.connect(ws_url)
        self._running = True

        # Receive thread
        t = threading.Thread(target=self._recv_loop)
        t.daemon = True
        t.start()

        # Wait for connection
        deadline = time.time() + 10
        while not self.connected and time.time() < deadline:
            time.sleep(0.1)

        if not self.connected:
            trace('Socket.IO connect timeout', True)
            return False
        return True

    def disconnect(self):
        self._running = False
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        self.connected = False

    def emit(self, event, data=None):
        """Emit a Socket.IO event (JSON only, no binary)"""
        with self._lock:
            try:
                if data is not None:
                    payload = '42' + json.dumps([event, data])
                else:
                    payload = '42' + json.dumps([event])
                self.ws.send(payload)
            except Exception as e:
                trace('emit error: %s' % e, True)

    def emit_binary(self, event, data_dict, binary_key='data'):
        """Emit a Socket.IO event with one binary attachment"""
        with self._lock:
            try:
                binary_data = data_dict[binary_key]
                placeholder = dict(data_dict)
                placeholder[binary_key] = {'_placeholder': True, 'num': 0}
                payload = '451-' + json.dumps([event, placeholder])
                self.ws.send(payload)
                if isinstance(binary_data, bytearray):
                    binary_data = bytes(binary_data)  # PY2: bytes == str
                # Engine.IO 3: binary frames must be prefixed with type byte (4=message)
                self.ws.send(b'\x04' + binary_data, opcode=websocket.ABNF.OPCODE_BINARY)
            except Exception as e:
                trace('emit_binary error: %s' % e, True)

    def _recv_loop(self):
        while self._running:
            try:
                opcode, data = self.ws.recv_data()
                if opcode == websocket.ABNF.OPCODE_TEXT:
                    msg = data.decode('utf-8') if isinstance(data, bytes) else data
                    self._on_text(msg)
                elif opcode == websocket.ABNF.OPCODE_BINARY:
                    self._on_binary(data)
            except websocket.WebSocketConnectionClosedException:
                trace('WebSocket connection closed', True)
                break
            except Exception as e:
                if self._running:
                    trace('WS recv error: %s' % e, True)
                break

        self._running = False
        was_connected = self.connected
        self.connected = False
        if was_connected and 'disconnect' in self.handlers:
            try:
                self.handlers['disconnect']()
            except Exception:
                pass

    def _on_text(self, msg):
        if not msg:
            return

        ptype = msg[0]

        if ptype == '0':  # Engine.IO Open
            try:
                handshake = json.loads(msg[1:])
                self.sid = handshake.get('sid')
                self.ping_interval = handshake.get('pingInterval', 25000)
                self.ping_timeout = handshake.get('pingTimeout', 60000)
                trace('EIO open sid=%s ping=%dms' % (self.sid, self.ping_interval), True)
                self._start_ping()
            except Exception as e:
                trace('EIO handshake error: %s' % e, True)

        elif ptype == '3':  # Engine.IO Pong
            pass

        elif ptype == '4':  # Engine.IO Message -> Socket.IO
            self._handle_socketio(msg[1:])

        elif ptype == '1':  # Engine.IO Close
            trace('EIO close received', True)
            self._running = False

    def _handle_socketio(self, msg):
        if not msg:
            return

        stype = msg[0]

        if stype == '0':  # SIO Connect
            trace('Socket.IO connected to server', True)
            self.connected = True
            if 'connect' in self.handlers:
                try:
                    self.handlers['connect']()
                except Exception as e:
                    trace('connect handler error: %s' % e, True)

        elif stype == '1':  # SIO Disconnect
            trace('Socket.IO disconnect', True)
            self.connected = False
            if 'disconnect' in self.handlers:
                try:
                    self.handlers['disconnect']()
                except Exception as e:
                    trace('disconnect handler error: %s' % e, True)

        elif stype == '2':  # SIO Event
            self._dispatch_event(msg[1:])

        elif stype == '5':  # SIO Binary Event
            try:
                dash = msg.index('-')
                n = int(msg[1:dash])
                json_str = msg[dash + 1:]
                self._pending_binary = json.loads(json_str)
                self._binary_count = n
                self._binary_attachments = []
            except Exception as e:
                trace('Binary event parse error: %s' % e, True)

    def _on_binary(self, data):
        if self._pending_binary is None:
            return

        # Engine.IO 3: binary frames have a type byte prefix (4 = message)
        if len(data) > 0 and ord(data[0:1]) == 4:  # PY2: data[0] is str, use ord()
            data = data[1:]

        self._binary_attachments.append(data)
        if len(self._binary_attachments) >= self._binary_count:
            event_arr = self._pending_binary
            self._pending_binary = None
            event_name = event_arr[0]
            args = self._replace_placeholders(event_arr[1]) if len(event_arr) > 1 else None
            if event_name in self.handlers:
                try:
                    self.handlers[event_name](args)
                except Exception as e:
                    trace('Handler error %s: %s' % (event_name, e), True)

    def _replace_placeholders(self, obj):
        if isinstance(obj, dict):
            if obj.get('_placeholder') and 'num' in obj:
                idx = obj['num']
                if idx < len(self._binary_attachments):
                    return self._binary_attachments[idx]
                return None
            return dict((k, self._replace_placeholders(v)) for k, v in obj.items())  # PY2: dict comprehension ok
        elif isinstance(obj, list):
            return [self._replace_placeholders(item) for item in obj]
        return obj

    def _dispatch_event(self, json_str):
        try:
            data = json.loads(json_str)
            event_name = data[0]
            args = data[1] if len(data) > 1 else None
            if event_name in self.handlers:
                self.handlers[event_name](args)
        except Exception as e:
            trace('Event dispatch error: %s' % e, True)

    def _start_ping(self):
        def ping_loop():
            while self._running and self.ws:
                time.sleep(self.ping_interval / 1000.0)
                if not self._running:
                    break
                try:
                    with self._lock:
                        self.ws.send('2')
                except Exception:
                    break

        t = threading.Thread(target=ping_loop)
        t.daemon = True
        t.start()


# --- Pepper Head Control ---

# Map COMMANDS16 to Pepper head joints
# [0] Turret X -> HeadYaw (radians), [1] Turret Y -> HeadPitch (radians)
PEPPER_JOINTS = [
    {'name': 'HeadYaw', 'index': 0, 'scale': -math.pi / 180},  # inverted: joystick right = look right
    {'name': 'HeadPitch', 'index': 1, 'scale': -math.pi / 180},  # inverted: joystick up = look up
]
HEAD_SPEED = 0.3


# --- Main Client ---

class VigiClient(object):

    def __init__(self):
        self.sockets = {}
        self.current_server = ''
        self.up = False
        self.engine = False
        self.up_timeout = None
        self.init_done = False
        self.init_naoqi = False

        self.conf = {}
        self.hard = {}
        self.tx = None
        self.rx = None

        self.last_timestamp = int(time.time() * 1000)
        self.last_frame = int(time.time() * 1000)
        self.latency_alarm = False

        self.float_targets16 = []
        self.float_targets8 = []
        self.float_targets1 = []
        self.float_commands16 = []
        self.float_commands8 = []
        self.float_commands1 = []
        self.margins16 = []
        self.margins8 = []

        # Sensor values
        self.voltage = 0
        self.battery = 0
        self.cpu_load = 0
        self.soc_temp = 0
        self.link = 0
        self.rssi = 0

        # NAOqi
        self.qi_session = None
        self.motion = None
        self.posture = None
        self.battery_svc = None
        self.tts = None
        self.video = None
        self.mem = None
        self.leds = None
        self._wake_sub = None
        self._eye_anim_running = False

        # CPU measurement
        self._prev_cpu = self._read_cpu_times()

        # Video
        self.cmd_diffusion = ''
        self.conf_video = None
        self._ffmpeg_proc = None
        self._video_server_sock = None
        self._video_server_started = False

        # Timers
        self._timers_started = False

    # --- NAOqi ---

    def init_naoqi_session(self):
        trace('Connecting to NAOqi...', True)
        try:
            self.qi_session = qi.Session()
            self.qi_session.connect('tcp://127.0.0.1:9559')
            trace('NAOqi session connected', True)

            self.motion = self.qi_session.service('ALMotion')
            trace('ALMotion acquired', True)

            self.battery_svc = self.qi_session.service('ALBattery')
            trace('ALBattery acquired', True)

            self.tts = self.qi_session.service('ALTextToSpeech')
            trace('ALTextToSpeech acquired', True)

            # Disable autonomous life (full behavior engine)
            try:
                life = self.qi_session.service('ALAutonomousLife')
                life.setState('disabled')
                trace('ALAutonomousLife disabled', True)
            except Exception as e:
                trace('ALAutonomousLife warning: %s' % e, True)

            # Enable background movement (subtle idle activity, may reset rest timer)
            try:
                bg = self.qi_session.service('ALBackgroundMovement')
                bg.setEnabled(True)
                trace('ALBackgroundMovement enabled', True)
            except Exception as e:
                trace('ALBackgroundMovement warning: %s' % e, True)

            # Enable autonomous blinking (harmless eye LEDs)
            try:
                blink = self.qi_session.service('ALAutonomousBlinking')
                blink.setEnabled(True)
                trace('ALAutonomousBlinking enabled', True)
            except Exception as e:
                trace('ALAutonomousBlinking warning: %s' % e, True)

            # Get ALLeds for eye animation during video
            try:
                self.leds = self.qi_session.service('ALLeds')
                trace('ALLeds acquired', True)
            except Exception as e:
                trace('ALLeds warning: %s' % e, True)

            # Get video service for frame grabbing
            try:
                self.video = self.qi_session.service('ALVideoDevice')
                trace('ALVideoDevice acquired', True)
            except Exception as e:
                trace('ALVideoDevice warning: %s' % e, True)

            # Wake up (can block 15-30s, may fail if already awake)
            trace('Waking up robot...', True)
            try:
                self.posture = self.qi_session.service('ALRobotPosture')
                self.motion.setStiffnesses('Body', 1.0)
                self.posture.goToPosture('Stand', 0.5)
                self.motion.wakeUp()
                trace('Robot is awake', True)
            except Exception as e:
                trace('wakeUp warning (non-fatal): %s' % e, True)

            self.motion.setStiffnesses('Body', 1.0)
            trace('Body stiffness set', True)

            # Subscribe to robotIsWakeUp event for fast recovery from rest
            try:
                self.mem = self.qi_session.service('ALMemory')
                self._wake_sub = self.mem.subscriber('robotIsWakeUp')
                self._wake_sub.signal.connect(self._on_wake_change)
                trace('Subscribed to robotIsWakeUp event', True)
            except Exception as e:
                trace('robotIsWakeUp subscribe error: %s' % e, True)

            self.init_naoqi = True
            self.init_done = True
            return True

        except Exception as e:
            trace('NAOqi init error: %s' % e, True)
            return False

    def apply_motor_commands(self):
        if not self.motion or not self.init_done:
            return

        for j in PEPPER_JOINTS:
            idx = j['index']
            if idx < len(self.float_commands16):
                try:
                    angle = self.float_commands16[idx] * j['scale']
                    self.motion.setAngles(j['name'], angle, HEAD_SPEED)
                except Exception as e:
                    trace('Motor error %s: %s' % (j['name'], e), False)

    def _on_wake_change(self, value):
        """Event callback when robotIsWakeUp changes"""
        if not value:
            trace('REST detected via event, recovering...', True)
            try:
                self.motion.setStiffnesses('Body', 1.0)
                self.posture.goToPosture('Stand', 0.5)
                self.motion.wakeUp()
                trace('Recovered from rest, awake=%s' % self.motion.robotIsWakeUp(), True)
            except Exception as e:
                trace('Rest recovery error: %s' % e, True)

    def keepalive_naoqi(self):
        """Refresh stiffness and animate fingers"""
        if not self.motion or not self.init_naoqi:
            return
        try:
            self.motion.setStiffnesses('Body', 1.0)
            # Wiggle fingers to generate activity (prevents 30s idle rest)
            if not hasattr(self, '_finger_state'):
                self._finger_state = False
            self._finger_state = not self._finger_state
            angle = 0.8 if self._finger_state else 0.2
            self.motion.setAngles(
                ['LHand', 'RHand'], [angle, angle], 0.2)
        except Exception as e:
            trace('Keepalive error: %s' % e, True)

    # --- Video streaming ---

    def configure_video(self):
        """Parse video config from server's CAMERAS settings"""
        if not self.conf_video:
            return
        cv = self.conf_video
        self._video_width = int(cv.get('WIDTH', 640))
        self._video_height = int(cv.get('HEIGHT', 480))
        self._video_fps = int(cv.get('FPS', 15))
        self._video_bitrate = int(cv.get('BITRATE', 400))
        # Camera index: 0=top, 1=bottom
        self._video_camera = int(cv.get('SOURCE', 0))
        trace('Video config: %dx%d @%dfps cam=%d bitrate=%d' % (
            self._video_width, self._video_height, self._video_fps,
            self._video_camera, self._video_bitrate), True)

    def start_diffusion(self):
        """Start video pipeline: ALVideoDevice -> ffmpeg stdin -> TCP -> NALU splitter"""
        self.stop_diffusion()
        if not self.video:
            trace('No ALVideoDevice, skipping video', True)
            return

        trace('Starting H.264 video broadcast via ALVideoDevice', True)
        self._start_eye_animation()

        # Build ffmpeg command: read raw YUYV from stdin, encode to H.264, output to TCP
        w = getattr(self, '_video_width', 640)
        h = getattr(self, '_video_height', 480)
        fps = getattr(self, '_video_fps', 15)
        bitrate = getattr(self, '_video_bitrate', 400)
        cmd = ('ffmpeg -f rawvideo -pix_fmt yuyv422 -video_size %dx%d -framerate %d -i pipe: '
               '-pix_fmt yuv420p -c:v libx264 -profile:v baseline -tune zerolatency '
               '-preset ultrafast -x264-params keyint=%d:bframes=0:repeat-headers=1 '
               '-b:v %d -f h264 tcp://127.0.0.1:%d' % (
                   w, h, fps, fps, bitrate, SYS['VIDEOLOCALPORT']))
        trace('ffmpeg command: %s' % cmd, False)

        try:
            self._ffmpeg_proc = subprocess.Popen(
                cmd, shell=True, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            trace('ffmpeg started pid=%d' % self._ffmpeg_proc.pid, True)
        except Exception as e:
            trace('ffmpeg start error: %s' % e, True)
            return

        # Start ffmpeg stderr reader thread
        def _ffmpeg_stderr_reader():
            try:
                for line in self._ffmpeg_proc.stderr:
                    line = line.strip()
                    if line:
                        trace('ffmpeg: %s' % line, False)
            except Exception:
                pass
        t_err = threading.Thread(target=_ffmpeg_stderr_reader)
        t_err.daemon = True
        t_err.start()

        # Start frame grabber thread
        self._diffusion_running = True
        t = threading.Thread(target=self._frame_grabber_loop)
        t.daemon = True
        t.start()

    def _frame_grabber_loop(self):
        """Grab frames from ALVideoDevice and write to ffmpeg stdin"""
        w = getattr(self, '_video_width', 640)
        h = getattr(self, '_video_height', 480)
        fps = getattr(self, '_video_fps', 15)
        cam = getattr(self, '_video_camera', 0)
        frame_interval = 1.0 / fps

        # NAOqi resolution codes: 0=QQVGA(160x120) 1=QVGA(320x240) 2=VGA(640x480)
        if w <= 160:
            res = 0
        elif w <= 320:
            res = 1
        else:
            res = 2
        # Colorspace 9 = kYUV422ColorSpace (YUYV, matches ffmpeg rawvideo input)
        colorspace = 9

        sub = None
        try:
            # Release all existing subscribers to free camera resources
            for old_sub in self.video.getSubscribers():
                try:
                    self.video.unsubscribe(old_sub)
                except Exception:
                    pass
            trace('Cleared existing camera subscribers', False)

            sub = self.video.subscribeCamera('vigiclient_video', cam, res, colorspace, fps)
            trace('Camera subscribed: %s (cam=%d res=%d cs=%d fps=%d)' % (
                sub, cam, res, colorspace, fps), True)

            frame_count = 0
            while self._diffusion_running and self._ffmpeg_proc:
                t0 = time.time()
                try:
                    img = self.video.getImageRemote(sub)
                    if img and len(img) > 6 and img[6]:
                        raw_data = img[6]
                        if isinstance(raw_data, list):
                            raw_data = bytes(bytearray(raw_data))
                        elif not isinstance(raw_data, bytes):
                            raw_data = bytes(raw_data)
                        self._ffmpeg_proc.stdin.write(raw_data)
                        frame_count += 1
                        if frame_count <= 3 or frame_count % 100 == 0:
                            trace('Frame %d: %d bytes written to ffmpeg' % (
                                frame_count, len(raw_data)), False)
                except IOError:
                    trace('ffmpeg stdin closed', False)
                    break
                except Exception as e:
                    trace('Frame grab error: %s' % e, False)

                elapsed = time.time() - t0
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except Exception as e:
            trace('Frame grabber error: %s' % e, True)
        finally:
            if sub:
                try:
                    self.video.unsubscribe(sub)
                    trace('Camera unsubscribed: %s' % sub, True)
                except Exception:
                    pass

    def stop_diffusion(self):
        """Stop video pipeline"""
        self._stop_eye_animation()
        self._diffusion_running = False
        if self._ffmpeg_proc:
            trace('Stopping ffmpeg pid=%d' % self._ffmpeg_proc.pid, False)
            try:
                self._ffmpeg_proc.stdin.close()
            except Exception:
                pass
            try:
                self._ffmpeg_proc.terminate()
                self._ffmpeg_proc.wait()
            except Exception:
                pass
            self._ffmpeg_proc = None
        # Kill any lingering ffmpeg processes (synchronous to avoid race)
        try:
            subprocess.call(['pkill', '-15', '-f', 'ffmpeg.*h264'])
            time.sleep(0.2)
        except Exception:
            pass

    def _start_eye_animation(self):
        """Start rotating eye LED animation while video is streaming"""
        if not self.leds:
            return
        self._eye_anim_running = True

        def eye_loop():
            # FaceLed groups: 8 LEDs per eye, named FaceLedRight0 .. FaceLedRight7
            # and FaceLedLeft0 .. FaceLedLeft7
            idx = 0
            while self._eye_anim_running:
                try:
                    # Dim all eye LEDs
                    self.leds.setIntensity('FaceLeds', 0.1)
                    # Light up current LED pair brightly
                    self.leds.setIntensity('FaceLedRight%d' % idx, 1.0)
                    self.leds.setIntensity('FaceLedLeft%d' % idx, 1.0)
                    idx = (idx + 1) % 8
                except Exception:
                    pass
                time.sleep(0.15)
            # Restore all eye LEDs on stop
            try:
                self.leds.setIntensity('FaceLeds', 1.0)
            except Exception:
                pass

        t = threading.Thread(target=eye_loop)
        t.daemon = True
        t.start()

    def _stop_eye_animation(self):
        """Stop eye LED animation"""
        self._eye_anim_running = False

    def start_video_server(self):
        """Start TCP server that receives H.264 from ffmpeg and splits NALUs"""
        if self._video_server_started:
            return

        self._video_server_started = True
        self._video_server_sock = socket_mod.socket(socket_mod.AF_INET, socket_mod.SOCK_STREAM)
        self._video_server_sock.setsockopt(socket_mod.SOL_SOCKET, socket_mod.SO_REUSEADDR, 1)
        self._video_server_sock.bind(('127.0.0.1', SYS['VIDEOLOCALPORT']))
        self._video_server_sock.listen(1)
        trace('Video TCP server listening on port %d' % SYS['VIDEOLOCALPORT'], True)

        t = threading.Thread(target=self._video_accept_loop)
        t.daemon = True
        t.start()

    def _video_accept_loop(self):
        """Accept ffmpeg connections and process H.264 stream"""
        while True:
            try:
                conn, addr = self._video_server_sock.accept()
                trace('ffmpeg connected to video TCP server', False)
                t = threading.Thread(target=self._video_recv_loop, args=(conn,))
                t.daemon = True
                t.start()
            except Exception as e:
                trace('Video accept error: %s' % e, True)
                break

    def _video_recv_loop(self, conn):
        """Receive H.264 stream, split by NALU separator, send to vigibot"""
        NALU_SEP = b'\x00\x00\x00\x01'
        buf = b''
        nalu_count = 0
        recv_count = 0
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    trace('Video TCP: connection closed (no data)', False)
                    break
                recv_count += 1
                if recv_count <= 3:
                    trace('Video TCP recv #%d: %d bytes' % (recv_count, len(data)), False)
                buf += data
                while True:
                    # Find NALU separator after first position
                    idx = buf.find(NALU_SEP, 1)
                    if idx < 0:
                        break
                    # Extract NALU (without the separator)
                    nalu = buf[:idx]
                    buf = buf[idx + 4:]
                    # Strip leading separator from first NALU
                    if nalu[:4] == NALU_SEP:
                        nalu = nalu[4:]
                    if nalu:
                        nalu_count += 1
                        if nalu_count <= 3 or nalu_count % 100 == 0:
                            trace('NALU #%d: %d bytes' % (nalu_count, len(nalu)), False)
                        self._send_video_nalu(nalu)
        except Exception as e:
            trace('Video recv error: %s' % e, False)
        finally:
            conn.close()
            trace('ffmpeg disconnected from video TCP server', False)

    def _send_video_nalu(self, nalu):
        """Send one H.264 NALU to vigibot server"""
        if not self.current_server:
            return
        sock = self.sockets.get(self.current_server)
        if not sock or not sock.connected:
            return
        # During latency alarm, send empty data (pause video)
        if self.latency_alarm:
            nalu = b''
        sock.emit_binary('serveurrobotvideo', {
            'timestamp': int(time.time() * 1000),
            'data': nalu,
        })

    # --- Server connection ---

    def connect_servers(self):
        ip_priv = get_ip()
        ssid = get_ssid()

        for i, server_url in enumerate(USER['SERVERS']):
            sock = VigiSocket(server_url, SYS['SECUREMOTEPORT'])

            # Register handlers
            if i == 0:
                sock.on('clientsrobotconf', self._on_conf)
                sock.on('clientsrobottx', self._on_tx_factory(server_url))
                sock.on('clientsrobotsys', self._on_sys)
                sock.on('clientsrobottts', self._on_tts)

            sock.on('connect', self._on_connect_factory(server_url, sock, ip_priv, ssid))
            sock.on('disconnect', self._on_disconnect_factory(server_url))
            sock.on('echo', self._on_echo_factory(sock))

            self.sockets[server_url] = sock

            if not sock.connect():
                trace('Failed to connect to %s' % server_url, True)

    def _on_connect_factory(self, server_url, sock, ip_priv, ssid):
        def handler():
            trace('Connected to %s/%d' % (server_url, SYS['SECUREMOTEPORT']), True)
            sock.emit('serveurrobotlogin', {
                'conf': USER,
                'version': VERSION,
                'processTime': PROCESS_TIME,
                'osTime': OS_TIME,
                'ipPriv': ip_priv,
                'ssid': ssid,
            })
            trace('Login sent to %s' % server_url, True)
        return handler

    def _on_disconnect_factory(self, server_url):
        def handler():
            trace('Disconnected from %s' % server_url, True)
            self.sleep()
        return handler

    def _on_echo_factory(self, sock):
        def handler(data):
            sock.emit('echo', {
                'serveur': data,
                'client': int(time.time() * 1000),
            })
        return handler

    def _on_conf(self, data):
        trace('Receiving robot configuration', True)
        self.conf = data['conf']
        self.hard = data['hard']

        self.tx = TxFrame(self.conf['TX'])
        self.rx = RxFrame(self.conf['TX'], self.conf['RX'])

        # Video config from CAMERAS + default command
        cameras = self.hard.get('CAMERAS', [])
        commands = self.conf.get('COMMANDS', [])
        default_cmd = self.conf.get('DEFAULTCOMMAND', 0)
        if cameras and commands and default_cmd < len(commands):
            cam_idx = commands[default_cmd].get('CAMERA', 0)
            if cam_idx < len(cameras):
                self.conf_video = cameras[cam_idx]
        self.configure_video()

        self.init_outputs()

        if not self.up:
            self.write_outputs()

        if not self._timers_started:
            self._timers_started = True
            self._start_timers()

    def _on_tx_factory(self, server_url):
        FRAME0 = ord('$')
        FRAME1S = ord('S')
        FRAME1T = ord('T')

        def handler(data):
            if self.current_server and server_url != self.current_server:
                return
            if not self.init_done or self.tx is None or self.rx is None:
                return

            raw = data.get('data') if isinstance(data, dict) else data
            if raw is None:
                return

            ba = bytearray(raw)
            if len(ba) < 2:
                return
            if ba[0] != FRAME0 or (ba[1] != FRAME1S and ba[1] != FRAME1T):
                trace('Corrupted frame', False)
                return

            now = int(time.time() * 1000)
            if now - self.last_frame < SYS['TXRATE'] // 2:
                return
            self.last_frame = now

            boucle = data.get('boucleVideoCommande', 0) if isinstance(data, dict) else 0
            # boucleVideoCommande=0 when nobody controls, use current time for latency calc
            if boucle == 0:
                boucle = now
            self.last_timestamp = boucle

            if ba[1] == FRAME1S:
                self.tx.load_from(ba)
                self.actions()

            self.wake(server_url)
            self._reset_up_timeout()

            self.set_rx_commands()
            self.set_rx_values()

            # Send RX response with binary
            sock = self.sockets.get(server_url)
            if sock:
                sock.emit_binary('serveurrobotrx', {
                    'timestamp': now,
                    'data': bytes(self.rx.buf),  # PY2: bytes == str
                })

        return handler

    def _on_sys(self, data):
        if data == 'exit':
            trace('Restart requested', True)
            os._exit(0)
        elif data == 'reboot':
            trace('Reboot requested', True)
            subprocess.Popen(['reboot'])
        elif data == 'poweroff':
            trace('Poweroff requested', True)
            subprocess.Popen(['poweroff'])

    def _on_tts(self, data):
        if self.tts and self.init_done and data:
            try:
                self.tts.say(str(data))
            except Exception as e:
                trace('TTS error: %s' % e, False)

    # --- State management ---

    def actions(self):
        for i in range(len(self.conf['TX']['COMMANDS16'])):
            self.float_targets16[i] = self.tx.get_float_command16(i)
        for i in range(len(self.conf['TX']['COMMANDS8'])):
            self.float_targets8[i] = self.tx.get_float_command8(i)
        for i in range(len(self.conf['TX']['COMMANDS1'])):
            self.float_targets1[i] = self.tx.get_command1(i)

    def init_outputs(self):
        n16 = len(self.conf['TX']['COMMANDS16'])
        n8 = len(self.conf['TX']['COMMANDS8'])
        n1 = len(self.conf['TX']['COMMANDS1'])

        self.float_targets16 = [0.0] * n16
        self.float_commands16 = [0.0] * n16
        self.margins16 = [0.0] * n16
        for i in range(n16):
            c = self.conf['TX']['COMMANDS16'][i]
            self.float_targets16[i] = c['INIT']
            self.float_commands16[i] = c['INIT']
            self.margins16[i] = (c['SCALEMAX'] - c['SCALEMIN']) / 65535.0

        self.float_targets8 = [0.0] * n8
        self.float_commands8 = [0.0] * n8
        self.margins8 = [0.0] * n8
        for i in range(n8):
            c = self.conf['TX']['COMMANDS8'][i]
            self.float_targets8[i] = c['INIT']
            self.float_commands8[i] = c['INIT']
            self.margins8[i] = (c['SCALEMAX'] - c['SCALEMIN']) / 255.0

        self.float_targets1 = [0.0] * n1
        self.float_commands1 = [0.0] * n1
        for i in range(n1):
            c = self.conf['TX']['COMMANDS1'][i]
            self.float_targets1[i] = c['INIT']
            self.float_commands1[i] = c['INIT']

    def wake(self, server):
        if self.up:
            return
        if not self.init_done:
            trace('Robot not initialized', True)
            return
        if self.current_server:
            trace('Robot in use by %s' % self.current_server, True)
            return

        trace('Robot wake', True)

        if self.motion:
            try:
                self.motion.setStiffnesses('Body', 1.0)
            except Exception as e:
                trace('Wake motor error: %s' % e, False)

        self.start_diffusion()

        self.current_server = server
        self.up = True
        self.engine = True

    def sleep(self):
        if not self.up:
            return

        trace('Robot sleep', False)

        self.stop_diffusion()

        if self.conf.get('TX'):
            for i in range(len(self.conf['TX']['COMMANDS16'])):
                if self.hard.get('COMMANDS16', [{}] * (i + 1))[i].get('SLEEP'):
                    self.float_targets16[i] = self.conf['TX']['COMMANDS16'][i]['INIT']
            for i in range(len(self.conf['TX']['COMMANDS8'])):
                if self.hard.get('COMMANDS8', [{}] * (i + 1))[i].get('SLEEP'):
                    self.float_targets8[i] = self.conf['TX']['COMMANDS8'][i]['INIT']
            for i in range(len(self.conf['TX']['COMMANDS1'])):
                if self.hard.get('COMMANDS1', [{}] * (i + 1))[i].get('SLEEP'):
                    self.float_targets1[i] = self.conf['TX']['COMMANDS1'][i]['INIT']

        self.current_server = ''
        self.up = False

    def _reset_up_timeout(self):
        if self.up_timeout:
            self.up_timeout.cancel()
        self.up_timeout = threading.Timer(SYS['UPTIMEOUT'] / 1000.0, self.sleep)
        self.up_timeout.daemon = True
        self.up_timeout.start()

    # --- RX frame building ---

    def set_rx_commands(self):
        if not self.tx or not self.rx:
            return
        for i in range(len(self.conf['TX']['COMMANDS16'])):
            raw = self.tx.compute_raw_command16(i, self.float_commands16[i])
            self.rx.set_cmd16_raw(i, raw)
        if self.tx.cam_len > 0:
            self.rx.set_camera_choice(0, self.tx.get_camera_choice(0))
        for i in range(len(self.conf['TX']['COMMANDS8'])):
            raw = self.tx.compute_raw_command8(i, self.float_commands8[i])
            self.rx.set_cmd8_raw(i, raw)
        nb1_bytes = int(math.ceil(len(self.conf['TX']['COMMANDS1']) / 8.0))
        for i in range(nb1_bytes):
            cmd1 = 0
            for j in range(8):
                idx = i * 8 + j
                if idx < len(self.float_commands1) and self.float_commands1[idx] > 0:
                    cmd1 += 1 << j
            self.rx.set_cmd1_byte(i, cmd1)

    def set_rx_values(self):
        if not self.rx:
            return
        # VALUES16: [0]=voltage, [1]=battery
        if self.rx.val16_len > 0:
            self.rx.set_float_value16(0, self.voltage)
        if self.rx.val16_len > 1:
            self.rx.set_float_value16(1, self.battery)
        # VALUES8: [0]=cpu, [1]=temp, [2]=link, [3]=rssi
        if self.rx.val8_len > 0:
            self.rx.set_float_value8(0, self.cpu_load)
        if self.rx.val8_len > 1:
            self.rx.set_float_value8(1, self.soc_temp)
        if self.rx.val8_len > 2:
            self.rx.set_float_value8(2, self.link)
        if self.rx.val8_len > 3:
            self.rx.set_float_value8(3, self.rssi)

    # --- Output / Servo loop ---

    def write_outputs(self):
        self.apply_motor_commands()

    # --- Sensor reading ---

    def _read_cpu_times(self):
        try:
            with open('/proc/stat') as f:
                line = f.readline()
            parts = line.split()
            user = int(parts[1])
            nice = int(parts[2])
            system = int(parts[3])
            idle = int(parts[4])
            return (user + nice + system, idle)
        except Exception:
            return (0, 0)

    def read_cpu(self):
        curr = self._read_cpu_times()
        d_busy = curr[0] - self._prev_cpu[0]
        d_idle = curr[1] - self._prev_cpu[1]
        total = d_busy + d_idle
        self.cpu_load = int(100 * d_busy / total) if total > 0 else 0
        self._prev_cpu = curr

    def read_temp(self):
        try:
            with open(SYS['TEMPFILE']) as f:
                self.soc_temp = int(f.read().strip()) / 1000.0
        except Exception:
            pass

    def read_wifi(self):
        try:
            with open(SYS['WIFIFILE']) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) > 4 and 'wlan' in parts[0]:
                        self.link = float(parts[2].rstrip('.'))
                        self.rssi = float(parts[3].rstrip('.'))
        except Exception:
            pass

    def read_battery(self):
        if not self.battery_svc or not self.init_done:
            return
        try:
            self.battery = self.battery_svc.getBatteryCharge()
            # Simulate single LiIon cell voltage from charge percentage
            self.voltage = 3.0 + 1.2 * self.battery / 100.0
        except Exception:
            pass

    # --- Timers ---

    def _start_timers(self):
        self._start_periodic('servo', SYS['SERVORATE'] / 1000.0, self._servo_tick)
        self._start_periodic('beacon', SYS['BEACONRATE'] / 1000.0, self._beacon_tick)
        self._start_periodic('cpu', SYS['CPURATE'] / 1000.0, self.read_cpu)
        self._start_periodic('temp', SYS['TEMPRATE'] / 1000.0, self.read_temp)
        self._start_periodic('wifi', SYS['WIFIRATE'] / 1000.0, self.read_wifi)
        self._start_periodic('battery', SYS['GAUGERATE'] / 1000.0, self.read_battery)
        self._start_periodic('keepalive', 5.0, self.keepalive_naoqi)

    def _start_periodic(self, name, interval, func):
        def loop():
            while True:
                time.sleep(interval)
                try:
                    func()
                except Exception as e:
                    trace('Timer %s error: %s' % (name, e), False)
        t = threading.Thread(target=loop)
        t.daemon = True
        t.start()

    def _servo_tick(self):
        if not self.engine:
            return
        if not self.conf.get('TX'):
            return

        change = False
        now = int(time.time() * 1000)
        predictive_latency = now - self.last_timestamp

        if predictive_latency < SYS['LATENCYALARMEND'] and self.latency_alarm:
            trace('%d ms latency, resuming' % predictive_latency, False)
            self.latency_alarm = False
        elif predictive_latency > SYS['LATENCYALARMBEGIN'] and not self.latency_alarm:
            trace('%d ms latency, failsafe' % predictive_latency, False)
            self.latency_alarm = True

        if self.latency_alarm:
            for i in range(len(self.conf['TX']['COMMANDS16'])):
                if self.hard.get('COMMANDS16', [{}] * (i + 1))[i].get('FAILSAFE'):
                    self.float_targets16[i] = self.conf['TX']['COMMANDS16'][i]['INIT']
            for i in range(len(self.conf['TX']['COMMANDS8'])):
                if self.hard.get('COMMANDS8', [{}] * (i + 1))[i].get('FAILSAFE'):
                    self.float_targets8[i] = self.conf['TX']['COMMANDS8'][i]['INIT']
            for i in range(len(self.conf['TX']['COMMANDS1'])):
                if self.hard.get('COMMANDS1', [{}] * (i + 1))[i].get('FAILSAFE'):
                    self.float_targets1[i] = self.conf['TX']['COMMANDS1'][i]['INIT']

        # Ramp engine for COMMANDS16
        for i in range(len(self.float_commands16)):
            if self.float_commands16[i] == self.float_targets16[i]:
                continue
            change = True

            target = self.float_targets16[i]
            init = self.conf['TX']['COMMANDS16'][i]['INIT']
            h = self.hard.get('COMMANDS16', [{}] * (i + 1))[i]

            if abs(target - init) <= self.margins16[i]:
                delta = h.get('RAMPINIT', 0)
            elif (target - init) * (self.float_commands16[i] - init) < 0:
                delta = h.get('RAMPDOWN', 0)
                target = init
            elif abs(target) - abs(self.float_commands16[i]) < 0:
                delta = h.get('RAMPDOWN', 0)
            else:
                delta = h.get('RAMPUP', 0)

            if delta <= 0:
                self.float_commands16[i] = target
            elif self.float_commands16[i] - target < -delta:
                self.float_commands16[i] += delta
            elif self.float_commands16[i] - target > delta:
                self.float_commands16[i] -= delta
            else:
                self.float_commands16[i] = target

        # Ramp engine for COMMANDS8
        for i in range(len(self.float_commands8)):
            if self.float_commands8[i] == self.float_targets8[i]:
                continue
            change = True

            target = self.float_targets8[i]
            init = self.conf['TX']['COMMANDS8'][i]['INIT']
            h = self.hard.get('COMMANDS8', [{}] * (i + 1))[i]

            if abs(target - init) <= self.margins8[i]:
                delta = h.get('RAMPINIT', 0)
            elif (target - init) * (self.float_commands8[i] - init) < 0:
                delta = h.get('RAMPDOWN', 0)
                target = init
            elif abs(target) - abs(self.float_commands8[i]) < 0:
                delta = h.get('RAMPDOWN', 0)
            else:
                delta = h.get('RAMPUP', 0)

            if delta <= 0:
                self.float_commands8[i] = target
            elif self.float_commands8[i] - target < -delta:
                self.float_commands8[i] += delta
            elif self.float_commands8[i] - target > delta:
                self.float_commands8[i] -= delta
            else:
                self.float_commands8[i] = target

        # Ramp engine for COMMANDS1
        for i in range(len(self.float_commands1)):
            if self.float_commands1[i] == self.float_targets1[i]:
                continue
            change = True

            h = self.hard.get('COMMANDS1', [{}] * (i + 1))[i]
            if abs(self.float_targets1[i] - self.conf['TX']['COMMANDS1'][i]['INIT']) < 1:
                delta = h.get('RAMPINIT', 0)
            else:
                delta = h.get('RAMPUP', 0)

            if delta <= 0:
                self.float_commands1[i] = self.float_targets1[i]
            elif self.float_targets1[i] - self.float_commands1[i] > delta:
                self.float_commands1[i] += delta
            elif self.float_targets1[i] - self.float_commands1[i] < -delta:
                self.float_commands1[i] -= delta
            else:
                self.float_commands1[i] = self.float_targets1[i]

        if change:
            self.write_outputs()
        elif not self.up:
            self.engine = False

    def _beacon_tick(self):
        if self.up or not self.init_done:
            return
        if not self.rx:
            return

        self.set_rx_commands()
        self.set_rx_values()

        now = int(time.time() * 1000)
        for server_url, sock in self.sockets.items():
            if sock.connected:
                sock.emit_binary('serveurrobotrx', {
                    'timestamp': now,
                    'data': bytes(self.rx.buf),
                })

    # --- Main ---

    def run(self):
        trace('Pepper vigiclient start (Python)', True)
        trace('VERSION=%d' % VERSION, True)

        # Init NAOqi first (blocking - wakeUp takes 15-30s)
        if not self.init_naoqi_session():
            trace('NAOqi init failed, exiting', True)
            sys.exit(1)

        # Start video TCP server (listens for ffmpeg H.264 output)
        self.start_video_server()

        # Connect to vigibot servers
        self.connect_servers()

        # Keep main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            trace('Interrupted', True)
            for sock in self.sockets.values():
                sock.disconnect()


if __name__ == '__main__':
    client = VigiClient()
    client.run()
