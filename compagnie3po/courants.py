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
from compagnon import STAND, relax_arms

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
    relax_arms(motion)
    for v in (-0.30, -0.20, -0.10, 0.0, 0.10):
        motion.angleInterpolation("HeadPitch", v, 1.0, True)
        time.sleep(1.0)
        out("HeadPitch %+.2f : %.2f A" % (v, mean_current(mem, ["HeadPitch"], 3.0)[0]))
    motion.angleInterpolation("HeadPitch", STAND["HeadPitch"], 1.0, True)
    # buste : genou = -hanche/2 (le buste reste au-dessus des roues)
    legs = ["HipPitch", "KneePitch", "HipRoll"]
    for hip in (0.03, 0.0, -0.03, -0.06, -0.10, -0.15, -0.20):
        motion.angleInterpolation(["HipPitch", "KneePitch"], [hip, -hip / 2], 1.5, True)
        motion.setAngles("HipRoll", motion.getAngles("HipRoll", True)[0], 0.05)
        time.sleep(1.5)
        c = mean_current(mem, legs, 3.0)
        out("HipPitch %+.2f KneePitch %+.3f : hanche %.2f genou %.2f roll %.2f"
            " total %.2f A" % (hip, -hip / 2, c[0], c[1], c[2], sum(c)))
    motion.angleInterpolation(["HipPitch", "KneePitch"],
                              [STAND["HipPitch"], STAND["KneePitch"]], 1.5, True)


if __name__ == "__main__":
    main()
