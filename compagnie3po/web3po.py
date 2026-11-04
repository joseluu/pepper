# -*- coding: utf-8 -*-
# Telecommande de l'esprit de compagnie 3PO : attention (Ecoute / Pause),
# posture, alarme anti-vol, micro, batterie. Derivee de halloween/web.py.
# Bibliotheque standard seulement (pas de Flask sur le robot).
#
# Lancer (sur le robot) : python2 web3po.py [--port 8080]
# Puis ouvrir http://pepper:8080/
#
# Etat lu dans ALMemory : 3PO/Ghost (battement de compagnon.py), 3PO/State,
# 3PO/DialoguePC (tram connecte au pont audio), Halloween/Alarm (antivol.py,
# partage avec le fantome). Boutons : 3PO/Command, execute par compagnon.py
# (accuse dans 3PO/CommandAck). Le bouton d'arret de la sirene cree
# ~/halloween/desarme, lu par antivol.py.
# Micro : niveau dans 3PO/MicLevel (pont audio), reglages [gain, seuil dBFS
# apres gain, porte] dans 3PO/MicSettings, gardes dans ~/compagnie3po/micro.json.
import os, json, time, argparse, threading
import BaseHTTPServer, SocketServer
import qi

HERE = os.path.dirname(os.path.abspath(__file__))
DISARM_FILE = os.path.join(HERE, "..", "halloween", "desarme")
MIC_FILE = os.path.join(HERE, "micro.json")
MIC_DEFAULT = [20.0, -16.0, 0]   # = live.py : gain x20, seuil 250 x 20 avant gain
COMMANDS = ("ecoute", "pause", "droit")
BATT = "Device/SubDeviceList/Battery/%s/Sensor/Value"

