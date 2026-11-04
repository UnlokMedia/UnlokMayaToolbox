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
parts. Jungle leaves: big single leaves in clusters of 1-3, green and dry
parts, lying on the surface, along a gutter. Removing a mesh inside the
Maya group leaves just it out (nothing grows on it), adding it puts it back.
Moss Style Clumps: separate cushions, lighter than the carpet. Specks:
tiny moss stars and dirt flakes stuck on a standing pane of glass.
Pause: edits are saved and nothing grows; Play grows each changed layer
once and is one Ctrl+Z. An old scatter opened again: one setting grows
only its layer; a live edit too big to grow quickly pauses.
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
    tb["sc_regrow"](root, readback=False)
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

    # --- leave one mesh of the Maya group out (the group stays), put it back
    beam = [n for n in nodes if "beam" in n][0]

    def on_beam():
        return sum(1 for node in tb["sc_parts"](root).values() if cmds.getAttr(node + ".visibility")
                   for p in points(tb, node)
                   if p[1] > 1.15 and 1.5 < p[2] < 2.5 and abs(p[0]) < 14.5)

    before = on_beam()
    tb["sc_set_surfaces"](root, remove=[beam])
    d = tb["sc_data"](root)
    meshes = tb["sc_surfaces"](d)
    check("Remove on a mesh inside a group leaves just it out of the group",
          len(meshes) == 6 and beam not in meshes and len(d["surfaces"]) == 1 and
          [k for _, _, k in tb["sc_surface_names"](d)] == ["group", "left out"],
          "%d meshes, %s" % (len(meshes), [k for _, _, k in tb["sc_surface_names"](d)]))
    after = on_beam()
    check("nothing grows on the mesh left out", before > 0 and after == 0, "%d -> %d points on it" % (before, after))
    cmds.undo()
    tb["sc_sync"]()
    check("one Ctrl+Z puts it back in", len(tb["sc_surfaces"](tb["sc_data"](root))) == 7 and on_beam() > 0)
    cmds.redo()
    tb["sc_sync"]()
    tb["sc_set_surfaces"](root, add=[beam])
    d = tb["sc_data"](root)
    check("adding it again puts it back in the group (not a surface of its own)",
          len(tb["sc_surfaces"](d)) == 7 and len(d["surfaces"]) == 1 and not d["exclude"], str(d["exclude"]))
    tb["sc_set_surfaces"](root, remove=[beam])
    tb["sc_set_surfaces"](root, remove=[grp])
    check("removing the group forgets what was left out of it", not tb["sc_data"](root)["exclude"])
    for _ in range(3):
        cmds.undo()
    tb["sc_sync"]()
    d = tb["sc_data"](root)
    check("Ctrl+Z steps back through them", len(tb["sc_surfaces"](d)) == 6 and len(d["exclude"]) == 1)
    cmds.undo()
    tb["sc_sync"]()

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


def leaf_shells(tb, node):
    """Each separate piece of a part's mesh: [points] (a Paddle / Broad leaf is one piece)."""
    fn = om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))
    pts = [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kWorld)]
    counts, ids = fn.getVertices()
    up = list(range(len(pts)))

    def find(a):
        while up[a] != a:
            up[a] = up[up[a]]
            a = up[a]
        return a

    k = 0
    for c in counts:
        r0 = find(ids[k])
        for i in ids[k + 1:k + c]:
            ri = find(i)
            if ri != r0:
                up[ri] = r0
        k += c
    groups = {}
    for i, p in enumerate(pts):
        groups.setdefault(find(i), []).append(p)
    return list(groups.values())


