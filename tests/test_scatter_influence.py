"""Headless tests for Scatter's Where it gathers targets (mayapy).

    mayapy tests/test_scatter_influence.py

The user (2026-11-17): "if I max out walls, everything will literally just
stick to walls. If I max out corners, things will stick to corners ... as
soon as I make one value more than the other, it would influence that
way", and it should move what grows, not add more.

A low-res slab in decimetres (10 faces: 4 x 3 m, 0.6 m high, a 0.4 m wide,
0.2 m deep gutter along its middle): its folds (gutter floor = crevices,
rims, corners); all targets 0 grows exactly as before; Outer edges 1 puts
it all along the rims (the same amount), Falloff hard vs soft, Open ground
1 keeps it off them, Walls 1 fills the gutter, Corners 1 the corners, and
Walls + Corners mixes by their values. Moss follows too.

Then the user's yard: a one-face floor with a separate wall ring standing
on its border, a blocker over the wall tops. Where the wall meets the floor
is a wall foot (crevice), also where a wall sunk into the floor passes
through it; Walls 1 / Corners 1 / both / Open ground 1, each keeping the
total. Top-down density pictures go to tests/_out/scatter_influence.
"""

import math
import os
import struct
import sys
import time
import traceback
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.path.join(HERE, "_out", "scatter_influence")

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


PROFILE = [(-20.0, 0.0), (20.0, 0.0), (20.0, 6.0), (2.0, 6.0), (2.0, 4.0), (-2.0, 4.0), (-2.0, 6.0), (-20.0, 6.0)]


def gutter_block():
    """The U profile (x, y) run along z -15..15: 8 side quads, two 8-gon ends."""
    n = len(PROFILE)
    pts = [om.MPoint(x, y, 15.0) for x, y in PROFILE] + [om.MPoint(x, y, -15.0) for x, y in PROFILE]
    counts, conn = [], []
    for i in range(n):
        j = (i + 1) % n
        counts.append(4)
        conn += [i, n + i, n + j, j]
    counts.append(n)
    conn += list(range(n))
    counts.append(n)
    conn += [n + i for i in reversed(range(n))]
    fn = om.MFnMesh()
    obj = fn.create(pts, counts, conn)
    node = cmds.rename(om.MFnDagNode(obj).fullPathName(), "gutterBlock")
    cmds.sets(node, edit=True, forceElement="initialShadingGroup")
    return cmds.ls(node, long=True)[0]


def part_points(tb, root, key):
    node = tb["sc_parts"](root).get(key)
    if not node or not cmds.getAttr(node + ".visibility"):
        return []
    fn = om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))
    return [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kWorld)]


def on_top(p):
    return p[1] > 5.5 and abs(p[0]) > 2.3


def edge_d(p):
    """Distance in from the nearest top edge: the slab's rim or a gutter lip (top only)."""
    return min(20.0 - abs(p[0]), 15.0 - abs(p[2]), abs(p[0]) - 2.0)


def band(pts, lo, hi):
    """Points per dm2 on the top between lo and hi in from the rim (gutter strip left out)."""
    n = sum(1 for p in pts if on_top(p) and lo <= edge_d(p) < hi)
    area = 0.0
    step = 0.25
    x = -20.0 + step / 2
    while x < 20.0:
        z = -15.0 + step / 2
        while z < 15.0:
            if abs(x) > 2.3 and lo <= min(20.0 - abs(x), 15.0 - abs(z), abs(x) - 2.0) < hi:
                area += step * step
            z += step
        x += step
    return n / max(area, 1e-9)


def in_gutter(p):
    return abs(p[0]) < 1.9 and p[1] < 4.8


def near_corner(p):
    return p[1] > 5.5 and 20.0 - abs(p[0]) < 4.0 and 15.0 - abs(p[2]) < 4.0


def _box(a, W, H, r):
    """A box blur of radius r, along rows then columns."""
    out = [0.0] * (W * H)
    for j in range(H):
        row = a[j * W:(j + 1) * W]
        s = sum(row[:r])
        for i in range(W):
            if i + r < W:
                s += row[i + r]
            if i - r - 1 >= 0:
                s -= row[i - r - 1]
            out[j * W + i] = s
    res = [0.0] * (W * H)
    for i in range(W):
        s = sum(out[j * W + i] for j in range(min(r, H)))
        for j in range(H):
            if j + r < H:
                s += out[(j + r) * W + i]
            if j - r - 1 >= 0:
                s -= out[(j - r - 1) * W + i]
            res[j * W + i] = s
    return res


