# Esprit de compagnie 3PO

Projet dérivé du fantôme d'Halloween (`halloween/`, `dialogue/`) : le robot
pepper se tient droit dans la pièce, en pause. Quand on le rend attentif depuis
la télécommande web, il fait un petit chirp et écoute la conversation avec
Gemini Live : il répond aux questions qu'on lui adresse, et quand on lui demande
son impression, il la bâtit à partir de citations de la littérature et de la
pensée occidentales (française, européenne, grecque et romaine, biblique).

Repris d'Halloween : pont audio du robot (micro ReSpeaker, tête tournée vers la
voix), Gemini Live sur tram (même voix Puck, même rythme lent), réglages du
micro sur la page web, alarme anti-vol, démarrage au boot par services
utilisateur. Laissés de côté : le BOUH, la détection lidar, le dialogue avec
les enfants et ses relances.

## Comportement

| Étape | Ce qui se passe |
|---|---|
| Démarrage | posture droite économe : hanches et genoux à la verticale, bras relâchés le long du corps (sans courant), tête tenue ; LED éteintes ; en pause |
| Bouton « Écoute » | chirp de 0,3 s (`chirp.wav`), yeux bleu pâle, session Gemini Live ouverte : 3PO écoute |
| Question directe | réponse directe, une à trois phrases |
| « Qu'en penses-tu ? », impression, sentiment | deux ou trois citations d'auteurs, puis son impression bâtie à partir d'elles |
| Conversation qui ne lui est pas adressée | il se tait (écoute proactive de Gemini) |
| « merci », « merci 3PO » | pause, sans rien dire |
| Bouton « Pause » | pause |
| 60 s sans un mot entendu ni dit | « L'esprit de compagnie 3PO en pause. », puis pause |
| Bouton « Tiens-toi droit » | reprend la posture droite (si NAOqi l'a mis au repos) |

Un mot entendu dans la pièce compte comme une interaction : tant qu'on parle
près de lui, 3PO reste attentif. Une session Gemini Live dure une dizaine de
minutes ; elle est reprise avec son contexte tant que 3PO est attentif.

## Fichiers

| Fichier | Où | Rôle |
|---|---|---|
| `compagnon.py` | robot, `~/compagnie3po/` | posture, pause/écoute, chirp, ordres de la page, anti-vol (`../halloween/antivol.py`) |
| `web3po.py` | robot | télécommande sur http://pepper:8080/ : attention, posture, alarme, micro, batterie |
| `chirp.wav`, `make_chirp.py` | robot / PC | le chirp (glissement 1500 → 2500 Hz, -20 dBFS) et son générateur |
| `courants.py` | robot | courant des moteurs dans la posture, pour la régler au plus économe |
| `live3po.py` | tram, `~/pepper/compagnie3po/` | Gemini Live (importe `dialogue/live.py`) |
| `preprompt_3po.txt` | tram | consignes de 3PO |
| `systemd/` | robot et tram | services utilisateur |

Le pont audio est `dialogue/robot_audio.py --prefix 3PO` : mêmes échanges que
pour le fantôme, sous les clés ALMemory `3PO/…` (`3PO/Dialogue`,
`3PO/DialoguePC`, `3PO/MicLevel`, `3PO/MicSettings`, `3PO/Command`,
`3PO/State`). L'anti-vol garde ses clés `Halloween/Alarm` et son fichier
`~/halloween/desarme`.

## Les consignes (`preprompt_3po.txt`)

- se taire par défaut, répondre seulement quand on s'adresse à lui ;
- pour une impression : citer des auteurs nommés, d'époques et de traditions
  différentes, puis bâtir son avis à partir des citations ; ne citer mot pour
  mot que ce dont il est sûr ;
- restituer fidèlement les auteurs dans leur contexte, sans les réécrire selon
  les opinions d'aujourd'hui ni les juger selon les sensibilités de l'époque ;
  pas de morale ni de mise en garde non demandée, aucun discours militant
  d'aucun bord ; sur une question disputée, exposer la tradition et ses
  désaccords et laisser chacun juger ; la religion traitée avec respect, comme
  un texte fondateur, sans prosélytisme ni dérision.

## Installation

Le fantôme et 3PO utilisent les mêmes ports (8090, 8080) : un seul des deux
tourne. Les services 3PO ont `Conflicts=` avec ceux d'Halloween.

```bash
# Robot
ssh pepper 'mkdir -p ~/compagnie3po'
scp compagnie3po/{compagnon.py,web3po.py,courants.py,chirp.wav} pepper:compagnie3po/
scp dialogue/robot_audio.py pepper:dialogue/
scp compagnie3po/systemd/compagnie3po{,-audio,-web}.service pepper:.config/systemd/user/
ssh pepper 'export XDG_RUNTIME_DIR=/run/user/1001; systemctl --user daemon-reload
  systemctl --user disable --now halloween halloween-dialogue halloween-web
  systemctl --user enable --now compagnie3po-audio compagnie3po compagnie3po-web'

# tram
ssh tram 'cd ~/pepper && git sparse-checkout add compagnie3po && git pull
  cp compagnie3po/systemd/pepper-3po.service ~/.config/systemd/user/
  mkdir -p compagnie3po/logs
  systemctl --user daemon-reload
  systemctl --user disable --now pepper-dialogue
  systemctl --user enable --now pepper-3po'
```

Revenir au fantôme : l'inverse (`disable --now` des services 3PO,
`enable --now` de ceux d'Halloween, sur le robot et sur tram).

Journaux : `~/compagnie3po/run.log`, `~/compagnie3po/web.log`,
`~/dialogue/bridge3po.log` sur le robot ; `journalctl --user -u pepper-3po -f`
sur tram. Transcriptions dans `~/pepper/compagnie3po/logs/` sur tram (hors
dépôt).
