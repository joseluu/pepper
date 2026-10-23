# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "sounddevice", "numpy"]
# ///
"""Dialogue parlé avec Gemini Live (voix -> voix, un seul modèle, en continu).

Variante de dialogue.py (STT -> LLM texte -> TTS) pour réduire la latence :
le son du micro est envoyé en continu à Gemini Live, qui détecte la fin de la
phrase et répond directement en voix (24 kHz), jouée au fil de l'arrivée.

  Modèle : gemini-live-2.5-flash-native-audio (Vertex AI, europe-west4)

Deux modes :
- micro et haut-parleurs du PC (par défaut). À lancer **sous Windows** : la
  sortie son de WSLg hache et se bloque (voir STATUT_HALLOWEEN.md). Sous Windows
  le son passe par sounddevice (PortAudio) ; la sortie lit une file remplie au
  fil de l'arrivée, ce qui donne aussi l'instant exact où Pepper finit de parler.
- --robot : micro USB et haut-parleur du robot, via son pont audio
  (robot_audio.py, port 8090). Une session Gemini par enfant : le fantôme
  (halloween.py) la demande pendant son BOUH, la salutation part à la fin du
  rire, et la rencontre se termine après IDLE s sans voix ni parole. Pas de son
  sur le PC : marche aussi sous WSL.

Pendant que Pepper parle, le micro est remplacé par du silence (sinon, avec des
haut-parleurs, il s'entend et se coupe lui-même) ; --barge-in le désactive
(avec un casque : l'enfant peut alors couper la parole à Pepper).

Lancer depuis WSL (Python et son de Windows, identifiants Google de WSL) :
  ./live_windows.sh --prompt ../halloween/preprompt_dialogue.txt
Avec le robot (depuis WSL) :
  uv run --script live.py --robot pepper
Directement sous Windows :
  uv run --script live.py --prompt ..\\halloween\\preprompt_dialogue.txt
"""
import argparse
import asyncio
import json
import re
import os
import socket
import struct
import threading
import time

import numpy as np
try:
    import sounddevice as sd
except OSError:                  # pas de PortAudio (WSL) : seul --robot marche
    sd = None
from google import genai
from google.genai import types

PROJECT = "m2if-270422"
LOCATION = "europe-west4"
MODEL = "gemini-live-2.5-flash-native-audio"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROMPT = os.path.join(HERE, "..", "halloween", "preprompt_dialogue.txt")
HELLO = ("(Consigne, ce n'est pas un enfant qui parle : un enfant vient d'arriver devant "
         "toi et tu viens de lui faire « Bouh » avec un rire de fantôme. Dis-lui "
         "exactement : « Bonsoir, je suis Casper le fantôme, as-tu des choses à me dire ? »)")
HELLO_GREET = ("(Consigne, ce n'est pas un enfant qui parle : un enfant vient d'arriver "
               "devant toi. Dis-lui exactement : « Bonsoir, je suis Casper le fantôme, "
               "as-tu des choses à me dire ? »)")
GOODBYE = ("(Consigne, ce n'est pas un enfant qui parle : l'enfant ne répond plus, il est "
           "sans doute parti. Dis-lui au revoir en une phrase courte, par exemple "
           "« Joyeux Halloween ! Va vite chercher tes bonbons ! »)")
IN_RATE = 16000
OUT_RATE = 24000
CHUNK = 1600                     # 100 ms de micro à 16 kHz
TAIL = 0.4                       # micro coupé encore TAIL s après la fin de la parole
SPEECH_RMS = 500                 # au-dessus : quelqu'un parle (micro du PC)
ROBOT_SPEECH_RMS = 250           # idem, micro du robot avant gain (fond ~65)
IDLE = 20.0                      # robot : fin de la rencontre après IDLE s de calme
RELAUNCH = 10.0                  # robot : relance après RELAUNCH s de silence de l'enfant
MAX_RELAUNCH = 2                 # relances au plus par rencontre
RELAUNCH_TEXT = ("(Consigne, ce n'est pas un enfant qui parle : l'enfant ne dit plus rien. "
                 "Relance-le en lui demandant exactement : « En quoi es-tu déguisé ? ». "
                 "S'il te l'a déjà dit, pose-lui une autre petite question.)")
