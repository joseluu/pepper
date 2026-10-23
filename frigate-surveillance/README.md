# Pepper as a Frigate Surveillance Camera

Turn a SoftBank **Pepper** robot into a network surveillance camera for
[Frigate](https://frigate.video/), including **PTZ control** (the operator aims
the robot's head from the Frigate UI, and Frigate's autotracking can drive it).

Both of Pepper's usable cameras are exposed as standard **RTSP/MJPEG** streams,
and the head can be moved over **ONVIF PTZ** — all served from the robot itself,
with no extra hardware.

> **Current setup (2026-10-23): only the bottom camera is streamed.** The `head`
> stream is commented out in `go2rtc/go2rtc.yaml` and `frigate/cameras.yml`, and
> the ONVIF PTZ bridge is not installed: the head is driven by the Halloween
> ghost and its dialogue (`../halloween/`). Uncomment both and reinstall
> `onvif-ptz.service` (as a user service, see step 3) to get them back.

---

## Features

- **Two RTSP streams** served by [go2rtc](https://github.com/AlexxIT/go2rtc) on the robot:
  - `rtsp://<robot>:8554/bottom` — bottom (mouth) camera, direct V4L2 capture
  - `rtsp://<robot>:8554/head` — head (forehead) camera, bridged through NAOqi
- **ONVIF PTZ** on port `8000` — pan/tilt the head from Frigate's live view (arrows,
  keyboard, drag, presets) and optional autotracking.
- Runs as two **systemd services**, started automatically on boot.
- Designed for Pepper's **weak 32-bit Atom CPU**: MJPEG-only, minimal robot load.

---

## Architecture

```
   ROBOT (Pepper, 192.168.11.182)                         FRIGATE HOST (+ GPU)
 ┌───────────────────────────────────────────┐         ┌──────────────────────┐
 │  bottom cam  /dev/video2 ──┐ (free V4L2)   │         │                      │
 │                            ├─► go2rtc ──────┼─RTSP────► detect / record     │
 │  head cam (NAOqi) ─ naoqi_cam.py ─┘  :8554  │  MJPEG  │ (CPU-decode MJPEG)   │
 │                                             │         │                      │
 │  onvif_ptz.py  :8000  ◄─────────────────────┼─ONVIF───┤ PTZ controls /       │
 │      │  ALMotion (HeadYaw/HeadPitch)        │  PTZ    │ autotracking         │
 │      ▼                                      │         │                      │
 │   robot head moves                          │         └──────────────────────┘
 └───────────────────────────────────────────┘
```

---

## Why MJPEG (and not H.264)

Pepper's CPU (32-bit Atom E3845) cannot software-encode H.264 in real time.
MJPEG (intra-frame JPEG) is cheap to encode, so the robot stays responsive.

The trade-off lands on the Frigate host: an **NVIDIA GPU (e.g. P2000) cannot
hardware-decode MJPEG** (NVDEC has no JPEG decoder). MJPEG therefore decodes on
the host CPU — negligible for these low-resolution cameras. This is why the
Frigate config forces `hwaccel_args: []` on the Pepper cameras (see
[`frigate/cameras.yml`](frigate/cameras.yml)). Object detection still runs on the
GPU/Coral as usual — it is independent of the decode path.

---

## Contents

```
frigate-surveillance/
├── README.md                  ← this file
├── go2rtc/
│   ├── go2rtc.yaml            go2rtc config (two MJPEG streams)
│   └── naoqi_cam.py           NAOqi → MJPEG bridge for the head camera
├── onvif/
│   ├── onvif_ptz.py           minimal ONVIF PTZ server → ALMotion head control
│   └── pepper_keepawake.py    periodic check: wake the robot if it has rested
├── systemd/
│   ├── go2rtc.service         runs go2rtc on boot
│   ├── onvif-ptz.service      runs the ONVIF PTZ bridge on boot
│   ├── pepper-keepawake.service  oneshot keep-awake check
│   └── pepper-keepawake.timer    runs the check every 6 h
└── frigate/
    └── cameras.yml            camera blocks to merge into your Frigate config
```

