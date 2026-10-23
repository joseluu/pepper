# -*- coding: utf-8 -*-
# Pont audio du robot pour le dialogue (Python 2.7, NAOqi 2.7).
#
# Le robot ne fait qu'ecouter et parler ; tout le traitement (Gemini Live, ou
# transcription + LLM + synthese vocale) tourne sur le PC (live.py --robot ou
# dialogue.py), qui se connecte ici.
#
# Lancer (sur le robot) :
#   PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages python2 robot_audio.py
#
# Protocole sur une seule connexion TCP (port 8090), dans les deux sens des
# messages encadres : 4 octets longueur (big endian) de l'en-tete JSON,
# l'en-tete, puis `size` octets de donnees.
#   robot -> PC :
#     {"cmd": "mic", "size": N}     son du micro USB, PCM 16 bits mono 16 kHz,
#                                   en continu (100 ms). Pendant que le robot
#                                   parle, du silence (il ne s'entend pas).
#     {"cmd": "quiet"}              le robot vient de finir de parler
#     {"cmd": "event", "name": E}   signal du fantome (halloween.py) :
#                                   "prepare" (BOUH en cours), "talk" (fin du
#                                   rire : saluer l'enfant), "abort" (sirene),
#                                   "scared" (BOUH redemande : fini)
#   PC -> robot :
#     {"cmd": "pcm", "size": N}     voix en continu, PCM 16 bits mono 24 kHz
#     {"cmd": "flush"}              coupe net la voix en cours (interruption)
#     {"cmd": "end"}                fin de la rencontre (une fois la voix finie)
#     {"cmd": "scare"}              refaire le BOUH (l'enfant l'a demande), une
#                                   fois la voix finie : par le fantome s'il
#                                   tourne, sinon juste le rire, yeux rouges
#     {"cmd": "heard"}              Gemini a transcrit des mots de l'enfant :
#                                   pendant un dialogue, la tete se tourne vers
#                                   la derniere voix reperee par le micro
#     {"cmd": "play", "size": N}    fichier WAV a jouer (dialogue.py)
#     {"cmd": "eyes", "color": "0x0000ff"}  couleur des yeux
#     {"cmd": "stop"}               coupe la parole en cours
#
# Avec le fantome, l'echange passe par ALMemory :
#   Halloween/DialoguePC  1 quand un PC est connecte
#   Halloween/Dialogue    "idle" -> "prepare" -> "talk" (ecrits par le fantome)
#                         -> "active" (ecrit ici) -> "idle" (apres "end"), ou
#                         "abort" (fantome) -> "idle" ;
#                         "active" -> "scare" (ecrit ici) -> "active" (fantome,
#                         une fois le BOUH fini)
#
# Direction de la voix : le ReSpeaker (premiere Mic Array, 2886:0007) envoie
# par HID, au debut et a la fin de chaque voix, un rapport
# ff ff 03 00 | 2 (debut) ou 0 (fin) | angle sur 2 octets (little endian),
# en degres par pas de 30 : 0 = devant le robot, croissant vers sa gauche
# (90 = gauche, 180 = derriere), comme HeadYaw. /dev/hidraw* est reserve a
# root : un petit lecteur tourne avec sudo.
import os, json, math, time, struct, socket, argparse, threading, subprocess, Queue
import qi

MIC = "plughw:UAC20,0"          # ReSpeaker Mic Array (carte UAC20)
RATE = 16000
CHUNK = 1600                    # 100 ms de son (16 bits mono)
OUT_RATE = 24000                # voix de Gemini Live
LATENCY = 0.15                  # tampon de pacat (s)
TAIL = 0.4                      # silence garde apres la fin de la parole (s)
PLAY_FILE = "/tmp/dialogue_say.wav"
LAUGH = os.path.expanduser("~/halloween/thriller_laugh.wav")
KEY = "Halloween/Dialogue"
PC_KEY = "Halloween/DialoguePC"
LOOK_MAX = 110                  # au-dela (deg), voix de derriere : ignoree
LOOK_AGE = 4.0                  # une voix plus ancienne (s) n'est plus visee

DOA_READER = r"""
import os, sys, glob
for u in glob.glob("/sys/class/hidraw/hidraw*/device/uevent"):
    if "00002886:00000007" in open(u).read():
        dev = "/dev/" + u.split("/")[4]
f = os.open(dev, os.O_RDONLY)
while True:
    d = bytearray(os.read(f, 64))
    if len(d) >= 7 and d[0] == 0xff and d[1] == 0xff and d[2] == 3:
        sys.stdout.write("%d %d\n" % (d[4], d[5] + 256 * d[6]))
        sys.stdout.flush()
"""


def enable_capture():
    # l'interrupteur de capture du ReSpeaker est coupe au demarrage
    for numid, val in (("7", "on,on"), ("8", "on")):
        subprocess.call(["amixer", "-q", "-c", "UAC20", "cset",
                         "numid=" + numid, val])


