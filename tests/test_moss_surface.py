"""Headless tests for the moss rest surface (mayapy).

    mayapy tests/test_moss_surface.py

What moss grows on (`_mi_rest`): a mesh subdivided at render time (_GES /
_GED / _GEV, or Surface Smooth) is read as its Catmull-Clark limit surface
without polySmooth, so a low-poly cage's moss sits on the smooth surface the
render shows; _GEP (or Surface Faceted) stays as modelled. Relief finer than
the moss (corrugated metal) is bridged by a rest envelope tied to Clump size
and Surface detail, so a corrugated roof is covered with no gaps or cracks,
over the side laps too.
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
import maya.api.OpenMaya as om  # noqa: E402

RESULTS = []
FULL = {"coverage": 1.0, "patchiness": 0.0, "edges": 0.0, "crevices": 0.0, "mess": 0.0, "detail": "Normal"}


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def load_toolbox():
    ns = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    return ns


def fn_of(tb, node):
    return om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))


def moss_fn(points, counts, conn):
    data = om.MFnMeshData().create()
    fn = om.MFnMesh()
    fn.create([om.MPoint(*p) for p in points], counts, conn, parent=data)
    return om.MFnMesh(data), data


def signed(q, p):
    c = q.closest(p)
    return (p[0] - c[1][0]) * c[2][0] + (p[1] - c[1][1]) * c[2][1] + (p[2] - c[1][2]) * c[2][2]


def cages(suffix):
    """A 1 m box and an 8-sided post (decimetres), one face per side, plus
    hidden polySmooth copies: the render's surface."""
    cmds.file(new=True, force=True)
    c = cmds.polyCube(w=10, h=10, d=10, name="rockStone_C_rock0001" + suffix, constructionHistory=False)[0]
    cmds.move(0, 5, 0, c)
    cy = cmds.polyCylinder(r=4, h=8, sx=8, sy=1, sz=1, name="woodPost_C_post0001" + suffix,
                           constructionHistory=False)[0]
    cmds.move(15, 4, 0, cy)
    nodes = [cmds.ls(c, long=True)[0], cmds.ls(cy, long=True)[0]]
    ref = []
    for n in nodes:
        d = cmds.duplicate(n, name="smoothRef#")[0]
        cmds.polySmooth(d, divisions=3, constructionHistory=False)
        cmds.setAttr(d + ".visibility", 0)
        ref.append(cmds.ls(d, long=True)[0])
    return nodes, ref


def roof(tb, mode):
    cmds.file(new=True, force=True)
    b = cmds.ls(cmds.polyCube(w=1, h=1, d=1, name="house", constructionHistory=False)[0], long=True)[0]
    cmds.xform(b, scale=(30.0, 12.0, 20.0), translation=(0.0, 15.0, 0.0))
    rep = tb["make_thatch_roof"](b, {"covering": "Corrugated", "m_mode": mode, "end_a": "Gable", "end_b": "Gable",
                                     "overhang": 0.03})
    return tb["thatch_parts"](rep["root"])["sheets"]


def roof_gaps(tb, sheets, out, lines=()):
    """Rays down over the roof's middle: the share that hit a sheet before
    moss (a gap), and on fine lines across the corrugations (cracks)."""
    mfn, keep = moss_fn(*out["moss"][:3])
    sfn = fn_of(tb, sheets)
    macc, sacc = mfn.autoUniformGridParams(), sfn.autoUniformGridParams()
    d = om.MFloatVector(0, -1, 0)

    def gap(x, z):
        p = om.MFloatPoint(x, 100.0, z)
        hs = sfn.closestIntersection(p, d, om.MSpace.kWorld, 1e4, False, accelParams=sacc)
        if not hs:
            return None
        hm = mfn.closestIntersection(p, d, om.MSpace.kWorld, 1e4, False, accelParams=macc)
        return not hm or hm[1] > hs[1] - 1e-5

    res = [gap(-12.0 + 24.0 * i / 60, -8.0 + 16.0 * j / 60) for i in range(61) for j in range(61)]
    res = [r for r in res if r is not None]
    fine = []
    for z in lines:
        fine.extend(r for r in (gap(-3.0 + 6.0 * i / 599, z) for i in range(600)) if r is not None)
    return (sum(res) / float(max(1, len(res))), len(res),
            sum(fine) / float(max(1, len(fine))) if fine else 0.0, len(fine))


