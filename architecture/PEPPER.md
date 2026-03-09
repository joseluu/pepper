# Pepper Robot — System Architecture

## Overview

This document describes the internal software architecture of the Pepper robot (NAOqiOS 3.3.10.1, NAOqi 2.7.1.128) and planned additions for Python 3 and Node.js bindings.

**Color convention in diagrams:**
- Default / neutral colors = existing base architecture (shipped with the robot)
- <span style="color:#22aa22">**Green**</span> = planned additions (qipy, qinode, vigiclient, Broadway.js streaming)

---

## 1. Hardware Layer

```mermaid
block-beta
  columns 3

  block:sensors["Sensors & Actuators"]:3
    columns 3
    cam_top["📷 Top Camera\nOV5640 (5MP)\n/dev/video-top"]
    cam_bot["📷 Bottom Camera\nOV5640\n/dev/video-bottom"]
    cam_depth["📷 Depth Camera\nXTION\n/dev/video-stereo"]
    mic["🎤 4× Microphones\n(head ring)"]
    speakers["🔊 Speakers"]
    touch["👆 Tactile Sensors\n(head, hands)"]
    motors["⚙️ 20 Joints\n(head, arms, hip, knee)"]
    leds["💡 LEDs\n(eyes, ears, shoulders)"]
    imu["📐 IMU\n(gyro + accel)"]
  end

  space:3

  block:hw["Hardware Platform"]:3
    columns 3
    cpu["Intel Atom\ni686 32-bit"]
    gpu["Intel GPU\nVA-API H.264 HW encode\ni965_drv_video.so"]
    storage["Storage\nRoot: 1.5GB (93% full)\n/data: 25GB"]
  end
```

---

## 2. Full Software Stack

