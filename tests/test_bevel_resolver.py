"""Headless tests for the Bevel Resolver (Modeling tab).

    mayapy tests/test_bevel_resolver.py

Builds the meshes a chamfer-off bevel leaves n-gons on (a wall with window
recesses, a box with a boss, a single bevelled cube edge, two windows whose
chamfers sit side by side), resolves them and checks: no n-gons left, the
original vertices didn't move, poles stay few and off the bevel strips, and
one Ctrl+Z restores the mesh exactly.
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


def load_toolbox():
    ns = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    return ns


# ----------------------------------------------------------------- helpers
def dag(node):
    sel = om.MSelectionList()
    sel.add(node)
    return sel.getDagPath(0)


def state(node):
    fn = om.MFnMesh(dag(node))
    counts, conn = fn.getVertices()
    return list(counts), list(conn), [(p.x, p.y, p.z) for p in fn.getPoints()]


def sides(node):
    hist = {}
    for c in om.MFnMesh(dag(node)).getVertices()[0]:
        hist[c] = hist.get(c, 0) + 1
    return hist


def ngons(node):
    return sum(n for c, n in sides(node).items() if c > 4)


def faces_where(node, pred):
    it = om.MItMeshPolygon(dag(node))
    out = []
    while not it.isDone():
        if pred(it.center()):
            out.append(it.index())
        it.next()
    return out


def edges_where(node, pred):
    it = om.MItMeshEdge(dag(node))
    out = []
    while not it.isDone():
        if pred(it.point(0), it.point(1)):
            out.append("%s.e[%d]" % (node, it.index()))
        it.next()
    return out


def full(node):
    return cmds.ls(node, long=True)[0]


# ------------------------------------------------------------ test meshes
def wall(windows=(0.0,), which="vertical", seg=2, chamfer=False):
    """6 x 4 wall (5 x 3 grid), window recesses at the given x centres.
    which: 'vertical' / 'top' window edges get the bevel (open chains, so
    the bevel ends on the flat wall)."""
    w = cmds.polyCube(w=6, h=4, d=0.4, sx=5, sy=3, sz=1, name="wall")[0]
    fs = faces_where(w, lambda c: c.z > 0.19 and abs(c.y) < 0.1 and any(abs(c.x - x) < 0.1 for x in windows))
    cmds.polyExtrudeFacet(["%s.f[%d]" % (w, f) for f in fs], ltz=-0.15, keepFacesTogether=False)

    def rim(a, b):
        if not (abs(a.z - 0.2) < 1e-4 and abs(b.z - 0.2) < 1e-4 and abs(a.y) < 0.7 and abs(b.y) < 0.7):
            return False
        for x in windows:
            if abs(a.x - x) < 0.61 and abs(b.x - x) < 0.61:
                vertical = abs(a.x - b.x) < 1e-3
                return vertical if which == "vertical" else (not vertical and a.y > 0)
        return False

    cmds.polyBevel3(edges_where(w, rim), segments=seg, chamfer=chamfer, offset=0.08, offsetAsFraction=False)
    return full(w)


def boss():
    """Box with a square boss; only the boss's four vertical edges bevelled."""
    c = cmds.polyCube(w=4, h=1, d=4, sx=3, sz=3, name="boss")[0]
    top = faces_where(c, lambda p: abs(p.y - 0.5) < 1e-4 and abs(p.x) < 0.1 and abs(p.z) < 0.1)
    cmds.polyExtrudeFacet("%s.f[%d]" % (c, top[0]), ltz=0.6)
    cmds.polyBevel3(edges_where(c, lambda a, b: max(abs(a.x), abs(a.z), abs(b.x), abs(b.z)) < 0.7
                                and abs(a.y - b.y) > 0.3), segments=2, chamfer=False, offset=0.08,
                    offsetAsFraction=False)
    return full(c)


def cube_edge(seg):
    c = cmds.polyCube(w=2, h=2, d=2, sx=2, sy=2, sz=2, name="cubeEdge")[0]
    cmds.polyBevel3(c + ".e[0]", segments=seg, chamfer=False, offset=0.15, offsetAsFraction=False)
    return full(c)


