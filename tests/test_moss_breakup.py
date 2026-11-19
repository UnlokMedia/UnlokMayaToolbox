"""Headless tests for the moss Mat's Outline detail and Breakup (mayapy).

    mayapy tests/test_moss_breakup.py
    (UNLOK_OLD_TOOLBOX=<an older UnlokToolbox.py> also checks that with both
    at 0 the Mat grows exactly as that one did)

A flat roof against a wall, moss gathering along the wall's foot (Where it
gathers: Walls) and falling off across the roof. Outline detail makes the
outline longer for its area (jagged, not rounded); Breakup turns the falloff
into many separate cushions, smaller further from the wall; both at 0 (any
other Breakup values) build the mat exactly as before; the mat stays all
quads, manifold, its open edges tucked under the roof.
"""

import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def load_toolbox(path=TOOLBOX):
    ns = {"__name__": "unlok_test", "__file__": path}
    with open(path) as f:
        exec(compile(f.read(), path, "exec"), ns)
    return ns


def roof():
    """A 5 x 3.5 m flat roof (decimetres) and the wall along its back edge."""
    r = cmds.polyPlane(w=50, h=35, sx=10, sy=7, ch=False, name="roofFelt_C_test0001_GEP")[0]
    w = cmds.polyCube(w=54, h=20, d=3, ch=False, name="wallBrick_C_test0001_GEP")[0]
    cmds.move(0, 10, -19, w)
    cmds.makeIdentity(w, apply=True)
    return [cmds.ls(x, long=True)[0] for x in (r, w)]


def edges(mesh):
    seen, k = {}, 0
    for n in mesh[1]:
        ids = mesh[2][k:k + n]
        k += n
        for a in range(n):
            e = (min(ids[a], ids[(a + 1) % n]), max(ids[a], ids[(a + 1) % n]))
            seen[e] = seen.get(e, 0) + 1
    return seen


def shells(mesh):
    """Connected pieces: [(face count, centre)]."""
    lab = list(range(len(mesh[0])))

    def find(i):
        while lab[i] != i:
            lab[i] = lab[lab[i]]
            i = lab[i]
        return i

    k = 0
    for n in mesh[1]:
        ids = mesh[2][k:k + n]
        k += n
        for a in ids[1:]:
            x, y = find(ids[0]), find(a)
            if x != y:
                lab[x] = y
    acc = {}
    k = 0
    P = mesh[0]
    for n in mesh[1]:
        ids = mesh[2][k:k + n]
        k += n
        r = find(ids[0])
        a = acc.setdefault(r, [0, 0.0, 0.0, 0.0])
        a[0] += 1
        for i in ids:
            a[1] += P[i][0] / n
            a[2] += P[i][1] / n
            a[3] += P[i][2] / n
    return [(a[0], (a[1] / a[0], a[2] / a[0], a[3] / a[0])) for a in acc.values()]


def outline_ratio(mesh):
    """Open-edge length over the square root of the top's area (a circle ~3.5; jagged: more)."""
    P = mesh[0]
    ln = 0.0
    for (a, b), c in edges(mesh).items():
        if c == 1:
            ln += math.sqrt(sum((P[a][j] - P[b][j]) ** 2 for j in range(3)))
    area = 0.0
    k = 0
    for n in mesh[1]:
        ids = mesh[2][k:k + n]
        k += n
        a, b, c, d = (P[i] for i in ids[:4])
        u = [c[j] - a[j] for j in range(3)]
        v = [d[j] - b[j] for j in range(3)]
        cr = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        area += 0.5 * math.sqrt(sum(x * x for x in cr))
    return ln / math.sqrt(max(area, 1e-9))


