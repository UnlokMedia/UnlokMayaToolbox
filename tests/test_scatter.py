"""Headless tests for scatter groups (mayapy).

    mayapy tests/test_scatter.py

A yard in decimetres under one Maya group: a floor, a wall standing on it,
a beam lying on it and a gutter (a U channel). A scatter group made from
the Maya group finds every mesh in it (and one added later), names its
parts scatteredObjects####, makes only parts that hold something, keeps
leaves off the wall, gathers leaf piles at the wall's foot and in the
gutter (drifts along them), gives every part its own UDIM tiles, and its
layers turn on / off, duplicate, move and delete with one Ctrl+Z each
(the undo / redo regrows what it built). New Group from This makes a
new empty group on the same surfaces (what's left out too), Duplicate
Group copies its layers with new seeds, one Ctrl+Z each. Live edits
stay out of the undo queue and only rebuild the layer edited; Bake drops the box and hidden
parts. Jungle leaves: big single leaves in clusters of 1-3, green and dry
parts, lying on the surface, along a gutter. Removing a mesh inside the
Maya group leaves just it out (nothing grows on it), adding it puts it back.
Moss Style Clumps: separate cushions, lighter than the carpet. Specks:
tiny moss stars and dirt flakes stuck on a standing pane of glass.
Drawn strokes one by one: listed with their meshes, Delete Stroke takes
just the picked ones out and only that layer grows again, Add Strokes
adds new ones, one Ctrl+Z each, saved while paused. Draw on: Surfaces
skips scatter, live or baked (even moved out of its group), Selected
draws only on the picked meshes, Everything on any; a surface group
never scatters onto baked parts moved into it (unless added by hand).
Ivy over a row of columns, two sunk into the floor: In all the vine
starts spread over most columns (low, above the floor), Per mesh every
column gets its own, Spacing 1 spreads them further than 0; Climb
variation gives vines different heights.
The box beside its group: dragged into a moved publish group the
scatter stays, an old group's box moves out, Ctrl+D copies, Make Box,
Draw on never on a box.
Pause: edits are saved and nothing grows; Play grows each changed layer
once and is one Ctrl+Z. An old scatter opened again: one setting grows
only its layer; a live edit too big to grow quickly pauses. Draft moss:
a quick rough look while editing, Full detail grows it properly. Height
fade: moss and ivy up columns from the foot, thinning out going up.
Dropped leaves: Leaves and Jungle leaves rest on corrugated roofs, a
glass roof's mullions, rails, a window lip, a step and each other without
sinking in or standing up, kept off a tall wall; Drape bends them over an
edge.
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
    check("a moss layer makes only parts that hold something", names == ["mossGreen_C_scatteredObjects0001_GES"],
          str(names))
    rep, moss2 = tb["sc_add_layer"](root, "Moss", {"strands": 1.0, "capsules": 0.5, "coverage": 0.3, "slope": 20.0})
    names2 = sorted(sn(n) for k, n in tb["sc_parts"](root).items() if k.startswith(moss2 + "/"))
    check("a second moss layer gets its own parts", names2 and all("2_C_scatteredObjects0001_GE" in n
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

    # --- a new group from this one: the same surfaces (and what's left out of them), blank or with its layers
    cmds.select(clear=True)  # (a selection is a Ctrl+Z step of its own)
    pre = tb["sc_data"](root)
    tb["sc_set_surfaces"](root, remove=[crate])
    src = tb["sc_data"](root)
    src_meshes = sorted(tb["sc_surfaces"](src))
    rep3 = tb["sc_new_group_from"](root)
    r3 = rep3["root"]
    d3 = tb["sc_data"](r3)
    check("New Group from This: a new group on the same surfaces, what's left out too, no layers",
          sn(r3) == "scatteredObjects0003_GRP" and d3["surfaces"] == src["surfaces"] and
          d3["exclude"] == src["exclude"] and d3["udim"] == src["udim"] and not d3["layers"] and
          not tb["sc_parts"](r3) and sorted(tb["sc_surfaces"](d3)) == src_meshes and crate not in src_meshes,
          "%s: %d surfaces, %d left out, %d layers" % (sn(r3), len(tb["sc_surfaces"](d3)), len(d3["exclude"]),
                                                       len(d3["layers"])))
    bb = cmds.exactWorldBoundingBox(tb["sc_box"](r3))
    sb = cmds.exactWorldBoundingBox(src_meshes)
    check("its box goes round those surfaces, and it's left selected",
          all(abs(bb[k] - sb[k]) < 0.5 for k in range(6)) and cmds.ls(selection=True, long=True) == [r3],
          "box %s, surfaces %s, selected %s" % (["%.1f" % v for v in bb], ["%.1f" % v for v in sb],
                                                cmds.ls(selection=True)))
    check("the group it came from is left as it was", tb["sc_data"](root) == src)
    check("it's one Ctrl+Z", cmds.undoInfo(q=True, undoName=True).startswith("New scatter group from"),
          cmds.undoInfo(q=True, undoName=True))
    rep, l3 = tb["sc_add_layer"](r3, "Moss tufts")
    check("Add Layer on it grows", rep["tufts"] > 5 and tb["sc_parts"](r3), "%d tufts" % rep["tufts"])
    rep4 = tb["sc_new_group_from"](root, layers=True)
    r4 = rep4["root"]
    d4 = tb["sc_data"](r4)
    pk = sorted(tb["sc_parts"](root))
    check("Duplicate Group: the same surfaces and every layer, each with a new seed",
          sn(r4) == "scatteredObjects0004_GRP" and d4["exclude"] == src["exclude"] and
          [(l["id"], l["type"], l["name"]) for l in d4["layers"]] ==
          [(l["id"], l["type"], l["name"]) for l in src["layers"]] and
          all(a["s"]["seed"] != b["s"]["seed"] for a, b in zip(d4["layers"], src["layers"])) and
          sorted(tb["sc_parts"](r4)) == pk and d4["next"] == src["next"],
          "%s: %s parts vs %s" % (sn(r4), sorted(tb["sc_parts"](r4)), pk))
    cmds.undo()
    check("one Ctrl+Z removes the duplicate, nothing else", not cmds.objExists(r4) and cmds.objExists(r3) and
          tb["sc_parts"](root) and tb["sc_data"](root) == src)
    cmds.redo()
    tb["sc_sync"]()
    check("redo brings it back, regrown", cmds.objExists(r4) and sorted(tb["sc_parts"](r4)) == pk and all(
        len(points(tb, n)) > 4 for n in tb["sc_parts"](r4).values() if cmds.getAttr(n + ".visibility")))
    cmds.undo()
    cmds.undo()  # the layer added
    cmds.undo()
    check("Ctrl+Z steps back past the new group", not cmds.objExists(r3) and cmds.objExists(root))
    cmds.undo()  # the crate back in
    tb["sc_sync"]()
    check("... and past leaving the crate out", tb["sc_data"](root) == pre, cmds.undoInfo(q=True, undoName=True))

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

    # --- strokes one by one (the user: "one of the ones I painted I don't want anymore ... how can I just
    # remove that?"): Delete Stroke, Add Strokes
    def lay():
        return tb["sc_layer"](tb["sc_data"](root), lid)

    third = [((x, 0.0, -60.0), gshape) for x in range(-40, 41, 2)]
    tb["sc_set_layer"](root, lid, drawing=[other, line, third])
    info = tb["sc_stroke_info"](lay())
    check("each stroke is listed with the meshes it's on", info == [(41, ["ground"]), (101, ["ground"]),
                                                                   (41, ["ground"])], str(info))
    wall_leaves = leaf_points(root, wl)
    tb["sc_delete_strokes"](root, lid, [1])
    rows = tb["_sc_drawing_rows"](lay())
    pts = leaf_points(root, lid)
    check("Delete Stroke takes just that one out, the others stay",
          len(rows) == 2 and abs(rows[0][0][2] - 60.0) < 0.01 and abs(rows[1][0][2] + 60.0) < 0.01 and
          not any(abs(p[2]) < 6.0 for p in pts) and any(p[2] > 54.0 for p in pts) and any(p[2] < -54.0 for p in pts),
          "%d strokes, %d leaves" % (len(rows), len(pts)))
    check("... and only that layer grows again", leaf_points(root, wl) == wall_leaves)
    check("it's one Ctrl+Z", cmds.undoInfo(q=True, undoName=True) == "Delete scatter strokes",
          cmds.undoInfo(q=True, undoName=True))
    cmds.undo()
    tb["sc_sync"]()
    check("one Ctrl+Z puts the stroke back", tb["sc_area"](lay())[2] == 3 and
          any(abs(p[2]) < 6.0 for p in leaf_points(root, lid)))
    tb["sc_set_layer"](root, lid, add_drawing=[up])
    d = lay()["draw"]
    check("Add Strokes adds to the drawing (the wall's stroke after the others)",
          tb["sc_area"](lay())[2] == 4 and len(d["t"]) == 2 and tb["sc_stroke_info"](lay())[3][1] == ["bigWall"],
          str(tb["sc_stroke_info"](lay())))
    tb["sc_delete_strokes"](root, lid, [0, 1, 2])
    d = lay()["draw"]
    check("deleting the ground's strokes leaves just the wall's (and forgets the ground)",
          len(d["k"]) == 1 and len(d["t"]) == 1 and tb["sc_stroke_info"](lay()) == [(len(up), ["bigWall"])],
          str(d.get("t")))
    cmds.undo()
    cmds.undo()
    tb["sc_sync"]()
    check("Ctrl+Z steps back through them", tb["sc_area"](lay())[2] == 3)
    tb["sc_pause"]()
    before = leaf_points(root, lid)
    tb["sc_delete_strokes"](root, lid, [0])
    check("paused, Delete Stroke saves it and grows nothing", tb["sc_area"](lay())[2] == 2 and
          leaf_points(root, lid) == before)
    cmds.undo()
    tb["sc_play"]()
    tb["sc_sync"]()
    check("... Ctrl+Z puts it back", tb["sc_area"](lay())[2] == 3)

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

    # --- along the gutter (inside 7.3 .. 8.7 wide, bottom 0.6, rims 1.7; sides 7.1 .. 7.3 and 8.7 .. 8.9):
    # leaves that fit in it lie along it (dropped across, they'd meet its sides); bigger ones rest on its rims
    def gutter_leaves(size, density, seed=0):
        cmds.file(new=True, force=True)
        grp, nodes = yard()
        gutter = [n for n in nodes if "gutter" in n]
        rep = tb["create_scatter_group"](gutter, "Jungle leaves", {"jungle": density, "jungle_cluster": 2,
                                                                   "coverage": 0.9, "jungle_shape": "Paddle",
                                                                   "creases": 1.5, "jungle_size": size,
                                                                   "jungle_green": 1.0, "seed": seed})
        root = rep["root"]
        lid = tb["sc_data"](root)["layers"][0]["id"]
        node = tb["sc_parts"](root).get(lid + "/green")
        return leaf_shells(tb, node) if node else []

    def in_sides(sh):
        return sum(1 for p in sh if (7.12 < p[2] < 7.28 or 8.72 < p[2] < 8.88) and 0.3 < p[1] < 1.68)

    shells = [sh for seed in (0, 2, 3, 4) for sh in gutter_leaves(0.2, 10.0, seed)]  # few fit: four seeds
    along = 0
    for sh in shells:
        xs, zs = [p[0] for p in sh], [p[2] for p in sh]
        along += (max(xs) - min(xs)) > 1.5 * (max(zs) - min(zs))
    check("in a gutter they lie along it", len(shells) >= 2 and along >= 0.7 * len(shells),
          "%d of %d along" % (along, len(shells)))
    ys = [p[1] for sh in shells for p in sh if 7.3 < p[2] < 8.7]
    check("riding up its sides, not through them", ys and min(ys) > 0.55 and not sum(in_sides(sh) for sh in shells),
          "lowest %.2f, %d points in its sides" % (min(ys) if ys else 0, sum(in_sides(sh) for sh in shells)))
    big = gutter_leaves(0.45, 10.0)
    check("bigger than it, they rest on its rims", big and not sum(in_sides(sh) for sh in big) and
          all(min(p[1] for p in sh if 7.1 < p[2] < 8.9) > 1.6 for sh in big if any(7.1 < p[2] < 8.9 for p in sh)),
          "%d leaves, %d points in its sides, lowest over it %s" % (
              len(big), sum(in_sides(sh) for sh in big),
              ", ".join("%.2f" % min([p[1] for p in sh if 7.1 < p[2] < 8.9] or [9]) for sh in big)))


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

    def counting(layer, surf, *rest, **kw):
        built.append(layer["id"])
        return real(layer, surf, *rest, **kw)

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

    def counting(layer, surf, *rest, **kw):
        built.append(layer["id"])
        return real(layer, surf, *rest, **kw)

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


def draft():
    """Moss speed (the user: "scattering moss is slowwwwwww, it takes ages
    to update"). A Strands / Droop / Capsules edit keeps the bed. Draft on:
    a moss edit grows a quick rough look (coarse bed, no strands) from the
    same patches, much faster, other layers as they were; it stays marked
    when the scene opens again; Full detail grows it just as a fresh full
    build does; Bake grows drafts properly first."""
    tb = load_toolbox()
    cmds.undoInfo(state=True, infinity=True)
    cmds.file(new=True, force=True)
    grp, nodes = yard()
    root = tb["create_scatter_group"]([grp], "Moss", {"coverage": 0.5})["root"]
    moss = tb["sc_data"](root)["layers"][0]["id"]
    _, leaves = tb["sc_add_layer"](root, "Leaves", {"leaves": 12.0, "on_moss": False})  # (not resting on it)
    keys = [moss + "/moss", moss + "/strands", leaves + "/litter"]

    def verts():
        parts = tb["sc_parts"](root)
        return [cmds.polyEvaluate(parts[k], vertex=True) if k in parts and cmds.getAttr(parts[k] + ".visibility")
                else 0 for k in keys]

    def bed_box():
        return cmds.exactWorldBoundingBox(tb["sc_parts"](root)[moss + "/moss"])

    beds = []
    Bed = tb["_MossBed"]
    real_build = Bed.build

    def counting(self):
        beds.append(1)
        return real_build(self)

    Bed.build = counting
    v0 = verts()
    tb["sc_update"](root, moss, {"strands": 1.6})
    v1 = verts()
    check("a Strands edit keeps the moss bed (only the strands grow again)",
          not beds and v1[0] == v0[0] and v1[1] != v0[1], "%s -> %s, bed built %d time(s)" % (v0, v1, len(beds)))
    t0 = time.time()
    tb["sc_update"](root, moss, {"strands": 1.0, "coverage": 0.45})
    t_full = time.time() - t0
    full = verts()
    box_full = bed_box()
    tb["sc_update"](root, moss, {"coverage": 0.5})

    tb["sc_set_draft"](True)
    tb["sc_update"](root, moss, {"coverage": 0.43})  # the first draft lays its coarse grid out
    t0 = time.time()
    tb["sc_update"](root, moss, {"coverage": 0.44})  # (0.45 grew in full just now: that comes from the cache)
    t_draft = time.time() - t0
    vd = verts()
    check("Draft: a moss edit grows a rough bed, much faster, no strands",
          tb["sc_drafted"](root) == [moss] and 0 < vd[0] < full[0] / 3 and vd[1] == 0 and t_draft < 0.6 * t_full,
          "%.2fs (full %.2fs), verts %s (full %s)" % (t_draft, t_full, vd, full))
    bd = bed_box()
    size = max(box_full[3] - box_full[0], box_full[5] - box_full[2])
    check("... the same patches in the same places, the leaves as they were",
          vd[2] == full[2] and max(abs(a - b) for a, b in zip(bd, box_full)) < 0.1 * size,
          "box %s vs %s" % ([round(v, 1) for v in bd], [round(v, 1) for v in box_full]))
    tb["sc_update"](root, leaves, {"coverage": 0.4})
    check("... another layer's edit leaves the draft a draft", tb["sc_drafted"](root) == [moss] and
          verts()[0] == vd[0], str(verts()))

    path = os.path.join(tempfile.mkdtemp(), "draft_scatter.ma")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaAscii", force=True)
    cmds.file(new=True, force=True)
    cmds.file(path, open=True, force=True)
    tb = load_toolbox()  # a new session: Draft off, nothing cached
    check("a draft stays marked when the scene opens again", tb["sc_drafted"](root) == [moss] and
          not tb["sc_drafting"]() and verts()[0] == vd[0], str(tb["sc_drafted"](root)))
    vr = verts()
    reps = tb["sc_full_detail"]([root])
    vf = verts()
    check("Full detail grows it properly (strands too), the leaves as they were", len(reps) == 1 and
          not tb["sc_drafted"](root) and vf[0] > vr[0] and vf[1] > 0 and vf[2] == vr[2], "%s -> %s" % (vr, vf))
    tb["_SC_BUILT"].clear()
    tb["sc_regrow"](root, readback=False)
    check("... just as a fresh full build does", verts() == vf, "%s vs %s" % (vf, verts()))

    tb["sc_set_draft"](True)
    tb["sc_update"](root, moss, {"coverage": 0.5})
    vd2 = verts()
    tb["bake_scatter"]([root])
    parts = dict((cmds.getAttr(tb["_log_shape"](n) + "." + tb["SC_PART"]), n)
                 for n in cmds.listRelatives(root, children=True, fullPath=True) or []
                 if tb["_log_shape"](n) and cmds.attributeQuery(tb["SC_PART"], node=tb["_log_shape"](n), exists=True))
    vb = [cmds.polyEvaluate(parts[k], vertex=True) if k in parts else 0 for k in keys]
    check("Bake grows a draft properly first", vd2[1] == 0 and vb[0] > vd2[0] and vb[1] > 0,
          "%s -> %s" % (vd2, vb))
    tb["sc_set_draft"](False)


COLS = {"A": (-20.0, 0.0), "B1": (-7.0, 4.0), "B2": (4.0, 4.0), "C": (18.0, -4.0)}


def colonnade():
    """A floor 6 x 3 m (top y = 0) and columns 3 m high (r 25 cm): A a
    cylinder; B1 and B2 one mesh (two pieces); C a base, shaft and capital,
    three meshes (base and capital 80 cm square, 30 cm high)."""
    grp = cmds.group(empty=True, name="colonnade_GRP")
    floor = box("floor", (60, 1, 30), (0, -0.5, 0), grp)

    def cyl(name, x, z, h=30.0, y0=0.0):
        c = cmds.polyCylinder(name=name, r=2.5, h=h, sx=24, sy=max(1, int(h / 2.5)), sc=1,
                              constructionHistory=False)[0]
        cmds.move(x, y0 + 0.5 * h, z, c)
        return c

    a = cyl("colA", *COLS["A"])
    b = cmds.polyUnite(cyl("colB1", *COLS["B1"]), cyl("colB2", *COLS["B2"]), constructionHistory=False,
                       name="colB")[0]
    x, z = COLS["C"]
    base = box("colC_base", (8, 3, 8), (x, 1.5, z), div=1.0)
    shaft = cyl("colC_shaft", x, z, h=24.0, y0=3.0)
    cap = box("colC_cap", (8, 3, 8), (x, 28.5, z), div=1.0)
    nodes = [floor] + [cmds.ls(cmds.parent(n, grp)[0], long=True)[0] for n in (a, b, base, shaft, cap)]
    return cmds.ls(grp, long=True)[0], nodes


def column_of(p):
    """Which column a point is on (None: the floor)."""
    if p[1] < 0.6:
        return None
    for k, (x, z) in COLS.items():
        dx, dz = p[0] - x, p[2] - z
        if (max(abs(dx), abs(dz)) <= 5.0) if k == "C" else (dx * dx + dz * dz <= 3.6 * 3.6):
            return k
    return None


def height_fade():
    """Height fade (the user: "moss and ivy growing up columns from the
    bottom fading out towards the top"): moss climbs every column from its
    foot and thins out up it, each piece of one mesh on its own, a base,
    shaft and capital (three meshes) as one column; by metres; from the
    top; leaves leave the column tops; ivy stops in the fade (each vine at
    its own height), leaves thinning out going up."""
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    grp, nodes = colonnade()
    root = tb["create_scatter_group"]([grp], "Moss", {"coverage": 0.6})["root"]
    moss = tb["sc_data"](root)["layers"][0]["id"]

    def spread(part):
        node = tb["sc_parts"](root).get(part)
        out = {k: [] for k in list(COLS) + [None]}
        if node and cmds.getAttr(node + ".visibility"):
            for p in points(tb, node):
                out[column_of(p)].append(p[1])
        return out

    def band(ys, lo, hi):
        return sum(1 for y in ys if lo <= y < hi)

    def short(sp):
        return " ".join("%s %d..%.1f" % (k, len(v), max(v) if v else 0.0) for k, v in sp.items() if k)

    off = spread(moss + "/moss")
    t0 = time.time()
    tb["sc_update"](root, moss, {"fade": "From base", "fade_part": 0.5, "fade_soft": 0.5})
    dt = time.time() - t0
    on = spread(moss + "/moss")
    check("From base: moss climbs every column from its foot (the Slope limit alone keeps it off)",
          all(band(on[k], 4.0, 15.0) >= max(40, 3 * band(off[k], 4.0, 15.0)) for k in COLS),
          "4..15: %s | off %s | on: %s (%.1fs)" % (" ".join("%s %d->%d" % (k, band(off[k], 4.0, 15.0), band(on[k], 4.0, 15.0)) for k in COLS), short(off), short(on), dt))
    check("... no higher than the fade (half way up)", all(on[k] and max(on[k]) < 16.0 for k in COLS), short(on))
    check("... thinning out going up", all(band(on[k], 0.6, 7.5) > band(on[k], 7.5, 15.0) > 0 for k in COLS),
          " ".join("%s %d/%d" % (k, band(on[k], 0.6, 7.5), band(on[k], 7.5, 15.0)) for k in COLS))
    x, z = COLS["C"]
    base_side = sum(1 for y in on["C"] if 1.8 <= y < 2.8)
    check("a base, shaft and capital (three meshes) fade as one column: the base is covered to its top",
          base_side >= 10, "%d moss points high on the base's sides" % base_side)
    check("the floor as it was", abs(len(on[None]) - len(off[None])) <= 0.1 * len(off[None]),
          "%d vs %d" % (len(on[None]), len(off[None])))

    tb["sc_update"](root, moss, {"fade_by": "Metres", "fade_height": 1.0, "fade_soft": 0.3})
    me = spread(moss + "/moss")
    check("Metres: the same 1 m on every column", all(me[k] and max(me[k]) < 11.0 for k in COLS), short(me))
    tb["sc_update"](root, moss, {"fade": "From top", "fade_by": "Object height", "fade_part": 0.3})
    top = spread(moss + "/moss")
    check("From top: moss on the top 30% of each column only",
          all(len(top[k]) >= 20 and min(top[k]) > 19.5 for k in COLS),
          " ".join("%s %d %.1f..%.1f" % (k, len(top[k]), min(top[k] or [0]), max(top[k] or [0])) for k in COLS))

    tb["sc_update"](root, moss, {"fade": "Off"})
    check("Off: as it was", spread(moss + "/moss") == off)
    _, leaves = tb["sc_add_layer"](root, "Leaves", {"leaves": 20.0, "coverage": 0.8})
    lo = spread(leaves + "/litter")
    tb["sc_update"](root, leaves, {"fade": "From base", "fade_part": 0.5})
    lf = spread(leaves + "/litter")
    up_off = sum(1 for k in COLS for y in lo[k] if y > 16.0)
    up_on = sum(1 for k in COLS for y in lf[k] if y > 16.0)
    check("Leaves: none on the column tops past the fade, the floor as it was",
          up_on == 0 and abs(len(lf[None]) - len(lo[None])) <= 0.1 * len(lo[None]),
          "on tops %d -> %d, floor %d -> %d" % (up_off, up_on, len(lo[None]), len(lf[None])))

    cols = nodes[1:]
    surf = tb["_MiSurface"](cols)
    seeds = [(COLS["A"][0] + 2.6, 0.3, COLS["A"][1]), (COLS["B1"][0] + 2.6, 0.3, COLS["B1"][1]),
             (COLS["B2"][0] - 2.6, 0.3, COLS["B2"][1]), (COLS["C"][0] + 4.1, 0.3, COLS["C"][1])]
    s = tb["sc_preset"]("Ivy", "Column base")
    s = tb["mi_settings_only"]("Ivy", dict(s, length=4.0))
    vf = tb["ivy_walk"](surf, seeds, s)
    vo = tb["ivy_walk"](surf, seeds, dict(s, fade="Off"))
    tops_f = [max(p[1] for p in v["pts"]) for v in vf]
    tops_o = [max(p[1] for p in v["pts"]) for v in vo]
    check("Ivy (Column base): vines stop in the fade, each at its own height",
          max(tops_f) < 22.0 and max(tops_o) > 25.0 and max(tops_f) - min(tops_f) > 3.0,
          "tops %s (no fade: up to %.1f)" % (sorted(round(t, 1) for t in tops_f), max(tops_o)))
    built = tb["ivy_build"](cols, s, seeds=seeds)
    ly = [p[1] for p in built["leaves"][0]]
    check("... leaves thinning out going up", built["leaves_n"] > 50 and band(ly, 0.0, 7.0) > band(ly, 7.0, 14.0) >
          band(ly, 14.0, 21.0), "%d leaves; leaf points %d / %d / %d" % (built["leaves_n"], band(ly, 0.0, 7.0),
                                                                        band(ly, 7.0, 14.0), band(ly, 14.0, 21.0)))


def drop_pitch(pts):
    """Degrees a piece's best-fit plane leans from level."""
    n = float(len(pts))
    cx, cy, cz = (sum(p[i] for p in pts) / n for i in range(3))
    xx = xz = zz = xy = zy = 0.0
    for x, y, z in pts:
        x, y, z = x - cx, y - cy, z - cz
        xx += x * x
        xz += x * z
        zz += z * z
        xy += x * y
        zy += z * y
    det = xx * zz - xz * xz
    if abs(det) < 1e-12:
        return 90.0
    a = (xy * zz - zy * xz) / det
    b = (zy * xx - xy * xz) / det
    return math.degrees(math.atan(math.sqrt(a * a + b * b)))


def leaf_pieces(tb, node):
    """A part's separate pieces in the order they were made: [(points, triangles of point indices)]."""
    fn = om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))
    pts = [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kWorld)]
    counts, ids = fn.getVertices()
    up = list(range(len(pts)))

    def find(a):
        while up[a] != a:
            up[a] = up[up[a]]
            a = up[a]
        return a

    faces, k = [], 0
    for c in counts:
        f = list(ids[k:k + c])
        faces.append(f)
        r0 = find(f[0])
        for i in f[1:]:
            ri = find(i)
            if ri != r0:
                up[ri] = r0
        k += c
    order, local = {}, {}
    for i in range(len(pts)):
        r = find(i)
        if r not in order:
            order[r] = ([], [])
        local[i] = len(order[r][0])
        order[r][0].append(pts[i])
    for f in faces:
        g = order[find(f[0])]
        for j in range(1, len(f) - 1):
            g[1].append((local[f[0]], local[f[j]], local[f[j + 1]]))
    return list(order.values())


