#!/usr/bin/env python2
"""Record all joint angles from sensors."""

import qi

session = qi.Session()
session.connect('tcp://127.0.0.1:9559')
motion = session.service('ALMotion')

joints = motion.getBodyNames('Body')
angles = motion.getAngles('Body', True)

for name, angle in zip(joints, angles):
    print('%-20s %.4f' % (name, angle))
