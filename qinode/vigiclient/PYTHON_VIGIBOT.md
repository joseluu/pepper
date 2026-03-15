# vigiclient.py - Vigibot client Python pour Pepper

## Architecture

Client Python 2.7 se connectant directement au SDK NAOqi via `qi.Session()`, sans passer par le bridge qimessaging-json (qui avait des limitations fatales : arrays silencieusement ignores, wakeUp non persistant).

### Composants

1. **Socket.IO 2.x / Engine.IO 3** - Implementation manuelle sur `websocket-client` 0.59.0
   - Handshake EIO=3 via WebSocket direct (pas de polling)
   - Gestion ping/pong, events JSON, events binaires (placeholders + attachments)
   - Prefix `\x04` sur les frames binaires sortantes (EIO message type)
   - Strip du prefix `\x04` sur les frames binaires entrantes

2. **Protocole de trames binaires** (port de `trame.js`)
   - `TxFrame` : trame de commande entrante (serveur -> robot)
   - `RxFrame` : trame de reponse sortante (robot -> serveur)
   - Layout : `[sync][cmd32][val32][cmd16][val16][cam][cmd8][cmd1][val8]`
   - Little-endian, packed via `struct.pack_into` / `struct.unpack_from`

3. **NAOqi direct** via `qi.Session('tcp://127.0.0.1:9559')`
   - `ALMotion` : wakeUp, setAngles, setStiffnesses
   - `ALBattery` : getBatteryCharge
   - `ALTextToSpeech` : say
   - `ALAutonomousLife` : disabled au demarrage
   - `ALVideoDevice` : release des subscribers au demarrage

4. **Moteur de ramping** - port fidele du servo loop Node.js
   - RAMPUP / RAMPDOWN / RAMPINIT par commande
   - Failsafe sur alarme de latence (seuils LATENCYALARMBEGIN/END)
   - Tick a SERVORATE (50ms)

### Mapping tete Pepper

| COMMANDS16 | Joint      | Conversion        |
|------------|------------|-------------------|
| [0] Turret X | HeadYaw  | degres -> radians |
| [1] Turret Y | HeadPitch | degres -> radians |

Vitesse : 0.3 (parametre HEAD_SPEED)

### Timers

| Timer     | Intervalle | Fonction                        |
|-----------|------------|---------------------------------|
| servo     | 50ms       | Ramping + apply motor commands  |
| beacon    | 1000ms     | Envoi RX quand idle             |
| cpu       | 2000ms     | Lecture /proc/stat              |
| temp      | 5000ms     | Lecture thermal_zone0           |
| wifi      | 5000ms     | Lecture /proc/net/wireless      |
| battery   | 5000ms     | getBatteryCharge via NAOqi      |
| keepalive | 10s        | Refresh stiffness tete          |

## Dependances

- `websocket-client` 0.59.0 (installe dans `/data/vigiclient/lib`)
- `six` (dependance de websocket-client)
- SDK qi (`/opt/aldebaran/lib/python2.7/site-packages`)

## Deploiement

```bash
# Installer websocket-client
ssh memmer "pip install --target=/data/vigiclient/lib 'websocket-client==0.59.0'"

# Copier le script
scp vigiclient.py memmer:/data/vigiclient/

# Lancer
ssh memmer "cd /data/vigiclient && PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages nohup python2 -u vigiclient.py > /tmp/vigiclient_stdout.log 2>&1 &"
```

Note : le flag `-u` est necessaire (stdout buffered en Python 2 quand pas de TTY).

## Etat actuel

- **Phase 1 (fait)** : connexion vigibot, controle tete, wake/sleep, beacon RX, TTS, sensors
- **Phase 2 (a faire)** : video streaming (ffmpeg -> TCP -> serveurrobotvideo)
- **Phase 3 (a faire)** : parite complete (sys commands, camera switch, audio)

## Compatibilite Python 3

Ecrit en Python 2.7 avec un minimum de specificites 2.7 :
- `print()` utilise comme fonction (compatible 2/3)
- `//` pour division entiere
- `sys.stdout.flush()` explicite
- `bytes`/`str` : en Python 2 ce sont le meme type ; adapter pour Python 3
- `dict.items()` : retourne une liste en 2.7, un view en 3.x (pas de probleme)
