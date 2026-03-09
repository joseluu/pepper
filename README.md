# Pepper Robot — Projects & Explorations

Work on two SoftBank Pepper robots (NAOqiOS 3.3.10.1, NAOqi 2.7.1.128, i686 32-bit).

## Repository structure

```
├── architecture/           System architecture docs and diagrams
├── qipy/                   Pure Python 3 QiMessaging bindings (planned)
├── qinode/                 Node.js NAOqi client (planned)
├── qipy_with_bridge/       Python 3.5 on Pepper via Python 2 bridge (working)
└── CLAUDE.md               Robot connection & system reference
```

## Projects

### Python 3.5 on Pepper (`qipy_with_bridge/`)

**Status: working, deployed**

Pepper ships only Python 2.7. The native Python 3 bindings (`libqipython3.so`) are broken — the matching `libpython3.5m.so` was never deployed, causing an ABI mismatch that crashes in `export_all()`.

Solution: Python 3.5.10 cross-compiled in Docker (`i386/ubuntu:16.04`) to match Pepper's glibc 2.23, plus a Python 2 bridge server that proxies NAOqi services over a Unix socket to Python 3 clients.

- Deploy package available as a [GitHub Release](https://github.com/joseluu/pepper/releases)
- See [PYTHON35_INSTALL_USAGE.md](qipy_with_bridge/PYTHON35_INSTALL_USAGE.md) for installation and usage
- See [PYTHON35_TECH.md](qipy_with_bridge/PYTHON35_TECH.md) for technical details

### Pure Python 3 QiMessaging bindings (`qipy/`)

**Status: planned**

Replace the Python 2 bridge with a pure Python 3 implementation of the QiMessaging binary protocol (TCP port 9559). No C extensions, no Python 2 dependency, works with any Python 3.5+.

The protocol is fully documented: 36-byte header (magic `0x42dead42`), binary serialization, capability-based auth, service directory, MetaObject introspection.

See [qipy/PLAN.md](qipy/PLAN.md) for the implementation plan.

### Node.js NAOqi client (`qinode/`)

**Status: planned**

Control Pepper from Node.js on a PC, using the robot's built-in Socket.IO bridge (`qimessaging-json`, Tornado/Python 2, port 8002). Verified that `socket.io-client@0.9.16` works on Node.js 18.

The plan also covers:
- **H.264 video streaming** to browsers via Broadway.js — ffmpeg encodes from V4L2 cameras, a Tornado WebSocket server splits NAL units, Broadway.js decodes in-browser on a `<canvas>`
- **Adapting [vigiclient](https://github.com/vigibot/vigiclient)** to run on Pepper — streaming video to vigibot.com and controlling joints via NAOqi

See [qinode/PLAN.md](qinode/PLAN.md) for the implementation plan.

### Architecture (`architecture/`)

System architecture documentation with Mermaid diagrams covering:
- Full software stack (kernel, NAOqi, bridges, media tools)
- Communication protocols (binary QiMessaging, Socket.IO bridge, nginx proxy)
- Video pipeline (existing poll model, planned H.264 streaming)
- NAOqi service map
- Network ports and filesystem layout

See [architecture/PEPPER.md](architecture/PEPPER.md) or the [rendered PDF](architecture/PEPPER.pdf).

## Robots

| Robot  | WiFi IP         | Ethernet IP      | Notes |
|--------|-----------------|------------------|-------|
| pepper | 192.168.11.182  | 192.168.11.183   |       |
| memmer | 192.168.11.185  | 192.168.11.190   | Python 3.5 deployed |

Both run NAOqiOS 3.3.10.1 (kernel 4.0.4-rt1, glibc 2.23, Intel Atom i686).

## Key findings

- Pepper's `libqipython3.so` is ABI-entangled with a never-shipped Yocto-built `libpython3.5m.so` — native Python 3 bindings cannot work without the original library
- The robot has ffmpeg 3.0, libx264, GStreamer 0.10+1.0, and VA-API hardware H.264 encoding (`i965_drv_video.so`) — all the pieces for video streaming, but no built-in streaming endpoint
- `qimessaging-json` (the Socket.IO bridge) creates a fresh `qi.Session()` per client connection — the full source is a concise 154-line Python 2 script
- The QiMessaging binary protocol is fully documented and has an existing Go implementation ([qiloop](https://github.com/lugu/qiloop))
- No Node.js runtime on the robot, but Node.js 10 can be cross-compiled the same way as Python 3.5
