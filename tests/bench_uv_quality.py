"""How good do Auto UV's UVs and the layout look on a messy set? (mayapy)

    mayapy tests/bench_uv_quality.py [OUT_DIR]

Builds a shack-like asset that trips unwrappers up (bevelled planks, some
tilted; long pipes with bevelled caps, soft-shaded ones and a bent one;
posts; a crate; bolts and brackets), runs Auto UV (Unlok) and a layout,
then writes pictures and prints scores:
- uv_meshes.png: each mesh's UVs in its own cell, shells in colours
- uv_sheet.png: the hand-off sheet of the layout
- per shell: compactness (4 pi area / perimeter^2; stars score low),
  straight (its box is already the tightest: edges square to the axes),
  upright (world +Y points up the tile, for shells that have an up)
- per mesh: shells, tiny shells (< 2% of the mesh's UV area)
"""

import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "bench_uv_quality", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]
OUT = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else os.path.join(HERE, "_out", "uv_quality")


def bevel(node, offset=0.6, segments=2, edges=None):
    cmds.polyBevel3(edges or node + ".e[*]", offset=offset, segments=segments, chamfer=True,
                    constructionHistory=False)


def build():
    root = cmds.group(empty=True, name="shack_GRP")
    grp = dict((g, cmds.group(empty=True, name=g, parent=root)) for g in ("frame_GRP", "pipes_GRP", "bits_GRP"))
    made = []

    def put(node, g):
        node = cmds.parent(node, grp[g])[0]
        made.append(cmds.ls(node, long=True)[0])
        return node

    # bevelled planks: lying, standing, tilted
    for i, (rx, rz, ry) in enumerate(((0, 0, 0), (0, 90, 0), (0, 0, 7), (5, 0, 30), (0, 90, 45))):
        p = cmds.polyCube(w=200, h=4, d=20, name="woodBrown_C_plank%04d_GEP" % (i + 1))[0]
        bevel(p, 0.6, 2)
        cmds.rotate(rx, ry, rz, p)
        cmds.move(0, i * 30, 0, p)
        cmds.makeIdentity(p, apply=True)
        put(p, "frame_GRP")
    # one plank with every edge soft (a softened bevel look)
    p = cmds.polyCube(w=150, h=6, d=15, name="woodBrown_C_plank0006_GEP")[0]
    bevel(p, 1.0, 3)
    cmds.polySoftEdge(p, angle=180, constructionHistory=False)
    put(p, "frame_GRP")
    # posts: bevelled caps, hard caps
    for i in range(2):
        c = cmds.polyCylinder(r=10, h=250, sx=12, sy=4, name="woodBrown_C_post%04d_GEP" % (i + 1))[0]
        n = cmds.polyEvaluate(c, edge=True)
        bevel(c, 1.0, 2, ["%s.e[%d:%d]" % (c, 12 * 4, 12 * 5 - 1), "%s.e[%d:%d]" % (c, 0, 11)])
        cmds.move(300 + i * 40, 0, 0, c)
        cmds.makeIdentity(c, apply=True)
        put(c, "frame_GRP")
    # long pipes: horizontal, vertical, all soft, bent
    def pipe(name, rot=(0, 0, 90), soft=False, bend=0.0):
        c = cmds.polyCylinder(r=5, h=400, sx=16, sy=24, name=name)[0]
        caps = []
        n = cmds.polyEvaluate(c, edge=True)
        caps = ["%s.e[0:15]" % c, "%s.e[%d:%d]" % (c, 16 * 24, 16 * 25 - 1)]
        bevel(c, 0.8, 2, caps)
        if soft:
            cmds.polySoftEdge(c, angle=180, constructionHistory=False)
        if bend:
            cmds.nonLinear(c, type="bend", curvature=bend)
            cmds.delete(c, constructionHistory=True)
        cmds.rotate(rot[0], rot[1], rot[2], c)
        cmds.makeIdentity(c, apply=True)
        return put(c, "pipes_GRP")

    pipe("metalGrey_C_pipe0001_GEP")
    pipe("metalGrey_C_pipe0002_GEP", rot=(0, 0, 0))
    pipe("metalGrey_C_pipe0003_GEP", soft=True)
    pipe("metalGrey_C_pipe0004_GEP", rot=(0, 0, 0), soft=True, bend=70)
    # crate
    c = cmds.polyCube(w=60, h=60, d=60, sx=2, sy=2, sz=2, name="woodBrown_C_crate0001_GEP")[0]
    bevel(c, 1.5, 2)
    put(c, "frame_GRP")
    # bolts and brackets
    for i in range(4):
        b = cmds.polyCylinder(r=1, h=4, sx=6, name="metalGrey_C_bolt%04d_GEP" % (i + 1))[0]
        cmds.move(i * 5, 0, 50, b)
        cmds.makeIdentity(b, apply=True)
        put(b, "bits_GRP")
    for i in range(2):
        k = cmds.polyCube(w=12, h=2, d=6, name="metalGrey_C_bracket%04d_GEP" % (i + 1))[0]
        bevel(k, 0.3, 1)
        cmds.move(0, i * 10, 80, k)
        cmds.makeIdentity(k, apply=True)
        put(k, "bits_GRP")
    for m in made:
        cmds.delete(m, constructionHistory=True)
    return root, made


