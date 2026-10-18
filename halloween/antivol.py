# -*- coding: utf-8 -*-
# Alarme anti-vol du fantome : si on emporte le robot (il faut monter un
# escalier de 10 marches, donc le pencher, le soulever, le tourner), sirene
# de police continue jusqu'au desarmement manuel.
#
# Capteur : centrale inertielle de la BASE (celle du torse est en panne).
# Bruit mesure au repos (2026-10-18) : angles +/- 0.003 rad, accelero
# +/- 0.2 m/s2, gyro +/- 0.02 rad/s. AngleY de repos ~ -0.026 (sol en pente).
#
# Rouler le robot au sol (seuil de porte, poussee rapide) fait tourner les
# roues : mesure 2026-10-18, roues 2 a 17, inclinaison jusqu'a 13 deg et ecart
# |acc| jusqu'a 9 m/s2 pendant ces manipulations. Tant que les roues tournent
# (et WHEEL_GRACE s apres), rien ne declenche. Porte dans l'escalier, le robot
# ne touche plus le sol : roues immobiles.
#
# Porte (meme "a plat") : mesure 2026-10-18, roues a 0 sauf a la prise et a
# la pose, mais rotation 3 axes 0.5 a 1.7 rad/s pendant tout le portage et
# inclinaison 6 a 12 deg. Au sol, le robot ne peut pas tourner sans que ses
# roues tournent : rotation sans roues = porte.
#
# Desarmer : ssh pepper 'touch ~/halloween/desarme'  (la sirene s'arrete,
# l'alarme se re-arme 30 s plus tard avec une nouvelle reference)
import os, time, math, threading

HERE = os.path.dirname(os.path.abspath(__file__))
SIREN = os.path.join(HERE, "siren.wav")
DISARM_FILE = os.path.join(HERE, "desarme")

IMU = "Device/SubDeviceList/InertialSensorBase/%s/Sensor/Value"
KEYS = [IMU % k for k in ("AngleX", "AngleY",
                          "AccelerometerX", "AccelerometerY", "AccelerometerZ",
                          "GyroscopeX", "GyroscopeY", "GyroscopeZ")] + \
       ["Device/SubDeviceList/%s/Speed/Sensor/Value" % w
        for w in ("WheelFL", "WheelFR", "WheelB")]

RATE = 20.0          # lectures par seconde
TILT_HOLD = 1.0      # s d'inclinaison continue pour declencher
SHOCK_ACC = 2.5      # m/s2 d'ecart a la pesanteur de reference
SHOCK_COUNT = 4      # ... sur au moins tant de lectures dans la derniere seconde
GYRO_MAX = 0.5       # rad/s de rotation ...
GYRO_HOLD = 0.5      # ... continue pendant tant de secondes
WHEEL_MIN = 0.5      # vitesse de roue (|.|) : le robot roule au sol ...
WHEEL_GRACE = 2.0    # ... et pendant tant de s apres, rien ne declenche
AIR_GYRO = 0.4       # rotation 3 axes moyenne (rad/s) sur AIR_HOLD s ...
AIR_HOLD = 1.0       # ... roues immobiles tout ce temps : il est porte
REARM_DELAY = 30.0   # s apres desarmement avant de re-armer
TEST_PAUSE = 3.0     # mode test (siren_max) : pause apres la sirene courte


def _log(msg):
    os.write(2, "%s [antivol] %s\n" % (time.strftime("%H:%M:%S"), msg))


