#!/usr/bin/env python2
# Releve temperature + etat (0 normal, 1 alerte...) des moteurs qui chauffent.
# Sur le robot : PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages python2 temps.py
import qi, sys
s = qi.Session(); s.connect("tcp://127.0.0.1:9559")
m = s.service("ALMemory")
J = ["HeadPitch", "HipPitch", "KneePitch", "HipRoll"]
v = [(j, m.getData("Device/SubDeviceList/%s/Temperature/Sensor/Value" % j),
      m.getData("Device/SubDeviceList/%s/Temperature/Sensor/Status" % j)) for j in J]
sys.__stdout__.write(" ".join("%s=%dC(st%d)" % x for x in v) + (" COOL" if max(x[1] for x in v) <= 45 else "") + "\n")
