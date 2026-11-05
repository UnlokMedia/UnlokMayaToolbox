"""Headless moss benchmark (mayapy): a 1.2 m faceted _GES boulder, Scatter
moss at High, then the live edits the user drags (Coverage, Strands,
Thickness, Patch size, Draft). Splits each step into engine time
(moss_build) and the rest (UDIM shift + writing the parts into Maya).

    mayapy tests/bench_moss.py [--detail High] [--profile] [--hash out.json]

--hash writes a fingerprint of every moss_build output (points, topology,
UVs hashed apart). Topology and UVs must match the old code's exactly; the
points differ by ~1e-10 from one run to the next even with the same code,
so compare old and new points in one process. --nogc: Python's cycle
collector off during each step (as sc_regrow runs builds).
"""
import cProfile
import gc
import hashlib
import io
import json
import math
import os
import pstats
import struct
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else True
    return default


DETAIL = arg("--detail", "High")
HASH = arg("--hash")
PROFILE = "--profile" in sys.argv
NOGC = "--nogc" in sys.argv

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402
import maya.api.OpenMaya as om  # noqa: E402


def load():
    ns = {"__name__": "bench_moss", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    return ns


def _h(i, j, k, seed):
    n = (i * 73856093) ^ (j * 19349663) ^ (k * 83492791) ^ (seed * 2654435761)
    n = (n ^ (n >> 13)) * 1274126177
    n = n ^ (n >> 16)
    return (n & 0xFFFFFF) / float(0xFFFFFF)


def vnoise(x, y, z, seed=0):
    xi, yi, zi = math.floor(x), math.floor(y), math.floor(z)
    xf, yf, zf = x - xi, y - yi, z - zi
    u, v, w = [t * t * t * (t * (t * 6 - 15) + 10) for t in (xf, yf, zf)]
    xi, yi, zi = int(xi), int(yi), int(zi)

    def L(a, b, t):
        return a + (b - a) * t
    c = [[[_h(xi + a, yi + b, zi + cc, seed) for cc in (0, 1)] for b in (0, 1)] for a in (0, 1)]
    x00 = L(c[0][0][0], c[1][0][0], u)
    x10 = L(c[0][1][0], c[1][1][0], u)
    x01 = L(c[0][0][1], c[1][0][1], u)
    x11 = L(c[0][1][1], c[1][1][1], u)
    return L(L(x00, x10, v), L(x01, x11, v), w) * 2.0 - 1.0


def fbm(x, y, z, octaves=4, seed=0):
    a, f, s, n = 1.0, 1.0, 0.0, 0.0
    for o in range(octaves):
        s += a * vnoise(x * f, y * f, z * f, seed + o)
        n += a
        a *= 0.5
        f *= 2.03
    return s / n


def make_rock():
    """A faceted boulder ~12 x 10 dm, ~6.5 dm tall (decimetre scene): a
    polytope smooth-min'd with a sphere, fbm relief, a crack."""
    node = cmds.polySphere(r=1, sx=56, sy=40, ch=False, name="rockGrey_C_boulder0001_GES")[0]
    sel = om.MSelectionList()
    sel.add(node)
    fn = om.MFnMesh(sel.getDagPath(0))
    raw = [((0.55, 0.75, 0.40), 0.70), ((-0.60, 0.70, 0.35), 0.72), ((0.35, 0.72, -0.62), 0.78),
           ((-0.40, 0.75, -0.55), 0.80), ((1.0, 0.12, 0.10), 0.92), ((-1.0, 0.10, -0.20), 0.90),
           ((0.10, 0.25, 1.0), 0.84), ((-0.20, 0.10, -1.0), 0.95), ((0.70, 0.15, 0.70), 0.88),
           ((-0.70, 0.20, 0.70), 0.86), ((0.75, 0.30, -0.60), 0.90)]
    planes = []
    for n, d in raw:
        l = math.sqrt(sum(c * c for c in n))
        planes.append(((n[0] / l, n[1] / l, n[2] / l), d))

    def smin(a, b, k):
        h = max(0.0, min(1.0, 0.5 + 0.5 * (b - a) / k))
        return b + (a - b) * h - k * h * (1 - h)
    out = []
    for p in fn.getPoints():
        l = math.sqrt(p.x * p.x + p.y * p.y + p.z * p.z) or 1.0
        v = (p.x / l, p.y / l, p.z / l)
        r = 1.2
        for n, d in planes:
            c = v[0] * n[0] + v[1] * n[1] + v[2] * n[2]
            if c > 0.05:
                r = smin(r, d / c, 0.07)
        X, Y, Z = v[0] * r * 6.4, v[1] * r * 5.6, v[2] * r * 5.6
        rr = math.sqrt(X * X + Y * Y + Z * Z) or 1.0
        disp = 0.18 * fbm(X * 0.3, Y * 0.3, Z * 0.3, 4, 3) + 0.05 * fbm(X * 1.3, Y * 1.3, Z * 1.3, 3, 9)
        g = abs(vnoise(X * 0.18, Y * 0.18 + 3.0, Z * 0.18, 21) * 6.0 + X * 0.35 - 1.2)
        disp -= 0.3 * math.exp(-g * g * 4.0) * (1.0 if X > -1 else 0.3)
        X += X / rr * disp
        Y += Y / rr * disp
        Z += Z / rr * disp
        Y += 1.4
        if Y < 0.0:
            Y = Y * 0.25
        out.append(om.MPoint(X, Y - 0.35, Z))
    fn.setPoints(out)
    cmds.rotate(0, -18, 0, node)
    cmds.makeIdentity(node, apply=True)
    cmds.polySoftEdge(node, a=180, ch=False)
    return cmds.ls(node, long=True)[0]


BASE = {"coverage": 0.72, "clump_size": 0.06, "size_var": 0.4, "thickness": 0.018, "mess": 0.5,
        "slope": 115.0, "crevices": 0.6, "edges": 1.0, "patchiness": 0.75, "patch_size": 0.3, "creases": 0.4,
        "strands": 1.4, "strand_length": 0.01, "droop": 0.3, "lumps": 0.45, "capsules": 0.0, "seed": 3}

STEPS = [("Coverage 0.72 -> 0.6", {"coverage": 0.6}),
         ("Strands 1.4 -> 1.0", {"strands": 1.0}),
         ("Thickness 0.018 -> 0.025", {"thickness": 0.025}),
         ("Lumps 0.45 -> 0.6", {"lumps": 0.6}),
         ("Patch size 0.3 -> 0.25", {"patch_size": 0.25}),
         ("Coverage 0.6 -> 0.65", {"coverage": 0.65})]


def fingerprint(out):
    """{part: [points, counts + corners, UVs] hashes} of a moss_build output."""
    got = {}
    for key in sorted(k for k, v in out.items() if isinstance(v, tuple) and len(v) == 6):
        pts, counts, conn, us, vs, uvi = out[key]
        hs = [hashlib.sha1() for _ in range(3)]
        for p in pts:
            hs[0].update(struct.pack("3d", p[0], p[1], p[2]))
        hs[1].update(struct.pack("%di" % len(counts), *counts))
        hs[1].update(struct.pack("%di" % len(conn), *conn))
        hs[2].update(struct.pack("%dd" % len(us), *us))
        hs[2].update(struct.pack("%dd" % len(vs), *vs))
        hs[2].update(struct.pack("%di" % len(uvi), *uvi))
        got[key] = [len(pts), len(counts)] + [h.hexdigest()[:12] for h in hs]
    return got


def main():
    tb = load()
    rock = make_rock()
    clock = {"engine": 0.0, "write": 0.0}
    prints = []
    real_build, real_write = tb["moss_build"], tb["_sc_write"]

    def moss_build(*a, **k):
        t = time.perf_counter()
        out = real_build(*a, **k)
        clock["engine"] += time.perf_counter() - t
        if HASH:
            prints.append(fingerprint(out))
        return out

    def sc_write(*a, **k):
        t = time.perf_counter()
        out = real_write(*a, **k)
        clock["write"] += time.perf_counter() - t
        return out
    tb["moss_build"], tb["_sc_write"] = moss_build, sc_write
    rows = []

    def step(label, fn):
        clock["engine"] = clock["write"] = 0.0
        prof = cProfile.Profile() if PROFILE else None
        gcs = sum(st["collections"] for st in gc.get_stats())
        if NOGC:
            gc.disable()
        t = time.perf_counter()
        if prof:
            prof.enable()
        rep = fn()
        if prof:
            prof.disable()
        total = time.perf_counter() - t
        gc.enable()
        print("  (gc collections %d, gen2 %d)" % (sum(st["collections"] for st in gc.get_stats()) - gcs,
                                                  gc.get_stats()[2]["collections"]))
        faces = sum(int(cmds.polyEvaluate(n, face=True)) for n in tb["sc_parts"](root_box[0]).values()
                    if cmds.getAttr(n + ".visibility")) if root_box[0] else 0
        rows.append((label, total, clock["engine"], clock["write"], faces))
        print("%-30s total %6.2f s  engine %6.2f  write %5.2f  faces %8d" % rows[-1])
        sys.stdout.flush()
        if prof:
            b = io.StringIO()
            pstats.Stats(prof, stream=b).sort_stats("tottime").print_stats(22)
            print(b.getvalue())
        return rep

    root_box = [None]
    s = dict(BASE, detail=DETAIL)

    def create():
        rep = tb["create_scatter_group"]([rock], "Moss", s, select=False)
        root_box[0] = rep["root"]
        return rep
    step("create (fresh) " + DETAIL, create)
    lid = tb["sc_data"](root_box[0])["layers"][0]["id"]
    for label, change in STEPS:
        step(label, lambda c=change: tb["sc_update"](root_box[0], lid, c))
    tb["sc_set_draft"](True)
    step("Draft: Coverage -> 0.55", lambda: tb["sc_update"](root_box[0], lid, {"coverage": 0.55}))
    step("Full detail", lambda: tb["sc_full_detail"]([root_box[0]]))
    tb["sc_set_draft"](False)
    print()
    print("%-30s %8s %8s %8s %9s" % ("step", "total", "engine", "write", "faces"))
    for r in rows:
        print("%-30s %8.2f %8.2f %8.2f %9d" % r)
    if HASH:
        with open(HASH, "w") as f:
            json.dump(prints, f, indent=1)
        print("fingerprints ->", HASH)


try:
    main()
except Exception:
    traceback.print_exc()
finally:
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(0)
