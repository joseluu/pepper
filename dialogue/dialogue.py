"""Dialogue parlé avec Pepper : micro USB du robot -> STT -> LLM -> TTS -> haut-parleurs.

Tourne sur le PC (WSL). Le robot exécute robot_audio.py (pont audio, port 8090)
et ce programme s'y connecte (sous WSL le robot ne peut pas joindre le PC).

  Transcription : Google Speech-to-Text v2 en continu (chirp_3, fr-FR, région eu),
                  fin de phrase = fin de parole détectée par Google + morceau final
  Dialogue      : Gemini sur Vertex AI (gemini-2.5-flash, sans réflexion)
  Voix          : Google Text-to-Speech, voix française Chirp 3 HD

Identifiants : `gcloud auth application-default login` (projet m2if-270422).

Lancer :
  uv run dialogue.py                        # avec le robot
  uv run dialogue.py --file question.wav    # test sans robot : WAV 16 kHz mono,
                                            # réponses écrites dans out/
  uv run dialogue.py --prompt ../halloween/preprompt_dialogue.txt   # autres consignes
"""
import argparse
import json
import os
import queue
import re
import socket
import struct
import threading
import time
import wave

from google.api_core.client_options import ClientOptions
from google.cloud import texttospeech as tts
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech as cs
from google import genai
from google.genai import types

PROJECT = "m2if-270422"
STT_LOCATION = "eu"
STT_MODEL = "chirp_3"
LLM_MODEL = "gemini-2.5-flash"
VOICE = "fr-FR-Chirp3-HD-Leda"
RATE = 16000
CHUNK = 3200                      # 100 ms de PCM 16 bits mono
STREAM_MAX = 240                  # relance du flux STT avant la limite de 5 min
END_SILENCE = 0.4                 # fin de la phrase : ni parole ni résultat depuis (s)
HERE = os.path.dirname(os.path.abspath(__file__))

EYES_LISTEN = "0x0060ff"          # bleu : j'écoute
EYES_THINK = "0xff8000"           # orange : je réfléchis

SYSTEM = """Tu es Pepper, un robot humanoïde gentil et joueur qui discute avec des
enfants (environ 4 à 10 ans), en français.
- Réponds en une ou deux phrases courtes, avec des mots simples. Ta réponse est
  lue à voix haute : pas d'emoji, pas de liste, pas de mise en forme.
- Sois chaleureux, curieux, encourageant ; pose parfois une petite question pour
  relancer la conversation.
- La transcription de la voix peut contenir des erreurs : si la phrase n'a pas de
  sens, demande gentiment de répéter.
- Ne demande jamais d'informations personnelles (nom de famille, adresse, école,
  téléphone). Évite les sujets effrayants, violents ou réservés aux adultes : change
  de sujet avec douceur. Pour un problème sérieux (blessure, danger, tristesse),
  conseille d'aller voir un adulte.
"""


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def for_speech(text):
    """Retire ce qui ne se prononce pas (mise en forme, emojis)."""
    text = re.sub(r"[*_#`~>\[\]]", "", text)
    text = re.sub(r"[^\w\s.,;:!?'’«»\"()\-–—%€°]", "", text)
    return re.sub(r"\s+", " ", text).strip()


# --- sources de son -------------------------------------------------------

class RobotLink:
    """Connexion au pont audio du robot (robot_audio.py)."""

    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(None)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.lock = threading.Lock()

    def read(self):
        data = self.sock.recv(CHUNK)
        if not data:
            raise EOFError("robot déconnecté")
        return data

    def send(self, head, data=b""):
        head = dict(head, size=len(data))
        h = json.dumps(head).encode()
        with self.lock:
            self.sock.sendall(struct.pack(">I", len(h)) + h + data)

    def play(self, wav):
        self.send({"cmd": "play"}, wav)

    def eyes(self, color):
        self.send({"cmd": "eyes", "color": color})


class FileLink:
    """Test sans robot : rejoue un WAV au rythme réel, écrit les réponses dans out/."""

    def __init__(self, path):
        w = wave.open(path)
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (RATE, 1, 2), \
            "WAV attendu : 16 kHz, mono, 16 bits"
        # 1 s de silence avant, 4 s après pour laisser finir la réponse
        self.pcm = b"\0" * RATE * 2 + w.readframes(w.getnframes()) + b"\0" * RATE * 8
        self.pos = 0
        self.n = 0
        os.makedirs(os.path.join(HERE, "out"), exist_ok=True)

    def read(self):
        if self.pos >= len(self.pcm):
            raise EOFError("fin du fichier")
        time.sleep(CHUNK / 2 / RATE)
        data = self.pcm[self.pos:self.pos + CHUNK]
        self.pos += CHUNK
        return data

    def play(self, wav):
        self.n += 1
        path = os.path.join(HERE, "out", "reponse_%d.wav" % self.n)
        with open(path, "wb") as f:
            f.write(wav)
        log("   (réponse écrite dans %s)" % os.path.relpath(path, HERE))

    def eyes(self, color):
        pass


# --- dialogue -------------------------------------------------------------

