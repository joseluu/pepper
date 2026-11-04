#!/usr/bin/env python2
# -*- coding: utf-8 -*-
# Esprit de compagnie 3PO (derive du fantome d'Halloween, sans BOUH ni lidar).
#
# En pause : debout, droit, dans la posture qui fait le moins travailler les
# moteurs (hanches et genoux a la verticale, bras relaches le long du corps,
# seule la tete est tenue), LED eteintes, les doigts bougent un peu (watchdog
# d'inactivite de NAOqi).
# La telecommande (web3po.py, bouton "Ecoute") le rend attentif : petit chirp
# de 0,3 s, yeux bleu pale, et live3po.py (sur tram, Gemini Live) ecoute la
# conversation. Il se remet en pause sur "merci" / "merci 3PO", sur le bouton
# "Pause", ou de lui-meme apres 60 s sans interaction ("L'esprit de compagnie
# 3PO en pause") : c'est live3po.py qui decide et termine la session.
#
# Echange avec le pont audio (dialogue/robot_audio.py --prefix 3PO) par
# ALMemory, meme protocole que le fantome : 3PO/Dialogue "idle" -> "prepare"
# -> "talk" (ecrits ici) -> "active" (pont) -> "idle" (fin), ou "abort" (ici).
#
# Lancement sur le robot :
#   PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages python2 compagnon.py
# Options : --volume N, --no-alarm, --alarm-tilt DEG (anti-vol, voir
#   ../halloween/antivol.py), --listen-max S
import sys, os, time, argparse

sys.stdout = sys.stderr  # qi ecrit ses [W] sur stdout
import qi

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "halloween"))   # antivol.py, partage
import antivol

CHIRP = os.path.join(HERE, "chirp.wav")

# Debout droit, au plus econome (courants.py, 2026-11-04) : bras poses le long
# du corps puis relaches (0,8 A -> 0) ; tete un peu baissee, a +0,10 rad
# (6 deg) : 0 A, contre 0,17 A a -0,10 et 0,26 A a 0 ; hanches et genoux
# droits, puis consigne = position reelle (le genou reste vers 0,05) :
# jambes 2,3 -> 1,9 A. Se pencher (-0,20/0,10 comme le fantome) coute a peine
# moins (~2,0 A mesure juste apres le mouvement) et n'est plus "droit".
STAND = {
    "HeadYaw": 0.0, "HeadPitch": 0.10,
    "HipRoll": 0.0, "HipPitch": -0.03, "KneePitch": 0.0,
    "LShoulderPitch": 1.55, "LShoulderRoll": 0.10, "LElbowYaw": -1.20,
    "LElbowRoll": -0.10, "LWristYaw": 0.0, "LHand": 0.60,
    "RShoulderPitch": 1.55, "RShoulderRoll": -0.10, "RElbowYaw": 1.20,
    "RElbowRoll": 0.10, "RWristYaw": 0.0, "RHand": 0.60,
}


def relax_arms(motion):
    """Bras sans courant, mains tenues (doigts qui bougent). Par chaine : une
    liste d'articulations avec une seule valeur est ignoree sans erreur."""
    for chain in ("LArm", "RArm"):
        motion.setStiffnesses(chain, 0.0)
    for hand in ("LHand", "RHand"):
        motion.setStiffnesses(hand, 1.0)

HELD = ["HipPitch", "KneePitch", "HipRoll", "HeadPitch", "HeadYaw"]
EYES_LISTEN = 0x002040           # bleu pale : 3PO ecoute

DIALOGUE = "3PO/Dialogue"
DIALOGUE_PC = "3PO/DialoguePC"
DIALOGUE_MODE = "3PO/DialogueMode"
ALIVE = "3PO/Ghost"              # battement (lu par le pont audio et web3po.py)
STATE = "3PO/State"              # "pause" ou "ecoute" (lu par web3po.py)
# Boutons de web3po.py : [ordre, heure]. Ordres : "ecoute", "pause", "droit".
COMMAND = "3PO/Command"
COMMAND_ACK = "3PO/CommandAck"
COMMAND_MAX_AGE = 15             # s : un ordre plus vieux est ignore


def log(msg):
    os.write(2, "%s %s\n" % (time.strftime("%H:%M:%S"), msg))


