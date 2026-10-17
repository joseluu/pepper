#!/usr/bin/env python3
# Genere siren.wav : sirene de police americaine ("wail"), un cycle de 6 s
# qui boucle sans coupure (frequence moyenne x duree = nombre entier de tours,
# donc la phase retombe exactement sur un multiple de 2*pi).
import math, struct, wave

RATE, T = 48000, 6.0
F0, F1 = 650.0, 1500.0           # Hz bas / haut
n = int(RATE * T)
phase, frames = 0.0, bytearray()
for i in range(n):
    t = i / RATE
    f = F0 + (F1 - F0) * (0.5 - 0.5 * math.cos(2 * math.pi * t / T))
    phase += 2 * math.pi * f / RATE
    # un peu d'harmoniques et d'ecretage pour le cote "haut-parleur de sirene"
    x = math.sin(phase) + 0.35 * math.sin(2 * phase) + 0.2 * math.sin(3 * phase)
    x = max(-1.0, min(1.0, 1.4 * x)) * 0.9
    v = int(x * 32767)
    frames += struct.pack("<hh", v, v)
w = wave.open("siren.wav", "wb")
w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE)
w.writeframes(bytes(frames)); w.close()
