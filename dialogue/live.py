# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "sounddevice", "numpy"]
# ///
"""Dialogue parlé avec Gemini Live (voix -> voix, un seul modèle, en continu).

Variante de dialogue.py (STT -> LLM texte -> TTS) pour réduire la latence :
le son du micro est envoyé en continu à Gemini Live, qui détecte la fin de la
phrase et répond directement en voix (24 kHz), jouée au fil de l'arrivée.

  Modèle : gemini-live-2.5-flash-native-audio (Vertex AI, europe-west4)

Pour l'instant : micro et haut-parleurs du PC. À lancer **sous Windows** : la
sortie son de WSLg hache et se bloque (voir STATUT_HALLOWEEN.md). Sous Windows
le son passe par sounddevice (PortAudio) ; la sortie lit une file remplie au fil
de l'arrivée, ce qui donne aussi l'instant exact où Pepper finit de parler.

Pendant que Pepper parle, le micro est remplacé par du silence (sinon, avec des
haut-parleurs, il s'entend et se coupe lui-même) ; --barge-in le désactive
(avec un casque : l'enfant peut alors couper la parole à Pepper).

Lancer depuis WSL (Python et son de Windows, identifiants Google de WSL) :
  ./live_windows.sh --prompt ../halloween/preprompt_dialogue.txt
Directement sous Windows :
  uv run --script live.py --prompt ..\\halloween\\preprompt_dialogue.txt
"""
import argparse
import asyncio
import os
import threading
import time

import numpy as np
import sounddevice as sd
from google import genai
from google.genai import types

PROJECT = "m2if-270422"
LOCATION = "europe-west4"
MODEL = "gemini-live-2.5-flash-native-audio"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROMPT = os.path.join(HERE, "..", "halloween", "preprompt_dialogue.txt")
HELLO = ("(Consigne, ce n'est pas un enfant qui parle : un enfant vient d'arriver devant "
         "toi. Salue-le et engage la conversation, en une ou deux phrases.)")
IN_RATE = 16000
OUT_RATE = 24000
CHUNK = 1600                     # 100 ms de micro à 16 kHz
TAIL = 0.4                       # micro coupé encore TAIL s après la fin de la parole
SPEECH_RMS = 500                 # au-dessus : quelqu'un parle (pour mesurer la latence)


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

    def flush(self):
        """Coupe net (l'enfant a interrompu Pepper)."""
        with self.lock:
            self.buf.clear()


class Live:
    def __init__(self, system, voice, barge_in, mic_device, out_device):
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
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=500)))
        self.barge_in = barge_in
        self.mic_device = mic_device
        self.speaker = Speaker(out_device)
        self.last_voice = 0.0        # dernier morceau de micro avec de la voix
        self.heard = ""
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

    async def mic(self, session):
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()

        def callback(indata, frames, time_info, status):
            loop.call_soon_threadsafe(q.put_nowait, bytes(indata))

        with sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16",
                               blocksize=CHUNK, device=self.mic_device, callback=callback):
            while True:
                data = await q.get()
                if not self.barge_in and self.speaker.speaking():
                    data = b"\0" * len(data)
                else:
                    x = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    if np.sqrt(np.mean(x * x)) > SPEECH_RMS:
                        self.last_voice = time.time()
                await session.send_realtime_input(
                    audio=types.Blob(data=data, mime_type="audio/pcm;rate=%d" % IN_RATE))

    async def receive(self, session):
        while True:
            async for r in session.receive():
                if r.go_away:
                    log("   (Gemini va fermer la session dans %s)" % r.go_away.time_left)
                sc = r.server_content
                if not sc:
                    continue
                if sc.input_transcription and sc.input_transcription.text:
                    self.heard += sc.input_transcription.text
                if sc.output_transcription and sc.output_transcription.text:
                    self.said += sc.output_transcription.text
                if sc.model_turn:
                    for p in sc.model_turn.parts:
                        if p.inline_data and p.inline_data.data:
                            if self.first_audio is None:
                                self.first_audio = time.time()
                                self.note("Enfant", self.heard)
                                self.heard = ""
                                if self.last_voice:
                                    log("   latence : %.1f s après la fin de la voix"
                                        % (self.first_audio - self.last_voice))
                            self.speaker.write(p.inline_data.data)
                if sc.interrupted:
                    log("   (interrompu)")
                    self.speaker.flush()
                if sc.turn_complete or sc.interrupted:
                    self.note("Pepper", self.said)
                    if self.speaker.underruns:
                        log("   (sortie son : %d manques de données)" % self.speaker.underruns)
                        self.speaker.underruns = 0
                    self.said = ""
                    self.first_audio = None

    async def run(self):
        async with self.client.aio.live.connect(model=MODEL, config=self.config) as session:
            log("connecté à %s, j'écoute (Ctrl+C pour arrêter)" % MODEL)
            log("   micro : %s" % sd.query_devices(self.mic_device, "input")["name"])
            log("   sortie : %s" % sd.query_devices(self.speaker.stream.device)["name"])
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=HELLO)]),
                turn_complete=True)
            await asyncio.gather(self.mic(session), self.receive(session))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--prompt", default=DEFAULT_PROMPT, help="fichier texte des consignes")
    p.add_argument("--voice", default="Leda", help="Leda, Aoede, Kore, Puck, Charon...")
    p.add_argument("--barge-in", action="store_true",
                   help="micro ouvert pendant que Pepper parle (avec un casque)")
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
    try:
        asyncio.run(Live(system, args.voice, args.barge_in, dev(args.mic), dev(args.out)).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
