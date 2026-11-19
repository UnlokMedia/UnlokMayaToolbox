"""Headless tests: grass and roof straw as curves (mayapy).

    mayapy tests/test_strand_curves.py

The user (2026-11-19): "update the grass and roof scripts so they have an
option to be curves instead, don't change anything else and make it a super
fast conversion if possible, e.g. not a conversion, more just a straight swap
to curves ... so they can be used in a sim setup or something in houdini or
rendered differently there".

Curves (Grass layers: `curves`; roofs: `curves`, off by default) writes each
blade / straw piece / leaflet as one linear curve through the middle of its
rows (strand_spines reads the built strips), with a per-point width, in a
group of its own; the mesh goes (a roof keeps its usual hidden placeholder).
Checked on a floor and roof boxes in decimetres: off changes nothing, the
curves match the blades exactly, switching a Grass layer is quick (no
regrow) and back gives the same mesh, roofs of each strip style give a
curve per piece, Surface stays a mesh, presets keep the switch.
"""

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


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def load_toolbox(path):
    ns = {"__name__": "unlok_test", "__file__": path}
    with open(path) as f:
        exec(compile(f.read(), path, "exec"), ns)
    return ns


def curve_shapes(group):
    return cmds.listRelatives(group, shapes=True, fullPath=True, type="nurbsCurve") or []


def mesh_pts(node):
    shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
    return [(p.x, p.y, p.z) for p in om.MFnMesh(om.MSelectionList().add(shape).getDagPath(0)).getPoints(
        om.MSpace.kWorld)]


