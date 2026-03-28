#!/usr/bin/env python2
"""Pepper hug pose: arms extended for embrace, then return to rest."""

import qi
import time

session = qi.Session()
session.connect('tcp://127.0.0.1:9559')
motion = session.service('ALMotion')

# Disable ALBackgroundMovement to prevent interference
bg = session.service('ALBackgroundMovement')
bg.setEnabled(False)
print('ALBackgroundMovement disabled')

motion.wakeUp()
time.sleep(1)
motion.setStiffnesses('Body', 1.0)

# Hug pose based on sensor readings from manually positioned arm
# LWristYaw rotates the hand inward for embrace
names = [
    'LShoulderPitch', 'LShoulderRoll', 'LElbowYaw', 'LElbowRoll', 'LWristYaw',
    'RShoulderPitch', 'RShoulderRoll', 'RElbowYaw', 'RElbowRoll', 'RWristYaw',
    'LHand', 'RHand',
]
angles = [
    0.36,   # LShoulderPitch: from memmer sensor
    0.58,   # LShoulderRoll: from memmer sensor
    -0.48,  # LElbowYaw: from memmer sensor
    -1.00,  # LElbowRoll: closing more
    -1.80,  # LWristYaw: hand rotated inward
    0.36,   # RShoulderPitch: mirrored
    -0.58,  # RShoulderRoll: mirrored
    0.48,   # RElbowYaw: mirrored
    1.00,   # RElbowRoll: mirrored
    1.80,   # RWristYaw: mirrored
    0.71,   # LHand: from memmer sensor
    0.71,   # RHand: mirrored
]

print('Moving to hug pose...')
motion.setAngles(names, angles, 0.15)
time.sleep(3)

# Arm joint names and targets (exclude hands)
arm_names = names[:10]
arm_targets = angles[:10]
TOLERANCE = 0.15

print('Finger animation started (Ctrl+C to stop)')
try:
    while True:
        # Check arm positions and correct any drift
        for i, jname in enumerate(arm_names):
            actual = motion.getAngles(jname, True)[0]
            error = arm_targets[i] - actual
            if abs(error) > TOLERANCE:
                corrected = arm_targets[i] + error / 10.0
                print('MISMATCH %s: target=%.2f actual=%.2f sending=%.2f' % (jname, arm_targets[i], actual, corrected))
                motion.setAngles(jname, corrected, 0.3)
        motion.setAngles(['LHand'], [0.2], 0.5)
        motion.setAngles(['RHand'], [0.8], 0.5)
        time.sleep(1)
        motion.setAngles(['LHand'], [0.8], 0.5)
        motion.setAngles(['RHand'], [0.2], 0.5)
        time.sleep(1)
except KeyboardInterrupt:
    pass

print('')

# Return arms along the body
rest_names = [
    'LShoulderPitch', 'LShoulderRoll', 'LElbowYaw', 'LElbowRoll', 'LWristYaw',
    'RShoulderPitch', 'RShoulderRoll', 'RElbowYaw', 'RElbowRoll', 'RWristYaw',
    'LHand', 'RHand',
]
rest_angles = [
    1.5,   # LShoulderPitch: arm down
    0.15,  # LShoulderRoll: close to body
    -1.2,  # LElbowYaw: natural resting
    -0.05, # LElbowRoll: straight
    0.0,   # LWristYaw: neutral
    1.5,   # RShoulderPitch: arm down
    -0.15, # RShoulderRoll: close to body
    1.2,   # RElbowYaw: natural resting
    0.05,  # RElbowRoll: straight
    0.0,   # RWristYaw: neutral
    0.5,   # LHand: relaxed
    0.5,   # RHand: relaxed
]

print('Returning arms to rest position...')
motion.setAngles(rest_names, rest_angles, 0.15)
time.sleep(4)

# Re-enable ALBackgroundMovement
bg.setEnabled(True)
print('ALBackgroundMovement re-enabled')
print('Done.')