def main():
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    nodes = roof()
    md = tb["mi_settings_only"]("Moss", {})
    base = dict(md, style="Mat", coverage=0.6, render_as="GED", lumps=0.5, detail="Normal", strands=0.0,
                capsules=0.0, seed=3, to_walls=0.8, to_walls_reach=1.6)
    for k in ("edge_detail", "breakup", "breakup_width", "breakup_size", "breakup_var", "breakup_scale", "breakup_mult", "breakup_height"):
        check("setting %s is a moss default" % k, k in tb["MOSS_DEFAULTS"] and k in tb["SC_FIELDS"])
    check("Outline detail and Breakup start at 0 (old layers grow as before)",
          tb["MOSS_DEFAULTS"]["edge_detail"] == 0.0 and tb["MOSS_DEFAULTS"]["breakup"] == 0.0)
    check("the panel has an Outline and breakup section",
          any(t == "Outline and breakup" for t, _, _ in tb["SC_LAYOUT"]["Moss"]))

    def build(**kw):
        t0 = time.time()
        s = dict(base, **kw)
        got = tb["moss_build"](nodes, s, paint=tb["_ScGather"](None, s, nodes))["moss"]  # (as Scatter builds it)
        return got, time.time() - t0

    plain, t_plain = build()
    other, _ = build(breakup_width=0.9, breakup_size=0.12, breakup_var=0.1, breakup_scale=1.3)
    check("Breakup 0: its other settings change nothing", plain[0] == other[0] and plain[2] == other[2],
          "%d / %d pts" % (len(plain[0]), len(other[0])))
    fine, t_fine = build(edge_detail=1.0, ragged=0.9)
    brk, t_brk = build(edge_detail=0.6, ragged=0.8, breakup=0.85, breakup_width=0.6, breakup_size=0.08,
                       breakup_var=0.7, breakup_scale=0.5)
    print("faces: plain %d, outline detail %d, breakup %d; cold build %.2f s (first), %.2f s, %.2f s"
          % (len(plain[1]), len(fine[1]), len(brk[1]), t_plain, t_fine, t_brk))

    for label, mesh in (("plain", plain), ("outline detail", fine), ("breakup", brk)):
        es = edges(mesh)
        check("%s: all quads, manifold" % label, all(n == 4 for n in mesh[1]) and max(es.values()) <= 2,
              "%d faces" % len(mesh[1]))
        P = mesh[0]
        low = max([max(P[a][1], P[b][1]) for (a, b), c in es.items() if c == 1 and P[a][1] < 10.0] or [0.0])
        # (the roof's; the wall's top, 2 m up, has its own)
        check("%s: open edges tucked under the roof" % label, low < 0.0, "highest %.4f dm" % low)

    r0, r1 = outline_ratio(plain), outline_ratio(fine)
    check("Outline detail: a longer, jagged outline for its area", r1 > 1.12 * r0, "%.2f -> %.2f" % (r0, r1))
    check("Outline detail costs at most ~4x the faces", len(fine[1]) < 4.0 * len(plain[1]),
          "%d -> %d" % (len(plain[1]), len(fine[1])))

    sp, sb = shells(plain), shells(brk)
    check("Breakup: the falloff breaks into many cushions", len(sb) >= 3 * max(4, len(sp)),
          "%d -> %d pieces" % (len(sp), len(sb)))
    def cover(mesh, z0, z1):  # the roof's moss (top faces) between two distances from the wall
        P, k, area = mesh[0], 0, 0.0
        for n in mesh[1]:
            ids = mesh[2][k:k + n]
            k += n
            cz = sum(P[i][2] for i in ids) / n
            if z0 <= cz < z1 and sum(P[i][1] for i in ids) / n < 10.0:
                a, b, c, d = (P[i] for i in ids[:4])
                area += 0.5 * abs((c[0] - a[0]) * (d[2] - b[2]) - (c[2] - a[2]) * (d[0] - b[0]))
        return area

    zs = sorted(s[1][2] for s in sb if s[1][1] < 10.0 and s[0] < 0.2 * max(x[0] for x in sb))
    z0, z1 = zs[0], zs[-1]
    mid = 0.5 * (z0 + z1)
    cn, cf = cover(brk, z0, mid), cover(brk, mid, z1 + 1e-6)
    check("Breakup: sparser further from the wall", cf < cn, "moss over the band: nearer half %.1f dm2, "
          "further half %.1f dm2" % (cn, cf))
    tall, _ = build(edge_detail=0.6, ragged=0.8, breakup=0.85, breakup_width=0.6, breakup_size=0.08,
                    breakup_var=0.7, breakup_scale=0.5, breakup_height=2.0)
    hb = max(p[1] for p in brk[0] if p[2] > mid and p[1] < 10.0)  # (the outer half: cushions, not the carpet)
    ht = max(p[1] for p in tall[0] if p[2] > mid and p[1] < 10.0)
    check("Cushion height 2: taller cushions, same layout", ht > 1.2 * hb and len(tall[1]) == len(brk[1]),
          "tallest in the outer band %.3f -> %.3f dm" % (hb, ht))

    big, _ = build(edge_detail=0.6, ragged=0.8, breakup=0.85, breakup_width=0.6, breakup_size=0.08,
                   breakup_var=0.7, breakup_scale=0.5, breakup_mult=2.0)
    big2, _ = build(edge_detail=0.6, ragged=0.8, breakup=0.85, breakup_width=1.2, breakup_size=0.16,
                    breakup_var=0.7, breakup_scale=1.0)
    check("Breakup scale 2 = width, cushion size and noise all doubled", big[0] == big2[0] and big[2] == big2[2]
          and big[0] != brk[0], "%d / %d pts" % (len(big[0]), len(big2[0])))
    sg = shells(big)
    m1 = sorted(x[0] for x in sb)[len(sb) // 2]
    m2 = sorted(x[0] for x in sg)[len(sg) // 2]
    check("Breakup scale 2: bigger cushions", m2 > m1, "median piece %d -> %d faces (%d -> %d pieces)"
          % (m1, m2, len(sb), len(sg)))

    old_path = os.environ.get("UNLOK_OLD_TOOLBOX")
    if old_path and os.path.isfile(old_path):
        tbo = load_toolbox(old_path)
        for seed in (3, 5):
            s2 = dict(base, seed=seed)
            so = {k: v for k, v in s2.items() if k in tbo["MOSS_DEFAULTS"] or k.startswith("to_")}
            a = tb["moss_build"](nodes, s2, paint=tb["_ScGather"](None, s2, nodes))["moss"]
            b = tbo["moss_build"](nodes, so, paint=tbo["_ScGather"](None, so, nodes))["moss"]
            same = a[2] == b[2] and len(a[0]) == len(b[0]) and \
                all(p == q for p, q in zip(a[0], b[0])) and list(a[0].col) == list(b[0].col) and \
                list(a[3]) == list(b[3])
            check("both 0: the Mat is the earlier one exactly (seed %d)" % seed, same,
                  "%d / %d pts" % (len(a[0]), len(b[0])))
    else:
        print("SKIP  older toolbox comparison (set UNLOK_OLD_TOOLBOX)")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        check("ran without an error", False)
    failed = [r for r in RESULTS if not r[1]]
    print("\n%d checks, %d failed" % (len(RESULTS), len(failed)))
    for r in failed:
        print("FAILED: %s %s" % (r[0], r[2]))
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(1 if failed else 0)
