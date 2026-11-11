"""Headless tests: scattered dry grass (mayapy).

    mayapy tests/test_grass_scatter.py

The user (2026-11-11): "dry grass scattering needs improving, its currently
just doing small bunches, I need to be able to have more scattered stuff,
like just individual bits of grass here and there, or smaller piles,
instead of neat round bunches, more random, more extreme values possible".

New Grass settings, all 0 = the round bunches from before: Stray blades
(single blades per square metre), Size range (bunch_var), Irregular
(bunch_shape: stretched, lobed, split into lumps), Scatter (blade_scatter:
blades thrown loose round a bunch) and Blades per bunch (bunch_blades).

Scenes in decimetres: a yard (floor, wall, step, a plank on two bricks), a
30 degree ramp. Checked: with the new settings at 0 a build is what the old
toolbox built (UNLOK_OLD_TOOLBOX, optional: e.g. `git show
origin/main:UnlokToolbox.py` saved somewhere), each setting does what it
says, no blade goes into or through a surface with everything turned up,
and the cost.
"""

import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OLD = os.environ.get("UNLOK_OLD_TOOLBOX")
NEW_KEYS = ("grass_strays", "bunch_var", "bunch_shape", "blade_scatter", "bunch_blades")

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def load_toolbox(path):
    ns = {"__name__": "unlok_test", "__file__": path}
    with open(path) as f:
        exec(compile(f.read(), path, "exec"), ns)
    return ns


def box(name, size, at, parent=None, div=2.0, rot=None):
    node = cmds.polyCube(w=size[0], h=size[1], d=size[2], sx=max(1, int(size[0] / div)), sy=max(1, int(size[1] / div)),
                         sz=max(1, int(size[2] / div)), name=name, constructionHistory=False)[0]
    if rot:
        cmds.rotate(rot[0], rot[1], rot[2], node)
    cmds.move(at[0], at[1], at[2], node)
    if parent:
        node = cmds.parent(node, parent)[0]
    return cmds.ls(node, long=True)[0]


def yard():
    g = cmds.group(empty=True, name="grassYard_GRP")
    box("floor", (40, 1, 30), (0, -0.5, 0), g)
    box("wall", (40, 12, 1), (0, 6, -10.5), g, div=3.0)
    box("step", (12, 1.5, 5), (12, 0.75, 6), g, div=1.0)
    box("brickA", (1, 0.6, 2), (-12, 0.3, 6), g, div=1.0)
    box("brickB", (1, 0.6, 2), (-4, 0.3, 6), g, div=1.0)
    box("plank", (10, 0.2, 2.5), (-8, 0.7, 6), g, div=1.0)
    return [cmds.ls(g, long=True)[0]]


def ramp():
    g = cmds.group(empty=True, name="grassRamp_GRP")
    box("ramp", (30, 1, 20), (0, 0, 0), g, rot=(0, 0, 30))
    cmds.move(100, 0, 0, g)
    return [cmds.ls(g, long=True)[0]]


def blades(mesh):
    """A grass mesh's blades: each a ribbon, [(left edge points, right edge points)]."""
    pts, counts, conn = mesh[0], mesh[1], mesh[2]
    out, cur, k = [], None, 0
    for n in counts:
        a = conn[k]
        k += n
        if cur is None or a != cur[1]:
            cur = [a, a]
            out.append(cur)
        cur[1] = a + 2
    return [([pts[i] for i in range(a, b + 1, 2)], [pts[i + 1] for i in range(a, b + 1, 2)]) for a, b in out]


def spines(mesh):
    return [[tuple((a[i] + b[i]) * 0.5 for i in range(3)) for a, b in zip(l, r)] for l, r in blades(mesh)]


