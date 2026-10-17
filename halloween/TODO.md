# Fantôme d'Halloween — à faire

## Alarme anti-vol : à tester sur le robot (codée le 2026-10-18)

Code dans `antivol.py`, lancé automatiquement par `halloween.py` (sauf
`--no-alarm`). Détails dans `STATUT_HALLOWEEN.md`, section « Alarme anti-vol ».

Plan de test :

1. `--test-alarm` : vérifier le son de la sirène (`siren.wav`), le volume 100 et
   le gyrophare rouge/bleu (5 s).
2. Lancer avec `--alarm-debug` et regarder dans `run.log` les écarts max
   toutes les 10 s au repos, puis pendant un BOUH (ligne « secousse du BOUH »).
   Les seuils doivent être bien au-dessus de ce que le BOUH produit.
3. Pencher le robot (une personne de chaque côté, comme pour l'escalier),
   le soulever, le faire pivoter : la sirène doit partir.
4. Désarmer : `ssh pepper 'touch ~/halloween/desarme'`. La sirène s'arrête et
   l'alarme se ré-arme 30 s plus tard.
5. Ajuster `--alarm-tilt` (8° par défaut) et les constantes en tête
   d'`antivol.py` (`SHOCK_ACC`, `GYRO_MAX`…).
