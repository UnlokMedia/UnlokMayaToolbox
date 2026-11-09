"""Headless tests for the Scatter influence paint (mayapy).

    mayapy tests/test_scatter_paint.py

A yard in decimetres (a floor, a wall at its back): a moss, a leaves, a
grass and an ivy layer. Influence paint set straight on the layer (the
group's JSON) and with the brush engine (ScPaint dabs): removing it empties
where it's painted, adding it fills where it's painted, a 10% stroke only
nudges and ten of them build up, unpainted parts grow as before, Flood /
Clear, Smooth, a layer at Coverage 0 grows only where it's painted in, the
paint follows its mesh, one Ctrl+Z per stroke (the undo regrows), paused
strokes grow at Play, Duplicate copies it, Bake keeps it harmlessly.
"""

import json
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


def box(name, size, at, parent=None, div=2.0):
    node = cmds.polyCube(w=size[0], h=size[1], d=size[2], sx=max(1, int(size[0] / div)), sy=max(1, int(size[1] / div)),
                         sz=max(1, int(size[2] / div)), name=name, constructionHistory=False)[0]
    cmds.move(at[0], at[1], at[2], node)
    if parent:
        node = cmds.parent(node, parent)[0]
    return cmds.ls(node, long=True)[0]


def yard():
    """Floor 4 x 3 m (top y = 0, x -20..20, z -15..15), a wall at its back
    (z -14..-13, 1.5 m high), under yard_GRP. The floor is one big quad on
    top (a guide mesh with few faces)."""
    grp = cmds.group(empty=True, name="yard_GRP")
    floor = box("floor", (40, 1, 30), (0, -0.5, 0), grp, div=100.0)
    wall = box("wall", (40, 15, 1), (0, 7.5, -13.5), grp, div=5.0)
    return cmds.ls(grp, long=True)[0], floor, wall


def part_points(tb, root, key):
    node = tb["sc_parts"](root).get(key)
    if not node or not cmds.getAttr(node + ".visibility"):
        return []
    fn = om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))
    return [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kWorld)]


def floor_half(pts, left):
    """Points on the floor (y < 1.5, off the wall) in the left (x < -3) or right (x > 3) half."""
    return sum(1 for p in pts if p[1] < 1.5 and p[2] > -12.0 and ((p[0] < -3.0) if left else (p[0] > 3.0)))


def left_paint(tb, floor, value):
    """A paint dict with every floor cell in the left half (x < -2) at value (set straight on the layer)."""
    uid, m16, inv, scale = tb["_sc_paint_space"](floor)
    hl = tb["SC_PAINT_CELL"] / tb["scene_m_per_unit"]() / scale
    flat = []
    for i in range(int(-20 / hl), int(-2 / hl)):
        for k in range(int(-15 / hl), int(15 / hl)):
            for j in (-1, 0):  # the top face is at local y 0: the cells either side of it
                flat.extend((i, j, k, int(round(value * tb["SC_PAINT_Q"]))))
    return {"t": [uid], "b": 0, "m": [[hl, flat]]}


def set_layer_paint(tb, root, lid, paint):
    """Write the paint straight into the group's JSON attribute, then grow."""
    data = json.loads(cmds.getAttr(root + "." + tb["SC_ATTR"]))
    for layer in data["layers"]:
        if layer["id"] == lid:
            if paint:
                layer["paint"] = paint
            else:
                layer.pop("paint", None)
    cmds.setAttr(root + "." + tb["SC_ATTR"], json.dumps(data, sort_keys=True), type="string")
    return tb["sc_regrow"](root)


def stroke(tb, sp, xs, z, y, radius, opacity, mode, nodes, step=None):
    """A brush stroke along x at depth z on the floor: dabs a quarter radius apart."""
    step = step or radius * 0.25
    x = xs[0]
    n = 0
    sp.begin_stroke()
    while x <= xs[1] + 1e-9:
        n += sp.dab((x, y, z), radius, opacity, mode, nodes)
        x += step
    sp.end_stroke()
    return n


