# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "sounddevice", "numpy"]  # sounddevice : import de live.py
# ///
"""Esprit de compagnie 3PO : Gemini Live à l'écoute d'une conversation.

Tourne sur tram (service pepper-3po), connecté au pont audio du robot
(dialogue/robot_audio.py --prefix 3PO, port 8090). Dérivé de dialogue/live.py,
dont il reprend le lien avec le robot (RobotLink) et les réglages du micro.

Une session Gemini par période d'attention : compagnon.py (sur le robot) la
demande quand on appuie sur « Écoute » dans la page web. 3PO ne parle pas en
premier ; l'écoute proactive de Gemini le laisse se taire quand la
conversation ne lui est pas adressée. Fin de l'écoute :
- « merci » ou « merci 3PO » : pause sans rien dire ;
- IDLE s sans aucun mot entendu ni dit : « L'esprit de compagnie 3PO en
  pause. », puis pause ;
- bouton « Pause » de la page (le robot envoie "abort").
Une session Gemini Live dure une dizaine de minutes : elle est reprise avec
son contexte (reprise de session) tant que 3PO est attentif.

  uv run --script live3po.py --robot pepper
"""
import argparse
import asyncio
import os
import re
import sys
import time

import numpy as np
from google import genai
from google.genai import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "dialogue"))
from live import (PROJECT, LOCATION, MODEL, IN_RATE, ROBOT_PORT, ROBOT_GAIN,  # noqa: E402
                  ROBOT_SPEECH_RMS, GATE_HOLD, RobotLink, log)

DEFAULT_PROMPT = os.path.join(HERE, "preprompt_3po.txt")
IDLE = 60.0                      # s sans interaction : pause d'elle-même
PAUSE_TEXT = ("(Consigne : personne ne parle plus. Dis exactement « L'esprit de "
              "compagnie 3PO en pause. » et rien d'autre.)")
THANKS_RE = re.compile(r"\bmerci\b", re.I)
THANKS_WAIT = 1.2                # s de silence après « merci » avant la pause
MAX_RESUME = 3                   # reprises de session de suite sans succès