def _png(name, img, IW, IH, titles):
    raw = b"".join(b"\x00" + bytes(img[r * IW * 3:(r + 1) * IW * 3]) for r in range(IH))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", IW, IH, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    path = os.path.join(OUT, name)
    with open(path, "wb") as f:
        f.write(png)
    print("picture: %s  (%s)" % (path, ", ".join(titles)))


def picture(name, panels, cols=3):
    """Top-down density pictures (x right, z down), one panel per build, as a PNG."""
    W, H, pad = 320, 240, 8
    rows = (len(panels) + cols - 1) // cols
    IW, IH = cols * (W + pad) + pad, rows * (H + pad) + pad
    img = bytearray(b"\x18" * (IW * IH * 3))
    accs = []
    for title, pts in panels:
        acc = [0.0] * (W * H)
        for p in pts:
            if p[1] < 3.5:
                continue
            i = int((p[0] + 20.0) / 40.0 * (W - 1))
            j = int((p[2] + 15.0) / 30.0 * (H - 1))
            if 0 <= i < W and 0 <= j < H:
                acc[j * W + i] += 1.0
        for _ in range(2):  # blurred (two box passes each way): a density map, not single blades
            acc = _box(acc, W, H, 7)
        accs.append(acc)
    top = max(max(a) for a in accs) or 1.0  # one scale for every panel, so they compare
    for idx, acc in enumerate(accs):
        ox, oy = pad + (idx % cols) * (W + pad), pad + (idx // cols) * (H + pad)
        for j in range(H):
            for i in range(W):
                x = -20.0 + 40.0 * i / (W - 1)
                v = min(1.0, acc[j * W + i] / top) ** 0.6
                gut = abs(x) < 2.0
                base = (52, 46, 40) if not gut else (30, 26, 22)
                col = (int(base[0] + v * (215 - base[0])), int(base[1] + v * (225 - base[1])),
                       int(base[2] + v * (120 - base[2])))
                k = ((oy + j) * IW + ox + i) * 3
                img[k:k + 3] = bytes(col)
    _png(name, img, IW, IH, [t for t, _ in panels])


def run():
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    blk = gutter_block()
    check("scene in decimetres", abs(tb["scene_m_per_unit"]() - 0.1) < 1e-9)

    # the folds
    f = tb["_sc_features"](blk, 30.0)
    crev = f["crev"]
    check("its folds: the gutter floor's two edges are the crevices",
          len(crev) == 2 and all(abs(abs(a[0]) - 2.0) < 1e-6 and abs(a[1] - 4.0) < 1e-6 for a, b in crev),
          "%d crevices, %d edges, %d corners" % (len(crev), len(f["edge"]), len(f["corner"])))
    check("... the rest of the box's and the gutter lips' edges are edges", len(f["edge"]) == 22)
    cs = set((round(p[0]), round(p[1]), round(p[2])) for p in f["corner"])
    check("... corners: the slab's, and where the gutter meets the ends",
          (20, 6, 15) in cs and (-20, 0, -15) in cs and (2, 4, 15) in cs and (2, 6, -15) in cs, "%d" % len(cs))
    check("... none on a smooth surface", not tb["_sc_features"](
        cmds.polySphere(r=5, sx=24, sy=16, constructionHistory=False, name="ball")[0], 30.0)["edge"])
    cmds.delete("ball")

    grass = {"grass": 25.0, "bunch_size": 0.08, "grass_length": 0.12, "coverage": 0.55, "detail": "Proxy",
             "grass_strays": 0.0, "patchiness": 0.3, "seed": 7,
             "edges": 0.0, "crevices": 0.0, "creases": 0.0}
    rep = tb["create_scatter_group"]([blk], "Grass", grass, select=False)
    root = rep["root"]
    lid = tb["sc_data"](root)["layers"][0]["id"]
    key = lid + "/grass"
    tb["sc_regrow"](root, readback=False)
    base = part_points(tb, root, key)
    check("grass grows on the block", len(base) > 2000, "%d points" % len(base))

    # all targets 0 (reaches, falloff, breakup changed): exactly as before
    tb["sc_update"](root, lid, {"to_walls_reach": 1.3, "to_soft": 0.9, "to_breakup": 0.8, "to_angle": 50.0})
    check("all targets 0: grows exactly as before", part_points(tb, root, key) == base)
    check("... and builds no gather object", not tb["sc_gather_on"](tb["sc_settings"](
        tb["sc_layer"](tb["sc_data"](root), lid))))
    tb["sc_update"](root, lid, dict((k, tb["SC_TO_DEFAULTS"][k]) for k in ("to_walls_reach", "to_soft", "to_breakup",
                                                                           "to_angle")))
    n0 = float(len(base))

    def grow(**kw):
        ch = {"to_walls": 0.0, "to_corners": 0.0, "to_rims": 0.0, "to_open": 0.0}
        ch.update(kw)
        t0 = time.time()
        tb["sc_update"](root, lid, ch)
        return part_points(tb, root, key), time.time() - t0

    def share(pts, test):
        top = [q for q in pts if on_top(q)]
        return sum(1 for q in top if test(q)) / float(max(1, len(top)))

    rims, t_rims = grow(to_rims=1.0, to_rims_reach=0.5)
    sh = share(rims, lambda q: edge_d(q) < 6.5)
    check("Outer edges 1: it all goes along the rims (within the reach)", sh > 0.9,
          "%.0f%% within the reach, %.0f%% before" % (100 * sh, 100 * share(base, lambda q: edge_d(q) < 6.5)))
    check("... the same amount, moved", 0.7 < len(rims) / n0 < 1.3, "%d -> %d points" % (n0, len(rims)))
    check("... and quick", t_rims < 3.0, "%.2fs" % t_rims)
    soft, _ = grow(to_rims=1.0, to_rims_reach=0.6, to_soft=1.0, to_breakup=0.0)
    bands = [band(soft, d, d + 1.5) for d in (0.0, 1.5, 3.0, 4.5)] + [band(soft, 7.0, 99.0)]
    # (blades right at the rim hang over it, below the top: the first band reads a little low)
    check("Falloff 1: a soft fade in from the edges, nothing past the reach",
          bands[0] > 0.7 * bands[1] and bands[1] > bands[2] > bands[3] and bands[4] < 0.05 * bands[1],
          " ".join("%.2f" % v for v in bands))
    hard, _ = grow(to_rims=1.0, to_rims_reach=0.6, to_soft=0.0, to_breakup=0.0)
    hb = [band(hard, d, d + 1.5) for d in (1.5, 4.0)]
    check("Falloff 0: a hard band, as full near its end as near the edge", hb[1] > 0.6 * hb[0] and
          band(hard, 4.0, 5.5) > 1.5 * band(soft, 4.0, 5.5), "%.2f %.2f vs soft %.2f" % (
              hb[0], hb[1], band(soft, 4.0, 5.5)))

    away, _ = grow(to_open=1.0, to_rims_reach=0.5)
    sh = share(away, lambda q: edge_d(q) < 4.0)
    check("Open ground 1: off the rims, the gutter and the corners", sh < 0.05 and not sum(map(in_gutter, away)),
          "%.1f%% near the rims, %d in the gutter" % (100 * sh, sum(map(in_gutter, away))))
    check("... the same amount", 0.7 < len(away) / n0 < 1.3, "%d -> %d" % (n0, len(away)))

    gut, _ = grow(to_walls=1.0, to_walls_reach=0.3)
    sh = sum(1 for q in gut if abs(q[0]) < 5.5) / float(len(gut))
    check("Walls 1: it all goes into the gutter (and just over its lips, in reach)", sh > 0.9 and
          sum(map(in_gutter, gut)) > 3 * max(1, sum(map(in_gutter, base))),
          "%.0f%% there, gutter %d -> %d" % (100 * sh, sum(map(in_gutter, base)), sum(map(in_gutter, gut))))

    corners = [q for q in tb["_sc_feature_set"]([blk], 30.0)["corner"]]

    def near_any_corner(q, r=6.5):
        return min((q[0] - c[0]) ** 2 + (q[1] - c[1]) ** 2 + (q[2] - c[2]) ** 2 for c in corners) < r * r

    cor, _ = grow(to_corners=1.0, to_corners_reach=0.5)
    sh = sum(map(near_any_corner, cor)) / float(len(cor))
    check("Corners 1: it all goes into the corners", sh > 0.9 and 0.6 < len(cor) / n0 < 1.4,
          "%.0f%% there, %d -> %d points" % (100 * sh, n0, len(cor)))
    w1, _ = grow(to_rims=1.0, to_rims_reach=0.5, to_corners=0.0)
    wc1, _ = grow(to_rims=1.0, to_rims_reach=0.5, to_corners=1.0, to_corners_reach=0.5)
    wch, _ = grow(to_rims=1.0, to_rims_reach=0.5, to_corners=0.5, to_corners_reach=0.5)
    fr = [sum(map(near_corner, x)) / float(len(x)) for x in (w1, wch, wc1)]
    check("Edges 1 + Corners: the more Corners, the more of it in the corners (same amount)",
          fr[0] < fr[1] < fr[2] and 0.7 < len(wc1) / n0 < 1.3, "corner share %s" % " < ".join(
              "%.0f%%" % (100 * v) for v in fr))

    picture("grass_influence.png", [("as it starts", base), ("Outer edges 1", rims), ("Open ground 1", away),
                                    ("Walls 1 (the gutter)", gut), ("Corners 1", cor), ("Edges 1 + Corners 1", wc1)])
    back, _ = grow()
    check("back to 0: as before", back == base)

    # moss follows it too (the same margins)
    _, mid = tb["sc_add_layer"](root, "Moss", {"style": "Carpet", "coverage": 0.3, "detail": "Proxy"})
    mkey = mid + "/moss"
    m0 = part_points(tb, root, mkey)
    tb["sc_update"](root, mid, {"to_rims": 1.0, "to_rims_reach": 0.6})
    m1 = part_points(tb, root, mkey)
    check("Moss: Outer edges 1 puts it along the rims, off the middles",
          band(m1, 0.0, 3.0) > 1.5 * max(band(m0, 0.0, 3.0), 0.01) and band(m1, 8.0, 99.0) < 0.2 * band(m0, 8.0, 99.0),
          "rim %.2f -> %.2f, middle %.2f -> %.2f" % (band(m0, 0.0, 3.0), band(m1, 0.0, 3.0), band(m0, 8.0, 99.0),
                                                     band(m1, 8.0, 99.0)))
    picture("moss_influence.png", [("moss: none", m0), ("moss: Outer edges 1", m1)], cols=2)
    cmds.delete(root)


def wall_ring(name, outer=20.0, inner=18.0, h=6.0, y0=0.0):
    """A square wall ring (one mesh, 16 quads) standing from y0."""
    O = [(-outer, -outer), (outer, -outer), (outer, outer), (-outer, outer)]
    I = [(-inner, -inner), (inner, -inner), (inner, inner), (-inner, inner)]
    pts = [om.MPoint(x, y, z) for y in (y0, y0 + h) for ring in (O, I) for x, z in ring]
    ob, ib, ot, it = 0, 4, 8, 12
    counts, conn = [], []
    for k in range(4):
        j = (k + 1) % 4
        conn += [ot + k, it + k, it + j, ot + j]   # top
        conn += [ob + k, ob + j, ib + j, ib + k]   # bottom
        conn += [ob + k, ot + k, ot + j, ob + j]   # outer face
        conn += [ib + k, ib + j, it + j, it + k]   # inner face
        counts += [4, 4, 4, 4]
    obj = om.MFnMesh().create(pts, counts, conn)
    node = cmds.rename(om.MFnDagNode(obj).fullPathName(), name)
    cmds.sets(node, edit=True, forceElement="initialShadingGroup")
    fn = om.MFnMesh(om.MSelectionList().add(node).getDagPath(0))
    tops = [f for f in range(fn.numPolygons) if all(abs(fn.getPoint(v).y - (y0 + h)) < 1e-6
                                                    for v in fn.getPolygonVertices(f))]
    if fn.getPolygonNormal(tops[0]).y < 0.0:  # wound inside out: turn every face round
        cmds.polyNormal(node, normalMode=0, constructionHistory=False)
    return node


def wall_d(p):
    """Distance in from the wall's inner face (on the floor)."""
    return 18.0 - max(abs(p[0]), abs(p[2]))


def yard_bands(pts):
    fl = [p for p in pts if p[1] < 2.0 and wall_d(p) > -0.1]

    def dens(lo, hi):
        n = sum(1 for p in fl if lo <= wall_d(p) < hi)
        return n / float((36 - 2 * lo) ** 2 - (36 - 2 * min(hi, 18.0)) ** 2)

    corner = sum(1 for p in fl if 18 - abs(p[0]) < 4 and 18 - abs(p[2]) < 4) / 64.0
    return [dens(0, 2), dens(2, 4), dens(4, 8), dens(8, 18)], corner


def yard_picture(name, panels):
    """Top-down density over the floor (the wall ring grey), one scale for all panels."""
    W = H = 240
    pad, cols = 8, 3
    rows = (len(panels) + cols - 1) // cols
    IW, IH = cols * (W + pad) + pad, rows * (H + pad) + pad
    img = bytearray(b"\x18" * (IW * IH * 3))
    accs = []
    for _title, pts in panels:
        acc = [0.0] * (W * H)
        for p in pts:
            if p[1] > 2.0:
                continue
            i = int((p[0] + 20.0) / 40.0 * (W - 1))
            j = int((p[2] + 20.0) / 40.0 * (H - 1))
            if 0 <= i < W and 0 <= j < H:
                acc[j * W + i] += 1.0
        for _ in range(2):
            acc = _box(acc, W, H, 5)
        accs.append(acc)
    top = max(max(a) for a in accs) or 1.0
    for idx, acc in enumerate(accs):
        ox, oy = pad + (idx % cols) * (W + pad), pad + (idx // cols) * (H + pad)
        for j in range(H):
            for i in range(W):
                x, z = -20.0 + 40.0 * i / (W - 1), -20.0 + 40.0 * j / (H - 1)
                v = min(1.0, acc[j * W + i] / top) ** 0.6
                base = (52, 46, 40) if max(abs(x), abs(z)) < 18 else (95, 95, 100)
                col = (int(base[0] + v * (215 - base[0])), int(base[1] + v * (225 - base[1])),
                       int(base[2] + v * (120 - base[2])))
                k = ((oy + j) * IW + ox + i) * 3
                img[k:k + 3] = bytes(col)
    _png(name, img, IW, IH, [t for t, _ in panels])


def walls():
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    floor = cmds.polyPlane(w=40, h=40, sx=1, sy=1, name="floor", constructionHistory=False)[0]
    wall = wall_ring("wallRing")
    grp = cmds.group(floor, wall, name="yard_GRP")
    floor, wall = cmds.listRelatives(grp, children=True, fullPath=True)
    blk = cmds.ls(cmds.polyCube(w=44, h=2, d=44, name="wallTopBlocker", constructionHistory=False)[0], long=True)[0]
    cmds.move(0, 6.0, 0, blk)

    fs = tb["_sc_feature_set"]([floor, wall], 30.0)
    foot = [s for s in fs["crev"] if abs(s[0][1]) < 1e-6 and abs(s[1][1]) < 1e-6 and
            abs(max(abs(s[0][0]), abs(s[0][2])) - 18.0) < 1e-6 and abs(max(abs(s[1][0]), abs(s[1][2])) - 18.0) < 1e-6]
    check("separate meshes: the wall's foot on the floor is a crevice", len(foot) == 4,
          "%d foot lines; %d crevices, %d edges, %d corners" % (len(foot), len(fs["crev"]), len(fs["edge"]),
                                                               len(fs["corner"])))
    cs = set((round(p[0]), round(p[1]), round(p[2])) for p in fs["corner"])
    check("... the room's corners are corners", all((x, 0, z) in cs for x in (-18, 18) for z in (-18, 18)))
    check("... and the floor's border under the wall is no open edge",
          not [s for s in fs["edge"] if abs(s[0][1]) < 1e-6 and abs(s[1][1]) < 1e-6])
    cmds.move(0, -1.0, 0, wall, relative=True)  # sunk into the floor: it passes through it
    sunk = tb["_sc_feature_set"]([floor, wall], 30.0)
    cut = [s for s in sunk["crev"] if abs(s[0][1]) < 1e-6 and abs(s[1][1]) < 1e-6]
    check("a wall sunk into the floor: where it passes through is a crevice", len(cut) >= 8,
          "%d crevice pieces on the floor" % len(cut))
    cmds.move(0, 1.0, 0, wall, relative=True)

    grass = {"grass": 25.0, "bunch_size": 0.08, "grass_length": 0.12, "detail": "Proxy", "seed": 3,
             "patchiness": 0.3}
    # the amount: bunches (a bunch against a wall loses the blades that would go into it, so points don't keep)
    made = {"n": 0}
    spots = tb["_DebrisBuild"]._spots

    def counted(self, density, kind, reach=0.0):
        got = spots(self, density, kind, reach)
        if kind == 1 and density > 0.0:
            made["n"] = len(got)
        return got

    tb["_DebrisBuild"]._spots = counted
    rep = tb["create_scatter_group"]([grp], "Grass", grass, select=False)
    root = rep["root"]
    tb["sc_set_blockers"](root, add=[blk])
    lid = tb["sc_data"](root)["layers"][0]["id"]
    key = lid + "/grass"

    def grow(**kw):
        ch = {"to_walls": 0.0, "to_corners": 0.0, "to_rims": 0.0, "to_open": 0.0, "to_walls_reach": 0.8,
              "to_corners_reach": 0.8}
        ch.update(kw)
        tb["sc_update"](root, lid, ch)
        grow.n = made["n"]  # bunches
        return [q for q in part_points(tb, root, key) if q[1] < 2.0]  # on the floor

    def at_corner(q, r=9.5):
        return min((abs(q[0]) - 18.0) ** 2 + (abs(q[2]) - 18.0) ** 2, 1e9) < r * r

    base = grow()
    n0, b0 = float(len(base)), float(made["n"])
    check("the yard grows, nothing on the blocked wall tops", n0 > 500 and not [
        q for q in part_points(tb, root, key) if q[1] > 2.0], "%d points" % n0)
    t0 = time.time()
    walls_ = grow(to_walls=1.0)
    dt = time.time() - t0
    bw = grow.n
    sh = sum(1 for q in walls_ if wall_d(q) < 9.5) / float(len(walls_))
    check("Walls 1: it all sticks to the walls (within the 0.8 m reach), the same amount",
          sh > 0.9 and 0.8 < bw / b0 < 1.2, "%.0f%% within reach (%.0f%% before), %d -> %d bunches, %.2fs" % (
              100 * sh, 100 * sum(1 for q in base if wall_d(q) < 9.5) / n0, b0, bw, dt))
    cor = grow(to_corners=1.0)
    sh = sum(map(at_corner, cor)) / float(len(cor))
    check("Corners 1: it all goes into the corners", sh > 0.9 and 0.8 < grow.n / b0 < 1.2,
          "%.0f%% in the corners, %d -> %d bunches" % (100 * sh, b0, grow.n))
    both = grow(to_walls=1.0, to_corners=1.0)
    half = grow(to_walls=1.0, to_corners=0.5)
    fr = [sum(map(at_corner, x)) / float(len(x)) for x in (walls_, half, both)]
    on_walls = sum(1 for q in both if wall_d(q) < 9.5) / float(len(both))
    check("Walls 1 + Corners: along the walls, and the more Corners the more in the corners",
          fr[0] < fr[1] < fr[2] and on_walls > 0.9, "corner share %s; %.0f%% by the walls" % (
              " < ".join("%.0f%%" % (100 * v) for v in fr), 100 * on_walls))
    open_ = grow(to_open=1.0)
    sh = sum(1 for q in open_ if wall_d(q) < 6.0) / float(len(open_))
    check("Open ground 1: keeps clear of the walls, the same amount", sh < 0.05 and 0.8 < grow.n / b0 < 1.2,
          "%.1f%% near the walls, %d -> %d bunches" % (100 * sh, b0, grow.n))
    lean = grow(to_walls=0.5, to_walls_reach=0.4)
    sh = sum(1 for q in lean if wall_d(q) < 5.5) / float(len(lean))
    sh0 = sum(1 for q in base if wall_d(q) < 5.5) / n0
    check("Walls 0.5: leans to the walls, some still in the open", sh0 + 0.1 < sh < 0.9,
          "%.0f%% by the walls (%.0f%% before)" % (100 * sh, 100 * sh0))
    yard_picture("yard_pulls.png", [("as it starts", base), ("Walls 1", walls_), ("Corners 1", cor),
                                    ("Walls 1 + Corners 1", both), ("Walls 1 + Corners 0.5", half),
                                    ("Open ground 1", open_)])
    cmds.delete(root)


try:
    run()
    walls()
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
