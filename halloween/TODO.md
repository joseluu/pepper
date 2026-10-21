# Fantôme d'Halloween — à faire

## Alarme anti-vol

Testée le 2026-10-18 (détails dans `STATUT_HALLOWEEN.md`) : déclenche quand on
porte le robot, pas quand on le fait rouler, pivoter, passer un seuil, ni
pendant un BOUH. Reste à essayer :

1. Une vraie montée d'escalier (avec `--alarm-siren 1`).
2. La sirène continue (sans `--alarm-siren`), puis le désarmement :
   `ssh pepper 'touch ~/halloween/desarme'` (ré-armement 30 s plus tard).
3. `--test-alarm` : son de la sirène et gyrophare pendant 5 s.

## Dialogue avec les enfants — perfectionnements à planifier

Préalable : Gemini Live sur le robot (voir « Pour le robot » dans
`STATUT_HALLOWEEN.md`).

### 1. Apprendre ce qui marche avec les enfants, en faire un skill

- **Matière** : les transcriptions `dialogue/logs/live-*.txt` (texte seulement,
  pas d'audio ; hors dépôt, `logs/` est ignoré par git). Les supprimer après
  analyse : ce sont des paroles d'enfants.
- **Indicateurs par conversation** : nombre d'échanges avant que l'enfant parte,
  longueur des réponses de l'enfant, rires ou « encore ! », demandes de
  répétition, réponses de Pepper restées sans suite.
- **Après chaque séance**, une revue des journaux (par Claude) note ce qui a
  accroché : accroches, devinettes et blagues qui marchent, questions qui
  relancent, phrases qui tombent à plat, tranches d'âge.
- **En faire un skill** (`pepper-enfants`, par exemple) qui capitalise ces
  leçons : comment mener la conversation, répertoire de devinettes éprouvées,
  à éviter. Le pré-prompt `preprompt_dialogue.txt` en reprend une section
  « Ce qui marche » mise à jour. Le skill sert aussi à relancer la revue des
  journaux.

### 2. Détecter les injures et l'agressivité : 1 s de sirène

- **Détection par Gemini Live lui-même**, par appel de fonction : déclarer un
  outil `alerte_agressivite(raison, gravite)`, que le modèle appelle s'il
  entend des injures réelles, des menaces, ou un ton agressif répété. Le
  programme reçoit l'appel et déclenche la sirène. Un filtre de mots sur la
  transcription de l'enfant sert de filet de secours.
- **Agressivité physique** (coups, bousculade) : `antivol.py` détecte déjà les
  chocs par la centrale inertielle de la base. Réutiliser sa règle de chocs
  pendant le dialogue.
- **Réaction** : 1 s de sirène et de gyrophare (`siren.wav`, comme
  `--alarm-siren 1`), puis Pepper dit calmement une phrase qui recadre, sans
  faire la morale. Délai d'au moins 30 s entre deux sirènes.
- **À calibrer** : pas de sirène pour les bêtises d'enfants (« caca boudin »,
  gros mots en riant), que le pré-prompt traite déjà avec humour. Sirène
  seulement pour les injures dirigées, les menaces, ou une agressivité qui se
  répète. Volume modéré : de petits enfants peuvent avoir peur. Tester d'abord
  sur le PC (sirène jouée sous Windows) avec des phrases de test.