class Companion:
    def __init__(self, system, voice, gain=ROBOT_GAIN):
        self.gain = gain
        self.speech_rms = ROBOT_SPEECH_RMS * gain
        self.gate = False            # couper le micro sous le seuil (page web)
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
            # le modèle peut ne pas répondre à ce qui ne lui est pas adressé
            proactivity=types.ProactivityConfig(proactive_audio=True),
            # longues conversations : contexte glissant, reprise de session
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()))
        self.speaker = None
        self.handle = None           # reprise de session Gemini
        self.pause = None            # raison de la pause, fin de l'écoute
        self.last_voice = 0.0
        self.last_activity = 0.0
        self.heard = ""
        self.heard_at = 0.0
        self.said = ""
        self.thanked = False
        self.first_audio = None
        logs = os.path.join(HERE, "logs")
        self.transcript = open(os.path.join(logs, time.strftime("3po-%Y%m%d-%H%M%S.txt")),
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
            x = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            if np.sqrt(np.mean(x * x)) > self.speech_rms:
                self.last_voice = time.time()
            elif self.gate and time.time() - self.last_voice > GATE_HOLD:
                data = b"\0" * len(data)   # sous le seuil : Gemini n'entend rien
            await session.send_realtime_input(
                audio=types.Blob(data=data, mime_type="audio/pcm;rate=%d" % IN_RATE))

    async def receive(self, session):
        while True:
            async for r in session.receive():
                if r.session_resumption_update and r.session_resumption_update.new_handle:
                    self.handle = r.session_resumption_update.new_handle
                if r.go_away:
                    log("   (Gemini va fermer la session dans %s)" % r.go_away.time_left)
                sc = r.server_content
                if not sc:
                    continue
                if sc.input_transcription and sc.input_transcription.text:
                    text = sc.input_transcription.text
                    self.heard += text
                    self.heard_at = time.time()
                    if any(c.isalpha() for c in text):
                        self.speaker.heard()       # la tête se tourne vers la voix
                        self.last_activity = time.time()
                    if THANKS_RE.search(self.heard):
                        self.thanked = True
                if sc.output_transcription and sc.output_transcription.text:
                    self.said += sc.output_transcription.text
                if sc.model_turn:
                    for p in sc.model_turn.parts:
                        if not (p.inline_data and p.inline_data.data):
                            continue
                        if self.first_audio is None:
                            self.first_audio = time.time()
                            self.note("Entendu", self.heard)
                            self.heard = ""
                        if self.thanked:           # pas de « je vous en prie »
                            continue
                        self.speaker.write(p.inline_data.data)
                        self.last_activity = time.time()
                if sc.interrupted:
                    self.speaker.flush()
                if sc.turn_complete or sc.interrupted:
                    self.note("3PO", self.said)
                    self.said = ""
                    self.first_audio = None

    async def watchdog(self, session):
        while True:
            await asyncio.sleep(0.3)
            now = time.time()
            if self.thanked and now - self.heard_at > THANKS_WAIT:
                self.note("Entendu", self.heard)
                log("   (merci : pause)")
                self.speaker.flush()
                self.pause = "merci"
                return
            if self.speaker.talking:
                self.last_activity = now
                continue
            if now - self.last_activity > IDLE:
                log("   (rien depuis %.0f s : pause)" % IDLE)
                await self.say_pause(session)
                self.pause = "silence"
                return

    async def say_pause(self, session):
        """Annonce la pause, puis attend que le robot ait fini de parler."""
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=PAUSE_TEXT)]),
            turn_complete=True)
        started = False
        for _ in range(50):          # 10 s au plus
            await asyncio.sleep(0.2)
            if self.speaker.talking:
                started = True
            elif started:
                return

    async def listen(self, link, q):
        """Une période d'attention : sessions Gemini reprises jusqu'à la pause."""
        self.handle, self.pause, failures = None, None, 0
        self.last_activity = time.time()
        self.heard = self.said = ""
        self.heard_at, self.thanked, self.first_audio = 0.0, False, None
        try:
            while self.pause is None:
                config = self.config.model_copy(update={
                    "session_resumption": types.SessionResumptionConfig(handle=self.handle)})
                try:
                    async with self.client.aio.live.connect(model=MODEL, config=config) as session:
                        log("à l'écoute : %s%s" % (MODEL, " (reprise)" if self.handle else ""))
                        failures = 0
                        tasks = [asyncio.create_task(self.mic(session, q)),
                                 asyncio.create_task(self.receive(session)),
                                 asyncio.create_task(self.watchdog(session))]
                        try:
                            done, _ = await asyncio.wait(tasks,
                                                         return_when=asyncio.FIRST_COMPLETED)
                            for t in done:
                                t.result()
                        finally:
                            for t in tasks:
                                t.cancel()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    failures += 1
                    log("   session Gemini fermée (%s : %s)" % (e.__class__.__name__, e))
                    if failures >= MAX_RESUME:
                        log("   abandon après %d échecs" % failures)
                        break
                    if failures > 1:        # la reprise elle-même échoue : session neuve
                        self.handle = None
                    await asyncio.sleep(1)
        finally:
            link.send("end")
            log("en pause (%s)" % (self.pause or "bouton ou erreur"))
            if self.transcript:
                self.transcript.write("---\n")
                self.transcript.flush()

    async def run_robot(self, host, port):
        """Reste connecté au robot (comme live.py) : délai croissant, journal discret."""
        delay, since, told = 3, None, 0
        while True:
            err = "fin"
            try:
                await self.serve_robot(host, port)
            except (asyncio.IncompleteReadError, OSError) as e:
                err = e.__class__.__name__
            if self.speaker.connected:
                delay, since = 3, None
            now = time.time()
            if since is None:
                since = told = now
                log("robot déconnecté (%s), nouveaux essais en silence" % err)
            elif now - told >= 3600:
                told = now
                log("robot toujours injoignable depuis %.0f h" % ((now - since) / 3600))
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def serve_robot(self, host, port):
        link = self.speaker = RobotLink(host, port)
        await link.connect()
        log("connecté au robot %s:%d, 3PO en pause" % (host, port))
        task = q = None
        async for head, data in link.frames():
            if task and task.done():
                task = q = None
            cmd = head.get("cmd")
            if cmd == "mic":
                if q is not None:
                    x = np.frombuffer(data, dtype=np.int16).astype(np.float32) * self.gain
                    x = 32767 * np.tanh(x / 32767)      # écrêtage doux
                    q.put_nowait(x.astype(np.int16).tobytes())
            elif cmd == "config":       # réglages de la page web du robot
                self.gain = float(head["gain"])
                self.speech_rms = 32768 * 10 ** (float(head["threshold"]) / 20)
                self.gate = bool(head["gate"])
                log("   (micro : gain x%.0f, seuil %.0f dBFS, porte %s)"
                    % (self.gain, head["threshold"], "oui" if self.gate else "non"))
            elif cmd == "quiet":
                link.talking = False
                self.last_activity = time.time()
            elif cmd == "event":
                name = head.get("name")
                log("   (robot : %s)" % name)
                if name in ("prepare", "talk") and task is None:
                    q = asyncio.Queue()
                    task = asyncio.create_task(self.listen(link, q))
                elif name == "abort" and task:
                    task.cancel()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--prompt", default=DEFAULT_PROMPT, help="fichier texte des consignes")
    p.add_argument("--voice", default="Puck", help="Puck, Leda, Aoede, Kore, Charon...")
    p.add_argument("--robot", metavar="HÔTE[:PORT]", required=True,
                   help="pont audio du robot (robot_audio.py --prefix 3PO)")
    p.add_argument("--gain", type=float, default=ROBOT_GAIN,
                   help="gain appliqué au micro du robot (%(default)s)")
    args = p.parse_args()
    with open(args.prompt, encoding="utf-8") as f:
        system = f.read()
    c = Companion(system, args.voice, args.gain)
    host, _, port = args.robot.partition(":")
    try:
        asyncio.run(c.run_robot(host, int(port or ROBOT_PORT)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