def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        part = conn.recv(n - len(buf))
        if not part:
            raise EOFError
        buf += part
    return buf


class Stream(object):
    """Voix en continu : PCM 24 kHz -> pacat -> PulseAudio (sortie speaker).

    Un fil ecrit dans pacat, qui bloque quand il a assez d'avance : le PC envoie
    la voix plus vite que le temps reel. L'heure de fin de la voix est calculee
    a partir de ce qui a ete recu.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.queue = Queue.Queue()
        self.proc = None
        self.gen = 0                # change a chaque coupure : morceaux perimes
        self.end = 0.0              # heure ou la voix recue aura fini de sortir
        t = threading.Thread(target=self._writer)
        t.daemon = True
        t.start()

    def _writer(self):
        while True:
            gen, pcm = self.queue.get()
            with self.lock:
                if gen != self.gen:
                    continue
                if self.proc is None:
                    self.proc = subprocess.Popen(
                        ["pacat", "-p", "-d", "speaker", "--format=s16le",
                         "--rate=%d" % OUT_RATE, "--channels=1",
                         "--latency-msec=%d" % (LATENCY * 1000)],
                        stdin=subprocess.PIPE)
                proc = self.proc
            try:
                proc.stdin.write(pcm)
                proc.stdin.flush()
            except (IOError, ValueError):
                pass                # pacat tue par flush()

    def write(self, pcm):
        with self.lock:
            self.end = max(self.end, time.time() + LATENCY) + len(pcm) / 2.0 / OUT_RATE
            self.queue.put((self.gen, pcm))

    def speaking(self):
        return time.time() < self.end + TAIL

    def flush(self):
        with self.lock:
            self.gen += 1
            self.end = 0.0
            if self.proc is not None:
                self.proc.kill()
                self.proc.wait()
                self.proc = None


class Doa(object):
    """Direction des voix reperees par le micro (lecteur HID lance avec sudo)."""

    def __init__(self, bridge):
        self.bridge = bridge
        self.last = None            # (heure de debut, angle) de la derniere voix
        t = threading.Thread(target=self._read)
        t.daemon = True
        t.start()

    def _read(self):
        try:
            proc = subprocess.Popen(["sudo", "-n", "python2", "-c", DOA_READER],
                                    stdout=subprocess.PIPE)
        except OSError as e:
            self.bridge.log("direction des voix indisponible : %s" % e)
            return
        for line in iter(proc.stdout.readline, b""):
            start, angle = [int(x) for x in line.split()]
            # sa propre voix ne compte pas
            if start and not self.bridge.busy():
                self.last = (time.time(), angle)
        self.bridge.log("lecteur de direction arrete")


class Bridge(object):
    def __init__(self, session):
        self.player = session.service("ALAudioPlayer")
        self.motion = session.service("ALMotion")
        self.leds = session.service("ALLeds")
        self.mem = session.service("ALMemory")
        self.stream = Stream()
        self.send_lock = threading.Lock()
        self.conn = None
        self.speaking_until = 0.0   # micro muet jusqu'a cette heure (WAV)
        self.speaking = False
        self.ending = False         # le PC a fini : repasser a idle apres la voix
        self.scaring = False        # BOUH redemande en cours
        self.state = "idle"
        self.set_state("idle")
        self.mem.insertData(PC_KEY, 0)
        self.looked = None
        self.doa = None             # demarre une fois le micro ouvert

    def look(self):
        """Tourne la tete vers la derniere voix (des mots ont ete transcrits)."""
        seg = self.doa and self.doa.last
        if self.state != "active" or seg is None or seg is self.looked:
            return
        self.looked = seg
        if time.time() - seg[0] > LOOK_AGE:
            return
        yaw = seg[1] if seg[1] <= 180 else seg[1] - 360
        if abs(yaw) > LOOK_MAX:
            self.log("voix de derriere (%d deg) : ignoree" % seg[1])
            return
        self.log("regarde vers %d deg" % yaw)
        self.motion.setStiffnesses("Head", 1.0)
        self.motion.setAngles(["HeadYaw", "HeadPitch"], [math.radians(yaw), 0.0], 0.15)

    def log(self, msg):
        print "%s %s" % (time.strftime("%H:%M:%S"), msg)

    def set_state(self, state):
        self.state = state
        self.mem.insertData(KEY, state)

    def send(self, head, data=b""):
        head = dict(head, size=len(data))
        h = json.dumps(head)
        with self.send_lock:
            self.conn.sendall(struct.pack(">I", len(h)) + h + data)

    # --- PC -> robot ---
    def commands(self, conn):
        try:
            while True:
                hlen = struct.unpack(">I", recv_exact(conn, 4))[0]
                head = json.loads(recv_exact(conn, hlen))
                data = recv_exact(conn, head.get("size", 0))
                cmd = head.get("cmd")
                if cmd == "pcm":
                    self.stream.write(data)
                elif cmd == "flush":
                    self.stream.flush()
                elif cmd == "end":
                    self.ending = True
                elif cmd == "heard":
                    self.look()
                elif cmd == "scare":
                    threading.Thread(target=self.scare).start()
                elif cmd == "play":
                    with open(PLAY_FILE, "wb") as f:
                        f.write(data)
                    threading.Thread(target=self.play).start()
                elif cmd == "eyes":
                    self.leds.fadeRGB("FaceLeds", int(head["color"], 16), 0.2)
                elif cmd == "stop":
                    self.player.stopAll()
                    self.stream.flush()
        except (EOFError, socket.error):
            pass

    def play(self):
        self.speaking = True
        try:
            self.player.playFile(PLAY_FILE)
        except Exception as e:
            self.log("lecture impossible : %s" % e)
        finally:
            self.speaking = False
            self.speaking_until = time.time() + TAIL

    def ghost_alive(self):
        try:    # battement de halloween.py, toutes les 0,2 s pendant un dialogue
            return time.time() - self.mem.getData("Halloween/Ghost") < 3
        except Exception:
            return False

    def scare(self):
        """Refait le BOUH apres la voix en cours, puis previent le PC."""
        self.scaring = True
        try:
            while self.stream.speaking():
                time.sleep(0.1)
            if self.state == "active" and self.ghost_alive():
                self.log("BOUH demande au fantome")
                self.set_state("scare")
                t0 = time.time()
                while self.mem.getData(KEY) == "scare" and time.time() - t0 < 30:
                    time.sleep(0.2)
                self.state = self.mem.getData(KEY)
            else:
                self.log("BOUH sans le fantome : rire seul")
                self.leds.fadeRGB("FaceLeds", 0xFF0000, 0.0)
                self.player.playFile(LAUGH)
                self.leds.fadeRGB("FaceLeds", 0x000000, 0.3)
            self.speaking_until = time.time() + TAIL
        finally:
            self.scaring = False
        self.send({"cmd": "event", "name": "scared"})

    def busy(self):
        return (self.speaking or self.scaring or time.time() < self.speaking_until
                or self.stream.speaking())

    # --- fantome -> PC ---
    def poll_ghost(self, busy):
        state = self.mem.getData(KEY)
        if state != self.state:
            self.state = state
            if state in ("prepare", "talk", "abort"):
                self.log("fantome : %s" % state)
                self.send({"cmd": "event", "name": state})
            if state == "talk":
                self.ending = False
                self.set_state("active")
            elif state == "abort":
                self.stream.flush()
                self.set_state("idle")
        if self.ending and not busy:
            self.ending = False
            self.stream.flush()     # ferme pacat
            if self.state != "idle":
                self.log("fin du dialogue")
                self.set_state("idle")

    # --- robot -> PC ---
    def serve(self, conn):
        self.conn = conn
        self.ending = False
        self.set_state("idle")
        self.mem.insertData(PC_KEY, 1)
        rec = subprocess.Popen(["arecord", "-q", "-D", MIC, "-f", "S16_LE",
                                "-c", "1", "-r", str(RATE), "-t", "raw"],
                               stdout=subprocess.PIPE)
        threading.Thread(target=self.commands, args=(conn,)).start()
        silence = b"\x00" * CHUNK * 2
        was_busy = False
        try:
            while True:
                data = rec.stdout.read(CHUNK * 2)
                if not data:
                    self.log("arecord s'est arrete")
                    break
                if self.doa is None:
                    # apres l'ouverture du micro : une panne USB (-71) est
                    # survenue en ouvrant le micro pendant la lecture HID
                    self.doa = Doa(self)
                busy = self.busy()
                self.send({"cmd": "mic"}, silence if busy else data)
                if was_busy and not busy:
                    self.send({"cmd": "quiet"})
                was_busy = busy
                self.poll_ghost(busy)
        except socket.error:
            pass
        finally:
            self.mem.insertData(PC_KEY, 0)
            self.set_state("idle")
            rec.terminate()
            rec.wait()
            self.player.stopAll()
            self.stream.flush()
            try:    # sinon le fil des commandes garde la connexion ouverte
                conn.shutdown(socket.SHUT_RDWR)
            except socket.error:
                pass
            conn.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8090)
    args = p.parse_args()
    session = qi.Session()
    session.connect("tcp://127.0.0.1:9559")
    enable_capture()
    bridge = Bridge(session)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("", args.port))
    srv.listen(1)
    bridge.log("en attente du PC sur le port %d" % args.port)
    while True:
        conn, addr = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        bridge.log("PC connecte : %s" % addr[0])
        bridge.serve(conn)            # un seul PC a la fois
        bridge.log("PC deconnecte")


if __name__ == "__main__":
    main()