---

## How it works

### Bottom camera — direct V4L2
`/dev/video2` (the mouth camera) is **not held by NAOqi**, so go2rtc captures it
directly with ffmpeg and encodes MJPEG. No NAOqi involvement.

### Head camera — NAOqi bridge
The forehead and stereo cameras are **held by `naoqi-service`**, so they cannot be
opened via V4L2. [`naoqi_cam.py`](go2rtc/naoqi_cam.py) subscribes to the camera
through `ALVideoDevice`, JPEG-encodes each frame with PIL, and writes a raw MJPEG
stream to stdout. go2rtc runs it as an `exec:` source.
> Gotcha handled inside: the `qi` library prints log lines to **stdout**, which
> would corrupt the MJPEG byte stream. The script redirects fd 1 to stderr
> *before* importing `qi` and writes JPEG to a saved stdout fd.

### ONVIF PTZ — head movement
[`onvif_ptz.py`](onvif/onvif_ptz.py) is a tiny ONVIF server (device/media/ptz/
imaging, SOAP 1.2) that answers exactly what Frigate's `onvif-zeep` client asks,
and maps PTZ moves to `ALMotion` `HeadYaw`/`HeadPitch`. Notable behaviour:
- **Wakes the robot** (`motion.wakeUp()`) when it has gone to rest — otherwise the
  joints are limp and `setAngles` is silently ignored.
- Keeps the robot awake (`ALBackgroundMovement`) so PTZ stays instant; pauses
  `ALBasicAwareness` while aiming so the head doesn't fight the operator.
- Per-axis speed: pitch travel is much shorter than yaw, so it uses a lower speed
  factor to avoid overshoot on small up/down taps.

---

## Prerequisites

- A Pepper robot reachable on your LAN (this setup uses `ssh pepper`, IP
  `192.168.11.182` on WiFi / `.183` on Ethernet). Python 2.7 + NAOqi SDK at
  `/opt/aldebaran/lib/python2.7/site-packages` (stock NAOqiOS 2.7.x).
- A working **Frigate** install (tested with **0.17.1**) on another host.
- `sudo` on the robot (the stock `nao` user has it).

---

## Installation (on the robot)

All robot-side files live under `/data` (the root FS is tiny and ~97% full;
`/data` has space).

### 1. Install the go2rtc binary

go2rtc is a single static binary. Pepper is **32-bit i686**, so use the `i386`
build. The robot's 2017 CA bundle rejects the GitHub CDN, so download on your dev
machine and copy it over:

```bash
# on your dev machine
curl -sL -o go2rtc \
  https://github.com/AlexxIT/go2rtc/releases/download/v1.9.14/go2rtc_linux_i386
ssh pepper 'sudo mkdir -p /data/go2rtc /data/onvif && sudo chown nao:nao /data/go2rtc /data/onvif'
scp go2rtc pepper:/data/go2rtc/go2rtc
ssh pepper 'chmod +x /data/go2rtc/go2rtc && /data/go2rtc/go2rtc --version'
```

### 2. Copy the project files

```bash
scp go2rtc/go2rtc.yaml   pepper:/data/go2rtc/go2rtc.yaml
scp go2rtc/naoqi_cam.py  pepper:/data/go2rtc/naoqi_cam.py
scp onvif/onvif_ptz.py   pepper:/data/onvif/onvif_ptz.py
```

> **Use a hostname, not a hardcoded IP.** Pepper's WiFi address is handed out by
> DHCP and *will* change. When it does, anything pinned to the old IP breaks. The
> ONVIF bridge guards against this by **echoing back the `Host:` header the client
> used** when it advertises its service URLs (so PTZ keeps working as long as
> Frigate reaches the robot by a name that still resolves). Point Frigate's
> `rtsp://…` and `onvif: host:` at a stable DNS name (e.g. the short name `pepper`, completed by the LAN DNS search domain),
> and set a **DHCP reservation** on your router so the name keeps resolving. The
> `ONVIF_HOST` env in `systemd/onvif-ptz.service` is only a fallback for clients
> that send no `Host` header.

