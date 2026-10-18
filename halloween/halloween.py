#!/usr/bin/env python2
# -*- coding: utf-8 -*-
# Pepper fantome d'Halloween.
#
# Attente : buste a demi penche, tete relachee, toutes LED eteintes, les doigts
# bougent un peu en permanence (petit mouvement pour le watchdog d'inactivite).
# Quelqu'un s'approche a moins de 1.5 m devant (lidars du pied) : LED rouges,
# il se redresse vite, leve les bras et joue le rire de Thriller. Puis il
# revient au repos et se re-arme.
#
# Lancement sur le robot :
#   PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages python2 halloween.py
# Options : --test (declenche une fois tout de suite), --volume N, --dist M,
#   --no-alarm, --alarm-tilt DEG, --alarm-debug, --alarm-siren S, --test-alarm (voir antivol.py)
import sys, os, time, math, argparse

sys.stdout = sys.stderr  # qi ecrit ses [W] sur stdout
import qi
import antivol

HERE = os.path.dirname(os.path.abspath(__file__))
SOUND = os.path.join(HERE, "thriller_laugh.wav")

# Posture d'attente : bras comme apres motion.rest(), buste un peu penche,
# genou = -hanche/2. Courant total hanche+genou+HipRoll, en arrivant depuis la
# position debout : -1.05/0.50 ~2.8 A, -0.50/0.25 1.84 A, -0.30/0.15 1.06 A,
# -0.20/0.10 0.69 A (hanche 0 A). La tete est ensuite relachee (stiffness 0) :
# elle reste en avant (~0.75) au lieu de chauffer le moteur du cou.
REST = {
    "HeadYaw": 0.0, "HeadPitch": 0.70,
    "HipRoll": 0.0, "HipPitch": -0.20, "KneePitch": 0.10,
    "LShoulderPitch": 1.12, "LShoulderRoll": 0.05, "LElbowYaw": -0.50,
    "LElbowRoll": -0.03, "LWristYaw": -0.78, "LHand": 0.60,
    "RShoulderPitch": 1.12, "RShoulderRoll": -0.05, "RElbowYaw": 0.50,
    "RElbowRoll": 0.03, "RWristYaw": 0.78, "RHand": 0.60,
}

# Debout, tete relevee, bras tendus par devant a 110 deg (20 deg au-dessus de
# l'horizontale : ShoulderPitch 0 = horizontal), paumes vers le sol (ElbowYaw
# et WristYaw a 0 = paumes en bas), mains ouvertes. Coudes un peu plies vers
# l'exterieur (ElbowRoll) et epaules un peu plus ecartees pour garder les
# mains devant : bras arrondis, moins rigides. Epaules ecartees de 30 deg
# (20 + 10 demandes en plus). Les *Roll bougent en 0.4 s,
# donc les coudes se plient pendant le debut de la montee (0.8 s).
SCARE = {
    "HeadYaw": 0.0, "HeadPitch": -0.30,
    "HipRoll": 0.0, "HipPitch": -0.03, "KneePitch": 0.0,
    "LShoulderPitch": -0.35, "LShoulderRoll": 0.52, "LElbowYaw": 0.0,
    "LElbowRoll": -0.45, "LWristYaw": 0.0, "LHand": 1.0,
    "RShoulderPitch": -0.35, "RShoulderRoll": -0.52, "RElbowYaw": 0.0,
    "RElbowRoll": 0.45, "RWristYaw": 0.0, "RHand": 1.0,
}
SHOULDER_PITCH = -0.35
ARM_WAVE = 0.087  # +/- 5 deg de ShoulderPitch, bras en opposition de phase
HIP_SWAY = 0.087  # +/- 5 deg de HipRoll pendant le rire

LASER_KEYS = []
for _i in range(1, 16):
    _k = "Device/SubDeviceList/Platform/LaserSensor/Front/Horizontal/Seg%02d/" % _i
    LASER_KEYS += [_k + "X/Sensor/Value", _k + "Y/Sensor/Value"]

MIN_DIST = 0.30      # en dessous : le drap ou le robot lui-meme, ignore
APPROACH = 0.30      # un segment doit s'etre rapproche d'au moins ca
MIN_SEGMENTS = 2     # nombre de segments concernes pour declencher
CONFIRM = 2          # lectures consecutives pour declencher
BASELINE_ALPHA = 0.02  # adaptation lente du fond (objets immobiles)


