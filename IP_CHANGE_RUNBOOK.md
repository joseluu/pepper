# Changement d'adresse IP d'un robot Pepper — problème & mode opératoire

S'applique aux deux robots de même type (**pepper**, **memmer**). À garder sous
la main : c'est la panne qui a fait disparaître les flèches PTZ dans Frigate le
2026-06-29.

---

## 1. Pourquoi ça arrive

Les Pepper prennent leur adresse en **DHCP** sur le WiFi (réseau WiFi de la maison).
Le bail DHCP n'est pas permanent : après une coupure, un reboot, une absence
prolongée ou si un autre appareil prend l'adresse, **la box réattribue une IP
différente**. Exemple vécu : `pepper` est passé de `192.168.11.182` à
`192.168.11.228` sans prévenir.

Point matériel important : chaque robot a **trois adresses distinctes**, avec des
MAC différentes donc des IP différentes :

| Adresse | Interface | Rôle |
|---|---|---|
| **Sans-fil** | `wlan0` | celle utilisée normalement (DHCP, instable) |
| **Filaire** | `eth0` | stable si un câble est branché (sinon `down`) |
| **Tablette** | (Android séparé) | **n'héberge AUCUN service robot** — pas concernée par les caméras/ONVIF |

Les services caméra (`go2rtc`, `onvif_ptz.py`) tournent sur le **PC tête
NAOqiOS**, accessible via `wlan0` **ou** `eth0` — **jamais** par la tablette.

---

## 2. Ce qui casse vs ce qui résiste

| Composant | Réaction au changement d'IP |
|---|---|
| `ssh` configuré **par nom** (`pepper` → `pepper.<domaine-lan>`) | ✅ continue (le DNS suit) |
| `ssh` configuré **par IP** (`memmer` → `192.168.11.185`) | ❌ **casse** — l'alias pointe vers l'ancienne IP |
| Flux **RTSP** Frigate s'ils sont adressés **par nom** | ✅ continue |
| **ONVIF PTZ** (flèches Frigate) | ⚠️ casse **si** l'ancienne IP est annoncée en dur (voir §5) |
| Tout ce qui est **codé en dur sur une IP** (config, scripts, réservations) | ❌ casse |

> Le bridge `onvif_ptz.py` a été corrigé pour **renvoyer le nom/hôte que le
> client a réellement utilisé** (en-tête `Host:`) dans les URL de ses services.
> Tant que Frigate joint le robot **par un nom qui résout encore**, le PTZ
> s'auto-répare. C'est l'IP codée en dur (`ONVIF_HOST`) qui cassait avant.

---

## 3. Symptômes typiques

- Flèches PTZ disparues dans Frigate ; log Frigate :
  `Unable to get Onvif media profiles for camera: <cam>: Request to http://<vieille-IP>:8000/onvif/media_service timed out`.
- Caméra "offline" dans Frigate alors que le robot est allumé.
- `ssh <robot>` qui pend / `Connection timed out` (si l'alias est par IP).
- Un `ping <vieille-IP>` ne répond plus, l'ARP reste `INCOMPLETE`.

---

## 4. Diagnostic (du plus rapide au plus fin)

```bash
# a) Quelle est l'IP ACTUELLE du robot ? (ssh par nom doit encore marcher)
ssh pepper 'ip -4 -o addr show wlan0 eth0 | awk "{print \$2, \$4}"'
ssh pepper 'cat /sys/class/net/wlan0/address /sys/class/net/eth0/address'  # MAC

# b) Vers quoi pointe le nom / l'alias ssh ?
getent hosts pepper 2>/dev/null || nslookup pepper
ssh -G pepper | grep -i hostname

# c) Le robot est-il joignable sur ses ports depuis le LAN ?
for p in 22 8000 8554 1984; do
  timeout 5 bash -c "</dev/tcp/<IP-actuelle>/$p" 2>/dev/null && echo "$p OUVERT" || echo "$p KO"
done
```

> ⚠️ **Piège réseau** : tester depuis le **bon point**. Le shell de l'hôte
> Frigate (`ssh tram`) **n'arrive pas** à joindre le robot en TCP (ICMP/ping
> oui, TCP non), alors que le **conteneur** Frigate y arrive. Toujours diagnostiquer
> ONVIF/RTSP depuis le conteneur :
> ```bash
> ssh tram 'docker exec frigate curl -s -m5 -o /dev/null -w "%{http_code}\n" \
>   http://pepper:8000/onvif/device_service \
>   -H "Content-Type: application/soap+xml" \
>   --data "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\"><s:Body><GetCapabilities xmlns=\"http://www.onvif.org/ver10/device/wsdl\"/></s:Body></s:Envelope>"'
> ```

---

## 5. Résolution (étapes)

### Cas A — l'accès par **nom** marche encore (idéal)

Rien de manuel sur le robot : le DNS a déjà suivi la nouvelle IP, et le bridge
ONVIF annonce le nom. Il suffit de **réinitialiser le côté Frigate** :

