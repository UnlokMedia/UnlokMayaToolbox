"""Headless tests for scatter groups (mayapy).

    mayapy tests/test_scatter.py

A yard in decimetres under one Maya group: a floor, a wall standing on it,
a beam lying on it and a gutter (a U channel). A scatter group made from
the Maya group finds every mesh in it (and one added later), names its
parts scatteredObjects####, makes only parts that hold something, keeps
leaves off the wall, gathers leaf piles at the wall's foot and in the
gutter (drifts along them), gives every part its own UDIM tiles, and its
layers turn on / off, duplicate, move and delete with one Ctrl+Z each
(the undo / redo regrows what it built). Live edits stay out of the undo
queue and only rebuild the layer edited; Bake drops the box and hidden
parts.
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


def box(name, size, at, parent=None, div=2.0):
    node = cmds.polyCube(w=size[0], h=size[1], d=size[2], sx=max(1, int(size[0] / div)), sy=max(1, int(size[1] / div)),
                         sz=max(1, int(size[2] / div)), name=name, constructionHistory=False)[0]
    cmds.move(at[0], at[1], at[2], node)
    if parent:
        node = cmds.parent(node, parent)[0]
    return cmds.ls(node, long=True)[0]


def points(tb, node):
    fn = om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))
    return [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kWorld)]


def tiles(tb, node):
    fn = om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))
    us, vs = fn.getUVs()
    counts, ids = fn.getAssignedUVs()
    out, k = set(), 0
    for c in counts:
        u = sum(us[i] for i in ids[k:k + c]) / c
        v = sum(vs[i] for i in ids[k:k + c]) / c
        out.add(1001 + int(math.floor(u)) + 10 * int(math.floor(v)))
        k += c
    return out


def yard():
    """Floor 4 x 3 m (top y = 0), a wall at its back (z -14..-13, 1.5 m
    high), a beam lying on it, a gutter channel (inside bottom y = 0.6,
    walls z 7.6..8.4 inside), under shack_GRP."""
    grp = cmds.group(empty=True, name="shack_GRP")
    floor = box("floor", (40, 1, 30), (0, -0.5, 0), grp)
    wall = box("wall", (40, 15, 1), (0, 7.5, -13.5), grp)
    beam = box("beam", (30, 1.2, 1.2), (0, 0.6, 2.0), grp)
    gb = box("gutterBottom", (30, 0.3, 1.4), (0, 0.45, 8.0), grp, div=1.0)
    g1 = box("gutterSideA", (30, 1.4, 0.2), (0, 1.0, 7.2), grp, div=1.0)
    g2 = box("gutterSideB", (30, 1.4, 0.2), (0, 1.0, 8.8), grp, div=1.0)
    return cmds.ls(grp, long=True)[0], [floor, wall, beam, gb, g1, g2]


def run():
    tb = load_toolbox()
    cmds.undoInfo(state=True, infinity=True)
    sn = tb["short_name"]
    cmds.file(new=True, force=True)
    grp, nodes = yard()

    # --- a group from a Maya group, one layer
    t0 = time.time()
    rep = tb["create_scatter_group"]([grp], "Leaves", {"leaves": 20.0, "coverage": 0.8, "slope": 35.0})
    dt = time.time() - t0
    root = rep["root"]
    data = tb["sc_data"](root)
    parts = tb["sc_parts"](root)
    check("a scatter group grows leaves", rep["leaves"] > 100, "%d leaves, %.2fs" % (rep["leaves"], dt))
    check("it's named scatteredObjects0001_GRP, its box _CTL", sn(root) == "scatteredObjects0001_GRP" and
          sn(tb["sc_box"](root)) == "scatteredObjects0001_CTL")
    check("the new group is left selected", cmds.ls(selection=True, long=True) == [root],
          str(cmds.ls(selection=True)))
    check("its part is named after its material", sorted(sn(n) for n in parts.values()) ==
          ["leafDry_C_scatteredObjects0001_GEP"], str([sn(n) for n in parts.values()]))
    check("a Maya group's meshes are all surfaces", len(tb["sc_surfaces"](data)) == 6,
          str([sn(n) for n in tb["sc_surfaces"](data)]))
    lpts = points(tb, parts[data["layers"][0]["id"] + "/litter"])
    surf = tb["_MiSurface"](nodes)
    on_wall = 0
    for p in lpts[::7]:
        c = surf.closest(p)
        if c and c[0] < 0.3 and abs(c[2][1]) < 0.5 and 2.5 < p[1] < 14.5:  # up a wall's face (not at its foot)
            on_wall += 1
    check("no leaves up the wall (Slope limit 35)", on_wall <= 0.01 * len(lpts[::7]), "%d of %d" % (
        on_wall, len(lpts[::7])))
    bb = cmds.exactWorldBoundingBox(tb["sc_box"](root))
    lb = cmds.exactWorldBoundingBox(list(parts.values()))
    check("the box sits round what grew", all(abs(bb[k] - lb[k]) < 0.05 * max(1.0, abs(lb[k3] - lb[k3 - 3]))
                                              for k, k3 in zip(range(6), (3, 4, 5, 3, 4, 5))), str(bb))

    # --- a crate added to the Maya group later is used at the next regrow
    crate = box("crate", (6, 6, 6), (12, 3, -5), grp)
    rep = tb["sc_regrow"](root)
    check("a mesh added to the Maya group is used", rep["surfaces"] == 7, str(rep["surfaces"]))

    # --- moss layer: only parts with something in them
    before = cmds.undoInfo(q=True, undoName=True)
    rep, moss = tb["sc_add_layer"](root, "Moss", {"strands": 0.0, "capsules": 0.0, "coverage": 0.6})
    names = sorted(sn(n) for k, n in tb["sc_parts"](root).items() if k.startswith(moss + "/"))
    check("a moss layer makes only parts that hold something", names == ["mossGreen_C_scatteredObjects0001_GEP"],
          str(names))
    rep, moss2 = tb["sc_add_layer"](root, "Moss", {"strands": 1.0, "capsules": 0.5, "coverage": 0.3, "slope": 20.0})
    names2 = sorted(sn(n) for k, n in tb["sc_parts"](root).items() if k.startswith(moss2 + "/"))
    check("a second moss layer gets its own parts", names2 and all("2_C_scatteredObjects0001_GEP" in n
                                                                   for n in names2), str(names2))
    allp = tb["sc_parts"](root)
    seen, clash = {}, []
    for k, n in allp.items():
        for t in tiles(tb, n):
            if t in seen:
                clash.append((k, seen[t], t))
            seen[t] = k
    check("no two parts share a UDIM tile", not clash and len(seen) >= len(allp), str(clash or sorted(seen)))

    # --- live edits: out of the undo queue, only the edited layer rebuilds
    q0 = cmds.undoInfo(q=True, undoName=True)
    t0 = time.time()
    rep = tb["sc_update"](root, moss2, {"coverage": 0.45})
    dt_one = time.time() - t0
    check("a live edit stays out of the undo queue", cmds.undoInfo(q=True, undoName=True) == q0, str(q0))
    t0 = time.time()
    tb["_SC_BUILT"].clear()
    tb["sc_regrow"](root)
    dt_all = time.time() - t0
    check("a live edit rebuilds only its layer", dt_one < 0.8 * dt_all, "%.2fs vs %.2fs for all" % (dt_one, dt_all))

    # --- toggles, undo / redo
    tb["sc_set_layer"](root, moss, on=False)
    mnode = tb["sc_parts"](root)[moss + "/moss"]
    check("a layer turned off hides its parts", not cmds.getAttr(mnode + ".visibility"))
    cmds.undo()
    tb["sc_sync"]()
    check("one Ctrl+Z turns it back on", cmds.getAttr(mnode + ".visibility") and
          tb["sc_layer"](tb["sc_data"](root), moss)["on"])
    tb["sc_remove_layer"](root, moss2)
    check("Delete removes the layer and its parts", not any(k.startswith(moss2 + "/") for k in tb["sc_parts"](root)))
    cmds.undo()
    tb["sc_sync"]()
    back = [k for k in tb["sc_parts"](root) if k.startswith(moss2 + "/")]
    check("one Ctrl+Z brings it back", len(back) == len(names2) and tb["sc_layer"](tb["sc_data"](root), moss2))
    cmds.redo()
    tb["sc_sync"]()
    check("redo removes it again", not tb["sc_layer"](tb["sc_data"](root), moss2))
    rep, dup = tb["sc_add_layer"](root, None, copy_of=moss)
    dl = tb["sc_layer"](tb["sc_data"](root), dup)
    check("Duplicate copies a layer with a new seed", dl["type"] == "Moss" and dl["s"]["seed"] != tb["sc_layer"](
        tb["sc_data"](root), moss)["s"]["seed"] and dl["tag"] == "2", str((dl["name"], dl["tag"])))
    tb["sc_move_layer"](root, dup, -1)
    order = [l["id"] for l in tb["sc_data"](root)["layers"]]
    check("Up moves a layer up the list", order.index(dup) < order.index(moss), str(order))

    # --- leaf piles: drifts at the wall's foot and in the gutter
    def pile_points(creases):
        r, lid = tb["sc_add_layer"](root, "Leaf piles", {"piles": 3.0, "pile_size": 0.3, "coverage": 0.35,
                                                         "creases": creases, "patchiness": 0.2})
        pts = points(tb, tb["sc_parts"](root)[lid + "/piles"])
        tb["sc_remove_layer"](root, lid)
        return pts, r["piles"]

    t0 = time.time()
    with_c, n_with = pile_points(1.3)
    dt = time.time() - t0
    without, n_without = pile_points(0.0)

    def rect_dist(p, x0, x1, z0, z1):
        dx, dz = max(x0 - p[0], 0.0, p[0] - x1), max(z0 - p[2], 0.0, p[2] - z1)
        return math.sqrt(dx * dx + dz * dz)

    def near(pts):
        """Shares of pile leaves at a crease (within 2 dm of the foot of the
        wall, the beam, the gutter or the crate, or in the gutter) and in the
        gutter."""
        at = gutter = 0
        for p in pts:
            if p[1] > 1.6:
                continue
            inside = 7.3 < p[2] < 8.7 and -15 < p[0] < 15 and p[1] > 0.55
            gutter += inside
            d = min(p[2] + 13.0 if -20 < p[0] < 20 else 99.0,
                    rect_dist(p, -15, 15, 1.4, 2.6) or 99.0, rect_dist(p, -15, 15, 7.1, 8.9) or 99.0,
                    rect_dist(p, 9, 15, -8, -2) or 99.0)
            at += inside or d < 2.0
        return at / float(max(1, len(pts))), gutter / float(max(1, len(pts)))

    fw, gw = near(with_c)
    f0, g0 = near(without)
    check("leaf piles gather at creases (Creases)", 1.0 - fw < 0.65 * (1.0 - f0) and fw > 0.6,
          "%.0f%% of pile leaves at a wall / beam / gutter / crate foot vs %.0f%% without creases" % (
              100 * fw, 100 * f0))
    check("leaf piles gather in the gutter", gw > 0.03, "%.0f%% (%.0f%% without creases)" % (100 * gw, 100 * g0))
    foot = [p for p in with_c if -13.0 < p[2] < -10.5 and p[1] < 2.0]
    xs, zs = [p[0] for p in foot], [p[2] for p in foot]
    check("piles at the wall's foot drift along it", foot and (max(xs) - min(xs)) > 3.0 * (max(zs) - min(zs)),
          "along %.1f, across %.1f" % ((max(xs) - min(xs)) if xs else 0, (max(zs) - min(zs)) if zs else 0))
    check("leaf piles grow fast", dt < 8.0, "%.2fs, %d piles (%d without creases)" % (dt, n_with, n_without))
    inside = 0
    for p in with_c[::5]:
        c = surf.closest(p)
        if c and ((p[0] - c[1][0]) * c[2][0] + (p[1] - c[1][1]) * c[2][1] + (p[2] - c[1][2]) * c[2][2]) < -0.05:
            inside += 1
    check("pile leaves stay out of the geometry", inside <= 0.01 * len(with_c[::5]), "%d of %d" % (
        inside, len(with_c[::5])))

    # --- grass on a steep surface: none past the slope limit
    rep, gl = tb["sc_add_layer"](root, "Grass", {"grass": 3.0, "coverage": 0.9, "slope": 30.0})
    gpts = points(tb, tb["sc_parts"](root)[gl + "/grass"])
    high = sum(1 for p in gpts if -13.2 < p[2] < -12.0 and 3.0 < p[1] < 14.0)
    check("no grass up the wall", high <= 0.01 * len(gpts), "%d of %d" % (high, len(gpts)))

    # --- surfaces: remove one, add one (one Ctrl+Z each)
    tb["sc_set_surfaces"](root, remove=[grp], add=[crate, nodes[0]])
    check("surfaces can be swapped for single meshes", len(tb["sc_surfaces"](tb["sc_data"](root))) == 2)
    cmds.undo()
    tb["sc_sync"]()
    check("one Ctrl+Z puts the Maya group back", len(tb["sc_surfaces"](tb["sc_data"](root))) == 7)

    # --- new group undo / redo
    cmds.select(clear=True)
    rep2 = tb["create_scatter_group"]([nodes[0]], "Moss tufts")
    r2 = rep2["root"]
    check("a second group is scatteredObjects0002", sn(r2) == "scatteredObjects0002_GRP" and rep2["tufts"] > 5,
          "%d tufts" % rep2["tufts"])
    cmds.undo()
    check("one Ctrl+Z removes a new group", not cmds.objExists(r2))
    cmds.redo()
    done = tb["sc_sync"]()
    p2 = tb["sc_parts"](r2)
    check("redo brings it back, regrown", r2 in done and p2 and all(
        len(points(tb, n)) > 4 for n in p2.values()), str(done))

    # --- presets
    pr = tb["sc_preset"]("Leaf piles", "Gutters and wall bases")
    check("layer presets fill in the type's defaults", pr["creases"] == 1.3 and pr["slope"] == 30.0 and
          "grass" not in pr, str(sorted(pr)))

    # --- bake
    tb["sc_update"](root, dup, {"coverage": 0.0})
    hidden = [n for n in tb["sc_parts"](root).values() if not cmds.getAttr(n + ".visibility")]
    tb["bake_scatter"]([root])
    check("Bake drops the box and the empty parts", not tb["sc_box"](root) and not any(cmds.objExists(n)
                                                                                     for n in hidden) and
          not tb["is_scatter"](root) and hidden, "%d hidden" % len(hidden))
    cmds.undo()
    check("one Ctrl+Z undoes the bake", tb["is_scatter"](root) and tb["sc_box"](root))
    check("nothing left at the origin", all(len(points(tb, n)) > 4 for n in tb["sc_parts"](root).values()
                                            if cmds.getAttr(n + ".visibility")))


def drawing():
    """Scatter on a drawing: strokes over a dense ground and up a wall, no
    meshes selected."""
    tb = load_toolbox()
    sn = tb["short_name"]
    cmds.file(new=True, force=True)
    ground = cmds.ls(cmds.polyPlane(w=400, h=400, sx=150, sy=150, name="ground", constructionHistory=False)[0],
                     long=True)[0]
    wall = box("bigWall", (200, 15, 2), (0, 7.5, -31))
    box("farBox", (10, 10, 10), (150, 5, 150))
    gshape = tb["_log_shape"](ground)
    wshape = tb["_log_shape"](wall)
    line = [((x, 0.0, 0.0), gshape) for x in range(-100, 101, 2)]
    up = [((20.0, y * 0.5, -30.0), wshape) for y in range(1, 26)]

    def leaf_points(root, lid, part="litter"):
        node = tb["sc_parts"](root).get(lid + "/" + part)
        return points(tb, node) if node and cmds.getAttr(node + ".visibility") else []

    cmds.select(clear=True)
    t0 = time.time()
    rep = tb["create_scatter_group"]([], "Leaves", {"leaves": 30.0, "coverage": 0.8, "draw_width": 0.5,
                                                    "draw_falloff": 0.5, "draw_follow": 0.0}, drawing=[line])
    dt = time.time() - t0
    root = rep["root"]
    data = tb["sc_data"](root)
    lid = data["layers"][0]["id"]
    check("a drawing makes a group on the meshes under it, nothing selected",
          [sn(n) for n in tb["sc_surfaces"](data)] == ["ground"] and tb["sc_area"](data["layers"][0])[2] == 1,
          str([sn(n) for n in tb["sc_surfaces"](data)]))
    pts = leaf_points(root, lid)
    off = [p for p in pts if abs(p[2]) > 6.0 or abs(p[0]) > 106.0]
    check("leaves only along the drawing (Width 0.5 m)", pts and len(off) <= 0.005 * len(pts),
          "%d of %d off it" % (len(off), len(pts)))
    check("they fill it", rep["leaves"] > 150, "%d leaves" % rep["leaves"])
    inner = sum(1 for p in pts if abs(p[2]) < 1.5) / 1.5
    outer = sum(1 for p in pts if 3.5 < abs(p[2]) < 5.0) / 1.5
    check("Falloff thins it out towards the edge", inner > 1.5 * max(1.0, outer), "%.0f vs %.0f" % (inner, outer))
    draw = tb["_MiDrawing"]([[p for p, _ in line]], 5.0, 0.5, 0.0, [ground])
    nf = cmds.polyEvaluate(ground, face=True)
    check("only the faces under the drawing are analysed", 0 < len(draw.faces.get(ground, ())) < 0.1 * nf,
          "%d of %d faces" % (len(draw.faces.get(ground, ())), nf))
    check("a drawing over a dense mesh grows fast", dt < 6.0, "%.2fs" % dt)

    tb["sc_update"](root, lid, {"draw_width": 1.0})
    pts = leaf_points(root, lid)
    check("a wider Width reaches further (live)", max(abs(p[2]) for p in pts) > 7.0,
          "%.1f" % max(abs(p[2]) for p in pts))
    tb["sc_update"](root, lid, {"draw_width": 0.5, "draw_falloff": 0.0})
    pts = leaf_points(root, lid)
    inner = sum(1 for p in pts if abs(p[2]) < 1.5) / 1.5
    outer = sum(1 for p in pts if 3.0 < abs(p[2]) < 4.5) / 1.5
    check("Falloff 0 is even out to a hard edge", outer > 0.6 * inner, "%.0f vs %.0f" % (inner, outer))

    cmds.move(50, 0, 0, ground, relative=True)
    tb["sc_regrow"](root)
    pts = leaf_points(root, lid)
    check("the drawing follows its mesh", pts and min(p[0] for p in pts) > -56.0 and max(p[0] for p in pts) > 145.0,
          "x %.1f..%.1f" % (min(p[0] for p in pts), max(p[0] for p in pts)))
    cmds.move(-50, 0, 0, ground, relative=True)
    tb["sc_regrow"](root)

    # --- a stroke up a wall: leaves stay at its foot, moss climbs it; the wall joins the surfaces
    rep, wl = tb["sc_add_layer"](root, "Leaves", {"leaves": 30.0, "coverage": 0.9, "draw_follow": 0.0},
                                 drawing=[up])
    check("a mesh drawn on joins the surfaces (same Ctrl+Z)",
          sorted(sn(n) for n in tb["sc_surfaces"](tb["sc_data"](root))) == ["bigWall", "ground"])
    high = [p for p in leaf_points(root, wl) if p[1] > 2.0]
    check("leaves don't climb a wall drawn on (Slope limit)", not high, "%d up the wall" % len(high))
    rep, ml = tb["sc_add_layer"](root, "Moss", {"coverage": 0.8, "draw_follow": 0.0, "strands": 0.0,
                                                "capsules": 0.0}, drawing=[up])
    mpts = leaf_points(root, ml, "moss")
    check("moss grows up the wall along the stroke", mpts and max(p[1] for p in mpts) > 9.0 and
          all(abs(p[0] - 20.0) < 7.0 for p in mpts), "top %.1f" % (max(p[1] for p in mpts) if mpts else 0))
    cmds.undo()
    tb["sc_sync"]()
    check("one Ctrl+Z takes the drawn moss layer away", len(tb["sc_data"](root)["layers"]) == 2)

    # --- Use Drawing / Clear Area
    other = [((x, 0.0, 60.0), gshape) for x in range(-40, 41, 2)]
    tb["sc_set_layer"](root, lid, drawing=[other, line])
    check("Use Drawing gives a layer new strokes", tb["sc_area"](tb["sc_layer"](tb["sc_data"](root), lid))[2] == 2 and
          any(p[2] > 54.0 for p in leaf_points(root, lid)))
    cmds.undo()
    tb["sc_sync"]()
    check("one Ctrl+Z puts the old drawing back",
          tb["sc_area"](tb["sc_layer"](tb["sc_data"](root), lid))[2] == 1 and
          not any(p[2] > 54.0 for p in leaf_points(root, lid)))
    rep, cp = tb["sc_add_layer"](root, None, copy_of=lid)
    check("Duplicate keeps the drawing", tb["sc_area"](tb["sc_layer"](tb["sc_data"](root), cp))[2] == 1)
    tb["sc_set_layer"](root, cp, area=([], {}), drawing=[])
    pts = leaf_points(root, cp)
    check("Clear Area lets it grow everywhere again", pts and max(abs(p[2]) for p in pts) > 50.0)

    # --- ivy: vines start along the drawing
    cmds.select(clear=True)
    foot = [((x, 0.0, -29.5), gshape) for x in range(-60, 61, 4)]
    rep = tb["create_scatter_group"]([wall], "Ivy", {"vines": 4, "length": 1.0}, drawing=[foot])
    check("ivy on a drawing starts its vines along it", rep["vines"] >= 4, "%d vines (branches too)" % rep["vines"])


try:
    run()
    drawing()
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