def frame_wall(cells, which="sides", seg=2):
    """8 x 4 wall of 1-unit cells with protruding window frames, like the
    user's reference: each window cell is inset into a frame ring that is
    pushed out (the frames of neighbouring cells merge into a mullion), and
    the centre pushed in. which: 'sides' bevels the vertical frame-to-wall
    edges, 'frontsides' the frames' vertical front edges, 'both' every
    frame-to-wall and front border edge."""
    w = cmds.polyCube(w=8, h=4, d=0.4, sx=8, sy=4, sz=1, name="frameWall")[0]
    centres = [faces_where(w, lambda c, cx=cx, cy=cy: c.z > 0.19 and abs(c.x - (cx - 3.5)) < 0.1
                           and abs(c.y - (cy - 1.5)) < 0.1)[0] for cx, cy in cells]
    cmds.polyExtrudeFacet(["%s.f[%d]" % (w, f) for f in centres], offset=0.15, ltz=0, keepFacesTogether=False)
    ring = [f for f in faces_where(w, lambda c: c.z > 0.19 and any(
        abs(c.x - (cx - 3.5)) < 0.5 and abs(c.y - (cy - 1.5)) < 0.5 for cx, cy in cells)) if f not in centres]
    cmds.polyExtrudeFacet(["%s.f[%d]" % (w, f) for f in ring], ltz=0.08, keepFacesTogether=True)
    cmds.polyExtrudeFacet(["%s.f[%d]" % (w, f) for f in centres], ltz=-0.2, keepFacesTogether=False)

    def border(p):
        return any(abs(abs(p.x - (cx - 3.5)) - 0.5) < 1e-3 and abs(p.y - (cy - 1.5)) < 0.5 + 1e-3 or
                   abs(abs(p.y - (cy - 1.5)) - 0.5) < 1e-3 and abs(p.x - (cx - 3.5)) < 0.5 + 1e-3 for cx, cy in cells)

    def pick(a, b):
        if not (border(a) and border(b)):
            return False
        base = abs(a.z - 0.2) < 1e-4 and abs(b.z - 0.2) < 1e-4
        front = abs(a.z - 0.28) < 1e-4 and abs(b.z - 0.28) < 1e-4
        vertical = abs(a.x - b.x) < 1e-4
        return {"sides": base and vertical, "frontsides": front and vertical, "both": base or front}[which]

    cmds.polyBevel3(edges_where(w, pick), segments=seg, chamfer=False, offset=0.15, offsetAsFraction=True)
    return full(w)


def window_grid(cols, rows):
    """Wall with cols x rows windows (every other cell, wall all round),
    vertical rims bevelled."""
    W, H = cols * 2 + 1, rows * 2 + 1
    w = cmds.polyCube(w=W * 1.0, h=H * 1.0, d=0.4, sx=W, sy=H, sz=1, name="facade")[0]
    fs = faces_where(w, lambda c: c.z > 0.19 and int(round(c.x + W / 2.0 - 0.5)) % 2 == 1
                     and int(round(c.y + H / 2.0 - 0.5)) % 2 == 1)
    cmds.polyExtrudeFacet(["%s.f[%d]" % (w, f) for f in fs], ltz=-0.15, keepFacesTogether=False)
    rim = edges_where(w, lambda a, b: abs(a.z - 0.2) < 1e-4 and abs(b.z - 0.2) < 1e-4 and abs(a.x - b.x) < 1e-4
                      and int((a.y + b.y) / 2 + H / 2.0) % 2 == 1 and max(abs(a.x), abs(b.x)) < W / 2.0 - 0.5)
    cmds.polyBevel3(rim, segments=2, chamfer=False, offset=0.08, offsetAsFraction=False)
    return full(w)


# ------------------------------------------------------------------- tests
def resolve_case(tb, label, mesh, expect_faces=None, max_poles_per_end=2, ends=None):
    """Resolve one mesh and run the common checks. Returns the report."""
    before = state(mesh)
    found_before = ngons(mesh)
    report = tb["resolve_bevel_ngons"]({mesh: None})[mesh]
    after = state(mesh)
    check("%s: every bevel n-gon resolved" % label, ngons(mesh) == 0 and report["resolved"] == report["found"]
          and report["found"] == found_before, "%s -> %s, report %s" % (found_before, sides(mesh), report))
    check("%s: original vertices didn't move" % label, after[2][:len(before[2])] == before[2])
    if expect_faces is not None:
        check("%s: face count" % label, len(after[0]) == expect_faces, "%d (want %d)" % (len(after[0]), expect_faces))
    if ends:
        check("%s: few new poles (<= %d per bevel end)" % (label, max_poles_per_end),
              report["poles"] <= max_poles_per_end * ends, "%d poles for %d ends" % (report["poles"], ends))
    cmds.undo()
    check("%s: one Ctrl+Z restores the mesh exactly" % label, state(mesh) == before)
    cmds.redo()
    check("%s: redo works" % label, ngons(mesh) == 0)
    return report


def test_planning(tb):
    splits = tb["_br_splits"]
    check("quad splits of a hexagon / octagon / decagon", [len(splits(n)) for n in (6, 8, 10)] == [3, 12, 55])
    t0 = time.time()
    n16 = len(splits(16))
    check("16-sided split table is quick", n16 == 7752 and time.time() - t0 < 1.0, "%d in %.2fs" % (n16, time.time() - t0))


