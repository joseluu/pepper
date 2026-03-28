# Video Streaming Proposal for Pepper Robot

## Context

The robot (memmer) has limited processing power (32-bit i686, older CPU). The goal is to achieve high-quality video streaming to a laptop browser.

## Camera Hardware

| Camera | Device | Default Resolution | Sensor |
|--------|--------|---------------------|--------|
| Top | /dev/video1 | 640×480 | OV5640 |
| Bottom | /dev/video2 | 640×480 | OV5640 |
| Stereo | /dev/video0 | 1344×376 | OV580 |

- Native format: YUV 4:2:2 (YUYV)
- Interface: USB 2.0, UVC compliant

## Constraints

- Robot CPU: weak, cannot encode H.264 in real-time at high quality
- Network: WiFi (limited bandwidth)
- Browser: can render VP8/VP9 (WebM), MJPEG natively

## Recommended Solution: MJPEG Streaming

**Architecture**: Robot captures YUV422 → encodes to JPEG → serves via HTTP → browser renders

### Why MJPEG?

1. **Minimal robot load**: JPEG encoding is lightweight (many hardware encoders available)
2. **Browser native support**: Chrome/FFmpeg render MJPEG without plugins
3. **Low latency**: Frame-by-frame streaming
4. **Good quality**: Can tune JPEG quality parameter

### Implementation

```python
# Robot side: capture + MJPEG server
import qi, cv2, numpy as np
from http.server import HTTPServer, BaseHTTPRequestHandler

session = qi.Session()
session.connect('tcp://127.0.0.1:9559')
video = session.service('ALVideoDevice')
sub = video.subscribeCamera('cam', 0, 2, 0, 15)  # top cam, VGA, YUV422, 15fps

class MJPEGHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.end_headers()
        while True:
            img = video.getImageRemote(sub)
            if img:
                data = np.frombuffer(bytes(img[6]), np.uint8)
                bgr = cv2.cvtColor(data.reshape(480, 640, 2), cv2.COLOR_YUV2BGR_YUYV)
                _, jpg = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
                self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpg.tobytes() + b'\r\n')

HTTPServer(('0.0.0.0', 8080), MJPEGHandler).serve_forever()
```

### Usage

- Laptop browser: `http://<robot-ip>:8080`
- Resolution: 640×480 @ 15fps (adjustable)
- JPEG quality: 85% (tunable)

## Alternative: Raw YUV + Laptop Decoding

For even lower robot load, stream raw YUV422 frames via UDP and decode on laptop:

```
Robot: ALVideoDevice → UDP socket → Laptop: FFmpeg → Display
```

Pros: Robot does zero encoding
Cons: Higher network bandwidth, requires laptop-side decoder

## Comparison

| Method | Robot CPU | Latency | Quality | Browser Support |
|--------|-----------|---------|---------|------------------|
| MJPEG | Low | Low | Good | Native |
| Raw UDP | Minimal | Very low | Best | Requires custom |
| H.264 | High | Medium | Good | Native (MSE) |

## Recommendation

Start with **MJPEG** — simplest implementation, good quality, browser-native. Optimize only if MJPEG quality/framerate proves insufficient.
