# vigiclient-pepper

Pepper robot client for [Vigibot.com](https://www.vigibot.com) - allows remote control of Pepper via the Vigibot web interface.

## Overview

This is an adapted version of [vigiclient](https://github.com/vigibot/vigiclient) for the Pepper robot. It replaces the Raspberry Pi-specific hardware dependencies (GPIO, I2C, PCA9685, etc.) with NAOqi service calls for motor control.

### What it does

- Connects to vigibot.com via Socket.IO
- Streams H.264 video from Pepper's top camera
- Sends telemetry (battery, CPU temp, WiFi signal) to the server
- Receives motor commands and applies them via NAOqi ALMotion
- Supports text-to-speech via NAOqi ALTextToSpeech

### Prerequisites

- Pepper robot running NAOqiOS
- Node.js 10+ installed on the robot (at `/data/node10/` or similar)
- Robot connected to WiFi
- vigibot.com account

## Installation

### 1. Install Node.js on Pepper (if not already installed)

See [qinode/PLAN.md](../PLAN.md) for building Node.js 10 for the i686 Pepper.

### 2. Transfer and install vigiclient

**Option A: With dependencies included (recommended - no npm needed)**
```bash
scp qinode/releases/vigiclient_pepper_with_deps.tar.gz pepper:/data/
ssh pepper "cd /data && tar xzf vigiclient_pepper_with_deps.tar.gz"
```

**Option B: Without dependencies (requires npm on robot)**
```bash
scp qinode/releases/vigiclient_pepper.tar.gz pepper:/data/
ssh pepper "cd /data && tar xzf vigiclient_pepper.tar.gz && cd vigiclient && /data/node10/bin/npm install --production"
```

### 3. Configure robot.json

Edit `/data/vigiclient/robot.json` with your vigibot.com credentials:

```json
{
  "LOGIN": "your_username",
  "PASSWORD": "your_password",
  "SERVERS": ["www.vigibot.com"]
}
```

### 4. Start the client

```bash
cd /data/vigiclient
node /data/node10/bin/node clientrobotpi.js
```

Or with the Node.js path in PATH:

```bash
export PATH=/data/node10/bin:$PATH
cd /data/vigiclient
node clientrobotpi.js
```

## Configuration

### robot.json

| Field | Description |
|-------|-------------|
| LOGIN | Your vigibot.com username |
| PASSWORD | Your vigibot.com password |
| SERVERS | Array of vigibot server URLs |

### sys.json

System configuration (usually doesn't need changes):

| Field | Description |
|-------|-------------|
| NAOQIBRIDGE | NAOqi bridge IP (default: 127.0.0.1) |
| NAOQIBRIDGEPORT | NAOqi bridge port (default: 8002) |
| VIDEOLOCALPORT | Local port for H.264 stream |
| CMDDIFFUSION | ffmpeg command for video capture |

## Motor Control Mapping

The client maps vigibot servo channels to Pepper joint angles. Configure this in the vigibot web interface:

| Vigibot Channel | Pepper Joint | Description |
|-----------------|--------------|-------------|
| 0 | HeadYaw | Head rotation (left-right) |
| 1 | HeadPitch | Head tilt (up-down) |
| 2 | LShoulderPitch | Left arm shoulder |
| 3 | RShoulderPitch | Right arm shoulder |
| ... | ... | Additional joints |

## Architecture

```
                     vigibot.com
                         ▲
                         │ Socket.IO 2.3
                         │
               ┌─────────┴──────────┐
               │  vigiclient-pepper │
               │  (Node.js)         │
               └─────────┬──────────┘
                         │
          NAL stream     │  motor commands
          (TCP pipe)     │
                         ▼
                    NAOqi bridge
                    (Socket.IO → port 8002)
                         │
                         ▼
                    ALMotion / ALTextToSpeech
                         │
                         ▼
                    NAOqi (port 9559)
```

## Files

| File | Description |
|------|-------------|
| clientrobotpi.js | Main application |
| trame.js | Telemetry frame handling |
| sys.json | System configuration |
| robot.json | Robot credentials (user-specific) |
| package.json | Node.js dependencies |

## Troubleshooting

### Client won't start

- Check that Node.js is installed: `node --version`
- Verify robot.json exists and has valid JSON
- Check the log file: `/data/vigiclient/vigiclient.log`

### No video stream

- Verify ffmpeg is installed: `which ffmpeg`
- Check camera device: `ls -la /dev/video-*`
- Try a different resolution in the vigibot configuration

### Can't connect to NAOqi

- Verify the qimessaging-json service is running on the robot
- Check the NAOqi bridge port (default 8002)

### Motor commands not working

- The robot must be "woken up" first - this happens automatically
- Check that ALMotion service is available

## Dependencies Removed (vs original vigiclient)

- pigpio - Raspberry Pi GPIO (not applicable to Pepper)
- i2c-bus - I2C communication (Pepper uses NAOqi)
- pca9685 - PWM servo driver (Pepper has built-in motors)
- ina219 - Current sensor (Pepper has ALBattery)
- serialport - Serial communication (not used)
- gps - GPS parsing (not available on Pepper)

## License

ISC (same as original vigiclient)
