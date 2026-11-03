"""Headless tests for Moss and Ivy (mayapy).

    mayapy tests/test_moss_ivy.py

Moss on a roof slab with a gap between its boards, an inside corner where
it meets a wall, a thin rail and a steep wall: it favours the up-facing
and sheltered spots, keeps off the rail and the wall, never sits inside
geometry, its bed rolls over the boards' edges into the gap, the detail
tiers add shoots, capsules and hanging strands, and its parts take their
own UDIM tiles. Ivy on a post: vines
climb it, stay on its surface, leaves stay out of it, picked seeds follow
the post when it moves. Undo / redo (the redo regrows the seed planes),
live edits out of the undo queue, save / reopen, bake, tags, presets and
speed.
"""

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


def box(name, size, at):
    node = cmds.polyCube(w=size[0], h=size[1], d=size[2], sx=max(1, int(size[0] / 2)), sy=1,
                         sz=max(1, int(size[2] / 2)), name=name, constructionHistory=False)[0]
    cmds.move(at[0], at[1], at[2], node)
    return cmds.ls(node, long=True)[0]


def mesh_data(tb, node):
    fn = om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))
    pts = [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kWorld)]
    us, vs = fn.getUVs()
    return fn, pts, list(us), list(vs)


def tiles(fn):
    """UDIM tiles a mesh's faces are in (by each face's UV centre)."""
    us, vs = fn.getUVs()
    counts, ids = fn.getAssignedUVs()
    out, k = set(), 0
    for c in counts:
        u = sum(us[i] for i in ids[k:k + c]) / c
        v = sum(vs[i] for i in ids[k:k + c]) / c
        out.add(1001 + int(math.floor(u)) + 10 * int(math.floor(v)))
        k += c
    return sorted(out)


def part_tiles(tb, node):
    return tiles(mesh_data(tb, node)[0])


def inside_count(surf, pts, tol, show=0):
    """Points more than tol behind the nearest surface (inside the solid)."""
    bad = 0
    for p in pts:
        c = surf.closest(p)
        depth = (p[0] - c[1][0]) * c[2][0] + (p[1] - c[1][1]) * c[2][1] + (p[2] - c[1][2]) * c[2][2] if c else 0.0
        if depth < -tol:
            bad += 1
            if bad <= show:
                print("   inside by %.3f at (%.2f, %.2f, %.2f)" % (-depth, p[0], p[1], p[2]))
    return bad


def ledge_scene():
    """A roof slab of two boards with a 3 cm gap, a wall behind it (inside
    corner), a thin rail on the front, all in decimetres."""
    a = box("boardA", (20, 1, 6), (0, 10, -3.15))
    b = box("boardB", (20, 1, 6), (0, 10, 3.15))
    wall = box("wall", (20, 12, 1), (0, 16, -6.65))
    rail = box("rail", (20, 0.4, 0.4), (0, 10.7, 6.0))
    return [a, b, wall, rail]