def run():
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    grp, floor, wall = yard()
    m = tb["scene_m_per_unit"]()
    check("scene in decimetres", abs(m - 0.1) < 1e-9, m)

    # --- the paint data itself
    sp = tb["ScPaint"]()
    check("empty paint dumps to {}", sp.dump() == {} and sp.count() == 0)
    t0 = time.time()
    n = sp.dab((-10.0, 0.0, 0.0), 3.0, 1.0, "Add", [floor])
    dt = time.time() - t0
    d = sp.dump()
    check("a dab on a one-quad floor paints cells round it", n > 50 and len(d["m"][0][1]) // 4 == n,
          "%d cells, %.1f ms" % (n, dt * 1000.0))
    mp = tb["_MiPaint"](d)
    c, e, out = mp.at((-10.0, 0.0, 0.0)), mp.at((-8.0, 0.0, 0.0)), mp.at((-5.0, 0.0, 0.0))
    check("full at its centre, softer out, none past its rim", c > 0.8 and 0.1 < e < c and abs(out) < 0.02,
          "%.3f / %.3f / %.3f" % (c, e, out))
    sp2 = tb["ScPaint"]()
    sp2.dab((-10.0, 0.0, 0.0), 3.0, 0.1, "Add", [floor])
    one = tb["_MiPaint"](sp2.dump()).at((-10.0, 0.0, 0.0))
    for _ in range(9):
        sp2.dab((-10.0, 0.0, 0.0), 3.0, 0.1, "Add", [floor])
    ten = tb["_MiPaint"](sp2.dump()).at((-10.0, 0.0, 0.0))
    check("10% opacity: one dab nudges, ten build up", 0.07 < one < 0.13 and 0.85 < ten <= 1.0,
          "%.3f after one, %.3f after ten" % (one, ten))
    st = tb["ScPaint"]()
    stroke(tb, st, (-14.0, -6.0), 0.0, 0.0, 3.0, 0.1, "Add", [floor])  # 11 dabs overlap the middle
    s1 = tb["_MiPaint"](st.dump()).at((-10.0, 0.0, 0.0))
    for _ in range(9):
        stroke(tb, st, (-14.0, -6.0), 0.0, 0.0, 3.0, 0.1, "Add", [floor])
    s10 = tb["_MiPaint"](st.dump()).at((-10.0, 0.0, 0.0))
    stroke(tb, st, (-14.0, -6.0), 0.0, 0.0, 3.0, 0.1, "Remove", [floor])
    sb = tb["_MiPaint"](st.dump()).at((-10.0, 0.0, 0.0))
    check("a 10% stroke adds 10% however many dabs overlap; ten strokes build up, one Remove takes 10%",
          0.07 < s1 < 0.13 and 0.85 < s10 <= 1.0 and 0.05 < s10 - sb < 0.15,
          "%.3f after one stroke, %.3f after ten, %.3f after a Remove" % (s1, s10, sb))
    sp2.dab((-10.0, 0.0, 0.0), 3.0, 0.5, "Remove", [floor])
    check("Remove takes it back down", tb["_MiPaint"](sp2.dump()).at((-10.0, 0.0, 0.0)) < ten - 0.4)
    rt = tb["ScPaint"](sp2.dump())
    check("stored and read back alike (1/1000 steps)", rt.dump() == sp2.dump() and rt.count() == sp2.count())
    t0 = time.time()
    big = tb["ScPaint"]()
    nb = big.dab((0.0, 0.0, 0.0), 20.0, 0.5, "Add", [floor, wall])
    check("a 2 m dab is quick", time.time() - t0 < 1.0 and nb > 1000,
          "%d cells in %.0f ms" % (nb, (time.time() - t0) * 1000.0))
    wallk = tb["_MiPaint"](big.dump()).at((0.0, 5.0, -13.0))
    check("a dab near the wall's foot reaches up the wall too", wallk > 0.1, "%.3f on the wall 0.5 m up" % wallk)

    # Smooth: a hard-edged square blurs
    sq = tb["ScPaint"]()
    for z in (-3.0, -1.5, 0.0, 1.5, 3.0):  # a 1 m patch, hard edged
        stroke(tb, sq, (-14.0, -6.0), z, 0.0, 1.5, 1.0, "Add", [floor])
    sharp = [tb["_MiPaint"](sq.dump()).at((x, 0.0, 0.0)) for x in (-16.5, -10.0)]
    sq.dab((-16.0, 0.0, 0.0), 3.0, 0.5, "Smooth", [floor])
    sq.dab((-10.0, 0.0, 0.0), 3.0, 0.5, "Smooth", [floor])
    soft = [tb["_MiPaint"](sq.dump()).at((x, 0.0, 0.0)) for x in (-16.5, -10.0)]
    check("Smooth softens it: just past the edge rises, the patch's middle stays", soft[0] > sharp[0] + 0.05 and
          soft[1] > sharp[1] - 0.15, "edge %.2f -> %.2f, middle %.2f -> %.2f" % (sharp[0], soft[0], sharp[1], soft[1]))

    # Flood / Clear
    fl = tb["ScPaint"]()
    fl.dab((-10.0, 0.0, 0.0), 3.0, 0.5, "Add", [floor])
    fl.flood(1.0, "Remove")
    mf = tb["_MiPaint"](fl.dump())
    check("Flood Remove: none everywhere (painted cells too)", mf.at((10.0, 0.0, 0.0)) == -1.0 and
          mf.at((-10.0, 0.0, 0.0)) < -0.45, "%.2f / %.2f" % (mf.at((10.0, 0.0, 0.0)), mf.at((-10.0, 0.0, 0.0))))
    fl.clear()
    check("Clear: nothing painted", fl.dump() == {})

    # --- layers: baseline, then paint set straight on the layer
    rep = tb["create_scatter_group"]([grp], "Moss", {"style": "Carpet", "coverage": 0.55, "detail": "Proxy",
                                                       "patchiness": 0.3},
                                     select=False)
    root = rep["root"]
    data = tb["sc_data"](root)
    moss = data["layers"][0]["id"]
    base = part_points(tb, root, moss + "/moss")
    bl, br = floor_half(base, True), floor_half(base, False)
    check("moss grows on both halves of the floor", bl > 100 and br > 100, "%d / %d points" % (bl, br))

    set_layer_paint(tb, root, moss, left_paint(tb, floor, -1.0))
    gone = part_points(tb, root, moss + "/moss")
    gl, gr = floor_half(gone, True), floor_half(gone, False)
    check("Moss: painted out on the left (set on the layer) -> none there, the right as it was",
          gl < 0.05 * bl and abs(gr - br) <= 0.1 * br, "left %d -> %d, right %d -> %d" % (bl, gl, br, gr))
    set_layer_paint(tb, root, moss, left_paint(tb, floor, 0.5))
    half = part_points(tb, root, moss + "/moss")
    hl_, hr = floor_half(half, True), floor_half(half, False)
    check("Moss: painted in on the left (+50%) -> more there, the right as it was",
          hl_ > 1.1 * bl and abs(hr - br) <= 0.1 * br, "left %d -> %d, right %d -> %d" % (bl, hl_, br, hr))
    set_layer_paint(tb, root, moss, left_paint(tb, floor, -0.3))
    sub = floor_half(part_points(tb, root, moss + "/moss"), True)
    check("Moss: a little painted out (-30%) -> a bit less, not gone", 0.2 * bl < sub < 0.95 * bl,
          "left %d -> %d" % (bl, sub))
    set_layer_paint(tb, root, moss, {})
    check("no paint: as it was", part_points(tb, root, moss + "/moss") == base)

    # Debris layers (Leaves, Grass): their spots follow the same field
    for typ, part, extra in (("Leaves", "litter", {"leaves": 20.0, "coverage": 0.6}),
                             ("Grass", "grass", {"grass": 3.0, "coverage": 0.6, "detail": "Proxy"})):
        _, lid = tb["sc_add_layer"](root, typ, extra)
        b0 = part_points(tb, root, lid + "/" + part)
        l0, r0 = floor_half(b0, True), floor_half(b0, False)
        set_layer_paint(tb, root, lid, left_paint(tb, floor, -1.0))
        b1 = part_points(tb, root, lid + "/" + part)
        l1, r1 = floor_half(b1, True), floor_half(b1, False)
        set_layer_paint(tb, root, lid, left_paint(tb, floor, 0.6))
        b2 = part_points(tb, root, lid + "/" + part)
        l2, r2 = floor_half(b2, True), floor_half(b2, False)
        check("%s: painted out -> none on the left; painted in -> more; the right as it was" % typ,
              l0 > 50 and l1 <= 0.01 * l0 and l2 > 1.15 * l0 and abs(r1 - r0) <= 0.1 * r0 and abs(r2 - r0) <= 0.1 * r0,
              "left %d / %d / %d, right %d / %d / %d" % (l0, l1, l2, r0, r1, r2))
        tb["sc_remove_layer"](root, lid)

    # Ivy: vines avoid the wall's painted-out middle
    _, ivy = tb["sc_add_layer"](root, "Ivy", {"vines": 8, "length": 2.0, "detail": "Proxy"})
    tb["sc_set_surfaces"](root, remove=[floor])

    def ivy_mid():
        pts = part_points(tb, root, ivy + "/leaves") + part_points(tb, root, ivy + "/stems")
        return sum(1 for p in pts if -8.0 < p[0] < 8.0), len(pts)

    i0 = ivy_mid()
    uid, m16, inv, scale = tb["_sc_paint_space"](wall)
    wp = tb["ScPaint"]()
    for y in range(1, 15, 2):
        stroke(tb, wp, (-9.0, 9.0), -13.0, float(y), 2.0, 1.0, "Remove", [wall])
    tb["sc_set_paint"](root, ivy, wp)
    i1 = ivy_mid()
    check("Ivy: painted out across the wall's middle -> vines and leaves avoid it", i0[0] > 100 and i1[0] < 0.25 * i0[0],
          "middle %d -> %d points (all %d -> %d)" % (i0[0], i1[0], i0[1], i1[1]))
    wq = tb["ScPaint"]()
    wq.flood(1.0, "Remove")
    for y in range(1, 13):
        stroke(tb, wq, (8.0, 16.0), -13.0, float(y), 2.0, 1.0, "Add", [wall])
    tb["sc_set_paint"](root, ivy, wq)
    pts = part_points(tb, root, ivy + "/leaves")
    inside = sum(1 for p in pts if p[0] > 5.0)
    check("Ivy: Flood Remove then paint in a patch -> it grows only there", len(pts) > 30 and inside >= 0.9 * len(pts),
          "%d of %d leaf points at x > 0.5 m" % (inside, len(pts)))
    tb["sc_remove_layer"](root, ivy)
    tb["sc_set_surfaces"](root, add=[floor])

    # --- the brush engine, undo, pause
    tb["sc_update"](root, moss, {"coverage": 0.0})
    check("moss at Coverage 0: nothing", not part_points(tb, root, moss + "/moss"))
    bp = tb["sc_paint"](root, moss)
    stroke(tb, bp, (-14.0, -6.0), 0.0, 0.0, 3.0, 1.0, "Add", [floor])
    undo_before = cmds.undoInfo(q=True, undoName=True)
    rep = tb["sc_set_paint"](root, moss, bp)
    pts = part_points(tb, root, moss + "/moss")
    inside = sum(1 for p in pts if -18.0 < p[0] < -2.0 and -4.0 < p[2] < 4.0)
    check("Coverage 0 + a painted-in stroke: moss only along it", len(pts) > 30 and inside >= 0.95 * len(pts),
          "%d of %d points by the stroke" % (inside, len(pts)))
    check("one Ctrl+Z per stroke", cmds.undoInfo(q=True, undoName=True) == "Scatter paint" and
          undo_before != "Scatter paint", cmds.undoInfo(q=True, undoName=True))
    cmds.undo()
    tb["sc_sync"]()
    check("Ctrl+Z takes the stroke back (and regrows)", not tb["sc_layer"](tb["sc_data"](root), moss).get("paint") and
          not part_points(tb, root, moss + "/moss"))
    cmds.redo()
    tb["sc_sync"]()
    check("Ctrl+Y puts it back", len(part_points(tb, root, moss + "/moss")) == len(pts))

    tb["sc_pause"]()
    bp = tb["sc_paint"](root, moss)
    stroke(tb, bp, (6.0, 14.0), 0.0, 0.0, 3.0, 1.0, "Add", [floor])
    rep = tb["sc_set_paint"](root, moss, bp)
    pend = tb["sc_pending"](root)
    check("paused: the stroke is saved, the layer marked changed, nothing grows", rep.get("held") and pend and
          moss in pend[0] and len(part_points(tb, root, moss + "/moss")) == len(pts))
    tb["sc_play"]()
    right = sum(1 for p in part_points(tb, root, moss + "/moss") if p[0] > 2.0)
    check("Play grows it", right > 30, "%d points on the right" % right)

    # follows the mesh
    sp3 = tb["sc_paint"](root, moss)
    before = tb["_MiPaint"](sp3.dump()).at((-10.0, 0.0, 0.0))
    cmds.move(0, 0, 50, floor, relative=True)
    after = tb["_MiPaint"](sp3.dump())
    check("the paint follows its mesh", before > 0.9 and after.at((-10.0, 0.0, 50.0)) > 0.9 and
          abs(after.at((-10.0, 0.0, 0.0))) < 0.02)
    cmds.move(0, 0, -50, floor, relative=True)

    # Duplicate, Bake
    _, dup = tb["sc_add_layer"](root, None, copy_of=moss)
    check("Duplicate copies the paint", tb["sc_layer"](tb["sc_data"](root), dup).get("paint") ==
          tb["sc_layer"](tb["sc_data"](root), moss).get("paint"))
    done = tb["bake_scatter"]([root])
    baked = json.loads(cmds.getAttr(root + "." + tb["SC_BAKED"]))
    check("Bake: plain meshes, the paint kept harmlessly in the baked settings",
          done == [root] and not tb["is_scatter"](root) and any(l.get("paint") for l in baked["layers"]))
    cmds.undo()
    check("... and one Ctrl+Z brings it back live", tb["is_scatter"](root))
    cmds.delete(root)
    check("deleting the group leaves nothing behind", not cmds.ls("*." + tb["SC_ATTR"], objectsOnly=True))


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
