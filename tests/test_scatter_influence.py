"""Headless tests for Scatter Influence (mayapy).

    mayapy tests/test_scatter_influence.py

A low-res block in decimetres (10 faces: a 4 x 3 m slab, 0.6 m high, with a
0.4 m wide, 0.2 m deep gutter groove along its middle). Its folds are found
(the gutter's two floor edges are crevices, the rim edges, corners where
they meet); a Grass layer with every Influence strength at 0 grows exactly
as before; Edges +1 gathers it at the rim in a smooth gradient inwards,
Edges -1 pushes it to the open middles, Crevices +1 fills the gutter,
Corners +1 the corners; a Moss layer follows too. Top-down density
pictures go to tests/_out/scatter_influence.
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
    print("picture: %s  (%s)" % (path, ", ".join(t for t, _ in panels)))


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
    t0 = time.time()
    tb["sc_regrow"](root, readback=False)
    t_base = time.time() - t0
    base = part_points(tb, root, key)
    check("grass grows on the block", len(base) > 2000, "%d points" % len(base))

    # all strengths 0 (falloffs and curves changed): no influence at all, exactly as before
    tb["sc_update"](root, lid, {"inf_edge_dist": 1.3, "inf_crev_curve": 0.9, "inf_breakup": 0.8, "inf_angle": 50.0})
    check("all strengths 0: grows exactly as before", part_points(tb, root, key) == base)
    check("... and builds no influence object", not tb["sc_influence_on"](tb["sc_settings"](
        tb["sc_layer"](tb["sc_data"](root), lid))))
    tb["sc_update"](root, lid, {"inf_edge_dist": 0.5, "inf_crev_curve": 0.5, "inf_breakup": 0.3, "inf_angle": 30.0})

    def grow(**kw):
        ch = dict((k, 0.0) for k in ("inf_edges", "inf_crev", "inf_corner"))
        ch.update(kw)
        t0 = time.time()
        tb["sc_update"](root, lid, ch)
        return part_points(tb, root, key), time.time() - t0

    b_edge, b_mid = band(base, 0.0, 3.0), band(base, 6.5, 99.0)
    edges, t_edge = grow(inf_edges=1.0, inf_edge_dist=0.5)
    e_edge, e_mid = band(edges, 0.0, 3.0), band(edges, 6.5, 99.0)
    check("Edges +1: gathers at the rim (the middles as they were)", e_edge > 2.0 * b_edge and e_mid < 1.5 * b_mid,
          "rim %.2f -> %.2f, middle %.2f -> %.2f /dm2" % (b_edge, e_edge, b_mid, e_mid))
    bands = [band(edges, d, d + 1.5) for d in (0.0, 1.5, 3.0, 4.5, 6.5)]
    # (blades right at the rim hang over it, below the top: the first band reads a little low)
    check("... a smooth gradient inwards", bands[0] > 0.7 * bands[1] and bands[1] > bands[2] > bands[3] > bands[4],
          " ".join("%.2f" % v for v in bands))
    t_infl = t_edge
    check("... and quick", t_infl < 3.0, "%.2fs (the first build %.2fs)" % (t_infl, t_base))
    tight, _ = grow(inf_edges=1.0, inf_edge_dist=0.5, inf_edge_curve=0.0)
    broad, _ = grow(inf_edges=1.0, inf_edge_dist=0.5, inf_edge_curve=1.0)
    bt, bb = band(tight, 2.5, 4.5), band(broad, 2.5, 4.5)
    check("Curve: 0 hugs the edge, 1 reaches further in", bb > 1.3 * bt, "2.5..4.5 dm in: %.2f vs %.2f" % (bt, bb))

    away, _ = grow(inf_edges=-1.0, inf_edge_dist=0.5)
    a_edge, a_mid = band(away, 0.0, 3.0), band(away, 6.5, 99.0)
    check("Edges -1: away from the rim, to the open middles", a_edge < 0.3 * b_edge and a_mid > 0.7 * b_mid,
          "rim %.2f -> %.2f, middle %.2f -> %.2f" % (b_edge, a_edge, b_mid, a_mid))

    b_gut = sum(map(in_gutter, base))
    crev_pts, _ = grow(inf_crev=1.0, inf_crev_dist=0.3)
    c_gut = sum(map(in_gutter, crev_pts))
    check("Crevices +1: fills the gutter", c_gut > 1.8 * max(b_gut, 1) and c_gut > 150, "%d -> %d" % (b_gut, c_gut))
    no_gut, _ = grow(inf_crev=-1.0, inf_crev_dist=0.3)
    check("Crevices -1: keeps out of it", sum(map(in_gutter, no_gut)) < 0.3 * max(b_gut, 1),
          "%d -> %d" % (b_gut, sum(map(in_gutter, no_gut))))

    b_cor = sum(map(near_corner, base))
    cor, _ = grow(inf_corner=1.0, inf_corner_dist=0.5)
    k_cor = sum(map(near_corner, cor))
    check("Corners +1: gathers in the corners", k_cor > 2.0 * max(b_cor, 1), "%d -> %d" % (b_cor, k_cor))
    mix, _ = grow(inf_edges=0.6, inf_edge_dist=1.0, inf_corner=0.8, inf_corner_dist=0.6, inf_crev=0.7,
                  inf_crev_dist=0.3)

    picture("grass_influence.png", [("no influence", base), ("Edges +1", edges), ("Edges -1", away),
                                    ("Crevices +1", crev_pts), ("Corners +1", cor), ("mix", mix)])

    back, _ = grow()
    check("back to 0: as before", back == base)

    # moss follows it too (the same margins)
    _, mid = tb["sc_add_layer"](root, "Moss", {"style": "Carpet", "coverage": 0.3, "detail": "Proxy"})
    mkey = mid + "/moss"
    m0 = part_points(tb, root, mkey)
    tb["sc_update"](root, mid, {"inf_edges": 1.0, "inf_edge_dist": 0.8})
    m1 = part_points(tb, root, mkey)
    check("Moss: Edges +1 gathers at the rim too", band(m1, 0.0, 3.0) > 1.5 * max(band(m0, 0.0, 3.0), 0.01),
          "%.2f -> %.2f" % (band(m0, 0.0, 3.0), band(m1, 0.0, 3.0)))
    picture("moss_influence.png", [("moss: none", m0), ("moss: Edges +1", m1)], cols=2)
    cmds.delete(root)


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
