"""Headless tests: dropped leaves touch what they lie on (mayapy).

    mayapy tests/test_leaf_contact.py [--measure]

The user (2026-11-05): leaf scattering gave "lots of floating leaves and bad
interaction between leaves, no proper draping onto the surface"; wanted the
big gaps between leaves and surfaces and between leaves fixed, better
draping, and a check that finds and fixes any floating leaves left.

Scenes in decimetres: a yard (floor, a tall wall, a window lip, a step, a
grating of rails), a 30 degree ramp, a lumpy rock, a ball, corrugated roofs
from the Roof tool, a glass roof with mullions and a dense floor of leaves.
Every leaf of Leaves, Leaf piles and Jungle leaves is measured: under each
of its points, how far down the surface or another leaf is (the air under
it). A leaf floats when even its lowest point is clear of everything under
it; it drapes when most of it is close to what it lies on.
"""

import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
MEASURE = "--measure" in sys.argv

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402
import maya.api.OpenMaya as om  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def load_toolbox():
    ns = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    return ns


def box(name, size, at, parent=None, div=2.0):
    node = cmds.polyCube(w=size[0], h=size[1], d=size[2], sx=max(1, int(size[0] / div)), sy=max(1, int(size[1] / div)),
                         sz=max(1, int(size[2] / div)), name=name, constructionHistory=False)[0]
    cmds.move(at[0], at[1], at[2], node)
    if parent:
        node = cmds.parent(node, parent)[0]
    return cmds.ls(node, long=True)[0]


def pieces(tb, node):
    """A part's separate pieces (one a leaf): [(points, triangles)]."""
    fn = om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))
    pts = [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kWorld)]
    counts, ids = fn.getVertices()
    up = list(range(len(pts)))

    def find(a):
        while up[a] != a:
            up[a] = up[up[a]]
            a = up[a]
        return a

    faces, k = [], 0
    for c in counts:
        f = list(ids[k:k + c])
        faces.append(f)
        r0 = find(f[0])
        for i in f[1:]:
            ri = find(i)
            if ri != r0:
                up[ri] = r0
        k += c
    order, local = {}, {}
    for i in range(len(pts)):
        r = find(i)
        if r not in order:
            order[r] = ([], [])
        local[i] = len(order[r][0])
        order[r][0].append(pts[i])
    for f in faces:
        g = order[find(f[0])]
        for j in range(1, len(f) - 1):
            g[1].append((local[f[0]], local[f[j]], local[f[j + 1]]))
    return list(order.values())


class Under(object):
    """The leaves of a scene seen from above, to find the leaf under a point."""

    def __init__(self, leaves, cell=0.25):
        self.c = cell
        self.grid = {}
        for n, (pts, tris) in enumerate(leaves):
            for t in tris:
                a, b, c = pts[t[0]], pts[t[1]], pts[t[2]]
                for i in range(int(math.floor(min(a[0], b[0], c[0]) / cell)),
                               int(math.floor(max(a[0], b[0], c[0]) / cell)) + 1):
                    for k in range(int(math.floor(min(a[2], b[2], c[2]) / cell)),
                                   int(math.floor(max(a[2], b[2], c[2]) / cell)) + 1):
                        self.grid.setdefault((i, k), []).append((n, a, b, c))

    def touching(self, leaves):
        """{leaf: the smallest gap between its faces and the points of the
        leaves under it}: a leaf lying on the curled rim of the one under it
        touches it there, between its own points."""
        out = {}
        for k, (pts, tris) in enumerate(leaves):
            for x, y, z in pts:
                for m, a, b, c in self.grid.get((int(math.floor(x / self.c)), int(math.floor(z / self.c))), ()):
                    if m == k:
                        continue
                    d = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
                    if abs(d) < 1e-12:
                        continue
                    w1 = ((b[2] - c[2]) * (x - c[0]) + (c[0] - b[0]) * (z - c[2])) / d
                    w2 = ((c[2] - a[2]) * (x - c[0]) + (a[0] - c[0]) * (z - c[2])) / d
                    if min(w1, w2, 1.0 - w1 - w2) < -1e-6:
                        continue
                    g = w1 * a[1] + w2 * b[1] + (1.0 - w1 - w2) * c[1] - y
                    if -0.005 <= g < out.get(m, 1e9):
                        out[m] = g
        return out

    def top(self, x, y, z, skip):
        """The highest leaf (not skip) under (x, z) no higher than y + 0.5 mm."""
        best = None
        for m, a, b, c in self.grid.get((int(math.floor(x / self.c)), int(math.floor(z / self.c))), ()):
            if m == skip:
                continue
            d = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
            if abs(d) < 1e-12:
                continue
            w1 = ((b[2] - c[2]) * (x - c[0]) + (c[0] - b[0]) * (z - c[2])) / d
            w2 = ((c[2] - a[2]) * (x - c[0]) + (a[0] - c[0]) * (z - c[2])) / d
            w3 = 1.0 - w1 - w2
            if min(w1, w2, w3) < -1e-6:
                continue
            h = w1 * a[1] + w2 * b[1] + w3 * c[1]
            if h <= y + 0.005 and (best is None or h > best):
                best = h
        return best