SCARED_TEXT = ("Le BOUH est fini. Demande maintenant à l'enfant exactement : "
               "« Alors, tu as eu peur ? »")
SCARE_TOOL = types.Tool(function_declarations=[types.FunctionDeclaration(
    name="refaire_peur",
    description="Refait le BOUH du fantôme : Pepper se redresse, lève les bras, ses yeux "
                "deviennent rouges et il joue un rire de fantôme (environ 12 secondes). "
                "À appeler seulement quand l'enfant vient de demander avec des mots de "
                "refaire peur, refaire le fantôme ou refaire le cri ; jamais de toi-même.")])
NOT_ASKED = ("Aucun BOUH n'a été fait : l'enfant ne l'a pas demandé. Ne dis pas « Alors, "
             "tu as eu peur ? » ; réponds simplement à ce que l'enfant vient de dire.")
# l'enfant s'en va : Pepper lui répond, puis la rencontre se termine
GOODBYE_RE = re.compile(r"au ?revoir|bye", re.I)
# demande de BOUH attendue dans la dernière phrase de l'enfant (« fais-moi peur »,
# « refais le fantôme », « encore »...), mais pas « j'ai eu peur »
ASK_SCARE = re.compile(r"\b(re)?fai(s|tes|re)\b.{0,15}(peur|fant[ôo]me|bouh|cri)"
                       r"|encore|recommence|bouh|\bcri\b", re.I)
MAX_TALK = 300.0                 # robot : durée max d'une rencontre (s)
ROBOT_PORT = 8090
ROBOT_GAIN = 20.0                # micro du robot très faible (parole vers -35 dBFS à
                                 # 50 cm, bien moins à 2 m) ; écrêtage doux au-delà


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Speaker:
    """Sortie continue : le rappel de PortAudio puise dans une file d'octets.

    Gemini envoie le son ~4 fois plus vite que le temps réel : on l'empile, la
    carte son le consomme à son rythme, et du silence sort quand la file est vide.
    """

    def __init__(self, device=None):
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.last_sound = 0.0        # dernier instant où la file n'était pas vide
        self.underruns = 0
        self.stream = sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16",
                                         blocksize=480, latency="high", device=device,
                                         callback=self._callback)
        self.stream.start()

    def _callback(self, outdata, frames, time_info, status):
        n = len(outdata)
        with self.lock:
            k = min(n, len(self.buf))
            outdata[:k] = self.buf[:k]
            del self.buf[:k]
            if k:
                self.last_sound = time.time()
            if k < n:
                outdata[k:] = b"\0" * (n - k)
        if status.output_underflow:
            self.underruns += 1

    def write(self, pcm):
        with self.lock:
            self.buf += pcm
            self.last_sound = time.time()

    def speaking(self):
        with self.lock:
            pending = len(self.buf)
        return pending > 0 or time.time() < self.last_sound + TAIL + self.stream.latency

    def heard(self):
        pass

    def scare(self):
        """Pas de robot : le BOUH est seulement annoncé."""
        log("   (BOUH : rien à faire sans le robot)")
        asyncio.get_running_loop().call_later(1, self.scared.set)

    def flush(self):
        """Coupe net (l'enfant a interrompu Pepper)."""
        with self.lock:
            self.buf.clear()


