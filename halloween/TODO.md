# Fantôme d'Halloween — à faire

## Alarme anti-vol

Testée le 2026-10-18 (détails dans `STATUT_HALLOWEEN.md`) : déclenche quand on
porte le robot, pas quand on le fait rouler, pivoter, passer un seuil, ni
pendant un BOUH. Reste à essayer :

1. Une vraie montée d'escalier (avec `--alarm-siren 1`).
2. La sirène continue (sans `--alarm-siren`), puis le désarmement :
   `ssh pepper 'touch ~/halloween/desarme'` (ré-armement 30 s plus tard).
3. `--test-alarm` : son de la sirène et gyrophare pendant 5 s.
