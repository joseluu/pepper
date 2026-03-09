# qinode — Node.js Bindings for NAOqi (Pepper Robot)

## Goal

Control Pepper from Node.js running on a PC (not on the robot). Connect over the network to NAOqi services, call methods, subscribe to events.

## Approach Decision: Socket.IO vs Binary Protocol

### Option A: Socket.IO (via robot's built-in bridge)

The robot already runs `qimessaging-json`, a Tornado/Python 2 process that bridges Socket.IO ↔ QiMessaging binary protocol. The official browser SDK (`qimessaging.js`) uses this.

**Pros:**
- No binary protocol implementation needed — JSON over Socket.IO
- Battle-tested: this is how all Choregraphe web apps communicate
- Works from any machine on the network (PC, laptop, server)
- Much simpler implementation (~200 lines vs ~1000+)

**Cons:**
- Depends on the robot's `qimessaging-json` bridge (always running, part of NAOqiOS)
- Cannot run on the robot itself (bridge is localhost-only for the binary side)
- Socket.IO version mismatch: robot serves v0.9.11 (2013), modern `socket.io-client` npm is v4.x
- Extra serialization hop: JS → JSON → Socket.IO → bridge → binary → NAOqi

### Option B: Raw binary QiMessaging protocol (like qipy)

Implement the 36-byte header, binary serialization, auth handshake directly over TCP.

**Pros:**
- No dependency on the bridge process
- Could also run ON the robot (direct localhost:9559)
- Lower latency, no double-serialization
- Shares protocol knowledge with qipy

**Cons:**
- Significantly more work (protocol.js, serialization.js, etc.)
- Duplicates effort already planned for qipy
- Node.js Buffer API is capable but verbose for binary parsing

### Decision: Option A (Socket.IO)

The Socket.IO approach is the right choice for Node.js because:
1. Node.js is for PC-side control, not on-robot scripts (Python 3 covers that)
2. The bridge already exists and is always running
3. Implementation is dramatically simpler
4. The main challenge is just Socket.IO version compatibility

If raw binary is ever needed, qipy (Python) already covers that path.

---

## Existing Work

### `node-naoqi` (npm: `naoqi`) — abandoned, unusable as-is

- 1 commit, last updated 2017, 3 stars
- Uses `socket.io-client@1.0.2` — incompatible with robot's Socket.IO 0.9.x server
- Babel/ES2015 transpilation, dated patterns
- `using()` pattern requires declaring all services upfront before `onload`
- No TypeScript, no tests worth speaking of

However, its architecture confirms the approach works: Socket.IO → service call → JSON response → Promise.

### `qimessaging.js` (official, aldebaran/libqi-js)

The browser SDK bundled on the robot at `http://<robot>/libs/qimessaging/2/qimessaging.js`. Key implementation details extracted:

- Connects via: `io.connect("http://" + host, { resource: "libs/qimessaging/2/socket.io" })`
- Socket.IO v0.9.11 bundled inline
- Message protocol over Socket.IO:
  - **Emit `'call'`**: `{ idm: <counter>, params: { service: name, method: name, args: [...] } }`
  - **Receive `'reply'`**: `{ idm: <counter>, result: { pyobject: id, metaobject: {...}, ... } }`
  - **Receive `'error'`**: `{ idm: <counter>, result: { error: "..." } }`
  - **Receive `'signal'`**: `{ result: { link: id, data: [...] } }`
- Service discovery: call `("ServiceDirectory", "service", [name])` → returns metaobject
- Metaobject contains methods/signals/properties maps → dynamically generates callable proxy
- Signal connect: call `(service, "registerEvent", [objectId, signalId, linkId])`
- Signal disconnect: call `(service, "unregisterEvent", [objectId, signalId, linkId])`

---

## Socket.IO Version Compatibility