```mermaid
flowchart TB
  subgraph ROBOT["<b>Pepper Robot</b> (NAOqiOS 3.3.10.1, i686)"]
    direction TB

    subgraph KERNEL["Kernel (4.0.4-rt1-aldebaran, PREEMPT RT)"]
      V4L2["V4L2 drivers\n(videodev, uvcvideo, soc_camera)"]
      GPIO["I2C / GPIO / UART"]
      ALSA_K["ALSA audio"]
    end

    subgraph NAOQI["NAOqi Core (port 9559)"]
      NAOQI_BIN["naoqi-bin\nService broker\nBinary QiMessaging\nmagic 0x42dead42"]
      ALVIDEO["ALVideoDevice"]
      ALMOTION["ALMotion\n(20 joints)"]
      ALTTS["ALTextToSpeech"]
      ALAUDIO["ALAudioDevice"]
      ALMEM["ALMemory"]
      ALSYS["ALSystem"]
      ALLIFE["ALAutonomousLife"]
      ALBAT["ALBattery"]
      ALPHOTO["ALPhotoCapture"]
    end

    subgraph PY2ENV["Python 2.7 Environment"]
      QI_PY2["qi Python 2 bindings\n(libqipython.so + _qi.so)"]
      PYTHON2["Python 2.7.11\n(/usr/bin/python2)"]
    end

    subgraph WEBBRIDGE["Web / Socket.IO Bridge"]
      QIMSG_JSON["qimessaging-json\n(Python 2 / Tornado 4.3)\nSocket.IO 0.9.11, port 8002"]
      NGINX["nginx 1.8.1\nport 80\nproxy → 127.0.0.1:8002"]
      QIMSG_JS["qimessaging.js v1.0 + v2\n(/opt/aldebaran/var/www/)"]
    end

    subgraph MEDIA["Media Tools (installed)"]
      FFMPEG["ffmpeg 3.0\nlibx264, libavcodec57\nVA-API support"]
      GST["GStreamer 0.10 + 1.0\njpegenc, x264enc, vaapi"]
      LIBJPEG["libjpeg 6.2"]
    end

    subgraph PY3ENV["Python 3.5 (/data/python3.5/) — deployed"]
      PYTHON3["Python 3.5.10"]
      QI_BRIDGE["qi_bridge_server.py\n(Python 2 process)\nUnix socket JSON"]
      QI_CLIENT["qi_bridge_client.py\n(Python 3 module)"]
      PY3QI["python3-qi wrapper"]
    end

    subgraph QIPY["qipy — Pure Python 3 QiMessaging (PLANNED)"]
      QIPY_LIB["qipy library\nDirect TCP to port 9559\nNo C extensions, no bridge"]:::planned
    end

    subgraph VIGICLIENT["vigiclient-pepper (PLANNED)"]
      NODE10["Node.js 10\n(/data/node10/)"]:::planned
      VIGICLI["vigiclient (modified)\nsocket.io-client 2.3\nstream-split NAL"]:::planned
    end

    subgraph H264STREAM["H.264 Video Streaming (PLANNED)"]
      WS_SERVER["Tornado WebSocket server\nport 8080\nNAL splitter"]:::planned
    end

    %% Existing connections
    V4L2 -.->|"V4L2 ioctl"| ALVIDEO
    GPIO -.-> ALMOTION
    ALSA_K -.-> ALAUDIO

    ALVIDEO & ALMOTION & ALTTS & ALAUDIO & ALMEM & ALSYS & ALLIFE & ALBAT & ALPHOTO --> NAOQI_BIN

    QI_PY2 -->|"binary protocol\n(in-process)"| NAOQI_BIN
    PYTHON2 --> QI_PY2

    QIMSG_JSON -->|"import qi\nqi.Session()"| QI_PY2
    NGINX -->|"proxy\nSocket.IO"| QIMSG_JSON

    QI_BRIDGE -->|"import qi"| QI_PY2
    QI_CLIENT -.->|"Unix socket\nJSON"| QI_BRIDGE
    PY3QI --> QI_BRIDGE & PYTHON3

    %% Planned connections
    QIPY_LIB -->|"TCP 9559\nbinary QiMessaging"| NAOQI_BIN
    VIGICLI -->|"Socket.IO 0.9\nNAOqi calls"| QIMSG_JSON
    WS_SERVER -->|"stdin pipe\nH.264 Annex B"| FFMPEG
    FFMPEG -->|"V4L2 capture"| V4L2
  end

  subgraph PC["<b>PC / Laptop</b> (LAN)"]
    subgraph QINODE["qinode — Node.js NAOqi client (PLANNED)"]
      QINODE_LIB["qinode library\nsocket.io-client 0.9.16\nServiceProxy + MetaObject"]:::planned
    end

    subgraph BROWSER_G["Browser"]
      BROWSER_SDK["qimessaging.js\n(official SDK)\nSocket.IO 0.9.11"]
      BROADWAY["Broadway.js (PLANNED)\nH.264 decoder → canvas\nWebSocket client"]:::planned
    end
  end

  subgraph CLOUD["<b>vigibot.com</b> (Internet)"]
    VIGIBOT_SRV["Vigibot server\nSocket.IO 2.x\nRobot control + video relay"]:::planned
  end

  %% External connections (existing)
  BROWSER_SDK -->|"Socket.IO\nport 80"| NGINX

  %% External connections (planned)
  QINODE_LIB -->|"Socket.IO 0.9\nport 80"| NGINX
  BROADWAY -->|"WebSocket port 8080\nbinary NAL units"| WS_SERVER
  VIGICLI -->|"Socket.IO 2.3\nNAL video + telemetry"| VIGIBOT_SRV

  classDef planned fill:#e8ffe8,stroke:#22aa22,color:#227722
```

---

## 3. Communication Protocols

### 3.1 Existing protocol layers

```mermaid
graph LR
  subgraph "Port 9559 — Binary QiMessaging"
    A["Client"] -->|"TCP"| B["NAOqi Broker"]
    B -->|"36-byte header\n+ binary payload\nmagic 0x42dead42"| A
  end

  subgraph "Port 8002 — Socket.IO Bridge"
    C["qimessaging-json\n(Tornado/Python 2)"] -->|"qi.Session()"| B
    D["Socket.IO client"] -->|"JSON events:\ncall, reply, error, signal"| C
  end

  subgraph "Port 80 — nginx"
    E["Browser / JS client"] -->|"HTTP + WebSocket\n/libs/qimessaging/*/socket.io/"| F["nginx"]
    F -->|"proxy_pass"| C
  end

  style A fill:#e8e8ff,stroke:#6666aa
  style B fill:#e8e8ff,stroke:#6666aa
  style C fill:#e8e8ff,stroke:#6666aa
  style D fill:#e8e8ff,stroke:#6666aa
  style E fill:#e8e8ff,stroke:#6666aa
  style F fill:#e8e8ff,stroke:#6666aa
```

