# -*- coding: utf-8 -*-
# Page d'etat du fantome : lidar avant, batterie, alarme + bouton d'arret.
# Bibliotheque standard seulement (pas de Flask sur le robot).
#
# Lancer (sur le robot) : python2 web.py [--port 8080]
# Puis ouvrir http://pepper:8080/
#
# Etat lu dans ALMemory : Halloween/Ghost (battement de halloween.py),
# Halloween/LastScare, Halloween/Alarm (antivol.py). Le bouton d'arret cree
# le fichier ~/halloween/desarme, comme `touch ~/halloween/desarme`.
import os, json, math, time, argparse, threading
import BaseHTTPServer, SocketServer
import qi

HERE = os.path.dirname(os.path.abspath(__file__))
DISARM_FILE = os.path.join(HERE, "desarme")

SEG = "Device/SubDeviceList/Platform/LaserSensor/Front/Horizontal/Seg%02d/"
LASER_KEYS = []
for _i in range(1, 16):
    LASER_KEYS += [SEG % _i + "X/Sensor/Value", SEG % _i + "Y/Sensor/Value"]
BATT = "Device/SubDeviceList/Battery/%s/Sensor/Value"

PAGE = u"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fantôme de Pepper</title>
<style>
:root { --bg:#111; --fg:#eee; --mut:#999; --card:#1d1d1d; --red:#e53935;
        --green:#43a047; --amber:#f9a825; --bar:#5c6bc0; }
body { margin:0; padding:16px; background:var(--bg); color:var(--fg);
       font:16px/1.4 system-ui, sans-serif; }
h1 { font-size:1.3em; margin:0 0 12px; }
.card { background:var(--card); border-radius:10px; padding:12px 14px;
        margin-bottom:12px; }
.big { font-size:2em; font-weight:600; }
.mut { color:var(--mut); font-size:.9em; }
.row { display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap; }
#bars { display:flex; align-items:flex-end; gap:3px; height:120px; margin-top:8px; }
#bars div { flex:1; background:var(--bar); border-radius:3px 3px 0 0; min-height:2px; }
#bars div.close { background:var(--red); }
#bars div.far { background:#333; }
button { width:100%; padding:16px; font-size:1.2em; border:0; border-radius:10px;
         background:var(--red); color:#fff; font-weight:600; }
button:disabled { background:#444; color:#888; }
.ok { color:var(--green); } .warn { color:var(--amber); } .bad { color:var(--red); }
</style></head><body>
<h1>Fantôme de Pepper</h1>

<div class="card">
  <div class="row"><span>Alarme anti-vol</span><span id="alarm" class="big">…</span></div>
  <div id="alarmd" class="mut"></div>
  <p><button id="stop" disabled onclick="disarm()">Arrêter la sirène</button></p>
</div>

<div class="card">
  <div class="row"><span>Lidar avant : plus proche</span>
    <span class="big" id="min">…</span></div>
  <div id="bars"></div>
  <div class="row mut"><span>gauche</span><span>vu par le robot · seuil BOUH <span id="thr"></span> m (rouge)</span><span>droite</span></div>
</div>

<div class="card">
  <div class="row"><span>Batterie</span><span class="big" id="batt">…</span></div>
  <div id="battd" class="mut"></div>
</div>

<div class="card">
  <div class="row"><span>Fantôme</span><span id="ghost">…</span></div>
  <div id="scare" class="mut"></div>
</div>
<div id="err" class="mut"></div>

<script>
function ago(s) {
  if (s == null) return "jamais";
  if (s < 60) return Math.round(s) + " s";
  if (s < 3600) return Math.round(s / 60) + " min";
  return (s / 3600).toFixed(1) + " h";
}
function set(id, txt, cls) {
  var e = document.getElementById(id); e.textContent = txt;
  if (cls !== undefined) e.className = "big " + cls;
}
var bars = document.getElementById("bars");
for (var i = 0; i < 15; i++) bars.appendChild(document.createElement("div"));

function refresh() {
  fetch("status").then(function (r) { return r.json(); }).then(function (s) {
    document.getElementById("err").textContent = "";
    // segment 1 = gauche du robot (Y > 0) : affiche du point de vue du robot
    var d = s.lidar, max = 4.0;
    for (var i = 0; i < 15; i++) {
      var b = bars.children[i], v = d[i];
      b.style.height = Math.max(2, 100 * Math.min(v, max) / max) + "%";
      b.className = v >= 7 ? "far" : (v < s.threshold ? "close" : "");
      b.title = "segment " + (i + 1) + " : " + v.toFixed(2) + " m";
    }
    set("min", s.lidar_min >= 7 ? "rien" : s.lidar_min.toFixed(2) + " m",
        s.lidar_min < s.threshold ? "bad" : "");
    document.getElementById("thr").textContent = s.threshold.toFixed(1);

    var pct = Math.round(s.battery * 100);
    set("batt", pct + " %", pct < 20 ? "bad" : (pct < 40 ? "warn" : "ok"));
    document.getElementById("battd").textContent =
      (s.current > 0.05 ? "en charge" : "sur batterie") +
      " · " + s.current.toFixed(2) + " A · " + s.batt_temp.toFixed(0) + " °C";

    var a = s.alarm, stop = document.getElementById("stop");
    if (!s.ghost_alive || !a) {
      set("alarm", "inactive", "warn"); stop.disabled = true;
      document.getElementById("alarmd").textContent =
        s.ghost_alive ? "lancée sans alarme" : "programme arrêté";
    } else if (a.state == "sirene") {
      set("alarm", "SIRÈNE", "bad"); stop.disabled = false;
      document.getElementById("alarmd").textContent = a.detail + " · depuis " + ago(a.age);
    } else {
      set("alarm", a.state == "armee" ? "armée" : "ré-armement…",
          a.state == "armee" ? "ok" : "warn");
      stop.disabled = true;
      document.getElementById("alarmd").textContent =
        a.state == "armee" ? "" : "ré-armée 30 s après l'arrêt";
    }
    var g = document.getElementById("ghost");
    g.textContent = s.ghost_alive ? "en marche" : "arrêté";
    g.className = s.ghost_alive ? "ok" : "bad";
    document.getElementById("scare").textContent = "dernier BOUH : " +
      (s.last_scare == null ? "aucun" : "il y a " + ago(s.last_scare));
  }).catch(function (e) {
    document.getElementById("err").textContent = "robot injoignable (" + e + ")";
  });
}
function disarm() {
  document.getElementById("stop").disabled = true;
  fetch("disarm", {method: "POST"}).then(refresh);
}
refresh(); setInterval(refresh, 1000);
</script></body></html>"""


class State(object):
    def __init__(self, threshold):
        self.session = None
        self.threshold = threshold
        self.lock = threading.Lock()

    def mem(self):
        # reconnexion si NAOqi a redemarre
        if self.session is None or not self.session.isConnected():
            s = qi.Session()
            s.connect("tcp://127.0.0.1:9559")
            self.session = s
        return self.session.service("ALMemory")

    def get(self, mem, key, default=None):
        try:
            return mem.getData(key)
        except Exception:
            return default

    def status(self):
        with self.lock:
            m = self.mem()
            v = m.getListData(LASER_KEYS)
            lidar = [round(math.hypot(v[2 * i], v[2 * i + 1]), 2) for i in range(15)]
            now = time.time()
            beat = self.get(m, "Halloween/Ghost")
            scare = self.get(m, "Halloween/LastScare")
            alarm = self.get(m, "Halloween/Alarm")
            # ALMemory : entiers 32 bits (les flottants y perdent la precision)
            alive = beat is not None and now - beat < 5
            return {
                "lidar": lidar,
                "lidar_min": min(d for d in lidar if d > 0.05) if any(d > 0.05 for d in lidar) else 7.0,
                "threshold": self.threshold,
                "battery": self.get(m, BATT % "Charge", 0.0),
                "current": self.get(m, BATT % "Current", 0.0),
                "batt_temp": self.get(m, BATT % "Temperature", 0.0),
                "ghost_alive": alive,
                "last_scare": now - scare if scare else None,
                "alarm": {"state": alarm[0], "detail": alarm[1],
                          "age": now - alarm[2]} if (alive and alarm) else None,
            }


class Handler(BaseHTTPServer.BaseHTTPRequestHandler):
    state = None

    def send(self, code, body, ctype):
        if isinstance(body, unicode):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/status":
            try:
                self.send(200, json.dumps(self.state.status()), "application/json")
            except Exception as e:
                self.send(503, json.dumps({"error": str(e)}), "application/json")
        else:
            self.send(404, "introuvable", "text/plain")

    def do_POST(self):
        if self.path == "/disarm":
            open(DISARM_FILE, "w").close()   # antivol.py arrete la sirene
            self.send(200, '{"ok": true}', "application/json")
        else:
            self.send(404, "introuvable", "text/plain")

    def log_message(self, fmt, *args):
        if "/status" not in (args[0] if args else ""):
            os.write(2, "%s [web] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))


class Server(SocketServer.ThreadingMixIn, BaseHTTPServer.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--dist", type=float, default=1.5, help="seuil BOUH affiche")
    args = p.parse_args()
    Handler.state = State(args.dist)
    srv = Server(("", args.port), Handler)
    os.write(2, "%s [web] http://pepper:%d/\n"
             % (time.strftime("%H:%M:%S"), args.port))
    srv.serve_forever()


if __name__ == "__main__":
    main()
