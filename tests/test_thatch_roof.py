"""Headless tests for Thatch Roof (mayapy).

    mayapy tests/test_thatch_roof.py

Builds every roof shape and end type in each thatch style and checks: the
shells are closed and face outwards, the roof sits on its box (eaves, ridge,
overhang), UVs are the right way round (in 0..1 for the surface, stacked in
one tile or column per stack for planes / pieces), undo / redo (the redo
rebuilds the seed planes), save / reopen, live edits, following the box,
bake, the Smart UDIM tag and speed.
"""

import json
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


def in_one_tile(us, vs):
    """UVs inside one UDIM tile column (a roof's parts each have their own), V in 0..1."""
    lo = math.floor(min(us) + 1e-6)
    return max(us) <= lo + 1.0 + 1e-6 and min(vs) >= -1e-6 and max(vs) <= 1.0 + 1e-6


def tile_columns(tb, node):
    """The UDIM tile columns a mesh's UVs span (a UV on a tile's edge counts for the tile it's inside)."""
    us = uv_stats(mesh_fn(tb, node))[0]
    return set(range(int(math.floor(min(us) + 1e-6)), int(math.ceil(max(us) - 1e-6))))


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
    bb = cmds.exactWorldBoundingBox(b)
    check("the default box is 6 x 3 x 4 m in decimetres, eaves 2.5 m up",
          [round(v, 3) for v in bb] == [-30.0, 25.0, -20.0, 30.0, 55.0, 20.0], str(bb))
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
    check("bake keeps the meshes, drops the settings and the box", done == [root] and gone == ["roofBox0001"] and
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
    check("seven palm presets, each a whole palm look (Detail and stacks stay yours)", len(palms) == 7 and all(
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
        # the bushy palapa is denser on purpose (two layers of loose fronds over the rows): its own limit
        check("%s: builds at Medium (%.2fs)" % (k, dt), rep["pieces"] > 100 and dt < (10.0 if "bushy" in k else 6.0),
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
    # Edges at their most (droop / length variation, messiness, limp top fronds, ragged eaves): still no gaps
    for k in palms[:2]:
        s = dict(tb["THATCH_DEFAULTS"], **tb["thatch_preset"](k))
        s.update(edge_hang_var=1.0, edge_len_var=1.0, edge_mess=1.0, edge_limp=1.0, ragged=1.5)
        tb["update_thatch_roofs"]({root: s})
        miss = sky_from_inside(tb["thatch_parts"](root)["straw"])
        check("%s, Edges all at 1, Ragged eaves 1.5: no gaps from inside" % k, not miss,
              "%d of %d rays see the sky: %s" % (len(miss), 31 * 31, miss[:5]))

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
    # the user, 2026-11-09: the messy ridge was a sawtooth of folded leaf ends under a pole floating off them.
    # Each ridge leaf drapes over the crest now, and the pole lies on the leaves (pressed in a little), tied down.
    shack = dict(tb["thatch_preset"]("Palm: beach shack (makeshift)"), resolution=80, frame=True, lashings=True)
    sh = build(**shack)
    members = sh["field"].frame_extra
    rpole = max((m for m in members if m["kind"] == "pole"), key=lambda m: abs(m["path"][-1][0] - m["path"][0][0]))
    ties = [m for m in members if m["kind"] == "tie"]
    rp = rpole["r0"]
    centres = tb["_th_to_world"](frame, (rpole["path"],))[0]
    straw = sh["straw"][0]
    gaps, above = [], 0
    for P in centres[len(centres) // 8: -len(centres) // 8]:
        under = [p[1] for p in straw if abs(p[0] - P[0]) < rp and abs(p[2] - P[2]) < 0.7 * rp]
        if under:
            gaps.append((P[1] - rp) - max(under))
            above += max(under) > P[1] + rp
    gaps.sort()
    check("ridge: the pole lies on the cap leaves (no gap under it), none stick up past it, tied down",
          gaps and gaps[len(gaps) // 2] < 0.15 * rp and gaps[-1] < 0.6 * rp and not above and len(ties) >= 6,
          "gap under the pole: median %.2f, worst %.2f pole radii (%d points), %d leaves above it, %d tie turns" % (
              gaps[len(gaps) // 2] / rp if gaps else -1, gaps[-1] / rp if gaps else -1, len(gaps), above, len(ties)))

    # straight wood (the user, 2026-11-10: sticks and poles "super bendy and weird", hips clipping through each
    # other at the ridge; lashings only as an option, off by default)
    plain = build(**dict(shack, lashings=False, hip_poles=True, end_a="Hip", end_b="Hip"))
    wood = plain["field"].frame_extra + plain["field"].stick_members
    check("Lashings off (the default): no ties", not any(m["kind"] == "tie" for m in wood) and
          tb["THATCH_DEFAULTS"]["lashings"] is False and "lashings" in tb["THATCH_LOOK_KEYS"])

    def plan_bow(path):  # most a member strays sideways (in plan) off the line between its ends, / its length
        (x0, _, z0), (x1, _, z1) = path[0], path[-1]
        ln = math.hypot(x1 - x0, z1 - z0)
        if ln < 1e-6:
            return 0.0
        return max(abs((p[0] - x0) * (z1 - z0) - (p[2] - z0) * (x1 - x0)) / ln for p in path) / ln
    bows = sorted(plan_bow(m["path"]) for m in wood if m["kind"] in ("stick", "rachis", "pole") and len(m["path"]) > 2)
    check("sticks, rachis and poles run straight in plan (no wandering with the roof's lumps, none bent round a hip)",
          bows and bows[-1] < 0.02, "worst bow %.4f of its length (%d members)" % (bows[-1] if bows else -1, len(bows)))
    rp_ = [m for m in plain["field"].frame_extra if m["kind"] == "pole" and m.get("rs") == 1.0]
    ridge_ = max(rp_, key=lambda m: abs(m["path"][-1][0] - m["path"][0][0]))
    hips_ = [m for m in rp_ if m is not ridge_]
    r_ = ridge_["r0"]
    butts = [abs(m["path"][0][2]) for m in hips_]  # a hip pole starts at its butt
    past = [max(abs(q[0]) for q in ridge_["path"]) - abs(m["path"][0][0]) for m in hips_]
    check("hips: four hip poles butt against the ridge pole's sides (not through its axis), which runs on past them",
          len(hips_) == 4 and min(butts) > 1.9 * r_ and max(butts) < 2.3 * r_ and min(past) > 0.0,
          "butts %s pole radii off its axis, ridge runs on %s" % (["%.2f" % (b / r_) for b in butts],
                                                                    ["%.2f" % p for p in past]))

    # hold-down poles (the user, 2026-11-10, Brazilian jungle shanties): pairs laid down the slopes over the
    # leaves, tops crossing over the ridge pole, straight, resting on the leaves with the leaves under them
    # pressed flat; off by default
    amz = build(**dict(tb["thatch_preset"]("Palm: Amazon jungle shack"), frame=True, resolution=80))
    am_poles = [m for m in amz["field"].frame_extra if m["kind"] == "pole"]
    am_ridge = max(am_poles, key=lambda m: abs(m["path"][-1][0] - m["path"][0][0]))
    holds = [m for m in am_poles if abs(m["path"][-1][2] - m["path"][0][2]) > abs(m["path"][-1][0] - m["path"][0][0])]
    arp = am_ridge["r0"]
    clear, pressed, rested = [], 0, []
    am_straw = amz["straw"][0]
    for m in holds:
        hr = m["r0"]
        wp = tb["_th_to_world"](frame, (m["path"],))[0]
        # lying on the ridge pole where it crosses it: their axes a radius plus a radius apart
        q = min(am_ridge["path"], key=lambda c: abs(c[0] - m["path"][0][0]))
        near = min(math.hypot(c[1] - q[1], c[2] - q[2]) for c in m["path"][:-1])
        clear.append((near - arp - hr) / hr)
        # in 3D (a sloped pole's underside is further under its axis than its radius): no leaf point inside
        # it, and along its middle the nearest leaf about at its surface
        xs_ = [c[0] for c in wp]
        near = [p for p in am_straw if min(xs_) - 3.0 * hr < p[0] < max(xs_) + 3.0 * hr]
        segs = wp[len(wp) // 4: -2]
        for c0, c1 in zip(segs, segs[1:]):
            ab = [c1[j] - c0[j] for j in range(3)]
            l2 = sum(v * v for v in ab)
            ds = []
            for p in near:
                t_ = sum((p[j] - c0[j]) * ab[j] for j in range(3)) / l2
                if 0.0 <= t_ <= 1.0:
                    d_ = math.sqrt(sum((p[j] - c0[j] - t_ * ab[j]) ** 2 for j in range(3)))
                    if d_ < 3.0 * hr:
                        ds.append(d_)
            if ds:
                pressed += sum(1 for d_ in ds if d_ < 0.9 * hr)
                rested.append((min(ds) - hr) / hr)
    rested.sort()
    hold_bows = [plan_bow(m["path"]) for m in holds]
    check("hold-down poles: off by default; the Amazon shack's 3 pairs are straight, cross over the ridge pole and "
          "rest on the leaves (pressed flat under them)",
          tb["THATCH_DEFAULTS"]["hold_poles"] == 0 and "hold_poles" in tb["THATCH_LOOK_KEYS"] and len(holds) == 6
          and max(hold_bows) < 0.02 and min(clear) > -0.15 and max(clear) < 0.5 and not pressed and rested
          and -0.15 < rested[len(rested) // 2] < 0.6,
          "%d poles, bow %.4f, over the ridge pole by %s radii, %d leaf points inside them, nearest leaf "
          "median %.2f radii off them" % (len(holds), max(hold_bows) if hold_bows else -1,
                                      ["%.2f" % c for c in clear], pressed,
                                      rested[len(rested) // 2] if rested else -99))

    # the frame's parts each have a switch (the user, 2026-11-11): one off takes away only its own members,
    # the rest stay exactly where they were (same crookedness, same cut ends); all off, no frame mesh
    parts = ("frame_rafters", "frame_hips", "frame_beam", "frame_battens", "wall_plates")

    def frame_pts(**over):
        o = build(**dict(dict(style="Planes", end_a="Hip", end_b="Half-hip", frame=True, resolution=40), **over))
        m = o.get("frame")
        return set((round(p[0], 4), round(p[1], 4), round(p[2], 4)) for p in m[0]) if m else set()
    full_pts = frame_pts()
    part_rows = []
    for key in parts:
        less = frame_pts(**{key: False})
        part_rows.append((key, len(less), less < full_pts))
    none_pts = frame_pts(**dict((k, False) for k in parts))
    check("frame parts: each part's switch takes away only that part (the rest unmoved); all off, no frame",
          all(tb["THATCH_DEFAULTS"][k] is True and k in tb["THATCH_LOOK_KEYS"] for k in parts)
          and all(ok for _, _, ok in part_rows) and not none_pts,
          "full %d points; %s; all off %d" % (len(full_pts), ", ".join("%s %d%s" % (k, n, "" if ok else " MOVED")
                                                                     for k, n, ok in part_rows), len(none_pts)))

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
    # Gable edge Flush (a wall at that end): nothing past the verge, fringe and reach or not; leaves still reach it
    fl = build(end_a="Gable", end_b="Gable", verge_a="Flush", end_fronds=1.5, end_reach=0.5, edge_hang=1.5,
               top_layer=1.0)
    fx = [p[0] for p in fl["straw"][0]]
    at_edge = sum(1 for x in fx if x > edge - 0.03)
    check("Gable edge Flush: the + end stops dead at the verge, the - end still hangs",
          max(fx) <= edge + 1e-6 and min(fx) < -edge - 0.15 and at_edge > 500,
          "x %.3f .. %.3f, %d points on the cut" % (min(fx), max(fx), at_edge))
    ux = [p[0] for p in fl["underlay"][0]]
    fr = fl["frame"][0] if fl["frame"] else [(0.0, 0.0, 0.0)]
    check("Gable edge Flush: the underlay and frame stop there too", max(ux) <= edge + 1e-6 and
          max(p[0] for p in fr) <= edge + 0.02, "underlay %.3f, frame %.3f" % (max(ux), max(p[0] for p in fr)))
    hf, hh = build(end_a="Hip", verge_a="Flush"), build(end_a="Hip")
    check("Gable edge only matters on a gable", hf["straw"][0] == hh["straw"][0])
    # Start UDIM: the leaves from there, the other meshes after them, up a row past the 10th tile, none shared
    ud = build(udim=1018, stacks=3)
    tl = ud["udims"]
    flat = [t for v in tl.values() for t in v]

    def corner(mesh):
        return int(math.floor(min(mesh[3]) + 1e-6)), int(math.floor(min(mesh[4]) + 1e-6))
    check("Start UDIM 1018: leaves in 1018-1020, sticks up a row from the same column, then the rest; no tile shared",
          tl.get("straw") == [1018, 1019, 1020] and tl.get("sticks") == [1028, 1029, 1030] and
          corner(ud["straw"]) == (7, 1) and corner(ud["sticks"]) == (7, 2) and len(flat) == len(set(flat)) and
          all(max(ud[p][3]) <= 10.0 + 1e-6 for p in tl), str(tl))
    # two layers at the edges: the limp under layer hangs, the stiff top layer holds its line
    limp, stiff = build(top_layer=0.0, edge_hang=1.5), build(top_layer=0.0, edge_hang=0.0)
    out_limp, out_stiff = max(abs(p[2]) for p in limp["straw"][0]), max(abs(p[2]) for p in stiff["straw"][0])
    check("Edge hang: past the eaves the under layer hangs down instead of reaching out", out_limp < out_stiff - 0.08,
          "reach %.3f vs %.3f" % (out_limp, out_stiff))
    tips = build(top_layer=1.5, end_reach=1.0, edge_hang=1.5)
    check("the top layer sticks out further at the eaves than the hanging under layer",
          max(abs(p[2]) for p in tips["straw"][0]) > max(abs(p[2]) for p in limp["straw"][0]) + 0.05)
    # Edges (the user, 2026-11-11): own controls for the leaves hanging off the eaves and verges; 0 = as before
    base_e = build(end_a="Gable")
    zero_e = build(end_a="Gable", edge_hang_var=0.0, edge_len_var=0.0, edge_mess=0.0, edge_limp=0.0, ragged=0.0)
    check("Edges all 0: the same leaves as before", base_e["straw"] == zero_e["straw"])
    low0 = min(p[1] for p in base_e["straw"][0])
    rag = build(end_a="Gable", ragged=1.5)
    lvar = build(end_a="Gable", edge_len_var=1.0)
    check("Ragged eaves on palm fronds: stretches of the edge hang further down",
          min(p[1] for p in rag["straw"][0]) < low0 - 0.05, "lowest %.3f vs %.3f" % (
              min(p[1] for p in rag["straw"][0]), low0))
    def hang_spread(o):  # how much the points hanging below the eaves differ in height
        ys = [p[1] for p in o["straw"][0] if p[1] < 2.45]
        m = sum(ys) / float(len(ys))
        return (sum((y - m) ** 2 for y in ys) / float(len(ys))) ** 0.5
    check("Hang length variation: the hanging leaves differ more in how far down they reach",
          lvar["straw"][0] != base_e["straw"][0] and hang_spread(lvar) > 1.1 * hang_spread(base_e),
          "spread %.4f vs %.4f" % (hang_spread(lvar), hang_spread(base_e)))
    for key in ("edge_hang_var", "edge_mess"):
        o = build(end_a="Gable", **{key: 1.0})
        check("%s 1 changes the edge leaves, the roof's count stays" % key,
              o["straw"][0] != base_e["straw"][0] and o["pieces"] == base_e["pieces"])
    limp_top = build(top_layer=1.5, end_reach=1.0, edge_hang=1.5, edge_limp=1.0)
    check("Limp top fronds 1: the top layer hangs at the eaves instead of sticking out",
          max(abs(p[2]) for p in limp_top["straw"][0]) < max(abs(p[2]) for p in tips["straw"][0]) - 0.03,
          "reach %.3f vs %.3f" % (max(abs(p[2]) for p in limp_top["straw"][0]), max(abs(p[2]) for p in tips["straw"][0])))

    # wood in the thatch (the user, 2026-11-09: "more accurate interaction with ... all the wood poles and
    # things ... Less clipping, more logic to it"): each top frond lies on the rachis laid under it and its
    # rachis on the leaflets under that; the frame stays under an underlay (none over the crest). Measured as
    # the share of the wood's mesh edges that pass through the leaves / underlay.
    def through(leaves, wood):
        data = om.MFnMeshData().create()
        fn = om.MFnMesh()
        fn.create([om.MPoint(*p) for p in leaves[0]], list(leaves[1]), list(leaves[2]), parent=data)
        acc = fn.autoUniformGridParams()
        edges, i = set(), 0
        for c in wood[1]:
            f = wood[2][i:i + c]
            i += c
            for k in range(c):
                a, b_ = f[k], f[(k + 1) % c]
                edges.add((a, b_) if a < b_ else (b_, a))
        hits = 0
        for a, b_ in edges:
            A, B = wood[0][a], wood[0][b_]
            d = [B[j] - A[j] for j in range(3)]
            ln = math.sqrt(sum(c * c for c in d))
            if ln < 1e-9:
                continue
            r = fn.anyIntersection(om.MFloatPoint(*A), om.MFloatVector(*[c / ln for c in d]), om.MSpace.kObject,
                                   ln, False, accelParams=acc)
            hits += bool(r and r[0] is not None and 1e-6 < r[1] < ln - 1e-6)
        return hits / float(max(1, len(edges)))
    pal = build(**dict(tb["thatch_preset"]("Palm: beach shack (makeshift)"), frame=True, detail="Medium"))
    sticks_in = through(pal["straw"], pal["sticks"])
    check("beach shack: fewer stick / rachis edges pass through the leaves (18% before 2026-11-09)",
          sticks_in < 0.14, "%.1f%%" % (sticks_in * 100))
    straw_kw = dict(tb["thatch_preset"]("Cambodian shack (straw)"), frame=True, detail="Medium", resolution=80)
    v1, v2 = build(**straw_kw), build(**dict(straw_kw, volume=2.0))
    in1, in2 = through(v1["underlay"], v1["frame"]), through(v2["underlay"], v2["frame"])
    check("straw over an underlay: the frame stays under it, at Volume 1 and 2 (1.4% before 2026-11-09)",
          in1 < 0.01 and in2 < 0.01, "%.2f%% / %.2f%%" % (in1 * 100, in2 * 100))

    # Volume (the user, 2026-11-09: "puff them out a little bit and have it still look realistic with an
    # accurate layering"): thicker thatch, more layers, heavier wood, the frame pushed down under it
    s1 = dict(tb["THATCH_DEFAULTS"], style="Planes")
    s2 = tb["_th_volume"](dict(s1, volume=2.0))
    check("Volume 2: twice the thickness and lift, sqrt(2) the density and timber; 1 changes nothing",
          tb["_th_volume"](dict(s1)) == s1 and abs(s2["thickness"] - 2.0 * s1["thickness"]) < 1e-9 and
          abs(s2["lift"] - 2.0 * s1["lift"]) < 1e-9 and abs(s2["density"] - math.sqrt(2.0) * s1["density"]) < 1e-9
          and abs(s2["rafter_size"] - math.sqrt(2.0) * s1["rafter_size"]) < 1e-9 and "volume" in
          tb["THATCH_LOOK_KEYS"])
    top = lambda o, part: max(p[1] for p in o[part][0])  # noqa: E731
    low = lambda o, part: min(p[1] for p in o[part][0] if abs(p[0]) < 1.0 and abs(p[2]) < 0.6)  # noqa: E731
    check("Volume 2 (straw): the thatch stands higher, the frame sits lower under the thicker underlay",
          top(v2, "straw") > top(v1, "straw") + 0.05 and low(v2, "frame") < low(v1, "frame") - 0.05,
          "thatch top %.2f -> %.2f, frame %.2f -> %.2f" % (top(v1, "straw"), top(v2, "straw"), low(v1, "frame"),
                                                            low(v2, "frame")))
    p1, p2 = build(volume=1.0), build(volume=2.0)
    r1 = max(m["r0"] for m in p1["field"].stick_members)
    r2 = max(m["r0"] for m in p2["field"].stick_members)
    check("Volume 2 (palm): the fronds stand off further, the sticks are thicker",
          top(p2, "straw") > top(p1, "straw") + 0.03 and 1.3 < r2 / r1 < 1.5,
          "top %.2f -> %.2f, stick radius x%.2f" % (top(p1, "straw"), top(p2, "straw"), r2 / r1))

    # tied bundles (the user, 2026-11-09: "one stick per level ... they wrap in and out of that and they're
    # sort of just like bunched bits of fronds"): a pole per course, handfuls tied over it, no battens
    def sky_mesh(m, n=30):
        data = om.MFnMeshData().create()
        fn = om.MFnMesh()
        fn.create([om.MPoint(*p) for p in m[0]], list(m[1]), list(m[2]), parent=data)
        acc = fn.autoUniformGridParams()
        return sum(1 for i in range(n + 1) for j in range(n + 1) if not fn.closestIntersection(
            om.MFloatPoint(-2.8 + 5.6 * i / float(n), 2.4, -1.85 + 3.7 * j / float(n)),
            om.MFloatVector(0.0, 1.0, 0.0), om.MSpace.kObject, 100.0, False, accelParams=acc))
    jk = dict(tb["thatch_preset"]("Palm: jungle hut (tied bundles)"), frame=True, detail="Medium", stacks=3,
              lashings=True)
    jg = build(**jk)
    kinds = [m["kind"] for m in jg["field"].frame_extra]
    n_pole, n_tie = kinds.count("pole"), kinds.count("tie")
    check("Bundles: a pole along every course, the bundles lashed to it, no loose rachis over them",
          n_pole >= 8 and n_tie > 2 * n_pole and not any(m["kind"] == "rachis" for m in jg["field"].stick_members) and
          tb["THATCH_FROND_LAYOUTS"] == ("Shingles", "Bundles") and "frond_layout" in tb["THATCH_LOOK_KEYS"],
          "%d poles, %d tie turns" % (n_pole, n_tie))
    xmax = max(p[0] for p in jg["straw"][0])
    check("Bundles: the poles end just past the gable verge (not long stubs)",
          max(q[0] for m in jg["field"].frame_extra for q in m["path"]) < xmax + 0.05,
          "pole end %.2f, leaves %.2f" % (max(q[0] for m in jg["field"].frame_extra for q in m["path"]), xmax))
    jh, jc = build(**dict(jk, end_a="Hip", end_b="Hip")), build(**dict(jk, frond_form="Cards"))
    gaps = (sky_mesh(jg["straw"]), sky_mesh(jh["straw"]), sky_mesh(jc["straw"]))
    check("Bundles on hips and as cards: they build and close the roof", jh["pieces"] > 100 and jc["pieces"] > 100
          and gaps[1] == 0 and gaps[2] == 0, "rays through: gable %d, hips %d, cards %d" % gaps)
    # Shingles: only about one top frond in three shows its rachis (a stick on every course read as a ladder)
    sh = build(**dict(tb["thatch_preset"]("Palm: beach shack (makeshift)"), detail="Medium"))
    n_r = sum(1 for m in sh["field"].stick_members if m["kind"] == "rachis")
    check("Shingles: most top fronds lie with their rachis tucked away, some show it",
          5 < n_r < 0.25 * sh["pieces"], "%d rachis, %d pieces" % (n_r, sh["pieces"]))

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
    check("relief underlay: closed, facing out, UVs in a tile of its own the right way round",
          boundary_edges(under) == 0 and signed_volume(under) > 0.0 and in_one_tile(us, vs) and
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
            fr = tb["thatch_parts"](root)["frame"]  # Sub-D renames it _GES
            fn = mesh_fn(tb, fr)
            us, vs, good = uv_stats(fn)
            sizes = face_sizes(fn)
            label = "%s frame%s" % (style, " (Sub-D)" if subd else "")
            check("%s: UVs packed in a tile of its own, every face the right way round (%.2fs)" % (label, dt),
                  in_one_tile(us, vs) and good > 0.999,
                  "%.2f%% upright, %d faces" % (good * 100, fn.numPolygons))
            if subd:
                check("%s: all quads, every member closed" % label, sizes == {4} and boundary_edges(fn) == 0,
                      "faces %s, %d open edges" % (sorted(sizes), boundary_edges(fn)))
            elif style != "Sawn":
                check("%s: light (6 sides), every member closed" % label, boundary_edges(fn) == 0 and
                      sizes <= {4, 6} and fn.numVertices < 60000, "%d verts, %s" % (fn.numVertices, sorted(sizes)))
            else:  # the ridge pole's ties are round vine: their two end caps the only non-quads
                ties = 2 * sum(1 for m in tb["thatch_build"](tb["thatch_data"](root)["box_frame"],
                                                             tb["thatch_data"](root))["field"].frame_extra
                               if m["kind"] == "tie")
                hexes = sum(1 for c in fn.getVertices()[0] if c == 6)
                check("%s: hard-edged quads (and the round ties' end caps)" % label,
                      sizes <= {4, 6} and hexes == ties, "faces %s, %d six-sided (%d tie caps)" % (
                          sorted(sizes), hexes, ties))
    tb["update_thatch_roofs"]({root: {"frame_subd": True}})
    fr = tb["thatch_parts"](root)["frame"]
    check("Sub-D on: the frame mesh is named _GES", fr.endswith("_GES"), fr)
    tb["update_thatch_roofs"]({root: {"frame_subd": False}})
    fr = tb["thatch_parts"](root)["frame"]
    check("Sub-D off: back to _GEP", fr.endswith("_GEP"), fr)
    tb["update_thatch_roofs"]({root: {"frame_style": "Bamboo", "frame_subd": False, "ridge_poles": False}})
    fbb, sbb = bbox(fr), bbox(parts["straw"])  # (no ridge pole: it rides on top of the cap)
    check("the frame sits under the thatch, rafters out to the eaves", fbb[4] < sbb[4] - 0.08 and 1.6 < fbb[1] < 2.6,
          "frame y %.2f..%.2f, thatch top %.2f" % (fbb[1], fbb[4], sbb[4]))
    tb["update_thatch_roofs"]({root: {"ridge_poles": True}})
    n_wide = mesh_fn(tb, fr).numVertices
    tb["update_thatch_roofs"]({root: {"rafter_spacing": 0.05}})
    check("closer rafters: more of them", mesh_fn(tb, fr).numVertices > n_wide * 1.1,
          "%d -> %d verts" % (n_wide, mesh_fn(tb, fr).numVertices))
    tb["update_thatch_roofs"]({root: {"rafter_spacing": 0.15, "detail": "Proxy"}})
    check("Proxy: no frame (just the shape)", not cmds.getAttr(fr + ".visibility"))
    tb["update_thatch_roofs"]({root: {"detail": "Medium", "frame": False}})
    check("Frame off hides it", not cmds.getAttr(fr + ".visibility"))
    tb["update_thatch_roofs"]({root: {}})
    d = tb["thatch_data"](root)
    check("Frame off stays off through a rebuild (the box's frame is stored apart)",
          not cmds.getAttr(fr + ".visibility") and d["frame"] is False and isinstance(d["box_frame"], dict))
    d["frame"] = d.pop("box_frame")  # how roofs were saved before
    cmds.setAttr(root + "." + tb["THATCH_SETTINGS"], __import__("json").dumps(d), type="string")
    d = tb["thatch_data"](root)
    check("an older roof: its box frame moves across, Frame is read off its hidden frame mesh",
          d["frame"] is False and isinstance(d["box_frame"], dict) and not tb["thatch_box_moved"](root))
    tb["update_thatch_roofs"]({root: {"frame": True, "shape": "Cone"}})
    check("a cone gets a frame (radial rafters, ring battens)", cmds.getAttr(fr + ".visibility") and
          mesh_fn(tb, fr).numPolygons > 1000)
    tb["update_thatch_roofs"]({root: {"shape": "Ridge", "end_a": "Hip", "end_b": "Hip", "style": "Surface"}})
    check("a hipped surface roof gets its frame too (under the shell)", cmds.getAttr(fr + ".visibility") and
          bbox(fr)[4] < bbox(parts["straw"])[4] - 0.1)

    # --- the frame follows the roof's shape; battens: every course / fewer / per level
    check("no overhang by default: the roof is the box", tb["THATCH_DEFAULTS"]["overhang"] == 0.0 and
          all(tb["thatch_preset"](k)["overhang"] == 0.0 for k in tb["THATCH_PRESETS"]))
    tb["update_thatch_roofs"]({root: dict(tb["thatch_preset"]("Palm: nipa shingles (neat)"), detail="Medium")})

    def frame_top(x0, x1):
        return max(q.y for q in mesh_fn(tb, fr).getPoints(om.MSpace.kWorld) if x0 < q.x < x1)
    mid0, end0 = frame_top(-0.3, 0.3), frame_top(2.0, 2.6)
    tb["update_thatch_roofs"]({root: {"ridge_sag": 1.5}})
    mid1, end1 = frame_top(-0.3, 0.3), frame_top(2.0, 2.6)
    check("ridge sag drags the frame's ridge down with the thatch", mid0 - mid1 > 0.15 and mid0 - mid1 > end0 - end1,
          "middle %.3f -> %.3f, near the end %.3f -> %.3f" % (mid0, mid1, end0, end1))
    nv = {}
    for mode in tb["THATCH_BATTENS"]:
        tb["update_thatch_roofs"]({root: {"ridge_sag": 0.0, "levels": 3, "lip": 0.4, "battens": mode}})
        nv[mode] = mesh_fn(tb, fr).numVertices
    check("battens: every course > every 2nd > every 3rd > one per level", nv["Every course"] > nv["Every 2nd"] >
          nv["Every 3rd"] > nv["Per level"], str(nv))
    s = dict(tb["THATCH_DEFAULTS"], **tb["thatch_preset"]("Palm: nipa shingles (neat)"))
    s.update(levels=3, lip=0.4)
    F = tb["ThatchField"](3.0, 2.0, 3.0, s)
    t_first = tb["_th_frond_courses"](F, s)[0]
    ts = tb["_th_palm_courses"](F, s, 1.0)
    dt_ = tb["_th_frond_courses"](F, s)[1]
    bottoms = tb["_th_level_bottoms"](F)
    check("with levels, every level starts a fresh palm course at its bottom step",
          any(abs(c - (bottoms[0] + t_first - F.t_low)) < 1e-9 for c in ts) and
          all(any(abs(c - (b_ + 0.25 * dt_)) < 1e-9 for c in ts) for b_ in bottoms[1:]), "%d courses" % len(ts))
    # 3D leaflets are solids, and the sticks are closed members; poles go to the frame
    tb["update_thatch_roofs"]({root: {"levels": 1, "lip": 0.0, "battens": "Every 2nd", "frond_form": "3D Leaflets",
                                      "end_fronds": 0.0}})
    fn = mesh_fn(tb, parts["straw"])
    check("3D Leaflets with a thickness: every leaflet a closed solid facing out",
          boundary_edges(fn) == 0 and signed_volume(fn) > 0.0, "%d open edges" % boundary_edges(fn))
    # the sticks and rachis are wood: a mesh of their own (woodStick), not on the leaves' mesh
    sk = parts.get("sticks")
    sfn = mesh_fn(tb, sk) if sk else None
    s_us, s_vs, _ = uv_stats(sfn) if sfn else ([0.0], [0.0], 0)
    l_us = uv_stats(fn)[0]
    check("sticks and rachis: their own mesh (woodStick, stacked UVs u 0..1), every one capped, none on the leaves",
          sk and "woodStick" in tb["short_name"](sk) and cmds.getAttr(sk + ".visibility") and
          boundary_edges(sfn) == 0 and sfn.numPolygons > 500 and max(s_us) - math.floor(min(s_us) + 1e-6) <= tb["thatch_data"](root)["stacks"] + 1e-6 and
          cmds.getAttr(tb["_log_shape"](sk) + "." + tb["UV_STACKED_ATTR"]) and
          not any(0.875 < (u - math.floor(u)) < 1.0 for u in l_us),
          "%s, %d faces, u %.2f..%.2f" % (sk, sfn.numPolygons if sfn else 0, min(s_us), max(s_us)))
    shown = [p for p in ("straw", "sticks", "underlay", "frame") if p in parts and
             cmds.getAttr(parts[p] + ".visibility")]
    cols = dict((p, tile_columns(tb, parts[p])) for p in shown)
    clash = [(a, b_) for i, a in enumerate(shown) for b_ in shown[i + 1:] if cols[a] & cols[b_]]
    check("each of the roof's meshes in UDIM tiles of its own (no UVs overlap across them)",
          len(shown) >= 3 and not clash, "%s, clashes %s" % (dict((p, sorted(c)) for p, c in cols.items()), clash))
    tb["update_thatch_roofs"]({root: {"leaf_thickness": 0.0}})
    check("thickness 0: single-sided leaflets again", boundary_edges(mesh_fn(tb, parts["straw"])) > 0)
    tb["update_thatch_roofs"]({root: {"frond_form": "Leaflets", "leaf_thickness": 0.0006}})
    with_frame = mesh_fn(tb, parts["sticks"]).numPolygons
    tb["update_thatch_roofs"]({root: {"frame": False}})
    check("ridge / hip poles sit in the frame's mesh (with the sticks without a frame)",
          mesh_fn(tb, parts["sticks"]).numPolygons > with_frame,
          "%d -> %d stick faces" % (with_frame, mesh_fn(tb, parts["sticks"]).numPolygons))
    # the user, 2026-11-02: the poles look like they float on the cap; turning them off mustn't open the ridge
    capped = [tuple(q) for q in mesh_fn(tb, parts["straw"]).getPoints()]
    tb["update_thatch_roofs"]({root: {"ridge_poles": False}})
    bare = [tuple(q) for q in mesh_fn(tb, parts["straw"]).getPoints()]
    check("Ridge and hip poles off: only the poles go (the cap leaves, sticks and rachis stay exactly)",
          mesh_fn(tb, parts["sticks"]).numPolygons == with_frame and bare == capped,
          "%d stick faces (%d without poles), %d / %d leaf points" % (
              mesh_fn(tb, parts["sticks"]).numPolygons, with_frame, len(bare), len(capped)))
    d = tb["thatch_data"](root)
    d.pop("ridge_poles")
    d["sticks"] = False
    cmds.setAttr(root + "." + tb["THATCH_SETTINGS"], json.dumps(d), type="string")
    check("an older roof with Sticks off keeps its poles off", tb["thatch_data"](root)["ridge_poles"] is False)
    d["sticks"] = True
    cmds.setAttr(root + "." + tb["THATCH_SETTINGS"], json.dumps(d), type="string")
    check("and with Sticks on, on", tb["thatch_data"](root)["ridge_poles"] is True)
    d["version"] = 5  # built before the poles switch and the layered cap leaves
    cmds.setAttr(root + "." + tb["THATCH_SETTINGS"], json.dumps(d), type="string")
    check("a roof built before the poles switch and messy cap leaves (version 5) is flagged for Upgrade",
          tb["THATCH_VERSION"] >= 6 and tb["thatch_needs_upgrade"](root))
    d["version"] = tb["THATCH_VERSION"]
    cmds.setAttr(root + "." + tb["THATCH_SETTINGS"], json.dumps(d), type="string")
    tb["update_thatch_roofs"]({root: {"frame": True, "ridge_poles": True}})
    # upgrade an old roof in place
    cmds.undoInfo(state=True, infinity=True)
    cmds.delete(fr)
    data = tb["thatch_data"](root)
    data["version"] = 2
    cmds.setAttr(root + "." + tb["THATCH_SETTINGS"], __import__("json").dumps(data), type="string")
    check("a roof from an older version is spotted", tb["thatch_needs_upgrade"](root))
    done, rep = tb["upgrade_thatch_roofs"]([root])
    parts = tb["thatch_parts"](root)
    check("Upgrade adds the frame mesh, keeps the settings and stamps the version", done == [root] and
          "frame" in parts and cmds.getAttr(parts["frame"] + ".visibility") and not tb["thatch_needs_upgrade"](root)
          and tb["thatch_data"](root)["frond_form"] == "Leaflets")
    cmds.undo()
    check("one Ctrl+Z takes the added mesh away again", "frame" not in tb["thatch_parts"](root))

    # --- Curl: leaves and straw planes bent across their width
    def curl_build(**over):
        s = dict(tb["THATCH_DEFAULTS"], style="Palm Fronds", resolution=80, top_layer=0.0, ridge_fronds=False,
                 end_fronds=0.0, sticks=False, curl_var=0.0)
        s.update(over)
        return tb["thatch_build"](tb["thatch_frame"](tb["thatch_box"](root)), s)["straw"]

    def uv_up(mesh):
        pts_, counts, conn, us_, vs_, uvi = mesh
        k = good = tot = 0
        for c_ in counts:
            ids = uvi[k:k + c_]
            k += c_
            a = sum(us_[ids[i]] * vs_[ids[(i + 1) % c_]] - us_[ids[(i + 1) % c_]] * vs_[ids[i]] for i in range(c_))
            if abs(a) > 1e-14:
                tot += 1
                good += a > 0
        return good / float(max(1, tot))
    flat, arched = curl_build(curl=0.0), curl_build(curl=0.6)
    check("Curl: leaflets get columns across them (3 at Medium), UVs still the right way round",
          len(arched[0]) > 1.4 * len(flat[0]) and uv_up(arched) > 0.999 and
          max(arched[3]) <= 1.0 + 1e-6, "%d -> %d verts, %.2f%% upright" % (len(flat[0]), len(arched[0]),
                                                                             uv_up(arched) * 100))
    hero = curl_build(curl=0.6, detail="High")
    check("High / Hero: 5 columns across a curled leaflet", len(hero[0]) > len(arched[0]) * 1.3)
    pl0, pl1 = curl_build(style="Planes", curl=0.0), curl_build(style="Planes", curl=-0.8)
    check("Curl on straw planes (cupped): more columns, UVs upright, same stack square",
          len(pl1[0]) > 1.4 * len(pl0[0]) and uv_up(pl1) > 0.999 and abs(min(pl1[3])) < 1e-6 and
          abs(max(pl1[3]) - 1.0) < 1e-6)
    pa0, pa1 = curl_build(style="Leaf Panels", curl=0.0), curl_build(style="Leaf Panels", curl=1.0)
    moved = max(max(abs(a[i] - b_[i]) for i in range(3)) for a, b_ in zip(pa0[0], pa1[0]))
    check("Curl on leaf panels: a gentle arch, same topology", len(pa0[0]) == len(pa1[0]) and 0.005 < moved < 0.2,
          "%.3f m" % moved)

    # --- Dried: the top layer's leaflets shrunk, folded, coiled, rolled and crumpled
    class _Flat(object):
        blockers = []
        block_gap = 0.0
    dl_line = [(0.1 * k, 0.0, 0.0) for k in range(7)]
    up_ = [(0.0, 1.0, 0.0)] * 7
    rnd = [0.5, 0.5, 0.95, 0.5, 0.5, 0.2, 0.3, 0.6, 0.1, 0.4, 0.7, 0.25]
    Q2, N2, h2, tw2, vv2, roll2, wr2 = tb["_th_dry_leaf"](_Flat(), dl_line, up_, [1.0] * 7, [0.0] * 7, 1.5, rnd, 3)
    length = sum(math.sqrt(sum((Q2[k][i] - Q2[k - 1][i]) ** 2 for i in range(3))) for k in range(1, len(Q2)))
    dl_reach = math.sqrt(sum((Q2[-1][i] - Q2[0][i]) ** 2 for i in range(3)))
    check("a dried leaflet keeps its length, folds and coils up off the roof (never into it), more rows",
          abs(length - 0.6) < 0.01 and dl_reach < 0.45 and min(q[1] for q in Q2) > -1e-6 and len(Q2) > 7 and
          len(vv2) == len(h2) == len(tw2) == len(roll2) == len(Q2) and abs(vv2[0] - 1.0) < 1e-9 and
          abs(vv2[-1]) < 1e-9 and roll2[-1] > roll2[0] > 0.0,
          "length %.3f, tip %.3f from the base, %d rows, lowest %.4f" % (length, dl_reach, len(Q2),
                                                                        min(q[1] for q in Q2)))
    fr_ = tb["thatch_frame"](tb["thatch_box"](root))

    def dry_build(**over):
        s = dict(tb["THATCH_DEFAULTS"], **tb["thatch_preset"]("Palm: palapa (hipped, messy top)"))
        s.update(resolution=80, dried=0.0)
        s.update(over)
        return tb["thatch_build"](fr_, s)["straw"]
    a_, b_ = dry_build(top_layer=0.0, ridge_fronds=False), dry_build(top_layer=0.0, ridge_fronds=False, dried=2.0)
    check("Dried leaves the neat under layer alone", a_[0] == b_[0])
    c0_, c1_ = dry_build(frond_form="Cards"), dry_build(frond_form="Cards", dried=1.0)
    check("Cards ignore Dried (an alpha card can't coil)", c0_[0] == c1_[0])
    t0 = time.time()
    d0_, d1_ = dry_build(), dry_build(dried=1.0)
    dt = time.time() - t0
    check("Dried 1: the top layer changes, a few more rows (not a heavy roof), UVs upright and in the stack "
          "(%.2fs for both)" % dt, d0_[0] != d1_[0] and 1.0 < len(d1_[0]) / float(len(d0_[0])) < 1.8 and
          uv_up(d1_) > 0.999 and min(d1_[3]) >= -1e-6 and dt < 8.0,
          "%d -> %d verts, %.2f%% upright" % (len(d0_[0]), len(d1_[0]), uv_up(d1_) * 100))
    check("Dried is repeatable (same seed, same leaves)", dry_build(dried=1.0)[0] == d1_[0])
    tb["update_thatch_roofs"]({root: {"frond_form": "3D Leaflets", "dried": 1.5, "dried_var": 1.0}})
    parts = tb["thatch_parts"](root)
    fn = mesh_fn(tb, parts["straw"])
    miss = sky_from_inside(parts["straw"])
    check("Dried 1.5, 3D Leaflets: still closed solids facing out, still no gaps from inside",
          boundary_edges(fn) == 0 and signed_volume(fn) > 0.0 and not miss,
          "%d open edges, %d rays see the sky" % (boundary_edges(fn), len(miss)))
    tb["update_thatch_roofs"]({root: {"frond_form": "Leaflets", "dried": 0.0, "dried_var": 0.6}})

    # --- Leaflet shape (the user, 2026-11-11: crinkle, twist, width variation, bent tips)
    shape_keys = tb["THATCH_LEAF_SHAPE_KEYS"]
    check("Leaflet shape: look keys, all off by default", all(k in tb["THATCH_LOOK_KEYS"] for k in shape_keys) and
          not tb["_th_leaf_shape_settings"](tb["THATCH_DEFAULTS"]))
    z0 = dry_build(**dict((k, tb["THATCH_DEFAULTS"][k]) for k in shape_keys))
    s_old = dict(tb["THATCH_DEFAULTS"], **tb["thatch_preset"]("Palm: palapa (hipped, messy top)"))
    s_old.update(resolution=80, dried=0.0)
    for k in shape_keys:
        s_old.pop(k)
    z1 = tb["thatch_build"](fr_, s_old)["straw"]
    check("Leaflet shape 0 builds exactly what a roof without the settings builds", z0[0] == z1[0] and z0[3] == z1[3])
    full = dict(crinkle=2.0, crinkle_var=1.0, leaf_twist=2.0, leaf_twist_var=1.0, width_var=1.0, width_wobble=1.0,
                bent_tips=1.0, bent_var=1.0)
    t0 = time.time()
    lf = dry_build(stacks=3, **full)
    dt = time.time() - t0
    frac = [u - math.floor(u) for u in lf[3] if u - math.floor(u) < 0.9999]
    check("Leaflet shape at its most: builds (%.2fs), UVs upright and inside each stack's strip" % dt,
          lf[0] != z0[0] and uv_up(lf) > 0.999 and max(frac) <= 0.8701 and min(lf[3]) >= -1e-6 and dt < 8.0,
          "%d -> %d verts, %.2f%% upright, widest u %.4f" % (len(z0[0]), len(lf[0]), uv_up(lf) * 100, max(frac)))
    check("Leaflet shape is repeatable (same seed, same leaves)", dry_build(stacks=3, **full)[0] == lf[0])
    for form in ("Rolled", "Creased", "Mixed"):  # the leaflets' cross-section (the user: "thinner curled tubes,
        sec_ = dry_build(stacks=3, leaf_section=form, section_amount=1.5, section_var=1.0)  # or flatter, pinched")
        frac = [u - math.floor(u) for u in sec_[3] if u - math.floor(u) < 0.9999]
        check("Cross-section %s at its most: changes the leaves, UVs upright and inside the strip" % form,
              sec_[0] != z0[0] and uv_up(sec_) > 0.999 and max(frac) <= 0.8701,
              "%d -> %d verts, %.2f%% upright, widest u %.4f" % (len(z0[0]), len(sec_[0]), uv_up(sec_) * 100,
                                                                max(frac)))
    check("Cross-section As is (any amount) builds exactly as before",
          dry_build(leaf_section="As is", section_amount=1.5)[0] == dry_build()[0])
    for pk in ("Palm: nipa shingles (neat)", "Palm: jungle hut (tied bundles)"):
        for form in ("Rolled", "Creased"):
            tb["update_thatch_roofs"]({root: dict(tb["thatch_preset"](pk), resolution=100, leaf_section=form,
                                                  section_amount=1.5, section_var=1.0, **full)})
            miss = sky_from_inside(tb["thatch_parts"](root)["straw"])
            check("Leaflet shape at its most (%s), %s: still no gaps from inside" % (form, pk), not miss,
                  "%d rays see the sky: %s" % (len(miss), miss[:5]))
    tb["update_thatch_roofs"]({root: dict([(k, tb["THATCH_DEFAULTS"][k]) for k in shape_keys] +
                                          [("leaf_section", "As is")])})

    # --- Shag and Cap leaf width (the user, 2026-11-11: a bushy palapa, shaggy, not "wet hair")
    check("Shag and Cap leaf width: look keys, off by default",
          all(k in tb["THATCH_LOOK_KEYS"] for k in ("shag", "cap_width", "hip_blend")) and
          tb["THATCH_DEFAULTS"]["shag"] == 0.0 and tb["THATCH_DEFAULTS"]["cap_width"] == 0.0 and
          tb["THATCH_DEFAULTS"]["hip_blend"] == 0.0)
    s_old = dict(tb["THATCH_DEFAULTS"], **tb["thatch_preset"]("Palm: palapa (hipped, messy top)"))
    s_old.update(resolution=80, dried=0.0)
    s_old.pop("shag")
    s_old.pop("cap_width")
    s_old.pop("hip_blend")
    s_old.pop("flow")
    for k_ in ("pokes", "poke_lift", "poke_clump", "tip_shape", "tip_var"):
        s_old.pop(k_)
    check("Shag, Cap leaf width and Hip blend 0 build exactly what a roof without them builds",
          dry_build(shag=0.0, cap_width=0.0, hip_blend=0.0, flow=0.0)[0] == tb["thatch_build"](fr_, s_old)["straw"][0])
    sh_, base_ = dry_build(shag=1.5), dry_build()
    check("Shag stands the leaves off the roof", sh_[0] != base_[0])
    check("Cap leaf width changes the cap leaves", dry_build(cap_width=0.01)[0] != base_[0])
    check("Hip blend changes the hip cap leaves", dry_build(hip_blend=1.0)[0] != base_[0])
    check("Flow round hips: a look key, 0 by default, changes the leaves",
          "flow" in tb["THATCH_LOOK_KEYS"] and tb["THATCH_DEFAULTS"]["flow"] == 0.0 and
          dry_build(flow=1.0)[0] != base_[0])
    check("Fronds poking out: look keys, none by default, lift some top fronds",
          all(k in tb["THATCH_LOOK_KEYS"] for k in ("pokes", "poke_lift", "poke_clump")) and
          tb["THATCH_DEFAULTS"]["pokes"] == 0 and dry_build(pokes=4, poke_clump=1.0)[0] != base_[0])
    check("Tip shape and variation: look keys, 0 by default, change the top leaflets",
          all(k in tb["THATCH_LOOK_KEYS"] for k in ("tip_shape", "tip_var")) and
          tb["THATCH_DEFAULTS"]["tip_shape"] == 0.0 and dry_build(tip_shape=0.8, tip_var=0.5)[0] != base_[0])
    tb["update_thatch_roofs"]({root: dict(tb["thatch_preset"]("Palm: bushy palapa (shaggy)"), resolution=100)})
    miss = sky_from_inside(tb["thatch_parts"](root)["straw"])
    check("Bushy palapa preset: builds, no gaps from inside", not miss, "%d rays see the sky: %s" % (len(miss), miss[:5]))
    tb["update_thatch_roofs"]({root: dict(tb["thatch_preset"]("Palm: palapa (hipped, messy top)"), resolution=100)})

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
    low = box("lowRoof", size=(4.0, 0.3, 2.0), move=(0.0, 1.9, 3.0))  # just under the eave (no overhang)
    tb["link_thatch_blockers"]([root], [low])
    pts = roof_pts()
    lying = sum(1 for p in pts if abs(p[0]) < 1.9 and 2.0 < p[2] < 4.0 and 2.05 < p[1] < 2.25)
    check("a lower roof under the eave: the hanging leaves lie down on it, none go into it",
          inside(pts, low) == 0 and lying > 40, "inside %d, lying on it %d" % (inside(pts, low), lying))
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
          not cmds.objExists(wall) and cmds.objExists(low) and "roofBlocker0001" in gone, str(gone))
    # blockers through a deformed box: world -> roof space undoes the lattice
    cmds.file(new=True, force=True)
    b = box("warp")
    cmds.move(0, 0.7, 0.4, ["warp.vtx[2]", "warp.vtx[3]"], relative=True)
    f = tb["thatch_frame"](b)
    pts = [(x * 0.7, y * 0.9, z * 0.5) for x in (-3, 0, 2.9) for y in (-0.2, 1.5, 3.1) for z in (-2, 0.3, 2.1)]
    back = tb["_th_to_roof"](f, tb["_th_to_world"](f, (pts, [], [], [], [], []))[0])
    check("a deformed box's lattice is undone exactly for blockers",
          max(abs(a[i] - c_[i]) for a, c_ in zip(pts, back) for i in range(3)) < 1e-6)

    # --- quick roof shape from points: eave corners + peaks -> box, ridge, ends, hip pitch
    shape = tb["thatch_shape_from_points"]
    rect = [(-3, 3, -2), (3, 3, -2), (3, 3, 2), (-3, 3, 2)]
    sh = shape(rect + [(-1.2, 5.5, 0), (1.2, 5.5, 0)])
    s_ = sh["settings"]
    check("points: a ridge short of both ends is hipped, the pitch from where it stops",
          s_["shape"] == "Ridge" and s_["end_a"] == s_["end_b"] == "Hip" and abs(s_["hip_pitch"] - 2.0 / 1.8) < 1e-6,
          str(s_))
    s_ = shape(rect + [(-3, 5.5, 0), (3, 5.5, 0)])["settings"]
    check("points: a ridge reaching both ends is gabled", s_["end_a"] == s_["end_b"] == "Gable", str(s_))
    s_ = shape(rect + [(3, 5.5, 0), (-1, 5.5, 0)])["settings"]
    check("points: gable at one end, hip at the other", sorted((s_["end_a"], s_["end_b"])) == ["Gable", "Hip"] and
          abs(s_["hip_pitch"] - 1.0) < 1e-6, str(s_))
    s_ = shape(rect + [(0, 5.5, 0)])["settings"]
    check("points: one apex makes a pyramid (hips meeting)", s_["end_a"] == s_["end_b"] == "Hip" and
          abs(s_["hip_pitch"] - 2.0 / 3.0) < 1e-6, str(s_))
    sh = shape(rect + [(-3, 5.5, -2), (3, 5.5, -2)])
    check("points: peaks along one edge make a lean-to, high on that side", sh["settings"]["shape"] == "Lean-to")
    ring = [(2.5 * math.cos(a_ * math.pi / 4), 3.0, 2.5 * math.sin(a_ * math.pi / 4)) for a_ in range(8)]
    check("points: eave points round a circle and an apex make a cone",
          shape(ring + [(0, 6, 0)])["settings"]["shape"] == "Cone")
    ang = math.radians(30)

    def rot(p):
        return (p[0] * math.cos(ang) - p[2] * math.sin(ang), p[1], p[0] * math.sin(ang) + p[2] * math.cos(ang))
    sh = shape([rot(p) for p in rect] + [rot((0, 5.5, -1.5)), rot((0, 5.5, 1.5))])  # the ridge across the short way
    a_ = sh["a"]
    check("points: the ridge runs the way the peaks do (here across the footprint), at any rotation",
          abs(abs(a_[0] * -math.sin(ang) + a_[2] * math.cos(ang)) - 1.0) < 1e-6 and
          sh["settings"]["end_a"] == "Hip", "a %s, %s" % (str(a_), sh["settings"]))
    try:
        shape([(0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 0, 1)])
        flat_ok = False
    except ValueError:
        flat_ok = True
    check("points: all at one height is refused with a reason", flat_ok)
    # the scene side: box and roof in one Ctrl+Z, the ridge through the peaks (off-centre too)
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    t0 = time.time()
    rep, bx, info = tb["thatch_roof_from_points"](rect + [(-1.0, 5.5, 0.6), (1.0, 5.5, 0.6)],
                                                  {"style": "Surface", "resolution": 60})
    dt = time.time() - t0
    straw = tb["thatch_parts"](rep["root"])["straw"]
    pts = [(q.x, q.y, q.z) for q in mesh_fn(tb, straw).getPoints(om.MSpace.kWorld)]
    top = max(p_[1] for p_ in pts)
    ridge_z = [p_[2] for p_ in pts if p_[1] > top - 0.05]
    bb = bbox(straw)
    check("from points: a box and a roof on the footprint, the ridge through the (off-centre) peaks (%.2fs)" % dt,
          abs(sum(ridge_z) / len(ridge_z) - 0.6) < 0.15 and 5.45 < top < 5.5 + 0.5 and abs(bb[0] + 3.0) < 0.3 and
          abs(bb[3] - 3.0) < 0.3 and tb["thatch_data"](rep["root"])["end_a"] == "Hip",
          "ridge z %.2f, top %.2f, x %.2f..%.2f" % (sum(ridge_z) / len(ridge_z), top, bb[0], bb[3]))
    check("the box is a proper thatch box (wireframe, never renders) that the roof follows",
          cmds.attributeQuery(tb["THATCH_BOX_ATTR"], node=bx, exists=True) and tb["thatch_box"](rep["root"]) == bx)
    cmds.undo()
    check("one Ctrl+Z removes box and roof", not cmds.objExists(bx) and not cmds.objExists(rep["root"]))
    # from a selection: a gable blockout's vertices
    v = [(-3, 3, -2), (3, 3, -2), (3, 3, 2), (-3, 3, 2), (-3, 5, 0), (3, 5, 0)]
    blk = cmds.polyCreateFacet(point=[v[0], v[1], v[5], v[4]], name="blockout", constructionHistory=False)[0]
    cmds.select("%s.vtx[*]" % blk)
    pts = tb["thatch_selected_points"]()
    pts += [(3, 3, 2), (-3, 3, 2)]  # the other slope's eave corners (a one-face blockout)
    rep2, bx2, info2 = tb["thatch_roof_from_points"](pts, {"resolution": 40, "style": "Surface"})
    check("from selected vertices: a gable blockout becomes a gabled roof", info2["settings"]["end_a"] == "Gable" and
          info2["settings"]["end_b"] == "Gable", str(info2["settings"]))

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

    # --- your own presets (an optionVar: Maya's prefs, every scene)
    var = tb["THATCH_PRESET_VAR"]
    old = cmds.optionVar(q=var) if cmds.optionVar(exists=var) else None
    try:
        mine = dict(D, style="Planes", levels=2, density=0.4, seed=77, ridge="X", detail="Hero")
        tb["thatch_save_preset"]("test hut", mine)
        p = tb["thatch_preset"]("test hut")
        check("a saved preset keeps the look, not the seed, ridge or detail", p["style"] == "Planes" and
              p["levels"] == 2 and p["density"] == 0.4 and not [k for k in ("seed", "ridge", "detail") if k in p],
              str(sorted(p))[:120])
        tb["thatch_save_preset"]("test hut", dict(mine, levels=3))
        check("saving under the same name overwrites it", tb["thatch_preset"]("test hut")["levels"] == 3)
        data = tb["thatch_user_presets"]()
        del data["test hut"]["dried"]
        cmds.optionVar(stringValue=(var, json.dumps(data)))
        check("a preset saved before a setting existed gets its default",
              tb["thatch_preset"]("test hut")["dried"] == D["dried"])
        check("built-in presets still load", tb["thatch_preset"]("Tiered")["levels"] == 4)
        check("delete removes it", tb["thatch_delete_preset"]("test hut") and
              tb["thatch_preset"]("test hut") is None and not tb["thatch_delete_preset"]("test hut"))
    finally:
        if old is None:
            cmds.optionVar(remove=var)
        else:
            cmds.optionVar(stringValue=(var, old))

    # --- Duplicate Roof, linked roofs, Ctrl+D copies
    cmds.file(new=True, force=True)
    data = tb["thatch_data"]
    tbox = tb["create_thatch_box"]()
    r1 = tb["make_thatch_roof"](tbox, {"resolution": 40, "levels": 2})["root"]
    rep = tb["duplicate_thatch_roof"](r1, link=True)
    r2, b2 = rep["root"], rep["box"]
    check("Duplicate Roof: a new roof on a new box beside the original", r2 != r1 and b2 != tbox and
          tb["thatch_box"](r2) == b2 and tb["thatch_box"](r1) == tbox and bbox(r2)[0] > bbox(r1)[3] and
          not tb["thatch_box_moved"](r2), "%s %s" % (r2, b2))
    diff = [(k, data(r1)[k], data(r2)[k]) for k in tb["THATCH_KEYS"]
            if data(r1)[k] != data(r2)[k]]
    check("the copy has the same settings and a new seed", [d[0] for d in diff] == ["seed"], str(diff))
    check("the new box is selected, a tool box", cmds.ls(selection=True, long=True) == [b2] and
          cmds.attributeQuery(tb["THATCH_BOX_ATTR"], node=b2, exists=True))
    check("Duplicate with link: the two are linked", tb["thatch_linked"](r1) == [r2] and
          tb["thatch_linked"](r2) == [r1])
    cmds.undo()
    check("one Ctrl+Z undoes Duplicate Roof (and the link)", not cmds.objExists(r2) and not cmds.objExists(b2) and
          "link" not in data(r1) and cmds.objExists(tbox))
    rep = tb["duplicate_thatch_roof"](r1, link=True)
    r2, b2 = rep["root"], rep["box"]
    cmds.setAttr(b2 + ".scaleX", cmds.getAttr(b2 + ".scaleX") * 0.6)
    tb["update_thatch_roofs"]({r2: {}})
    rep = tb["update_thatch_roofs"]({r1: {"levels": 3, "lumps": 0.9, "end_a": "Gable"}})
    check("a shared setting changed on one linked roof rebuilds the other", sorted(rep["done"]) == sorted([r1, r2])
          and data(r2)["levels"] == 3 and data(r2)["lumps"] == 0.9, str(rep["done"]))
    check("each keeps its own ends and box size", data(r1)["end_a"] == "Gable" and data(r2)["end_a"] == "Hip" and
          data(r2)["box_frame"]["L"] < 0.7 * data(r1)["box_frame"]["L"])
    rep = tb["update_thatch_roofs"]({r1: {"seed": 5}})
    check("the seed is each roof's own", rep["done"] == [r1] and data(r2)["seed"] != 5)
    rep = tb["update_thatch_roofs"]({r1: {}})
    check("a plain rebuild leaves linked roofs alone", rep["done"] == [r1])
    b3 = tb["create_thatch_box"]()
    cmds.move(0, 0, 80, b3, relative=True)
    r3 = tb["make_thatch_roof"](b3, {"resolution": 40, "levels": 1, "lumps": 0.1})["root"]
    rep = tb["link_thatch_roofs"]([r3, r1])
    check("Link: the first roof's look goes to the rest, and their links join in",
          sorted(rep["linked"]) == sorted([r1, r2, r3]) and data(r1)["levels"] == data(r2)["levels"] == 1 and
          data(r2)["lumps"] == 0.1 and sorted(tb["thatch_linked"](r3)) == sorted([r1, r2]) and
          data(r1)["end_a"] == "Gable", str(rep["done"]))
    check("Unlink takes a roof out; the rest stay linked", tb["unlink_thatch_roofs"]([r2]) == [r2] and
          tb["thatch_linked"](r2) == [] and tb["thatch_linked"](r1) == [r3])
    tb["update_thatch_roofs"]({r1: {"levels": 2}})
    check("an unlinked roof keeps its settings", data(r2)["levels"] == 1 and data(r3)["levels"] == 2)

    # Ctrl+D on a roof group copies its box uuid: the copy gets its own box where it's moved to
    cp = cmds.ls(cmds.duplicate(r2)[0], long=True)[0]
    check("a Ctrl+D copy is found", tb["thatch_copies"]() == {cp: r2}, str(tb["thatch_copies"]()))
    cmds.move(0, 0, -80, cp, relative=True)
    cmds.rotate(0, 30, 0, cp, relative=True)
    before = bbox(tb["thatch_parts"](cp)["straw"])
    tb["update_thatch_roofs"]({cp: {}})
    after = bbox(tb["thatch_parts"](cp)["straw"])
    nb = tb["thatch_box"](cp)
    check("rebuilding a Ctrl+D copy gives it its own box; it stays where it was moved",
          nb and nb != b2 and tb["thatch_box"](r2) == b2 and not tb["thatch_copies"]() and
          max(abs(a - b) for a, b in zip(before, after)) < 0.05 and not tb["thatch_box_moved"](cp),
          "%s %s" % (str(before), str(after)))
    cmds.undo()  # the box it was given (the rebuild itself isn't undoable)
    check("one Ctrl+Z takes that box back", not cmds.objExists(nb) and tb["thatch_copies"]() == {cp: r2})
    cmds.delete(cp)
    nboxes = len(cmds.ls("*." + tb["THATCH_BOX_ATTR"], objectsOnly=True))
    cps = cmds.duplicate([r3, b3], returnRootsOnly=True)
    cp, cb = [cmds.ls(n, long=True)[0] for n in cps]
    cmds.move(60, 0, 0, cp, cb, relative=True)
    tb["update_thatch_roofs"]({cp: {}})
    check("Ctrl+D on a roof and its box together: the copy takes the copied box",
          tb["thatch_box"](cp) == cb and tb["thatch_box"](r3) == b3 and
          len(cmds.ls("*." + tb["THATCH_BOX_ATTR"], objectsOnly=True)) == nboxes + 1)
    cmds.delete(cp, cb)
    d = data(r3)
    del d["self"]  # a roof made before roofs remembered their uuid
    cmds.setAttr(r3 + "." + tb["THATCH_SETTINGS"], json.dumps(d), type="string")
    cp = cmds.ls(cmds.duplicate(r3)[0], long=True)[0]
    check("an older roof's Ctrl+D copy: the original is the one Maya didn't renumber",
          tb["thatch_copies"]() == {cp: r3}, str(tb["thatch_copies"]()))

    # --- Make Box Again: a roof whose box was deleted (kept out of a publish) gets it back where it was
    for name, shape in (("tapered, turned", "taper"), ("mirrored", "mirror"), ("not a box, ridge Z", "cyl")):
        cmds.file(new=True, force=True)
        if shape == "cyl":
            b = cmds.ls(cmds.polyCylinder(r=2, h=3, name="notABox", constructionHistory=False)[0], long=True)[0]
            cmds.move(5, 4, -2, b)
            s = {"resolution": 40, "ridge": "Z"}
        else:
            b = box("b", rot=(0.0, 35.0, 0.0))
            if shape == "mirror":
                cmds.scale(-6, 3, 4, b)
            else:
                cmds.move(0, 0.7, 0.4, ["%s.vtx[2]" % b, "%s.vtx[3]" % b], relative=True)
            s = {"resolution": 40, "end_a": "Gable"}
        root = tb["make_thatch_roof"](b, s)["root"]
        stored = data(root)["box_frame"]
        before = bbox(tb["thatch_parts"](root)["straw"])
        check("Make Box Again (%s): leaves a roof that still has its box alone" % name,
              tb["remake_thatch_boxes"]([root]) == [])
        cmds.delete(b)
        rep = tb["update_thatch_roofs"]({root: {}})
        made = tb["remake_thatch_boxes"]([root])
        nb = made[0][1] if made else None
        new_f = tb["thatch_frame"](nb, data(root).get("ridge", "Auto")) if nb else None
        if shape == "cyl":  # a plain box now, with the frame the cylinder had
            same = new_f and tb["_th_same_frame"](dict(new_f, corners=None, axis=None), stored)
        else:
            same = tb["_th_same_frame"](new_f, stored) and new_f["flip"] == stored["flip"]
        check("Make Box Again (%s): a linked box with the old box's exact frame, selected" % name,
              rep["lost"] == [root] and made == [(root, nb)] and same and tb["thatch_box"](root) == nb and
              cmds.ls(selection=True, long=True) == [nb] and
              cmds.attributeQuery(tb["THATCH_BOX_ATTR"], node=nb, exists=True), "%s %s" % (rep["lost"], made))
        tb["update_thatch_roofs"]({root: {}})
        after = bbox(tb["thatch_parts"](root)["straw"])
        check("Make Box Again (%s): rebuilt on it, the roof doesn't move" % name,
              max(abs(p - q) for p, q in zip(before, after)) < 1e-3 and not tb["thatch_box_moved"](root),
              "%s %s" % (before, after))
        if shape == "taper":
            cmds.move(3, 0, 0, nb, relative=True)
            rep = tb["update_thatch_roofs"]({root: {}})
            moved = bbox(tb["thatch_parts"](root)["straw"])
            check("Make Box Again: moving the new box moves the roof", rep["done"] == [root] and
                  abs(moved[0] - after[0] - 3.0) < 1e-3, "%.3f" % (moved[0] - after[0]))
            cmds.delete(nb)
            made = tb["remake_thatch_boxes"]([root])
            nb = made[0][1]
            cmds.undo()
            check("one Ctrl+Z undoes Make Box Again", not cmds.objExists(nb) and not tb["thatch_box"](root) and
                  data(root).get("box_frame"))

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
