"""Headless tests: loose piles of dry grass (mayapy).

    mayapy tests/test_grass_pile.py

The user (2026-11-06): "trying to scatter some loose piles of dry grass but
its just flat clumps". Grass bunches were a 3 cm mound on a 30 cm clump with
every blade pressed onto it. Pile height (`grass_pile`) builds a loose heap:
a lumpy dome Pile height x its radius high, blades all through it, ends
splaying out and drooping onto the ground.

Scenes in decimetres: a yard (floor, a tall wall, a step, a thin plank lying
across two bricks), a 30 degree ramp. Checked: Pile height 0 builds what the
old toolbox built (UNLOK_OLD_TOOLBOX, optional), piles stand up, no blade
point is inside a surface, no blade edge passes through one, blades lie
every which way, and the cost.
"""

import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OLD = os.environ.get("UNLOK_OLD_TOOLBOX")

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


def measure(tb, nodes, mesh, Hp):
    """{high, inside, through, tilted, n}, on each blade's centre line (a
    twisted ribbon lying on a surface dips its edge a hair under it): high =
    the share of points more than a quarter of the pile's height Hp off the
    surface; inside = points more than 1 mm inside a surface (the nearest
    face is behind them); through = blades with a segment that crosses a
    surface and ends more than 2 mm past it; tilted = blades whose ends'
    line leaves the surface under its middle by over a fifth of its length."""
    surf = tb["_MiSurface"](nodes)
    mm = 0.001 / tb["scene_m_per_unit"]()
    high, pts, inside, through, tilted, n = 0, 0, 0, 0, 0, 0
    for left, right in blades(mesh):
        n += 1
        spine = [tuple((a[i] + b[i]) * 0.5 for i in range(3)) for a, b in zip(left, right)]
        for p in spine:
            hit = surf.closest(p)
            if hit is None:
                continue
            off = sum((p[i] - hit[1][i]) * hit[2][i] for i in range(3))
            pts += 1
            if off > 0.25 * Hp:
                high += 1
            if off < -mm:
                inside += 1
        for a, b in zip(spine, spine[1:]):
            d = [b[i] - a[i] for i in range(3)]
            ln = math.sqrt(sum(x * x for x in d))
            if ln < 1e-9:
                continue
            d = [x / ln for x in d]
            hit = surf.ray(a, d, ln)
            if hit is not None and sum((b[i] - hit[1][i]) * hit[2][i] for i in range(3)) < -2.0 * mm:
                through += 1
                break
        L = sum(math.sqrt(sum((q[i] - p[i]) ** 2 for i in range(3))) for p, q in zip(spine, spine[1:]))
        hit = surf.closest(spine[len(spine) // 2])
        if L > 0.0 and hit is not None and abs(sum((spine[-1][i] - spine[0][i]) * hit[2][i]
                                                   for i in range(3))) > 0.2 * L:
            tilted += 1
    return {"high": high / float(max(1, pts)), "inside": inside, "through": through, "tilted": tilted, "n": n}


def settings(tb, pile, **kw):
    s = dict(tb["DEBRIS_DEFAULTS"], grass=3.0, leaves=0.0, piles=0.0, tufts=0.0, coverage=0.9, slope=45.0, seed=7)
    if pile is not None:
        s["grass_pile"] = pile
    s.update(kw)
    return s


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
    check("Pile height is a debris setting, off by default (old groups build as before)",
          tb["DEBRIS_DEFAULTS"].get("grass_pile") == 0.0, str(tb["DEBRIS_DEFAULTS"].get("grass_pile")))
    new = dict(tb["SC_TYPES"])["Grass"].get("new", {})
    check("a new Grass layer is a loose pile", new.get("grass_pile", 0.0) > 0.0, str(new))
    check("Pile height is a Grass layer key", "grass_pile" in dict(tb["SC_TYPES"])["Grass"]["keys"])

    if OLD:  # a toolbox from before piles (and before bunches inside a box were skipped)
        old = load_toolbox(OLD)
        for name, nodes in scenes.items():
            a = old["debris_build"](nodes, settings(old, None))["grass"]
            b = tb["debris_build"](nodes, settings(tb, 0.0))["grass"]
            if name == "ramp":
                same = len(a[0]) == len(b[0]) and list(a[2]) == list(b[2]) and max(
                    [max(abs(p[i] - q[i]) for i in range(3)) for p, q in zip(a[0], b[0])] or [0.0]) < 1e-7
                check("ramp: Pile height 0 builds what the old toolbox did", same,
                      "%d vs %d points" % (len(a[0]), len(b[0])))
            else:  # away from the wall, step, bricks and plank the same blades; next to them fewer, shorter
                key = lambda p: tuple(round(v, 5) for v in p)  # noqa: E731

                def clear(p):
                    return p[2] > -7.0 and not (3.0 < p[0] < 21.0 and 0.5 < p[2] < 11.5) and \
                        not (-16.0 < p[0] < 0.0 and 2.0 < p[2] < 10.0)

                olds = set(key(p) for p in a[0])
                news = set(key(p) for p in b[0])
                moved = sum(1 for p in b[0] if clear(p) and key(p) not in olds)
                lost = sum(1 for p in a[0] if clear(p) and key(p) not in news)
                check("%s: flat bunches as before away from things standing on the floor" % name,
                      0 < len(b[0]) < len(a[0]) and moved == 0 and lost == 0,
                      "%d -> %d points; away from them %d moved, %d gone" % (len(a[0]), len(b[0]), moved, lost))

    Rb = 0.5 * 0.3 / m  # the default bunch's radius
    for name, nodes in scenes.items():
        t0 = time.time()
        flat = tb["debris_build"](nodes, settings(tb, 0.0))
        t_flat = time.time() - t0
        t0 = time.time()
        got = tb["debris_build"](nodes, settings(tb, 0.7))
        t_pile = time.time() - t0
        f = measure(tb, nodes, flat["grass"], 0.7 * Rb)
        r = measure(tb, nodes, got["grass"], 0.7 * Rb)
        print("STATS %s flat %s %.2fs pile %s %.2fs bunches %d / %d" % (
            name, f, t_flat, r, t_pile, flat["bunches"], got["bunches"]))
        check("%s: piles grew" % name, got["bunches"] > 3 and r["n"] > f["n"],
              "%d piles, %d blades (flat %d)" % (got["bunches"], r["n"], f["n"]))
        check("%s: piles stand up (flat bunches are a mat)" % name,
              r["high"] > 0.25 and r["high"] > 3.0 * f["high"],
              "%.0f%% of blade points over a quarter of the pile's height off the surface (flat %.0f%%)" % (
                  100 * r["high"], 100 * f["high"]))
        check("%s: no blade point inside a surface" % name, r["inside"] <= r["n"] // 200,
              "%d points over 1 mm in, of %d blades" % (r["inside"], r["n"]))
        check("%s: flat bunches don't grow inside a box on the floor either" % name, f["inside"] <= f["n"] // 200,
              "%d points over 1 mm in, of %d blades" % (f["inside"], f["n"]))
        check("%s: no blade through a surface" % name, r["through"] <= max(1, r["n"] // 200),
              "%d of %d blades cross a surface" % (r["through"], r["n"]))
        check("%s: blades lie every which way, not pressed flat" % name,
              r["tilted"] > 2 * f["tilted"] + r["n"] // 20,
              "%d of %d tilted (flat %d of %d)" % (r["tilted"], r["n"], f["tilted"], f["n"]))
        check("%s: piles cost a few times a flat bunch, not more" % name, t_pile < max(2.0, 8.0 * t_flat),
              "%.2fs vs %.2fs" % (t_pile, t_flat))
    # a single-sided roof plane overhead (a porch): a ray up hits its back, yet the floor isn't inside it
    under = []
    for k, roofed in enumerate((False, True)):
        x = -100.0 - 40.0 * k
        g = cmds.group(empty=True, name="porch%d_GRP" % k)
        box("porchFloor%d" % k, (24, 1, 24), (x, -0.5, 0), g, div=4.0)
        if roofed:
            roof = cmds.polyPlane(name="porchRoof", w=16, h=16, sx=4, sy=4, constructionHistory=False)[0]
            cmds.move(x, 25, 0, roof)
            cmds.parent(roof, g)
        nodes = meshes([cmds.ls(g, long=True)[0]])
        row = []
        for pile in (0.0, 0.7):
            got = tb["debris_build"](nodes, settings(tb, pile))["grass"]
            row.append(sum(1 for p in got[0] if abs(p[0] - x) < 6.0 and abs(p[2]) < 6.0))
        under.append(row)
    check("grass still grows under a single-sided roof plane (flat, pile)",
          all(under[1][j] >= 0.9 * under[0][j] > 0 for j in range(2)),
          "open %s, roofed %s points under it" % (under[0], under[1]))

    s = settings(tb, 0.7, detail="Proxy")
    got = tb["debris_build"](scenes["yard"], s)
    check("Proxy piles build", got["bunches"] > 3 and len(got["grass"][0]) > 0, str(got["bunches"]))


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
