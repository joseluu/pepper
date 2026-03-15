# vigiclient.py - Technical Reference

## Why Python instead of Node.js

The original Node.js vigiclient connected to NAOqi through the qimessaging-json bridge (Socket.IO 0.9 over nginx on port 80). This bridge had fatal limitations:

1. **Arrays silently dropped**: `setAngles(['HeadYaw'], [0.5], 0.3)` — the bridge serialized array arguments incorrectly, causing NAOqi to receive no data
2. **wakeUp non-persistent**: the robot would immediately go back to rest after `wakeUp()` via the bridge
3. **Camera device locked**: naoqi-service holds `/dev/video-top` and `/dev/video-bottom` exclusively via V4L2. Direct ffmpeg access to `/dev/video-*` fails with "Device or resource busy"
4. **No workaround**: these are bridge-level bugs, not fixable from the client side

The Python rewrite connects directly to NAOqi via `qi.Session('tcp://127.0.0.1:9559')`, bypassing the bridge entirely. Video uses `ALVideoDevice.getImageRemote()` to grab frames from the camera API and pipe raw YUYV422 to ffmpeg stdin.

## Architecture

### Components

1. **Socket.IO 2.x / Engine.IO 3** — Manual implementation on `websocket-client` 0.59.0
   - Handshake EIO=3 via WebSocket (no polling fallback)
   - Ping/pong keepalive
   - JSON events and binary events (placeholders + attachments)
   - `\x04` prefix on outgoing binary frames (EIO message type)
   - `\x04` prefix stripped on incoming binary frames

2. **Binary frame protocol** (ported from `trame.js`)
   - `TxFrame`: command frames (server -> robot)
   - `RxFrame`: response frames (robot -> server)
   - Layout: `[sync][cmd32][val32][cmd16][val16][cam][cmd8][cmd1][val8]`
   - Little-endian, packed via `struct.pack_into` / `struct.unpack_from`

3. **NAOqi direct** via `qi.Session('tcp://127.0.0.1:9559')`
   - `ALMotion`: wakeUp, setAngles, setStiffnesses, robotIsWakeUp
   - `ALBattery`: getBatteryCharge
   - `ALTextToSpeech`: say
   - `ALRobotPosture`: goToPosture (for rest recovery)
   - `ALVideoDevice`: subscribeCamera, getImageRemote (video frame grabbing)
   - `ALAutonomousLife`: disabled at startup
   - `ALBackgroundMovement`: enabled (prevents 30s idle rest)
   - `ALAutonomousBlinking`: enabled (harmless eye LEDs)

4. **Servo ramping engine** — faithful port of the Node.js servo loop
   - RAMPUP / RAMPDOWN / RAMPINIT per command
   - Failsafe on latency alarm (thresholds LATENCYALARMBEGIN/END)
   - Tick at SERVORATE (50ms)

5. **Video pipeline** — ALVideoDevice -> ffmpeg -> TCP -> NALU splitter
   - Frame grabber thread: `getImageRemote()` loop, writes raw YUYV422 to ffmpeg stdin
   - ffmpeg encodes to H.264 baseline, outputs to TCP port 9998
   - TCP server receives H.264 stream, splits by NALU separator `\x00\x00\x00\x01`
   - Each NALU sent as Socket.IO binary event `serveurrobotvideo`

### Head mapping

| COMMANDS16 | Joint      | Conversion                     |
|------------|------------|--------------------------------|
| [0] Turret X | HeadYaw  | degrees -> radians (inverted) |
| [1] Turret Y | HeadPitch | degrees -> radians (inverted) |

Speed: 0.3 (HEAD_SPEED constant)

### NAOqi idle rest prevention

NAOqi has a hardcoded 30-second idle rest timer that cannot be configured or disabled. Investigation found:
- `setStiffnesses('Body', 1.0)` does NOT reset the timer
- `setAngles()` does NOT reset the timer
- `wakeUp()` while already awake does NOT reset the timer
- `moveToward(0, 0, 0)` does NOT reset the timer
- `setSmartStiffnessEnabled(False)` does NOT prevent rest
- `setIdlePostureEnabled('Body', False)` does NOT prevent rest

**Solution**: Enable `ALBackgroundMovement` — its subtle idle movements reset the timer.
Reference: http://doc.aldebaran.com/2-4/ref/life/autonomous_abilities_management.html

Additionally, a `robotIsWakeUp` event subscription provides fast recovery if rest occurs despite ALBackgroundMovement.

### Timers

| Timer     | Interval | Function                        |
|-----------|----------|---------------------------------|
| servo     | 50ms     | Ramping + apply motor commands  |
| beacon    | 1000ms   | Send RX when idle               |
| cpu       | 2000ms   | Read /proc/stat                 |
| temp      | 5000ms   | Read thermal_zone0              |
| wifi      | 5000ms   | Read /proc/net/wireless         |
| battery   | 5000ms   | getBatteryCharge via NAOqi      |
| keepalive | 5s       | Refresh body stiffness + finger wiggle |

### Telemetry

| VALUE | Source | Description |
|-------|--------|-------------|
| voltage (VALUES16[0]) | `3.0 + 1.2 * charge% / 100` | Simulated single LiIon cell (3.0–4.2V) |
| battery (VALUES16[1]) | `ALBattery.getBatteryCharge()` | Charge percentage (0–100) |
| cpu (VALUES8[0]) | `/proc/stat` delta | CPU load percentage |
| temp (VALUES8[1]) | `/sys/class/thermal/thermal_zone0/temp` | SoC temperature (°C) |
| link (VALUES8[2]) | `/proc/net/wireless` | WiFi link quality |
| rssi (VALUES8[3]) | `/proc/net/wireless` | WiFi signal level (dBm) |

### Finger animation

The keepalive timer (every 5s) alternates both hands (LHand, RHand) between open (0.8) and closed (0.2) positions. This provides visible activity and, together with ALBackgroundMovement, prevents the NAOqi 30s idle rest timer.

### Eye LED animation

While video is streaming, a rotating animation runs on the FaceLeds (8 LEDs per eye). One LED pair is lit at full intensity while the rest are dimmed to 0.1, rotating every 150ms. The animation stops and LEDs restore to full when video stops.

## Dependencies

- `websocket-client` 0.59.0 (installed in `/data/vigiclient/lib`)
- `six` (dependency of websocket-client)
- NAOqi SDK (`/opt/aldebaran/lib/python2.7/site-packages`)

## Key implementation notes

- Python 2.7 with minimal 2.7-specific code (compatible path to Python 3)
- `python2 -u` flag required (stdout fully buffered without TTY in Python 2)
- Engine.IO 3 binary frames need `\x04` prefix when sending, strip when receiving
- `boucleVideoCommande=0` from server means nobody controls; default to current time to avoid false latency alarm
- `wakeUp()` throws "WakeUp not started" when robot is stuck in rest; recovery requires `setStiffnesses('Body', 1.0)` + `goToPosture('Stand')` before `wakeUp()`
- ALVideoDevice subscribers must be cleared before subscribing (stale subscribers block camera)
- `stop_diffusion()` pkill must be synchronous (`subprocess.call`) to avoid race with newly started ffmpeg
