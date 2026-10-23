"""Headless tests for Thatch Roof (mayapy).

    mayapy tests/test_thatch_roof.py

Builds every roof shape and end type in each thatch style and checks: the
shells are closed and face outwards, the roof sits on its box (eaves, ridge,
overhang), UVs are the right way round (in 0..1 for the surface, stacked in
one tile or column per stack for planes / pieces), undo / redo (the redo
rebuilds the seed planes), save / reopen, live edits, following the box,
bake, the Smart UDIM tag and speed.
"""

import math
import os
import sys
import tempfile
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


def load_toolbox():
    ns = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    return ns


def mesh_fn(tb, node):
    return om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))


def boundary_edges(fn):
    it = om.MItMeshEdge(fn.dagPath())
    n = 0
    while not it.isDone():
        if it.onBoundary():
            n += 1
        it.next()
    return n


def signed_volume(fn):
    pts = fn.getPoints(om.MSpace.kWorld)
    counts, conn = fn.getVertices()
    vol, k = 0.0, 0
    for c in counts:
        ids = conn[k:k + c]
        k += c
        a = pts[ids[0]]
        for i in range(1, c - 1):
            b, d = pts[ids[i]], pts[ids[i + 1]]
            vol += (a.x * (b.y * d.z - b.z * d.y) - a.y * (b.x * d.z - b.z * d.x) + a.z * (b.x * d.y - b.y * d.x))
    return vol / 6.0


def uv_stats(fn):
    """(us, vs, fraction of faces with positive UV area)."""
    us, vs = fn.getUVs()
    counts, ids = fn.getAssignedUVs()
    k, good, total = 0, 0, 0
    for c in counts:
        poly = ids[k:k + c]
        k += c
        area = 0.0
        for i in range(c):
            a, b = poly[i], poly[(i + 1) % c]
            area += us[a] * vs[b] - us[b] * vs[a]
        if abs(area) > 1e-14:
            total += 1
            good += area > 0.0
    return list(us), list(vs), good / float(max(1, total))


def bbox(node):
    return cmds.exactWorldBoundingBox(node)


def box(name, size=(6.0, 3.0, 4.0), move=(0.0, 4.0, 0.0), rot=(0.0, 0.0, 0.0)):
    node = cmds.ls(cmds.polyCube(w=1, h=1, d=1, name=name, constructionHistory=False)[0], long=True)[0]
    cmds.xform(node, scale=size, rotation=rot, translation=move)
    return node


