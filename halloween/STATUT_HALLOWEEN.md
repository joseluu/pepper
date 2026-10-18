# Fantôme d'Halloween — statut et notes de reprise

Dernière mise à jour : 2026-10-17, 23h45. Robot : **pepper** uniquement.

## Objectif

Pepper, sous un drap blanc, dehors et immobile, joue le fantôme :

- **En attente** : posture affaissée, **toutes les LED éteintes**, rien ne doit
  trahir l'électronique sous le drap. Les doigts bougent un peu en permanence.
- **Quelqu'un passe à moins de 1,5 m devant lui** (détecté par les lidars du
  pied) : yeux et épaules en rouge, il se redresse vite, lève les bras par
  devant, et joue le rire de Thriller (Michael Jackson).
- Puis il revient en attente et se ré-arme.

## État actuel

| Élément | État |
|---|---|
| Script `halloween.py` | ✅ fonctionne, validé par plusieurs déclenchements réels et en test |
| Détection lidar | ✅ fonctionne (premier déclenchement réel à ~0,6 m) |
| Mouvement BOUH | ✅ bras tendus par devant à 110°, paumes vers le sol (validé), coudes arrondis (validé), bras écartés de 30° + bras haut/bas en opposition (validé) |
| LED | ✅ yeux + épaules en rouge ; oreilles éteintes (choix de l'utilisateur, elles n'ont que du bleu) |
| Chauffe en attente | ⚠️ corrigée (tête relâchée, buste à demi penché), à surveiller sur une longue durée |
| Démarrage automatique au boot | ❌ pas installé : il faut le lancer à la main (voir plus bas) |
| Alarme anti-vol (sirène) | ✅ testée sur le robot le 2026-10-18 : déclenche quand on le porte (même à plat), pas quand on le fait rouler, pivoter ou passer un seuil, ni pendant un BOUH |
| Connexion | ✅ WiFi seul suffit (`ssh pepper`) ; câble réseau et tablette débranchés |

## Fichiers

Dans le dépôt (`halloween/`) et sur le robot (`/home/nao/halloween/`) :

| Fichier | Rôle |
|---|---|
| `halloween.py` | Le programme (Python 2.7 + `qi`, tourne **sur le robot**) |
| `thriller_laugh.wav` | Le rire (12,3 s, WAV 48 kHz stéréo), converti depuis `%USERPROFILE%\Downloads\Thriller End Laugh - rire (36).mp3` avec ffmpeg (sans la pochette) |
| `temps.py` | Relevé de température + état des moteurs à risque (cou, hanches, genoux) |
| `antivol.py` | Alarme anti-vol (module importé par `halloween.py`) |
| `siren.wav` | Sirène de police « wail » synthétisée (6 s, boucle sans coupure) |
| `make_siren.py` | Régénère `siren.wav` (Python 3, sur le PC) |
| `simu_antivol.py` | Simulation hors robot de la détection anti-vol (Python 3) |
| `web.py` | Page d'état sur http://pepper.<domaine-lan>:8080/ : lidar avant, batterie, état de l'alarme, bouton « Arrêter la sirène » (stdlib, pas de Flask sur le robot) |
| `record_imu.py` | Enregistre centrale de la base + roues + pare-chocs en CSV (`python2 record_imu.py f.csv 180`, fantôme arrêté) |
| `TODO.md` | Plan de test de l'alarme anti-vol |
| `run.log` (robot seulement) | Journal du programme (détections, BOUH) |

`/data` n'est **pas** inscriptible par `nao` (seul `/data/home/nao` l'est), d'où
l'installation dans `~/halloween`.

## Commandes

```bash
# Déployer depuis le PC
cd halloween && scp halloween.py antivol.py temps.py thriller_laugh.wav siren.wav pepper:halloween/

# Lancer en mode détection (attend qu'on passe devant)
ssh pepper 'cd ~/halloween && PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages setsid nohup python2 halloween.py > run.log 2>&1 < /dev/null &'

# Déclencher une fois tout de suite (test), puis le script s'arrête
#   ... python2 halloween.py --test
# Options : --dist 1.5 (seuil m), --volume 85, --cooldown 5 (s après un BOUH),
#           --phrase "Trick or treat!" (dite après le rire)
#           --no-alarm, --alarm-tilt 8 (deg), --alarm-debug, --test-alarm

# Désarmer la sirène anti-vol (ré-armement 30 s plus tard)
ssh pepper 'touch ~/halloween/desarme'

# Journal
ssh pepper 'grep -v -E "sdklayout|transportsocket" ~/halloween/run.log'

# Arrêter (pkill DANS SA PROPRE commande ssh, voir les pièges)
ssh pepper 'pkill -f "[p]ython2 halloween"'
# puis mettre au repos si besoin : ALMotion.rest()

# Températures
ssh pepper 'PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages python2 ~/halloween/temps.py 2>/dev/null | grep HeadPitch'
```