def shells_of(tb, m):
    """[(faces, uv polygons, 3D polygons)] per UV shell."""
    fn = tb["_mesh_fn"](m)
    counts, ids = fn.getAssignedUVs("map1")
    _, shell_of = fn.getUvShellsIds("map1")
    us, vs = fn.getUVs("map1")
    vcounts, vids = fn.getVertices()
    pts = fn.getPoints(tb["om"].MSpace.kWorld)
    out = {}
    k = 0
    for f, c in enumerate(counts):
        if c:
            uvp = [(us[ids[k + i]], vs[ids[k + i]]) for i in range(c)]
            p3 = [pts[vids[k + i]] for i in range(c)]
            out.setdefault(shell_of[ids[k]], []).append((uvp, p3))
        k += c
    return list(out.values())


def poly_area(q):
    return 0.5 * sum(q[i][0] * q[(i + 1) % len(q)][1] - q[(i + 1) % len(q)][0] * q[i][1] for i in range(len(q)))


def shell_scores(faces):
    """(uv area, compactness, straight, upright or None)."""
    area = sum(abs(poly_area(uv)) for uv, _ in faces)
    edges = {}
    for uv, _ in faces:
        for i in range(len(uv)):
            a, b = uv[i], uv[(i + 1) % len(uv)]
            key = (round(min(a, b)[0], 6), round(min(a, b)[1], 6), round(max(a, b)[0], 6), round(max(a, b)[1], 6))
            edges[key] = edges.get(key, 0) + 1
    perim = sum(math.hypot(k[2] - k[0], k[3] - k[1]) for k, n in edges.items() if n == 1)
    compact = 4 * math.pi * area / (perim * perim) if perim > 0 else 0.0
    pts = [p for uv, _ in faces for p in uv]

    def box(ang):
        c, s = math.cos(ang), math.sin(ang)
        xs = [p[0] * c - p[1] * s for p in pts]
        ys = [p[0] * s + p[1] * c for p in pts]
        return (max(xs) - min(xs)) + (max(ys) - min(ys))

    base = box(0.0)
    best = min(box(math.radians(a * 0.5)) for a in range(-90, 91))
    straight = base <= best * 1.01
    # world-up direction in UV: least squares of y over the shell's corners
    gu = gv = 0.0
    for uv, p3 in faces:
        for i in range(len(uv)):
            j = (i + 1) % len(uv)
            du, dv = uv[j][0] - uv[i][0], uv[j][1] - uv[i][1]
            dy = p3[j].y - p3[i].y
            gu += du * dy
            gv += dv * dy
    mag = math.hypot(gu, gv)
    upright = None
    if mag > 1e-9:
        upright = gv / mag > 0.7  # within ~45 degrees of +V
    return area, compact, straight, upright