def run():
    tb = load_toolbox()
    cmds.undoInfo(state=True, infinity=True)
    m = tb["scene_m_per_unit"]()
    check("the test scene is in decimetres", abs(m - 0.1) < 1e-9, str(m))

    # --- moss: where it grows
    cmds.file(new=True, force=True)
    nodes = ledge_scene()
    t0 = time.time()
    rep = tb["grow_moss_ivy"]("Moss", nodes, {"coverage": 0.5})
    dt = time.time() - t0
    root = rep["root"]
    parts = tb["mi_parts"](root)
    check("moss grows (clumps, all three parts)", rep["clumps"] > 20 and set(parts) == {"moss", "strands", "capsules"},
          "%d clumps, %d faces, %.2fs" % (rep["clumps"], rep["faces"], dt))
    check("moss grows fast", dt < 6.0, "%.2fs" % dt)
    names = sorted(tb["short_name"](x) for x in parts.values())
    check("part names follow the convention", names == ["mossGreen_C_mossPatch0001_GEP", "mossSpore_C_mossPatch0001_GEP",
                                                        "mossStrand_C_mossPatch0001_GEP"], str(names))
    surf = tb["_MiSurface"](nodes)
    s = tb["mi_settings_only"]("Moss", {"coverage": 0.5})
    clumps = tb["moss_clumps"](surf, tb["_MiSampler"](surf.nodes), s)
    top = [c for c in clumps if c[1][1] > 0.9 and c[0][1] < 11.0]  # the boards' tops (not the wall's)
    wall_open = [c for c in clumps if abs(c[1][2]) > 0.9 and c[0][1] > 11.5]
    on_rail = [c for c in clumps if c[0][2] > 5.7 and c[0][1] > 10.6]
    corner = [c for c in top if c[0][2] < -5.2]
    gap = [c for c in top if abs(c[0][2]) < 1.2]
    open_mid = [c for c in top if 1.5 < abs(c[0][2]) < 4.0]
    # moss area per unit area: the corner strip (z -6.15..-5.2) and the gap strip are ~1 unit wide, the open
    # strip 2.5 x 2 (cushion area, not count: sheltered cushions are bigger)
    def cover(cs):
        return sum(c[2] * c[2] for c in cs)
    dens_corner, dens_gap, dens_open = cover(corner) / 0.95, cover(gap) / 2.4, cover(open_mid) / 5.0
    check("moss prefers up-facing surfaces (few on the open wall)", len(top) > 5 * max(1, len(wall_open)),
          "%d up, %d on the open wall" % (len(top), len(wall_open)))
    check("moss gathers in the inside corner and the gap",
          dens_corner > 1.3 * dens_open and dens_gap > 1.1 * dens_open,
          "per unit width: corner %.1f, gap %.1f, open %.1f" % (dens_corner, dens_gap, dens_open))
    check("moss keeps off the thin rail", len(on_rail) <= 1, "%d on the rail" % len(on_rail))
    check("bigger clumps in sheltered spots",
          sum(c[2] for c in corner) / max(1, len(corner)) > sum(c[2] for c in open_mid) / max(1, len(open_mid)),
          "")
    fn, pts, us, vs = mesh_data(tb, parts["moss"])
    thick = 0.02 / m
    verts = len(pts)
    bad = inside_count(surf, pts, 0.2 * thick, show=8)
    check("the moss bed sits on the surface, not inside it", bad <= 0.01 * len(pts), "%d of %d" % (bad, len(pts)))
    in_gap = [p for p in pts if abs(p[2]) < 0.14 and 9.6 < p[1] < 10.45]
    check("the bed rolls over the boards' edges into the gap between them", len(in_gap) >= 10,
          "%d points down in the gap" % len(in_gap))
    # the inside corner's strip: full moss there (out in the open it's a thin fringe at this coverage)
    tops = [p[1] for p in pts if -6.1 < p[2] < -5.2 and abs(p[0]) < 8.0 and 10.5 < p[1] < 11.2]
    lift = sorted(y - 10.5 for y in tops)
    check("the bed is lumpy, about Thickness thick", lift and 0.3 * 0.25 / 10 < lift[len(lift) // 2] / 10 < 0.04 and
          lift[-1] > 1.6 * lift[len(lift) // 4], "lift metres: quarter %.4f, median %.4f, top %.4f" % (
              lift[len(lift) // 4] / 10, lift[len(lift) // 2] / 10, lift[-1] / 10) if lift else "none")
    check("moss UVs in 1001, strands in 1002, capsules in 1003", part_tiles(tb, parts["moss"]) == [1001] and
          part_tiles(tb, parts["strands"]) == [1002] and part_tiles(tb, parts["capsules"]) == [1003], "%s / %s / %s" % (
              part_tiles(tb, parts["moss"]), part_tiles(tb, parts["strands"]), part_tiles(tb, parts["capsules"])))
    check("moss UVs stay inside their tile", min(us) >= 0.0 and max(us) <= 1.0 and min(vs) >= 0.0 and max(vs) <= 1.0)
    for part, node in parts.items():
        shape = tb["_log_shape"](node)
        check("%s is tagged for the UV hand-off" % part,
              cmds.getAttr(shape + "." + tb["UV_READY_ATTR"]) and cmds.getAttr(shape + "." + tb["UV_STACKED_ATTR"]))
    lo = min(c[0][1] for c in clumps)
    check("no moss on undersides", lo > 9.4, "lowest clump at y %.2f" % lo)

    # --- coverage and other live edits are out of the undo queue
    before = cmds.undoInfo(q=True, undoName=True)
    low = tb["update_moss_ivy"]({root: {"coverage": 0.2}})
    check("lower coverage grows fewer clumps", 0 < low["clumps"] < rep["clumps"],
          "%d -> %d" % (rep["clumps"], low["clumps"]))
    check("live edits stay out of the undo queue", cmds.undoInfo(q=True, undoName=True) == before,
          "%s / %s" % (before, cmds.undoInfo(q=True, undoName=True)))
    t0 = time.time()
    tb["update_moss_ivy"]({root: {"coverage": 0.6}})
    check("re-scoring is quick (spots are cached)", time.time() - t0 < 1.5, "%.2fs" % (time.time() - t0))
    tb["update_moss_ivy"]({root: {"stacks": 3}})
    check("3 stacks: the bed in 1001, strands 1002-1004, capsules after them",
          part_tiles(tb, parts["moss"]) == [1001] and part_tiles(tb, parts["strands"]) == [1002, 1003, 1004] and
          part_tiles(tb, parts["capsules"]) == [1005, 1006, 1007],
          "%s / %s / %s" % (part_tiles(tb, parts["moss"]), part_tiles(tb, parts["strands"]),
                            part_tiles(tb, parts["capsules"])))
    tb["update_moss_ivy"]({root: {"stacks": 1, "udim": 1011}})
    check("Start UDIM moves every part", part_tiles(tb, parts["moss"]) == [1011] and
          part_tiles(tb, parts["strands"]) == [1012])
    counts = {}
    for detail in tb["MI_DETAILS"]:
        t0 = time.time()
        r = tb["update_moss_ivy"]({root: {"detail": detail}})
        counts[detail] = [mesh_data(tb, parts[p])[0].numPolygons if cmds.getAttr(parts[p] + ".visibility") else 0
                          for p in ("moss", "strands", "capsules")]
        print("   moss detail %s: %d faces (bed, strands, capsules %s) %.2fs" % (detail, r["faces"], counts[detail],
                                                                             time.time() - t0))
    check("Detail tiers: a finer bed and more standing out of it each step",
          counts["Proxy"][0] < counts["Normal"][0] < counts["High"][0] < counts["Hero"][0] and
          counts["Proxy"][1] == 0 == counts["Proxy"][2] and 0 < counts["Normal"][1] < counts["High"][1] and
          counts["Normal"][2] > 0, str(counts))
    tb["update_moss_ivy"]({root: {"detail": "Normal", "capsules": 0.0}})
    check("Capsules 0: no sporophytes", not cmds.getAttr(parts["capsules"] + ".visibility"))
    tb["update_moss_ivy"]({root: {"capsules": 0.3, "droop": 1.6, "strand_length": 0.02}})
    low = min(p[1] for p in mesh_data(tb, parts["strands"])[1])
    check("Hanging: strands hang down over the edges", low < 9.6, "lowest strand point y %.2f (boards' tops 10.5)" % low)
    tb["update_moss_ivy"]({root: {"droop": 0.5, "strand_length": 0.012}})

    # --- undo / redo (the redo regrows what Grow made: live edits aren't undoable)
    cmds.undo()
    check("one Ctrl+Z removes the moss", not cmds.objExists(root))
    cmds.redo()
    check("redo brings back the seed planes", cmds.objExists(root) and
          mesh_data(tb, tb["mi_parts"](root)["moss"])[0].numVertices == 4)
    stale = tb["rebuild_stale_moss_ivy"]()
    check("the panel's Redo job regrows them", stale == [root] and
          mesh_data(tb, tb["mi_parts"](root)["moss"])[0].numVertices == verts,
          "%d vs %d" % (mesh_data(tb, tb["mi_parts"](root)["moss"])[0].numVertices, verts))

    # --- save / reopen
    path = os.path.join(tempfile.gettempdir(), "unlok_moss_ivy_test.ma")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaAscii", force=True)
    cmds.file(path, open=True, force=True)
    root = tb["mi_systems"]()[0]
    check("moss survives save / reopen", mesh_data(tb, tb["mi_parts"](root)["moss"])[0].numVertices == verts)
    os.remove(path)

    # --- bake
    tb["bake_moss_ivy"]([root])
    check("bake makes plain meshes", not tb["mi_systems"]() and tb["mi_systems"](baked=True) == [root])
    cmds.undo()
    check("one Ctrl+Z undoes the bake", tb["mi_systems"]() == [root])

    # --- directed moss: a clump round each picked point, or only on picked faces
    cmds.file(new=True, force=True)
    nodes = ledge_scene()
    a, b = nodes[0], nodes[1]
    fn = om.MFnMesh(om.MSelectionList().add(a).getDagPath(0))
    tops = [f for f in range(fn.numPolygons) if fn.getPolygonNormal(f, om.MSpace.kWorld).y > 0.9]
    cmds.select(["%s.f[%d]" % (a, f) for f in tops])
    picks = tb["mi_moss_picks"]()
    check("picked faces are an area", picks[0] == [] and picks[1] == {a: tops}, str(picks)[:200])
    cmds.select(b + ".vtx[2:3]")
    check("picked vertices are clump centres", len(tb["mi_moss_picks"]()[0]) == 2)
    cmds.select(clear=True)
    surf = tb["_MiSurface"](nodes)
    sampler = tb["_MiSampler"](surf.nodes)
    s = tb["mi_settings_only"]("Moss", {"spread": 0.3})
    seed_pt = (0.0, 10.5, 3.15)  # the open middle of board B, where little grows on its own
    clumps = tb["moss_clumps"](surf, sampler, s, seeds=[seed_pt])
    far = max([math.sqrt(sum((c[0][k] - seed_pt[k]) ** 2 for k in range(3))) for c in clumps] or [0.0])
    near = [c for c in clumps if math.sqrt(sum((c[0][k] - seed_pt[k]) ** 2 for k in range(3))) < 1.0]
    check("a picked point grows a clump round it, out to Spread", len(clumps) > 10 and near and far < 4.5,
          "%d cushions, %d within 10 cm, furthest %.2f (Spread 3.0)" % (len(clumps), len(near), far))
    clumps = tb["moss_clumps"](surf, sampler, tb["mi_settings_only"]("Moss", {"coverage": 0.8}), faces={a: set(tops)})
    check("picked faces keep the moss to them", len(clumps) > 10 and
          all(c[0][1] > 10.45 and -6.2 < c[0][2] < -0.1 for c in clumps), "%d cushions" % len(clumps))
    rep = tb["grow_moss_ivy"]("Moss", nodes, {"coverage": 0.8}, faces={a: tops})
    root = rep["root"]
    again = tb["update_moss_ivy"]({root: {}})
    check("Regrow keeps the picked faces", again["clumps"] == rep["clumps"] and
          list(tb["mi_data"](root)["faces"].values()) == [tops], "%d / %d" % (rep["clumps"], again["clumps"]))
    bpts = mesh_data(tb, tb["mi_parts"](root)["moss"])[1]
    check("the bed keeps to the picked faces", bpts and all(p[2] < -0.1 and p[1] > 10.3 for p in bpts),
          "z %.2f..%.2f, lowest y %.2f" % (min(p[2] for p in bpts), max(p[2] for p in bpts), min(p[1] for p in bpts)))

    # --- ivy on a post
    cmds.file(new=True, force=True)
    post = cmds.ls(cmds.polyCylinder(r=1.0, h=25, sx=16, sy=10, name="post", constructionHistory=False)[0],
                   long=True)[0]
    cmds.move(0, 12.5, 0, post)
    t0 = time.time()
    rep = tb["grow_moss_ivy"]("Ivy", [post], {"vines": 4, "length": 2.2})
    dt = time.time() - t0
    root = rep["root"]
    parts = tb["mi_parts"](root)
    check("ivy grows (vines, leaves, both parts)", rep["vines"] >= 4 and rep["leaves"] > 50 and
          set(parts) == {"stems", "leaves"}, "%d vines, %d leaves, %d faces, %.2fs" % (
              rep["vines"], rep["leaves"], rep["faces"], dt))
    check("ivy grows fast", dt < 4.0, "%.2fs" % dt)
    names = sorted(tb["short_name"](x) for x in parts.values())
    check("ivy part names", names == ["ivyLeaf_C_ivy0001_GEP", "ivyStem_C_ivy0001_GEP"], str(names))
    fn, spts, us, vs = mesh_data(tb, parts["stems"])
    top = max(p[1] for p in spts)
    check("vines climb the post", top > 12.0, "top of the stems at y %.1f (post 0..25)" % top)
    radial = [math.hypot(p[0], p[2]) for p in spts if 0.5 < p[1] < 24.5]
    check("stems stay on the post's surface", radial and max(radial) < 1.6, "radius %.2f..%.2f" % (
        min(radial), max(radial)))
    stem_r = 0.006 / m
    bad = inside_count(tb["_MiSurface"]([post]), spts, 0.5 * stem_r, show=4)
    check("stems sink no deeper than half their radius", bad <= 0.01 * len(spts), "%d of %d" % (bad, len(spts)))
    check("stem UVs in 1001, leaves in 1002", part_tiles(tb, parts["stems"]) == [1001] and
          part_tiles(tb, parts["leaves"]) == [1002],
          "%s / %s" % (part_tiles(tb, parts["stems"]), part_tiles(tb, parts["leaves"])))
    surf = tb["_MiSurface"]([post])
    lpts = mesh_data(tb, parts["leaves"])[1]
    bad = inside_count(surf, lpts, 0.02)
    check("leaves stay out of the post", bad <= 0.01 * len(lpts), "%d of %d" % (bad, len(lpts)))
    check("leaves are stacked, stems laid out", cmds.getAttr(tb["_log_shape"](parts["leaves"]) + "." +
                                                             tb["UV_STACKED_ATTR"]) and not cmds.attributeQuery(
        tb["UV_STACKED_ATTR"], node=tb["_log_shape"](parts["stems"]), exists=True))
    us_ok = all(0.0 <= u - math.floor(u) <= 1.0 for u in us)
    check("stem UVs stay inside their tile", us_ok and min(vs) >= 0.0 and max(vs) <= 1.0,
          "v %.3f..%.3f" % (min(vs), max(vs)))
    for detail in tb["MI_DETAILS"]:
        r = tb["update_moss_ivy"]({root: {"detail": detail}})
        print("   ivy detail %s: %d faces" % (detail, r["faces"]))
    tb["update_moss_ivy"]({root: {"detail": "Normal"}})

    # --- picked seeds, and they follow the post
    cmds.select(post + ".vtx[16:19]")
    systems, targets, seeds = tb["mi_selection"]()
    check("selected vertices are seeds", targets == [post] and 1 <= len(seeds) <= 4, "%d seeds" % len(seeds))
    rep2 = tb["grow_moss_ivy"]("Ivy", targets, {"vines": 2, "length": 1.0}, seeds)
    pts0 = mesh_data(tb, tb["mi_parts"](rep2["root"])["stems"])[1]
    near = min(min(math.sqrt(sum((p[i] - q[i]) ** 2 for i in range(3))) for p in pts0) for q in seeds)
    check("vines start at the picked seeds", near < 1.0, "%.2f units" % near)
    cmds.move(30, 0, 0, post, relative=True)
    tb["update_moss_ivy"]({rep2["root"]: {}})
    pts1 = mesh_data(tb, tb["mi_parts"](rep2["root"])["stems"])[1]
    shift = sum(p[0] for p in pts1) / len(pts1) - sum(p[0] for p in pts0) / len(pts0)
    check("Regrow follows the post when it moves", abs(shift - 30) < 1.0, "moved %.2f" % shift)

    # --- presets live in an optionVar
    var = "unlokIvyPresets"
    old = cmds.optionVar(q=var) if cmds.optionVar(exists=var) else None
    try:
        tb["mi_save_preset"]("Ivy", "test vines", dict(tb["IVY_DEFAULTS"], vines=9))
        p = tb["mi_preset"]("Ivy", "test vines")
        check("user preset saves and loads", p and p["vines"] == 9 and "seed" not in tb["mi_user_presets"]("Ivy")[
            "test vines"])
        check("built-in preset fills in defaults", tb["mi_preset"]("Moss", "Thick carpet")["coverage"] == 0.85 and
              tb["mi_preset"]("Moss", "Thick carpet")["slope"] == tb["MOSS_DEFAULTS"]["slope"])
        check("user preset deletes", tb["mi_delete_preset"]("Ivy", "test vines") and
              tb["mi_preset"]("Ivy", "test vines") is None)
    finally:
        if old is None:
            cmds.optionVar(remove=var)
        else:
            cmds.optionVar(stringValue=(var, old))

    # --- debris: dry grass, dead leaves, leaf piles, moss tufts on the ledge
    cmds.file(new=True, force=True)
    nodes = ledge_scene()
    surf = tb["_MiSurface"](nodes)
    look = {"coverage": 0.6, "grass": 3.0, "leaves": 15.0, "piles": 0.6, "tufts": 12.0}
    t0 = time.time()
    rep = tb["grow_moss_ivy"]("Debris", nodes, look)
    dt = time.time() - t0
    root = rep["root"]
    parts = tb["mi_parts"](root)
    check("debris grows (grass bunches, leaves, piles, tufts; three parts)",
          rep["bunches"] >= 3 and rep["leaves"] > 40 and rep["piles"] >= 1 and rep["tufts"] > 5 and
          set(parts) == {"grass", "litter", "tufts"},
          "%d bunches, %d leaves, %d piles, %d tufts, %.2fs" % (rep["bunches"], rep["leaves"], rep["piles"],
                                                                rep["tufts"], dt))
    check("debris grows fast", dt < 8.0, "%.2fs" % dt)
    names = sorted(n.split("|")[-1] for n in parts.values())
    check("debris part names", names == ["grassDry_C_debris0001_GEP", "leafDry_C_debris0001_GEP",
                                         "mossTuft_C_debris0001_GEP"], str(names))
    check("every debris part is stacked and UV ready", all(
        cmds.getAttr(tb["_log_shape"](n) + "." + tb["UV_STACKED_ATTR"]) and
        cmds.getAttr(tb["_log_shape"](n) + "." + tb["UV_READY_ATTR"]) for n in parts.values()))
    check("grass UVs in 1001, leaves in 1002, tufts in 1003", part_tiles(tb, parts["grass"]) == [1001] and
          part_tiles(tb, parts["litter"]) == [1002] and part_tiles(tb, parts["tufts"]) == [1003], "%s / %s / %s" % (
              part_tiles(tb, parts["grass"]), part_tiles(tb, parts["litter"]), part_tiles(tb, parts["tufts"])))
    gpts = mesh_data(tb, parts["grass"])[1]
    lpts = mesh_data(tb, parts["litter"])[1]
    tpts = mesh_data(tb, parts["tufts"])[1]
    for name, pts in (("grass", gpts), ("leaves", lpts), ("tufts", tpts)):
        bad = inside_count(surf, pts, 0.03, show=4)
        check("%s stay out of the geometry" % name, bad <= 0.02 * len(pts), "%d of %d" % (bad, len(pts)))
    on_rail = [p for p in tpts + lpts if p[1] > 10.95 and 5.7 < p[2] < 6.3]
    check("debris keeps off the thin rail's top", len(on_rail) <= 0.02 * len(tpts + lpts), "%d" % len(on_rail))
    hang = [p for p in gpts if p[1] < 10.3]
    check("grass hangs over the edges (into the gap, over the front)", len(hang) > 10, "%d points below the tops" %
          len(hang))
    lift = sorted(p[1] - 10.5 for p in lpts if abs(p[2]) > 0.3 and abs(p[2]) < 5.8 and abs(p[0]) < 9.5)
    check("leaves lie on the boards, piles stand up a little",
          lift and lift[len(lift) // 4] < 0.06 and lift[-1] > 0.12,
          "lift (units): quarter %.3f, top %.3f" % (lift[len(lift) // 4], lift[-1]) if lift else "none")
    counts = []
    for det in tb["MI_DETAILS"]:
        b = tb["mi_build"]("Debris", nodes, dict(look, detail=det))
        counts.append((len(b["grass"][0]), len(b["litter"][0]), len(b["tufts"][0])))
    check("Detail tiers: more blades, finer leaves and tufts each step",
          all(a[i] < b[i] for a, b in zip(counts, counts[1:]) for i in range(3)), str(counts))
    b = tb["mi_build"]("Debris", nodes, dict(look, grass=0.0, piles=0.0))
    check("Grass bunches 0 and Leaf piles 0: none", not b["grass"][1] and b["piles"] == 0 and b["leaves_n"] > 20)
    tb["update_moss_ivy"]({root: {"tufts": 0.0}})
    check("an empty part is hidden", not cmds.getAttr(parts["tufts"] + ".visibility"))
    pick = (0.0, 10.5, -3.0)
    rep2 = tb["grow_moss_ivy"]("Debris", nodes, dict(look, spread=0.15, coverage=0.5), seeds=[pick])
    p2 = tb["mi_parts"](rep2["root"])
    allp = mesh_data(tb, p2["grass"])[1] + mesh_data(tb, p2["litter"])[1] + mesh_data(tb, p2["tufts"])[1]
    far = max(math.sqrt((p[0] - pick[0]) ** 2 + (p[2] - pick[2]) ** 2) for p in allp) if allp else 99.0
    check("a picked point gathers the debris round it", allp and far < 6.0, "farthest %.2f units" % far)
    check("Debris presets fill in defaults", tb["mi_preset"]("Debris", "Dry grass mat")["grass"] == 6.0 and
          tb["mi_preset"]("Debris", "Dry grass mat")["slope"] == tb["DEBRIS_DEFAULTS"]["slope"])


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
