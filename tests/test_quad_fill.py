"""Headless tests for Quad Fill (mayapy).

    mayapy tests/test_quad_fill.py

Square, rectangular, uneven and odd holes in a grid; a hole in a sphere
(the fill must follow its curvature) and round its pole; a cylinder's open
end (closes flat) and a hole in its side (follows the round). Every fill is
all quads (one triangle on odd holes), manifold, wound like the mesh, with
continuous loops; the mesh keeps its node, name, uuid, attributes,
material and history state; one Ctrl+Z puts it back; the preview is never
saved; and it's quick.
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


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def load_toolbox():
    ns = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    return ns


def shape_of(node):
    return cmds.listRelatives(node, shapes=True, fullPath=True, noIntermediate=True)[0]


def fn_of(node):
    sel = om.MSelectionList()
    sel.add(shape_of(node))
    return om.MFnMesh(sel.getDagPath(0))


def points(node):
    return [(p.x, p.y, p.z) for p in fn_of(node).getPoints(om.MSpace.kWorld)]


def counts(node):
    fn = fn_of(node)
    return fn.numVertices, fn.numEdges, fn.numPolygons


def border_edges(node):
    sel = om.MSelectionList()
    sel.add(shape_of(node))
    it = om.MItMeshEdge(sel.getDagPath(0))
    out = []
    while not it.isDone():
        if it.onBoundary():
            out.append(it.index())
        it.next()
    return out


def pick_edge(node, test):
    """Select the first border edge whose midpoint passes test(x, y, z)."""
    fn = fn_of(node)
    for e in border_edges(node):
        a, b = fn.getEdgeVertices(e)
        pa, pb = fn.getPoint(a, om.MSpace.kWorld), fn.getPoint(b, om.MSpace.kWorld)
        if test((pa.x + pb.x) / 2, (pa.y + pb.y) / 2, (pa.z + pb.z) / 2):
            cmds.select("%s.e[%d]" % (node, e), replace=True)
            return e
    raise RuntimeError("no border edge found")


def face_sizes(node, faces):
    fn = fn_of(node)
    return [len(fn.getPolygonVertices(f)) for f in faces]


def new_faces(before, node):
    return list(range(before, fn_of(node).numPolygons))


def winding_ok(node):
    """Every edge with two faces is run in opposite directions by them."""
    fn = fn_of(node)
    seen = {}
    for f in range(fn.numPolygons):
        vs = list(fn.getPolygonVertices(f))
        for i in range(len(vs)):
            key = (vs[i], vs[(i + 1) % len(vs)])
            if key in seen:
                return False
            seen[key] = f
    return True


def manifold_ok(node):
    return not (cmds.polyInfo(node, nonManifoldEdges=True) or cmds.polyInfo(node, nonManifoldVertices=True)
                or cmds.polyInfo(node, laminaFaces=True))


def interior_valence(node, faces):
    """Valence of the new vertices strictly inside the fill."""
    fn = fn_of(node)
    sel = om.MSelectionList()
    sel.add(shape_of(node))
    vit = om.MItMeshVertex(sel.getDagPath(0))
    verts = set()
    for f in faces:
        verts.update(fn.getPolygonVertices(f))
    out = {}
    for v in verts:
        vit.setIndex(v)
        if not vit.onBoundary():
            fs = set(vit.getConnectedFaces())
            if fs <= set(faces):
                out[v] = len(vit.getConnectedEdges())
    return out


def folded_corners(node, faces):
    """Corners of the new faces that fold back (or are under ~3 degrees)
    against Maya's own vertex normal there."""
    fn = fn_of(node)
    bad = 0
    for f in faces:
        vs = list(fn.getPolygonVertices(f))
        k = len(vs)
        for i in range(k):
            a, b, c = [om.MVector(fn.getPoint(x)) for x in (vs[i - 1], vs[i], vs[(i + 1) % k])]
            u, w = b - a, c - b
            nb = fn.getVertexNormal(vs[i], True)
            if (u ^ w) * om.MVector(nb) <= 0.05 * u.length() * w.length():
                bad += 1
    return bad


def common_checks(tag, node, nf0, expect_tris=0):
    faces = new_faces(nf0, node)
    sizes = face_sizes(node, faces)
    check("%s: all quads" % tag, sizes.count(4) == len(sizes) - expect_tris and sizes.count(3) == expect_tris,
          "%d faces, sizes %s" % (len(sizes), sorted(set(sizes))))
    check("%s: hole closed" % tag, not border_edges(node) or tag.startswith("plane"),
          "%d border edges left" % len(border_edges(node)))
    check("%s: manifold" % tag, manifold_ok(node))
    check("%s: winding matches the mesh" % tag, winding_ok(node))
    bad = folded_corners(node, faces)
    check("%s: no folded corners" % tag, not bad, "%d folded" % bad)
    return faces