def main():
    tb = load_toolbox(TOOLBOX)
    cmds.file(new=True, force=True)
    floor = cmds.polyCube(w=30, h=1, d=30, sx=8, sy=1, sz=8, name="floor", constructionHistory=False)[0]
    cmds.move(0, -0.5, 0, floor)
    floor = cmds.ls(floor, long=True)[0]

    # ---------------------------------------------------------------- settings
    check("Curves is off by default for grass and roofs, with a field and a place in the Grass panel",
          tb["DEBRIS_DEFAULTS"]["curves"] is False and tb["THATCH_DEFAULTS"]["curves"] is False and
          "curves" in tb["SC_TYPES"]["Grass"]["keys"] and "curves" in tb["SC_FIELDS"] and
          any("curves" in sec[2] for sec in tb["SC_LAYOUT"]["Grass"]))
    check("... roof presets leave it alone (each roof's own)",
          "curves" in tb["THATCH_PRESET_SKIP"] and
          all("curves" not in (tb["thatch_preset"](n) or {}) for n in tb["THATCH_PRESETS"]))

    # ---------------------------------------------------------------- strands
    s = dict(tb["sc_start_settings"]("Grass"), coverage=0.9, seed=3)
    s.update(tb["SC_PRESETS"]["Grass"]["Strewn hay"])
    g = tb["debris_build"]([floor], s)["grass"]
    t = time.time()
    st = tb["strand_spines"](g)
    dt = time.time() - t
    rows = sum(len(x[0]) for x in st)
    # each blade's rows: its two ribbon points, in order: the strand point is their middle
    a = 0
    worst = 0.0
    for line, wide, _ in st:
        for k, p in enumerate(line):
            l_, r_ = g[0][a + 2 * k], g[0][a + 2 * k + 1]
            worst = max(worst, max(abs(p[j] - 0.5 * (l_[j] + r_[j])) for j in range(3)),
                        abs(wide[k] - sum((l_[j] - r_[j]) ** 2 for j in range(3)) ** 0.5))
        a += 2 * len(line)
    check("Grass: every blade a strand, each point the middle of its row, the blade's width there",
          rows * 2 == len(g[0]) and worst < 1e-9 and len(st) > 1000,
          "%d blades, %d points (%d mesh points), worst %.1e, %.3f s" % (len(st), rows, len(g[0]), worst, dt))

    # ---------------------------------------------------------------- a Grass layer
    rep = tb["create_scatter_group"]([floor], "Grass", dict(s), select=False)
    root = rep["root"]
    lid = tb["sc_data"](root)["layers"][0]["id"]
    part = list(tb["sc_parts"](root).values())[0]
    before = mesh_pts(part)
    check("Curves off: a grass mesh, no curves group",
          not tb["strand_groups"](root) and len(before) > 1000, "%d points" % len(before))
    grows = []
    real = tb["debris_build"]
    tb["debris_build"] = lambda *a, **k: grows.append(1) or real(*a, **k)
    t = time.time()
    tb["sc_update"](root, lid, {"curves": True})
    dt_on = time.time() - t
    tb["debris_build"] = real
    groups = tb["strand_groups"](root)
    grp = groups.get(lid + "/grass")
    shapes = curve_shapes(grp) if grp else []
    check("Curves on: a curves group (..._CRV) instead of the mesh, a curve per blade",
          grp and cmds.ls(grp)[0].endswith("_CRV") and not tb["sc_parts"](root) and len(shapes) == len(st),
          "%s: %d curves for %d blades" % (grp and cmds.ls(grp)[0], len(shapes), len(st)))
    check("... switched without growing the grass again", not grows,
          "%.2f s for %d curves (%d grass builds)" % (dt_on, len(shapes), len(grows)))
    shapes = curve_shapes(tb["strand_groups"](root)[lid + "/grass"])
    fn = om.MFnNurbsCurve(om.MSelectionList().add(shapes[0]).getDagPath(0))
    cvs = fn.cvPositions(om.MSpace.kWorld)
    width = cmds.getAttr(shapes[0] + ".width")
    check("... linear curves on the blades' middles, a width per point",
          fn.degree == 1 and len(cvs) == len(st[0][0]) and
          max(abs(cvs[k][j] - st[0][0][k][j]) for k in range(len(cvs)) for j in range(3)) < 1e-6 and
          len(width) == len(cvs) and abs(width[0] - st[0][1][0]) < 1e-9,
          "%d CVs, width %.4f" % (len(cvs), width[0]))
    # N across the strip: unit, square to the curve (central difference, as it's worked out)
    worst = 0.0
    for line, wide, nrm in st:
        last = len(line) - 1
        for k in range(last + 1):
            t = [line[min(last, k + 1)][j] - line[max(0, k - 1)][j] for j in range(3)]
            lt = sum(x * x for x in t) ** 0.5
            ln = sum(x * x for x in nrm[k]) ** 0.5
            if lt > 1e-9:
                worst = max(worst, abs(sum(a * b for a, b in zip(t, nrm[k]))) / lt, abs(ln - 1.0))
    up = sum(1 for _, _, nrm in st if abs(nrm[0][1]) > 0.5) / float(len(st))
    check("... a normal per point: unit, square to the blade, facing up / down on most (blades lie flat-ish)",
          worst < 1e-6 and up > 0.5, "worst %.1e, %.0f%% face up or down at the root" % (worst, 100 * up))
    grp = tb["strand_groups"](root)[lid + "/grass"]
    s0 = shapes[0]
    n0 = cmds.getAttr(s0 + ".N")
    check("... on each curve shape: N per CV", len(n0) == len(cvs))
    import tempfile
    abc = os.path.join(tempfile.gettempdir(), "unlok_grass_curves.abc").replace("\\", "/")  # (no spaces)
    try:
        cmds.loadPlugin("AbcExport", quiet=True)
        cmds.loadPlugin("AbcImport", quiet=True)
        t = time.time()
        cmds.AbcExport(j="-frameRange 1 1 -attr N -root %s -file %s" % (grp, abc))
        dt_abc = time.time() - t
        had = set(cmds.ls(type="nurbsCurve", long=True) or [])
        tops = set(cmds.ls(assemblies=True))
        cmds.AbcImport(abc, mode="import")
        back = [c for c in cmds.ls(type="nurbsCurve", long=True) or [] if c not in had]
        b0 = back[0] if back else ""
        attrs = cmds.listAttr(b0, userDefined=True) or [] if b0 else []
        wb = cmds.getAttr(b0 + ".width") if cmds.attributeQuery("width", node=b0, exists=True) else None
        nb = cmds.getAttr(b0 + ".N") if cmds.attributeQuery("N", node=b0, exists=True) else None
        check("Alembic: AbcExport -attr N writes every curve with its width and N",
              len(back) == len(shapes) and wb is not None and nb is not None,
              "%d curves back, attrs on one: %s, export %.2f s" % (len(back), attrs, dt_abc))
        cmds.delete([n for n in cmds.ls(assemblies=True) if n not in tops])
    except Exception as exc:
        check("Alembic round trip", False, str(exc))
    tb["sc_update"](root, lid, {"curves": False})
    parts = tb["sc_parts"](root)
    after = mesh_pts(list(parts.values())[0]) if parts else []
    check("Curves off again: the curves go, the same grass mesh is back",
          not tb["strand_groups"](root) and after == before, "%d points" % len(after))

    # ---------------------------------------------------------------- roofs
    def roof(preset, **over):
        box = cmds.polyCube(w=40, h=12, d=30, name="roofBox", constructionHistory=False)[0]
        cmds.move(0, 30, 0, box)
        settings = dict(tb["thatch_preset"](preset), **over)
        t0 = time.time()
        r = tb["make_thatch_roof"](box, settings)
        return r, time.time() - t0

    for preset, style in (("Cottage (hipped)", "Planes"), ("Cottage (hipped)", "3D Pieces"),
                          ("Cambodian shack (leaf panels)", None), ("Palm: palapa (hipped, messy top)", None)):
        over = {"style": style} if style else {}
        plain, t_plain = roof(preset, **over)
        r, t_crv = roof(preset, curves=True, **over)
        root = r["root"]
        grp = tb["strand_groups"](root).get("straw")
        n = len(curve_shapes(grp)) if grp else 0
        straw = tb["thatch_parts"](root)["straw"]
        name = preset + (" / " + style if style else "")
        check("Roof %s: a curve per piece / leaflet, the straw mesh empty and hidden" % name,
              n > 0 and (style is None or n == plain["pieces"]) and not cmds.getAttr(straw + ".visibility") and
              cmds.ls(grp)[0].endswith("_CRV"),
              "%d curves (%d pieces), %s; build %.2f s, with curves %.2f s" % (
                  n, plain["pieces"], cmds.ls(grp)[0] if grp else "-", t_plain, t_crv))
        if style == "Planes":
            other = tb["thatch_parts"](plain["root"])
            same = all(mesh_pts(other[p]) == mesh_pts(tb["thatch_parts"](root)[p]) for p in ("underlay", "frame")
                       if p in other and cmds.getAttr(other[p] + ".visibility"))
            check("... the other parts as they were", same)
            tb["update_thatch_roofs"]({root: {"curves": False}})
            check("... Curves off: the group goes, the straw mesh is back",
                  not tb["strand_groups"](root) and cmds.getAttr(straw + ".visibility") and
                  mesh_pts(straw) == mesh_pts(tb["thatch_parts"](plain["root"])["straw"]))
    r, _ = roof("Cottage (hipped)", style="Surface", curves=True)
    check("Roof Surface style: no strands, stays a mesh",
          not tb["strand_groups"](r["root"]) and cmds.getAttr(tb["thatch_parts"](r["root"])["straw"] + ".visibility"))


try:
    main()
except Exception:
    traceback.print_exc()
    RESULTS.append(("crashed", False, ""))
failed = [r for r in RESULTS if not r[1]]
print("%d checks, %d failed" % (len(RESULTS), len(failed)))
for name, _, detail in failed:
    print("FAILED: %s  %s" % (name, detail))
maya.standalone.uninitialize()
os._exit(1 if failed else 0)
