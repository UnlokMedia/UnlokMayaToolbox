"""Headless tests: clumping stray grass (mayapy).

    mayapy tests/test_grass_clump.py     (UNLOK_OLD_TOOLBOX=<older UnlokToolbox.py> also compares with it)

The user (2026-11-19): "piles of grass that have falloff, so a lot of stray
blades building up to a pile that a few bundles might be piled onto ... a
broad coverage of stray blades and then controlling how much they clump
together and attract to each other". Grass layer settings Clumping
(stray_clump), Clump size, Build-up and Heaps on clumps. Checked on a yard in
decimetres: off (Clumping 0) every stray and bunch is exactly as before
(and as the older toolbox), Clumping gathers the strays (fewer cells hold
half of them) with about as many blades, Build-up lifts them in the middles,
Heaps on clumps adds bundles only there, nothing goes into the surfaces, and
the cost.
"""

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OLD = os.environ.get("UNLOK_OLD_TOOLBOX")
NEW_KEYS = ("stray_clump", "stray_clump_size", "stray_buildup", "stray_heaps")

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


def box(name, size, at, parent, div=2.0):
    node = cmds.polyCube(w=size[0], h=size[1], d=size[2], sx=max(1, int(size[0] / div)), sy=max(1, int(size[1] / div)),
                         sz=max(1, int(size[2] / div)), name=name, constructionHistory=False)[0]
    cmds.move(at[0], at[1], at[2], node)
    return cmds.ls(cmds.parent(node, parent)[0], long=True)[0]


def settings(tb, **kw):
    s = dict(tb["DEBRIS_DEFAULTS"], grass=0.0, leaves=0.0, piles=0.0, tufts=0.0, coverage=0.9, slope=45.0, seed=7,
             grass_strays=120.0, patchiness=0.2)
    s.update(kw)
    return s


def same_mesh(a, b):
    return len(a[0]) == len(b[0]) and list(a[1]) == list(b[1]) and list(a[2]) == list(b[2]) and max(
        [max(abs(p[i] - q[i]) for i in range(3)) for p, q in zip(a[0], b[0])] or [0.0]) < 1e-7


def blades(mesh):
    """Each blade's centre line (ribbons: two points a row)."""
    pts, counts, conn = mesh[0], mesh[1], mesh[2]
    out, cur, k = [], None, 0
    for n in counts:
        a = conn[k]
        k += n
        if cur is None or a != cur[1]:
            cur = [a, a]
            out.append(cur)
        cur[1] = a + 2
    return [[tuple((pts[i][j] + pts[i + 1][j]) * 0.5 for j in range(3)) for i in range(a, b + 1, 2)] for a, b in out]


