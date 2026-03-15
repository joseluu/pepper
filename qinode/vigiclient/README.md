# vigiclient-pepper

Python client for controlling a Pepper robot via [Vigibot.com](https://www.vigibot.com).

## Overview

Rewritten from the original Node.js [vigiclient](https://github.com/vigibot/vigiclient) to use direct NAOqi SDK access via `qi.Session()`, eliminating the qimessaging-json bridge which had fatal limitations (arrays silently ignored, wakeUp non-persistent).

### Features

- Head control (pan/tilt) via vigibot.com joystick
- H.264 video streaming from Pepper's camera via ALVideoDevice + ffmpeg
- Text-to-speech via ALTextToSpeech
- Telemetry: battery, CPU, temperature, WiFi signal
- Automatic wake/sleep on remote control take/release
- Robot stays awake via ALBackgroundMovement (prevents NAOqi 30s idle rest)

### Why Python instead of Node.js

The original Node.js version connected to NAOqi through the qimessaging-json bridge (Socket.IO 0.9 over nginx). This bridge had critical bugs:

- **Arrays silently ignored**: `setAngles(['HeadYaw'], [0.5], 0.3)` — array arguments were dropped
- **wakeUp non-persistent**: robot would go back to rest immediately
- **No binary frame support**: couldn't properly handle the vigibot binary protocol
- **Camera device locked**: naoqi-service holds `/dev/video-*` exclusively, preventing direct v4l2 access

The Python version connects directly to NAOqi via `qi.Session('tcp://127.0.0.1:9559')`, bypassing all bridge issues. Video uses ALVideoDevice API to grab frames and pipe them to ffmpeg.

## Installation

### Quick install

Download `vigiclient_pepper.tar.gz` from the [releases page](https://github.com/joseluu/pepper/releases), then:

```bash
# From a machine with SSH access to the robot
scp vigiclient_pepper.tar.gz nao@<robot-ip>:/tmp/
ssh nao@<robot-ip> "sudo mkdir -p /data/vigiclient && sudo chown nao:nao /data/vigiclient && cd /data && tar xzf /tmp/vigiclient_pepper.tar.gz && rm /tmp/vigiclient_pepper.tar.gz"
```

This creates `/data/vigiclient/` with all dependencies (websocket-client, six) included.

### Configure credentials

```bash
ssh nao@<robot-ip>
cp /data/vigiclient/robot.json.example /home/nao/robot.json
```

Edit `/home/nao/robot.json`:

```json
{
  "NAME": "your_robot_name",
  "PASSWORD": "your_password"
}
```

### Start

```bash
ssh nao@<robot-ip> "cd /data/vigiclient && PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages nohup python2 -u vigiclient.py > /tmp/vigiclient_stdout.log 2>&1 &"
```

### Check logs

```bash
ssh nao@<robot-ip> "tail -20 /tmp/vigiclient_stdout.log"
```

A successful startup shows:

```
Pepper vigiclient start (Python)
Connecting to NAOqi...
NAOqi session connected
ALMotion acquired
ALAutonomousLife disabled
ALBackgroundMovement enabled
ALAutonomousBlinking enabled
Robot is awake
Body stiffness set
Subscribed to robotIsWakeUp event
Connected to https://www.vigibot.com/8042
Login sent to https://www.vigibot.com
Receiving robot configuration
```

### Stop

```bash
ssh nao@<robot-ip> "pkill -f vigiclient.py"
```

## Architecture

```
                     vigibot.com
                         ^
                         | Socket.IO 2.x / Engine.IO 3
                         | (manual implementation on websocket-client)
                         |
               +--------------------+
               |  vigiclient.py     |
               |  (Python 2.7)      |
               +--------+-----------+
                         |
                  qi.Session()
                  tcp://127.0.0.1:9559
                         |
                         v
                    NAOqi (direct)
                         |
      +---------+-----------+-----------+------------------+
      |         |           |           |                  |
  ALMotion  ALBattery   ALTts    ALVideoDevice    ALBackgroundMovement
```

### Video pipeline

```
ALVideoDevice.getImageRemote() -> raw YUYV422 frames
         |
         v (pipe to stdin)
    ffmpeg -f rawvideo ... -c:v libx264 -f h264 tcp://127.0.0.1:9998
         |
         v (TCP connection)
    NALU splitter (split by 0x00000001)
         |
         v (Socket.IO binary events)
    serveurrobotvideo -> vigibot.com
```

## Files

| File | Description |
|------|-------------|
| vigiclient.py | Main application (Python 2.7) |
| sys.json | System configuration (rates, ports, thresholds) |
| robot.json.example | Template for robot credentials |

## Dependencies

- Python 2.7 (system, on Pepper)
- `websocket-client` 0.59.0 (bundled in `/data/vigiclient/lib/`)
- `six` (dependency of websocket-client, bundled)
- NAOqi SDK (`/opt/aldebaran/lib/python2.7/site-packages/`, on Pepper)
- ffmpeg (system, on Pepper)

## Configuration

### robot.json

| Field | Description |
|-------|-------------|
| NAME | Your vigibot.com robot name |
| PASSWORD | Your vigibot.com password |

### sys.json

| Field | Default | Description |
|-------|---------|-------------|
| SECUREMOTEPORT | 8042 | Vigibot.com Socket.IO port |
| VIDEOLOCALPORT | 9998 | Local TCP port for H.264 stream |
| SERVORATE | 50 | Servo loop interval (ms) |
| LATENCYALARMBEGIN | 300 | Latency threshold to trigger failsafe (ms) |
| LATENCYALARMEND | 200 | Latency threshold to resume (ms) |
| UPTIMEOUT | 5000 | Idle timeout before sleep (ms) |

## Troubleshooting

### Robot goes to rest after 30 seconds

ALBackgroundMovement must be enabled. The vigiclient enables it automatically at startup. If it was manually disabled, the NAOqi 30-second idle rest timer will put the robot to rest.

### Camera subscription fails (empty string)

Too many leftover ALVideoDevice subscribers. The vigiclient clears all existing subscribers before subscribing. If the problem persists, reboot the robot.

### No video on vigibot.com

Check that ffmpeg is running: `ps aux | grep ffmpeg`. Check logs for "NALU" messages indicating H.264 data is being sent.

### wakeUp fails with "WakeUp not started"

The robot is stuck in rest state. The vigiclient subscribes to the `robotIsWakeUp` event and automatically recovers using `goToPosture('Stand')` + `wakeUp()`.

## License

ISC (same as original vigiclient)
