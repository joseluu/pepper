#!/usr/bin/env python2
# -*- coding: utf-8 -*-
# Attend que NAOqi et les services du fantome repondent (demarrage du robot :
# NAOqi met plusieurs minutes). Utilise par les services systemd du dossier
# systemd/ (ExecStartPre).
import sys, time

sys.stdout = sys.stderr  # qi ecrit ses [W] sur stdout
import qi

SERVICES = ("ALMemory", "ALMotion", "ALLeds", "ALAudioPlayer", "ALAudioDevice",
            "ALAutonomousLife")

t0 = time.time()
while True:
    try:
        s = qi.Session()
        s.connect("tcp://127.0.0.1:9559")
        for name in SERVICES:
            s.service(name)
        break
    except Exception:
        time.sleep(5)
print("NAOqi pret apres %.0f s" % (time.time() - t0))
time.sleep(10)   # laisser NAOqi finir son demarrage (posture, vie autonome)
