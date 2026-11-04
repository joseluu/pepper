#!/usr/bin/env python2
# -*- coding: utf-8 -*-
# Courant des moteurs dans la posture de 3PO, pour la regler au plus econome.
#   python2 courants.py            courant moyen par articulation (5 s), tel quel
#   python2 courants.py --sweep    balaie HeadPitch et HipPitch autour de STAND
#                                  (compagnon.py) et donne le courant de chacun
# compagnon.py doit etre arrete (systemctl --user stop compagnie3po).
import sys, time, argparse

sys.stdout = sys.stderr  # qi ecrit ses [W] sur stdout
import qi
from compagnon import STAND, ARMS

J = ["HeadYaw", "HeadPitch", "HipPitch", "HipRoll", "KneePitch",
     "LShoulderPitch", "RShoulderPitch", "LElbowRoll", "RElbowRoll"]
KEY = "Device/SubDeviceList/%s/ElectricCurrent/Sensor/Value"


def mean_current(mem, joints, seconds):
    keys = [KEY % j for j in joints]
    tot, n, t_end = [0.0] * len(keys), 0, time.time() + seconds
    while time.time() < t_end:
        tot = [a + abs(b) for a, b in zip(tot, mem.getListData(keys))]
        n += 1
        time.sleep(0.05)
    return [a / n for a in tot]


def out(line):
    sys.__stdout__.write(line + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--seconds", type=float, default=5.0)
    args = p.parse_args()
    s = qi.Session()
    s.connect("tcp://127.0.0.1:9559")
    mem, motion = s.service("ALMemory"), s.service("ALMotion")
    if not args.sweep:
        c = mean_current(mem, J, args.seconds)
        for j, a in zip(J, c):
            out("%-15s %.2f A" % (j, a))
        out("%-15s %.2f A" % ("total", sum(c)))
        return
    motion.wakeUp()
    names = sorted(STAND.keys())
    motion.angleInterpolation(names, [STAND[n] for n in names], [2.0] * len(names), True)
    motion.setStiffnesses(ARMS, 0.0)
    for joint, values in (("HeadPitch", [-0.30, -0.20, -0.10, 0.0, 0.10, 0.20]),
                          ("HipPitch", [-0.10, -0.06, -0.03, 0.0, 0.03])):
        for v in values:
            motion.angleInterpolation(joint, v, 1.0, True)
            time.sleep(1.0)
            a = mean_current(mem, [joint], 3.0)[0]
            out("%-10s %+.2f rad : %.2f A" % (joint, v, a))
        motion.angleInterpolation(joint, STAND[joint], 1.0, True)


if __name__ == "__main__":
    main()