def jungle():
    """Big jungle leaves: single big leaves the size of a small pile, 1-3 to
    a cluster, green and dry ones in their own parts, lying on the yard
    (riding up a gutter's sides, along it), never up the wall."""
    tb = load_toolbox()
    sn = tb["short_name"]
    cmds.file(new=True, force=True)
    grp, nodes = yard()
    L = 4.5  # 0.45 m in decimetres

    t0 = time.time()
    rep = tb["create_scatter_group"]([grp], "Jungle leaves", {"jungle": 1.5, "jungle_cluster": 1, "coverage": 0.6,
                                                              "jungle_shape": "Paddle", "jungle_size": 0.45,
                                                              "jungle_green": 0.5})
    dt = time.time() - t0
    root = rep["root"]
    lid = tb["sc_data"](root)["layers"][0]["id"]
    parts = tb["sc_parts"](root)
    check("a Jungle leaves layer grows big leaves", rep["jungle"] >= 6, "%d leaves, %.2fs" % (rep["jungle"], dt))
    check("green and dry leaves are their own parts", sorted(sn(n) for n in parts.values()) ==
          ["leafJungleDry_C_scatteredObjects0001_GEP", "leafJungle_C_scatteredObjects0001_GEP"],
          str(sorted(sn(n) for n in parts.values())))
    shells = leaf_shells(tb, parts[lid + "/green"]) + leaf_shells(tb, parts[lid + "/dry"])
    sizes = []
    for sh in shells:
        xs, zs = [p[0] for p in sh], [p[2] for p in sh]
        sizes.append(math.hypot(max(xs) - min(xs), max(zs) - min(zs)))
    sizes.sort()
    mid = sizes[len(sizes) // 2] if sizes else 0.0
    check("one leaf per cluster at Per cluster 1, each one piece", len(shells) == rep["jungle"],
          "%d pieces, %d leaves" % (len(shells), rep["jungle"]))
    check("each is big: about Leaf length (a small pile's size)", 0.75 * L < mid < 1.35 * L,
          "median %.2f dm across (Leaf length %.1f dm)" % (mid, L))
    pts = points(tb, parts[lid + "/green"]) + points(tb, parts[lid + "/dry"])
    surf = tb["_MiSurface"](nodes)
    inside = high = on_wall = 0
    for p in pts[::3]:
        c = surf.closest(p)
        if c is None:
            continue
        if tb["_rl_dot"](tb["_rl_sub"](p, c[1]), c[2]) < -0.05:
            inside += 1
        if c[0] > 0.3 * L:
            high += 1
        if abs(c[2][1]) < 0.5 and 4.0 < p[1] < 14.5 and p[2] < -12.0:
            on_wall += 1
    n3 = len(pts[::3])
    check("they lie on the surface, never in it", inside <= 0.01 * n3 and high <= 0.05 * n3,
          "%d of %d inside, %d floating" % (inside, n3, high))
    check("no big leaves up the wall", on_wall <= 0.01 * n3, "%d of %d" % (on_wall, n3))
    check("big leaves grow fast", dt < 6.0, "%.2fs" % dt)

    # --- 1 to 3 to a cluster
    base = rep["jungle"]
    made = {}
    for most in (1, 3):
        r3, l3 = tb["sc_add_layer"](root, "Jungle leaves", {"jungle": 2.0, "jungle_cluster": most, "coverage": 0.6,
                                                             "jungle_shape": "Paddle", "jungle_size": 0.45})
        made[most] = r3["jungle"] - base
        tb["sc_remove_layer"](root, l3)
    check("Per cluster 3 drops clusters of 1-3", 1.4 * made[1] < made[3] < 3.05 * made[1],
          "%d leaves vs %d single" % (made[3], made[1]))

    # --- all green: no dry part
    r1, l1 = tb["sc_add_layer"](root, "Jungle leaves", {"jungle": 1.5, "jungle_green": 1.0, "coverage": 0.6})
    p1 = tb["sc_parts"](root)
    check("Green 1: every leaf in the green part", (l1 + "/green") in p1 and (l1 + "/dry") not in p1,
          str(sorted(k for k in p1 if k.startswith(l1))))
    tb["sc_remove_layer"](root, l1)

    # --- every shape, every Detail
    counts = {}
    for shape in ("Paddle", "Broad", "Frond"):
        for detail in ("Proxy", "Normal", "Hero"):
            r, lx = tb["sc_add_layer"](root, "Jungle leaves", {"jungle": 1.0, "jungle_cluster": 1, "coverage": 0.6,
                                                               "jungle_shape": shape, "detail": detail,
                                                               "jungle_green": 1.0})
            node = tb["sc_parts"](root).get(lx + "/green")
            counts[(shape, detail)] = (cmds.polyEvaluate(node, vertex=True) if node else 0) / float(max(
                1, r["jungle"] - base))
            tb["sc_remove_layer"](root, lx)
    check("every shape builds, Detail adds points", all(counts[(s, "Proxy")] < counts[(s, "Normal")] <
                                                        counts[(s, "Hero")] for s in ("Paddle", "Broad", "Frond")),
          ", ".join("%s %s %d" % (s, d, counts[(s, d)]) for s, d in sorted(counts)))

    # --- along the gutter
    cmds.file(new=True, force=True)
    grp, nodes = yard()
    gutter = [n for n in nodes if "gutter" in n]
    rep = tb["create_scatter_group"](gutter, "Jungle leaves", {"jungle": 4.0, "jungle_cluster": 2, "coverage": 0.9,
                                                               "jungle_shape": "Paddle", "creases": 1.5,
                                                               "jungle_size": 0.45, "jungle_green": 1.0})
    root = rep["root"]
    lid = tb["sc_data"](root)["layers"][0]["id"]
    shells = leaf_shells(tb, tb["sc_parts"](root)[lid + "/green"])
    along = 0
    for sh in shells:
        xs, zs = [p[0] for p in sh], [p[2] for p in sh]
        along += (max(xs) - min(xs)) > 1.5 * (max(zs) - min(zs))
    check("in a gutter they lie along it", shells and along >= 0.7 * len(shells),
          "%d of %d along" % (along, len(shells)))
    ys = [p[1] for sh in shells for p in sh if 7.3 < p[2] < 8.7]
    check("riding up its sides, not through them", ys and min(ys) > 0.55, "lowest %.2f" % (min(ys) if ys else 0))


def moss_and_specks():
    """Moss Style Clumps: separate small cushions (lighter than the carpet),
    shoots on them, on the surface. Specks: tiny moss stars and dirt flakes
    stuck on a standing glass pane, both faces, never floating or inside."""
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    grp, nodes = yard()
    R = 0.6  # Clump size 0.06 m in decimetres
    base = {"coverage": 0.6, "slope": 35.0, "detail": "Normal"}
    rep = tb["create_scatter_group"]([grp], "Moss", dict(base))
    root = rep["root"]
    carpet_lid = tb["sc_data"](root)["layers"][0]["id"]
    carpet = cmds.polyEvaluate(tb["sc_parts"](root)[carpet_lid + "/moss"], face=True)
    t0 = time.time()
    rc, lid = tb["sc_add_layer"](root, "Moss", dict(base, style="Clumps"))
    dt = time.time() - t0
    parts = tb["sc_parts"](root)
    node = parts.get(lid + "/moss")
    shells = leaf_shells(tb, node) if node else []
    faces = cmds.polyEvaluate(node, face=True) if node else 0
    check("Style Clumps: separate moss cushions", rc["clumps"] >= 30 and len(shells) >= 30,
          "%d clumps, %d pieces, %.2fs" % (rc["clumps"], len(shells), dt))
    wide = 0.0
    for sh in shells:
        xs, ys, zs = [p[0] for p in sh], [p[1] for p in sh], [p[2] for p in sh]
        wide = max(wide, max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)))
    check("each cushion is about Clump size", wide < 5.0 * R, "widest %.2f dm (Clump size %.1f dm)" % (wide, R))
    check("lighter than the carpet", 0 < faces < carpet, "%d faces vs the carpet's %d" % (faces, carpet))
    check("shoots grow on the cushions", (lid + "/strands") in parts and
          cmds.polyEvaluate(parts[lid + "/strands"], vertex=True) > 100)
    surf = tb["_MiSurface"](nodes)
    inside = 0
    pts = points(tb, node)[::4] if node else []
    for p in pts:
        c = surf.closest(p)
        if c is not None and tb["_rl_dot"](tb["_rl_sub"](p, c[1]), c[2]) < -0.05:
            inside += 1
    check("the cushions sit on the surface, not in it", pts and inside <= 0.01 * len(pts),
          "%d of %d inside" % (inside, len(pts)))

    def floor_spread(extra):
        """Cushions (dome centres) on the floor counted in 2 dm cells: the
        index of dispersion (variance / mean) is about 1 for random, under 1
        for evenly spaced, well over 1 when they gather into groups."""
        t0 = time.time()
        rg, lg = tb["sc_add_layer"](root, "Moss", dict(base, style="Clumps", **extra))
        dt = time.time() - t0
        ng = tb["sc_parts"](root).get(lg + "/moss")
        counts = {}
        for sh in (leaf_shells(tb, ng) if ng else []):
            cx = sum(p[0] for p in sh) / len(sh)
            cy = sum(p[1] for p in sh) / len(sh)
            cz = sum(p[2] for p in sh) / len(sh)
            if cy < 0.4 and -20 < cx < 20 and -13 < cz < 7:
                k = (int((cx + 20) // 2), int((cz + 13) // 2))
                counts[k] = counts.get(k, 0) + 1
        vals = [counts.get((i, j), 0) for i in range(20) for j in range(10)]
        mean = sum(vals) / float(len(vals))
        var = sum((v - mean) ** 2 for v in vals) / float(len(vals))
        empty = sum(1 for v in vals if v == 0)
        tb["sc_remove_layer"](root, lg)
        return sum(vals), (var / mean if mean else 0.0), empty, dt  # the group report sums every layer

    n0, d0, e0, t0_ = floor_spread({"clump_group": 0.0})
    n1, d1, e1, t1_ = floor_spread({"clump_group": 1.0})
    check("Grouping: cushions gather into groups, bare gaps between",
          d1 > 1.5 * d0 and e1 > e0, "dispersion %.2f -> %.2f, empty cells %d -> %d, %d -> %d cushions on the floor" % (
              d0, d1, e0, e1, n0, n1))
    check("grouping costs next to nothing", t1_ < 1.5 * t0_ + 0.5, "%.2fs vs %.2fs" % (t1_, t0_))
    nl, _, _, _ = floor_spread({"clump_group": 1.0, "clump_pack": 0.0})
    nh, _, _, _ = floor_spread({"clump_group": 1.0, "clump_pack": 1.0})
    check("Packing crowds a group's cushions together", nh > 1.15 * nl, "%d -> %d cushions on the floor" % (nl, nh))
    ns, ds, _, _ = floor_spread({"clump_group": 1.0, "clump_group_size": 0.15})
    nb, db, _, _ = floor_spread({"clump_group": 1.0, "clump_group_size": 0.8})
    check("Group size: bigger groups and gaps", db > ds, "dispersion %.2f (0.15 m) -> %.2f (0.8 m)" % (ds, db))

    def floor_heights(extra):
        """Each floor cushion's height (the floor's top is y = 0), with its 2 dm cell."""
        flat = {"clump_hvar": 0.0, "clump_mounds": 0.0, "clump_ghvar": 0.0}
        flat.update(extra)
        rg, lg = tb["sc_add_layer"](root, "Moss", dict(base, style="Clumps", **flat))
        ng = tb["sc_parts"](root).get(lg + "/moss")
        out = []
        for sh in (leaf_shells(tb, ng) if ng else []):
            cx = sum(p[0] for p in sh) / len(sh)
            cz = sum(p[2] for p in sh) / len(sh)
            lo, hi = min(p[1] for p in sh), max(p[1] for p in sh)
            if -0.2 < lo < 0.2 and -20 < cx < 20 and -13 < cz < 7:
                out.append(((int((cx + 20) // 2), int((cz + 13) // 2)), hi))
        tb["sc_remove_layer"](root, lg)
        return out

    def cv(vals):
        m = sum(vals) / float(len(vals))
        return (sum((v - m) ** 2 for v in vals) / float(len(vals))) ** 0.5 / m if m else 0.0

    def cell_means(hs):
        cells = {}
        for k, h in hs:
            cells.setdefault(k, []).append(h)
        return [sum(v) / len(v) for v in cells.values() if len(v) >= 3]

    h0 = floor_heights({})
    h1 = floor_heights({"clump_hvar": 1.0})
    check("Height variation: cushions differ in height at random", h0 and h1 and cv([h for _, h in h1]) >
          1.3 * cv([h for _, h in h0]), "spread %.2f -> %.2f" % (cv([h for _, h in h0]), cv([h for _, h in h1])))
    hm = floor_heights({"clump_mounds": 0.6})

    def tall(hs):
        s = sorted(h for _, h in hs)
        return s[int(0.97 * (len(s) - 1))] / s[len(s) // 2]

    check("Mounds: a few rise well above the rest", hm and tall(hm) > 1.4 * tall(h0),
          "97th percentile %.2fx the median -> %.2fx" % (tall(h0), tall(hm)))
    hg = floor_heights({"clump_ghvar": 1.0})
    check("Group heights: whole groups taller or flatter", hg and cv(cell_means(hg)) > 1.5 * cv(cell_means(h0)),
          "spread between 2 dm cells %.2f -> %.2f" % (cv(cell_means(h0)), cv(cell_means(hg))))

    # --- specks on a pane of glass standing on the floor
    glass = box("glassPane", (12, 8, 0.1), (0, 4.0, 4.0), div=1.0)
    t0 = time.time()
    rs = tb["create_scatter_group"]([glass], "Specks", {"specks": 60.0})
    dt = time.time() - t0
    sroot = rs["root"]
    sl = tb["sc_data"](sroot)["layers"][0]["id"]
    sp = tb["sc_parts"](sroot)
    check("Specks: tiny moss and dirt bits stuck on glass", rs["specks"] >= 40 and
          sorted(k.split("/")[1] for k in sp) == ["dirt", "specks"], "%d specks, %s, %.2fs" % (
              rs["specks"], sorted(sp), dt))
    gs = tb["_MiSurface"]([glass])
    far = inside = front = back = 0
    allp = points(tb, sp[sl + "/specks"]) + points(tb, sp[sl + "/dirt"])
    for p in allp:
        c = gs.closest(p)
        if c is None:
            continue
        d = tb["_rl_dot"](tb["_rl_sub"](p, c[1]), c[2])
        if d < -0.002:
            inside += 1
        if tb["_rl_len"](tb["_rl_sub"](p, c[1])) > 0.12:
            far += 1
        if c[2][2] > 0.9:
            front += 1
        elif c[2][2] < -0.9:
            back += 1
    check("specks lie on the glass (never floating, never in it)", allp and far == 0 and inside == 0,
          "%d points: %d off it, %d in it" % (len(allp), far, inside))
    check("on both faces of the standing pane", front > 0 and back > 0, "%d front, %d back" % (front, back))
    size = 0.0
    for sh in leaf_shells(tb, sp[sl + "/dirt"]):
        xs, ys, zs = [p[0] for p in sh], [p[1] for p in sh], [p[2] for p in sh]
        size = max(size, max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)))
    check("they're tiny (about Speck size)", 0.0 < size < 0.12, "biggest flake %.3f dm" % size)
    r1, l1 = tb["sc_add_layer"](sroot, "Specks", {"specks": 30.0, "speck_dirt": 0.0})
    p1 = tb["sc_parts"](sroot)
    check("Dirt 0: moss specks only", (l1 + "/specks") in p1 and (l1 + "/dirt") not in p1,
          str(sorted(k for k in p1 if k.startswith(l1))))
    r2, l2 = tb["sc_add_layer"](sroot, "Specks", {"specks": 30.0, "detail": "High", "speck_dirt": 0.0})
    n_norm = cmds.polyEvaluate(p1[l1 + "/specks"], vertex=True) / float(max(1, r1["specks"] - rs["specks"]))
    n_high = cmds.polyEvaluate(tb["sc_parts"](sroot)[l2 + "/specks"], vertex=True) / float(
        max(1, r2["specks"] - r1["specks"]))
    check("High: a tiny shoot (stem and star), not just a star", n_high > n_norm, "%.1f vs %.1f points a speck" % (
        n_high, n_norm))


def pause():
    """Pause: edits are saved, nothing grows; Play grows each changed layer
    once, and one Ctrl+Z takes the paused edits back."""
    tb = load_toolbox()
    cmds.undoInfo(state=True, infinity=True)
    cmds.file(new=True, force=True)
    grp, nodes = yard()
    rep = tb["create_scatter_group"]([grp], "Leaves", {"leaves": 12.0, "coverage": 0.7})
    root = rep["root"]
    leaves = tb["sc_data"](root)["layers"][0]["id"]
    _, moss = tb["sc_add_layer"](root, "Moss", {"coverage": 0.4, "strands": 0.0, "capsules": 0.0})
    _, grass = tb["sc_add_layer"](root, "Grass", {"grass": 0.6, "coverage": 0.4})
    built = []
    real = tb["_sc_build_layer"]

    def counting(layer, surf):
        built.append(layer["id"])
        return real(layer, surf)

    tb["_sc_build_layer"] = counting

    def verts(lid, part):
        node = tb["sc_parts"](root).get(lid + "/" + part)
        return cmds.polyEvaluate(node, vertex=True) if node and cmds.getAttr(node + ".visibility") else 0

    json0 = cmds.getAttr(root + "." + tb["SC_ATTR"])
    v0 = (verts(leaves, "litter"), verts(moss, "moss"), verts(grass, "grass"))
    tb["sc_pause"]()
    t0 = time.time()
    r1 = tb["sc_update"](root, leaves, {"leaves": 30.0})
    tb["sc_update"](root, leaves, {"coverage": 0.9})
    dt = time.time() - t0
    s = tb["sc_settings"](tb["sc_layer"](tb["sc_data"](root), leaves))
    check("paused: edits are saved on the layer, nothing grows", r1.get("held") and not built and
          s["leaves"] == 30.0 and s["coverage"] == 0.9 and verts(leaves, "litter") == v0[0],
          "%d builds, %.3fs for 2 edits" % (len(built), dt))
    pend = tb["sc_pending"](root)
    check("the changed layer is known (and only it)", pend and pend[0] == set([leaves]) and not pend[1], str(pend))
    tb["sc_set_layer"](root, grass, on=False)
    gnode = tb["sc_parts"](root)[grass + "/grass"]
    check("turning a layer off while paused waits for Play too", not built and cmds.getAttr(gnode + ".visibility")
          and grass in tb["sc_pending"](root)[0])
    cmds.undo()
    tb["sc_sync"]()
    pend = tb["sc_pending"](root)
    check("Ctrl+Z while paused: nothing grows, the earlier edits stay pending", not built and
          tb["sc_layer"](tb["sc_data"](root), grass)["on"] and pend and pend[0] == set([leaves]), str(pend))
    tb["sc_update"](root, moss, {"coverage": 0.8})
    t0 = time.time()
    reps = tb["sc_play"]()
    dt = time.time() - t0
    check("Play grows each changed layer once (the others from the cache)",
          sorted(built) == sorted([leaves, moss]) and len(reps) == 1 and not tb["sc_paused"](),
          "%s, %.2fs" % (built, dt))
    v1 = (verts(leaves, "litter"), verts(moss, "moss"), verts(grass, "grass"))
    check("... and the parts show the edits", v1[0] > 1.5 * v0[0] and v1[1] > v0[1] and v1[2] == v0[2],
          "%s -> %s" % (v0, v1))
    check("nothing pending after Play", tb["sc_pending"](root) is None)
    check("Play is one step on the undo queue", cmds.undoInfo(q=True, undoName=True) == "Scatter play",
          cmds.undoInfo(q=True, undoName=True))
    cmds.undo()
    tb["sc_sync"]()
    check("one Ctrl+Z takes Play's edits back (and regrows)", verts(moss, "moss") == v0[1] and
          verts(leaves, "litter") == v1[0], "moss %d -> %d points" % (v1[1], verts(moss, "moss")))
    n = cmds.undoInfo(q=True, undoName=True)
    cmds.undo()
    tb["sc_sync"]()
    check("edits made before a paused undoable step are their own Ctrl+Z", n == "Scatter edits" and
          cmds.getAttr(root + "." + tb["SC_ATTR"]) == json0 and verts(leaves, "litter") == v0[0],
          "%s: %d -> %d leaf points" % (n, v1[0], verts(leaves, "litter")))
    cmds.redo()
    cmds.redo()
    tb["sc_sync"]()
    check("... and Ctrl+Y puts them back", verts(leaves, "litter") == v1[0] and verts(moss, "moss") == v1[1])

    # Regrow and new layers while paused; Bake grows what's pending first
    tb["sc_pause"]()
    del built[:]
    tb["sc_regrow_later"]([root])
    check("Regrow while paused waits for Play", not built and tb["sc_pending"](root) == (set(), True),
          str(tb["sc_pending"](root)))
    r2, ivy = tb["sc_add_layer"](root, "Moss tufts")
    check("a layer added while paused is pending, no parts yet", r2.get("held") and not built and
          not any(k.startswith(ivy + "/") for k in tb["sc_parts"](root)) and ivy in tb["sc_pending"](root)[0])
    tb["sc_update"](root, leaves, {"leaves": 8.0})
    tb["bake_scatter"]([root])
    check("Bake while paused grows the pending edits first", leaves in built and ivy in built and
          verts(leaves, "litter") < v1[0] and any(k.startswith(ivy + "/") for k in tb["sc_parts"](root)),
          str(built))
    tb["sc_play"]()
    tb["_sc_build_layer"] = real


def old_scatter():
    """A scatter made by an earlier version (its layers without the newer
    keys, nothing noted of what it grew from), saved and opened again in a
    new session: one setting grows only its layer (the others are read
    back from the scene, just as growing them would give), never the whole
    group (the user: "changed one setting and now it seems to have frozen
    Maya"). A mesh added to its surface group grows them all again. A live
    edit that would take a minute or more pauses instead."""
    tb = load_toolbox()
    cmds.undoInfo(state=True, infinity=True)
    cmds.file(new=True, force=True)
    grp, nodes = yard()
    root = tb["create_scatter_group"]([grp], "Moss", {"coverage": 0.5})["root"]
    moss = tb["sc_data"](root)["layers"][0]["id"]
    _, leaves = tb["sc_add_layer"](root, "Leaves", {"leaves": 12.0})
    _, grass = tb["sc_add_layer"](root, "Grass", {"grass": 0.6})
    data = tb["sc_data"](root)
    for layer in data["layers"]:  # as an earlier version stored it
        for k in [k for k in layer["s"] if k.startswith(("clump_", "jungle", "speck", "draw_")) or k == "style"]:
            del layer["s"][k]
        layer.pop("draw", None)
    data.pop("exclude", None)
    cmds.undoInfo(stateWithoutFlush=False)
    cmds.setAttr(root + "." + tb["SC_ATTR"], json.dumps(data, sort_keys=True), type="string")
    for attr in (tb["SC_GROWN"], tb["SC_COUNTS"], tb["SC_SURF"]):
        cmds.deleteAttr(root + "." + attr)
    cmds.undoInfo(stateWithoutFlush=True)
    path = os.path.join(tempfile.mkdtemp(), "old_scatter.ma")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaAscii", force=True)
    cmds.file(new=True, force=True)
    cmds.file(path, open=True, force=True)
    tb = load_toolbox()  # a new session: nothing cached
    cmds.undoInfo(state=True, infinity=True)
    built = []
    real = tb["_sc_build_layer"]

    def counting(layer, surf):
        built.append(layer["id"])
        return real(layer, surf)

    tb["_sc_build_layer"] = counting
    parts = [(moss, "moss"), (leaves, "litter"), (grass, "grass")]

    def verts():
        out = []
        for lid, part in parts:
            node = tb["sc_parts"](root).get(lid + "/" + part)
            out.append(cmds.polyEvaluate(node, vertex=True) if node else 0)
        return out

    def all_tiles():
        return dict((k, tiles(tb, n)) for k, n in tb["sc_parts"](root).items() if cmds.getAttr(n + ".visibility"))

    v0 = verts()
    t0 = time.time()
    rep = tb["sc_update"](root, leaves, {"coverage": 0.33})
    dt = time.time() - t0
    v1 = verts()
    check("an old scatter opened again: one setting grows only that layer", built == [leaves] and rep["read"] == 2,
          "%s grown, %d read back, %.2fs" % (built, rep["read"], dt))
    check("... the others stay as they were, the edit shows", v1[0] == v0[0] and v1[2] == v0[2] and v1[1] != v0[1],
          "%s -> %s" % (v0, v1))
    tb["sc_update"](root, grass, {"coverage": 0.31})
    tiles0, v2 = all_tiles(), verts()
    tb["_SC_BUILT"].clear()
    del built[:]
    tb["sc_regrow"](root, readback=False)
    check("reading back gives what growing it again does (meshes and UDIM tiles)",
          sorted(built) == sorted([moss, leaves, grass]) and verts() == v2 and all_tiles() == tiles0,
          "%s vs %s" % (v2, verts()))
    saved = json.loads(cmds.getAttr(root + "." + tb["SC_COUNTS"]))
    check("what it grew from and its counts are kept on the group (for the next session)",
          saved.get(moss, {}).get("clumps", 0) > 0 and cmds.getAttr(root + "." + tb["SC_GROWN"]) ==
          cmds.getAttr(root + "." + tb["SC_ATTR"]), str(saved.get(moss)))
    del built[:]
    crate = box("crate", (6, 6, 6), (12, 3, -5), tb["sc_surfaces"](tb["sc_data"](root))[0].rsplit("|", 1)[0])
    tb["sc_update"](root, leaves, {"coverage": 0.29})
    check("a mesh added to its surface group grows every layer again", sorted(built) == sorted([moss, leaves, grass]),
          "%s, crate %s" % (built, crate))

    # the budget: a live edit that would take a minute or more pauses, Play grows it anyway
    keep = tb["MOSS_WARN_CELLS"]
    tb["MOSS_WARN_CELLS"] = 1000
    v3 = verts()
    rep = tb["sc_update"](root, moss, {"coverage": 0.7})
    s = tb["sc_settings"](tb["sc_layer"](tb["sc_data"](root), moss))
    check("a live edit too big to grow quickly pauses instead (the edit is kept)", rep.get("stopped") and
          tb["sc_paused"]() and verts() == v3 and s["coverage"] == 0.7, str(rep.get("stopped")))
    tb["sc_play"]()
    check("... and Play grows it anyway", not tb["sc_paused"]() and verts()[0] != v3[0] and
          tb["sc_pending"](root) is None, "%s -> %s" % (v3, verts()))
    tb["MOSS_WARN_CELLS"] = keep
    tb["_sc_build_layer"] = real


try:
    run()
    drawing()
    jungle()
    moss_and_specks()
    pause()
    old_scatter()
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
