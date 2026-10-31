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
# Les boutons du fantome (tiens-toi droit, bouh, dodo, parle) ecrivent
# Halloween/Command, que halloween.py execute (accuse dans CommandAck).
# Carte Micro : niveau lu dans Halloween/MicLevel (pont audio, 10 fois par s),
# reglages [gain, seuil dBFS apres gain, porte] ecrits dans
# Halloween/MicSettings (le pont les passe a live.py sur tram) et gardes dans
# ~/halloween/micro.json pour le prochain demarrage.
import os, json, math, time, argparse, threading
import BaseHTTPServer, SocketServer
import qi

HERE = os.path.dirname(os.path.abspath(__file__))
DISARM_FILE = os.path.join(HERE, "desarme")
MIC_FILE = os.path.join(HERE, "micro.json")
MIC_DEFAULT = [20.0, -16.0, 0]   # = live.py : gain x20, seuil 250 x 20 avant gain

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
.grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px; }
.grid button { background:#5c6bc0; padding:14px 8px; }
#meter { position:relative; height:28px; background:#333; border-radius:6px;
         margin:10px 0 4px; overflow:hidden; }
#lvl { position:absolute; left:0; top:0; bottom:0; width:0; background:var(--green);
       transition:width .1s; }
#lvl.loud { background:var(--amber); }
#thrm { position:absolute; top:0; bottom:0; width:3px; background:var(--red); }
#peak { position:absolute; top:0; bottom:0; width:2px; background:#fff; opacity:.7; }
.set { display:flex; align-items:center; gap:10px; margin-top:10px; }
.set label { width:4.5em; } .set input[type=range] { flex:1; }
.set span { width:5.5em; text-align:right; }
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
  <div class="row"><span>Micro (après gain)</span><span class="big" id="mdb">…</span></div>
  <div id="meter"><div id="lvl"></div><div id="peak"></div><div id="thrm"></div></div>
  <div class="row mut"><span>-70 dBFS</span><span>seuil de voix (rouge)</span><span>0</span></div>
  <div class="set"><label>Gain</label>
    <input id="gain" type="range" min="1" max="60" step="1" oninput="mic(true)">
    <span id="gainv"></span></div>
  <div class="set"><label>Seuil</label>
    <input id="thr2" type="range" min="-60" max="0" step="1" oninput="mic(true)">
    <span id="thrv"></span></div>
  <div class="set"><label><input id="gate" type="checkbox" onchange="mic(true)"></label>
    <span style="width:auto;text-align:left">couper le son sous le seuil
    (Gemini n'entend que ce qui dépasse, 1 s de maintien)</span></div>
  <div id="micd" class="mut"></div>
</div>

<div class="card">
  <div class="row"><span>Batterie</span><span class="big" id="batt">…</span></div>
  <div id="battd" class="mut"></div>
</div>

<div class="card">
  <div class="row"><span>Fantôme</span><span id="ghost">…</span></div>
  <div id="scare" class="mut"></div>
  <div id="dlg" class="mut"></div>
  <div class="grid">
    <button class="cmd" onclick="order('droit')">Tiens-toi droit</button>
    <button class="cmd" onclick="order('bouh')">Bouh</button>
    <button class="cmd" onclick="order('dodo')">Dodo</button>
    <button class="cmd" onclick="order('parle')">Parle</button>
  </div>
  <div id="ack" class="mut"></div>
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
    document.getElementById("dlg").textContent = "dialogue : " +
      (!s.dialogue_pc ? "tram non connecté" :
       (s.dialogue == "idle" || !s.dialogue ? "en attente" : "en cours (" + s.dialogue + ")"));
    var off = !s.ghost_alive || (a && a.state == "sirene");
    var cmds = document.querySelectorAll("button.cmd");
    for (var j = 0; j < cmds.length; j++) cmds[j].disabled = off;
    if (s.ack) document.getElementById("ack").textContent =
      "dernier ordre exécuté : " + NAMES[s.ack.name] + " il y a " + ago(s.ack.age);
  }).catch(function (e) {
    document.getElementById("err").textContent = "robot injoignable (" + e + ")";
  });
}
var NAMES = {droit: "tiens-toi droit", bouh: "bouh", dodo: "dodo", parle: "parle"};
function order(name) {
  document.getElementById("ack").textContent = "ordre envoyé : " + NAMES[name] + "…";
  fetch("cmd/" + name, {method: "POST"});
}
function disarm() {
  document.getElementById("stop").disabled = true;
  fetch("disarm", {method: "POST"}).then(refresh);
}
// --- micro ---
var MIN = -70, cfg = null, timer = null, peak = MIN, peakT = 0;
function pos(db) { return Math.max(0, Math.min(100, 100 * (db - MIN) / -MIN)); }
function mic(changed) {
  var g = +document.getElementById("gain").value,
      t = +document.getElementById("thr2").value,
      o = document.getElementById("gate").checked ? 1 : 0;
  document.getElementById("gainv").textContent = "x" + g;
  document.getElementById("thrv").textContent = t + " dBFS";
  document.getElementById("thrm").style.left = pos(t) + "%";
  cfg = [g, t, o];
  if (!changed) return;
  clearTimeout(timer);    // envoi apres 300 ms sans mouvement du curseur
  timer = setTimeout(function () {
    fetch("micro", {method: "POST", body: JSON.stringify(cfg)});
  }, 300);
}
function level() {
  fetch("level").then(function (r) { return r.json(); }).then(function (m) {
    if (!cfg) {
      document.getElementById("gain").value = m.settings[0];
      document.getElementById("thr2").value = m.settings[1];
      document.getElementById("gate").checked = !!m.settings[2];
      mic(false);
    }
    var d = document.getElementById("micd"), lvl = document.getElementById("lvl");
    if (m.raw == null || m.age > 2) {
      lvl.style.width = "0"; set("mdb", "—", "");
      d.textContent = "micro arrêté (tram non connecté au robot)";
      return;
    }
    var rms = Math.min(32767, m.raw * cfg[0]);
    var db = 20 * Math.log(Math.max(rms, 1) / 32768) / Math.LN10;
    lvl.style.width = pos(db) + "%";
    lvl.className = db > cfg[1] ? "loud" : "";
    var now = Date.now();
    if (db > peak || now - peakT > 2000) { peak = db; peakT = now; }
    document.getElementById("peak").style.left = pos(peak) + "%";
    set("mdb", db.toFixed(0) + " dBFS", db > cfg[1] ? "warn" : "");
    d.textContent = "brut " + m.raw + " (fond ~65) · " +
      (db > cfg[1] ? "voix" : "sous le seuil");
  }).catch(function () {});
}
refresh(); setInterval(refresh, 1000);
level(); setInterval(level, 200);
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

    def mic_init(self):
        try:
            v = json.load(open(MIC_FILE))
        except Exception:
            v = MIC_DEFAULT
        self.mic_set(v, save=False)

    def mic_set(self, v, save=True):
        v = [min(max(float(v[0]), 1.0), 60.0), min(max(float(v[1]), -60.0), 0.0),
             1 if v[2] else 0]
        with self.lock:
            self.mem().insertData("Halloween/MicSettings", v)
        if save:
            with open(MIC_FILE, "w") as f:
                json.dump(v, f)
        return v

    def level(self):
        with self.lock:
            m = self.mem()
            lv = self.get(m, "Halloween/MicLevel")
            st = self.get(m, "Halloween/MicSettings")
        if st is None:      # NAOqi a redemarre : remettre les reglages gardes
            self.mic_init()
            st = self.get(self.mem(), "Halloween/MicSettings", MIC_DEFAULT)
        return {"raw": lv[0] if lv else None,
                "age": time.time() - lv[1] if lv else None,
                "settings": st}

    def command(self, name):
        with self.lock:
            self.mem().insertData("Halloween/Command", [name, int(time.time())])

    def status(self):
        with self.lock:
            m = self.mem()
            v = m.getListData(LASER_KEYS)
            lidar = [round(math.hypot(v[2 * i], v[2 * i + 1]), 2) for i in range(15)]
            now = time.time()
            beat = self.get(m, "Halloween/Ghost")
            scare = self.get(m, "Halloween/LastScare")
            alarm = self.get(m, "Halloween/Alarm")
            ack = self.get(m, "Halloween/CommandAck")
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
                "dialogue": self.get(m, "Halloween/Dialogue"),
                "dialogue_pc": bool(self.get(m, "Halloween/DialoguePC")),
                "ack": {"name": ack[0], "age": now - ack[1]} if ack else None,
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
        elif self.path == "/level":
            try:
                self.send(200, json.dumps(self.state.level()), "application/json")
            except Exception as e:
                self.send(503, json.dumps({"error": str(e)}), "application/json")
        elif self.path == "/status":
            try:
                self.send(200, json.dumps(self.state.status()), "application/json")
            except Exception as e:
                self.send(503, json.dumps({"error": str(e)}), "application/json")
        else:
            self.send(404, "introuvable", "text/plain")

    def do_POST(self):
        if self.path == "/micro":
            try:
                n = int(self.headers.getheader("Content-Length") or 0)
                v = self.state.mic_set(json.loads(self.rfile.read(n)))
                self.send(200, json.dumps(v), "application/json")
            except Exception as e:
                self.send(400, json.dumps({"error": str(e)}), "application/json")
        elif self.path == "/disarm":
            open(DISARM_FILE, "w").close()   # antivol.py arrete la sirene
            self.send(200, '{"ok": true}', "application/json")
        elif self.path in ("/cmd/droit", "/cmd/bouh", "/cmd/dodo", "/cmd/parle"):
            try:
                self.state.command(self.path[5:])
                self.send(200, '{"ok": true}', "application/json")
            except Exception as e:
                self.send(503, json.dumps({"error": str(e)}), "application/json")
        else:
            self.send(404, "introuvable", "text/plain")

    def log_message(self, fmt, *args):
        if not any(p in (args[0] if args else "") for p in ("/status", "/level")):
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
    try:
        Handler.state.mic_init()
    except Exception as e:     # NAOqi pas encore pret : reglages par defaut
        os.write(2, "%s [web] reglages micro : %s\n" % (time.strftime("%H:%M:%S"), e))
    srv = Server(("", args.port), Handler)
    os.write(2, "%s [web] http://pepper:%d/\n"
             % (time.strftime("%H:%M:%S"), args.port))
    srv.serve_forever()


if __name__ == "__main__":
    main()
