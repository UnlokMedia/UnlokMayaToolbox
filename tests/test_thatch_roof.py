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

    # --- palm fronds: presets, forms, layers, ends, detail levels, the underlay
    cmds.file(new=True, force=True)
    b = box("palm")
    frame = tb["thatch_frame"](b)
    palms = [k for k in tb["THATCH_PRESETS"] if k.startswith("Palm")]
    check("four palm presets, each a whole palm look (Detail and stacks stay yours)", len(palms) == 4 and all(
        tb["thatch_preset"](k)["style"] == "Palm Fronds" and "detail" not in tb["thatch_preset"](k) and
        "stacks" not in tb["thatch_preset"](k) for k in palms))
    def sky_from_inside(straw, n=30):
        """Rays straight up from under the roof over the walls (the ridge line and a hip end's middle
        included): the ones that miss every leaf."""
        fn = mesh_fn(tb, straw)
        acc = fn.autoUniformGridParams()
        miss = []
        for i in range(n + 1):
            for j in range(n + 1):
                x, z = -2.8 + 5.6 * i / float(n), -1.85 + 3.7 * j / float(n)
                hit = fn.closestIntersection(om.MFloatPoint(x, 2.4, z), om.MFloatVector(0.0, 1.0, 0.0),
                                             om.MSpace.kWorld, 100.0, False, accelParams=acc)
                if not hit:
                    miss.append((round(x, 2), round(z, 2)))
        return miss
    root = None
    for k in palms:
        s = dict(tb["THATCH_DEFAULTS"], **tb["thatch_preset"](k))
        s["stacks"] = 3
        t0 = time.time()
        if root is None:
            rep = tb["make_thatch_roof"](b, s)
            root = rep["root"]
        else:
            rep = tb["update_thatch_roofs"]({root: s})
        dt = time.time() - t0
        parts = tb["thatch_parts"](root)
        fn = mesh_fn(tb, parts["straw"])
        us, vs, good = uv_stats(fn)
        tiles = set(int(math.floor(max(0.0, u - 1e-6))) for u in us)
        normals = fn.getNormals(om.MSpace.kWorld)
        up = sum(1 for n in normals if n.y > 0.0) / float(len(normals))
        check("%s: builds at Medium (%.2fs)" % (k, dt), rep["pieces"] > 100 and dt < 6.0,
              "%d fronds, %d faces" % (rep["pieces"], fn.numPolygons))
        check("%s: 3 stacks, UVs the right way round, leaves face out" % k, tiles == {0, 1, 2} and good > 0.99 and
              up > 0.8, "%s, %.2f%% upright, %.1f%% up" % (sorted(tiles), good * 100, up * 100))
        check("%s: no underlay: the fronds are the whole roof" % k,
              not cmds.getAttr(parts["underlay"] + ".visibility"))
        miss = sky_from_inside(parts["straw"])
        check("%s: no gaps: looking up from inside, every ray hits a leaf" % k, not miss,
              "%d of %d rays see the sky: %s" % (len(miss), 31 * 31, miss[:5]))
        bb = bbox(parts["straw"])
        check("%s: leaves cover the roof, tips hang past the eaves" % k, bb[1] < 2.5 - 0.05 and bb[4] > 5.3 and
              bb[0] < -3.0 and bb[3] > 3.0, str([round(v, 2) for v in bb]))

    def build(**over):
        s = dict(tb["THATCH_DEFAULTS"], style="Palm Fronds", resolution=80)
        s.update(over)
        return tb["thatch_build"](frame, s)

    def tris(mesh):
        return sum(1 for c in mesh[1] if c == 3)

    # leaflets: each tapers to one tip point (a triangle per leaflet side); forms differ in weight
    forms = dict((f, build(frond_form=f, top_layer=0.0)) for f in tb["THATCH_FROND_FORMS"])
    nv = dict((f, len(o["straw"][0])) for f, o in forms.items())
    lf = forms["Leaflets"]["straw"]
    check("leaflets taper to a tip, inside the left 85% of the UV square (rachis on the right)",
          tris(lf) > 1000 and max(lf[3]) <= 1.0 + 1e-6 and
          all(0.0 - 1e-6 <= u <= 0.85 + 1e-6 or u >= 0.88 for u in lf[3]), "%d tips" % tris(lf))
    check("forms: cards < leaflets < 3D leaflets, one layout", nv["Cards"] < nv["Leaflets"] < nv["3D Leaflets"] and
          len(set(o["pieces"] for o in forms.values())) == 1, str(nv))
    cu = forms["Cards"]["straw"][3]
    check("cards fill the UV square", abs(min(cu)) < 1e-6 and abs(max(cu) - 1.0) < 1e-6)

    # neat underneath: one under layer only (gables, no top layer, cap or fringe), leaflets measured base -> tip
    def leaflet_spread(neat):
        o = build(end_a="Gable", end_b="Gable", top_layer=0.0, ridge_fronds=False, end_fronds=0.0, neat=neat,
                  sticks=False,
                  mess=1.5, segments=4)
        pts = o["straw"][0]
        per = 2 * 4 + 1
        lens, sides = [], []
        for i in range(0, len(pts) - per + 1, per):
            a, b_, tip = pts[i], pts[i + 1], pts[i + per - 1]
            base = ((a[0] + b_[0]) * 0.5, (a[1] + b_[1]) * 0.5, (a[2] + b_[2]) * 0.5)
            d = (tip[0] - base[0], tip[1] - base[1], tip[2] - base[2])
            ln = math.sqrt(sum(c * c for c in d))
            lens.append(ln)
            sides.append(abs(d[0]) / max(1e-9, ln))  # how far it turns along the ridge
        mean = sum(lens) / len(lens)
        sd = math.sqrt(sum((v - mean) ** 2 for v in lens) / len(lens)) / mean
        return sd, sum(sides) / len(sides), len(lens)
    neat_sd, neat_side, n_neat = leaflet_spread(1.0)
    messy_sd, messy_side, n_messy = leaflet_spread(0.0)
    check("Neat 1: an even under layer; Neat 0: a messy one", neat_sd < 0.15 and messy_sd > neat_sd * 1.5 and
          messy_side > neat_side, "length spread %.3f vs %.3f, turn %.3f vs %.3f (%d / %d leaflets)" % (
              neat_sd, messy_sd, neat_side, messy_side, n_neat, n_messy))
    o0, o1 = build(top_layer=0.0), build(top_layer=1.0)
    check("the top layer adds loose fronds over the courses", o1["pieces"] > o0["pieces"] * 1.2 and
          len(o1["straw"][0]) > len(o0["straw"][0]), "%d -> %d fronds" % (o0["pieces"], o1["pieces"]))
    c0, c1 = build(ridge_fronds=False), build(ridge_fronds=True)
    check("a cap of fronds over the ridge", max(p[1] for p in c1["straw"][0]) > max(p[1] for p in c0["straw"][0]))

    # the ends: leaves hang off the gable verges; a hipped end has no fringe
    edge = 3.0 + tb["THATCH_DEFAULTS"]["overhang"] * 4.0

    def hanging(o):  # past the verge, above the eaves (a hip's eave leaves hang past the end line too)
        return sum(1 for p in o["straw"][0] if p[0] > edge + 0.15 and 2.7 < p[1] < 5.0)
    g0 = build(end_a="Gable", end_fronds=0.0, end_reach=0.0, edge_hang=0.0)
    g1 = build(end_a="Gable", end_fronds=1.5, end_reach=0.5)
    h1 = build(end_a="Hip", end_fronds=1.5, end_reach=0.5)
    check("gable fringe and reach: leaves hang down past the verge", hanging(g1) > 3 * max(10, hanging(g0)),
          "%d vs %d points" % (hanging(g1), hanging(g0)))
    check("a hipped end has no gable fringe", hanging(h1) < hanging(g1) * 0.05, "%d points" % hanging(h1))
    # two layers at the edges: the limp under layer hangs, the stiff top layer holds its line
    limp, stiff = build(top_layer=0.0, edge_hang=1.5), build(top_layer=0.0, edge_hang=0.0)
    out_limp, out_stiff = max(abs(p[2]) for p in limp["straw"][0]), max(abs(p[2]) for p in stiff["straw"][0])
    check("Edge hang: past the eaves the under layer hangs down instead of reaching out", out_limp < out_stiff - 0.08,
          "reach %.3f vs %.3f" % (out_limp, out_stiff))
    tips = build(top_layer=1.5, end_reach=1.0, edge_hang=1.5)
    check("the top layer sticks out further at the eaves than the hanging under layer",
          max(abs(p[2]) for p in tips["straw"][0]) > max(abs(p[2]) for p in limp["straw"][0]) + 0.05)

    # detail levels: Proxy is the shell only and quick; the rest keep the layout and add detail
    t0 = time.time()
    px = build(detail="Proxy")
    t_proxy = time.time() - t0
    check("Proxy: no fronds, the underlay shows the shape, quick", px["straw"] is None and px["underlay"] and
          px["level"] == 0 and t_proxy < 1.0, "%.2fs" % t_proxy)
    levels = dict((d, build(detail=d)) for d in ("Rough", "Medium", "High"))
    vv = dict((d, len(o["straw"][0])) for d, o in levels.items())
    uv_ = dict((d, len(o["underlay"][0])) for d, o in levels.items())
    check("Rough < Medium < High, the same fronds at every level", vv["Rough"] < vv["Medium"] < vv["High"] and
          uv_["Rough"] < uv_["Medium"] < uv_["High"] and len(set(o["pieces"] for o in levels.values())) == 1,
          "%s / underlay %s" % (vv, uv_))
    tb["update_thatch_roofs"]({root: {"detail": "Proxy"}})
    parts = tb["thatch_parts"](root)
    check("Proxy on a roof: the straw hides, the underlay shows", not cmds.getAttr(parts["straw"] + ".visibility")
          and cmds.getAttr(parts["underlay"] + ".visibility"))
    tb["update_thatch_roofs"]({root: {"detail": "Medium"}})
    check("back to Medium: the fronds come back", cmds.getAttr(parts["straw"] + ".visibility"))

    # the underlay: coursed relief, still a closed shell, the same topology as the plain one
    for style in ("Palm Fronds", "Planes", "Leaf Panels"):
        plain = build(style=style, underlay=True, underlay_relief=0.0)["underlay"]
        rel = build(style=style, underlay=True, underlay_relief=1.0)["underlay"]
        moved = max(math.sqrt(sum((a[i] - c[i]) ** 2 for i in range(3))) for a, c in zip(plain[0], rel[0]))
        check("%s: the underlay's relief moves it (%.3f m), same topology" % (style, moved),
              len(plain[0]) == len(rel[0]) and plain[2] == rel[2] and moved > 0.01)
    tb["update_thatch_roofs"]({root: {"underlay": True, "underlay_relief": 2.0, "resolution": 120}})
    under = mesh_fn(tb, tb["thatch_parts"](root)["underlay"])
    us, vs, good = uv_stats(under)
    check("relief underlay: closed, facing out, UVs in 0..1 the right way round",
          boundary_edges(under) == 0 and signed_volume(under) > 0.0 and min(us) >= 0.0 and max(us) <= 1.0 and
          good > 0.995, "%.2f%% upright" % (good * 100))
    o = build(shape="Cone")
    check("a palm cone (no gables, no hips) builds", o["pieces"] > 50 and o["straw"] and o["underlay"])
    o = build(shape="Lean-to", end_a="Gable", end_b="Hip")
    check("a palm lean-to builds", o["pieces"] > 50)

    # --- the frame: rafters, battens, ridge beam, wall plates under the thatch, its own mesh
    cmds.file(new=True, force=True)
    b = box("frm")
    root = tb["make_thatch_roof"](b, tb["thatch_preset"]("Palm: nipa shingles (neat)"))["root"]
    parts = tb["thatch_parts"](root)
    fr = parts.get("frame")
    check("a roof has a frame mesh of its own (woodFrame), handed to Smart UDIM as ready",
          fr is not None and "woodFrame" in fr and cmds.getAttr(fr + ".visibility") and
          cmds.attributeQuery(tb["UV_READY_ATTR"], node=tb["_log_shape"](fr), exists=True), str(fr))

    def face_sizes(fn):
        return set(fn.getVertices()[0])
    for style in tb["THATCH_FRAME_STYLES"]:
        for subd in (False, True):
            t0 = time.time()
            tb["update_thatch_roofs"]({root: {"frame_style": style, "frame_subd": subd}})
            dt = time.time() - t0
            fn = mesh_fn(tb, fr)
            us, vs, good = uv_stats(fn)
            sizes = face_sizes(fn)
            label = "%s frame%s" % (style, " (Sub-D)" if subd else "")
            check("%s: UVs packed in 0..1, every face the right way round (%.2fs)" % (label, dt),
                  min(us) >= 0.0 and max(us) <= 1.0 and min(vs) >= 0.0 and max(vs) <= 1.0 and good > 0.999,
                  "%.2f%% upright, %d faces" % (good * 100, fn.numPolygons))
            if subd:
                check("%s: all quads, every member closed" % label, sizes == {4} and boundary_edges(fn) == 0,
                      "faces %s, %d open edges" % (sorted(sizes), boundary_edges(fn)))
            elif style != "Sawn":
                check("%s: light (6 sides), every member closed" % label, boundary_edges(fn) == 0 and
                      sizes <= {4, 6} and fn.numVertices < 60000, "%d verts, %s" % (fn.numVertices, sorted(sizes)))
            else:
                check("%s: hard-edged quads" % label, sizes == {4})
    tb["update_thatch_roofs"]({root: {"frame_style": "Bamboo", "frame_subd": False}})
    fbb, sbb = bbox(fr), bbox(parts["straw"])
    check("the frame sits under the thatch, rafters out to the eaves", fbb[4] < sbb[4] - 0.08 and 1.6 < fbb[1] < 2.6,
          "frame y %.2f..%.2f, thatch top %.2f" % (fbb[1], fbb[4], sbb[4]))
    n_wide = mesh_fn(tb, fr).numVertices
    tb["update_thatch_roofs"]({root: {"rafter_spacing": 0.075}})
    check("closer rafters: more of them", mesh_fn(tb, fr).numVertices > n_wide * 1.1,
          "%d -> %d verts" % (n_wide, mesh_fn(tb, fr).numVertices))
    tb["update_thatch_roofs"]({root: {"rafter_spacing": 0.15, "detail": "Proxy"}})
    check("Proxy: no frame (just the shape)", not cmds.getAttr(fr + ".visibility"))
    tb["update_thatch_roofs"]({root: {"detail": "Medium", "frame": False}})
    check("Frame off hides it", not cmds.getAttr(fr + ".visibility"))
    tb["update_thatch_roofs"]({root: {"frame": True, "shape": "Cone"}})
    check("a cone gets a frame (radial rafters, ring battens)", cmds.getAttr(fr + ".visibility") and
          mesh_fn(tb, fr).numPolygons > 1000)
    tb["update_thatch_roofs"]({root: {"shape": "Ridge", "end_a": "Hip", "end_b": "Hip", "style": "Surface"}})
    check("a hipped surface roof gets its frame too (under the shell)", cmds.getAttr(fr + ".visibility") and
          bbox(fr)[4] < bbox(parts["straw"])[4] - 0.1)

    # --- blockers: the thatch bends round boxes (walls, a lower roof) and follows them
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    b = box("blk")
    root = tb["make_thatch_roof"](b, tb["thatch_preset"]("Palm: nipa shingles (neat)"))["root"]

    def roof_pts(r=None):
        out = []
        for part in ("straw", "underlay", "frame"):
            node = tb["thatch_parts"](r or root)[part]
            if cmds.getAttr(node + ".visibility"):  # plain tuples: an MPoint outlives its array badly
                out.extend((q.x, q.y, q.z) for q in mesh_fn(tb, node).getPoints(om.MSpace.kWorld))
        return out

    def inside(pts, node, tol=0.001):
        bx = tb["_th_blocker_box"](node)
        n = 0
        for p in pts:
            d = (p[0] - bx["c"][0], p[1] - bx["c"][1], p[2] - bx["c"][2])
            n += all(abs(sum(d[i] * bx["u"][k][i] for i in range(3))) < bx["h"][k] - tol for k in range(3))
        return n
    n_free = len(roof_pts())
    t0 = time.time()
    wall = tb["create_thatch_blocker"](root)
    dt = time.time() - t0
    check("Add Blocker: a red wireframe box that never renders, selected, blocking the roof",
          cmds.attributeQuery(tb["THATCH_BLOCKER_ATTR"], node=wall, exists=True) and
          not cmds.getAttr(tb["_log_shape"](wall) + ".primaryVisibility") and
          cmds.ls(selection=True, long=True) == [wall] and tb["thatch_blockers"](root) == [wall],
          "%s (%.2fs)" % (wall, dt))
    check("a wall across the gable: nothing goes into it", inside(roof_pts(), wall) == 0,
          "%d of %d points inside" % (inside(roof_pts(), wall), len(roof_pts())))
    check("selecting a blocker picks its roof", (cmds.select(wall) or tb["thatch_selection"]()) == ([root], []))
    cmds.xform(wall, scale=(0.3, 5.0, 2.2), translation=(3.25, 4.0, 1.4), worldSpace=True)  # half the verge
    check("moving a blocker is noticed", tb["thatch_box_moved"](root))
    tb["update_thatch_roofs"]({root: {}})
    pts = roof_pts()
    edge = 3.0 + tb["THATCH_DEFAULTS"]["overhang"] * 4.0
    free = sum(1 for p in pts if p[0] > edge + 0.03 and p[2] < -0.4 and p[1] < 5.0)
    past = sum(1 for p in pts if p[0] > 3.45 and 0.8 < p[2] < 2.2)  # well behind the wall (not round its end)
    check("a wall over half the verge: leaves hang free on the open half, none get past the wall",
          inside(pts, wall) == 0 and free > 50 and past == 0 and not tb["thatch_box_moved"](root),
          "inside %d, free %d, past %d" % (inside(pts, wall), free, past))
    low = box("lowRoof", size=(4.0, 0.3, 2.0), move=(0.0, 1.9, 3.3))
    tb["link_thatch_blockers"]([root], [low])
    pts = roof_pts()
    lying = sum(1 for p in pts if abs(p[0]) < 1.9 and 2.4 < p[2] < 4.2 and 2.05 < p[1] < 2.25)
    check("a lower roof under the eave: the hanging leaves lie down on it, none go into it",
          inside(pts, low) == 0 and lying > 100, "inside %d, lying on it %d" % (inside(pts, low), lying))
    for style in ("Surface", "Planes", "3D Pieces", "Leaf Panels", "Palm Fronds"):
        t0 = time.time()
        tb["update_thatch_roofs"]({root: {"style": style, "underlay": True}})
        dt = time.time() - t0
        pts = roof_pts()
        check("%s with two blockers: nothing inside either (%.2fs)" % (style, dt),
              inside(pts, wall) == 0 and inside(pts, low) == 0 and dt < 6.0,
              "%d / %d inside" % (inside(pts, wall), inside(pts, low)))
    tb["update_thatch_roofs"]({root: {"underlay": False}})
    tb["link_thatch_blockers"]([root], [low], add=False)
    check("Remove: the lower roof stops blocking", tb["thatch_blockers"](root) == [wall])
    cmds.delete(wall)
    check("deleting a blocker is noticed", tb["thatch_box_moved"](root))
    tb["update_thatch_roofs"]({root: {}})
    check("with its blockers gone the roof is whole again", len(roof_pts()) == n_free,
          "%d vs %d points" % (len(roof_pts()), n_free))
    wall = tb["create_thatch_blocker"](root)
    cmds.undo()
    check("undoing Add Blocker removes the box, and the roof sees it", not cmds.objExists(wall) and
          tb["thatch_box_moved"](root))
    tb["update_thatch_roofs"]({root: {}})
    wall = tb["create_thatch_blocker"](root)
    tb["link_thatch_blockers"]([root], [low])
    done, gone = tb["bake_thatch"]([root])
    check("bake removes the blocker the tool made, keeps your own meshes",
          not cmds.objExists(wall) and cmds.objExists(low) and "thatchBlocker0001" in gone, str(gone))
    # blockers through a deformed box: world -> roof space undoes the lattice
    cmds.file(new=True, force=True)
    b = box("warp")
    cmds.move(0, 0.7, 0.4, ["warp.vtx[2]", "warp.vtx[3]"], relative=True)
    f = tb["thatch_frame"](b)
    pts = [(x * 0.7, y * 0.9, z * 0.5) for x in (-3, 0, 2.9) for y in (-0.2, 1.5, 3.1) for z in (-2, 0.3, 2.1)]
    back = tb["_th_to_roof"](f, tb["_th_to_world"](f, (pts, [], [], [], [], []))[0])
    check("a deformed box's lattice is undone exactly for blockers",
          max(abs(a[i] - c_[i]) for a, c_ in zip(pts, back) for i in range(3)) < 1e-6)

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