### 3.2 All protocol paths (existing + planned)

```mermaid
flowchart TB
  subgraph ROBOT["Pepper Robot"]
    NAOQI["NAOqi Core\nport 9559\nBinary QiMessaging"]

    subgraph EXISTING_BRIDGES["Existing Bridges"]
      direction TB
      QI_PY2["qi Python 2 bindings\n(in-process, libqipython.so)"]
      QIMSG["qimessaging-json\n(Tornado, port 8002)"]
      NGINX["nginx\n(port 80)"]
      QI_BRIDGE["qi_bridge_server.py\n(Python 2, Unix socket)"]
    end

    subgraph PLANNED_ONROBOT["Planned On-Robot Components"]
      direction TB
      QIPY["qipy\nPure Python 3\nbinary protocol"]:::planned
      NODE10["Node.js 10\nvigiclient-pepper"]:::planned
      WS_H264["Tornado WS server\nport 8080\nH.264 NAL splitter"]:::planned
      FFMPEG["ffmpeg\nH.264 baseline\nAnnex B"]:::planned
      V4L2["V4L2 camera"]
    end

    QI_PY2 --> NAOQI
    QIMSG --> QI_PY2
    NGINX -->|"proxy"| QIMSG
    QI_BRIDGE --> QI_PY2

    QIPY -->|"TCP 9559\nbinary"| NAOQI
    NODE10 -->|"Socket.IO 0.9\nport 8002"| QIMSG

    FFMPEG -->|"V4L2 ioctl"| V4L2
    WS_H264 -->|"stdin pipe"| FFMPEG
  end

  subgraph PC["PC / Laptop"]
    BROWSER["Browser\nqimessaging.js"]
    BROADWAY["Browser\nBroadway.js\nH.264 canvas"]:::planned
    QINODE["qinode\nNode.js\nsocket.io-client 0.9.16"]:::planned
    PY3_SCRIPT["Python 3 script\nqi_bridge_client"]
  end

  subgraph CLOUD["Internet"]
    VIGIBOT["vigibot.com\nSocket.IO 2.x"]:::planned
  end

  BROWSER -->|"Socket.IO\nport 80"| NGINX
  QINODE -->|"Socket.IO\nport 80"| NGINX
  PY3_SCRIPT -->|"Unix socket\nJSON"| QI_BRIDGE
  BROADWAY -->|"WebSocket\nport 8080\nbinary NAL"| WS_H264
  NODE10 -->|"Socket.IO 2.3\nNAL + telemetry"| VIGIBOT

  classDef planned fill:#e8ffe8,stroke:#22aa22,color:#227722
```

---

## 4. Video Pipeline

### 4.1 Existing video access (no streaming)

```mermaid
sequenceDiagram
  participant Client as Client (Python/JS)
  participant Bridge as qimessaging-json
  participant VD as ALVideoDevice
  participant V4L as V4L2 Kernel Driver
  participant Cam as Camera Hardware

  Client->>Bridge: call("subscribeCamera", [name, 0, 2, 11, 15])
  Bridge->>VD: subscribeCamera(name, 0, VGA, RGB, 15fps)
  VD->>V4L: open /dev/video-top, ioctl VIDIOC_STREAMON
  V4L->>Cam: start capture
  VD-->>Bridge: subscriber ID
  Bridge-->>Client: subscriber ID

  loop Every frame request
    Client->>Bridge: call("getImageRemote", [subId])
    Bridge->>VD: getImageRemote(subId)
    VD->>V4L: ioctl VIDIOC_DQBUF
    V4L-->>VD: raw pixel buffer
    VD-->>Bridge: ALValue [w, h, layers, colorspace, ts, ?, pixels]
    Note over Bridge: bytearray → JSON int array (v2)<br/>or base64 string (v1.0)<br/>921KB raw → 3-5MB JSON per VGA frame!
    Bridge-->>Client: JSON frame data
  end

  Client->>Bridge: call("unsubscribe", [subId])
  Bridge->>VD: unsubscribe(subId)
  VD->>V4L: ioctl VIDIOC_STREAMOFF
```

