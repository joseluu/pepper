#!/usr/bin/env python2
"""Relax arms (zero stiffness), keep robot awake with head movements."""

import qi
import time

session = qi.Session()
session.connect('tcp://127.0.0.1:9559')
motion = session.service('ALMotion')
bg = session.service('ALBackgroundMovement')

bg.setEnabled(False)
print('ALBackgroundMovement disabled')

arm_joints = [
    'LShoulderPitch', 'LShoulderRoll', 'LElbowYaw', 'LElbowRoll', 'LWristYaw', 'LHand',
    'RShoulderPitch', 'RShoulderRoll', 'RElbowYaw', 'RElbowRoll', 'RWristYaw', 'RHand',
]

print('Relaxing arms (Ctrl+C to stop)')

try:
    while True:
        # Zero stiffness on each arm joint
        for j in arm_joints:
            motion.setStiffnesses(j, 0.0)
        # Head movement to prevent idle rest
        motion.setStiffnesses('HeadYaw', 0.3)
        motion.setAngles('HeadYaw', 0.1, 0.1)
        time.sleep(2)
        motion.setAngles('HeadYaw', -0.1, 0.1)
        time.sleep(2)
        motion.setAngles('HeadYaw', 0.0, 0.1)
        time.sleep(1)
        motion.setStiffnesses('HeadYaw', 0.0)
        time.sleep(20)
except KeyboardInterrupt:
    bg.setEnabled(True)
    print('\nALBackgroundMovement re-enabled')
