#!/usr/bin/env python2
"""Re-enable ALBackgroundMovement."""

import qi

session = qi.Session()
session.connect('tcp://127.0.0.1:9559')
bg = session.service('ALBackgroundMovement')
bg.setEnabled(True)
print('ALBackgroundMovement enabled')
