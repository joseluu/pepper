#!/usr/bin/env python2
"""Capture a single depth image from Pepper's depth camera (camera 2)."""

import qi
import time
import struct

session = qi.Session()
session.connect('tcp://127.0.0.1:9559')

video = session.service('ALVideoDevice')

# Clear existing subscribers
for sub in video.getSubscribers():
    try:
        video.unsubscribe(sub)
    except Exception:
        pass

# Camera 2 = depth, Resolution 1 = QVGA (320x240)
# Colorspaces: 17 = kDepthColorSpace, 23 = kRawDepthColorSpace
# Try multiple colorspaces
for cs_name, cs in [('kDepthColorSpace', 17), ('kRawDepthColorSpace', 23),
                     ('kDistanceColorSpace', 21), ('kXYZColorSpace', 19)]:
    try:
        sub = video.subscribeCamera('depth_%d' % cs, 2, 1, cs, 5)
        time.sleep(2)
        img = video.getImageRemote(sub)
        video.unsubscribe(sub)
        if img is None:
            print('%s (cs=%d): no image (None)' % (cs_name, cs))
            continue
        w, h, layers = img[0], img[1], img[2]
        data = img[6]
        print('%s (cs=%d): %dx%d, %d layers, %d bytes' % (
            cs_name, cs, w, h, layers, len(data)))
        # Save raw data
        path = '/home/nao/depth_cs%d.raw' % cs
        with open(path, 'wb') as f:
            f.write(bytes(bytearray(data)))
        print('  Saved to %s' % path)
        # Show a few sample values
        if layers == 1 and len(data) >= w * 2:
            # 16-bit depth values (millimeters)
            samples = []
            for i in range(0, min(20, w * 2), 2):
                val = struct.unpack('<H', bytes(bytearray(data[i:i+2])))[0]
                samples.append(val)
            print('  First %d depth values (mm): %s' % (len(samples), samples))
    except Exception as e:
        print('%s (cs=%d): error: %s' % (cs_name, cs, e))

# Also try RGB on depth camera
try:
    sub = video.subscribeCamera('depth_rgb', 2, 1, 11, 5)
    time.sleep(2)
    img = video.getImageRemote(sub)
    video.unsubscribe(sub)
    if img is None:
        print('RGB on depth (cs=11): no image (None)')
    else:
        print('RGB on depth (cs=11): %dx%d, %d layers, %d bytes' % (
            img[0], img[1], img[2], len(img[6])))
except Exception as e:
    print('RGB on depth (cs=11): error: %s' % e)