### 4.2 Planned H.264 streaming (Broadway.js)

```mermaid
sequenceDiagram
  participant Browser as Browser (Broadway.js)
  participant WS as Tornado WS Server<br/>(port 8080)
  participant FF as ffmpeg
  participant V4L as /dev/video-top

  Note over FF,V4L: ffmpeg -f v4l2 -video_size 320x240 -framerate 15<br/>-i /dev/video-top -c:v libx264 -profile:v baseline<br/>-tune zerolatency -f h264 pipe:1

  FF->>V4L: V4L2 capture
  V4L-->>FF: raw YUV frames

  Browser->>WS: WebSocket connect ws://robot:8080/video

  loop Continuous stream
    FF-->>WS: H.264 Annex B byte stream (stdout)
    Note over WS: Split on 00 00 00 01<br/>start codes
    WS->>Browser: binary WS message (1 NAL unit, 1-5 KB)
    Note over Browser: decoder.decode(nalUnit)<br/>render to canvas
  end
```

### 4.3 Planned vigiclient video path

```mermaid
sequenceDiagram
  participant Vigibot as vigibot.com
  participant VC as vigiclient-pepper<br/>(Node.js 10)
  participant FF as ffmpeg
  participant V4L as /dev/video-top

  FF->>V4L: V4L2 capture
  V4L-->>FF: raw YUV frames
  FF-->>FF: H.264 encode (baseline, zerolatency)
  FF->>VC: TCP localhost (H.264 Annex B)

  Note over VC: stream-split on<br/>00 00 00 01

  loop Each NAL unit
    VC->>Vigibot: socket.emit("serveurrobotvideo",<br/>{timestamp, data: nalBuffer})
  end

  Vigibot->>VC: socket.emit("clientsrobottx", commandFrame)
  Note over VC: Parse Rx telemetry frame<br/>Map servo channels → ALMotion joints
  VC->>VC: NAOqi call via Socket.IO bridge<br/>ALMotion.setAngles(joints, angles, speed)
```

---

## 5. NAOqi Service Map

```mermaid
graph TB
  subgraph NAOqi["NAOqi Services (port 9559)"]

    subgraph Perception[" Perception "]
      VD["ALVideoDevice\n3 cameras, V4L2\nsubscribe/poll"]:::perception
      PC["ALPhotoCapture\nJPEG/PNG to file"]:::perception
      VR["ALVideoRecorder\nRecord to file"]:::perception
      AD["ALAudioDevice\n4 microphones"]:::perception
      SL["ALSoundLocalization\nSound direction"]:::perception
      SR["ALSpeechRecognition\nKeyword spotting"]:::perception
      FD["ALFaceDetection"]:::perception
      PP["ALPeoplePerception"]:::perception
    end

    subgraph Motion[" Motion "]
      MO["ALMotion\n20 joints\nsetAngles, moveTo\nwakeUp, rest"]:::motion
      RP["ALRobotPosture\nStand, Sit, Crouch"]:::motion
      NV["ALNavigation\nmoveTo, navigateTo"]:::motion
    end

    subgraph Speech[" Speech "]
      TTS["ALTextToSpeech\nEN, ZH (no FR)\nespeak engine"]:::speech
      AS["ALAnimatedSpeech\nSpeech + gestures"]:::speech
      DL["ALDialog\nTopic-based dialog"]:::speech
    end

    subgraph System[" System "]
      SY["ALSystem\nversion, reboot, robotName"]:::system
      BA["ALBattery\ncharge, status, temperature"]:::system
      ME["ALMemory\nKey-value store, event hub"]:::system
      CM["ALConnectionManager\nWiFi management"]:::system
    end

    subgraph Behavior[" Behavior "]
      AL["ALAutonomousLife\nAwareness, reactions"]:::behavior
      BM["ALBehaviorManager\nInstalled behaviors"]:::behavior
    end
  end

  classDef perception fill:#ffe8e8,stroke:#cc6666
  classDef motion fill:#e8e8ff,stroke:#6666cc
  classDef speech fill:#fff8e0,stroke:#ccaa44
  classDef system fill:#e8ffe8,stroke:#66aa66
  classDef behavior fill:#ffe8ff,stroke:#aa66aa
```

