# -*- coding: utf-8 -*-
"""Genere chirp.wav : petit signal discret (0,3 s) quand 3PO devient attentif.

Glissement montant de 1500 a 2500 Hz, attaque et chute en cosinus (pas de
clic), a -20 dBFS. WAV 48 kHz mono 16 bits, comme les sons du fantome.
Bibliotheque standard seulement : python3 make_chirp.py
"""
import math, os, struct, wave

RATE = 48000
DUR = 0.3
F0, F1 = 1500.0, 2500.0
AMP = 10 ** (-20 / 20.0)
FADE = 0.06                      # s d'attaque et de chute

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chirp.wav")
n = int(RATE * DUR)
phase, frames = 0.0, []
for i in range(n):
    t = i / float(RATE)
    f = F0 + (F1 - F0) * t / DUR
    phase += 2 * math.pi * f / RATE
    env = 1.0
    if t < FADE:
        env = 0.5 - 0.5 * math.cos(math.pi * t / FADE)
    elif t > DUR - FADE:
        env = 0.5 - 0.5 * math.cos(math.pi * (DUR - t) / FADE)
    frames.append(struct.pack("<h", int(32767 * AMP * env * math.sin(phase))))
w = wave.open(out, "wb")
w.setnchannels(1)
w.setsampwidth(2)
w.setframerate(RATE)
w.writeframes(b"".join(frames))
w.close()
print("%s : %.2f s" % (out, DUR))