def leaves_through_leaves(pieces, cell=0.25, found=None):
    """(How many pieces cross another - some of their points above its face
    and some under it (by more than 1 mm, seen from above, within 3 cm):
    one pushed through the other instead of lying on it, the deepest in
    decimetres)."""
    grid = {}
    for n, (pts, tris) in enumerate(pieces):
        for t in tris:
            a, b, c = pts[t[0]], pts[t[1]], pts[t[2]]
            for i in range(int(math.floor(min(a[0], b[0], c[0]) / cell)), int(math.floor(max(a[0], b[0], c[0]) / cell)) + 1):
                for k in range(int(math.floor(min(a[2], b[2], c[2]) / cell)),
                               int(math.floor(max(a[2], b[2], c[2]) / cell)) + 1):
                    grid.setdefault((i, k), []).append((n, (a, b, c)))
    bad, deep = 0, 0.0
    for n, (pts, tris) in enumerate(pieces):
        side = {}  # other piece -> [above, under, deepest under]
        for x, y, z in pts:
            for m, (a, b, c) in grid.get((int(math.floor(x / cell)), int(math.floor(z / cell))), ()):
                if m == n:
                    continue
                d = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
                if abs(d) < 1e-12:
                    continue
                w1 = ((b[2] - c[2]) * (x - c[0]) + (c[0] - b[0]) * (z - c[2])) / d
                w2 = ((c[2] - a[2]) * (x - c[0]) + (a[0] - c[0]) * (z - c[2])) / d
                w3 = 1.0 - w1 - w2
                if min(w1, w2, w3) < 0.0:
                    continue
                h = w1 * a[1] + w2 * b[1] + w3 * c[1]
                e = side.setdefault(m, [False, False, 0.0])
                if y > h + 0.01:
                    e[0] = True
                elif h - 0.3 < y < h - 0.01:
                    e[1] = True
                    e[2] = max(e[2], h - y)
        cross = [e[2] for e in side.values() if e[0] and e[1]]
        if found is not None:
            found.extend((n, m) for m, e in side.items() if e[0] and e[1])
        if cross:
            bad += 1
            deep = max(deep, max(cross))
    return bad, deep


