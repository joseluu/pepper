# Pepper Camera Configuration

3 cameras: 2 monocular (top/bottom) and 1 stereo depth camera.

| Camera ID   | Device        | Default Resolution | Sensor        | Position    |
|-------------|---------------|--------------------|---------------|-------------|
| Camera 0    | /dev/video1   | 640x480            | LI-OV5640     | Head (top)  |
| Camera 1    | /dev/video2   | 640x480            | LI-OV5640     | Chin (bottom)|
| Stereo      | /dev/video0   | 1344x376           | OV580 STEREO  | Forehead    |

Symlinks: `/dev/video-top` → video1, `/dev/video-bottom` → video2, `/dev/video-stereo` → video0.

## Hardware Specs

| Camera | FOV (H×V)    | Sensor      | Driver   |
|--------|--------------|-------------|----------|
| Top    | 60.9° × 47.6°| OV5640      | uvcvideo |
| Bottom | 60.9° × 47.6°| OV5640      | uvcvideo |
| Stereo | 61.0° × 48.0°| OV580 STEREO| uvcvideo |

- Sensor: Omnivision OV5640 (5 MP, native 2592×1944)
- Interface: USB 2.0 (UVC compliant)
- Driver version: 4.0.4 (Linux kernel)
- Native pixel format: YUV 4:2:2 (YUYV)

## Native UVC Stream Formats

### Top/Bottom Cameras (OV5640)

| Resolution | Max FPS | Notes |
|------------|---------|-------|
| 2592×1944  | 15      | Native sensor resolution |
| 1920×1080  | 30      | |
| 1280×960   | 30      | 4:3 aspect |
| 640×480    | 30      | Default |
| 320×240    | 30      | |

### Stereo Camera (OV580)

| Resolution | Max FPS | Notes |
|------------|---------|-------|
| 4416×1242  | 15      | Wide panoramic |
| 2560×720   | 60      | HD panoramic |
| 1344×376   | 60      | Default |

## ALVideoDevice Supported Formats

NAOqi provides abstracted access with these options:

### Resolutions (Resolution ID)

| ID  | Name   | Size       |
|-----|--------|------------|
| 0   | QQVGA | 160 × 120  |
| 1   | QVGA  | 320 × 240  |
| 2   | VGA   | 640 × 480  |
| 3   | 4VGA  | 1280 × 960 |

Note: Stereo camera supports panoramic resolutions (1344×376, 2560×720) only via direct V4L2 access.

### Color Spaces

| ID  | Name              | Notes |
|-----|-------------------|-------|
| 0   | YUV422            | Native camera format (fastest) |
| 1   | YUV               | |
| 2   | RGB               | |
| 3   | BGR               | |
| 9   | HSY               | Optimized for embedded (fast) |
| 10  | Y                 | Grayscale |
| 11  | RGB               | 24-bit |

Performance ranking: YUV422 > YUV > RGB/BGR > HSY

## NAOqi Service

`ALVideoDevice` — provides access to all 3 cameras.

```python
# Subscribe to top camera (VGA, RGB)
sub = video.subscribeCamera('capture', 0, 2, 11, 5)

# Camera IDs: 0=top, 1=bottom, 2=depth/stereo
# Resolution: 2=VGA(640x480), 1=QVGA(320x240), 3=4VGA(1280x960)
# Colorspace: 11=RGB, 0=YUV422 (native, fastest)
```

For best performance, use native YUV422 color space.