def run():
    tb = load_toolbox()
    S = dict(tb["MOSS_DEFAULTS"])
    check("Surface settings in the moss defaults",
          S.get("surface") == "Auto" and S.get("surface_detail") == 0.5 and "surface" in tb["SC_FIELDS"])

    # ---- the suffix (UnlokRenamer's) decides, Surface overrides it
    cmds.file(new=True, force=True)
    names = {}
    for sfx in ("_GEP", "_GES", "_GED", "_GEV", ""):
        n = cmds.polyCube(name="rockStone_C_suffix0001" + sfx, constructionHistory=False)[0]
        names[sfx] = cmds.ls(n, long=True)[0]
    sub = dict((k, tb["_mi_subdivided"](v)) for k, v in names.items())
    check("_GES / _GED / _GEV are subdivided, _GEP and no suffix are not",
          sub["_GES"] and sub["_GED"] and sub["_GEV"] and not sub["_GEP"] and not sub[""], str(sub))
    check("Surface Smooth / Faceted override the suffix",
          tb["_mi_rest_smooth"](names["_GEP"], {"surface": "Smooth"}) and
          not tb["_mi_rest_smooth"](names["_GES"], {"surface": "Faceted"}) and
          tb["_mi_rest_smooth"](names["_GES"], {"surface": "Auto"}))

    # ---- a low-poly _GES cage: moss on the smooth surface, not the cage
    s = dict(FULL, slope=90.0, lumps=0.0, size_var=0.0)
    stats = {}
    for sfx in ("_GEP", "_GES"):
        nodes, ref = cages(sfx)
        q = tb["_MiSurface"](ref)
        t0 = time.time()
        out = tb["moss_build"](nodes, s)
        dt = time.time() - t0
        pts = out["moss"][0]
        ds = sorted(signed(q, p) for p in pts[::2])
        n = len(ds)
        rests = []
        for node, r3 in zip(nodes, ref):
            ss = tb["mi_settings_only"]("Moss", s)
            rest = tb["_mi_rest"](node, tb["_mi_rest_smooth"](node, ss), *tb["_mi_rest_scale"](ss))
            if rest is None:
                rests.append(None)
                continue
            fq = rest.item[1]
            rp = [(p.x, p.y, p.z) for p in fq.getPoints()]
            for f in range(fq.numPolygons):  # the query mesh's face middles too
                vs = fq.getPolygonVertices(f)
                rp.append(tuple(sum(rp[v][k] for v in vs) / len(vs) for k in range(3)))
            d2 = cmds.duplicate(node, name="smoothRefTwo#")[0]  # the twice subdivided mesh (Maya's default level)
            cmds.polySmooth(d2, divisions=2, constructionHistory=False)
            q2 = tb["_MiSurface"]([cmds.ls(d2, long=True)[0]])
            dr = sorted(signed(tb["_MiSurface"]([r3]), p) for p in rp)
            dr2 = sorted(abs(signed(q2, p)) for p in rp)
            cmds.delete(d2)
            rests.append((round(dr[0], 4), round(dr[len(dr) // 2], 4), round(dr[-1], 4), round(dr2[len(dr2) // 2], 4)))
        stats[sfx] = (dt, n, ds[n // 2], sum(1 for d in ds if d < -0.02) / float(n), rests)
        print("   %s: %.2fs, %d moss points, median %.3f over the smooth surface, %.1f%% under it, rests %s" % (
            sfx, dt, n, ds[n // 2], 100.0 * stats[sfx][3], rests))
        if sfx == "_GES":
            # picked faces still work on a subdivided cage (its quads keep the mesh's face ids)
            fn = fn_of(tb, nodes[0])
            top = max(range(fn.numPolygons), key=lambda f: fn.getPolygonNormal(f, om.MSpace.kWorld).y)
            o2 = tb["moss_build"](nodes, s, faces={nodes[0]: [top]})
            ys = [p[1] for p in o2["moss"][0]]
            check("picked faces on a _GES cage: moss only on the picked face's part of the smooth surface",
                  ys and min(ys) > 5.0, "lowest moss y %.2f (box 0..10)" % (min(ys) if ys else -1))
    pep, pes = stats["_GEP"], stats["_GES"]
    check("_GEP: moss follows the cage as modelled (no rest surface; far off the smooth one)",
          pep[4] == [None, None] and pep[2] > 1.0, "median %.2f units off" % pep[2])
    check("_GES: the rest surface is the twice subdivided one (median under 1 cm off polySmooth 2; "
          "never under polySmooth 3, at most 2.5 cm over it)",
          all(r and r[3] < 0.1 and r[0] > -0.02 and r[2] < 0.25 for r in pes[4]),
          "(min, median, max over div 3; median off div 2) %s" % str(pes[4]))
    check("_GES: the moss sits on the smooth surface (median within the bed's thickness, under 6% below it)",
          0.0 < pes[2] < 0.3 and pes[3] < 0.06, "median %.3f, %.1f%% under" % (pes[2], 100.0 * pes[3]))
    check("_GES costs no more than _GEP (no polySmooth)", pes[0] < max(2.0 * pep[0], 3.0),
          "%.2fs vs %.2fs" % (pes[0], pep[0]))
    nodes, ref = cages("_GES")
    a = tb["moss_build"](nodes, dict(s, surface="Faceted"))
    nodes2, _ = cages("_GEP")
    b = tb["moss_build"](nodes2, s)
    check("Surface Faceted on a _GES cage = the _GEP build",
          len(a["moss"][0]) == len(b["moss"][0]), "%d vs %d points" % (len(a["moss"][0]), len(b["moss"][0])))

    # ---- Clumps over a beam's edge (the user, 2026-11-05: spots "able to grow around corners ... instead of
    # them just ending harshly at corners"): cushions on the top drape down the sides, never into the beam
    cmds.file(new=True, force=True)
    bm = cmds.ls(cmds.polyCube(w=40, h=4, d=1.2, name="beamWood_C_beam0001", constructionHistory=False)[0],
                 long=True)[0]
    cmds.move(0, 2, 0, bm)
    fn = fn_of(tb, bm)
    top = max(range(fn.numPolygons), key=lambda f: fn.getPolygonNormal(f, om.MSpace.kWorld).y)
    sclump = dict(FULL, style="Clumps", strands=0.0, capsules=0.0)
    pts = tb["moss_build"]([bm], sclump, faces={bm: [top]})["moss"][0]
    R = 0.06 / tb["scene_m_per_unit"]()
    draped = [p for p in pts if abs(p[2]) > 0.6 - 1e-3 and abs(p[0]) < 20.0 and p[1] < 4.0 - 0.2 * R]
    inside = [p for p in pts if abs(p[2]) < 0.58 and abs(p[0]) < 19.98 and p[1] < 3.98]
    check("Clumps drape over a beam's edge instead of stopping flat at it", len(draped) >= 10 and not inside,
          "%d points down the sides (lowest y %.2f, top 4), %d inside" % (
              len(draped), min([p[1] for p in draped] or [4.0]), len(inside)))

    # ---- corrugated metal: the rest envelope bridges the grooves, no gaps or cracks
    sheets = roof(tb, "Clean")
    sc = dict(FULL, slope=80.0)
    ss = tb["mi_settings_only"]("Moss", sc)
    lifts = []
    for det in (0.0, 0.5, 1.0):
        rest = tb["_mi_rest"](sheets, False, *tb["_mi_rest_scale"](dict(ss, surface_detail=det)))
        if rest is None:
            lifts.append(0.0)
            continue
        raw = [(p.x, p.y, p.z) for p in fn_of(tb, sheets).getPoints(om.MSpace.kWorld)]
        lifts.append(max(tb["_rl_len"](tb["_rl_sub"](a_, b_)) for a_, b_ in zip(rest.P, raw)))
    check("Surface detail: 0 fills the grooves most, 1 leaves the sheet as modelled",
          lifts[0] > lifts[1] > 0.0 and lifts[2] == 0.0, str([round(x, 3) for x in lifts]))
    t0 = time.time()
    out = tb["moss_build"]([sheets], sc)
    dt = time.time() - t0
    g, n, fine, nf = roof_gaps(tb, sheets, out, lines=(2.0, 4.5, -2.5, -5.0))
    check("corrugated Clean: moss over the sheets everywhere (under 4% gaps; 15.7% before)", g < 0.04,
          "%.1f%% of %d rays, %.1fs" % (100.0 * g, n, dt))
    check("corrugated Clean: no cracks across the corrugations or the side laps (fine lines)", fine < 0.03,
          "%.1f%% of %d rays" % (100.0 * fine, nf))
    t0 = time.time()
    tb["moss_build"]([sheets], dict(sc, coverage=0.9))
    dt2 = time.time() - t0
    check("a Coverage edit reuses the rest surface and the bed layout", dt2 < 0.6 * dt, "%.1fs vs %.1fs" % (dt2, dt))
    sheets = roof(tb, "Makeshift")
    t0 = time.time()
    out = tb["moss_build"]([sheets], sc)
    dt = time.time() - t0
    g, n, fine, nf = roof_gaps(tb, sheets, out)
    check("corrugated Makeshift: moss over the stacked panels (under 4% gaps; 27.8% before)", g < 0.04,
          "%.1f%% of %d rays, %.1fs" % (100.0 * g, n, dt))


try:
    run()
except Exception:
    traceback.print_exc()
    RESULTS.append(("crashed", False, ""))
failed = [r for r in RESULTS if not r[1]]
print("\n%d checks, %d failed" % (len(RESULTS), len(failed)))
for name, _, detail in failed:
    print("FAILED: %s  %s" % (name, detail))
sys.stdout.flush()
cmds.file(new=True, force=True)
maya.standalone.uninitialize()
os._exit(1 if failed else 0)