def gaps(surf, under, n, pts, reach):
    """[(gap, on a leaf)] under each point of leaf n (None: nothing within
    reach under it - hanging over an edge)."""
    out = []
    for x, y, z in pts:
        hit = surf.ray((x, y + 0.02, z), (0.0, -1.0, 0.0), reach + 0.02)
        hs = (y + 0.02 - hit[0]) if hit is not None and hit[2][1] > 0.05 else None
        hl = under.top(x, y, z, n)
        if hl is not None and y - hl > reach:
            hl = None
        if hs is None and hl is None:
            out.append(None)
        elif hl is not None and (hs is None or hl > hs):
            out.append((y - hl, True))
        else:
            out.append((y - hs, False))
    return out


def size(pts):
    return math.hypot(max(p[0] for p in pts) - min(p[0] for p in pts), max(p[2] for p in pts) - min(p[2] for p in pts))


def report(surf, leaves, label, skip=None):
    """{floating, big, on_leaf, air, n, worst}: floating = leaves whose
    lowest point is over 5 mm (a leaf lies 1 mm off what it rests on) off everything under it, big = over 1 cm;
    air = the mean share of a leaf's points more than a tenth of its length
    off what's under them (how well it drapes; a cupped leaf on its
    midrib keeps its edges up). skip(middle): leaves not counted."""
    under = Under(leaves)
    rims = under.touching(leaves)
    floating, big, worst, airs, ll = [], 0, (0.0, None), [], 0
    for n, (pts, tris) in enumerate(leaves):
        if skip is not None and skip(tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))):
            continue
        L = max(0.05, size(pts))
        mids = [tuple((pts[a][i] + pts[b][i] + pts[c][i]) / 3.0 for i in range(3)) for a, b, c in tris]
        g = gaps(surf, under, n, pts + mids, max(0.6, 0.6 * L))  # face middles too: one across a thin rail
        held = [q for q in g if q is not None]
        if len(held) < 0.3 * len(g):
            continue  # mostly over an edge: draping off it, not lying on anything
        low = min(held)
        if rims.get(n, 1e9) < low[0]:
            low = (rims[n], True)  # on the rim of the leaf under it
        if low[1]:
            ll += 1
        if low[0] > 0.05:
            floating.append(n)
            if low[0] > 0.1:
                big += 1
            if low[0] > worst[0]:
                c = tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))
                worst = (low[0], c)
        airs.append(sum(1 for q in held if q[0] > 0.1 * L) / float(len(held)))
    air = sum(airs) / len(airs) if airs else 0.0
    out = {"n": len(leaves), "floating": len(floating), "big": big, "on_leaf": ll, "air": air, "worst": worst,
           "idx": floating}
    print("  %-34s %4d leaves  floating %3d (>1cm %3d)  resting on a leaf %3d  air %.2f  worst %.1f mm %s" % (
        label, len(leaves), len(floating), big, ll, air, 100.0 * worst[0],
        "(%.1f, %.1f, %.1f)" % worst[1] if worst[1] else ""))
    sys.stdout.flush()
    return out


def scenes(tb):
    """{name: ([surface nodes], settings overrides)}."""
    out = {}
    yard_g = cmds.group(empty=True, name="yard_GRP")
    box("floor", (60, 1, 40), (0, -0.5, 0), yard_g)
    box("tallWall", (60, 15, 1), (0, 7.5, -19.5), yard_g, div=3.0)
    box("windowLip", (24, 0.4, 0.5), (15, 0.2, -3), yard_g, div=1.0)
    box("stairStep", (24, 1.5, 4), (15, 0.75, 5), yard_g, div=1.0)
    for k in range(11):
        box("rail%d" % k, (20, 0.4, 0.4), (-15, 0.2, -6 + 1.2 * k), yard_g, div=1.0)
    out["yard"] = [cmds.ls(yard_g, long=True)[0]]
    ramp = cmds.polyPlane(name="ramp", w=30, h=30, sx=15, sy=15, constructionHistory=False)[0]
    cmds.rotate(30, 0, 0, ramp)
    cmds.move(0, 0, 100, ramp)
    out["ramp 30"] = [cmds.ls(ramp, long=True)[0]]
    rock = cmds.polySphere(name="rock", r=8, sx=48, sy=32, constructionHistory=False)[0]
    fn = om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](rock)))
    ps = fn.getPoints()
    for i, p in enumerate(ps):
        n = (math.sin(1.7 * p.x + 0.3) * math.cos(1.3 * p.z) + 0.6 * math.sin(2.9 * p.y + 1.1 * p.x)) * 0.5
        s = (1.0 + 0.06 * n) * (0.55 if p.y < 0.0 else 1.0)
        ps[i] = om.MPoint(p.x * (1.0 + 0.04 * n), p.y * s, p.z * (1.0 + 0.04 * n))
    fn.setPoints(ps)
    cmds.move(0, 4, 200, rock)
    flr = box("rockFloor", (40, 1, 40), (0, -0.5, 200), div=4.0)
    out["rock"] = [cmds.ls(rock, long=True)[0], flr]
    ball = cmds.polySphere(name="ball", r=6, sx=40, sy=30, constructionHistory=False)[0]
    cmds.move(100, 6, 200, ball)
    out["ball"] = [cmds.ls(ball, long=True)[0]]
    house = box("house", (24, 10, 16), (100.0, 5.0, 0.0), div=8.0)
    rep = tb["make_thatch_roof"](house, {"covering": "Corrugated", "m_mode": "Clean", "overhang": 0.03,
                                         "shape": "Lean-to", "end_a": "Gable", "end_b": "Gable"})
    out["corrugated"] = [rep["root"]]
    g = cmds.group(empty=True, name="glass_GRP")
    for ix in range(4):
        for iz in range(3):
            box("pane_%d_%d" % (ix, iz), (5.6, 0.06, 5.6), (-9.0 + ix * 6.0, 0.0, -6.0 + iz * 6.0), g, div=6.0)
    for ix in range(5):
        box("mullionX_%d" % ix, (0.4, 0.4, 18.4), (-12.0 + ix * 6.0, 0.17, 0.0), g, div=2.0)
    for iz in range(4):
        box("mullionZ_%d" % iz, (24.4, 0.4, 0.4), (0.0, 0.17, -9.0 + iz * 6.0), g, div=2.0)
    cmds.rotate(12, 0, 0, g)
    cmds.move(200.0, 20.0, 0.0, g)
    out["glass roof"] = [cmds.ls(g, long=True)[0]]
    dense = box("denseFloor", (20, 1, 20), (200, -0.5, 200), div=4.0)
    out["dense floor"] = [dense]
    return out