```bash
# Redémarre Frigate pour relancer l'init ONVIF (un reload de config ne suffit pas)
ssh tram 'docker restart frigate'
# Relance l'init PTZ et vérifie
ssh tram 'curl -s http://localhost:5000/api/<cam>/ptz/info; echo'
# -> doit renvoyer {"name":"<cam>","features":["pt"],...}
```

Puis **rafraîchir la page caméra** dans le navigateur Frigate → flèches de retour.

### Cas B — l'accès par **IP** était utilisé quelque part

1. **Trouver la nouvelle IP** (§4-a, via `ssh <robot>` par nom, ou la box).
2. **Mettre à jour les références codées en dur** :
   - `~/.ssh/config` : remplacer l'IP par un **nom** (cf. §6).
   - Config Frigate (`/opt/frigate/config/config.yml` sur `tram`) : utiliser le
     **nom** dans `rtsp://…` et `onvif: host:`.
   - Bridge ONVIF : `Environment=ONVIF_HOST=<nom>` dans
     `/etc/systemd/system/onvif-ptz.service`, puis
     `sudo systemctl daemon-reload && sudo systemctl restart onvif-ptz`.
3. Redémarrer Frigate (Cas A) et vérifier.

### Vérifier le mouvement réel (pas seulement les flèches)

```bash
# ContinuousMove pan court puis Stop, en lisant HeadYaw avant/après
ssh pepper 'PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages python2 -c \
 "import qi;s=qi.Session();s.connect(\"tcp://127.0.0.1:9559\");print(s.service(\"ALMotion\").getAngles(\"HeadYaw\",True))"'
```

---

## 6. Prévention durable

### L'essentiel est déjà en place : DHCP ↔ DNS coordonnés (DDNS) sur tram

`tram` héberge **isc-dhcp-server** (dhcpd, `:67`) **et** **BIND** (named, `:53`),
couplés en **mise à jour dynamique** :

- dhcpd : `ddns-update-style standard; ddns-updates on; ddns-domainname "<domaine-lan>";`
  avec les zones `<domaine-lan>.` et `11.168.192.in-addr.arpa.` signées par la clé
  TSIG `ddns-key`.
- named : ces deux zones ont `allow-update { key "ddns-key"; };`.

**Conséquence : dès qu'un robot prend ou renouvelle son bail, son `A` (et son
`PTR` inverse) est publié dans le DNS dans la seconde.** Vérifié : `pepper` →
`192.168.11.228` en direct, avec enregistrement `DHCID` à l'appui. Une réservation
DHCP n'est donc **pas nécessaire** pour la stabilité du **nom** (elle ne sert que
si un tiers exige une **IP** figée).

Le robot s'enregistre sous le **`client-hostname`** qu'envoie son client DHCP,
c'est-à-dire son **hostname système** (`pepper`, `memmer`). Vérifier ce nom si un
robot n'apparaît pas :
```bash
ssh <robot> hostname           # doit valoir pepper / memmer
dig +short @192.168.11.135 <robot>.<domaine-lan>  # doit renvoyer son IP courante
```
> Un robot absent du DNS = très probablement **éteint / sans bail actif** (cas de
> `memmer` quand son chargeur n'est pas branché), pas un défaut de config.

### À faire une fois

1. **Toujours adresser par nom**, jamais par IP :
   - `~/.ssh/config` : `HostName <robot>` (nom court, complété par le domaine de recherche du DHCP) (déjà fait pour `pepper` ;
     **à faire pour `memmer`** qui est encore en `192.168.11.185`, et pour les
     alias `*_wired`).
   - Config Frigate : noms dans `rtsp://` et `onvif: host:`.
2. *(Optionnel)* **Réservation DHCP** sur le serveur dhcpd de tram si tu veux en
   plus figer l'**IP** d'un robot (associer sa MAC à une `fixed-address`).
3. **Préférer le filaire** pour un usage caméra de surveillance fixe : `eth0` est
   stable et ne subit ni le churn DHCP WiFi ni les interférences. (Brancher un
   câble ; eth0 a sa **propre MAC** donc sa propre IP/bail — il s'enregistrera
   dans le DNS sous le même hostname, donc le nom suivra automatiquement.)

---

## 7. Référence — adresses & MAC

| Robot | Nom DNS | WiFi (`wlan0`) | Filaire (`eth0`) | MAC WiFi | MAC eth0 |
|---|---|---|---|---|---|
| **pepper** | `pepper` | DHCP (était .182 → .228) | .183 (si câblé) | `48:a9:d2:a8:ed:0c` | `00:13:95:1d:eb:58` |
| **memmer** | *(à créer)* | .185 (DHCP) | .190 (si câblé) | *(relever : `ssh memmer 'cat /sys/class/net/wlan0/address'`)* | *(idem eth0)* |

> Récupérer la MAC d'un robot pour la réservation DHCP :
> ```bash
> ssh <robot> 'cat /sys/class/net/wlan0/address /sys/class/net/eth0/address'
> ```

---

## 8. Résumé en une phrase

**La cause = une IP codée en dur qui devient périmée quand le DHCP change l'adresse.
La parade = tout adresser par nom DNS + réservation DHCP (+ idéalement filaire),
et le bridge ONVIF s'auto-répare en renvoyant l'hôte effectivement utilisé.**
