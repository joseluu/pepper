# -*- coding: utf-8 -*-
# Alarme anti-vol du fantome : si on emporte le robot (il faut monter un
# escalier de 10 marches, donc le pencher, le soulever, le tourner), sirene
# de police continue jusqu'au desarmement manuel.
#
# Capteur : centrale inertielle de la BASE (celle du torse est en panne).
# Bruit mesure au repos (2026-10-18) : angles +/- 0.003 rad, accelero
# +/- 0.2 m/s2, gyro +/- 0.02 rad/s. AngleY de repos ~ -0.026 (sol en pente).
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
                          "GyroscopeX", "GyroscopeY", "GyroscopeZ")]

RATE = 20.0          # lectures par seconde
TILT_HOLD = 0.5      # s d'inclinaison continue pour declencher
SHOCK_ACC = 2.5      # m/s2 d'ecart a la pesanteur de reference
SHOCK_COUNT = 4      # ... sur au moins tant de lectures dans la derniere seconde
GYRO_MAX = 0.5       # rad/s de rotation ...
GYRO_HOLD = 0.5      # ... continue pendant tant de secondes
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
        gyro = math.sqrt(v[5] ** 2 + v[6] ** 2 + v[7] ** 2)
        return v[0], v[1], acc, gyro

    def calibrate(self, seconds=2.0):
        n, sx, sy, sa = 0, 0.0, 0.0, 0.0
        t_end = time.time() + seconds
        while time.time() < t_end:
            ax, ay, acc, _ = self.read()
            n += 1; sx += ax; sy += ay; sa += acc
            time.sleep(1.0 / RATE)
        self.ref = (sx / n, sy / n, sa / n)
        _log("reference : AngleX %.3f AngleY %.3f |acc| %.2f" % self.ref)

    def reset_peaks(self):
        self.peaks = [0.0, 0.0, 0.0]   # inclinaison, ecart |acc|, gyro

    # -- sirene --------------------------------------------------------------
    def start_siren(self, reason):
        if self.active:
            return
        self.active = True
        self.siren_t0 = time.time()
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

    def stop_siren(self, why="desarmement"):
        self.active = False
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
        _log("armee (inclinaison %.0f deg, choc %.1f m/s2, rotation %.1f rad/s)"
             % (math.degrees(self.tilt), SHOCK_ACC, GYRO_MAX))

    def stop(self):
        self._stop = True

    def _run(self):
        tilt_since = gyro_since = None
        shocks = []          # instants des lectures "choc"
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
            ax, ay, acc, gyro = self.read()
            tilt = max(abs(ax - self.ref[0]), abs(ay - self.ref[1]))
            dacc = abs(acc - self.ref[2])
            p = self.peaks
            p[0], p[1], p[2] = max(p[0], tilt), max(p[1], dacc), max(p[2], gyro)

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
                _log("max 10 s : inclinaison %.1f deg, ecart acc %.2f, gyro %.2f"
                     % (math.degrees(p[0]), p[1], p[2]))
                self.reset_peaks()
            time.sleep(1.0 / RATE)