LAYERS = (("Leaves", "litter", {"leaves": 30.0, "coverage": 0.85, "slope": 45.0}),
          ("Leaf piles", "piles", {"coverage": 0.85, "slope": 45.0}),
          ("Jungle leaves", None, {"jungle": 3.0, "coverage": 0.85, "slope": 45.0}))


def run():
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    tb["scene_m_per_unit"]()
    out = {}
    for name, nodes in scenes(tb).items():
        trs = []
        for n in nodes:
            trs += (cmds.listRelatives(n, allDescendents=True, type="transform", fullPath=True) or []) + [n]
        surf = tb["_MiSurface"]([t for t in trs if tb["_log_shape"](t)])
        root = None
        for typ, part, s in LAYERS:
            s = dict(s)
            if name == "dense floor":
                if typ == "Leaf piles":
                    continue
                s.update({"leaves": 250.0, "coverage": 1.0} if typ == "Leaves" else {"jungle": 12.0, "coverage": 1.0})
            t0 = time.time()
            if root is None:
                root = tb["create_scatter_group"](nodes, typ, s)["root"]
                lid = tb["sc_data"](root)["layers"][0]["id"]
            else:
                _, lid = tb["sc_add_layer"](root, typ, s)
            dt = time.time() - t0
            leaves = []
            for key, node in tb["sc_parts"](root).items():
                p = key.split("/")[1]
                if key.startswith(lid + "/") and (p == part or (part is None and p in ("green", "dry"))) \
                        and cmds.getAttr(node + ".visibility"):
                    leaves += pieces(tb, node)
            grating = (lambda c: -25.5 < c[0] < -4.5 and -6.8 < c[2] < 6.8) if name == "yard" else None
            out[(name, typ)] = report(surf, leaves, "%s / %s (%.1fs)" % (name, typ, dt), grating)  # (across the
            # rails: rested on them, test_scatter)
            if name == "ramp 30" and typ == "Leaves":
                got = tb["debris_build"](nodes, dict(tb["DEBRIS_DEFAULTS"], grass=0.0, tufts=0.0, piles=0.0, **s))
                out["contact"] = got.get("contact")
    return out


try:
    got = run()
    if not MEASURE:
        contact = got.pop("contact", None)
        for (name, typ), r in sorted(got.items()):
            check("%s / %s: no leaf floats" % (name, typ),
                  r["floating"] <= max(0, r["n"] // 100) and r["big"] <= r["n"] // 100,
                  "%d of %d leaves over 5 mm off what's under them (%d over 1 cm), worst %.1f mm" % (
                      r["floating"], r["n"], r["big"], 100.0 * r["worst"][0]))
        curls = [(name, round(r["air"], 2)) for (name, typ), r in sorted(got.items()) if typ == "Leaves" and r["n"] > 10]
        check("Leaves keep their curl (pressed onto what's under them, not flat)", all(a >= 0.05 for _, a in curls),
              "share of points held up by the leaf's own cup: %s" % curls)
        check("the build reports what its contact pass fixed (leaves brought down onto the ramp)",
              contact is not None and contact["lowered"] > 50, contact)
except Exception:
    traceback.print_exc()
    RESULTS.append(("crashed", False, ""))
failed = [r for r in RESULTS if not r[1]]
print("\n%d checks, %d failed" % (len(RESULTS), len(failed)))
for name, _, detail in failed:
    print("FAILED: %s  %s" % (name, detail))
sys.stdout.flush()
maya.standalone.uninitialize()
os._exit(1 if failed else 0)