PAGE = u"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Esprit de compagnie 3PO</title>
<style>
:root { --bg:#111; --fg:#eee; --mut:#999; --card:#1d1d1d; --red:#e53935;
        --green:#43a047; --amber:#f9a825; --blue:#5c6bc0; }
body { margin:0; padding:16px; background:var(--bg); color:var(--fg);
       font:16px/1.4 system-ui, sans-serif; }
h1 { font-size:1.3em; margin:0 0 12px; }
.card { background:var(--card); border-radius:10px; padding:12px 14px;
        margin-bottom:12px; }
.big { font-size:2em; font-weight:600; }
.mut { color:var(--mut); font-size:.9em; }
.row { display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap; }
button { width:100%; padding:16px; font-size:1.2em; border:0; border-radius:10px;
         background:var(--red); color:#fff; font-weight:600; }
button:disabled { background:#444; color:#888; }
.grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px; }
.grid button { background:var(--blue); padding:14px 8px; }
.grid button.wide { grid-column:1 / 3; }
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
<h1>Esprit de compagnie 3PO</h1>

<div class="card">
  <div class="row"><span>Attention</span><span id="state" class="big">…</span></div>
  <div id="dlg" class="mut"></div>
  <div class="grid">
    <button class="cmd" onclick="order('ecoute')">Écoute</button>
    <button class="cmd" onclick="order('pause')">Pause</button>
    <button class="cmd wide" onclick="order('droit')">Tiens-toi droit</button>
  </div>
  <div id="ack" class="mut"></div>
</div>

<div class="card">
  <div class="row"><span>Alarme anti-vol</span><span id="alarm" class="big">…</span></div>
  <div id="alarmd" class="mut"></div>
  <p><button id="stop" disabled onclick="disarm()">Arrêter la sirène</button></p>
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
var NAMES = {ecoute: "écoute", pause: "pause", droit: "tiens-toi droit"};

function refresh() {
  fetch("status").then(function (r) { return r.json(); }).then(function (s) {
    document.getElementById("err").textContent = "";
    if (!s.alive) set("state", "arrêté", "bad");
    else if (s.state == "ecoute") set("state", "à l'écoute", "ok");
    else set("state", "en pause", "");
    document.getElementById("dlg").textContent = s.dialogue_pc ?
      "tram connecté (Gemini Live)" : "tram non connecté : l'écoute est impossible";

    var a = s.alarm, stop = document.getElementById("stop");
    if (!s.alive || !a) {
      set("alarm", "inactive", "warn"); stop.disabled = true;
      document.getElementById("alarmd").textContent =
        s.alive ? "lancé sans alarme" : "programme arrêté";
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
    var off = !s.alive || (a && a.state == "sirene");
    var cmds = document.querySelectorAll("button.cmd");
    for (var j = 0; j < cmds.length; j++) cmds[j].disabled = off;
    if (s.ack) document.getElementById("ack").textContent =
      "dernier ordre exécuté : " + NAMES[s.ack.name] + " il y a " + ago(s.ack.age);

    var pct = Math.round(s.battery * 100);
    set("batt", pct + " %", pct < 20 ? "bad" : (pct < 40 ? "warn" : "ok"));
    document.getElementById("battd").textContent =
      (s.current > 0.05 ? "en charge" : "sur batterie") +
      " · " + s.current.toFixed(2) + " A · " + s.batt_temp.toFixed(0) + " °C";
  }).catch(function (e) {
    document.getElementById("err").textContent = "robot injoignable (" + e + ")";
  });
}
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
    def __init__(self):
        self.session = None
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
            self.mem().insertData("3PO/MicSettings", v)
        if save:
            with open(MIC_FILE, "w") as f:
                json.dump(v, f)
        return v

    def level(self):
        with self.lock:
            m = self.mem()
            lv = self.get(m, "3PO/MicLevel")
            st = self.get(m, "3PO/MicSettings")
        if st is None:      # NAOqi a redemarre : remettre les reglages gardes
            self.mic_init()
            st = self.get(self.mem(), "3PO/MicSettings", MIC_DEFAULT)
        return {"raw": lv[0] if lv else None,
                "age": time.time() - lv[1] if lv else None,
                "settings": st}

    def command(self, name):
        with self.lock:
            self.mem().insertData("3PO/Command", [name, int(time.time())])

    def status(self):
        with self.lock:
            m = self.mem()
            now = time.time()
            beat = self.get(m, "3PO/Ghost")
            alarm = self.get(m, "Halloween/Alarm")
            ack = self.get(m, "3PO/CommandAck")
            # ALMemory : entiers 32 bits (les flottants y perdent la precision)
            alive = beat is not None and now - beat < 5
            return {
                "alive": alive,
                "state": self.get(m, "3PO/State"),
                "dialogue_pc": bool(self.get(m, "3PO/DialoguePC")),
                "ack": {"name": ack[0], "age": now - ack[1]} if ack else None,
                "battery": self.get(m, BATT % "Charge", 0.0),
                "current": self.get(m, BATT % "Current", 0.0),
                "batt_temp": self.get(m, BATT % "Temperature", 0.0),
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

    def send_json(self, fn):
        try:
            self.send(200, json.dumps(fn()), "application/json")
        except Exception as e:
            self.send(503, json.dumps({"error": str(e)}), "application/json")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/level":
            self.send_json(self.state.level)
        elif self.path == "/status":
            self.send_json(self.state.status)
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
        elif self.path.startswith("/cmd/") and self.path[5:] in COMMANDS:
            self.send_json(lambda: self.state.command(self.path[5:]) or {"ok": True})
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
    args = p.parse_args()
    Handler.state = State()
    try:
        Handler.state.mic_init()
    except Exception as e:     # NAOqi pas encore pret : reglages par defaut
        os.write(2, "%s [web] reglages micro : %s\n" % (time.strftime("%H:%M:%S"), e))
    srv = Server(("", args.port), Handler)
    os.write(2, "%s [web] http://pepper:%d/\n" % (time.strftime("%H:%M:%S"), args.port))
    srv.serve_forever()


if __name__ == "__main__":
    main()