def test_wall(tb):
    cmds.file(new=True, force=True)
    mesh = wall()
    topo = tb["BevelTopology"](dag(mesh))
    targets = tb["bevel_ngons"](topo)
    check("wall: finds the 12 n-gons around the two bevel ends", len(targets) == 12 and ngons(mesh) == 12,
          str(sides(mesh)))
    plain = tb["bevel_ngons"](topo, scope="All n-gons")
    check("wall: 'All n-gons' scope agrees here", sorted(plain) == sorted(targets))
    dry = tb["resolve_bevel_ngons"]({mesh: None}, dry_run=True)[mesh]
    check("wall: Select N-gons (dry run) changes nothing", ngons(mesh) == 12 and len(dry["targets"]) == 12
          and not dry["unresolved"])
    report = resolve_case(tb, "wall with a window", mesh, expect_faces=70, ends=4)
    check("wall: no new pole on the wall-side bevel strips' long edges",
          report["strip_poles"] <= 4, str(report))
    # The face below the window held both chamfer tips: they should be joined
    # straight across (the chamfers merge), not fanned to a far corner.
    fn = om.MFnMesh(dag(mesh))
    pts = fn.getPoints()
    tips = [i for i, p in enumerate(pts) if abs(p.z - 0.2) < 1e-4 and abs(abs(p.x) - 0.6) < 1e-3
            and abs(p.y + 0.76) < 0.02]
    it = om.MItMeshVertex(dag(mesh))
    joined = False
    if len(tips) == 2:
        it.setIndex(tips[0])
        joined = tips[1] in list(it.getConnectedVertices())
    check("wall: chamfer tips under the window are joined (merge)", joined, str(tips))


def test_top_only(tb):
    cmds.file(new=True, force=True)
    resolve_case(tb, "wall, top edge only (V cuts)", wall(which="top"), ends=2, max_poles_per_end=4)


def test_side_by_side(tb):
    cmds.file(new=True, force=True)
    resolve_case(tb, "two windows side by side", wall(windows=(-1.2, 1.2)), ends=8)


def test_protruding_frames(tb):
    # The user's reference: frames pushed out of a gridded wall, bevel loops
    # ending on the wall around them. Two frames side by side share a mullion.
    for cells, which, seg in (([(1, 1)], "sides", 2), ([(1, 1)], "sides", 3), ([(1, 1), (3, 1)], "both", 3),
                              ([(1, 1), (2, 1)], "sides", 2), ([(1, 1), (2, 1)], "sides", 3),
                              ([(1, 1), (2, 1)], "frontsides", 3)):
        cmds.file(new=True, force=True)
        label = "protruding frame%s (%s, %d seg)" % ("s side by side" if len(cells) == 2 and cells[1][0] == 2
                                                     else "s" if len(cells) == 2 else "", which, seg)
        resolve_case(tb, label, frame_wall(cells, which, seg))
    # Side by side: both chamfer corners above the mullion run up to one shared
    # vertex on the mullion's vertical loop (the "V" in the user's sketch).
    cmds.file(new=True, force=True)
    mesh = frame_wall([(1, 1), (2, 1)], "sides", 2)
    tb["resolve_bevel_ngons"]({mesh: None})
    fn = om.MFnMesh(dag(mesh))
    pts = fn.getPoints()
    corners = [i for i, p in enumerate(pts) if abs(p.z - 0.2) < 1e-4 and abs(p.y - 0.04) < 0.02
               and min(abs(p.x + 3), abs(p.x + 1)) < 1e-3]
    it = om.MItMeshVertex(dag(mesh))
    reach = []
    for v in corners:
        it.setIndex(v)
        reach.append(set(it.getConnectedVertices()))
    apex = set.intersection(*reach) if len(reach) == 2 else set()
    apex = [v for v in apex if abs(pts[v].x + 2) < 1e-3 and pts[v].y > 0.05]
    check("side-by-side frames: chamfer corners meet at one vertex above the mullion (V)", len(apex) == 1,
          "corners %s, apex %s" % (corners, [(round(pts[v].x, 2), round(pts[v].y, 2)) for v in apex]))


def test_boss(tb):
    cmds.file(new=True, force=True)
    mesh = boss()
    report = resolve_case(tb, "boss with bevelled sides", mesh, ends=8)
    # The boss top had all four support loops ending on it: they should carry
    # straight across (grid), adding no poles at all.
    check("boss: support loops carried across the top, no poles", report["poles"] == 0, str(report))