Au lancement, il faut ~15 s avant « fantome en place » : c'est le `wakeUp()`.

## Fonctionnement du script

1. **Calme l'autonomie** : `ALAutonomousLife` → `disabled`, et désactive
   `ALBackgroundMovement`, `ALAutonomousBlinking`, `ALListeningMovement`,
   `ALSpeakingMovement` et `ALBasicAwareness`. Il le refait toutes les 30 s, car
   le timer `pepper-keepawake` (toutes les 6 h) réactive `ALBackgroundMovement`.
   Il éteint aussi les LED toutes les 30 s (les épaules clignotent sur les alertes).
   Si le robot est passé au repos tout seul, il le réveille.
2. **Posture d'attente** (`REST`) : bras pendants (angles relevés après
   `motion.rest()`), **HipPitch -0,20 / KneePitch 0,10** (genou = -hanche/2), puis **tête relâchée**
   (stiffness 0) : elle reste en avant (HeadPitch ≈ 0,75), car elle part de 0,70 et les frottements la retiennent.
   Puis consigne HipRoll = sa position réelle (voir chauffe HipRoll).
3. **Doigts** : toutes les 2 s, LHand/RHand alternent entre 0,5 et 0,7 en
   opposition, très lentement (vitesse 0,08).
4. **Détection** (10 Hz) : lit les 15 segments du lidar **avant**
   (`Device/SubDeviceList/Platform/LaserSensor/Front/Horizontal/SegNN/{X,Y}/Sensor/Value`),
   distance = hypot(X, Y). Déclenche si **≥ 2 segments** sont à la fois
   - entre 0,30 m (en dessous : le drap ou le robot, ignoré) et 1,5 m,
   - plus proches d'au moins 0,30 m que leur valeur de fond,

   et cela sur **2 lectures consécutives**. Le fond est la première lecture,
   puis il s'adapte lentement (moyenne glissante, alpha 0,02 ≈ 5 s) : une
   personne qui reste immobile finit par faire partie du décor. Le fond est
   remis à zéro après chaque BOUH.