def safety(tb, nodes, mesh):
    """(inside, through, n): blade centre-line points over 1 mm inside a
    surface; blades with a segment crossing one and ending over 2 mm past."""
    surf = tb["_MiSurface"](nodes)
    mm = 0.001 / tb["scene_m_per_unit"]()
    inside, through, n = 0, 0, 0
    for spine in spines(mesh):
        n += 1
        for p in spine:
            hit = surf.closest(p)
            if hit is not None and sum((p[i] - hit[1][i]) * hit[2][i] for i in range(3)) < -mm:
                inside += 1
        for a, b in zip(spine, spine[1:]):
            d = [b[i] - a[i] for i in range(3)]
            ln = math.sqrt(sum(x * x for x in d))
            if ln < 1e-9:
                continue
            hit = surf.ray(a, [x / ln for x in d], ln)
            if hit is not None and sum((b[i] - hit[1][i]) * hit[2][i] for i in range(3)) < -2.0 * mm:
                through += 1
                break
    return inside, through, n


def spread_cells(mesh, cell):
    """Grid cells (cell scene units, x / z) holding a blade middle, per blade."""
    sp = spines(mesh)
    cells = set()
    for s in sp:
        p = s[len(s) // 2]
        cells.add((int(math.floor(p[0] / cell)), int(math.floor(p[2] / cell))))
    return len(cells) / float(max(1, len(sp)))


def settings(tb, **kw):
    s = dict(tb["DEBRIS_DEFAULTS"], grass=3.0, leaves=0.0, piles=0.0, tufts=0.0, coverage=0.9, slope=45.0, seed=7)
    s.update(kw)
    return s


def same_mesh(a, b):
    return len(a[0]) == len(b[0]) and list(a[1]) == list(b[1]) and list(a[2]) == list(b[2]) and max(
        [max(abs(p[i] - q[i]) for i in range(3)) for p, q in zip(a[0], b[0])] or [0.0]) < 1e-7


def main():
    tb = load_toolbox(TOOLBOX)
    cmds.file(new=True, force=True)

    def meshes(nodes):  # the builds take mesh transforms, not groups
        trs = []
        for n in nodes:
            trs += (cmds.listRelatives(n, allDescendents=True, type="transform", fullPath=True) or []) + [n]
        return [t for t in trs if tb["_log_shape"](t)]

    scenes = {"yard": meshes(yard()), "ramp": meshes(ramp())}
    m = tb["scene_m_per_unit"]()
    D = tb["DEBRIS_DEFAULTS"]
    grass = dict(tb["SC_TYPES"])["Grass"]
    check("the scattered-grass settings are debris settings, all off (old groups build as before)",
          all(k in D and not D[k] for k in NEW_KEYS), str([D.get(k) for k in NEW_KEYS]))
    check("... Grass layer keys, with fields, in the panel layout",
          all(k in grass["keys"] and k in tb["SC_FIELDS"] for k in NEW_KEYS) and
          all(any(k in sec[2] for sec in tb["SC_LAYOUT"]["Grass"]) for k in NEW_KEYS))
    check("... and not set by a new Grass layer", not any(k in grass.get("new", {}) for k in NEW_KEYS))
    names = list(tb["SC_PRESETS"]["Grass"])
    check("Grass presets Scattered blades, Loose wisps, Small messy piles",
          all(n in names for n in ("Scattered blades", "Loose wisps", "Small messy piles")), str(names))
    for name in ("Scattered blades", "Loose wisps", "Small messy piles"):
        s = tb["sc_preset"]("Grass", name)
        check("preset %s only names Grass settings" % name,
              s is not None and all(k in s for k in tb["SC_PRESETS"]["Grass"][name]))

    # --- off: exactly as before (flat and piles)
    if OLD:
        old = load_toolbox(OLD)
        for name, nodes in scenes.items():
            for pile in (0.0, 0.7):
                a = old["debris_build"](nodes, settings(old, grass_pile=pile))
                b = tb["debris_build"](nodes, settings(tb, grass_pile=pile))
                check("%s, Pile height %.1f: the new settings off build what the old toolbox did" % (name, pile),
                      same_mesh(a["grass"], b["grass"]) and a["bunches"] == b["bunches"],
                      "%d vs %d points" % (len(a["grass"][0]), len(b["grass"][0])))
    else:
        print("(UNLOK_OLD_TOOLBOX not set: old-toolbox comparison skipped)")
    for name, nodes in scenes.items():  # an old group's settings lack the keys: the same as them all 0
        s = settings(tb)
        bare = {k: v for k, v in s.items() if k not in NEW_KEYS}
        check("%s: settings without the new keys build the same as them at 0" % name,
              same_mesh(tb["debris_build"](nodes, bare)["grass"], tb["debris_build"](nodes, s)["grass"]))

    yard_n = scenes["yard"]
    cell = 0.05 / m  # 5 cm

    # --- Stray blades: single blades, here and there
    t0 = time.time()
    got = tb["debris_build"](yard_n, settings(tb, grass=0.0, grass_strays=40.0))
    t_str = time.time() - t0
    nb = len(blades(got["grass"]))
    check("Stray blades with no bunches: single blades grow (one to three each)",
          got["strays"] > 20 and got["strays"] <= nb <= 3 * got["strays"] and got["bunches"] == 0,
          "%d strays, %d blades, %.2fs" % (got["strays"], nb, t_str))
    check("... spread out, not in clumps", spread_cells(got["grass"], cell) > 0.7,
          "%.2f cells a blade" % spread_cells(got["grass"], cell))
    ins, thr, n = safety(tb, yard_n, got["grass"])
    check("... none into or through the wall, step, bricks or plank", ins <= n // 200 and thr <= max(1, n // 200),
          "%d points in, %d through, of %d" % (ins, thr, n))
    few = tb["debris_build"](yard_n, settings(tb, grass=0.0, grass_strays=10.0))["strays"]
    check("... more Stray blades, more of them", got["strays"] > 2.5 * few, "%d vs %d" % (got["strays"], few))

    # --- Size range: wider spread of bunch radii, mostly smaller
    radii, centres = [], []
    cls = tb["_DebrisBuild"]
    orig = cls._bunch_lump

    def spy(self, c, n, r, ci, Rb, Lg, full, j, shape):
        radii.append((Rb, j, shape))
        centres.append((j, c, Rb))
        return orig(self, c, n, r, ci, Rb, Lg, full, j, shape)

    cls._bunch_lump = spy
    try:
        stats = {}
        for key, val in (("base", 0.0), ("var", 1.0)):
            del radii[:]
            tb["debris_build"](yard_n, settings(tb, grass=6.0, bunch_var=val, size_var=0.5))
            rs = sorted(r for r, _, _ in radii)
            stats[key] = (rs[-1] / rs[0], rs[len(rs) // 2], len(rs)) if rs else (0.0, 0.0, 0)
        check("Size range 1: bunches from tiny to big (radius max / min)",
              stats["var"][0] > 6.0 and stats["base"][0] < 2.5,
              "%.1fx (off %.1fx)" % (stats["var"][0], stats["base"][0]))
        check("... mostly smaller ones", stats["var"][1] < stats["base"][1], "median %.3f vs %.3f" % (
            stats["var"][1], stats["base"][1]))
        # --- Irregular: lumps, stretched
        del radii[:]
        tb["debris_build"](yard_n, settings(tb, grass=6.0, bunch_shape=1.0))
        lumps = sum(1 for _, j, _ in radii if j > 0)
        roundish = sum(1 for _, _, sh in radii if sh is None)
        check("Irregular 1: bunches split into lumps, none round", lumps > 0.4 * (len(radii) - lumps) and roundish == 0,
              "%d lumps besides %d firsts" % (lumps, len(radii) - lumps))
        long = sum(1 for _, _, sh in radii if sh is not None and sh[2] > 1.5)
        check("... most of them stretched", long > 0.5 * len(radii), "%d of %d" % (long, len(radii)))
        apart, first = [], None
        for j, c, Rj in centres:
            if j == 0:
                first = c
            elif first is not None:
                apart.append(math.sqrt(sum((c[i] - first[i]) ** 2 for i in range(3))) / Rj)
        mean = sum(apart) / max(1, len(apart))
        check("... the lumps set apart from each other (not one round bunch)", mean > 0.8,
              "lump centres %.2f of their radius from the first" % mean)
    finally:
        cls._bunch_lump = orig
    irr = tb["debris_build"](yard_n, settings(tb, grass=6.0, bunch_shape=1.0))
    ins, thr, n = safety(tb, yard_n, irr["grass"])
    check("... no lump into or through the wall, step, bricks or plank", ins <= n // 200 and thr <= max(1, n // 200),
          "%d points in, %d through, of %d" % (ins, thr, n))

    # --- Scatter: blades thrown loose
    for pile in (0.0, 0.7):
        sc = tb["debris_build"](yard_n, settings(tb, grass=6.0, blade_scatter=1.0, grass_pile=pile))
        b0 = tb["debris_build"](yard_n, settings(tb, grass=6.0, grass_pile=pile))
        a, b = spread_cells(sc["grass"], cell), spread_cells(b0["grass"], cell)
        check("Scatter 1 (Pile height %.1f): blades strewn round the bunches" % pile, a > 1.6 * b,
              "%.3f vs %.3f cells a blade" % (a, b))

    # --- Blades per bunch
    wisp = tb["debris_build"](yard_n, settings(tb, grass=6.0, bunch_blades=3))
    per = len(blades(wisp["grass"])) / float(max(1, wisp["bunches"]))
    check("Blades per bunch 3: wisps of a few blades", 1.0 <= per <= 4.5 and wisp["bunches"] > 10,
          "%.1f blades a bunch over %d" % (per, wisp["bunches"]))
    one = tb["debris_build"](yard_n, settings(tb, grass=6.0, bunch_blades=1, grass_pile=0.7))
    per = len(blades(one["grass"])) / float(max(1, one["bunches"]))
    check("Blades per bunch 1 on piles: one or two", 1.0 <= per <= 2.0, "%.1f" % per)

    # --- the presets and everything turned up: safe, not slow
    for name in ("Scattered blades", "Loose wisps", "Small messy piles"):
        for sn, nodes in scenes.items():
            s = tb["sc_preset"]("Grass", name)
            s.update({"leaves": 0.0, "piles": 0.0, "tufts": 0.0, "seed": 5})
            t0 = time.time()
            got = tb["debris_build"](nodes, s)
            dt = time.time() - t0
            ins, thr, n = safety(tb, nodes, got["grass"])
            check("%s on the %s: grows, nothing into or through a surface" % (name, sn),
                  n > 10 and ins <= max(2, n // 100) and thr <= max(1, n // 200),
                  "%d blades, %d points in, %d through, %.2fs" % (n, ins, thr, dt))
    s = settings(tb, grass=20.0, grass_strays=200.0, bunch_var=1.0, bunch_shape=1.0, blade_scatter=2.0,
                 bunch_size=1.5, grass_length=0.8, grass_pile=1.5)
    t0 = time.time()
    got = tb["debris_build"](yard_n, s)
    dt = time.time() - t0
    ins, thr, n = safety(tb, yard_n, got["grass"])
    check("everything turned up: builds, safe", n > 100 and ins <= max(2, n // 100) and thr <= max(1, n // 100),
          "%d blades, %d points in, %d through, %.2fs, capped %s" % (n, ins, thr, dt, got["capped"]))


try:
    main()
except Exception:
    traceback.print_exc()
    check("ran without errors", False, "exception")
failed = [r for r in RESULTS if not r[1]]
print("%d checks, %d failed" % (len(RESULTS), len(failed)))
for name, ok, detail in failed:
    print("FAILED: %s  %s" % (name, detail))
sys.stdout.flush()
maya.standalone.uninitialize()
os._exit(1 if failed else 0)