def log(msg):
    os.write(2, "%s %s\n" % (time.strftime("%H:%M:%S"), msg))


class Ghost(object):
    def __init__(self, session, args):
        self.args = args
        self.mem = session.service("ALMemory")
        self.motion = session.service("ALMotion")
        self.leds = session.service("ALLeds")
        self.player = session.service("ALAudioPlayer")
        self.tts = session.service("ALTextToSpeech")
        self.audio = session.service("ALAudioDevice")
        self.session = session
        self.baseline = None
        self.hits = 0
        self.finger_up = False
        self.last_finger = 0.0
        self.last_check = 0.0
        self.alarm = None

    def _svc(self, name):
        try:
            return self.session.service(name)
        except Exception:
            return None

    def quiet_autonomy(self):
        """Coupe tout ce qui bouge ou allume des LED tout seul."""
        life = self._svc("ALAutonomousLife")
        if life and life.getState() != "disabled":
            life.setState("disabled")
        for name in ("ALBackgroundMovement", "ALAutonomousBlinking",
                     "ALListeningMovement", "ALSpeakingMovement"):
            s = self._svc(name)
            try:
                if s and s.isEnabled():
                    s.setEnabled(False)
            except Exception as e:
                log("%s: %s" % (name, e))
        ba = self._svc("ALBasicAwareness")
        try:
            if ba and ba.isEnabled():
                ba.setEnabled(False)
        except Exception as e:
            log("ALBasicAwareness: %s" % e)

    def leds_off(self):
        self.leds.fadeRGB("AllLeds", 0x000000, 0.3)
        self.leds.fadeRGB("ChestLeds", 0x000000, 0.0)

    def leds_red(self):
        # yeux + torse en rouge (les oreilles n'ont que des LED bleues)
        for g in ("FaceLeds", "ChestLeds"):
            self.leds.fadeRGB(g, 0xFF0000, 0.0)

    def move(self, pose, duration):
        names = sorted(pose.keys())
        self.motion.angleInterpolation(names, [pose[n] for n in names],
                                       [duration] * len(names), True)

    def go_rest(self, duration=3.0):
        if not self.motion.robotIsWakeUp():
            self.motion.wakeUp()
        self.motion.setStiffnesses("Head", 1.0)
        self.move(REST, duration)
        self.motion.setStiffnesses("Head", 0.0)
        # HipRoll n'atteint pas 0 (reste vers -0.04) et force en permanence :
        # 0.8 A et +1.5 C/min. Consigne = position reelle -> 0.2 A.
        time.sleep(1.0)
        self.motion.setAngles("HipRoll", self.motion.getAngles("HipRoll", True)[0], 0.05)
        self.leds_off()

    def wiggle_fingers(self):
        now = time.time()
        if now - self.last_finger < 2.0:
            return
        self.last_finger = now
        self.finger_up = not self.finger_up
        v = 0.70 if self.finger_up else 0.50
        self.motion.setAngles(["LHand", "RHand"], [v, 1.2 - v], 0.08)

    def distances(self):
        v = self.mem.getListData(LASER_KEYS)
        return [math.hypot(v[2 * i], v[2 * i + 1]) for i in range(15)]

    def detect(self):
        d = self.distances()
        if self.baseline is None:
            self.baseline = d
            return False
        close = [i for i in range(15)
                 if MIN_DIST < d[i] < self.args.dist
                 and d[i] < self.baseline[i] - APPROACH]
        self.hits = self.hits + 1 if len(close) >= MIN_SEGMENTS else 0
        if self.hits >= CONFIRM:
            log("detection: segments %s, dist %s" % (
                close, ["%.2f" % d[i] for i in close]))
            self.hits = 0
            return True
        a = BASELINE_ALPHA
        self.baseline = [b * (1 - a) + x * a for b, x in zip(self.baseline, d)]
        return False

    def scare(self):
        log("BOUH !")
        if self.alarm:
            self.alarm.reset_peaks()  # pour calibrer : ce que le BOUH secoue
        self.motion.setStiffnesses("Head", 1.0)
        self.leds_red()
        old_vol = self.audio.getOutputVolume()
        self.audio.setOutputVolume(self.args.volume)
        play = self.player.playFile(SOUND, 1.0, 0.0, _async=True)
        names = sorted(SCARE.keys())
        self.motion.angleInterpolation(
            names, [SCARE[n] for n in names],
            [0.4 if "Roll" in n else 0.8 for n in names], True)
        # balancement des hanches (+/- 5 deg), bras qui montent et descendent
        # (+/- 5 deg) en opposition de phase
        t_end = time.time() + 11.0
        k = 0
        while time.time() < t_end:
            k += 1
            sign = 1 if k % 2 else -1
            self.motion.setAngles(
                ["HipRoll", "LShoulderPitch", "RShoulderPitch"],
                [sign * HIP_SWAY, SHOULDER_PITCH + ARM_WAVE * sign,
                 SHOULDER_PITCH - ARM_WAVE * sign], 0.10)
            time.sleep(0.9)
        self.motion.setAngles("HipRoll", 0.0, 0.10)
        play.wait()
        if not self.alarm_active():
            # voix grave (vct) et lente (rspd), en pourcentage de la normale
            self.tts.setLanguage("English")
            self.tts.say("\\vct=60\\ \\rspd=75\\ " + self.args.phrase)
            self.audio.setOutputVolume(old_vol)
        self.go_rest(3.0)
        if self.alarm:
            p = self.alarm.peaks
            log("secousse du BOUH (base) : inclinaison %.1f deg, ecart acc %.2f, "
                "gyro %.2f" % (math.degrees(p[0]), p[1], p[2]))
        time.sleep(self.args.cooldown)
        self.baseline = None  # le fond peut avoir change (gens, drap)

    def alarm_active(self):
        return self.alarm is not None and self.alarm.active

    def run(self):
        self.quiet_autonomy()
        self.go_rest()
        log("fantome en place (seuil %.2f m)" % self.args.dist)
        if self.args.test:
            time.sleep(2)
            self.scare()
            return
        if not self.args.no_alarm:
            self.alarm = antivol.TheftAlarm(self.session, self.args.alarm_tilt,
                                            debug=self.args.alarm_debug,
                                            siren_max=self.args.alarm_siren)
            self.alarm.start()
        while True:
            if self.alarm_active():   # sirene : le fantome ne fait plus rien
                time.sleep(0.5)
                self.baseline = None
                continue
            now = time.time()
            if now - self.last_check > 30:
                self.last_check = now
                self.quiet_autonomy()  # le timer keepawake les reactive
                self.leds_off()  # les epaules clignotent sur les alertes
                if not self.motion.robotIsWakeUp():
                    log("robot passe au repos, je le reveille")
                    self.go_rest()
            if self.detect():
                self.scare()
            else:
                self.wiggle_fingers()
            time.sleep(0.1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--test", action="store_true", help="declenche une fois")
    p.add_argument("--volume", type=int, default=85)
    p.add_argument("--dist", type=float, default=1.5)
    p.add_argument("--cooldown", type=float, default=5.0)
    p.add_argument("--phrase", default="Trick or treat!")
    p.add_argument("--no-alarm", action="store_true", help="sans anti-vol")
    p.add_argument("--alarm-tilt", type=float, default=8.0,
                   help="inclinaison (deg) qui declenche la sirene")
    p.add_argument("--alarm-debug", action="store_true",
                   help="journalise les ecarts max de la centrale toutes les 10 s")
    p.add_argument("--alarm-siren", type=float, default=0.0,
                   help="tests : coupe la sirene apres tant de s (0 = continue)")
    p.add_argument("--test-alarm", action="store_true",
                   help="joue la sirene 5 s (gyrophare compris) et quitte")
    args = p.parse_args()
    s = qi.Session()
    s.connect("tcp://127.0.0.1:9559")
    if args.test_alarm:
        a = antivol.TheftAlarm(s)
        old = a.audio.getOutputVolume()
        a.start_siren("test")
        for i in range(10):
            a.leds.fadeRGB("FaceLeds", 0xFF0000 if i % 2 else 0x0000FF, 0.0)
            time.sleep(0.5)
        a.stop_siren()
        a.audio.setOutputVolume(old)
        return
    g = Ghost(s, args)
    try:
        g.run()
    except KeyboardInterrupt:
        log("arret")
        g.leds.fadeRGB("AllLeds", 0xFFFFFF, 0.5)


if __name__ == "__main__":
    main()