class RobotLink:
    """Pont audio du robot (robot_audio.py) : micro, haut-parleur, signaux du fantôme.

    Même interface que Speaker pour la voix ; c'est le robot qui remplace son
    micro par du silence quand il parle, et qui signale la fin ("quiet").
    """
    underruns = 0
    scared = None                    # asyncio.Event posé par Live.tool
    talking = False                  # le robot joue encore la voix reçue

    def __init__(self, host, port):
        self.host, self.port = host, port

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        self.writer.get_extra_info("socket").setsockopt(
            socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    async def frames(self):
        while True:
            n = struct.unpack(">I", await self.reader.readexactly(4))[0]
            head = json.loads(await self.reader.readexactly(n))
            yield head, await self.reader.readexactly(head.get("size", 0))

    def send(self, cmd, data=b""):
        h = json.dumps({"cmd": cmd, "size": len(data)}).encode()
        self.writer.write(struct.pack(">I", len(h)) + h + data)

    def write(self, pcm):
        self.talking = True          # jusqu'au "quiet" du robot
        self.send("pcm", pcm)

    def scare(self):
        self.send("scare")

    def flush(self):
        self.send("flush")

    def heard(self):
        """Des mots de l'enfant ont été transcrits : le robot regarde d'où vient la voix."""
        self.send("heard")

    def speaking(self):
        return False


class Live:
    def __init__(self, system, voice, barge_in, gain=ROBOT_GAIN):
        self.gain = gain
        self.speech_rms = SPEECH_RMS
        self.client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
        self.config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=system,
            speech_config=types.SpeechConfig(
                language_code="fr-FR",
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=500)),
            tools=[SCARE_TOOL])
        self.barge_in = barge_in
        self.speaker = None          # Speaker (PC) ou RobotLink
        self.last_voice = 0.0        # dernier morceau de micro avec de la voix
        self.last_activity = 0.0     # voix de l'enfant ou de Pepper
        self.scaring = False         # BOUH redemandé en cours
        self.last_child = ""         # dernière phrase de l'enfant (avant un BOUH)
        self.scared = None           # asyncio.Event : le BOUH redemandé est fini
        self.heard = ""
        self.heard_at = 0.0          # dernier morceau de transcription de l'enfant
        self.said = ""
        self.first_audio = None
        logs = os.path.join(HERE, "logs")
        self.transcript = open(os.path.join(logs, time.strftime("live-%Y%m%d-%H%M%S.txt")),
                               "a", encoding="utf-8") if os.path.isdir(logs) else None

    def note(self, who, text):
        text = text.strip()
        if not text:
            return
        log("%s : %s" % (who, text))
        if self.transcript:
            self.transcript.write("%s %s : %s\n" % (time.strftime("%H:%M:%S"), who, text))
            self.transcript.flush()

    async def mic(self, session, q):
        while True:
            data = await q.get()
            if not self.greeted.is_set():
                # les voix de la pièce ne doivent pas couper la salutation
                data = b"\0" * len(data)
            elif not self.barge_in and self.speaker.speaking():
                data = b"\0" * len(data)
            else:
                x = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                if np.sqrt(np.mean(x * x)) > self.speech_rms:
                    self.last_voice = time.time()
            await session.send_realtime_input(
                audio=types.Blob(data=data, mime_type="audio/pcm;rate=%d" % IN_RATE))

    async def receive(self, session):
        while True:
            async for r in session.receive():
                if r.go_away:
                    log("   (Gemini va fermer la session dans %s)" % r.go_away.time_left)
                if r.tool_call:
                    for fc in r.tool_call.function_calls:
                        asyncio.create_task(self.tool(session, fc))
                sc = r.server_content
                if not sc:
                    continue
                if sc.input_transcription and sc.input_transcription.text:
                    self.heard += sc.input_transcription.text
                    self.heard_at = time.time()
                    if any(c.isalpha() for c in sc.input_transcription.text):
                        self.speaker.heard()
                        # des mots compris, pas seulement du bruit dans la pièce
                        self.last_activity = time.time()
                if sc.output_transcription and sc.output_transcription.text:
                    self.said += sc.output_transcription.text
                if sc.model_turn:
                    for p in sc.model_turn.parts:
                        if p.inline_data and p.inline_data.data:
                            if self.first_audio is None:
                                self.first_audio = time.time()
                                self.note("Enfant", self.heard)
                                self.last_child = self.heard
                                if GOODBYE_RE.search(self.heard):
                                    self.leaving = True
                                self.heard = ""
                                if self.last_voice:
                                    log("   latence : %.1f s après la fin de la voix"
                                        % (self.first_audio - self.last_voice))
                            self.speaker.write(p.inline_data.data)
                            self.last_activity = time.time()
                if sc.interrupted:
                    log("   (interrompu)")
                    self.speaker.flush()
                if sc.turn_complete or sc.interrupted:
                    self.greeted.set()
                    if self.leaving:     # Pepper a répondu à « au revoir »
                        self.left = True
                    self.note("Pepper", self.said)
                    if self.speaker.underruns:
                        log("   (sortie son : %d manques de données)" % self.speaker.underruns)
                        self.speaker.underruns = 0
                    self.said = ""
                    self.first_audio = None

    async def tool(self, session, fc):
        """Outil appelé par Gemini : refaire_peur (attend la fin du BOUH)."""
        if fc.name != "refaire_peur":
            result = {"error": "outil inconnu"}
        elif not ASK_SCARE.search(self.heard + " " + self.last_child):
            # Gemini l'a appelé de lui-même
            log("   BOUH refusé : l'enfant ne l'a pas demandé")
            result = {"error": NOT_ASKED}
        else:
            self.last_child = ""
            log("   BOUH redemandé")
            self.scaring = True
            self.scared = asyncio.Event()
            self.speaker.scared = self.scared
            self.speaker.scare()
            try:
                await asyncio.wait_for(self.scared.wait(), 40)
                result = {"result": SCARED_TEXT}
            except TimeoutError:
                result = {"error": "le BOUH n'a pas pu être fait"}
            self.scaring = False
            self.last_activity = time.time()
        await session.send_tool_response(function_responses=[
            types.FunctionResponse(id=fc.id, name=fc.name, response=result)])

    async def talk(self, session, q, idle=False, hello=HELLO):
        """Salue l'enfant puis dialogue ; avec idle, s'arrête quand c'est calme."""
        self.heard = self.said = ""
        self.heard_at = 0.0
        self.last_child = ""
        self.greeted = asyncio.Event()
        self.leaving = self.left = False
        self.first_audio = None
        self.last_activity = time.time()
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=hello)]),
            turn_complete=True)
        tasks = [asyncio.create_task(self.mic(session, q)),
                 asyncio.create_task(self.receive(session))]
        if idle:
            tasks.append(asyncio.create_task(self.watchdog(session)))
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                t.result()           # fait remonter une erreur
        finally:
            for t in tasks:
                t.cancel()

    async def watchdog(self, session):
        start = time.time()
        relaunches = 0
        relaunched_at = None         # last_activity au moment de la dernière relance
        while True:
            await asyncio.sleep(0.5)
            now = time.time()
            if self.left and not getattr(self.speaker, "talking", False):
                log("   (l'enfant a dit au revoir)")
                return
            # le rire du BOUH et la voix de Pepper ne sont pas un silence
            if self.scaring or getattr(self.speaker, "talking", False):
                self.last_activity = now
                continue
            if self.heard_at and self.first_audio is None and now - self.heard_at > 4:
                if self.heard.strip():
                    log("   entendu, sans réponse : %s" % self.heard.strip())
                self.heard_at = 0.0
            if (now - self.last_activity > RELAUNCH and relaunches < MAX_RELAUNCH
                    and relaunched_at != self.last_activity
                    and now - self.last_voice > 2):    # pas pendant qu'on parle
                relaunches += 1
                relaunched_at = self.last_activity
                log("   (silence : relance)")
                await session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=RELAUNCH_TEXT)]),
                    turn_complete=True)
            if now - self.last_activity > IDLE:
                log("   (plus personne depuis %.0f s)" % IDLE)
                return await self.goodbye(session)
            if now - start > MAX_TALK:
                log("   (rencontre trop longue)")
                return await self.goodbye(session)

    async def goodbye(self, session):
        """Pepper dit au revoir, puis on attend que le robot ait fini de parler."""
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=GOODBYE)]),
            turn_complete=True)
        started = False
        for _ in range(75):          # 15 s au plus
            await asyncio.sleep(0.2)
            if self.speaker.talking:
                started = True
            elif started:
                return

    async def run_local(self, mic_device, out_device):
        self.speaker = Speaker(out_device)
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()

        def callback(indata, frames, time_info, status):
            loop.call_soon_threadsafe(q.put_nowait, bytes(indata))

        async with self.client.aio.live.connect(model=MODEL, config=self.config) as session:
            log("connecté à %s, j'écoute (Ctrl+C pour arrêter)" % MODEL)
            log("   micro : %s" % sd.query_devices(mic_device, "input")["name"])
            log("   sortie : %s" % sd.query_devices(self.speaker.stream.device)["name"])
            with sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16",
                                   blocksize=CHUNK, device=mic_device, callback=callback):
                await self.talk(session, q)

    async def run_robot(self, host, port):
        """Reste connecté au robot : se reconnecte s'il redémarre son pont audio."""
        while True:
            try:
                await self.serve_robot(host, port)
            except (asyncio.IncompleteReadError, OSError) as e:
                log("robot déconnecté (%s), nouvel essai dans 3 s" % e.__class__.__name__)
            await asyncio.sleep(3)

    async def serve_robot(self, host, port):
        link = self.speaker = RobotLink(host, port)
        self.speech_rms = ROBOT_SPEECH_RMS * self.gain
        await link.connect()
        log("connecté au robot %s:%d, en attente d'un enfant (Ctrl+C pour arrêter)"
            % (host, port))
        task = q = go = None
        async for head, data in link.frames():
            if task and task.done():
                task = None
            cmd = head.get("cmd")
            if cmd == "mic":
                if go and go.is_set():
                    x = np.frombuffer(data, dtype=np.int16).astype(np.float32) * self.gain
                    x = 32767 * np.tanh(x / 32767)      # écrêtage doux
                    q.put_nowait(x.astype(np.int16).tobytes())
            elif cmd == "quiet":
                link.talking = False
                self.last_activity = time.time()
                if task:
                    log("   (le robot a fini de parler)")
            elif cmd == "event":
                name = head.get("name")
                log("   (fantôme : %s)" % name)
                if name == "scared" and link.scared:
                    link.scared.set()
                if name in ("prepare", "talk") and task is None:
                    q, go = asyncio.Queue(), asyncio.Event()
                    hello = HELLO_GREET if head.get("mode") == "greet" else HELLO
                    task = asyncio.create_task(self.encounter(link, q, go, hello))
                if name == "talk":
                    go.set()
                elif name == "abort" and task:
                    task.cancel()

    async def encounter(self, link, q, go, hello):
        """Une rencontre avec un enfant : une session Gemini, fermée à la fin."""
        try:
            async with self.client.aio.live.connect(model=MODEL, config=self.config) as session:
                log("nouvel enfant : connecté à %s" % MODEL)
                await asyncio.wait_for(go.wait(), 30)
                await self.talk(session, q, idle=True, hello=hello)
        except TimeoutError:
            log("   (pas de signal du fantôme)")
        except Exception as e:
            log("   erreur : %s" % e)
        finally:
            link.send("end")
            log("fin de la rencontre")
            if self.transcript:
                self.transcript.write("---\n")
                self.transcript.flush()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--prompt", default=DEFAULT_PROMPT, help="fichier texte des consignes")
    p.add_argument("--voice", default="Puck", help="Puck, Leda, Aoede, Kore, Charon...")
    p.add_argument("--barge-in", action="store_true",
                   help="micro ouvert pendant que Pepper parle (avec un casque)")
    p.add_argument("--robot", metavar="HÔTE[:PORT]",
                   help="micro et haut-parleur du robot (pont robot_audio.py)")
    p.add_argument("--gain", type=float, default=ROBOT_GAIN,
                   help="--robot : gain appliqué au micro du robot (%(default)s)")
    p.add_argument("--mic", help="numéro ou nom du micro (--list pour les voir)")
    p.add_argument("--out", help="numéro ou nom de la sortie son")
    p.add_argument("--list", action="store_true", help="liste les périphériques son")
    args = p.parse_args()
    if args.list:
        print(sd.query_devices())
        return
    dev = lambda d: int(d) if d and d.isdigit() else d
    with open(args.prompt, encoding="utf-8") as f:
        system = f.read()
    live = Live(system, args.voice, args.barge_in, args.gain)
    if args.robot:
        host, _, port = args.robot.partition(":")
        run = live.run_robot(host, int(port or ROBOT_PORT))
    else:
        run = live.run_local(dev(args.mic), dev(args.out))
    try:
        asyncio.run(run)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