def run():
    tb = load_toolbox()
    cmds.undoInfo(state=True, infinity=True)
    D = tb["THATCH_DEFAULTS"]

    # --- the box and its frame
    house = cmds.polyCube(w=8, h=3, d=5, name="house", constructionHistory=False)[0]
    cmds.move(0, 1.5, 0, house)
    cmds.select(house)
    b = tb["create_thatch_box"]([house])
    f = tb["thatch_frame"](b)
    check("a box made over the house sits on its walls", abs(f["o"][1] - 3.0) < 1e-6 and abs(f["L"] - 4.0) < 1e-6
          and abs(f["W"] - 2.5) < 1e-6 and abs(f["H"] - 2.75) < 1e-6, str(f))
    check("the ridge runs along the long side", abs(f["a"][0]) > 0.999 and f["y"][1] > 0.999)
    check("the box is selected and doesn't render",
          cmds.ls(selection=True, long=True) == [b] and
          not cmds.getAttr(tb["_log_shape"](b) + ".primaryVisibility"))
    cmds.file(new=True, force=True)
    b = box("rot", size=(4.0, 2.0, 7.0), move=(3, 2, 1), rot=(0, 30, 0))
    f = tb["thatch_frame"](b)
    check("a rotated box: the ridge follows its longer (Z) side", abs(f["L"] - 3.5) < 1e-6 and
          abs(f["a"][0] - math.sin(math.radians(30))) < 1e-6)

    # --- every shape and end type, as a surface: closed, facing out, on the box
    cmds.file(new=True, force=True)
    combos = [("Ridge", "Hip", "Hip"), ("Ridge", "Gable", "Gable"), ("Ridge", "Half-hip", "Hip"),
              ("Ridge", "Gable", "Half-hip"), ("Lean-to", "Gable", "Gable"), ("Lean-to", "Hip", "Gable"),
              ("Cone", "Gable", "Gable")]
    for k, (shape, ea, eb) in enumerate(combos):
        b = box("b%d" % k, move=(k * 10.0, 4.0, 0.0))
        s = {"shape": shape, "end_a": ea, "end_b": eb, "resolution": 60}
        t0 = time.time()
        rep = tb["make_thatch_roof"](b, s)
        dt = time.time() - t0
        straw = tb["thatch_parts"](rep["root"])["straw"]
        fn = mesh_fn(tb, straw)
        bb = bbox(straw)
        vol = signed_volume(fn)
        us, vs, good = uv_stats(fn)
        label = "%s %s/%s" % (shape, ea, eb)
        check("%s: closed shell facing out" % label, boundary_edges(fn) == 0 and vol > 0.0,
              "boundary %d, volume %.3f" % (boundary_edges(fn), vol))
        span = 4.0 if shape != "Cone" else 5.0
        top = bb[4] - 2.5  # above the box's bottom
        check("%s: ridge at the box top, eaves below it" % label,
              2.9 < top < 3.0 + 2.0 * D["thickness"] * span and bb[1] < 2.5,
              "top %.3f, low %.3f (%.2fs)" % (top, bb[1], dt))
        reach = (bb[5] - bb[2]) * 0.5
        want = 2.0 + D["overhang"] * span * (0.5 if shape == "Lean-to" else 1.0)  # no overhang up at the wall
        if shape == "Cone":  # an elliptical cone's eave ring is the box's ellipse scaled up
            want = 2.0 * (1.0 + D["overhang"] * span / 2.5)
        check("%s: overhang past the box" % label, want - 0.05 < reach < want + D["thickness"] * span + 0.05,
              "half width %.3f, want ~%.3f" % (reach, want))
        check("%s: UVs inside 0..1, the right way round" % label,
              min(us) >= 0.0 and max(us) <= 1.0 and min(vs) >= 0.0 and max(vs) <= 1.0 and good > 0.995,
              "u %.3f..%.3f v %.3f..%.3f, %.2f%% upright" % (min(us), max(us), min(vs), max(vs), good * 100))
        under = tb["thatch_parts"](rep["root"])["underlay"]
        check("%s: no underlay for a surface" % label, not cmds.getAttr(under + ".visibility"))
    # a gable end is upright: nothing reaches past the verge's overhang
    b = box("gable", move=(0, 4, 20))
    rep = tb["make_thatch_roof"](b, {"end_a": "Gable", "end_b": "Hip", "resolution": 60})
    bb = bbox(tb["thatch_parts"](rep["root"])["straw"])
    check("gable end reaches the overhang, the hip end slopes in",
          abs(bb[3] - (3.0 + D["overhang"] * 4.0)) < 0.05 + D["thickness"] * 4.0 and bb[0] > -3.0 - 0.6,
          "x %.3f..%.3f" % (bb[0], bb[3]))

    # --- planes and 3D pieces: stacked UVs
    for style in ("Planes", "3D Pieces"):
        cmds.file(new=True, force=True)
        b = box("b")
        t0 = time.time()
        rep = tb["make_thatch_roof"](b, {"style": style, "stacks": 3, "resolution": 60})
        dt = time.time() - t0
        parts = tb["thatch_parts"](rep["root"])
        fn = mesh_fn(tb, parts["straw"])
        us, vs, good = uv_stats(fn)
        tiles = set(int(math.floor(max(0.0, u - 1e-6))) for u in us)  # u = 1.0 is the tile's edge
        check("%s: pieces laid (%.2fs)" % (style, dt), rep["pieces"] > 500, "%d pieces, %d faces" % (
            rep["pieces"], fn.numPolygons))
        check("%s: 3 stacks in UDIM tiles 1001-1003" % style, tiles == {0, 1, 2} and min(vs) >= 0.0 and
              max(vs) <= 1.0, str(sorted(tiles)))
        check("%s: UVs the right way round" % style, good > 0.999, "%.2f%%" % (good * 100))
        under = mesh_fn(tb, parts["underlay"])
        check("%s: an underlay, closed" % style, cmds.getAttr(parts["underlay"] + ".visibility") and
              boundary_edges(under) == 0 and signed_volume(under) > 0.0)
        shape = tb["_log_shape"](parts["straw"])
        check("%s: tagged as stacked for Smart UDIM" % style, cmds.getAttr(shape + "." + tb["UV_STACKED_ATTR"]))
        if style == "3D Pieces":
            check("3D pieces are closed and face out", boundary_edges(fn) == 0 and signed_volume(fn) > 0.0)
        else:
            normals = fn.getNormals(om.MSpace.kWorld)
            up = sum(1 for n in normals if n.y > 0.0) / float(len(normals))
            check("planes face up the roof", up > 0.9, "%.1f%% up" % (up * 100))
        rep = tb["update_thatch_roofs"]({rep["root"] if "root" in rep else tb["thatch_roofs"]()[0]:
                                         {"stack_layout": "Atlas columns"}})
        us = uv_stats(mesh_fn(tb, parts["straw"]))[0]
        check("%s: atlas columns stay in 0..1" % style, min(us) >= 0.0 and max(us) <= 1.0)
    # one stack: everything in 0..1, so each piece is the same square
    rep = tb["update_thatch_roofs"]({tb["thatch_roofs"]()[0]: {"stacks": 1, "style": "Planes"}})
    us, vs, _ = uv_stats(mesh_fn(tb, tb["thatch_parts"](tb["thatch_roofs"]()[0])["straw"]))
    check("one stack: every plane fills 0..1", abs(min(us)) < 1e-6 and abs(max(us) - 1.0) < 1e-6)
    rep = tb["update_thatch_roofs"]({tb["thatch_roofs"]()[0]: {"mirror": True}})
    us, vs, good = uv_stats(mesh_fn(tb, tb["thatch_parts"](tb["thatch_roofs"]()[0])["straw"]))
    check("mirror flips about half the pieces", 0.35 < good < 0.65, "%.1f%% upright" % (good * 100))

    # --- undo / redo, save / reopen
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    b = box("b")
    cmds.select(b)
    rep = tb["make_thatch_roof"](b, {"resolution": 50})
    root = rep["root"]
    nverts = mesh_fn(tb, tb["thatch_parts"](root)["straw"]).numVertices
    cmds.undo()
    check("undo removes the roof", not cmds.objExists(root))
    cmds.redo()
    stale = tb["rebuild_stale_thatch"]()
    check("redo + rebuild brings it back", stale == [root] and
          mesh_fn(tb, tb["thatch_parts"](root)["straw"]).numVertices == nverts,
          "%s, %d verts" % (stale, mesh_fn(tb, tb["thatch_parts"](root)["straw"]).numVertices))
    path = os.path.join(tempfile.gettempdir(), "unlok_thatch_test.ma")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaAscii", force=True)
    cmds.file(new=True, force=True)
    cmds.file(path, open=True, force=True)
    root = tb["thatch_roofs"]()[0]
    check("save / reopen keeps the roof and its settings",
          mesh_fn(tb, tb["thatch_parts"](root)["straw"]).numVertices == nverts and
          tb["thatch_data"](root)["resolution"] == 50 and tb["thatch_box"](root) is not None)
    check("nothing to rebuild after reopening", tb["rebuild_stale_thatch"]() == [])

    # --- live edits and following the box
    before = mesh_fn(tb, tb["thatch_parts"](root)["straw"]).numPolygons
    cmds.undoInfo(state=True, infinity=True)
    queue = cmds.undoInfo(q=True, undoName=True)
    rep = tb["update_thatch_roofs"]({root: {"levels": 5, "shape": "Cone"}})
    check("live edit rebuilds it and stays out of the undo queue",
          rep["done"] == [root] and tb["thatch_data"](root)["levels"] == 5 and
          mesh_fn(tb, tb["thatch_parts"](root)["straw"]).numPolygons != before and
          cmds.undoInfo(q=True, undoName=True) == queue)
    b = tb["thatch_box"](root)
    cmds.move(5, 0, 0, b, relative=True)
    cmds.scale(1.5, 1, 1, b, relative=True)
    check("moving the box is noticed", tb["thatch_box_moved"](root))
    tb["update_thatch_roofs"]({root: {}})
    bb = bbox(tb["thatch_parts"](root)["straw"])
    check("the roof follows the box", abs((bb[0] + bb[3]) * 0.5 - 5.0) < 0.05 and not tb["thatch_box_moved"](root),
          "centre x %.3f" % ((bb[0] + bb[3]) * 0.5))
    cmds.delete(b)
    rep = tb["update_thatch_roofs"]({root: {"levels": 2}})
    check("a roof whose box is deleted keeps its place", rep["lost"] == [root] and rep["done"] == [root])

    # --- a deformed box: the roof warps through its corners
    def verts_where(node, test):
        out = []
        for i in range(8):
            v = "%s.vtx[%d]" % (node, i)
            if test(cmds.pointPosition(v, world=True)):
                out.append(v)
        return out

    def straw_pts(r):
        return mesh_fn(tb, tb["thatch_parts"](r)["straw"]).getPoints(om.MSpace.kWorld)

    cmds.file(new=True, force=True)
    b = box("b")
    f = tb["thatch_frame"](b)
    plain = dict(f)
    for k in ("corners", "axis", "flip"):
        plain.pop(k)
    s = {"resolution": 40}
    warped = tb["thatch_build"](f, s)["straw"][0]
    straight = tb["thatch_build"](plain, s)["straw"][0]
    check("a plain box warps to exactly the same roof", f.get("corners") and len(warped) == len(straight) and
          max(abs(a[i] - b_[i]) for a, b_ in zip(warped, straight) for i in range(3)) < 1e-6)
    root = tb["make_thatch_roof"](b, {"resolution": 50, "end_a": "Gable", "end_b": "Gable"})["root"]
    cmds.move(0, 0, -0.8, verts_where(b, lambda q: q[0] > 0 and q[2] > 0), relative=True)
    cmds.move(0, 0, 0.8, verts_where(b, lambda q: q[0] > 0 and q[2] < 0), relative=True)
    check("moving the box's vertices is noticed", tb["thatch_box_moved"](root))
    tb["update_thatch_roofs"]({root: {}})
    pts = straw_pts(root)
    narrow = max(abs(q.z) for q in pts if q.x > 2.6)
    wide = max(abs(q.z) for q in pts if q.x < -2.6)
    fn = mesh_fn(tb, tb["thatch_parts"](root)["straw"])
    check("a tapered box tapers the roof, still a closed shell facing out", wide - narrow > 0.6 and
          boundary_edges(fn) == 0 and signed_volume(fn) > 0.0, "half width %.2f -> %.2f" % (wide, narrow))
    cmds.move(0, 1.0, 0, verts_where(b, lambda q: q[0] > 0 and q[1] > 4), relative=True)
    tb["update_thatch_roofs"]({root: {}})
    pts = straw_pts(root)
    hi_end = max(q.y for q in pts if q.x > 2.6)
    lo_end = max(q.y for q in pts if q.x < -2.6)
    check("a taller end lifts the ridge there", hi_end - lo_end > 0.8, "%.2f vs %.2f" % (hi_end, lo_end))
    cmds.file(new=True, force=True)
    b = box("b")
    root = tb["make_thatch_roof"](b, {"resolution": 50, "end_a": "Gable", "end_b": "Gable", "top": 0.0})["root"]
    cmds.move(0, 0, 1.0, verts_where(b, lambda q: q[1] > 4), relative=True)
    tb["update_thatch_roofs"]({root: {}})
    pts = straw_pts(root)
    top = max(q.y for q in pts)
    ridge = [q.z for q in pts if q.y > top - 0.05]
    fn = mesh_fn(tb, tb["thatch_parts"](root)["straw"])
    check("a skewed box moves the ridge over with its top", abs(sum(ridge) / len(ridge) - 1.0) < 0.25 and
          signed_volume(fn) > 0.0, "ridge z %.2f" % (sum(ridge) / len(ridge)))
    cmds.file(new=True, force=True)
    b = box("b")
    cmds.scale(-6, 3, 4, b)
    root = tb["make_thatch_roof"](b, {"resolution": 40, "style": "Planes", "density": 0.3})["root"]
    parts = tb["thatch_parts"](root)
    fn = mesh_fn(tb, parts["underlay"])
    normals = mesh_fn(tb, parts["straw"]).getNormals(om.MSpace.kWorld)
    up = sum(1 for n in normals if n.y > 0.0) / float(len(normals))
    check("a mirrored box still makes a roof facing out", tb["thatch_frame"](b)["flip"] and
          signed_volume(fn) > 0.0 and up > 0.9, "%.1f%% up" % (up * 100))
    cyl = cmds.polyCylinder(r=2, h=3, name="notABox", constructionHistory=False)[0]
    cmds.move(20, 4, 0, cyl)
    f = tb["thatch_frame"](cyl)
    check("any other mesh still works as a box (its bounding box)", not f.get("corners") and
          abs(f["L"] - 2.0) < 1e-3 and abs(f["H"] - 3.0) < 1e-3)

    # --- selection: a roof is found from its box or any of its meshes
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    b = tb["create_thatch_box"]()
    root = tb["make_thatch_roof"](b, {"resolution": 40})["root"]
    other = box("other", move=(20, 0, 0))
    cmds.select(b)
    sel = tb["thatch_selection"]()
    check("selecting the box picks its roof", sel == ([root], []), str(sel))
    cmds.select(tb["thatch_parts"](root)["straw"], other)
    sel = tb["thatch_selection"]()
    check("selecting the straw picks the roof; other meshes are boxes", sel == ([root], [other]), str(sel))

    # --- bake
    done, gone = tb["bake_thatch"]([root])
    check("bake keeps the meshes, drops the settings and the box", done == [root] and gone == ["thatchBox0001"] and
          not tb["is_thatch_roof"](root) and not cmds.objExists(b) and cmds.objExists(root))
    cmds.undo()
    check("undo un-bakes it", tb["is_thatch_roof"](root) and cmds.objExists(b))
    cmds.redo()
    cmds.select(tb["thatch_parts"](root)["straw"])
    check("a baked roof is plain geometry (not a box, not a roof)", tb["thatch_selection"]() == ([], []))

    # --- presets set the shape and keep the thatch style; look presets set the style too
    p = tb["thatch_preset"]("Roundhouse")
    check("shape presets set the shape only", p["shape"] == "Cone" and "style" not in p and "stacks" not in p)
    p = tb["thatch_preset"]("Cambodian shack (leaf panels)")
    check("the Cambodian shack preset sets a makeshift leaf-panel roof", p["style"] == "Leaf Panels" and
          p["end_a"] == "Gable" and p["ridge_sag"] > 0 and p["ragged"] > 0 and "stacks" not in p)

    # --- makeshift: ridge sag, warp, ragged eaves, gaps
    cmds.file(new=True, force=True)
    b = box("b")
    root = tb["make_thatch_roof"](b, {"resolution": 60, "end_a": "Gable", "end_b": "Gable"})["root"]
    straw = tb["thatch_parts"](root)["straw"]

    def top_at(x):
        fn = mesh_fn(tb, straw)
        return max(p.y for p in fn.getPoints(om.MSpace.kWorld) if abs(p.x - x) < 0.08)
    mid0, end0 = top_at(0.0), top_at(2.6)
    low0 = bbox(straw)[1]
    tb["update_thatch_roofs"]({root: {"ridge_sag": 1.0}})
    mid1, end1 = top_at(0.0), top_at(2.6)
    check("ridge sag drops the middle of the ridge, not its ends", mid0 - mid1 > 0.15 and abs(end0 - end1) < 0.1,
          "middle %.3f -> %.3f, end %.3f -> %.3f" % (mid0, mid1, end0, end1))
    tb["update_thatch_roofs"]({root: {"ridge_sag": 0.0, "ragged": 1.5}})
    fn = mesh_fn(tb, straw)
    check("ragged eaves hang lower in places, still a closed shell", bbox(straw)[1] < low0 - 0.1 and
          boundary_edges(fn) == 0 and signed_volume(fn) > 0.0, "low %.3f -> %.3f" % (low0, bbox(straw)[1]))
    tb["update_thatch_roofs"]({root: {"ragged": 0.0, "warp": 1.5}})
    fn = mesh_fn(tb, straw)
    check("warp keeps a closed shell", boundary_edges(fn) == 0 and signed_volume(fn) > 0.0)
    n0 = tb["update_thatch_roofs"]({root: {"warp": 0.0, "style": "Planes", "density": 0.5}})["pieces"]
    n1 = tb["update_thatch_roofs"]({root: {"gaps": 0.6}})["pieces"]
    check("gaps leave pieces out in clumps", 0.2 * n0 < n1 < 0.85 * n0, "%d -> %d" % (n0, n1))

    # --- leaf panels: courses of panels, stacked UVs, fronts outwards
    tb["update_thatch_roofs"]({root: {"gaps": 0.0}})
    for preset in ("Cambodian shack (leaf panels)", "Cambodian shack (straw)", "Grass hut (messy)"):
        s = dict(tb["THATCH_DEFAULTS"], **tb["thatch_preset"](preset))
        s["stacks"] = 3
        t0 = time.time()
        rep = tb["update_thatch_roofs"]({root: s})
        dt = time.time() - t0
        fn = mesh_fn(tb, straw)
        us, vs, good = uv_stats(fn)
        tiles = set(int(math.floor(max(0.0, u - 1e-6))) for u in us)
        check("%s: builds (%.2fs)" % (preset, dt), rep["pieces"] > 50 and dt < 6.0,
              "%d pieces, %d faces" % (rep["pieces"], fn.numPolygons))
        check("%s: 3 stacks, UVs the right way round" % preset, tiles == {0, 1, 2} and good > 0.999,
              "%s, %.2f%% upright" % (sorted(tiles), good * 100))
        if s["style"] == "Leaf Panels":
            normals = fn.getNormals(om.MSpace.kWorld)
            up = sum(1 for n in normals if n.y > 0.0) / float(len(normals))
            check("leaf panels face out of the roof", up > 0.95, "%.1f%% up" % (up * 100))
            bb = bbox(straw)
            check("leaf panels cover the whole roof, over the ridge and past the verges",
                  bb[4] > 2.5 + 3.0 - 0.3 and bb[0] < -3.0 and bb[3] > 3.0, str([round(v, 2) for v in bb]))
            check("no underlay for the leaf panel shack", not cmds.getAttr(tb["thatch_parts"](root)["underlay"] +
                                                                           ".visibility"))

    # --- Smart UDIM: surfaces are Keep UVs, stacked planes Hands off
    cmds.file(new=True, force=True)
    grp = cmds.group(empty=True, name="hut_GRP")
    b1 = box("b1")
    b2 = box("b2", move=(10, 4, 0))
    cmds.parent(b1, b2, grp)
    r1 = tb["make_thatch_roof"](cmds.ls("b1", long=True)[0], {"resolution": 40})["root"]
    r2 = tb["make_thatch_roof"](cmds.ls("b2", long=True)[0], {"resolution": 40, "style": "Planes", "density": 0.3})["root"]
    check("roofs go next to their box", r1.startswith("|hut_GRP|") and r2.startswith("|hut_GRP|"))
    asset = tb["SmartUdimAsset"].for_group(cmds.ls("hut_GRP", long=True)[0])
    asset.scan()
    st = asset.uv_status()
    meshes = [tb["thatch_parts"](r1)["straw"], tb["thatch_parts"](r2)["straw"], tb["thatch_parts"](r2)["underlay"]]
    check("Smart UDIM Scan: surface Keep UVs, stacked planes Hands off, underlay Keep UVs",
          st.get(meshes[0]) == "keep" and st.get(meshes[1]) == "handsoff" and st.get(meshes[2]) == "keep",
          str(st))
    asset.set_uv_status([meshes[1]], "auto")
    asset.scan()
    check("marking stacked planes Auto sticks through the next Scan", meshes[1] not in asset.uv_status())

    # --- speed (defaults)
    cmds.file(new=True, force=True)
    for style in ("Surface", "Planes", "3D Pieces"):
        b = box("speed")
        t0 = time.time()
        rep = tb["make_thatch_roof"](b, {"style": style})
        dt = time.time() - t0
        fn = mesh_fn(tb, tb["thatch_parts"](rep["root"])["straw"])
        check("speed: %s at defaults under 6 s" % style, dt < 6.0, "%.2fs, %d faces, %d pieces" % (
            dt, fn.numPolygons, rep["pieces"]))
        cmds.delete(rep["root"], b)


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
maya.standalone.uninitialize()
os._exit(1 if failed else 0)
