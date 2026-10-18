# -*- coding: utf-8 -*-
# Enregistre la centrale inertielle de la base a 20 Hz dans un CSV
# + vitesse des roues et pare-chocs (pour regler l'anti-vol). Usage : python2 record_imu.py fichier.csv secondes
import sys, time, qi
import antivol

s = qi.Session()
s.connect("tcp://127.0.0.1:9559")
mem = s.service("ALMemory")
EXTRA = ["Device/SubDeviceList/%s/Speed/Sensor/Value" % w
         for w in ("WheelFL", "WheelFR", "WheelB")] + \
        ["Device/SubDeviceList/Platform/%s/Bumper/Sensor/Value" % b
         for b in ("FrontLeft", "FrontRight", "Back")]
out = open(sys.argv[1], "w")
out.write("t,angx,angy,accx,accy,accz,gyrx,gyry,gyrz,wfl,wfr,wb,bfl,bfr,bb\n")
t0 = time.time()
while time.time() - t0 < float(sys.argv[2]):
    v = mem.getListData(antivol.KEYS[:8] + EXTRA)
    out.write("%.2f,%s\n" % (time.time() - t0, ",".join("%.4f" % x for x in v)))
    time.sleep(0.05)
out.close()