class TheftAlarm(object):
    def __init__(self, session, tilt_deg=8.0, volume=100, debug=False,
                 siren_max=0.0):
        self.mem = session.service("ALMemory")
        self.player = session.service("ALAudioPlayer")
        self.audio = session.service("ALAudioDevice")
        self.leds = session.service("ALLeds")
        self.tilt = math.radians(tilt_deg)
        self.volume = volume
        self.debug = debug
        self.siren_max = siren_max   # > 0 : sirene coupee seule apres tant de s (tests)
        self.siren_t0 = 0.0
        self.active = False       # sirene en cours
        self.ref = None
        self.peaks = None         # ecarts max depuis le dernier reset_peaks()
        self._stop = False
        self._thread = None

    # -- mesure ------------------------------------------------------------
    def read(self):
        v = self.mem.getListData(KEYS)
        acc = math.sqrt(v[2] ** 2 + v[3] ** 2 + v[4] ** 2)
        # gyro X/Y seulement (basculement) : rouler et pivoter au sol (Z) est permis
        gyro = math.sqrt(v[5] ** 2 + v[6] ** 2)
        gyro3 = math.sqrt(v[5] ** 2 + v[6] ** 2 + v[7] ** 2)
        wheel = max(abs(v[8]), abs(v[9]), abs(v[10]))
        return v[0], v[1], acc, gyro, wheel, gyro3

    def calibrate(self, seconds=2.0):
        n, sx, sy, sa = 0, 0.0, 0.0, 0.0
        t_end = time.time() + seconds
        while time.time() < t_end:
            ax, ay, acc = self.read()[:3]
            n += 1; sx += ax; sy += ay; sa += acc
            time.sleep(1.0 / RATE)
        self.ref = (sx / n, sy / n, sa / n)
        _log("reference : AngleX %.3f AngleY %.3f |acc| %.2f" % self.ref)

    def reset_peaks(self):
        self.peaks = [0.0, 0.0, 0.0, 0.0]   # inclinaison, ecart |acc|, gyro, roues

    # -- sirene --------------------------------------------------------------
    def start_siren(self, reason):
        if self.active:
            return
        self.active = True
        self.siren_t0 = time.time()
        self._state("sirene", reason)
        _log("ALARME : %s" % reason)
        self.player.stopAll()
        self.audio.setOutputVolume(self.volume)
        try:
            self.player.playFileInLoop(SIREN, _async=True)
        except Exception:
            # repli : relance le fichier en boucle dans ce fil
            threading.Thread(target=self._loop_siren).start()

    def _loop_siren(self):
        while self.active and not self._stop:
            self.player.playFile(SIREN)

    def _state(self, state, detail=""):
        # lu par web.py (page d'etat)
        try:
            self.mem.insertData("Halloween/Alarm", [state, detail, int(time.time())])
        except Exception:
            pass

    def stop_siren(self, why="desarmement"):
        self.active = False
        self._state("rearmement" if why == "desarmement" else "armee", why)
        self.player.stopAll()
        self.leds.fadeRGB("AllLeds", 0x000000, 0.0)
        _log("sirene arretee (%s)" % why)

    # -- boucle de surveillance ---------------------------------------------
    def start(self):
        self.calibrate()
        self.reset_peaks()
        self._thread = threading.Thread(target=self._run)
        self._thread.daemon = True
        self._thread.start()
        self._state("armee")
        _log("armee (inclinaison %.0f deg, choc %.1f m/s2, rotation %.1f rad/s, "
             "porte %.1f rad/s sans roues)"
             % (math.degrees(self.tilt), SHOCK_ACC, GYRO_MAX, AIR_GYRO))

    def stop(self):
        self._stop = True

    def _run(self):
        tilt_since = gyro_since = None
        shocks = []          # instants des lectures "choc"
        air = []             # (instant, rotation 3 axes, roues) sur AIR_HOLD s
        rolled = 0.0         # dernier instant ou les roues tournaient
        last_debug = time.time()
        flash = False
        while not self._stop:
            now = time.time()
            if self.active:
                flash = not flash   # gyrophare : yeux/epaules rouge/bleu
                c = 0xFF0000 if flash else 0x0000FF
                self.leds.fadeRGB("FaceLeds", c, 0.0)
                self.leds.fadeRGB("ChestLeds", c, 0.0)
                if os.path.exists(DISARM_FILE):
                    os.remove(DISARM_FILE)
                    self.stop_siren()
                    _log("re-armement dans %.0f s" % REARM_DELAY)
                    time.sleep(REARM_DELAY)
                    self.calibrate()
                    self._state("armee")
                    tilt_since = gyro_since = None
                    shocks = []
                elif self.siren_max and now - self.siren_t0 >= self.siren_max:
                    # mode test : coupe seule, garde la reference d'origine
                    self.stop_siren("mode test, %.1f s" % self.siren_max)
                    time.sleep(TEST_PAUSE)
                    tilt_since = gyro_since = None
                    shocks = []
                    continue
                time.sleep(0.25)
                continue
            if os.path.exists(DISARM_FILE):   # fichier oublie : sans effet
                os.remove(DISARM_FILE)
            ax, ay, acc, gyro, wheel, gyro3 = self.read()
            tilt = max(abs(ax - self.ref[0]), abs(ay - self.ref[1]))
            dacc = abs(acc - self.ref[2])
            p = self.peaks
            p[0], p[1], p[2] = max(p[0], tilt), max(p[1], dacc), max(p[2], gyro)
            p[3] = max(p[3], wheel)
            if wheel > WHEEL_MIN:
                rolled = now
            # la rotation oscille au rythme des pas : moyenne sur la fenetre
            air.append((now, gyro3, wheel))
            air = [a for a in air if now - a[0] <= AIR_HOLD]
            mean = sum(a[1] for a in air) / len(air)
            if (now - air[0][0] >= 0.9 * AIR_HOLD and mean > AIR_GYRO
                    and max(a[2] for a in air) < WHEEL_MIN):
                self.start_siren("rotation %.2f rad/s sans les roues (porte)" % mean)
                air = []
                time.sleep(1.0 / RATE)
                continue
            if now - rolled < WHEEL_GRACE:   # au sol, on le fait rouler
                tilt_since = gyro_since = None
                shocks = []
                time.sleep(1.0 / RATE)
                continue

            tilt_since = (tilt_since or now) if tilt > self.tilt else None
            gyro_since = (gyro_since or now) if gyro > GYRO_MAX else None
            if dacc > SHOCK_ACC:
                shocks.append(now)
            shocks = [t for t in shocks if now - t < 1.0]

            if tilt_since and now - tilt_since >= TILT_HOLD:
                self.start_siren("inclinaison %.1f deg" % math.degrees(tilt))
            elif len(shocks) >= SHOCK_COUNT:
                self.start_siren("secousses (|acc| ecart %.1f m/s2)" % dacc)
            elif gyro_since and now - gyro_since >= GYRO_HOLD:
                self.start_siren("rotation %.2f rad/s" % gyro)

            if self.debug and now - last_debug > 10:
                last_debug = now
                _log("max 10 s : inclinaison %.1f deg, ecart acc %.2f, gyro %.2f, roues %.1f"
                     % (math.degrees(p[0]), p[1], p[2], p[3]))
                self.reset_peaks()
            time.sleep(1.0 / RATE)
