# -*- coding: utf-8 -*-
# Pont audio du robot pour le dialogue (Python 2.7, NAOqi 2.7).
#
# Le robot ne fait qu'ecouter et parler ; tout le traitement (transcription,
# LLM, synthese vocale) tourne sur le PC (dialogue.py), qui se connecte ici.
#
# Lancer (sur le robot) :
#   PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages python2 robot_audio.py
#
# Protocole sur une seule connexion TCP (port 8090) :
#   robot -> PC : son brut du micro USB, PCM 16 bits mono 16 kHz, en continu.
#                 Pendant que le robot parle, on envoie du silence (il ne
#                 s'entend pas lui-meme).
#   PC -> robot : messages encadres : 4 octets longueur (big endian) de l'en-tete
#                 JSON, l'en-tete, puis `size` octets de donnees.
#                 {"cmd": "play", "size": N}   fichier WAV a jouer
#                 {"cmd": "eyes", "color": "0x0000ff"}  couleur des yeux
#                 {"cmd": "stop"}              coupe la parole en cours
import os, json, time, struct, socket, argparse, threading, subprocess
import qi

MIC = "plughw:UAC20,0"          # ReSpeaker Mic Array (carte UAC20)
RATE = 16000
CHUNK = 1600                    # 50 ms de son (16 bits mono)
TAIL = 0.4                      # silence garde apres la fin de la parole (s)
PLAY_FILE = "/tmp/dialogue_say.wav"


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


class Bridge(object):
    def __init__(self, session):
        self.player = session.service("ALAudioPlayer")
        self.leds = session.service("ALLeds")
        self.speaking_until = 0.0   # micro muet jusqu'a cette heure
        self.speaking = False

    def log(self, msg):
        print "%s %s" % (time.strftime("%H:%M:%S"), msg)

    # --- PC -> robot ---
    def commands(self, conn):
        try:
            while True:
                hlen = struct.unpack(">I", recv_exact(conn, 4))[0]
                head = json.loads(recv_exact(conn, hlen))
                data = recv_exact(conn, head.get("size", 0))
                cmd = head.get("cmd")
                if cmd == "play":
                    with open(PLAY_FILE, "wb") as f:
                        f.write(data)
                    threading.Thread(target=self.play).start()
                elif cmd == "eyes":
                    self.leds.fadeRGB("FaceLeds", int(head["color"], 16), 0.2)
                elif cmd == "stop":
                    self.player.stopAll()
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

    # --- robot -> PC ---
    def serve(self, conn):
        rec = subprocess.Popen(["arecord", "-q", "-D", MIC, "-f", "S16_LE",
                                "-c", "1", "-r", str(RATE), "-t", "raw"],
                               stdout=subprocess.PIPE)
        threading.Thread(target=self.commands, args=(conn,)).start()
        silence = b"\x00" * CHUNK * 2
        try:
            while True:
                data = rec.stdout.read(CHUNK * 2)
                if not data:
                    self.log("arecord s'est arrete")
                    break
                if self.speaking or time.time() < self.speaking_until:
                    data = silence
                conn.sendall(data)
        except socket.error:
            pass
        finally:
            rec.terminate()
            rec.wait()
            self.player.stopAll()
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