class Dialogue:
    def __init__(self, link, voice, system=SYSTEM):
        self.link = link
        self.audio = queue.Queue(maxsize=200)
        self.busy_until = 0.0        # on ignore ce qui est entendu jusque-là
        self.stt = SpeechClient(client_options=ClientOptions(
            api_endpoint="%s-speech.googleapis.com" % STT_LOCATION))
        self.tts = tts.TextToSpeechClient()
        self.voice = tts.VoiceSelectionParams(language_code="fr-FR", name=voice)
        self.pending = []            # morceaux de phrase finalisés, pas encore traités
        self.last_heard = 0.0        # dernier résultat ou événement STT
        self.speaking = False        # l'enfant parle (détection de parole Google)
        self.lock = threading.Lock()
        self.ended = False
        # garder une référence au client : sinon il est fermé par le ramasse-miettes
        self.llm = genai.Client(vertexai=True, project=PROJECT, location="global")
        self.chat = self.llm.chats.create(model=LLM_MODEL, config=types.GenerateContentConfig(
            system_instruction=system, temperature=0.8, max_output_tokens=200,
            thinking_config=types.ThinkingConfig(thinking_budget=0)))
        self.transcript = open(os.path.join(HERE, "logs", time.strftime("%Y%m%d-%H%M%S.txt")),
                               "a", encoding="utf-8") if os.path.isdir(os.path.join(HERE, "logs")) else None

    def note(self, who, text):
        log("%s : %s" % (who, text))
        if self.transcript:
            self.transcript.write("%s %s : %s\n" % (time.strftime("%H:%M:%S"), who, text))
            self.transcript.flush()

    def reader(self):
        try:
            while True:
                self.audio.put(self.link.read())
        except (EOFError, OSError) as e:
            log("son : %s" % e)
            self.audio.put(None)

    def requests(self, deadline):
        cfg = cs.StreamingRecognitionConfig(
            config=cs.RecognitionConfig(
                explicit_decoding_config=cs.ExplicitDecodingConfig(
                    encoding=cs.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                    sample_rate_hertz=RATE, audio_channel_count=1),
                language_codes=["fr-FR"], model=STT_MODEL),
            streaming_features=cs.StreamingRecognitionFeatures(
                interim_results=True, enable_voice_activity_events=True))
        yield cs.StreamingRecognizeRequest(
            recognizer="projects/%s/locations/%s/recognizers/_" % (PROJECT, STT_LOCATION),
            streaming_config=cfg)
        while time.time() < deadline:
            data = self.audio.get()
            if data is None:
                self.ended = True
                return
            yield cs.StreamingRecognizeRequest(audio=data)

    def answer(self, heard):
        t0 = time.time()
        self.link.eyes(EYES_THINK)
        try:
            reply = for_speech(self.chat.send_message(heard).text or "")
        except Exception as e:
            log("LLM : %s" % e)
            reply = "Oups, je n'ai pas bien compris. Tu peux répéter ?"
        t1 = time.time()
        self.note("Pepper", reply)
        wav = self.tts.synthesize_speech(
            input=tts.SynthesisInput(text=reply), voice=self.voice,
            audio_config=tts.AudioConfig(audio_encoding=tts.AudioEncoding.LINEAR16,
                                         sample_rate_hertz=24000)).audio_content
        t2 = time.time()
        duration = (len(wav) - 44) / 2.0 / 24000
        log("   LLM %.1f s, voix %.1f s, durée %.1f s" % (t1 - t0, t2 - t1, duration))
        self.link.play(wav)
        self.busy_until = time.time() + duration + 0.5
        self.link.eyes(EYES_LISTEN)

    def listen(self):
        """Flux STT (relancé toutes les STREAM_MAX s) : remplit self.pending."""
        while not self.ended:
            responses = self.stt.streaming_recognize(
                requests=self.requests(time.time() + STREAM_MAX))
            for r in responses:
                # chirp_3 coupe les phrases aux pauses : un morceau final suivi
                # aussitôt d'un début de parole n'est pas la fin de la phrase
                ev = r.speech_event_type
                if ev:
                    with self.lock:
                        self.last_heard = time.time()
                        if ev == cs.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_BEGIN:
                            self.speaking = True
                        elif ev == cs.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_END:
                            self.speaking = False
                for res in r.results:
                    if not res.alternatives:
                        continue
                    text = res.alternatives[0].transcript.strip()
                    if not text:
                        continue
                    if time.time() < self.busy_until:
                        if res.is_final:
                            log("   (ignoré pendant que Pepper parle : %s)" % text)
                        continue
                    with self.lock:
                        self.last_heard = time.time()
                        if res.is_final:
                            self.pending.append(text)

    def run(self):
        threading.Thread(target=self.reader, daemon=True).start()
        threading.Thread(target=self.listen, daemon=True).start()
        self.link.eyes(EYES_LISTEN)
        log("j'écoute (Ctrl+C pour arrêter)")
        while not self.ended:
            time.sleep(0.1)
            with self.lock:
                if (not self.pending or self.speaking
                        or time.time() - self.last_heard < END_SILENCE):
                    continue
                heard = " ".join(self.pending)
                self.pending = []
            self.note("Enfant", heard)
            self.answer(heard)
        time.sleep(1)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--robot", default="pepper:8090",
                   help="hôte:port du pont audio (le nom court suffit sur le LAN)")
    p.add_argument("--file", help="WAV 16 kHz mono à la place du robot (test)")
    p.add_argument("--voice", default=VOICE)
    p.add_argument("--prompt", help="fichier texte des consignes du LLM (sinon SYSTEM)")
    args = p.parse_args()
    if args.file:
        link = FileLink(args.file)
    else:
        host, port = args.robot.rsplit(":", 1)
        link = RobotLink(host, int(port))
    try:
        system = SYSTEM
        if args.prompt:
            with open(args.prompt, encoding="utf-8") as f:
                system = f.read()
        Dialogue(link, args.voice, system).run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
