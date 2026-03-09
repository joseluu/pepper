# Python 3.5 for Pepper — Installation & Usage

## Requirements

- Pepper robot running NAOqi 2.7.x (NAOqiOS 3.3.10.1)
- SSH access to the robot (`nao` user)
- The deployment package `python35_pepper_deploy.tar.gz` (45 MB)

## Installation

### 1. Copy the package to the robot

```bash
scp python35_pepper_deploy.tar.gz nao@<robot_ip>:/home/nao/
```

### 2. Extract to /data

```bash
ssh nao@<robot_ip>
sudo tar xzf /home/nao/python35_pepper_deploy.tar.gz -C /data/
rm /home/nao/python35_pepper_deploy.tar.gz
```

### 3. Verify

```bash
LD_LIBRARY_PATH=/data/python3.5/lib /data/python3.5/bin/python3.5 --version
# Python 3.5.10
```

### 4. Test NAOqi access

```bash
/data/python3.5/bin/python3-qi -c '
from qi_bridge_client import QiSession
s = QiSession()
s.connect()
print(s.service("ALSystem").systemVersion())
s.close()
'
```

## Uninstall

```bash
ssh nao@<robot_ip>
sudo rm -rf /data/python3.5
rm -f /tmp/qi_bridge.sock /tmp/qi_bridge.pid /tmp/qi_bridge.log
kill $(cat /tmp/qi_bridge.pid 2>/dev/null) 2>/dev/null
```

---

## Usage

### Running a script

```bash
# With NAOqi access (starts the bridge automatically)
/data/python3.5/bin/python3-qi my_script.py

# Without NAOqi (plain Python 3.5, no bridge)
LD_LIBRARY_PATH=/data/python3.5/lib /data/python3.5/bin/python3.5 my_script.py
```

### pip

```bash
LD_LIBRARY_PATH=/data/python3.5/lib /data/python3.5/bin/pip3.5 install <package>
```

Install to `/data` to avoid filling the root filesystem:

```bash
LD_LIBRARY_PATH=/data/python3.5/lib /data/python3.5/bin/pip3.5 install --prefix=/data/python3.5 <package>
```

### Interactive shell

```bash
/data/python3.5/bin/python3-qi
```

---

## Differences with Python 2

### Connecting to NAOqi

**Python 2** — direct import, single process:

```python
import qi

session = qi.Session()
session.connect('tcp://127.0.0.1:9559')
tts = session.service('ALTextToSpeech')
tts.say('Hello')
```

**Python 3** — through the bridge client:

```python
from qi_bridge_client import QiSession

s = QiSession()
s.connect('tcp://127.0.0.1:9559')
tts = s.service('ALTextToSpeech')
tts.say('Hello')
s.close()
```

Key differences:

| | Python 2 | Python 3 |
|---|---|---|
| Import | `import qi` | `from qi_bridge_client import QiSession` |
| Session | `qi.Session()` | `QiSession()` |
| Cleanup | not required | `s.close()` or use `with` |
| Runs as | single process | two processes (bridge + your script) |
| Return values | native qi types | JSON-serialized (str, int, float, list, dict, None) |

### Context manager

Python 3 sessions support `with` for automatic cleanup:

```python
from qi_bridge_client import QiSession

with QiSession() as s:
    s.connect()
    s.service('ALTextToSpeech').say('Hello')
# bridge connection closed automatically
```

### Calling service methods

Methods are called the same way as Python 2:

```python
tts = s.service('ALTextToSpeech')
tts.say('Hello')

motion = s.service('ALMotion')
motion.wakeUp()
motion.setAngles(['HeadYaw'], [0.5], 0.2)
```

You can also use the explicit `.call()` form:

```python
tts.call('say', 'Hello')
```

### Return values

Bridge serializes all return values to JSON. This means:

```python
# Works — simple types pass through
battery = s.service('ALBattery').getBatteryCharge()  # int
name = s.service('ALSystem').robotName()             # str

# Works — lists and dicts are preserved
joints = s.service('ALMotion').getJointNames('Body')  # list of str

# Limitation — raw binary data (images, audio) is converted to string
# Use ALPhotoCapture.takePicture() to save to a file path instead
```

### Starting programs on the robot

**Python 2** — just run:
```bash
python2 my_script.py
```

**Python 3** — use the `python3-qi` wrapper to auto-start the bridge:
```bash
/data/python3.5/bin/python3-qi my_script.py
```

If you don't need NAOqi services, use Python directly:
```bash
LD_LIBRARY_PATH=/data/python3.5/lib /data/python3.5/bin/python3.5 my_script.py
```

### Background scripts / cron

When running Python 3 from cron or nohup, start the bridge first:

```bash
/data/python3.5/bin/start_qi_bridge.sh
LD_LIBRARY_PATH=/data/python3.5/lib /data/python3.5/bin/python3.5 my_daemon.py &
```

### Stopping the bridge

The bridge stays running across script invocations (one bridge serves many scripts). Stop it manually:

```bash
kill $(cat /tmp/qi_bridge.pid)
rm -f /tmp/qi_bridge.sock
```

---

## Troubleshooting

**`FileNotFoundError: /tmp/qi_bridge.sock`**
Bridge server is not running. Start it:
```bash
/data/python3.5/bin/start_qi_bridge.sh
```

**`ImportError: dynamic module does not define init function (init_qi)`**
There is a stray `_qi.so` file in the current directory. Python 2 finds it instead of the real one. Remove it:
```bash
rm -f /home/nao/_qi.so
rm -f ./_qi.so
```

**`error while loading shared libraries: libpython3.5m.so.1.0`**
Missing `LD_LIBRARY_PATH`. Use:
```bash
LD_LIBRARY_PATH=/data/python3.5/lib /data/python3.5/bin/python3.5
```
Or use the `python3-qi` wrapper which sets it automatically.

**Bridge server log**
```bash
cat /tmp/qi_bridge.log
```

---

## File layout

```
/data/python3.5/
├── bin/
│   ├── python3.5              # Python 3.5.10 interpreter
│   ├── python3-qi             # wrapper: starts bridge, sets env, runs python3
│   ├── qi_bridge_server.py    # Python 2 process proxying NAOqi over Unix socket
│   ├── start_qi_bridge.sh     # starts bridge if not already running
│   └── pip3.5                 # package manager
├── lib/
│   ├── libpython3.5m.so.1.0  # Python shared library
│   └── python3.5/
│       └── site-packages/
│           └── qi_bridge_client.py  # import this in your Python 3 scripts
└── include/python3.5m/        # C headers for building extensions

/tmp/qi_bridge.sock            # Unix socket (created at runtime)
/tmp/qi_bridge.pid             # bridge server PID file
/tmp/qi_bridge.log             # bridge server log
```
