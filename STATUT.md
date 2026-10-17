# Statut matériel — Pepper

Dernière vérification : 2026-10-17 (boot observé, log `/var/log/firmware/firmware.log`).

## En panne / ne répond pas

| Carte                       | Symptôme                                                        | Firmware attendu |
|-----------------------------|-----------------------------------------------------------------|------------------|
| Chestboard (torse)          | `NACK` au démarrage → déclenche un reflash complet à chaque boot (voir plus bas). Répond normalement une fois démarrée (0.2.0.41). Suspectée. | 0.2.0.41 |
| Touchboard                  | `NACK` / `onboard: 0.0`, flash échoue : `write error on SMBUS firmware: 42` (répété), `Touchboard flashing status: 2` | 0.7 |
| Inertialboard (Torso)       | `NACK` (l'inertielle de la base répond, 0.32). Confirmé dans ALMemory : `InertialSensor/AngleX,Y` figés à 0.000, accéléro/gyro absents. `InertialSensorBase` OK (AccZ ≈ -9.0). | 0.32 |
| Fuseboard                   | `NACK`                                                          | 0.2 |

## Conséquence : reflash complet à chaque boot

`/opt/aldebaran/libexec/firmware/firmware-update.sh` force `firmware-update -fa`
si `chest-mode` échoue au démarrage :

```sh
if ! chest-mode &>/dev/null ; then
  force_all_fw_reflash=true
```

La chestboard ne répondant pas à ce moment-là, toutes les cartes sont reflashées
à chaque boot, avec le même firmware que celui déjà présent (aucun changement).
NAOqi ne démarre qu'après : **~8 min de boot** au lieu de ~2. Sans danger, mais
**ne pas couper le robot pendant le flash**.

## OK (version embarquée = fichier)

Moteurs (Hip/Thigh/Platform 79, Head/Shoulder/Arm/Hand 101), HubBoard 26,
Faceboard 0.26, lasers Front/Left/Right 352, Inertialboard Base 0.32,
Multifuseboard 0.3, Fanboard 0.4.

## Autres points à surveiller

- Bras gauche : en redescendant des bras levés, il ne suit pas tout de suite
  (observé à l'œil, 2026-10-17). Peut-être un embrayage / problème mécanique.
- Chauffe si une posture est tenue moteurs actifs : tête baissée tenue →
  HeadPitch 74 °C, `Warning 720` (épaules qui clignotent en jaune). Accroupi à
  fond → HipPitch tire ~1.5 A. Relâcher la tête et pencher moins le buste.

- Partition racine `/` à 97 % (51 Mo libres).
