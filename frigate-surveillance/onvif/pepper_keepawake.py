#!/usr/bin/env python2
# Periodic Pepper state check: wake the robot if it has gone to rest and make
# sure ALBackgroundMovement is on (prevents NAOqi's idle rest timer).
# Run from a systemd timer (every 6h). Logs one line to /data/onvif/keepawake.log
import sys, os, time

# qi prints [W] log lines to stdout; keep our log clean by sending qi noise to stderr
sys.stdout = sys.stderr
import qi

LOG = "/data/onvif/keepawake.log"

def log(msg):
    line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        f = open(LOG, "a")
        f.write(line)
        f.close()
    except Exception:
        pass
    os.write(2, line)

def main():
    s = qi.Session()
    s.connect("tcp://127.0.0.1:9559")
    motion = s.service("ALMotion")
    awake = motion.robotIsWakeUp()
    action = "already awake"
    if not awake:
        motion.wakeUp()
        action = "was asleep -> wakeUp()"
    try:
        bg = s.service("ALBackgroundMovement")
        if not bg.isEnabled():
            bg.setEnabled(True)
            action += " + bgMovement re-enabled"
    except Exception as e:
        action += " (bgMovement err: %s)" % e
    log("check: %s ; awake_now=%s" % (action, motion.robotIsWakeUp()))

if __name__ == "__main__":
    main()
