# vigiclient-pepper

Pepper robot client for [Vigibot.com](https://www.vigibot.com) - allows remote control of Pepper via the Vigibot web interface.

## Overview

This is an adapted version of [vigiclient](https://github.com/vigibot/vigiclient) for the Pepper robot. It replaces the Raspberry Pi-specific hardware dependencies (GPIO, I2C, PCA9685, etc.) with NAOqi service calls for motor control.

### What it does

- Connects to vigibot.com via Socket.IO 2.3.0
- Connects to the on-robot NAOqi bridge via Socket.IO 0.9.16 (legacy protocol)
- Streams H.264 video from Pepper's top camera via ffmpeg
- Sends telemetry (battery, CPU temp, WiFi signal) to the server
- Receives motor commands and applies them via NAOqi ALMotion
- Supports text-to-speech via NAOqi ALTextToSpeech

### Dual Socket.IO Architecture

The client uses two different Socket.IO versions simultaneously:

| Connection | Library | Version | Protocol |
|-----------|---------|---------|----------|
| vigibot.com | `socket.io-client` | 2.3.0 | Socket.IO 2.x (modern) |
| NAOqi bridge | `socket.io-client-legacy` | 0.9.16 | Socket.IO 0.9 (legacy) |

The NAOqi bridge (`qimessaging-json`) on the robot speaks Socket.IO 0.9.11 (Tornado/tornadio2), requiring the legacy client. The vigibot.com server uses Socket.IO 2.x.

### Prerequisites

- Pepper robot running NAOqiOS 2.7.x
- Node.js 10 installed on the robot at `/data/node10/`
- Robot connected to WiFi with internet access
- vigibot.com account with a robot configured

## Installation

### 1. Deploy Node.js 10

Use the `node10_pepper.tar.gz` release package:

```bash
scp node10_pepper.tar.gz nao@<robot-ip>:/data/
ssh nao@<robot-ip> "cd /data && tar xzf node10_pepper.tar.gz && rm node10_pepper.tar.gz"
```

Verify: `ssh nao@<robot-ip> "/data/node10/bin/node --version"` should show `v10.24.1`.

### 2. Deploy vigiclient

Use the `vigiclient_pepper_with_deps.tar.gz` release package (includes node_modules):

```bash
scp vigiclient_pepper_with_deps.tar.gz nao@<robot-ip>:/data/
ssh nao@<robot-ip> "cd /data && tar xzf vigiclient_pepper_with_deps.tar.gz && rm vigiclient_pepper_with_deps.tar.gz"
```

This creates `/data/vigiclient/` with all dependencies included.

### 3. Configure credentials

Copy the example and edit with your vigibot.com credentials:

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

The `SERVERS`, `CMDDIFFUSION`, `CMDDIFFAUDIO`, and `CMDTTS` fields in `robot.json` override the defaults in `sys.json`. If omitted, the defaults from `sys.json` are used.

### 4. Start the client

```bash
ssh nao@<robot-ip>
PATH=/data/node10/bin:$PATH
cd /data/vigiclient
node clientrobotpi.js
```

To run in background:

```bash
ssh nao@<robot-ip> "cd /data/vigiclient && PATH=/data/node10/bin:\$PATH nohup node clientrobotpi.js > /dev/null 2>&1 &"
```

### 5. Check the log

```bash
ssh nao@<robot-ip> "cat /home/nao/vigiclient.log"
```

A successful startup looks like:

```
Pepper client start
Client ready
Connecting to NAOqi bridge at http://127.0.0.1:80 with resource libs/qimessaging/1.0/socket.io
Connected to NAOqi bridge
Connected to https://www.vigibot.com/8042
Login sent to https://www.vigibot.com
Receiving robot configuration data from the https://www.vigibot.com server
ALMotion service acquired (pyobject=0)
Robot woken up
ALBattery service acquired (pyobject=1)
ALTextToSpeech service acquired (pyobject=2)
NAOqi connected successfully
```

## Configuration

### robot.json (user credentials — on robot at /home/nao/robot.json)

| Field | Description |
|-------|-------------|
| NAME | Your vigibot.com robot name |
| PASSWORD | Your vigibot.com password |
| SERVERS | (optional) Override server URLs |
| CMDDIFFUSION | (optional) Override ffmpeg video command |

### sys.json (system config — at /data/vigiclient/sys.json)

| Field | Default | Description |
|-------|---------|-------------|
| SECUREMOTEPORT | 8042 | Vigibot.com Socket.IO port |
| NAOQIBRIDGE | 127.0.0.1 | NAOqi bridge host |
| NAOQIBRIDGEPORT | 80 | NAOqi bridge port (nginx) |
| NAOQIPATH | libs/qimessaging/1.0/socket.io | Socket.IO resource path |
| VIDEOLOCALPORT | 9998 | Local TCP port for H.264 stream |
| LOGFILE | /home/nao/vigiclient.log | Log file path |

## Architecture

```
                     vigibot.com
                         ^
                         | Socket.IO 2.3.0
                         |
               +--------------------+
               |  vigiclient-pepper |
               |  (Node.js 10)      |
               +--------+-----------+
                         |
          NAL stream     |  Socket.IO 0.9.16
          (TCP pipe)     |
                         v
            nginx (port 80) -> qimessaging-json (port 8002)
                         |
                         v
                    NAOqi (port 9559)
                         |
                    ALMotion / ALBattery / ALTextToSpeech
```

## Files

| File | Description |
|------|-------------|
| clientrobotpi.js | Main application |
| trame.js | Telemetry frame handling |
| sys.json | System configuration |
| robot.json.example | Template for robot credentials |
| package.json | Node.js dependencies |

## Troubleshooting

### Client won't start

- Check that Node.js is installed: `/data/node10/bin/node --version`
- Verify `/home/nao/robot.json` exists and has valid JSON
- Check the log file: `cat /home/nao/vigiclient.log`

### Not visible on vigibot.com

- Check that the robot has internet access: `ping -c 1 www.vigibot.com`
- Verify credentials in `/home/nao/robot.json` match your vigibot.com account
- Check the log for "Connected to https://www.vigibot.com/8042" and "Login sent"

### wakeUp timeout

- wakeUp can take 15-30 seconds when the robot was in rest mode — this is normal
- The timeout is set to 30 seconds; if it fails, the init continues but motor commands won't work

### Can't connect to NAOqi

- The qimessaging-json bridge starts automatically with NAOqiOS
- Verify it's running: `curl -s http://127.0.0.1:80/libs/qimessaging/1.0/socket.io/1/`
- The bridge must be accessed through nginx (port 80), not directly (port 8002)

### No video stream

- Verify ffmpeg is installed: `which ffmpeg`
- Check camera device: `ls -la /dev/video-*`

## Dependencies Removed (vs original vigiclient)

- pigpio - Raspberry Pi GPIO (not applicable to Pepper)
- i2c-bus - I2C communication (Pepper uses NAOqi)
- pca9685 - PWM servo driver (Pepper has built-in motors)
- ina219 - Current sensor (Pepper has ALBattery)
- serialport - Serial communication (not used)
- gps - GPS parsing (not available on Pepper)

## License

ISC (same as original vigiclient)