### 3. Install and start the systemd services

**Install them as user services of `nao`, not as system services.** On NAOqiOS,
`/etc` is an overlay mounted from `/data`, and systemd builds its boot
transaction before that mount: a unit enabled in `/etc/systemd/system` is never
started at boot (found on 2026-10-23: `go2rtc`, `onvif-ptz` and the keep-awake
timer had not started since the last reboot). The `nao` user manager (which also
runs NAOqi) starts later and reads `~/.config/systemd/user/`.

```bash
scp systemd/go2rtc.service pepper:.config/systemd/user/
ssh pepper 'export XDG_RUNTIME_DIR=/run/user/1001 &&
  systemctl --user daemon-reload &&
  systemctl --user enable --now go2rtc &&
  systemctl --user is-active go2rtc'
```

For `onvif-ptz.service` (and `pepper-keepawake.*`), drop the `User=`/`Group=`
lines and use `WantedBy=default.target` in the same way.

> Note: this robot runs systemd **v229** — do not add `StartLimitIntervalSec` to
> the `[Service]` section (it is rejected as an unknown key).

### 4. Verify the streams and PTZ

```bash
# from any LAN machine with ffmpeg
ffprobe -rtsp_transport tcp rtsp://192.168.11.182:8554/bottom
ffprobe -rtsp_transport tcp rtsp://192.168.11.182:8554/head
# go2rtc web UI / preview:
xdg-open http://192.168.11.182:1984/
```

---

## Frigate configuration

Merge [`frigate/cameras.yml`](frigate/cameras.yml) into your Frigate `config.yml`,
fix the IP, then **restart Frigate** (a config reload is *not* enough for ONVIF).

Key point already baked into the snippet: `hwaccel_args: []` on both Pepper
cameras so MJPEG is CPU-decoded instead of being sent to the GPU NVDEC.

---

## Usage

- **Live view / recording / detection**: the cameras appear like any other Frigate
  camera once configured.
- **PTZ (head)**: open the **`pepper_head` camera in full-screen view**. The PTZ
  arrows appear in the bottom bar (the dashboard grid does not show them). Use the
  arrows, keyboard arrow keys, or drag on the image to aim the head.
  - Short tap = small move; press and hold = continuous move until release.
  - Presets are stored on the robot.

---

## Tuning

### `onvif/onvif_ptz.py` (top of file) — restart `onvif-ptz` after editing
| Constant | Default | Meaning |
|---|---|---|
| `YAW_SIGN`, `PITCH_SIGN` | `-1.0` | flip if a Frigate arrow moves the head the wrong way |
| `YAW_SPEED_SCALE` | `0.6` | left/right speed (fraction of joint max speed) |
| `PITCH_SPEED_SCALE` | `0.12` | up/down speed — low on purpose (short pitch travel overshoots otherwise) |
| `KEEP_AWAKE` | `True` | keep motors energized so PTZ is instant. `False` = robot rests when idle and re-wakes (and recenters) on the first move |
| `RESUME_AWARENESS_AFTER` | `8.0` | seconds idle before `ALBasicAwareness` resumes |

### `go2rtc/go2rtc.yaml`
- Lower resolution/fps (e.g. `-video_size 320x240`, `-framerate 5`, or
  `naoqi_cam.py 0 1 5` for QVGA) if the robot gets sluggish.
- Streams are **lazy**: nothing runs until a client connects.

```bash
ssh pepper 'sudo systemctl restart go2rtc onvif-ptz'
```

---

## Keeping the robot awake

NAOqi puts Pepper to **rest** after ~30 s of inactivity; once rested the joints go
limp and `setAngles` is silently ignored, so PTZ does nothing until the next
`wakeUp()`. The ONVIF bridge wakes the robot on demand, but a periodic safety net
keeps it ready (and re-enables `ALBackgroundMovement`).