def draw_meshes(tb, meshes, path):
    from PySide2 import QtGui, QtCore
    cols = 6
    cell = 260
    rows = (len(meshes) + cols - 1) // cols
    img = QtGui.QImage(cols * cell, rows * cell, QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor("#202020"))
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    palette = ["#e07a5f", "#81b29a", "#f2cc8f", "#3d85c6", "#c27ba0", "#8e7cc3", "#76a5af", "#e69138", "#6aa84f",
               "#a64d79"]
    for n, m in enumerate(meshes):
        x0, y0 = (n % cols) * cell, (n // cols) * cell
        sh = shells_of(tb, m)
        pts = [q for faces in sh for uv, _ in faces for q in uv]
        if not pts:
            continue
        u0, u1 = min(q[0] for q in pts), max(q[0] for q in pts)
        v0, v1 = min(q[1] for q in pts), max(q[1] for q in pts)
        sc = (cell - 30) / max(u1 - u0, v1 - v0, 1e-9)
        for si, faces in enumerate(sh):
            col = QtGui.QColor(palette[si % len(palette)])
            fill = QtGui.QColor(col)
            fill.setAlpha(110)
            p.setPen(QtGui.QPen(col.darker(150), 0.6))
            p.setBrush(fill)
            for uv, _ in faces:
                poly = QtGui.QPolygonF([QtCore.QPointF(x0 + 10 + (q[0] - u0) * sc, y0 + cell - 20 - (q[1] - v0) * sc)
                                        for q in uv])
                p.drawPolygon(poly)
        p.setPen(QtGui.QColor("#dddddd"))
        p.drawText(x0 + 6, y0 + 14, "%s (%d)" % (m.split("|")[-1].replace("_GEP", ""), len(sh)))
    p.end()
    img.save(path)


def run():
    tb = ns["load_toolbox"]()
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    root, meshes = build()
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=False)
    t = time.time()
    res = tb["run_auto_uv"](asset, score=False, unwrapper=tb["UNWRAP_METHODS"][0], pack="fit")
    t_auto = time.time() - t
    draw_meshes(tb, meshes, os.path.join(OUT, "uv_meshes.png"))
    report(tb, meshes, "after Auto UV")
    col = tb["collect_shells"](asset)
    settings = dict(tb["LAYOUT_DEFAULTS"], texel_density=256.0, map_size="2048",
                    orientation=tb["ORIENTATIONS"][0], group_similar=True)
    plan = tb["make_plan"](col, settings)
    tb["apply_layout"](asset, col, plan)
    img = tb["render_handoff_sheet"](asset, px_per_tile=512)
    img.save(os.path.join(OUT, "uv_sheet.png"))
    report(tb, meshes, "after layout (%s, %d tile(s))" % (settings["orientation"], len(plan["new_tiles"])))
    print("Auto UV %.1fs on %d meshes; pictures in %s" % (t_auto, len(meshes), OUT))


def report(tb, meshes, title):
    totals = {"shells": 0, "tiny": 0, "stars": 0, "straight": 0, "upright": 0, "with_up": 0}
    rows = []
    for m in meshes:
        sh = shells_of(tb, m)
        scores = [shell_scores(f) for f in sh]
        total = sum(s[0] for s in scores) or 1.0
        tiny = sum(1 for s in scores if s[0] < 0.02 * total)
        stars = sum(1 for s in scores if s[1] < 0.2 and s[0] >= 0.02 * total)
        totals["shells"] += len(sh)
        totals["tiny"] += tiny
        totals["stars"] += stars
        totals["straight"] += sum(1 for s in scores if s[2])
        totals["upright"] += sum(1 for s in scores if s[3])
        totals["with_up"] += sum(1 for s in scores if s[3] is not None)
        rows.append("%-28s shells %3d  tiny %3d  low-compact %2d  straight %3d/%-3d  upright %s" % (
            m.split("|")[-1], len(sh), tiny, stars, sum(1 for s in scores if s[2]), len(sh),
            "%d/%d" % (sum(1 for s in scores if s[3]), sum(1 for s in scores if s[3] is not None))))
    print("--- %s" % title)
    if "-v" in sys.argv:
        for r in rows:
            print(r)
    print("TOTAL shells %(shells)d  tiny %(tiny)d  low-compact %(stars)d  straight %(straight)d  "
          "upright %(upright)d/%(with_up)d" % totals)


try:
    run()
except Exception:
    traceback.print_exc()
finally:
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(0)
