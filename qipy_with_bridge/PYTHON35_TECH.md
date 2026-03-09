# Python 3.5 on Pepper — Technical Summary

## Build

Python 3.5.10 cross-compiled in Docker (`i386/ubuntu:16.04`) to match pepper's glibc 2.23 and i686 architecture.

```
Dockerfile:     Dockerfile.python35
Base image:     i386/ubuntu:16.04 (glibc 2.23 exact match)
Source:         Python-3.5.10 (last 3.5.x release)
Configure:      --enable-shared --enable-optimizations --with-ensurepip
Installed to:   /data/python3.5/ on pepper (25GB partition, avoids 93%-full root fs)
Size:           ~45MB
GLIBC max:      2.17 (pepper has 2.23)
```

Docker build & extract:
```bash
docker build -f Dockerfile.python35 -t python35_pepper .
docker run --rm -v $(pwd)/python35_out:/out python35_pepper
scp python35_out/python35_pepper.tar.gz pepper-2:/home/nao/
ssh pepper-2 "sudo tar xzf /home/nao/python35_pepper.tar.gz -C /data/"
```

## Why native qi bindings don't work

Pepper ships `libqipython3.so` and `libboost_python3.so.1.59.0` but the matching `libpython3.5m.so.1.0` was never deployed — it only existed in the Yocto SDK sysroot at build time.

All three libraries are ABI-entangled: `libqipython3.so` contains inline template instantiations compiled against the Yocto Python 3.5 headers. Our rebuilt Python 3.5.10 has a subtly different internal layout.

Crash chain:
```
PyInit__qi (our _qi.so)
  → BOOST_PYTHON_MODULE scope setup (works)
    → qi::py::export_all() in libqipython3.so
      → registers FutureState enum
        → boost::python::objects::enum_base::add_value()
          → Py_XDECREF on corrupted pointer (0x1) → SIGSEGV
```

Verified that the crash is NOT a general Boost.Python issue — a trivial module with `boost::python::enum_<>` works fine with our Python 3.5 + pepper's `libboost_python3.so`. The crash is specific to converter function pointers baked into `libqipython3.so` that assume the Yocto Python 3.5 struct layout.

Rebuilding `libboost_python3.so` alone does not fix it — `libqipython3.so` still has mismatched inline code.

## Bridge architecture

A Python 2 process acts as a proxy between Python 3 and NAOqi.

```
Python 3 app ──(Unix socket JSON)──▶ qi_bridge_server.py (Python 2) ──(qi C++)──▶ NAOqi
```

Protocol: newline-delimited JSON over `/tmp/qi_bridge.sock`.

Commands:
```json
{"cmd": "connect", "url": "tcp://127.0.0.1:9559"}
{"cmd": "service", "name": "ALTextToSpeech"}
{"cmd": "call", "service": "ALTextToSpeech", "method": "say", "args": ["Hello"]}
{"cmd": "quit"}
```

Responses:
```json
{"ok": true, "result": "2.7.1.128"}
{"error": "Not connected"}
```

## Deployed files on pepper-2

```
/data/python3.5/
├── bin/
│   ├── python3.5, python3.5m         # interpreter
│   ├── python3-qi                     # wrapper: starts bridge + sets env
│   ├── qi_bridge_server.py            # Python 2 NAOqi proxy
│   ├── start_qi_bridge.sh             # bridge lifecycle management
│   └── pip3.5                         # package manager
├── lib/
│   ├── libpython3.5m.so.1.0          # shared library
│   └── python3.5/
│       └── site-packages/
│           └── qi_bridge_client.py    # Python 3 client module
└── include/python3.5m/                # headers (for building C extensions)
```

## Usage

```bash
/data/python3.5/bin/python3-qi -c '
from qi_bridge_client import QiSession
s = QiSession()
s.connect()
s.service("ALTextToSpeech").say("Hello from Python 3")
print(s.service("ALSystem").systemVersion())
s.close()
'
```

## Known issues

- Do not leave any `_qi.so` in `/home/nao/` — Python 2's `imp.find_module` searches CWD first, which breaks the bridge server's `import qi`.
- Bridge adds ~2ms latency per call (Unix socket + JSON serialization).
- Return values are JSON-serialized; raw bytes and qi-specific objects are converted to strings.
- Bridge server must be running before Python 3 can access NAOqi (`python3-qi` wrapper handles this automatically).