NAOqiOS has **no cron daemon**, so this is a **systemd timer**:

```bash
scp onvif/pepper_keepawake.py        pepper:/data/onvif/pepper_keepawake.py
scp systemd/pepper-keepawake.service pepper:/tmp/
scp systemd/pepper-keepawake.timer   pepper:/tmp/
ssh pepper '
  chmod +x /data/onvif/pepper_keepawake.py &&
  sudo mv /tmp/pepper-keepawake.service /tmp/pepper-keepawake.timer /etc/systemd/system/ &&
  sudo systemctl daemon-reload &&
  sudo systemctl enable --now pepper-keepawake.timer &&
  systemctl list-timers pepper-keepawake.timer'
```

Runs every 6 h (`OnUnitActiveSec=6h`, `Persistent=true`), logging one line per
check to `/data/onvif/keepawake.log`. Force a check with
`sudo systemctl start pepper-keepawake.service`.

> Heads-up on CPU: even with no video streaming, `naoqi-service` alone uses ~2 of
> the 4 Atom cores because Pepper's autonomous **3D-vision / navigation** stack
> (stereo + depth + `VisionNavigation`) runs continuously. Lowering stream fps
> barely changes the total; meaningfully freeing CPU means disabling that
> autonomous stack (a behaviour change) or rebooting a long-up robot.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `go2rtc: magic: unsupported header` on the head stream | The `qi` lib polluted stdout. Use the provided `naoqi_cam.py` (redirects fd 1 → stderr). |
| Frigate: *"No appropriate Onvif profiles found"* | The media profile must expose `VideoEncoderConfiguration` + `PTZConfiguration` + a pan/tilt velocity space — the provided `onvif_ptz.py` does this. Restart Frigate. |
| PTZ arrows show but **nothing moves**, no request reaches the robot | Frigate's ONVIF controller wasn't (re)initialized. Restart Frigate, then reopen the camera so the frontend re-triggers init (`GET /api/<cam>/ptz/info`). |
| PTZ command reaches the robot but the head doesn't move | Robot was asleep (`robotIsWakeUp() == False`). The bridge calls `wakeUp()`; ensure `KEEP_AWAKE=True`. Head stiffness can read `1.0` even while rested — don't trust it. |
| Up/down overshoots on small taps | Lower `PITCH_SPEED_SCALE`. |
| Frigate (0.17) shows no arrows at all | 0.17 requires an ONVIF **imaging** service; `onvif_ptz.py` advertises and answers it. Make sure you deployed the current version and restarted Frigate. |
| Arrows were working, now gone; Frigate log: *"Unable to get Onvif media profiles … timed out"* | The robot's **DHCP IP changed** and a stale IP was being advertised. Use a DNS name in the Frigate config (the bridge echoes the `Host` header, so XAddrs follow it) and add a DHCP reservation. `ping` may work while TCP fails if you test from the wrong host — see next row. |
| ONVIF/RTSP unreachable from the Frigate **host shell** but Frigate still can't connect | Frigate runs in a docker container with its own network path. Test from the container: `ssh <frigate-host> 'docker exec frigate curl -m5 http://<robot-name>:8000/onvif/device_service -d ...'`, not from the host shell. |
| Check what the robot received | `ssh pepper 'journalctl -u onvif-ptz -f'` logs every `ONVIF REQ from <ip> op=<op>`. |

---

## Robot facts (reference)

- CPU: Intel Atom E3845 (4 cores, 32-bit i686), NAOqiOS, glibc 2.23, Python 2.7.
- Cameras: `bottom` = `/dev/video2` (free); `top`/`stereo` held by `naoqi-service`.
- Head joint limits: `HeadYaw` ±2.0857 rad, `HeadPitch` −0.7069 .. +0.4451 rad.
- Ports: RTSP `8554`, go2rtc API/UI `1984`, WebRTC `8555`, ONVIF `8000`.
- With the head stream active the 4-core Atom sits around load ~9 — fine, but drop
  resolution/fps if you add more load.