def test_cube_edges(tb):
    for seg in (1, 2, 3):
        cmds.file(new=True, force=True)
        resolve_case(tb, "single cube edge, %d segment(s)" % seg, cube_edge(seg), ends=2)
    cmds.file(new=True, force=True)
    c = cmds.polyCube(w=2, h=2, d=2, sx=2, sy=2, sz=2, name="cubeChamfer")[0]
    cmds.polyBevel3(c + ".e[0]", segments=1, chamfer=True, offset=0.15, offsetAsFraction=False)
    resolve_case(tb, "chamfer-on bevel works too", full(c), ends=2)


def test_selection(tb):
    cmds.file(new=True, force=True)
    mesh = wall()
    # One vertex at the lower-left chamfer end: only the n-gons around it change.
    fn = om.MFnMesh(dag(mesh))
    pts = fn.getPoints()
    v = [i for i, p in enumerate(pts) if abs(p.x + 0.68) < 0.01 and abs(p.y + 0.667) < 0.01 and abs(p.z - 0.2) < 1e-3]
    cmds.select("%s.vtx[%d]" % (mesh, v[0]))
    items = tb["bevel_selection"]()
    report = tb["resolve_bevel_ngons"](items)[mesh]
    check("component selection: resolves just the n-gons there", report["found"] == 2 and report["resolved"] == 2
          and ngons(mesh) == 10, "%s, %s" % (report, sides(mesh)))
    cmds.undo()
    check("component selection: undo", ngons(mesh) == 12)
    cmds.select(cmds.group(mesh, name="grp"))
    check("selecting a group picks up the meshes under it", list(tb["bevel_selection"]().values()) == [None])


def test_reports(tb):
    cmds.file(new=True, force=True)
    cyl = full(cmds.polyCylinder(sx=24, sy=1, sc=0, name="cyl24")[0])
    plain = full(cmds.polyCube(name="plain")[0])
    cap = full(cmds.polyCylinder(sx=12, sy=1, sc=0, name="cyl12")[0])
    holed = full(cmds.polyCreateFacet(p=[(0, 0, 0), (4, 0, 0), (4, 0, 4), (2, 0, 5), (0, 0, 4), (),
                                         (1, 0, 1), (1, 0, 2), (2, 0, 2), (2, 0, 1)], name="holed")[0])
    report = tb["resolve_bevel_ngons"]({cyl: None, plain: None, cap: None, holed: None}, scope="All n-gons")
    check("24-sided caps are reported, not mangled",
          sorted(report[cyl]["unresolved"].values()) == ["too_many", "too_many"] and sides(cyl).get(24) == 2,
          str(report[cyl]))
    check("12-sided caps split into quads (All n-gons)", ngons(cap) == 0 and report[cap]["resolved"] == 2)
    check("a face with a hole is reported", list(report[holed]["unresolved"].values()) == ["holed"])
    check("a mesh without n-gons is left alone", report[plain]["found"] == 0 and sides(plain) == {4: 6})
    sel = cmds.ls(selection=True, flatten=True) or []
    check("unresolved faces end up selected", any("cyl24" in s for s in sel) and any("holed" in s for s in sel),
          str(sel[:6]))
    cmds.undo()
    check("several meshes: one Ctrl+Z for all of them", ngons(cap) == 2)
    cmds.file(new=True, force=True)
    bevelled = full(cmds.polyCube(name="noBevel", sx=2)[0])
    cmds.polyDelEdge(bevelled + ".e[1]", cleanVertices=False)  # an n-gon with no bevel strip near it
    report = tb["resolve_bevel_ngons"]({bevelled: None})[bevelled]
    check("'Bevel n-gons' ignores n-gons away from any bevel", report["found"] == 0 and ngons(bevelled) > 0,
          str(sides(bevelled)))


def test_speed(tb):
    cmds.file(new=True, force=True)
    mesh = window_grid(6, 4)
    n = ngons(mesh)
    t0 = time.time()
    report = tb["resolve_bevel_ngons"]({mesh: None})[mesh]
    dt = time.time() - t0
    check("facade with 24 windows: resolved", report["resolved"] == report["found"] and ngons(mesh) == 0,
          "%d n-gons, report %s" % (n, {k: report[k] for k in ("found", "resolved", "unresolved")}))
    check("facade with 24 windows: fast", dt < 3.0, "%.2fs for %d n-gons" % (dt, n))


def run():
    tb = load_toolbox()
    for test in (test_planning, test_wall, test_top_only, test_side_by_side, test_protruding_frames, test_boss,
                 test_cube_edges,
                 test_selection, test_reports, test_speed):
        try:
            test(tb)
        except Exception:
            traceback.print_exc()
            RESULTS.append((test.__name__, False, "exception"))


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
