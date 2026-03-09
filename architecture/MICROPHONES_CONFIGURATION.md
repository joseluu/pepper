# Pepper Microphone Configuration

4 directional microphones in the head, arranged in a rectangular array.

| Mic ID   | Position    | X (m)   | Y (m)    | Z (m)  |
|----------|-------------|---------|----------|--------|
| MicroFL  | Front Left  | 0.0313  | 0.0343   | 0.2066 |
| MicroFR  | Front Right | 0.0313  | -0.0343  | 0.2066 |
| MicroRL  | Back Left   | -0.0267 | 0.0343   | 0.2066 |
| MicroRR  | Back Right  | -0.0267 | -0.0343  | 0.2066 |

Spacing: ~6.86 cm left-right, ~5.8 cm front-back.

## Specs

- Sensitivity: 300 mV/Pa (±3 dB @ 1 kHz)
- Frequency range: 300 Hz – 12 kHz (-10 dB relative to 1 kHz)

## NAOqi Service

`ALSoundLocalization` — uses the 4-mic array to determine sound source direction.
