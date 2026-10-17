# Simulation hors robot de la detection anti-vol (Python 3, faux services)
# Usage : python3 simu_antivol.py <dossier contenant antivol.py>
import sys, time, math, types
sys.path.insert(0, sys.argv[1])
import antivol
antivol._log = lambda m: print("   log:", m)
antivol.RATE = 200.0; antivol.TILT_HOLD = 0.05; antivol.GYRO_HOLD = 0.05

class Mem:
    def __init__(s): s.v = [-0.005, -0.026, -0.26, -0.09, -8.96, 0, 0, 0]
    def getListData(s, k): return list(s.v)
class Svc:
    def __getattr__(s, n): return lambda *a, **k: None
class Sess:
    def __init__(s): s.mem = Mem()
    def service(s, n): return s.mem if n == "ALMemory" else Svc()

def scenario(name, mutate):
    sess = Sess(); a = antivol.TheftAlarm(sess)
    a.ref = None
    # calibrage rapide
    t0 = time.time(); a.ref = (-0.005, -0.026, math.sqrt(0.26**2+0.09**2+8.96**2))
    a.reset_peaks()
    import threading
    a._stop = False
    th = threading.Thread(target=a._run); th.daemon = True; th.start()
    real_sleep = __import__("time").sleep
    mutate(sess.mem, real_sleep)
    real_sleep(0.3); a._stop = True
    print("%-32s -> sirene=%s" % (name, a.active))

scenario("repos (bruit)", lambda m, sl: None)
def tilt(m, sl): m.v[1] = -0.026 + math.radians(12); sl(0.2)
scenario("penche 12 deg", tilt)
def tilt_short(m, sl): m.v[1] = -0.026 + math.radians(12)
scenario("penche 5 deg", lambda m, sl: m.v.__setitem__(1, -0.026 + math.radians(5)))
def lift(m, sl):
    for i in range(10):
        m.v[4] = -8.96 - (4 if i % 2 else -4); sl(0.01)
    m.v[4] = -8.96
scenario("secousses (soulevé)", lift)
scenario("rotation 1 rad/s", lambda m, sl: m.v.__setitem__(7, 1.0))