---

## 6. Network Ports & Endpoints

```mermaid
graph TB
  subgraph ROBOT["Pepper (192.168.11.182 wifi / .183 eth)"]
    P9559["Port 9559\nNAOqi binary protocol\nQiMessaging (TCP)"]
    P80["Port 80\nnginx\nWeb UI + Socket.IO proxy"]
    P8002["Port 8002\nqimessaging-json\nSocket.IO 0.9.11 (Tornado)"]
    P8080["Port 8080 (PLANNED)\nTornado WebSocket\nH.264 NAL stream"]:::planned

    P80 -->|"/libs/qimessaging/*/socket.io/*"| P8002
    P8002 -->|"qi.Session()"| P9559
    P80 -->|"/video (PLANNED)"| P8080
  end

  subgraph ENDPOINTS["Served content on port 80"]
    E1["/ → robot-page (AngularJS UI)"]
    E2["/advanced → settings UI"]
    E3["/libs/qimessaging/2/qimessaging.js"]
    E4["/apps/*/html/ → installed apps"]
    E5["/version → NAOqi version"]
    E6["/video → H.264 WS (PLANNED)"]:::planned
  end

  classDef planned fill:#e8ffe8,stroke:#22aa22,color:#227722
```

---

## 7. Filesystem Layout

```
/ (rootfs, 1.5 GB, 93% full — DO NOT install here)
├── opt/aldebaran/
│   ├── bin/
│   │   └── qimessaging-json          # Socket.IO ↔ NAOqi bridge (Python 2)
│   ├── lib/
│   │   ├── naoqi/
│   │   │   ├── libalvideodevice.so    # ALVideoDevice
│   │   │   ├── libphotocapture.so     # ALPhotoCapture
│   │   │   └── libvideorecorder.so    # ALVideoRecorder
│   │   ├── libvideodevice.so          # V4L2 hardware layer
│   │   ├── libqipython.so            # Python 2 qi bindings
│   │   ├── libqipython3.so           # Python 3 qi bindings (UNUSABLE — ABI mismatch)
│   │   ├── libboost_python3.so.1.59.0
│   │   ├── libx264.so.144            # H.264 encoder
│   │   └── python2.7/site-packages/
│   │       ├── qi/                    # Python 2 SDK
│   │       └── vision_definitions.py  # Camera constants
│   └── var/www/
│       └── libs/qimessaging/
│           ├── 1.0/qimessaging.js     # Legacy JS SDK
│           └── 2/qimessaging.js       # Current JS SDK (Socket.IO 0.9.11 bundled)
├── usr/
│   ├── bin/
│   │   ├── ffmpeg                     # FFmpeg 3.0
│   │   ├── gst-launch-0.10           # GStreamer 0.10
│   │   └── gst-launch-1.0            # GStreamer 1.0
│   └── lib/
│       ├── libavcodec.so.57
│       ├── libjpeg.so.62
│       ├── libva.so.1                 # VA-API
│       ├── dri/i965_drv_video.so      # Intel GPU VA-API driver
│       ├── gstreamer-0.10/
│       │   ├── libgstjpeg.so          # JPEG encoder
│       │   ├── libgstx264.so          # H.264 encoder (annexb support)
│       │   ├── libgstmultipart.so     # Multipart mux (MJPEG)
│       │   └── libgsttcp.so           # TCP sink/source
│       └── gstreamer-1.0/
│           ├── libgstvideo4linux2.so  # V4L2 source
│           ├── libgstvaapi.so         # VA-API H.264/JPEG/VP8 HW encode
│           ├── libgstmultipart.so
│           └── libgsttcp.so
└── etc/nginx/nginx.conf               # nginx config (port 80)

/data/ (25 GB, plenty of space — install everything here)
├── python3.5/                          # DEPLOYED
│   ├── bin/
│   │   ├── python3.5                  # Python 3.5.10 interpreter
│   │   ├── python3-qi                 # Wrapper (starts bridge, sets env)
│   │   ├── qi_bridge_server.py        # Python 2 NAOqi proxy
│   │   ├── start_qi_bridge.sh         # Bridge lifecycle
│   │   └── pip3.5                     # Package manager
│   └── lib/
│       ├── libpython3.5m.so.1.0
│       └── python3.5/site-packages/
│           └── qi_bridge_client.py    # Python 3 client module
│
├── node10/                             # PLANNED (vigiclient)
│   ├── bin/
│   │   ├── node                       # Node.js 10.24.1
│   │   └── npm
│   └── lib/node_modules/
│
└── vigiclient-pepper/                  # PLANNED
    ├── clientrobotpi.js               # Modified vigiclient
    └── node_modules/
        ├── socket.io-client/          # 2.3.x
        └── stream-split/             # NAL splitter
```