class Companion(object):
    def __init__(self, session, args):
        self.args = args
        self.session = session
        self.mem = session.service("ALMemory")
        self.motion = session.service("ALMotion")
        self.leds = session.service("ALLeds")
        self.player = session.service("ALAudioPlayer")
        self.audio = session.service("ALAudioDevice")
        self.alarm = None
        self.listening = False
        self.finger_up = False
        self.last_finger = 0.0
        self.last_check = 0.0
        self.last_beat = 0.0
        cmd = self._get(COMMAND)
        self.last_cmd = cmd[1] if cmd else 0   # pas d'ordre d'avant le demarrage

    def _get(self, key):
        try:
            return self.mem.getData(key)
        except Exception:
            return None

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
                     "ALListeningMovement", "ALSpeakingMovement", "ALBasicAwareness"):
            s = self._svc(name)
            try:
                if s and s.isEnabled():
                    s.setEnabled(False)
            except Exception as e:
                log("%s: %s" % (name, e))

    def take_command(self):
        """Ordre web nouveau et recent, sinon None."""
        cmd = self._get(COMMAND)
        if not cmd or cmd[1] <= self.last_cmd:
            return None
        self.last_cmd = cmd[1]
        if time.time() - cmd[1] > COMMAND_MAX_AGE:
            return None
        log("ordre web : %s" % cmd[0])
        self.mem.insertData(COMMAND_ACK, [cmd[0], int(time.time())])
        return cmd[0]

    def eyes(self):
        self.leds.fadeRGB("AllLeds", 0x000000, 0.3)
        if self.listening:
            self.leds.fadeRGB("FaceLeds", EYES_LISTEN, 0.3)

    def stand(self, duration=2.0):
        """Posture droite economique (pause et ecoute)."""
        if not self.motion.robotIsWakeUp():
            self.motion.wakeUp()
        self.motion.setStiffnesses("Body", 1.0)
        names = sorted(STAND.keys())
        self.motion.angleInterpolation(names, [STAND[n] for n in names],
                                       [duration] * len(names), True)
        time.sleep(0.5)
        relax_arms(self.motion)                 # bras pendants, sans courant
        self.settle()
        self.eyes()

    def settle(self):
        """Consigne = position reelle : le moteur ne force plus pour atteindre
        une consigne qu'il n'atteint pas (cf. HipRoll dans halloween.py)."""
        for j in HELD:
            self.motion.setAngles(j, self.motion.getAngles(j, True)[0], 0.05)

    def head_home(self):
        """Fin d'ecoute : la tete, qui suivait la voix, revient a sa place."""
        self.motion.angleInterpolation(["HeadYaw", "HeadPitch"],
                                       [STAND["HeadYaw"], STAND["HeadPitch"]], 1.0, True)
        self.settle()

    def wiggle_fingers(self):
        now = time.time()
        if now - self.last_finger < 2.0:
            return
        self.last_finger = now
        self.finger_up = not self.finger_up
        v = 0.70 if self.finger_up else 0.50
        self.motion.setAngles(["LHand", "RHand"], [v, 1.2 - v], 0.08)

    def beat(self):
        now = time.time()
        if now - self.last_beat > 1:
            self.last_beat = now
            self.mem.insertData(ALIVE, int(now))

    def dialogue_ready(self):
        return bool(self._get(DIALOGUE_PC))

    def alarm_active(self):
        return self.alarm is not None and self.alarm.active

    def listen(self):
        """Attention active jusqu'a la pause (merci, bouton, 60 s de calme)."""
        if not self.dialogue_ready():
            log("ecoute impossible : tram n'est pas connecte au pont audio")
            return
        log("attentif")
        self.listening = True
        self.mem.insertData(STATE, "ecoute")
        self.eyes()
        self.player.playFile(CHIRP, self.args.chirp_volume, 0.0, _async=True)
        self.mem.insertData(DIALOGUE_MODE, "3po")
        self.mem.insertData(DIALOGUE, "prepare")
        self.mem.insertData(DIALOGUE, "talk")
        t0 = time.time()
        time.sleep(0.3)        # le pont lit 3PO/Dialogue tous les 100 ms
        while True:
            state = self.mem.getData(DIALOGUE)
            if state == "idle":
                break
            now = time.time()
            if state == "talk" and now - t0 > 5:
                log("le pont audio ne repond pas")
                self.mem.insertData(DIALOGUE, "idle")
                break
            cmd = self.take_command()
            if cmd == "droit":
                self.stand(2.0)
            elif cmd == "pause" or self.alarm_active() \
                    or now - t0 > self.args.listen_max:
                log("pause demandee" if cmd else "ecoute interrompue")
                self.mem.insertData(DIALOGUE, "abort")
                t1 = time.time()   # le pont audio repasse a "idle"
                while self.mem.getData(DIALOGUE) != "idle" and time.time() - t1 < 3:
                    time.sleep(0.1)
                break
            self.mem.insertData(ALIVE, int(now))
            self.wiggle_fingers()
            time.sleep(0.2)
        self.listening = False
        self.mem.insertData(STATE, "pause")
        self.eyes()
        self.head_home()
        log("en pause (%.0f s d'ecoute)" % (time.time() - t0))

    def run(self):
        self.quiet_autonomy()
        self.mem.insertData(STATE, "pause")
        self.stand(3.0)
        self.audio.setOutputVolume(self.args.volume)
        log("3PO en pause, pret (volume %d)" % self.args.volume)
        if not self.args.no_alarm:
            self.alarm = antivol.TheftAlarm(self.session, self.args.alarm_tilt)
            self.alarm.start()
        while True:
            if self.alarm_active():    # sirene : 3PO ne fait plus rien
                self.mem.insertData(ALIVE, int(time.time()))
                time.sleep(0.5)
                continue
            self.beat()
            now = time.time()
            if now - self.last_check > 30:
                self.last_check = now
                self.quiet_autonomy()  # le timer keepawake les reactive
                self.eyes()            # les epaules clignotent sur les alertes
                if not self.motion.robotIsWakeUp():
                    log("robot passe au repos, je le redresse")
                    self.stand()
            cmd = self.take_command()
            if cmd == "ecoute":
                self.listen()
            elif cmd == "droit":
                self.stand(2.0)
            else:                      # "pause" : deja en pause
                self.wiggle_fingers()
            time.sleep(0.1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--volume", type=int, default=70, help="volume de la voix (0-100)")
    p.add_argument("--chirp-volume", type=float, default=0.5,
                   help="volume du chirp d'attention (0-1, sur le volume general)")
    p.add_argument("--listen-max", type=float, default=3600.0,
                   help="duree max d'une ecoute (s), filet de securite")
    p.add_argument("--no-alarm", action="store_true", help="sans anti-vol")
    p.add_argument("--alarm-tilt", type=float, default=8.0,
                   help="inclinaison (deg) qui declenche la sirene")
    args = p.parse_args()
    s = qi.Session()
    s.connect("tcp://127.0.0.1:9559")
    c = Companion(s, args)
    try:
        c.run()
    except KeyboardInterrupt:
        log("arret")


if __name__ == "__main__":
    main()