5. **BOUH** :
   - raidit la tête, yeux (`FaceLeds`) et épaules (`ChestLeds`) en rouge (appels
     synchrones), volume réglé à 85 ;
   - lance le WAV en asynchrone (`ALAudioPlayer.playFile(..., _async=True)`) ;
   - redressement (HipPitch -0,03, Knee 0, tête -0,30) et **bras tendus par
     devant à 110°** (ShoulderPitch -0,35 ; 0 = horizontal) en 0,8 s,
     **ElbowYaw = WristYaw = 0 → paumes vers le sol** (confirmé à l'œil), mains
     ouvertes. Les articulations *Roll bougent en 0,4 s : **coudes un peu pliés
     vers l'extérieur** (ElbowRoll ∓0,45, validé) et **épaules écartées de 30°**
     (ShoulderRoll ±0,52 = 20° + 10° demandés en plus) dès le
     début de la montée, pour des bras arrondis, moins rigides ;
   - pendant le rire (~11 s) : **balancement des hanches ±5°** (HipRoll ±0,087,
     toutes les 0,9 s) et **bras qui montent et descendent de ±5°**
     (ShoulderPitch -0,35 ± 0,087) **en opposition de phase** (l'un monte quand
     l'autre descend), puis HipRoll revient à 0. Avant : ondulation
     droite-gauche des épaules (ShoulderRoll), remplacée à la demande.
   - Version précédente : bras presque verticaux (ShoulderPitch -1,30, roll
     ±0,35, ElbowYaw/WristYaw ∓1,20) : trop haut.
   - Historique : une variante « bras par le côté puis au-dessus de la tête »
     (3 étapes : écarter l'épaule, bras horizontal, épaules tournées vers
     l'avant) a été essayée, puis abandonnée après essai sous le drap : on est
     revenu au mouvement d'origine.
   - attend la fin du rire, puis dit **« Trick or treat! »** en synthèse vocale
     anglaise (`ALTextToSpeech`, balises `\\vct=60\\ \\rspd=75\\` : voix grave et lente ;
     phrase réglable avec `--phrase`), rétablit le volume, revient en attente en 3 s,
     LED éteintes, pause de 5 s.

## Alarme anti-vol (`antivol.py`)

Testée sur le robot le 2026-10-18. Elle démarre avec le fantôme, sauf `--no-alarm`.

- Capteurs : centrale inertielle de la **base**
  (`Device/SubDeviceList/InertialSensorBase/{AngleX,AngleY,Accelerometer*,Gyroscope*}/Sensor/Value`)
  et **vitesse des roues** (`Device/SubDeviceList/Wheel{FL,FR,B}/Speed/Sensor/Value`),
  lues à 20 Hz dans un fil séparé. La centrale du torse est en panne.
- Bruit mesuré au repos : angles ±0,003 rad, accéléro ±0,2 m/s², gyro
  ±0,02 rad/s, roues 0,000.
- Référence : moyenne de 2 s au démarrage (et à chaque ré-armement). Pas
  d'adaptation lente.
- **Roues** : dès qu'une roue tourne (> 0,5), le robot est au sol et on le fait
  rouler ; rien ne déclenche pendant ce temps et 2 s après. Mesures en roulant
  (poussée franche, pivot ¼ de tour, seuil de porte) : roues 2 à 17,
  inclinaison jusqu'à 13°, écart |acc| jusqu'à 9 m/s², rotation verticale
  jusqu'à 4 rad/s. Sans cette règle, ces manipulations déclenchaient la sirène.
- Déclenchement (le premier qui arrive) :
  - **porté** : rotation 3 axes moyenne sur 1 s > 0,4 rad/s alors que les roues
    sont restées immobiles toute cette seconde. Mesure en portant « à plat » :
    roues à 0 (sauf à la prise et à la pose), rotation 0,5 à 1,7 rad/s qui
    oscille au rythme des pas, inclinaison 6 à 12°. Au sol, le robot ne peut
    pas tourner sans ses roues. **C'est la règle qui a déclenché lors du test.**
  - **inclinaison** > 8° (`--alarm-tilt`) pendant 1 s, roues immobiles ;
  - **secousses** : écart de |acc| > 2,5 m/s² sur ≥ 4 lectures en 1 s, roues immobiles ;
  - **basculement** : gyro X/Y > 0,5 rad/s pendant 0,5 s, roues immobiles (la
    rotation verticale seule ne compte pas).
- BOUH : au plus 2,9° d'inclinaison, 1 m/s² d'écart, gyro 0,13 rad/s ; les
  roues tournent un peu (jusqu'à 3,7) car le robot oscille.
- Alarme : coupe tout son en cours, **sirène en boucle** (`playFileInLoop`,
  volume 100), yeux et épaules en **gyrophare rouge/bleu**. Le fantôme ne fait
  plus rien (ni BOUH ni « Trick or treat ») tant que la sirène sonne.
- **Désarmement** : `touch ~/halloween/desarme`. La sirène s'arrête, les LED
  s'éteignent, nouvelle référence et ré-armement **30 s** plus tard (le temps de
  remettre le robot en place). Un fichier `desarme` présent quand rien ne sonne
  est simplement effacé.
- Calibrage : après chaque BOUH, `run.log` donne les écarts max de la base
  pendant le geste (« secousse du BOUH »). Avec `--alarm-debug`, il les donne
  toutes les 10 s.
- Mode test : `--alarm-siren 1` coupe la sirène après 1 s (pause 3 s puis
  ré-armé avec la même référence), pas besoin de désarmer. **Pour Halloween,
  lancer sans cette option** (sirène continue).
- Simulation hors robot (`simu_antivol.py`) : rien au repos, à 5°, en pivotant
  ou en roulant ; sirène à 12°, en cas de secousses, de basculement.
- Limite : rien n'empêche d'éteindre le robot (bouton du torse) ou de
  débrancher la batterie.

## Page web d'état (`web.py`)

Processus séparé, à lancer en plus du fantôme :

```sh
ssh pepper 'cd ~/halloween && PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages setsid nohup python2 web.py > web.log 2>&1 < /dev/null &'
```

- `/` : page (rafraîchie chaque seconde), `/status` : JSON, `POST /disarm` :
  crée `~/halloween/desarme` (arrête la sirène si elle sonne, sinon sans effet).
- État partagé par ALMemory : `Halloween/Ghost` (battement chaque seconde de
  `halloween.py`), `Halloween/LastScare`, `Halloween/Alarm` = [état, détail,
  instant] écrit par `antivol.py`. **Stocker les instants en entiers** :
  ALMemory garde les flottants en 32 bits (un `time.time()` y perd ~2 min).
- Lidar : segment 1 = gauche du robot (Y > 0), 15 = droite ; la page les
  affiche du point de vue du robot.

## Anti-collision des bras (désactivé)

Le 2026-10-18, le bras gauche est resté levé après un BOUH : consigne figée à
0,37 rad au lieu de 1,12, `Motion/ExternalCollision/ClippingAmplitude/LArm` =
8,96, `ALMotion/MoveFailed` = « Internal stop ». La protection anti-collision
externe des bras avait vu quelqu'un tout près et annulé le mouvement ; personne
ne redonne l'ordre ensuite. Probablement aussi la cause du « bras gauche lent à
redescendre » noté plus tôt (pas un embrayage).

- Autorisation (persistante, survit au reboot) : case « Permit deactivation of
  the safety reflexes » dans http://pepper.<domaine-lan>/advanced/ (Settings),
  cochée le 2026-10-18. Stockée dans `~/.config/naoqi/ALMotion.xml`
  (`ENABLE_DEACTIVATION_OF_FALL_MANAGER` = true).
- Désactivation (non persistante, perdue au redémarrage de NAOqi) :
  `halloween.py` appelle `setExternalCollisionProtectionEnabled("Arms", False)`
  au démarrage et toutes les 30 s (`quiet_autonomy`). Sans l'autorisation,
  NAOqi refuse sans erreur ; le journal l'indique.
- Conséquence : les bras ne s'arrêtent plus si quelqu'un est tout près pendant
  le BOUH. La protection des déplacements (« Move ») reste active.

## Dialogue avec les enfants (`../dialogue/`) — prêt, pas encore testé sur le robot

But : parler avec les enfants. Le micro USB écoute, la transcription passe le
texte au LLM, la synthèse vocale répond. Les micros internes du robot ne
marchent pas.

**Micro USB** : ReSpeaker Mic Array de Seeed (USB `2886:0007`, carte ALSA
`UAC20`). Il enregistre en 16 kHz stéréo S24_3LE ; les 2 canaux sont identiques
(son déjà traité par le réseau de micros). Il devient la carte n°0 mais ne gêne
pas le son : PulseAudio garde `speaker` comme sortie par défaut, et la voix du
robot sort bien sur ses haut-parleurs (vérifié le 2026-10-18). Son
**interrupteur de capture est coupé au démarrage** :
`amixer -c UAC20 cset numid=7 on,on` et `numid=8 on`. `robot_audio.py` le
remet à chaque lancement. Niveaux mesurés près du robot : bruit de fond
(ventilateurs) vers -34 dBFS, voix vers -25 dBFS.

**Répartition** : le robot ne fait qu'écouter et parler, tout le reste tourne
sur le PC. Sur le robot, Python 2.7/3.5 et OpenSSL 1.0.2 ne permettent pas la
transcription en temps réel de Google, et l'Atom est trop faible pour faire
tourner un modèle en local. **C'est le PC qui se connecte au robot**, car sous
WSL le robot ne peut pas joindre le PC.

- `robot_audio.py` (sur le robot, Python 2) est un serveur TCP sur le port 8090.
  - Il envoie le son du micro en PCM 16 bits mono 16 kHz
    (`arecord -D plughw:UAC20,0`).
  - Il reçoit des messages encadrés (longueur + en-tête JSON + données) :
    `play` (un WAV, joué par `ALAudioPlayer.playFile`), `eyes` (couleur des
    yeux) et `stop`.
  - Pendant qu'il parle, et 0,4 s après, il envoie du silence pour ne pas
    s'entendre lui-même.
- `dialogue.py` (sur le PC, projet uv avec `pyproject.toml`) enchaîne les trois
  services Google sur le projet GCP `m2if-270422` :
  1. **Transcription** : Speech-to-Text v2 en continu, modèle `chirp_3`, région
     `eu`, fr-FR. Ce modèle **coupe les phrases aux pauses** et ne donne pas de
     résultat partiel. La fin de phrase est donc décidée avec la détection de
     parole de Google (`enable_voice_activity_events`) : on attend que la parole
     soit finie, qu'au moins un morceau soit final, et 0,4 s sans rien de
     nouveau. Les morceaux finaux sont alors regroupés.
     - Comparé sur le même fichier : `chirp_2` coupe de la même façon ;
       `latest_long` ne valide qu'à la fin du flux ; `latest_short` s'arrête
       après la première phrase.
  2. **LLM** : `gemini-2.5-flash` sur Vertex AI, **réflexion désactivée**
     (`thinking_budget=0`). Il répond en 0,5 à 1,7 s ; avec la réflexion il
     mettait 14 s. `gemini-3-flash-preview` met 2,4 à 4,4 s. Le texte de
     départ (`SYSTEM` dans le code) l'oblige à faire des phrases courtes et
     simples pour des enfants de 4 à 10 ans, sans emoji, sans demander
     d'informations personnelles, et à éviter les sujets effrayants. La
     conversation garde l'historique.
  3. **Voix** : Text-to-Speech `fr-FR-Chirp3-HD-Leda`, en LINEAR16 24 kHz,
     prête en environ 0,8 s. La voix du robot ne parle pas français :
     seuls `English` et `Chinese` sont installés.
- **Yeux** : bleus quand Pepper écoute, orange quand il réfléchit.
- **Journal** des conversations : `dialogue/logs/AAAAMMJJ-HHMMSS.txt` (non
  commité, comme `out/`).

**Testé sur le PC seulement** (`--file`, avec un WAV généré par la synthèse
vocale qui joue un enfant). La phrase « Tu as peur… des sorcières » n'est plus
coupée en deux, l'historique est gardé, et les WAV de réponse sont valides.
**Délai entre la fin de la phrase et le début de la réponse : environ 3 s**,
soit 1,3 s de transcription, 0,6 à 1,7 s de LLM et 0,8 s de voix.

**Pas encore fait** : aucun test sur le robot. L'utilisateur a demandé
d'attendre, et `robot_audio.py` n'est **pas copié** sur le robot (sa syntaxe
Python 2 n'a pas été vérifiée, il n'y a pas de Python 2 sur le PC).

Mise en route :
```bash
# Identifiants Google, une fois (déjà fait le 2026-10-18) :
#   gcloud auth application-default login
# API activées : speech.googleapis.com, texttospeech.googleapis.com, aiplatform
scp ../dialogue/robot_audio.py pepper:~/halloween/
timeout 10 ssh pepper 'cd ~/halloween && PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages \
  setsid nohup python2 robot_audio.py > audio.log 2>&1 < /dev/null &'
cd ../dialogue && uv run dialogue.py              # Ctrl+C pour arrêter
uv run dialogue.py --file question.wav            # test sans robot (WAV 16 kHz mono)
uv run dialogue.py --voice fr-FR-Chirp3-HD-Puck   # autre voix (42 voix fr-FR)
```

Points à vérifier au premier essai sur le robot :
- `ALAudioPlayer.playFile` lit-il le WAV 24 kHz, et à quel volume ?
- Le silence envoyé pendant que Pepper parle suffit-il à ce qu'il ne s'entende
  pas ? (Le micro est dans le robot, près des haut-parleurs.)
- Avec l'autonomie (`ALAutonomousLife`) en `interactive`, le robot bouge et
  peut parler de lui-même. La couper pendant le dialogue, comme le fait
  `halloween.py` ?
- Distance de captation avec des enfants et du bruit autour. Pepper répond à
  tout ce qu'il entend (télé, adultes) : ajouter éventuellement un mot de réveil
  (« Pepper »).
- Coût : la transcription est facturée sur tout le son envoyé, silences compris
  (environ 1 €/heure en continu). Ajouter éventuellement un filtre de niveau
  sonore côté PC si le dialogue doit tourner longtemps.

## Trouvailles importantes

### Chauffe des moteurs (le point le plus critique)

- Tenir une posture avec les moteurs actifs les fait chauffer. Avec la première
  version (vraie position de repos tenue moteurs actifs : tête baissée à 0,60,
  HipPitch -1,05) :
  - **HeadPitch (cou) à 74 °C**, état 1 → notification
    `Warning 720: Some of my motors are getting hot in my neck. I will need to rest soon.`
    et **épaules qui clignotent en double jaune** ;
  - HipPitch à 62 °C (état 0), en hausse.
- Courant mesuré dans HipPitch selon l'inclinaison (Knee ≈ HipPitch/2) :
  -0,03 → 0,80 A ; -0,30 → 0,67 A ; **-0,50 → 0,26 A** ; -0,70 → 0,74 A ;
  -1,05 → 1,50 A. Une autre mesure à -0,52 a donné 1,18 A : ça varie selon le
  sens d'arrivée (frottements). KneePitch ≈ 1 A et HipRoll ≈ 0,75 A quelle que
  soit la posture.
- **HipRoll** : consigne 0, il reste vers -0,04 et pousse en permanence
  (0,8 A, +1,5 °C/min, 52 → 60 °C en 6 min). Avec une consigne égale à sa position
  mesurée : **0,22 A**. Le même essai sur HipPitch/KneePitch ne gagne rien (ils
  s'affaissent sous le poids et la consigne court après).
- **Posture d'attente retenue : -0,20 / 0,10.** Courant total hanche + genou +
  HipRoll en arrivant **depuis la position debout** (comme dans le script) :
  -0,50/0,25 → 1,84 A ; -0,40/0,20 → 1,18 A ; -0,30/0,15 → 1,06 A ;
  **-0,20/0,10 → 0,69 A** (hanche 0 A). Garder le genou ≈ -hanche/2 ; avec le
  genou à 0 et la hanche penchée, la hanche monte à 1,3–2,2 A. Les mesures
  dépendent beaucoup du sens d'arrivée (frottements). Avec -0,50/0,25, les genoux
  sont montés de 50 à 62 °C en 25 min.
- **Tête relâchée** : 0 A. Elle tombe en avant (0,74) si le buste est penché
  (HipPitch ≤ -0,5), mais **en arrière (-0,42) si le robot est droit**.
- On **ne peut pas** couper la rigidité du bas du corps à la main sur Pepper
  (interdit par NAOqi). L'alternative `motion.rest()` (freins, aucun courant)
  impose un `wakeUp()` de **14,7 s** pour se relever : beaucoup trop lent pour
  faire peur. Au repos, les mains peuvent quand même être raidies et bouger.
- Seuil d'alerte : non documenté (le site doc.aldebaran.com est **hors ligne**,
  il redirige vers sa page d'accueil ; les fichiers de configuration du robot
  ne donnent que des noms, sans valeurs). Observé : état 1 à 74 °C (cou),
  état 0 à 62 °C (hanches). L'état se lit dans
  `Device/SubDeviceList/<Joint>/Temperature/Sensor/Status`.
- Refroidissement au repos : cou 74 → 42 °C en ~20 min ; hanches ~1 °C toutes les 2 min.
- Températures de repos à froid : bras ~24–34 °C.

### LED

- Groupes utiles : `AllLeds`, `FaceLeds` (yeux, RGB), `ChestLeds` (= LED des
  **épaules** sur Pepper, RGB), `EarLeds`.
- **Oreilles : bleu uniquement** (`Ears/Led/Left/0Deg/Actuator/Value`, un seul
  canal) : impossible de les mettre en rouge. L'utilisateur a choisi de les
  laisser éteintes.
- `ALLeds.listLED(groupe)` ne marche pas : utiliser `listGroup(groupe)`.

### Lidars

- Front/Left/Right, 15 segments chacun, en mètres. Une absence d'obstacle se lit 7,00 m.
- **Le drap ne doit pas couvrir l'avant de la base** (les lidars sont au ras du
  sol). Vérifié avec le drap en place : 1,85 à 7 m sur les 15 segments avant, donc dégagé.
- Si le drap pend devant la base (vent), il est ignoré (< 0,30 m) mais il rend
  le robot aveugle.

### Divers

- Postures disponibles : `Crouch`, `Stand`, `StandInit`, `StandZero`.
- (Variante abandonnée) Pour lever les bras **par le côté** : l'épaule ne s'écarte que jusqu'à
  l'horizontale (ShoulderRoll max ≈ ±1,56). Avec un bras écarté à 90°, changer
  le pitch ne fait que tourner le bras sur lui-même. Il faut donc 3 étapes.
- **Bras gauche** : à la redescente, il ne suit pas tout de suite. Problème
  mécanique (embrayage ?) d'après l'utilisateur.
- **Tablette** : pas nécessaire. `ALTabletService` est absent (la tablette ne
  répondait déjà pas) ; elle est maintenant débranchée (prise USB, débranchée
  robot allumé sans problème). Avantage : pas d'écran qui luit sous le drap.
- Sans le câble réseau : le WiFi seul fonctionne (`pepper.<domaine-lan>` →
  192.168.11.228 sur `wlan0`). Le câble donnait 192.168.11.183 (`eth0`).
- Le capot d'alimentation était ouvert pendant les essais : seules les roues
  sont bloquées, ce qui ne gêne pas le fantôme.

## Pièges rencontrés

- **`/` est montée en lecture seule.** Pour y écrire :
  `sudo mount -o remount,rw /` … `sync; sudo mount -o remount,ro /`.
  C'est nécessaire pour `/etc/systemd/system`.
- **`pkill -f "...halloween..."` tue sa propre session ssh** si la même
  commande ssh contient ce texte (par exemple un relancement dans la foulée).
  Faire l'arrêt dans un `ssh` séparé, avec le motif `"[p]ython2 halloween"`.
- Un `ssh` qui lance le script en arrière-plan peut rester bloqué : utiliser
  `setsid nohup … < /dev/null &` et entourer le ssh d'un `timeout`.
- API `qi` : `service.post.methode()` **n'existe pas** (c'est l'ancien
  `ALProxy`). Utiliser `service.methode(..., _async=True)`, qui renvoie un
  Future (`.wait()`).
- `qi` écrit ses avertissements `[W] ... sdklayout` / `transportsocketcache`
  sur stdout : ils sont sans importance, il suffit de les filtrer.
- **Boot de ~8 min** (corrigé le 2026-10-18) : la carte du torse ne répond pas
  au démarrage, donc `firmware-update.sh` reflashait tout à chaque boot. La
  ligne fautive est commentée : le boot prend maintenant ~70 s à chaud et
  ~2 min 25 s à froid. Voir `../STATUT.md`.

## Ce qui a été changé sur le robot pendant ce projet

- `/usr/lib/python3.7` (56 Mo, inutilisé, sans interpréteur) a été déplacé dans
  `/data/backup/usr_lib/python3.7` : `/` est passée de 51 à 107 Mo libres.
- `ALAutonomousLife` est laissée en `disabled` par le script. Elle reviendra à
  la normale au prochain redémarrage si le script ne tourne pas.

## Reste à faire

1. **Démarrage automatique** (proposé, en attente de la décision de
   l'utilisateur) : un service `halloween.service`, sur le modèle de
   `/etc/systemd/system/pepper-keepawake.service` (User=nao,
   PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages, `Restart=always`).
   Le script devra **réessayer la connexion à NAOqi** (jusqu'à ~8 min après le
   boot). Il faut remonter `/` en écriture pour poser le fichier. À activer
   seulement le soir d'Halloween ? (Le robot se lève devant tout le monde à
   chaque démarrage.)
2. Alarme anti-vol : testée. Reste à essayer une vraie montée d'escalier et le
   mode sirène continue + désarmement (`touch ~/halloween/desarme`).
3. Valider la chauffe sur **plusieurs heures** en attente, avec `temps.py`
   (à 23h42 : cou 36, hanches 52, genoux 50, hanches latérales 52 °C).
4. Optionnel : mesurer le seuil exact de l'état 1 (relever `Status` en continu).
5. **Dialogue** : premier essai sur le robot (voir la section « Dialogue avec
   les enfants » et ses points à vérifier). La page web (port 8080) et le
   fantôme ne sont pas relancés depuis le redémarrage du 2026-10-18 au soir.