<span style="color:#22aa22">Green items above are planned additions — everything else is already deployed.</span>

---

## 8. Planned Additions Summary

```mermaid
flowchart LR
  subgraph EXISTING["Existing (shipped / deployed)"]
    NAOQI["NAOqi Core\nport 9559\nBinary QiMessaging"]
    BRIDGE["qimessaging-json\nSocket.IO bridge\nport 8002"]
    PYBRIDGE["qi_bridge_server.py\nPython 2 Unix socket\nbridge for Python 3.5"]
    CAMERAS["V4L2 Cameras\n/dev/video-top\n/dev/video-bottom"]
  end

  subgraph PLANNED["Planned Additions"]
    QIPY["<b>qipy</b>\nPure Python 3 QiMessaging\nRuns ON robot\nDirect TCP to 9559\nNo bridge, no Python 2"]:::planned
    QINODE["<b>qinode</b>\nNode.js NAOqi client\nRuns on PC\nsocket.io-client 0.9.16\nPromise-based API"]:::planned
    BROADWAY["<b>H.264 Broadway.js</b>\nffmpeg → NAL → WebSocket\nTornado server port 8080\nBrowser: canvas decoder\n~55ms with VA-API"]:::planned
    VIGICLIENT["<b>vigiclient-pepper</b>\nNode.js 10 on robot\nVideo to vigibot.com\nNAL-over-Socket.IO\nMotor via NAOqi bridge"]:::planned
  end

  PYBRIDGE -->|"qi.Session()"| NAOQI
  BRIDGE -->|"qi.Session()"| NAOQI

  QIPY -->|"binary protocol"| NAOQI
  QINODE -->|"Socket.IO 0.9"| BRIDGE
  VIGICLIENT -->|"Socket.IO 0.9\n(NAOqi calls)"| BRIDGE
  BROADWAY -->|"ffmpeg V4L2"| CAMERAS
  VIGICLIENT -->|"ffmpeg V4L2"| CAMERAS

  classDef planned fill:#e8ffe8,stroke:#22aa22,color:#227722
```

### Dependency matrix

| Component | Runs on | Connects to | Protocol | Status |
|-----------|---------|-------------|----------|--------|
| qi Python 2 | Robot | NAOqi | In-process (libqipython.so) | ✅ Shipped |
| qimessaging-json | Robot | NAOqi via qi Python 2 | Socket.IO 0.9 ↔ binary | ✅ Shipped |
| qi_bridge_server.py | Robot | NAOqi via qi Python 2 | Unix socket JSON ↔ binary | ✅ Deployed |
| qimessaging.js | Browser | nginx → qimessaging-json | Socket.IO 0.9 (JSON) | ✅ Shipped |
| **qipy** | Robot | NAOqi | TCP 9559 binary (pure Python 3) | 🟢 Planned |
| **qinode** | PC | nginx → qimessaging-json | Socket.IO 0.9 (JSON) | 🟢 Planned |
| **Broadway.js stream** | Robot + Browser | V4L2 → ffmpeg → WS → browser | H.264 NAL over WebSocket | 🟢 Planned |
| **vigiclient-pepper** | Robot | V4L2 + qimessaging-json + vigibot.com | H.264 NAL + telemetry over Socket.IO 2.3 | 🟢 Planned |