The robot runs Socket.IO **0.9.11** (Engine.IO didn't exist yet — this is the old protocol with XHR polling + WebSocket upgrade, custom framing).

Modern `socket.io-client` (v4.x) speaks an entirely different wire protocol and **will not connect**.

### Verified: `socket.io-client@0.9.16` works

Tested 2026-03-09 on Node.js v18.20.6 (WSL2):

```
$ npm install socket.io-client@0.9.16   # installs fine, 10 packages
$ node -e "var io = require('socket.io-client'); console.log(io.version)"
0.9.16
```

**It loads and runs without errors on modern Node.js.** This is the last 0.9.x release and speaks the exact same protocol as the robot's 0.9.11 server.

### Dependencies (all bundled, no transitive installs)

| Package | Version | Role | Notes |
|---------|---------|------|-------|
| `ws` | 0.4.x | WebSocket client | Works on Node 18. Has a DoS CVE — irrelevant for LAN robot control |
| `xmlhttprequest` | 1.4.2 | XHR polyfill for HTTP polling | Only used during initial handshake before WebSocket upgrade. Has a code injection CVE — only exploitable if fetching attacker-controlled URLs (we only connect to our robot) |
| `uglify-js` | 1.2.5 | JS minifier | Build-time only, never runs at runtime. Has ReDoS CVEs — no impact |
| `active-x-obfuscator` | 0.0.1 | ActiveX workaround | IE legacy, inert on Node.js |

### npm audit (4 vulnerabilities — all non-issues)

```
uglify-js  <=2.5.0       critical  ReDoS + minification bug    (build-time only, never executes)
ws         <=1.1.4        high      DoS via large message       (LAN-only, trusted robot)
xmlhttprequest <1.7.0     critical  Code injection              (only connects to our robot IP)
socket.io-client 0.7-0.9  (rolls up above)
```

**None of these matter for our use case**: we connect to a single trusted robot on a local network. The CVEs require either attacker-controlled input or internet-facing exposure, neither of which applies.

### Fallback plan (if ever needed)

If a future Node.js version breaks `ws@0.4.x`, we can:
1. Replace `ws@0.4.x` with modern `ws@8.x` — the API is mostly compatible
2. Or skip Socket.IO entirely and speak raw WebSocket to the bridge with Socket.IO 0.9 framing (5-style message encoding: `5:::{json}`)

---

## Architecture

```
qinode/
├── package.json
├── lib/
│   ├── index.js           # public API: Session, connect()
│   ├── session.js          # Socket.IO connection, auth, call dispatch
│   ├── proxy.js            # ServiceProxy with dynamic method generation
│   └── signal.js           # signal subscription management
├── examples/
│   ├── hello.js            # say hello
│   ├── list-services.js    # enumerate all services
│   └── motion.js           # wave arm
└── test/
    └── session.test.js     # integration tests against real robot
```

No TypeScript initially — plain JS with JSDoc comments. Can add TypeScript later.

Dependencies: `socket.io-client@0.9.16` only.

---

## Target API

```javascript
const { Session } = require('qinode');

async function main() {
  const session = new Session('192.168.11.182');
  await session.connect();

  // Get a service proxy
  const tts = await session.service('ALTextToSpeech');
  await tts.say('Hello from Node.js!');

  // List available methods
  const system = await session.service('ALSystem');
  console.log(await system.systemVersion());

  // Motion
  const motion = await session.service('ALMotion');
  await motion.wakeUp();
  await motion.setAngles(['HeadYaw'], [0.5], 0.2);

  // Events
  const memory = await session.service('ALMemory');
  const subscriber = await memory.subscriber('FrontTactilTouched');
  subscriber.on('signal', (value) => {
    console.log('Head touched!', value);
  });

  // Cleanup
  session.disconnect();
}

main().catch(console.error);
```

---

## Implementation Plan

### Phase 1: Connection & Basic Calls

**File: `lib/session.js`**

1. `Session` class constructor takes `host` (IP or hostname)
2. `connect()`:
   - Create Socket.IO connection to `http://<host>` with `resource: "libs/qimessaging/2/socket.io"`
   - Return a Promise that resolves on `'connect'` event, rejects on `'error'`
3. Internal state:
   - `_idm`: message ID counter
   - `_pending`: `Map<id, {resolve, reject}>` for in-flight calls
4. `_call(service, method, args) → Promise`:
   - Increment `_idm`
   - Emit `'call'` with `{ idm, params: { service, method, args } }`
   - Store resolve/reject in `_pending[idm]`
   - On `'reply'` event: resolve `_pending[idm]` with `result`
   - On `'error'` event: reject `_pending[idm]`
5. `disconnect()`: close socket, reject all pending calls

**Validation**: Connect to pepper, call `_call("ServiceDirectory", "service", ["ALSystem"])`, print the metaobject.

### Phase 2: Service Proxy

**File: `lib/proxy.js`**

1. `session.service(name) → Promise<ServiceProxy>`:
   - Call `ServiceDirectory.service(name)` via `_call`
   - Receive metaobject with methods/signals/properties maps
   - Return a `ServiceProxy` wrapping the metaobject
2. `ServiceProxy`:
   - Constructor parses metaobject, extracts method names
   - Uses `Proxy` (ES6) or `__defineGetter__` to dynamically generate methods
   - Each method returns a Promise: `proxy.say("hello")` → `session._call(serviceName, "say", ["hello"])`
   - `listMethods()` returns available method names
3. Handle nested objects: some method returns include a `pyobject` ID + metaobject → wrap in a new ServiceProxy

**Validation**: `session.service("ALTextToSpeech").then(tts => tts.say("Hello"))`.

### Phase 3: Signals & Events

**File: `lib/signal.js`**

1. Signal subscription via the metaobject's signal list
2. `proxy.signalName.connect(callback)`:
   - Call `registerEvent` on the service
   - Register callback in local signal map
   - On `'signal'` socket event: dispatch to registered callbacks
3. `proxy.signalName.disconnect(linkId)`:
   - Call `unregisterEvent`
   - Remove callback

**Validation**: Subscribe to `FrontTactilTouched` via ALMemory subscriber, touch pepper's head, see event.

### Phase 4: Error Handling & Robustness

1. Call timeout (default 10s) — reject pending promise if no reply
2. Connection lost: reject all pending, emit `'disconnected'` event
3. Reconnection: optional auto-reconnect with backoff
4. Proper cleanup: `session.disconnect()` unsubscribes all signals first

### Phase 5: Examples & Polish

1. `examples/hello.js` — say hello, print system version
2. `examples/list-services.js` — list all NAOqi services
3. `examples/motion.js` — wave arm
4. `examples/events.js` — react to head touch
5. `examples/camera.js` — trigger photo capture (ALPhotoCapture.takePicture saves to file, then SCP it)
6. JSDoc on all public methods
7. `README.md` with quickstart

---

## Socket.IO 0.9 Message Protocol Details

From reverse-engineering `qimessaging.js` and the `node-naoqi` source:

### Client → Robot

```javascript
// Emit event name: 'call'
// Payload:
{
  "idm": 1,                    // message counter
  "params": {
    "service": "ALTextToSpeech",  // service name (string)
    "method": "say",              // method name (string)
    "args": ["Hello"]             // arguments (JSON array)
  }
}
```

### Robot → Client

```javascript
// Event: 'reply'
{
  "idm": 1,
  "result": "anything"          // JSON-serialized return value
}

// If the result is a service/object, it includes metaobject:
{
  "idm": 1,
  "result": {
    "metaobject": {
      "methods": { "100": { "name": "say", ... }, ... },
      "signals": { ... },
      "properties": { ... }
    },
    "pyobject": 42              // object reference ID
  }
}

// Event: 'error'
{
  "idm": 1,
  "result": {
    "error": "Service not found"
  }
}

// Event: 'signal'
{
  "result": {
    "link": "signal-link-id",
    "data": [1.0]               // signal payload
  }
}
```

### Service call routing

Once you have a `pyobject` ID from a service lookup, subsequent calls reference it:
```javascript
{
  "idm": 2,
  "params": {
    "service": "ALTextToSpeech",  // or the pyobject ID as string
    "method": "say",
    "args": ["Hello"]
  }
}
```

---

## Comparison with qipy

| Aspect | qipy (Python 3) | qinode (Node.js) |
|--------|-----------------|-----------------|
| Runs on | Robot (on-board) | PC (remote) |
| Protocol | Raw binary TCP (port 9559) | Socket.IO JSON (port 80) |
| Dependency | None (stdlib only) | socket.io-client 0.9.x |
| Complexity | ~1000 lines | ~300 lines |
| Latency | ~2ms (local socket) | ~5-10ms (network + JSON + bridge) |
| Auth | Binary capability exchange | None (bridge handles it) |
| Binary data | Possible (raw type) | No (JSON only) |
| Signals | Direct event messages | Via bridge signal relay |

They complement each other: qipy for on-robot Python 3 scripts, qinode for PC-side orchestration, dashboards, testing.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| ~~`socket.io-client@0.9.16` breaks on modern Node.js~~ | ~~Test with Node 18/20/22~~ **Verified working on Node 18.20.6** |
| Socket.IO 0.9 handshake is HTTP polling first | Normal — 0.9.x does XHR handshake then upgrades to WebSocket. Performance is fine for robot control |
| Robot bridge has undocumented quirks | Use `qimessaging.js` as the reference implementation — it works, so matching its exact message format will work |
| Large return values (camera images) | ALPhotoCapture saves to disk, transfer via SCP/SFTP. Don't try to stream raw camera data over Socket.IO JSON |
| Signal reliability | Socket.IO 0.9 has no built-in ack for signals. Accept that events can be lost on network hiccups |
| Future Node.js breaks `ws@0.4.x` | Swap in modern `ws@8.x` (compatible API) or use raw WebSocket with SIO 0.9 framing |

---

## H.264 Video Streaming via Broadway.js

### Context

Pepper has no built-in video streaming endpoint. ALVideoDevice only provides a subscribe/poll API returning raw pixel buffers. Sending those over Socket.IO JSON is impractical (921KB per VGA frame as JSON integer array).

**Broadway.js** is a pure JavaScript H.264 decoder (Emscripten port of Android's H.264 decoder). It accepts raw Annex B NAL units and renders to `<canvas>`. Feeding it NAL units over WebSocket is the lowest-latency browser-compatible streaming approach — no container format, no HLS/DASH segmenting, no media server.

### What the robot has

| Component | Details |
|-----------|---------|
| **libx264** | `libx264.so.144` — software H.264 encoding |
| **VA-API H.264** | `i965_drv_video.so` + GStreamer `vaapiencode_h264` — **hardware** encoding on the Intel Atom GPU |
| **ffmpeg 3.0** | Compiled with `--enable-libx264`, can output raw Annex B stream |
| **GStreamer 0.10** | `gstx264enc` with `annexb=1` for byte-stream NAL output |
| **V4L2 cameras** | `/dev/video-top`, `/dev/video-bottom`, `/dev/video-stereo` |
| **Tornado 4.3** | `tornado.websocket` — native WebSocket server (Python 2) |
| **nginx** | Port 80, can proxy WebSocket (`proxy_set_header Upgrade` already configured for Socket.IO) |

### Architecture

```
/dev/video-top (V4L2)
    │
    ▼
ffmpeg -f v4l2 ... -c:v libx264 -profile:v baseline -tune zerolatency -f h264 pipe:1
    │
    ▼ raw Annex B H.264 stream (stdout)
    │
Python 2 Tornado WebSocket server (on robot, port 8080)
    │ split on 00 00 00 01 start codes
    │ send each NAL as one binary WebSocket message
    ▼
Browser: WebSocket → Broadway.js → <canvas>
```

### ffmpeg commands

**Software encoding** (works, but Atom CPU is weak):
```bash
ffmpeg -f v4l2 -video_size 320x240 -framerate 15 -i /dev/video-top \
  -c:v libx264 -profile:v baseline -level 3.0 \
  -tune zerolatency -preset ultrafast \
  -x264-params "keyint=30:bframes=0:repeat-headers=1" \
  -f h264 -
```

**VA-API hardware encoding** (preferred — offloads to Intel GPU):
```bash
ffmpeg -vaapi_device /dev/dri/renderD128 \
  -f v4l2 -video_size 320x240 -framerate 15 -i /dev/video-top \
  -vf 'format=nv12,hwupload' \
  -c:v h264_vaapi -profile:v constrained_baseline \
  -f h264 -
```

Key parameters for Broadway.js compatibility:
- **Baseline profile** (no B-frames, no CABAC — Broadway.js doesn't support Main/High)
- **`repeat-headers=1`** or `repeat_sequence_header=1` — SPS/PPS on every keyframe so browser can join mid-stream
- **`-tune zerolatency`** — disables lookahead buffering
- **`-f h264`** — raw Annex B output (no container)

### WebSocket server (Python 2, Tornado, ~40 lines)

```python
#!/usr/bin/python2
import tornado.ioloop, tornado.web, tornado.websocket
import subprocess

clients = set()
NAL_SEP = b'\x00\x00\x00\x01'

class VideoHandler(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin): return True
    def open(self): clients.add(self)
    def on_close(self): clients.discard(self)

def stream_video():
    proc = subprocess.Popen(
        ['ffmpeg', '-f', 'v4l2', '-video_size', '320x240', '-framerate', '15',
         '-i', '/dev/video-top', '-c:v', 'libx264', '-profile:v', 'baseline',
         '-tune', 'zerolatency', '-preset', 'ultrafast',
         '-x264-params', 'keyint=30:bframes=0:repeat-headers=1',
         '-f', 'h264', '-'],
        stdout=subprocess.PIPE, stderr=open('/dev/null', 'w'))
    buf = b''
    while True:
        chunk = proc.stdout.read(4096)
        if not chunk: break
        buf += chunk
        while NAL_SEP in buf[1:]:
            idx = buf.index(NAL_SEP, 1)
            nal = buf[:idx]
            buf = buf[idx:]
            for c in clients:
                c.write_message(nal, binary=True)

app = tornado.web.Application([(r'/video', VideoHandler)])
app.listen(8080)
tornado.ioloop.IOLoop.current().spawn_callback(stream_video)
tornado.ioloop.IOLoop.current().start()
```

### Browser client

```html
<canvas id="video" width="320" height="240"></canvas>
<script src="broadway/Decoder.js"></script>
<script>
var canvas = document.getElementById('video');
var decoder = new Decoder({useWorker: true, webgl: 'auto'});
document.body.appendChild(decoder.domElement);  // or render to existing canvas

var ws = new WebSocket('ws://192.168.11.182:8080/video');
ws.binaryType = 'arraybuffer';
ws.onmessage = function(e) {
  decoder.decode(new Uint8Array(e.data));
};
</script>
```

### nginx proxy (optional, to serve on port 80)

Add to the existing `/etc/nginx/nginx.conf`:
```nginx
location /video {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

### Performance estimates

| Resolution | Encoder | CPU impact | NAL size | Latency |
|-----------|---------|-----------|----------|---------|
| QVGA 320×240 @15fps | x264 ultrafast | ~40% of one core | 1-5 KB | ~80ms |
| QVGA 320×240 @15fps | h264_vaapi | ~5% | 1-5 KB | ~55ms |
| VGA 640×480 @10fps | h264_vaapi | ~10% | 5-15 KB | ~70ms |

VAAPI hardware encoding is strongly preferred on Pepper's weak Atom CPU.

---

## Adapting vigiclient to Run on Pepper

### What is vigiclient

[vigiclient](https://github.com/vigibot/vigiclient) is a Node.js 10 client that connects Raspberry Pi robots to [vigibot.com](https://vigibot.com) for remote control and video streaming. It:

- Connects to vigibot.com servers via **Socket.IO 2.3** (WebSocket transport)
- Captures H.264 video from the Pi's V4L2 camera (hardware-encoded by the BCM2835 GPU)
- **Splits the H.264 stream into NAL units** using `stream-split` on `00 00 00 01` separator
- Sends each NAL as a Socket.IO binary event (`serveurrobotvideo`)
- Receives servo/motor commands via Socket.IO, drives GPIO/I2C hardware
- Sends telemetry (battery, CPU temp, RSSI, GPS) back to the server

### vigiclient dependencies

| Dependency | Purpose | Pepper-compatible? |
|-----------|---------|-------------------|
| `socket.io-client@^2.3.0` | Server connection | **Yes** — pure JS |
| `stream-split@^1.1.0` | NAL unit splitting | **Yes** — pure JS |
| `pigpio@^3.2.3` | Raspberry Pi GPIO | **No** — Pi-specific, native addon for BCM2835 |
| `i2c-bus@^5.2.0` | I2C communication | **No** — native addon, Linux i2c-dev (Pepper has I2C but different bus layout) |
| `pca9685@^4.0.3` | PWM servo driver | **No** — requires i2c-bus, Pi-specific hardware |
| `ina219@^0.6.2` | Current/voltage sensor | **No** — requires i2c-bus |
| `serialport@^8.0.8` | Serial/UART | **Maybe** — native addon, needs rebuild for i686 |
| `gps@^0.6.0` | GPS NMEA parsing | **Yes** — pure JS |

### Feasibility assessment

**The video streaming part is directly portable.** vigiclient's NAL-over-Socket.IO architecture is exactly the Broadway.js pattern described above. The video pipeline is:

```
V4L2 camera → ffmpeg (H.264 baseline) → TCP localhost → stream-split (NAL) → Socket.IO → vigibot.com
```

On Pepper, this becomes:
```
/dev/video-top → ffmpeg (H.264 baseline, x264 or vaapi) → TCP localhost → stream-split (NAL) → Socket.IO → vigibot.com
```

**The hardware control part needs a complete rewrite** for Pepper — no GPIO/pigpio, no PCA9685 servos. Instead, motor commands would go through NAOqi's ALMotion service. This is a different abstraction entirely.

### Node.js 10 on Pepper — the main blocker

Pepper runs NAOqiOS (Yocto Linux, i686 32-bit, glibc 2.23). No Node.js is installed. To run vigiclient on Pepper:

1. **Build or obtain Node.js 10 for i686 + glibc 2.23**
   - Node.js 10.24.1 (last LTS) official builds: only x64 and armv7l — **no i686 build provided**
   - Must cross-compile or build in Docker (`i386/ubuntu:16.04`, same as our Python 3.5 build)
   - Node.js 10 should build on glibc 2.23 — it required glibc ≥ 2.17
   - Install to `/data/node10/` (same approach as Python 3.5 — root fs has no space)

2. **Native addons**
   - `pigpio`: **drop entirely** — no BCM2835 on Pepper
   - `i2c-bus`, `pca9685`, `ina219`: **drop** — Pepper's motors are controlled via NAOqi, not I2C
   - `serialport`: **drop unless needed** — would need rebuild for i686
   - `stream-split`, `socket.io-client`, `gps`: **work as-is** — pure JavaScript

3. **Video capture**
   - Replace Pi's `raspivid`/`v4l2-ctl` with ffmpeg commands for Pepper's V4L2 cameras
   - V4L2 devices: `/dev/video-top` (top camera), `/dev/video-bottom` (bottom camera)
   - Use `ffmpeg -f v4l2 ... -c:v libx264 -profile:v baseline -tune zerolatency -f h264 tcp://127.0.0.1:<port>`
   - Or use VA-API hardware encoding if available: `-c:v h264_vaapi`
   - vigiclient reads from TCP on localhost, so the interface is identical

4. **Motor control adaptation**
   - Replace `pigpio` GPIO writes with NAOqi ALMotion calls
   - Two options:
     - **a)** Use qimessaging-json Socket.IO bridge from Node.js (port 8002) — vigiclient already uses Socket.IO
     - **b)** Spawn a Python 2 subprocess that receives commands via stdin/pipe and calls qi.Session directly
   - Map vigibot's servo channels to Pepper's joint names (HeadYaw, HeadPitch, RShoulderPitch, etc.)

5. **Telemetry**
   - CPU temperature: read from `/sys/class/thermal/` (same Linux interface)
   - Battery: NAOqi ALBattery service → getBatteryCharge()
   - WiFi RSSI: `iwconfig` parsing (same as Pi)
   - No GPS on Pepper (unless USB GPS added)

### Proposed architecture for vigiclient on Pepper

```
                    vigibot.com
                        ▲
                        │ Socket.IO 2.3 (WebSocket)
                        │
              ┌─────────┴──────────┐
              │  vigiclient-pepper  │  (Node.js 10, /data/node10/)
              │  (modified fork)    │
              └──┬─────────┬───────┘
                 │         │
    NAL stream   │         │  motor commands
    (TCP pipe)   │         │
                 │         ▼
                 │    NAOqi bridge
                 │    (Socket.IO → port 8002
                 │     or Python 2 subprocess)
                 │         │
                 │         ▼
    ffmpeg       │    ALMotion / ALTextToSpeech / ...
    (H.264)      │         │
       ▲         │         ▼
       │         │    NAOqi (port 9559)
  /dev/video-top │
```

### What to keep, what to replace

| vigiclient component | Action | Replacement |
|---------------------|--------|-------------|
| `clientrobotpi.js` (main) | **Fork & modify** | Remove Pi-specific code, add NAOqi bridge |
| `trame.js` (telemetry) | **Keep** | Adapt Tx/Rx fields to Pepper's joints |
| `socket.io-client` | **Keep** | Same version, same vigibot protocol |
| `stream-split` | **Keep** | Same NAL splitting logic |
| `pigpio` | **Remove** | Replace with NAOqi ALMotion calls |
| `i2c-bus`, `pca9685`, `ina219` | **Remove** | Battery via ALBattery, no servo board |
| `serialport` | **Remove** | No serial peripherals |
| `gps` | **Remove** | No GPS on Pepper |
| Video capture command | **Replace** | ffmpeg with Pepper's V4L2 devices |
| `install.sh` | **Rewrite** | Build Node.js 10 for i686, install to /data |

### Build plan for Node.js 10 on Pepper

Same Docker approach as Python 3.5:

```dockerfile
FROM i386/ubuntu:16.04
RUN apt-get update && apt-get install -y build-essential python2.7 git curl
RUN curl -O https://nodejs.org/dist/v10.24.1/node-v10.24.1.tar.gz && \
    tar xzf node-v10.24.1.tar.gz
RUN cd node-v10.24.1 && \
    ./configure --prefix=/opt/node10 --partly-progress --without-snapshot && \
    make -j$(nproc) && make install
CMD tar czf /out/node10_pepper.tar.gz -C /opt node10
```

Deploy to `/data/node10/` on the robot (~30-40MB).

### Effort estimate

| Task | Scope |
|------|-------|
| Build Node.js 10 for Pepper (Docker) | Small — same pattern as Python 3.5 |
| Strip vigiclient of Pi hardware deps | Medium — remove pigpio/i2c, keep socket.io + stream-split |
| Add NAOqi motor bridge | Medium — map vigibot servo channels to Pepper joints |
| Adapt video capture to Pepper cameras | Small — change v4l2 device path and ffmpeg flags |
| Adapt telemetry | Small — battery from ALBattery, temp from sysfs |
| Testing on robot | Medium — end-to-end with vigibot.com |

---

## Future Possibilities

- **TypeScript types**: Generate `.d.ts` from metaobject introspection (method signatures are in the metaobject)
- **REPL**: Interactive Node.js shell with tab-completion from metaobject methods
- **Web dashboard**: Since we're already in JS, build a browser UI on top of the same session logic
- **Multiple robots**: Connect to both pepper and memmer simultaneously from one Node.js process
- **Vigibot integration**: Stream Pepper's cameras and control its joints via vigibot.com (see vigiclient section above)

---

## References

- [qimessaging.js v2 source](https://github.com/aldebaran/libqi-js/blob/master/libs/qi/2/qi.js) — official browser SDK, Socket.IO 0.9.11
- [node-naoqi](https://github.com/yorkie/node-naoqi) — abandoned Node.js attempt, useful for API shape reference
- [NAOqi JS SDK docs](http://doc.aldebaran.com/2-5/dev/js/index.html) — official Aldebaran documentation
- [qipy PLAN.md](../qipy/PLAN.md) — companion project for on-robot Python 3 bindings
- [Broadway.js](https://github.com/nicyrv/Broadway) — pure JS H.264 decoder for browser-side video playback
- [vigiclient](https://github.com/vigibot/vigiclient) — Raspberry Pi robot client for vigibot.com, NAL-over-Socket.IO architecture
- [qimessaging-json source](/opt/aldebaran/bin/qimessaging-json) — robot's built-in Socket.IO ↔ NAOqi bridge (Python 2/Tornado)
