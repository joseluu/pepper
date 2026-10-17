# Fantôme d'Halloween — à faire plus tard

## Alarme anti-vol

Le fantôme reste dehors, fixe. Détecter qu'on l'emporte : il y a un escalier
de 10 marches à monter, donc le robot sera penché / secoué.

- Surveiller la direction du vecteur pesanteur avec la centrale inertielle de
  la **base** (`Device/SubDeviceList/InertialSensorBase/...` : AngleX/AngleY,
  AccelerometerX/Y/Z). Celle du torse est en panne (voir `../STATUT.md`).
- Au repos : AccZ ≈ -9.0, AngleX/Y ≈ 0. Déclencher si l'inclinaison dépasse
  un seuil pendant un moment (à calibrer, ignorer le redressement du fantôme).
- Si déclenché : **sirène de police continue** dans les haut-parleurs, volume max,
  jusqu'à arrêt manuel.
