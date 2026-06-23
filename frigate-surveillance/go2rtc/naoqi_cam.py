#!/usr/bin/env python2
# NAOqi camera -> raw MJPEG on stdout, for go2rtc exec source.
# Usage: python2 naoqi_cam.py [camera_index] [resolution] [fps]
#   camera_index: 0=top(head) 1=bottom 2=depth/stereo   (default 0)
#   resolution:   1=QVGA(320x240) 2=VGA(640x480)        (default 2)
#   fps:          frames per second                      (default 10)
import os, sys
# The qi library writes its log lines to stdout (fd 1), which would corrupt the
# raw MJPEG byte stream go2rtc reads. Save the real stdout, then point fd 1 at
# stderr so any library noise goes to the log, not into the video pipe.
_out_fd = os.dup(1)
os.dup2(2, 1)

import qi, time, signal, StringIO
from PIL import Image

cam = int(sys.argv[1]) if len(sys.argv) > 1 else 0
res = int(sys.argv[2]) if len(sys.argv) > 2 else 2
fps = int(sys.argv[3]) if len(sys.argv) > 3 else 10
COLORSPACE_RGB = 11

session = qi.Session()
session.connect('tcp://127.0.0.1:9559')
video = session.service('ALVideoDevice')
name = 'go2rtc_%d_%d' % (cam, os.getpid())
sub = video.subscribeCamera(name, cam, res, COLORSPACE_RGB, fps)

def cleanup(*a):
    try:
        video.unsubscribe(sub)
    except Exception:
        pass
    os._exit(0)

signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

period = 1.0 / fps
try:
    while True:
        t0 = time.time()
        img = video.getImageRemote(sub)
        if not img or img[6] is None:
            time.sleep(0.02)
            continue
        w, h, data = img[0], img[1], img[6]
        pil = Image.frombytes('RGB', (w, h), bytes(bytearray(data)))
        buf = StringIO.StringIO()
        pil.save(buf, 'JPEG', quality=70)
        os.write(_out_fd, buf.getvalue())
        dt = period - (time.time() - t0)
        if dt > 0:
            time.sleep(dt)
finally:
    cleanup()
