# Pepper Robots — Connection & System Reference

Both robots are the same model, same OS (NAOqiOS 3.3.10.1, NAOqi 2.7.1.128).

## SSH Access

SSH key auth is configured — no password needed for normal use.
Use `ssh memmer`, `ssh pepper`, `ssh vigibot` directly (aliases configured in ~/.ssh/config).

| Robot     | SSH alias        | WiFi IP          | Ethernet IP      |
|-----------|------------------|------------------|------------------|
| pepper    | `ssh pepper`     | 192.168.11.182   | 192.168.11.183   |
| memmer    | `ssh memmer`   | 192.168.11.185   | 192.168.11.190   |
| vigibot   | `ssh vigibot`    | —                | —                |

- User: `nao` — key: `~/.ssh/nao`
- Wired aliases: `ssh pepper_wired`, `ssh memmer_wired`
- `sudo` available, unrestricted
- Root SSH blocked (`PermitRootLogin no`), `su` blocked (root shell is `/sbin/nologin`)
- `vigibot` is a reference vigibot robot (Raspberry Pi) that connects properly to vigibot.com

### Non-interactive SSH (for scripts without key agent)

```bash
# Create password helper script once
echo '#!/bin/sh\necho "nao"' > /tmp/pass.sh && chmod +x /tmp/pass.sh

# Use it for SSH/SCP commands
SSH_ASKPASS=/tmp/pass.sh SSH_ASKPASS_REQUIRE=force ssh -o StrictHostKeyChecking=no nao@<ip> "<command>" < /dev/null
SSH_ASKPASS=/tmp/pass.sh SSH_ASKPASS_REQUIRE=force scp -o StrictHostKeyChecking=no nao@<ip>:/remote/path /local/path < /dev/null
```

## Root Access Status

- `PermitRootLogin no` in `/etc/ssh/sshd_config` — direct root SSH blocked
- root shell is `/sbin/nologin` — `su` is blocked even with correct password (`root`)
- `sudo` for nao is not restricted
- naoqi processes run as user `nao` (uid 1001), not root

## System Info (both robots identical)

| Field           | Value                                      |
|----------------|--------------------------------------------|
| OS             | NAOqiOS 3.3.10.1 / Juliette 2.7.1.128     |
| Codename       | Etivaz                                     |
| Build date     | 2017-12-05                                 |
| Kernel         | 4.0.4-rt1-aldebaran (i686, PREEMPT RT)     |
| Toolchain      | Yocto SDK 3.3.10.1                         |
| glibc          | 2.23                                       |
| Python         | Python 2.7.11 (system), 3.5.10 on memmer   |
| NAOqi version  | 2.7.1.128                                  |
| Architecture   | i686 (32-bit x86)                          |

### Storage

- Root `/` — 1.5 GB, typically 93% full (~107 MB free). Do not install here.
- `/data` — 25 GB, plenty of space. Install everything here.

## SDK & Python Environment

```bash
# qi / naoqi Python SDK path (must set manually)
PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages

# Connect to NAOqi session
PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages python2 -c "
import qi
session = qi.Session()
session.connect('tcp://127.0.0.1:9559')
# session.service('ALServiceName')
"
```

Available modules in `/opt/aldebaran/lib/python2.7/site-packages/`:
- `qi` — main SDK
- `naoqi` — legacy ALProxy style
- `almath`, `allog`, etc.

## Key NAOqi Services

| Service               | Description                        |
|----------------------|------------------------------------|
| `ALTextToSpeech`     | Speech synthesis                   |
| `ALMotion`           | Joint/body control                 |
| `ALVideoDevice`      | Camera access                      |
| `ALConnectionManager`| WiFi/network management            |
| `ALSystem`           | System info, reboot, password      |
| `ALPhotoCapture`     | Photo capture                      |
| `ALRobotPosture`     | Posture presets (Stand, Sit, etc.) |
| `ALAutonomousLife`   | Autonomous behavior control        |

## WiFi

Both robots connect to **freeboite2** (PSK, DHCP). WiFi service ID (pepper): `wifi_48a9d2a8ed0c_66726565626f69746532_managed_psk`

### Connect to WiFi (no root needed)

```python
import qi, time, threading

session = qi.Session()
session.connect('tcp://127.0.0.1:9559')
cm = session.service('ALConnectionManager')

service_id = 'wifi_48a9d2a8ed0c_66726565626f69746532_managed_psk'

def do_connect():
    cm.connect(service_id)

t = threading.Thread(target=do_connect)
t.start()
time.sleep(2)
cm.setServiceInput({'ServiceId': service_id, 'Passphrase': '123456789a'})
t.join(timeout=15)
```

## Camera Capture

```python
import qi, time
from PIL import Image

session = qi.Session()
session.connect('tcp://127.0.0.1:9559')
video = session.service('ALVideoDevice')

# Camera 0=top, 1=bottom, 2=depth | Resolution 2=VGA(640x480) | Colorspace 11=RGB
sub = video.subscribeCamera('capture', 0, 2, 11, 5)
time.sleep(1)
img = video.getImageRemote(sub)
video.unsubscribe(sub)

w, h, data = img[0], img[1], img[6]
pil = Image.frombytes('RGB', (w, h), bytes(bytearray(data)))
pil.save('/home/nao/capture.png')
```

## TTS / Speech

```python
session.service('ALTextToSpeech').say('Hello')
# Installed languages: English, Chinese (French NOT installed)
```

## Motion — Raise Right Arm

```python
motion = session.service('ALMotion')
motion.wakeUp()
# RShoulderPitch: -1.5=up, +1.5=down | speed: 0.0-1.0
motion.setAngles(['RShoulderPitch', 'RShoulderRoll', 'RElbowRoll'], [-1.5, -0.1, 0.1], 0.2)
```

## Python 3.5 (memmer only, for now)

Deployed to `/data/python3.5/`. Uses a Python 2 bridge for NAOqi access.
See `PYTHON35_INSTALL_USAGE.md` for full details.

```bash
# Run a script with NAOqi access
ssh memmer /data/python3.5/bin/python3-qi my_script.py

# Inside the script
from qi_bridge_client import QiSession
s = QiSession()
s.connect()
s.service('ALTextToSpeech').say('Hello')
s.close()
```

Deploy package: `python35_pepper_deploy.tar.gz` (45 MB, works on any Pepper 2.7.x).

## Web Interface

| Robot  | Main UI                       | Advanced UI                          |
|--------|-------------------------------|--------------------------------------|
| pepper | `http://192.168.11.182/`      | `http://192.168.11.182/advanced/`    |
| memmer | `http://192.168.11.185/`      | `http://192.168.11.185/advanced/`    |

AngularJS app, nginx 1.8.1.