def drop_scenes(tb):
    """{name: ([surface nodes], roof)}: a yard (floor 6 x 4 m, a tall wall at
    the back, a window lip 4 cm high, a stair step 15 cm, a grating of rails
    4 cm high 12 cm apart), corrugated roofs from the Roof tool (Clean,
    Makeshift), a glass roof (panes between mullions 4 cm proud, tilted 12
    degrees) and a ball."""
    out = {}
    yard_g = cmds.group(empty=True, name="dropYard_GRP")
    box("dropFloor", (60, 1, 40), (0, -0.5, 0), yard_g)
    box("tallWall", (60, 15, 1), (0, 7.5, -19.5), yard_g, div=3.0)
    box("windowLip", (24, 0.4, 0.5), (15, 0.2, -3), yard_g, div=1.0)
    box("stairStep", (24, 1.5, 4), (15, 0.75, 5), yard_g, div=1.0)
    for k in range(11):
        box("rail%d" % k, (20, 0.4, 0.4), (-15, 0.2, -6 + 1.2 * k), yard_g, div=1.0)
    out["yard"] = ([cmds.ls(yard_g, long=True)[0]], False)
    for i, mode in enumerate(("Clean", "Makeshift")):
        house = box("dropHouse%s" % mode, (24, 10, 16), (100.0 + 50.0 * i, 5.0, 0.0), div=8.0)
        rep = tb["make_thatch_roof"](house, {"covering": "Corrugated", "m_mode": mode, "overhang": 0.03,
                                             "shape": "Lean-to", "end_a": "Gable", "end_b": "Gable"})
        out["corrugated " + mode] = ([rep["root"]], True)
    g = cmds.group(empty=True, name="dropGlass_GRP")
    for ix in range(4):
        for iz in range(3):
            box("pane_%d_%d" % (ix, iz), (5.6, 0.06, 5.6), (-9.0 + ix * 6.0, 0.0, -6.0 + iz * 6.0), g, div=6.0)
    for ix in range(5):
        box("mullionX_%d" % ix, (0.4, 0.4, 18.4), (-12.0 + ix * 6.0, 0.17, 0.0), g, div=2.0)
    for iz in range(4):
        box("mullionZ_%d" % iz, (24.4, 0.4, 0.4), (0.0, 0.17, -9.0 + iz * 6.0), g, div=2.0)
    cmds.rotate(12, 0, 0, g)
    cmds.move(200.0, 20.0, 0.0, g)
    out["glass roof"] = ([cmds.ls(g, long=True)[0]], True)
    ball = cmds.polySphere(name="dropBall", r=6, sx=40, sy=30, constructionHistory=False)[0]
    cmds.move(260.0, 6.0, 0.0, ball)
    out["ball"] = ([cmds.ls(ball, long=True)[0]], None)
    return out


