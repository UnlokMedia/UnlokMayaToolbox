"""Headless tests for UnlokToolbox.py.

Run with mayapy (Maya 2023+):

    mayapy tests/test_toolbox.py

Loads the toolbox exactly like a Script Editor paste would (exec of the whole
file), minus showing the window, then exercises the engine, bake and UI.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")

import maya.cmds as cmds  # noqa: E402
import maya.api.OpenMaya as om  # noqa: E402
import maya.OpenMaya as om1  # noqa: E402
import maya.OpenMayaFX as omfx1  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def load_toolbox():
    ns = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        code = compile(f.read(), TOOLBOX, "exec")
    exec(code, ns)
    return ns


def straight_curve(length=10.0, name="testPath"):
    return cmds.curve(degree=1, point=[(0, 0, 0), (length, 0, 0)], name=name)


def instancer_matrices(inst):
    sel = om1.MSelectionList()
    sel.add(inst)
    dag = om1.MDagPath()
    sel.getDagPath(0, dag)
    fx = omfx1.MFnInstancer(dag)
    paths, mats, pidx, path_idx = om1.MDagPathArray(), om1.MMatrixArray(), om1.MIntArray(), om1.MIntArray()
    fx.allInstances(paths, mats, pidx, path_idx)
    return [[mats[i](r, c) for r in range(4) for c in range(4)] for i in range(mats.length())]


def close(a, b, tol=1e-3):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def run():
    tb = load_toolbox()
    PSS = tb["PathScatterSystem"]
    D = dict(tb["PS_DEFAULTS"])

    # ------------------------------------------------------------ engine
    cmds.file(new=True, force=True)
    curve = straight_curve()
    system = PSS.create(D)
    system.set_paths([curve])
    n, ms, warn = system.rebuild(D)
    check("fit-to-size count on 10u path with 1u cubes", n == 10, "got %d (%.1f ms) %s" % (n, ms, warn))
    items, _ = system.compute(D)
    t = items[0][1]
    # Bottom pivot: the 0.1-high cube's origin sits 0.05 above the path.
    check("first item centred at x=0.5, resting on path", close([t.getElement(3, 0), t.getElement(3, 1)], [0.5, 0.05]),
          str([round(t.getElement(3, i), 4) for i in range(3)]))
    inst_m = instancer_matrices(system.instancer())
    check("instancer matrices == computed matrices",
          len(inst_m) == len(items) and all(close(inst_m[i], list(items[i][1])) for i in range(len(items))))

    s = dict(D, dist_mode="Spacing", spacing=2.0)
    check("spacing mode", system.rebuild(s)[0] == 6)
    s = dict(D, dist_mode="Count", count=7)
    check("count mode", system.rebuild(s)[0] == 7)
    s = dict(D, rows=3, row_spacing=0.6, row_stagger=0.5)
    check("rows + stagger", system.rebuild(s)[0] == 29, str(system.rebuild(s)[0]))
    s = dict(D, rows=3, row_spacing=0.6, rows_centered=True)
    items, _ = system.compute(s)
    zs = sorted(set(round(m.getElement(3, 2), 4) for _, m in items))
    check("centred rows straddle the path", close(zs, [-0.6, 0.0, 0.6]), str(zs))
    s = dict(D, dist_mode="Spacing", spacing=0.0001, max_items=500)
    n, _, warn = system.rebuild(s)
    check("max items cap", n == 500 and warn, warn or "")
    s = dict(D, skip_chance=50, seed=3)
    a = system.rebuild(s)[0]
    b = system.rebuild(s)[0]
    check("random is stable for a seed", a == b and 0 < a < 10, str(a))
    s = dict(D, rand_rot_y=45, rand_scale_min=0.5, rand_scale_max=1.5, rand_side=0.2, seed=7)
    m1 = [list(m) for _, m in system.compute(s)[0]]
    m2 = [list(m) for _, m in system.compute(s)[0]]
    check("random transforms deterministic", m1 == m2 and len(m1) > 3)
    for kind in ("Cylinder", "Plane", "Sphere", "Cube"):
        n, _, warn = system.rebuild(dict(D, source_type=kind, size_x=2.0))
        check("preset %s rebuild" % kind, n == 5, "%d %s" % (n, warn))
    n, _, _ = system.rebuild(dict(D, forward_axis="Z", up_axis="Y", size_x=2.0, size_z=0.5))
    check("forward axis Z uses width as length", n == 20, str(n))
    n, _, warn = system.rebuild(dict(D, forward_axis="Y", up_axis="Y"))
    check("same forward/up axis warns, no crash", warn is not None)

    # closed curve, count mode: no doubled item at the seam
    circle = cmds.circle(normal=(0, 1, 0), radius=5, sections=16, constructionHistory=False)[0]
    system.set_paths([circle])
    items, _ = system.compute(dict(D, dist_mode="Count", count=12))
    pts = [(round(m.getElement(3, 0), 3), round(m.getElement(3, 2), 3)) for _, m in items]
    check("closed curve count: 12 unique positions", len(set(pts)) == 12, str(len(set(pts))))

    # ------------------------------------------------------- surface snap
    plane = cmds.polyPlane(w=20, h=20, sx=4, sy=4, name="roof")[0]
    cmds.setAttr(plane + ".rotateX", 30)
    cmds.makeIdentity(plane, apply=True)
    roof_curve = cmds.curve(degree=1, point=[(-5, 0.5, 0), (5, 0.5, 0)], name="roofPath")
    system.set_paths([roof_curve])
    system.set_surfaces([plane])
    items, _ = system.compute(dict(D, rows=2, row_spacing=1.0, row_lift=0.05, pivot="Source Origin"))
    fn = om.MFnMesh(tb["get_dag_path"](plane))
    normal = fn.getPolygonNormal(0, om.MSpace.kWorld)
    worst = 0.0
    for _, m in items:
        p = om.MPoint(m.getElement(3, 0), m.getElement(3, 1), m.getElement(3, 2))
        cp = fn.getClosestPoint(p, om.MSpace.kWorld)[0]
        worst = max(worst, (p - cp).length())
    row0 = [m for _, m in items][:10]
    up = om.MVector(row0[0].getElement(1, 0), row0[0].getElement(1, 1), row0[0].getElement(1, 2)).normal()
    check("items snapped onto sloped surface (+ row lift)", worst < 0.051 + 1e-4, "max dist %.4f" % worst)
    check("items aligned to surface normal", abs(abs(up * normal) - 1.0) < 1e-3, str(up))

    # ------------------------------------------------------- mesh sources
    cmds.file(new=True, force=True)
    rock_a = cmds.polySphere(r=0.5, name="rockA")[0]
    rock_b = cmds.polyCube(w=1, h=2, d=1, name="rockB")[0]
    cmds.setAttr(rock_a + ".translate", 20, 5, 3)  # object-space is used, not world position
    lam = cmds.shadingNode("lambert", asShader=True, name="redMat")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="redSG")
    cmds.connectAttr(lam + ".outColor", sg + ".surfaceShader")
    cmds.sets(rock_b + ".f[0:2]", edit=True, forceElement=sg)
    curve = straight_curve()
    system = PSS.create(D)
    system.set_paths([curve])
    system.set_sources([rock_a, rock_b])
    s = dict(D, source_type="Mesh", dist_mode="Spacing", spacing=1.0)
    n, _, warn = system.rebuild(s)
    check("mesh variants scatter", n == 11, "%d %s" % (n, warn))
    used = set(vi for vi, _ in system.compute(s)[0])
    check("both variants used", used == {0, 1}, str(used))
    items, _ = system.compute(s)
    first = [m for vi, m in items if vi == 0][0]
    check("source world position ignored", abs(first.getElement(3, 1) - 0.5) < 1e-4 and abs(first.getElement(3, 2)) < 1e-4,
          str([round(first.getElement(3, i), 3) for i in range(3)]))

    # bake copies keeps per-face shading
    s_copy = dict(s, bake_mode="Copies", keep_system=True)
    out = system.bake(s_copy)
    shapes = cmds.listRelatives(out, allDescendents=True, type="mesh", fullPath=True) or []
    check("bake copies: one mesh per item", len(shapes) == 11, str(len(shapes)))
    cube_copies = [sh for sh in shapes if cmds.polyEvaluate(sh, face=True) == 6]
    members = cmds.sets(sg, q=True) or []
    check("bake copies: per-face material copied",
          cube_copies and any(short in m for m in members for short in [cube_copies[0].split("|")[-2]]),
          str(members[:3]))
    check("keep_system hides live system", system.exists() and not cmds.getAttr(system.root() + ".visibility"))
    cmds.delete(out)

    s_inst = dict(s, bake_mode="Instances", keep_system=False)
    out = system.bake(s_inst)
    check("bake instances: system deleted", not system.exists())
    kids = cmds.listRelatives(out, children=True, fullPath=True) or []
    with_geo = [k for k in kids if cmds.listRelatives(k, shapes=True)]
    check("bake instances: items keep geometry after system delete", len(kids) == 11 and len(with_geo) == 11,
          "%d items, %d with geometry" % (len(kids), len(with_geo)))
    check("user source meshes untouched", cmds.objExists(rock_a) and cmds.objExists(rock_b)
          and cmds.getAttr(rock_a + ".translateX") == 20)

    curve = straight_curve(name="p2")
    system = PSS.create(D)
    system.set_paths([curve])
    system.rebuild(D)
    out = system.bake(dict(D, bake_mode="Combined Mesh"))
    check("bake combined: single mesh", cmds.nodeType(cmds.listRelatives(out, shapes=True, fullPath=True)[0]) == "mesh"
          and cmds.polyEvaluate(out, vertex=True) == 80, str(cmds.polyEvaluate(out, vertex=True)))

    # delete system keeps user curve, deletes drawn ones
    system = PSS.create(D)
    drawn = cmds.curve(degree=1, point=[(0, 0, 0), (3, 0, 0)])
    drawn = system.adopt_curve(drawn)
    system.set_paths([drawn])
    system.set_paths([curve])
    check("replacing a drawn path deletes the old drawn curve", not cmds.objExists(drawn))
    system.delete()
    check("deleting system keeps user curve", cmds.objExists(curve))

    # settings round trip + lookup from any child
    system = PSS.create(dict(D, rows=4, seed=42))
    check("settings persist on the node", system.get_settings()["rows"] == 4 and system.get_settings()["seed"] == 42)
    found = PSS.from_node(system.instancer())
    check("from_node finds the owning system", found is not None and found.uuid == system.uuid)
    check("all_roots lists systems", system.root() in PSS.all_roots())

    # ------------------------------------------------------- drawing bits
    tmp = cmds.curve(degree=1, point=[(0, 0, 0), (1, 0, 0)])
    cmds.curve(tmp, replace=True, degree=1, point=[(0, 0, 0), (1, 0, 0), (2, 1, 0)])
    check("temp curve replace works", len(cmds.getAttr(tmp + ".cv[*]")) == 3)
    box = cmds.polyCube(w=4, h=4, d=4, name="hitBox")[0]
    dag = tb["get_dag_path"](box)
    fnm = om.MFnMesh(dag)
    drawer = tb["SurfacePathDrawer"]
    hit = drawer._intersect((fnm, fnm.autoUniformGridParams()), om.MPoint(0, 10, 0), om.MVector(0, -1, 0))
    check("raycast with accel params", hit and abs(hit[0].y - 2.0) < 1e-4, str(hit))
    miss = drawer._intersect((fnm, fnm.autoUniformGridParams()), om.MPoint(10, 10, 0), om.MVector(0, 1, 0))
    check("raycast miss returns None", miss is None)
    check("ray/box prefilter hit", drawer._ray_hits_box(om.MPoint(0, 10, 0), om.MVector(0, -1, 0), dag))
    check("ray/box prefilter miss", not drawer._ray_hits_box(om.MPoint(10, 10, 0), om.MVector(0, -1, 0), dag))
    entry = drawer._ray_box_entry(om.MPoint(0, 10, 0), om.MVector(0, -1, 0), drawer._world_box(dag))
    check("ray/box entry distance", entry is not None and abs(entry - 8.0) < 1e-6, str(entry))

    # live stroke preview: edited in place, grows past capacity, leaves nothing behind
    d = drawer(lambda *a: None, lambda: 3)
    before = set(cmds.ls(dagObjects=True, long=True))
    sel_before = cmds.ls(selection=True)
    d.points = [(om.MPoint(i * 0.1, 0, 0), None) for i in range(10)]
    d._update_preview()
    shape = d.preview[1].fullPathName()
    cvs = cmds.getAttr(shape + ".cv[*]")
    check("preview curve shows stroke points", d.preview[2] == 1024 and abs(cvs[9][0] - 0.9) < 1e-6
          and abs(cvs[-1][0] - 0.9) < 1e-6, str(cvs[9]))
    node = d.preview[0]
    d.points = [(om.MPoint(i * 0.01, 0, 0), None) for i in range(3000)]
    d._update_preview()
    last = cmds.getAttr(d.preview[1].fullPathName() + ".cv[1023]")[0][0]
    check("long strokes reuse the same preview node (thinned for display)",
          d.preview[0] is node and abs(last - 29.99) < 1e-6, str(last))
    xform = om.MDagPath.getAPathTo(d.preview[0].object()).fullPathName()
    check("preview is never saved and hidden from the Outliner",
          not om.MFnDependencyNode(d.preview[0].object()).canBeWritten() and cmds.getAttr(xform + ".hiddenInOutliner"))
    d._set_preview_visible(False)
    check("preview hides between strokes", not cmds.getAttr(xform + ".visibility"))
    check("preview doesn't change the selection", cmds.ls(selection=True) == sel_before)
    d._delete_preview()
    check("preview cleaned up", set(cmds.ls(dagObjects=True, long=True)) == before)

    # UI is covered by tests/gui_smoke.py (needs a real Maya session).


try:
    run()
except Exception:
    traceback.print_exc()
    RESULTS.append(("exception", False, ""))
finally:
    failed = [r for r in RESULTS if not r[1]]
    print("\n%d passed, %d failed" % (len(RESULTS) - len(failed), len(failed)))
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(1 if failed else 0)