def main():
    tb = load_toolbox(TOOLBOX)
    cmds.file(new=True, force=True)
    m = tb["scene_m_per_unit"]()
    g = cmds.group(empty=True, name="yard_GRP")
    floor = box("floor", (40, 1, 40), (0, -0.5, 0), g, div=4.0)
    wall = box("wall", (40, 12, 1), (0, 6, -20.5), g, div=3.0)
    step = box("step", (10, 1.5, 6), (10, 0.75, 8), g, div=1.0)
    nodes = [floor, wall, step]
    D = tb["DEBRIS_DEFAULTS"]
    check("the clumping settings are Grass settings, off by default, with fields and a panel section",
          D.get("stray_clump") == 0.0 and D.get("stray_heaps") == 0.0 and
          all(k in tb["SC_TYPES"]["Grass"]["keys"] and k in tb["SC_FIELDS"] for k in NEW_KEYS) and
          any(sec[0] == "Clumping strays" and list(sec[2]) == list(NEW_KEYS) for sec in tb["SC_LAYOUT"]["Grass"]))

    # --- off: as before
    base = settings(tb, grass=1.5, grass_pile=0.6)
    if OLD:
        old = load_toolbox(OLD)
        a = old["debris_build"](nodes, settings(old, grass=1.5, grass_pile=0.6))
        b = tb["debris_build"](nodes, base)
        check("Clumping 0: strays and bunches exactly as the older toolbox built them",
              same_mesh(a["grass"], b["grass"]) and a["bunches"] == b["bunches"],
              "%d vs %d points" % (len(a["grass"][0]), len(b["grass"][0])))
    else:
        print("(UNLOK_OLD_TOOLBOX not set: old-toolbox comparison skipped)")
    bare = dict((k, v) for k, v in base.items() if k not in NEW_KEYS + ("pile_var",))
    ref = tb["debris_build"](nodes, base)
    others = tb["debris_build"](nodes, dict(base, stray_clump_size=3.0, stray_buildup=2.0, stray_heaps=1.0))
    check("... and without the keys, and with the other three set while Clumping is 0",
          same_mesh(tb["debris_build"](nodes, bare)["grass"], ref["grass"]) and same_mesh(others["grass"], ref["grass"]))

    # --- Clumping gathers the strays
    def strays(**kw):
        t0 = time.time()
        got = tb["debris_build"](nodes, settings(tb, **kw))
        return got, blades(got["grass"]), time.time() - t0

    def half_cells(bl):
        """How many 20 cm floor cells hold half the blades' middles."""
        cell = 0.2 / m
        cnt = {}
        for b in bl:
            p = b[len(b) // 2]
            if p[1] < 0.5:
                key = (int(p[0] // cell), int(p[2] // cell))
                cnt[key] = cnt.get(key, 0) + 1
        vals = sorted(cnt.values(), reverse=True)
        tot, k = 0, 0
        while vals and tot < 0.5 * sum(vals):
            tot += vals[k]
            k += 1
        return k

    e_got, e_bl, e_t = strays()
    c_got, c_bl, c_t = strays(stray_clump=1.0, stray_clump_size=1.5, stray_buildup=0.0)
    h0, h1 = half_cells(e_bl), half_cells(c_bl)
    check("Clumping 1 gathers the strays: far fewer floor cells hold half of them", h1 < 0.55 * h0,
          "%d cells vs %d even" % (h1, h0))
    check("... with about as many blades (drawn in, not removed)", len(c_bl) >= 0.85 * len(e_bl),
          "%d vs %d blades" % (len(c_bl), len(e_bl)))
    s_got, s_bl, _ = strays(stray_clump=0.3, stray_clump_size=1.5, stray_buildup=0.0)
    check("... Clumping 0.3 in between", h1 < half_cells(s_bl) < h0, "%d" % half_cells(s_bl))
    flat_top = max(p[1] for b in c_bl for p in b if p[1] < 0.5)
    u_got, u_bl, u_t = strays(stray_clump=1.0, stray_clump_size=1.5, stray_buildup=1.5)

    def high(bl):
        hs = sorted(p[1] for b in bl for p in b if p[1] < 0.6 / m)
        return hs[int(0.98 * (len(hs) - 1))] if hs else 0.0
    check("Build-up lifts the gathered blades into a mound (98th percentile height)",
          high(u_bl) > high(c_bl) + 0.01 / m, "%.3f vs %.3f dm (flat top %.3f)" % (high(u_bl), high(c_bl), flat_top))
    check("... the blades stay the same (only lifted)", len(u_bl) == len(c_bl), "%d vs %d" % (len(u_bl), len(c_bl)))

    # --- Heaps on clumps
    k_got, k_bl, k_t = strays(stray_clump=1.0, stray_clump_size=1.5, stray_buildup=1.0, stray_heaps=1.0)
    check("Heaps on clumps adds bundles (none without it)", k_got["bunches"] > 0 and c_got["bunches"] == 0,
          "%d bunches" % k_got["bunches"])
    surf = tb["_MiSurface"](nodes)
    mm = 0.001 / m
    under = 0
    pts = [p for b in k_bl for p in b[::2]]
    for p in pts:
        c = surf.closest(p)
        if c is not None and tb["_rl_dot"](tb["_rl_sub"](p, c[1]), c[2]) < -mm:
            under += 1
    check("nothing goes into the surfaces (blade points over 1 mm under the nearest face)",
          under <= max(2, len(pts) // 2000), "%d of %d" % (under, len(pts)))
    on_step = [b for b in u_bl if any(p[1] > 1.4 for p in b)]
    check("blades still grow on the step (it gets its own clumps)", on_step, "%d" % len(on_step))
    check("cost: clumping about as fast as even strays, heaps a few seconds",
          u_t < 2.0 * e_t + 0.5 and k_t < 3.0 * e_t + 3.0,
          "even %.2fs, clumped %.2fs, built up %.2fs, heaped %.2fs" % (e_t, c_t, u_t, k_t))

    # --- Height variation (pile_var; the user: "pile height variation")
    check("Height variation is a Grass setting, off by default, in Shape and scatter",
          D.get("pile_var") == 0.0 and "pile_var" in tb["SC_TYPES"]["Grass"]["keys"] and "pile_var" in tb["SC_FIELDS"]
          and any(sec[0] == "Shape and scatter" and "pile_var" in sec[2] for sec in tb["SC_LAYOUT"]["Grass"]))
    piles = dict(grass=1.2, grass_strays=0.0, grass_pile=0.8, bunch_var=0.0)
    p0 = tb["debris_build"](nodes, settings(tb, **piles))
    check("Height variation 0: piles exactly as without the key",
          same_mesh(p0["grass"], tb["debris_build"](nodes, dict(settings(tb, **piles), pile_var=0.0))["grass"]))
    p1 = tb["debris_build"](nodes, settings(tb, pile_var=1.0, **piles))

    def tops(bl):
        """Each pile's height: the highest blade root on the floor in 25 cm cells
        (roots sit on the pile's mound; tips mostly show blade length)."""
        cell = 0.25 / m
        top = {}
        for b in bl:
            if b[0][1] > 0.6 / m or abs(b[0][0]) > 18 or abs(b[0][2]) > 18 or (5 < b[0][0] < 15 and 5 < b[0][2] < 11):
                continue
            key = (int(b[0][0] // cell), int(b[0][2] // cell))
            top[key] = max(top.get(key, 0.0), b[0][1])
        hs = sorted(v for v in top.values() if v > 0.02 / m)
        return hs[int(0.1 * (len(hs) - 1))], hs[int(0.9 * (len(hs) - 1))]
    lo0, hi0 = tops(blades(p0["grass"]))
    lo1, hi1 = tops(blades(p1["grass"]))
    check("Height variation 1 spreads pile heights (10th-90th percentile tops further apart)",
          (hi1 - lo1) > 1.3 * (hi0 - lo0) and p1["bunches"] == p0["bunches"],
          "%.3f-%.3f vs %.3f-%.3f dm, %d vs %d bunches" % (lo1, hi1, lo0, hi0, p1["bunches"], p0["bunches"]))


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