def dropped_leaves():
    """Dropped leaves (the user: leaves "conform to the surface instead of
    sitting on top", "clipping through the window frames", big leaves
    standing up "like towers" against a small step; "stop leaves clipping
    into the surface or clipping into each other"): Leaves and Jungle
    leaves rest on the highest things under them - the surface and the
    leaves laid before them - never into either, bridging corrugation
    troughs and rails, lying no steeper than about 45 degrees against a
    lip, kept off a tall wall; Drape bends them down over an edge."""
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    scenes = drop_scenes(tb)
    small = {"leaves": 30.0, "coverage": 0.85, "slope": 45.0}
    big = {"jungle": 3.0, "coverage": 0.85, "slope": 45.0}

    def under(surf, pts):
        for p in pts:
            hit = surf.ray(p, (0.0, 1.0, 0.0), 0.6)
            if hit is not None and hit[2][1] > 0.2:
                return p
        return None

    def held(surf, pts):  # every point has the surface close under it (not drooping over an edge)
        return all(surf.ray(p, (0.0, -1.0, 0.0), 1.0) is not None for p in pts[::3])

    def tall(pts):
        ext = math.hypot(max(p[0] for p in pts) - min(p[0] for p in pts), max(p[2] for p in pts) - min(p[2] for p in pts))
        return max(p[1] for p in pts) - min(p[1] for p in pts) > 1.2 * ext  # past 50 degrees

    def at(pts):
        n = float(len(pts))
        return "(%.1f, %.1f, %.1f)" % tuple(sum(p[i] for p in pts) / n for i in range(3))

    for name, (nodes, roof) in scenes.items():
        trs = (cmds.listRelatives(nodes, allDescendents=True, type="transform", fullPath=True) or []) + list(nodes)
        surf = tb["_MiSurface"]([t for t in trs if tb["_log_shape"](t)])
        root, times, parts = None, [], {}
        for typ, s in (("Leaves", small), ("Jungle leaves", big)):
            t0 = time.time()
            if root is None:
                root = tb["create_scatter_group"](nodes, typ, dict(s))["root"]
                lid = tb["sc_data"](root)["layers"][0]["id"]
            else:
                _, lid = tb["sc_add_layer"](root, typ, dict(s))
            times.append(time.time() - t0)
            for key, node in tb["sc_parts"](root).items():
                part = key.split("/")[1]
                if key.startswith(lid + "/") and part in ("litter", "green", "dry") and cmds.getAttr(node + ".visibility"):
                    parts[part] = leaf_pieces(tb, node)
        sm = [p[0] for p in parts.get("litter", [])]
        bg = [p[0] for p in parts.get("green", []) + parts.get("dry", [])]
        us = [u for u in (under(surf, p) for p in sm) if u]
        ub = [u for u in (under(surf, p) for p in bg) if u]
        check("Dropped leaves (%s): none into the surface" % name,
              len(sm) > 5 and len(us) <= max(1, len(sm) // 200) and not ub,
              "%d leaves (%d under), %d big pieces (%d under%s); %.1f s + %.1f s" % (
                  len(sm), len(us), len(bg), len(ub), (" at %.1f, %.1f, %.1f" % ub[0]) if ub else "", times[0], times[1]))
        thr = [leaves_through_leaves(parts.get("litter", []))]
        for shape in ("Paddle", "Broad"):  # one piece a leaf (a Frond's own leaflets overlap, as they grow)
            tb["sc_update"](root, lid, {"jungle_shape": shape})
            blades = []
            for key, node in tb["sc_parts"](root).items():
                if key.startswith(lid + "/") and key.split("/")[1] in ("green", "dry") and cmds.getAttr(node + ".visibility"):
                    blades += leaf_pieces(tb, node)
            thr.append(leaves_through_leaves(blades))
        through = sum(x[0] for x in thr)
        check("... none through another leaf (%s)" % name, through == 0,
              "%d leaves crossing another (%d small, %d Paddle, %d Broad; deepest %.1f mm)" % (
                  through, thr[0][0], thr[1][0], thr[2][0], 100.0 * max(x[1] for x in thr)))
        if roof is not None:  # (a ball's own slope is steeper than that)
            most = 52.0 if roof else 48.0
            ps = sorted((drop_pitch(p), at(p)) for p in sm if len(p) > 3 and held(surf, p))
            pb = sorted((drop_pitch(p), at(p)) for p in bg if len(p) > 3 and held(surf, p))
            ts, tb_ = sum(1 for p in sm if tall(p) and held(surf, p)), sum(1 for p in bg if tall(p) and held(surf, p))
            check("... lying no steeper than about 45 degrees, no towers (%s)" % name,
                  (ps[-1][0] if ps else 0) <= most and (pb[-1][0] if pb else 0) <= 45.0
                  and ts <= max(1, len(sm) // 100) and tb_ == 0,
                  "steepest leaf %.0f %s, big %.0f %s; standing up %d / %d" % (
                      ps[-1][0] if ps else 0, ps[-1][1] if ps else "", pb[-1][0] if pb else 0,
                      pb[-1][1] if pb else "", ts, tb_))
        if name == "yard":
            pts = [q for p in sm + bg for q in p]
            wall = [q for q in pts if q[2] < -18.4 and 1.0 < q[1] < 14.0]
            check("... nothing up the tall wall", not wall, "%d points up it" % len(wall))
            on = [p for p in bg if all(-25.0 < q[0] < -5.0 and -6.0 < q[2] < 6.0 for q in p)]
            low = min(min(q[1] for q in p) for p in on) if on else -1.0
            check("... big leaves across the rails rest on them (not down between)",
                  len(on) >= 2 and low > 0.25, "%d on the grating, lowest point %.2f (rail tops 0.4)" % (len(on), low))

    table = box("dropTable", (10, 1.5, 10), (320.0, 0.75, 0.0), div=1.0)
    root = tb["create_scatter_group"]([table], "Jungle leaves", {"jungle": 12.0, "coverage": 1.0, "jungle_green": 1.0,
                                                                 "drape": 0.0})["root"]
    lid = tb["sc_data"](root)["layers"][0]["id"]

    def over_edge():
        out = []
        for key, node in tb["sc_parts"](root).items():
            if key.startswith(lid + "/") and key.split("/")[1] in ("green", "dry") and cmds.getAttr(node + ".visibility"):
                out.extend(q[1] for q in points(tb, node) if not (315.0 < q[0] < 325.0 and -5.0 < q[2] < 5.0))
        return out

    stiff = over_edge()
    tb["sc_update"](root, lid, {"drape": 1.0})
    soft = over_edge()
    ms = sum(stiff) / len(stiff) if stiff else 0.0
    mf = sum(soft) / len(soft) if soft else 0.0
    check("Drape: leaves on a table bend down over its edge (Drape 0 stick out level)",
          len(stiff) > 10 and len(soft) > 10 and min(stiff) > 1.45 and mf < ms - 0.1,
          "overhanging points %d; mean height %.2f at Drape 0 (lowest %.2f), %.2f at Drape 1 (table top 1.5)" % (
              len(soft), ms, min(stiff) if stiff else 0, mf))

def draw_on():
    """Draw on: Surfaces skips scatter (live or baked, even moved out of its
    group), Selected draws only on the picked meshes, Everything on any; a
    surface group never scatters onto baked parts moved into it."""
    tb = load_toolbox()
    sn = tb["short_name"]
    cmds.file(new=True, force=True)
    grp = cmds.group(empty=True, name="yard_GRP")
    floor = box("floor", (40, 1, 30), (0, -0.5, 0), grp)
    crate = box("crate", (6, 6, 6), (8, 3, 4), grp)
    root = tb["create_scatter_group"]([grp], "Leaf piles", {"coverage": 0.8})["root"]
    tb["bake_scatter"]([root])
    baked = [n for n in cmds.listRelatives(root, children=True, type="transform", fullPath=True) or []]
    moved = cmds.ls(cmds.parent(baked[0], grp)[0], long=True)[0]
    live = tb["create_scatter_group"]([grp], "Moss tufts")["root"]
    check("a surface group never scatters onto baked scatter moved into it",
          sorted(sn(n) for n in tb["sc_surfaces"](tb["sc_data"](live))) == ["crate", "floor"],
          str([sn(n) for n in tb["sc_surfaces"](tb["sc_data"](live))]))
    tb["sc_set_surfaces"](live, add=[moved])
    check("... unless it's added by hand", moved in tb["sc_surfaces"](tb["sc_data"](live)))
    cmds.undo()
    drawer = tb["ScatterDrawer"]()

    def hits(mode, only=None):
        drawer.mode, drawer.only = mode, list(only or [])
        out = set()
        for dag in drawer._candidate_meshes():
            path = dag.fullPathName()
            out.add(sn(cmds.listRelatives(path, parent=True, fullPath=True)[0]))
        return sorted(out)

    got = hits("Surfaces")
    check("Draw on Surfaces: not on scatter, live or baked (even moved out of its group)", got == ["crate", "floor"],
          str(got))
    got = hits("Everything")
    check("Draw on Everything: baked scatter too (not a live group's)",
          "crate" in got and sn(moved) in got and len(got) == 2 + len(baked) and
          not any(sn(n) in got for n in tb["sc_parts"](live).values()), str(got))
    got = hits("Selected", tb["sc_draw_targets"]([crate]))
    check("Draw on Selected: only the meshes picked", got == ["crate"], str(got))
    check("... a group picked means every mesh in it", sorted(sn(cmds.listRelatives(s, parent=True)[0]) for s in
                                                            tb["sc_draw_targets"]([grp])) ==
          sorted(["crate", "floor", sn(moved)]))


def ivy_columns():
    """Ivy over a row of 8 columns, two sunk 20 cm into the floor (they used
    to take every vine start): In all, the starts spread over most columns,
    low on them and above the floor; Per mesh, every column gets its own;
    Spacing 1 starts them further apart than 0. Climb variation: vines up a
    wall reach different heights, some creeping low."""
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    floor = box("floor", (100, 1, 20), (0, -0.5, 0))
    xs = [-42 + 12 * i for i in range(8)]
    cols = []
    for i, x in enumerate(xs):
        c = cmds.polyCylinder(name="col%d" % i, r=2.0, h=25.0, sx=16, sy=10, sc=1, constructionHistory=False)[0]
        cmds.move(x, (-2.0 if i in (2, 5) else 0.0) + 12.5, 0, c)
        cols.append(cmds.ls(c, long=True)[0])
    surf = tb["_MiSurface"]([floor] + cols)
    sampler = tb["_MiSampler"](surf.nodes)

    def on(q):
        for i, x in enumerate(xs):
            if (q[0] - x) ** 2 + q[2] ** 2 <= 3.0 ** 2:
                return i
        return None

    def starts(count, spacing, per_mesh=False, seed=1):
        return tb["_ivy_auto_seeds"](surf, sampler, count, seed, spacing, None, per_mesh)

    for n in (8, 16):
        got = starts(n, 0.7)
        cs = [on(q) for q in got if on(q) is not None]
        check("In all, %d vines start over most of 8 columns (not crowded onto the two sunk ones)" % n,
              len(set(cs)) >= (6 if n == 8 else 7) and sum(1 for c in cs if c in (2, 5)) <= max(3, n // 4),
              "columns %s" % sorted(cs))
    got = starts(16, 0.7)
    col_y = [q[1] for q in got if on(q) is not None]
    check("they start low on the columns, above the floor (not inside it)",
          col_y and min(col_y) > -0.05 and max(col_y) < 3.5, "y %.2f..%.2f" % (min(col_y), max(col_y)))
    got = starts(2, 0.7, per_mesh=True)
    per = [on(q) for q in got]
    check("Per mesh: every column gets its own vines", all(per.count(i) == 2 for i in range(8)), str(sorted(
        c for c in per if c is not None)))

    def nearest(pts):
        return sum(min(tb["_rl_len"](tb["_rl_sub"](a, b)) for b in pts if b is not a) for a in pts) / len(pts)

    tight = sum(nearest(starts(12, 0.0, seed=s)) for s in range(1, 5)) / 4.0
    apart = sum(nearest(starts(12, 1.0, seed=s)) for s in range(1, 5)) / 4.0
    check("Spacing 1 starts vines further apart than Spacing 0", apart > 1.3 * tight,
          "mean nearest %.1f vs %.1f" % (apart, tight))
    rep = tb["create_scatter_group"](cols, "Ivy", {"vines": 2, "vines_by": "Per mesh", "length": 1.0})
    stems = [n for k, n in tb["sc_parts"](rep["root"]).items() if k.endswith("/stems")]
    grown = set(on(q) for n in stems for q in points(tb, n)) - {None}
    check("a Per mesh ivy layer grows on every column", grown == set(range(8)), str(sorted(grown)))

    # --- Climb variation: each vine its own Climb
    cmds.file(new=True, force=True)
    wall = box("ivyWall", (80, 30, 2), (0, 15, 0))
    surf = tb["_MiSurface"]([wall])
    seeds = tb["_ivy_auto_seeds"](surf, tb["_MiSampler"](surf.nodes), 14, 3, 1.0)

    def tops(var):
        s = tb["mi_settings_only"]("Ivy", {"vines": 14, "length": 1.4, "climb": 0.75, "climb_var": var,
                                           "branching": 0.0, "seed": 3})
        return [max(q[1] for q in v["pts"]) for v in tb["ivy_walk"](surf, seeds, s) if v["gen"] == 0]

    def spread(v):
        m = sum(v) / len(v)
        return math.sqrt(sum((x - m) ** 2 for x in v) / len(v))

    even, varied = tops(0.0), tops(1.0)
    check("Climb variation: vines reach different heights, some creeping low",
          spread(varied) > 1.3 * spread(even) and min(varied) < min(even),
          "height spread %.1f vs %.1f, lowest top %.1f vs %.1f" % (spread(varied), spread(even), min(varied),
                                                                    min(even)))


def box_outside():
    """The box sits beside its group, linked both ways (the user: "move
    them into my publish thing without having to move the bounding boxes
    out of them"): the group dragged under a moved, rotated, scaled
    publish group keeps its scatter where it was, and regrows on its
    surfaces when everything moves together; an old group (box inside,
    locked) is brought up to date the first time it regrows; Ctrl+D
    copies get a box of their own (undoing the copy takes it away); a
    deleted box: still grows, Make Box brings it back; New Group from This
    and Duplicate Group have theirs beside them; Draw on never lands on a
    box, a surface group never scatters onto one."""
    tb = load_toolbox()
    sn = tb["short_name"]
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    grp = cmds.group(empty=True, name="yard_GRP")
    floor = box("floor", (30, 1, 20), (0, -0.5, 0), grp)
    box("crate", (6, 6, 6), (6, 3, 2), grp)
    root = tb["create_scatter_group"]([grp], "Leaf piles", {"coverage": 0.8})["root"]
    bx = tb["sc_box"](root)
    locked = [a for a in ("tx", "ry", "sz") if cmds.getAttr(root + "." + a, lock=True)]
    check("the box is beside the group, not in it, linked both ways",
          bx and not cmds.listRelatives(bx, parent=True) and
          bx not in (cmds.listRelatives(root, children=True, fullPath=True) or []) and
          tb["sc_owner"](bx) == (root, None), "%s | %s" % (bx, tb["sc_owner"](bx)))
    check("the group's move / rotate / scale aren't locked", not locked, str(locked))

    def world_pts():
        out = []
        for node in tb["sc_parts"](root).values():
            if cmds.getAttr(node + ".visibility"):
                out.extend(points(tb, node))
        return out

    def bbox(pts):
        return [min(q[k] for q in pts) for k in range(3)] + [max(q[k] for q in pts) for k in range(3)]

    def near(a, b, tol=0.05):
        return max(abs(x - y) for x, y in zip(a, b)) < tol

    before = bbox(world_pts())
    pub = cmds.group(empty=True, world=True, name="publish_GRP")
    cmds.xform(pub, translation=(10, 3, -4), rotation=(0, 30, 0), scale=(2, 2, 2))
    root = cmds.ls(cmds.parent(root, pub)[0], long=True)[0]
    check("dragged under a moved, rotated, scaled publish group, the scatter stays where it was",
          near(bbox(world_pts()), before) and tb["sc_box"](root) == bx and tb["sc_owner"](bx) == (root, None),
          "%s vs %s" % (bbox(world_pts()), before))
    rep = tb["sc_regrow"](root)
    check("... and regrows there in the same place", rep.get("faces") and near(bbox(world_pts()), before, 0.2),
          "%s vs %s" % (bbox(world_pts()), before))
    grp = cmds.ls(cmds.parent(grp, pub)[0], long=True)[0]
    cmds.xform(pub, translation=(14, 3, -4))
    moved = bbox(world_pts())
    tb["sc_regrow"](root)
    check("everything moved together: it regrows on the surfaces where they are now",
          near(bbox(world_pts()), moved, 0.2) and abs(moved[0] - before[0] - 4.0) < 0.2,
          "%s vs %s" % (bbox(world_pts()), moved))
    cmds.parent(root, world=True)
    cmds.parent(grp, world=True)
    cmds.delete(pub)
    root = cmds.ls("scatteredObjects0001_GRP", long=True)[0]
    grp = cmds.ls("yard_GRP", long=True)[0]

    # --- an old group: its box inside it, move / rotate / scale locked
    old = tb["create_scatter_group"]([grp], "Leaf piles", {"coverage": 0.5})["root"]
    obox = tb["sc_box"](old)
    cmds.xform(obox, translation=(1, 2, 3))
    obox = cmds.ls(cmds.parent(obox, old)[0], long=True)[0]
    for node, attr in ((old, tb["SC_BOX_ID"]), (obox, tb["SC_BOX_OF"])):
        cmds.deleteAttr(node + "." + attr)
    for a in ("translate", "rotate", "scale"):
        for ax in "XYZ":
            cmds.setAttr(old + "." + a + ax, lock=True)
    check("(an old group: its box inside it)", tb["sc_box"](old) == obox and tb["sc_owner"](obox) == (old, None))
    q0 = cmds.undoInfo(q=True, undoName=True)
    tb["sc_regrow"](old)
    nb = tb["sc_box"](old)
    check("an old group's box moves out beside it the first time it regrows, linked, not on the undo queue",
          nb and not cmds.listRelatives(nb, parent=True) and sn(nb) == sn(obox) and
          tb["sc_owner"](nb) == (old, None) and cmds.undoInfo(q=True, undoName=True) == q0,
          "%s | %s" % (nb, cmds.undoInfo(q=True, undoName=True)))
    check("... and the group is unlocked", not any(cmds.getAttr(old + "." + a, lock=True) for a in ("tx", "ry", "sz")))
    cmds.delete(old, nb)

    # --- Ctrl+D copies
    cmds.select(root)
    copy = cmds.ls(cmds.duplicate(root)[0], long=True)[0]
    check("a Ctrl+D copy has no box of its own yet (its link is the original's)",
          tb["sc_box"](copy) is None and tb["sc_box"](root) == bx)
    cb = tb["sc_fix_box"](copy)
    check("... the toolbox gives it one, linked, round its scatter", cb and cb != bx and
          tb["sc_owner"](cb) == (copy, None) and tb["sc_box"](root) == bx and tb["sc_owner"](bx) == (root, None),
          "%s %s" % (cb, tb["sc_owner"](cb or bx)))
    check("... and it grows like any group", tb["sc_regrow"](copy).get("faces"))
    cmds.undo()  # the Ctrl+D
    tb["sc_sync"]()
    check("undoing the Ctrl+D takes the box made for it away too", not cmds.objExists(copy) and
          not cmds.ls(cb) and tb["sc_box"](root) == bx)
    two = cmds.duplicate([root, bx], returnRootsOnly=True)
    copy2, box2 = [cmds.ls(n, long=True)[0] for n in two]
    got = tb["sc_fix_box"](copy2)
    check("the group and its box copied together: that copy is its box", got == box2 and
          tb["sc_owner"](box2) == (copy2, None) and tb["sc_owner"](bx) == (root, None), "%s vs %s" % (got, box2))
    cmds.delete(copy2, box2)

    # --- a deleted box
    cmds.delete(bx)
    rep = tb["sc_regrow"](root)
    check("a group whose box is deleted still grows", rep.get("faces") and tb["sc_box"](root) is None)
    made = tb["sc_remake_boxes"]([root])
    nb = tb["sc_box"](root)
    check("Make Box: one round it again, beside it, linked, one Ctrl+Z", made and nb and
          not cmds.listRelatives(nb, parent=True) and tb["sc_owner"](nb) == (root, None) and
          cmds.undoInfo(q=True, undoName=True) == "Scatter box", cmds.undoInfo(q=True, undoName=True))
    cmds.undo()
    check("... Ctrl+Z takes it away", tb["sc_box"](root) is None)
    cmds.redo()
    bx = tb["sc_box"](root)

    # --- New Group from This / Duplicate Group
    for layers in (False, True):
        new = tb["sc_new_group_from"](root, layers=layers)["root"]
        b = tb["sc_box"](new)
        check("%s: its box beside it, linked" % ("Duplicate Group" if layers else "New Group from This"),
              b and b != bx and not cmds.listRelatives(b, parent=True) and tb["sc_owner"](b) == (new, None))

    # --- never drawn on, never scattered onto
    drawer = tb["ScatterDrawer"]()
    for mode in ("Surfaces", "Everything"):
        drawer.mode, drawer.only = mode, []
        on = [cmds.listRelatives(d.fullPathName(), parent=True, fullPath=True)[0] for d in drawer._candidate_meshes()]
        check("Draw on %s: never on a group's box" % mode, not any(n.endswith("_CTL") for n in on),
              str([sn(n) for n in on]))
    bx = cmds.ls(cmds.parent(bx, grp)[0], long=True)[0]
    check("a box moved into a surface group isn't scattered onto",
          sorted(sn(n) for n in tb["sc_surfaces"](tb["sc_data"](root))) == ["crate", "floor"] and
          tb["sc_box"](root) == bx, str([sn(n) for n in tb["sc_surfaces"](tb["sc_data"](root))]))
    tb["bake_scatter"]([root])
    check("Bake still drops the box", not cmds.ls(bx))


try:
    box_outside()
    run()
    drawing()
    draw_on()
    ivy_columns()
    jungle()
    moss_and_specks()
    pause()
    old_scatter()
    draft()
    height_fade()
    dropped_leaves()
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