def plane(name, n=8, size=8.0):
    return cmds.polyPlane(w=size, h=size, sx=n, sy=n, name=name, constructionHistory=False)[0]


def cell_faces(n, cells):
    return ["f[%d]" % (j * n + i) for i, j in cells]


def main():
    tb = load_toolbox()
    quad_fill, qf_plan, qf_read, qf_selection = tb["quad_fill"], tb["qf_plan"], tb["qf_read"], tb["qf_selection"]
    cmds.undoInfo(state=True, infinity=True)

    # ------------------------------------------------ square hole in a grid
    cmds.file(new=True, force=True)
    p = plane("squareHole")
    cmds.delete(["%s.%s" % (p, f) for f in cell_faces(8, [(3, 3), (4, 3), (3, 4), (4, 4)])])
    nf0 = fn_of(p).numPolygons
    pick_edge(p, lambda x, y, z: abs(x) < 1.5 and abs(z) < 1.5)
    report = quad_fill(settings={"smooth": 0.0})
    faces = common_checks("plane square", p, nf0)
    check("square: 2 x 2 grid", len(faces) == 4 and report["plans"][0]["A"] == 2, tb["qf_describe"](report["plans"][0]))
    centre = points(p)[-1]
    check("square: centre vertex back in the middle", max(abs(c) for c in centre) < 1e-4, str(centre))
    check("square: new faces selected", len(cmds.ls(sl=True, fl=True)) == 4)

    # ------------------------------------------- rectangle: the grid it lost
    cmds.file(new=True, force=True)
    p = plane("rectHole")
    orig = points(p)
    cells = [(i, j) for i in range(2, 6) for j in range(3, 5)]  # 4 x 2 faces
    cmds.delete(["%s.%s" % (p, f) for f in cell_faces(8, cells)])
    nf0 = fn_of(p).numPolygons
    nv0 = fn_of(p).numVertices
    pick_edge(p, lambda x, y, z: abs(x) < 3 and abs(z) < 2)
    report = quad_fill()
    faces = common_checks("plane rectangle", p, nf0)
    plan = report["plans"][0]
    check("rectangle: 4 x 2 grid at the real corners", sorted((plan["A"], plan["B"])) == [2, 4] and len(faces) == 8,
          tb["qf_describe"](plan))
    pts = points(p)
    lost = [q for q in orig if abs(q[0]) < 1.9 and abs(q[2]) < 0.9]
    err = max(min(math.sqrt(sum((a - b) ** 2 for a, b in zip(q, r))) for r in pts[nv0:]) for q in lost)
    check("rectangle: interior vertices land on the old grid", err < 1e-3 and len(pts) - nv0 == len(lost),
          "max error %.2g, %d new verts" % (err, len(pts) - nv0))
    val = interior_valence(p, faces)
    check("rectangle: no poles (loops run straight across)", val and all(v == 4 for v in val.values()), str(val))

    # ------------------------------------------- uneven: corners that don't match
    cmds.file(new=True, force=True)
    p = plane("unevenHole", n=10, size=10.0)
    cells = [(i, j) for i in range(3, 7) for j in range(3, 6)] + [(7, 4), (5, 6), (6, 6)]
    cmds.delete(["%s.%s" % (p, f) for f in cell_faces(10, cells)])
    nf0 = fn_of(p).numPolygons
    pick_edge(p, lambda x, y, z: abs(x) < 3 and abs(z) < 3)
    report = quad_fill()
    faces = common_checks("plane uneven", p, nf0)
    check("uneven: a concave border gets a ring (two faces at every border vertex)",
          report["plans"][0]["rings"] == 1, tb["qf_describe"](report["plans"][0]))
    cmds.undo()
    for opt in ({"offset": 1}, {"offset": 3}, {"span": 1}, {"span": -2}, {"rings": "1"}, {"rings": "2"}):
        pick_edge(p, lambda x, y, z: abs(x) < 3 and abs(z) < 3)
        quad_fill(settings=opt)
        sizes = face_sizes(p, new_faces(nf0, p))
        check("uneven %s: valid" % opt, sizes and all(s == 4 for s in sizes) and manifold_ok(p) and winding_ok(p))
        cmds.undo()

    # ------------------------------------------- L-shaped hole
    cmds.file(new=True, force=True)
    p = plane("lHole", n=10, size=10.0)
    cells = [(i, j) for i in range(2, 7) for j in range(2, 4)] + [(i, j) for i in range(2, 4) for j in range(4, 7)]
    cmds.delete(["%s.%s" % (p, f) for f in cell_faces(10, cells)])
    nf0 = fn_of(p).numPolygons
    pick_edge(p, lambda x, y, z: abs(x) < 4 and abs(z) < 4)
    report = quad_fill()
    common_checks("plane L", p, nf0)
    for sm in (0.0, 1.0):
        cmds.undo()
        pick_edge(p, lambda x, y, z: abs(x) < 4 and abs(z) < 4)
        quad_fill(settings={"smooth": sm})
        bad = folded_corners(p, new_faces(nf0, p))
        check("L at Smooth %.0f: no folds" % sm, not bad, "%d folded" % bad)

    # ------------------------------------------- odd hole: one triangle
    cmds.file(new=True, force=True)
    p = plane("oddHole", n=8)
    cmds.delete(["%s.%s" % (p, f) for f in cell_faces(8, [(i, j) for i in range(2, 5) for j in range(3, 5)])])
    e = pick_edge(p, lambda x, y, z: abs(x - 0.5) < 0.1 and 0 < z < 2)  # split one border edge: 11 edges
    cmds.polySubdivideEdge("%s.e[%d]" % (p, e), divisions=1, constructionHistory=False)
    nf0 = fn_of(p).numPolygons
    pick_edge(p, lambda x, y, z: abs(x) < 3 and abs(z) < 2)
    report = quad_fill()
    common_checks("plane odd", p, nf0, expect_tris=1)
    check("odd: says so", "triangle" in tb["qf_describe"](report["plans"][0]), tb["qf_describe"](report["plans"][0]))

    # ------------------------------------------- sphere: follow the curvature
    cmds.file(new=True, force=True)
    r = 10.0
    s = cmds.polySphere(r=r, sx=24, sy=24, name="ballHole", constructionHistory=False)[0]
    cmds.addAttr(s, longName="assetTag", dataType="string")
    cmds.setAttr(s + ".assetTag", "keep me", type="string")
    uuid = cmds.ls(s, uuid=True)[0]
    shape_name = shape_of(s)
    fn = fn_of(s)
    hole = []
    for f in range(fn.numPolygons):  # a 4 x 4 block of faces on the equator facing +x
        c = om.MVector()
        vs = fn.getPolygonVertices(f)
        for v in vs:
            c += om.MVector(fn.getPoint(v))
        c /= len(vs)
        if c.x > 0 and abs(math.atan2(c.z, c.x)) < math.radians(30) and abs(c.y) < r * math.sin(math.radians(30)):
            hole.append(f)
    cmds.delete(["%s.f[%d]" % (s, f) for f in hole])
    rim = border_edges(s)
    before_pts = points(s)
    before_counts = counts(s)
    nf0 = fn_of(s).numPolygons
    nv0 = fn_of(s).numVertices
    mesh_nodes = len(cmds.ls(type="mesh"))
    pick_edge(s, lambda x, y, z: x > 0)
    t0 = time.time()
    report = quad_fill()
    dt = time.time() - t0
    faces = common_checks("sphere", s, nf0)
    pts = points(s)
    dev = max(abs(math.sqrt(sum(c * c for c in q)) - r) for q in pts[nv0:])
    check("sphere: fill follows the curvature (within 1% of the radius)", dev < 0.01 * r,
          "max off-sphere %.3f (r %.0f), %s" % (dev, r, tb["qf_describe"](report["plans"][0])))
    fnn = fn_of(s)
    out = 0
    for f in faces:
        nn = fnn.getPolygonNormal(f, om.MSpace.kWorld)
        c = om.MVector()
        for v in fnn.getPolygonVertices(f):
            c += om.MVector(fnn.getPoint(v, om.MSpace.kWorld))
        out += nn * c > 0
    check("sphere: new normals face out", out == len(faces), "%d / %d" % (out, len(faces)))
    check("sphere: the old border shades smoothly", all(fnn.isEdgeSmooth(e) for e in rim))
    check("sphere: same node, name, uuid, attributes", cmds.objExists(shape_name) and cmds.ls(s, uuid=True)[0] == uuid
          and cmds.getAttr(s + ".assetTag") == "keep me" and len(cmds.ls(type="mesh")) == mesh_nodes)
    check("sphere: a mesh without history gets none", not cmds.listConnections(shape_name + ".inMesh"),
          str(cmds.listHistory(shape_name)))
    check("sphere: fast", dt < 1.0, "%.3fs" % dt)
    cmds.undo()
    check("sphere: one undo puts it back", counts(s) == before_counts and max(
        abs(a - b) for q, w in zip(points(s), before_pts) for a, b in zip(q, w)) < 1e-6, str(counts(s)))
    # flat (Follow 0) is far off: the curvature really comes from the surface
    pick_edge(s, lambda x, y, z: x > 0)
    quad_fill(settings={"follow": 0.0})
    dev0 = max(abs(math.sqrt(sum(c * c for c in q)) - r) for q in points(s)[nv0:])
    check("sphere: Follow 0 is the flat fill", dev0 > 5 * dev, "flat %.3f vs %.3f" % (dev0, dev))
    cmds.undo()

    # round hole at the pole: one ring, then a grid
    cmds.file(new=True, force=True)
    s = cmds.polySphere(r=r, sx=24, sy=24, name="poleHole", constructionHistory=True)[0]
    fn = fn_of(s)
    top = [f for f in range(fn.numPolygons)
           if min(fn.getPoint(v).y for v in fn.getPolygonVertices(f)) > r * math.cos(math.radians(38))]
    cmds.delete(["%s.f[%d]" % (s, f) for f in top])
    nf0, nv0 = fn_of(s).numPolygons, fn_of(s).numVertices
    pick_edge(s, lambda x, y, z: y > 0)
    report = quad_fill()
    plan = report["plans"][0]
    common_checks("pole", s, nf0)
    dev = max(abs(math.sqrt(sum(c * c for c in q)) - r) for q in points(s)[nv0:])
    check("pole: round hole gets a ring", plan["rings"] == 1, tb["qf_describe"](plan))
    check("pole: follows the sphere (within 1.5%)", dev < 0.015 * r, "max off-sphere %.3f" % dev)
    check("pole: history mesh keeps its history", bool(cmds.listConnections(shape_of(s) + ".inMesh")))

    # ------------------------------------------- cylinder: flat cap, round side
    cmds.file(new=True, force=True)
    c = cmds.polyCylinder(r=5, h=10, sx=16, sy=5, sc=0, name="tubeHole", constructionHistory=False)[0]
    fn = fn_of(c)
    capf = [f for f in range(fn.numPolygons) if len(fn.getPolygonVertices(f)) > 4
            and fn.getPoint(fn.getPolygonVertices(f)[0]).y > 4.9]
    cmds.delete("%s.f[%d]" % (c, capf[0]))
    nf0, nv0 = fn_of(c).numPolygons, fn_of(c).numVertices
    rim = border_edges(c)
    pick_edge(c, lambda x, y, z: y > 4.9)
    report = quad_fill()
    common_checks("cylinder cap", c, nf0)
    ys = [q[1] for q in points(c)[nv0:]]
    check("cylinder cap: open tube end closes flat", max(abs(y - 5.0) for y in ys) < 0.05,
          "y %.3f .. %.3f, %s" % (min(ys), max(ys), tb["qf_describe"](report["plans"][0])))
    check("cylinder cap: the rim stays a hard edge", not any(fn_of(c).isEdgeSmooth(e) for e in rim))
    fn = fn_of(c)
    side = []
    for f in range(fn.numPolygons):
        vs = fn.getPolygonVertices(f)
        if len(vs) != 4:
            continue
        cx = sum(fn.getPoint(v).x for v in vs) / 4
        cy = sum(fn.getPoint(v).y for v in vs) / 4
        cz = sum(fn.getPoint(v).z for v in vs) / 4
        if math.hypot(cx, cz) > 4.5 and cx > 0 and abs(math.atan2(cz, cx)) < math.radians(50) and abs(cy) < 3:
            side.append(f)
    cmds.delete(["%s.f[%d]" % (c, f) for f in side])
    nf0, nv0 = fn_of(c).numPolygons, fn_of(c).numVertices
    pick_edge(c, lambda x, y, z: x > 3 and abs(y) < 3)
    report = quad_fill()
    common_checks("cylinder side", c, nf0)
    rad = [math.hypot(q[0], q[2]) for q in points(c)[nv0:]]
    check("cylinder side: follows the round (within 1.5%)", max(abs(x - 5.0) for x in rad) < 0.075,
          "radius %.3f .. %.3f, %s" % (min(rad), max(rad), tb["qf_describe"](report["plans"][0])))

    # ------------------------------------------- materials per face
    cmds.file(new=True, force=True)
    p = plane("shadedHole")
    sgs = []
    for k in range(2):
        mat = cmds.shadingNode("lambert", asShader=True, name="mat%d" % k)
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="mat%dSG" % k)
        cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader")
        sgs.append(sg)
    cmds.sets(p + ".f[0:31]", edit=True, forceElement=sgs[0])
    cmds.sets(p + ".f[32:63]", edit=True, forceElement=sgs[1])
    cmds.delete(["%s.%s" % (p, f) for f in cell_faces(8, [(3, 5), (4, 5), (3, 6), (4, 6)])])
    nf0 = fn_of(p).numPolygons
    pick_edge(p, lambda x, y, z: abs(x) < 1.5 and 0.5 < abs(z) < 3.5)
    quad_fill()
    faces = new_faces(nf0, p)
    check("per-face materials: the hole was filled", len(faces) == 4, str(len(faces)))
    check("per-face materials: new faces take the material round the hole",
          all(cmds.sets("%s.f[%d]" % (p, f), isMember=sgs[1]) for f in faces))

    # ------------------------------------------- picking: vertex, face, whole mesh
    cmds.file(new=True, force=True)
    p = plane("pickHole")
    cmds.delete(["%s.%s" % (p, f) for f in cell_faces(8, [(3, 3), (4, 3), (3, 4), (4, 4)])])
    cmds.select(p + ".vtx[30]")  # a corner of the hole (row 3, col 3)
    picked, _ = qf_selection()
    check("pick by border vertex", len(picked) == 1 and len(picked[0][1]) == 1 and len(picked[0][1][0]) == 8)
    cmds.select(p + ".f[19]")  # the face below-left of the hole
    picked, _ = qf_selection()
    check("pick by a face next to the hole", len(picked) == 1 and len(picked[0][1][0]) == 8)
    cmds.select(p)
    picked, notes = qf_selection()
    check("a mesh with two open borders asks which", not picked and notes, str(notes))

    # ------------------------------------------- preview: never saved, out of undo
    cmds.file(new=True, force=True)
    p = plane("previewHole")
    cmds.delete(["%s.%s" % (p, f) for f in cell_faces(8, [(3, 3), (4, 3), (3, 4), (4, 4)])])
    pick_edge(p, lambda x, y, z: abs(x) < 1.5 and abs(z) < 1.5)
    picked, _ = qf_selection()
    dp = tb["get_dag_path"](picked[0][0])
    plan = qf_plan(qf_read(dp, picked[0][1][0]))
    pv = tb["QuadFillPreview"]()
    cmds.flushUndo()
    pv.show([(picked[0][0], plan)])
    node = pv.node()
    check("preview made", node and cmds.objExists(node))
    pv.show([(picked[0][0], qf_plan(qf_read(dp, picked[0][1][0]), {"rings": "1"}))])
    check("preview rebuilt in place for a new layout", pv.node() == node)
    check("preview stays out of the undo queue", not cmds.undoInfo(q=True, undoName=True))
    path = os.path.join(os.environ.get("TEMP", "/tmp"), "qf_preview_test.ma")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaAscii", force=True)
    with open(path) as f:
        text = f.read()
    check("preview never saved", "quadFillPreview" not in text)
    os.remove(path)
    pv.clear()
    check("preview cleared", not cmds.objExists(node))

    # ------------------------------------------- speed on a big round hole
    cmds.file(new=True, force=True)
    big = cmds.polyCylinder(r=5, h=10, sx=96, sy=2, sc=0, name="bigTube", constructionHistory=False)[0]
    fn = fn_of(big)
    capf = [f for f in range(fn.numPolygons) if len(fn.getPolygonVertices(f)) > 4]
    cmds.delete("%s.f[%d]" % (big, capf[0]))
    nf0 = fn_of(big).numPolygons
    cmds.select("%s.e[%d]" % (big, border_edges(big)[0]))
    t0 = time.time()
    report = quad_fill()
    dt = time.time() - t0
    common_checks("big cap", big, nf0)
    check("big cap: 96 edges filled quickly", dt < 3.0, "%.2fs, %s" % (dt, tb["qf_describe"](report["plans"][0])))

    print("")
    failed = [r for r in RESULTS if not r[1]]
    print("%d checks, %d failed" % (len(RESULTS), len(failed)))
    for r in failed:
        print("  FAIL", r[0], r[2])
    return not failed


if __name__ == "__main__":
    ok = False
    try:
        ok = main()
    except Exception:
        traceback.print_exc()
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(0 if ok else 1)
