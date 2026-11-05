"""Headless tests for the moss realism settings (mayapy).

    mayapy tests/test_moss_realism.py
    (UNLOK_OLD_TOOLBOX=<an older UnlokToolbox.py> also checks that moss
    without the new settings grows exactly as that one did)

Bare ridges keeps sharp ridges bare, Soft edges thins a patch's rim and
its shoots, Ragged outline frays the outlines, Stray tufts adds shoots just
outside the patches, Merge makes Clumps low and wide, Shoot shape Leafy
grows leafier instanced shoots, Floor spill keeps moss on a floor to the
foot of what stands on it, and leaves that Rest on moss land on top of it.
New Scatter layers get the realistic look; old layers (and Moss & Ivy)
keep theirs.
"""

import math
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def load_toolbox(path=TOOLBOX):
    ns = {"__name__": "unlok_test", "__file__": path}
    with open(path) as f:
        exec(compile(f.read(), path, "exec"), ns)
    return ns


def rock(name="rockGrey_C_test0001_GEP"):
    """A lumpy boulder ~6 dm across (decimetres)."""
    node = cmds.polySphere(r=3.0, sx=24, sy=16, ch=False, name=name)[0]
    cmds.scale(1.0, 0.7, 0.85, node)
    cmds.move(0, 1.6, 0, node)
    cmds.makeIdentity(node, apply=True)
    return cmds.ls(node, long=True)[0]


def block(name="woodPlank_C_test0001_GEP"):
    """A 6 dm block with sharp edges (its top edges are ridges)."""
    node = cmds.polyCube(w=6.0, h=6.0, d=6.0, sx=12, sy=12, sz=12, ch=False, name=name)[0]
    cmds.move(0, 3.0, 0, node)
    cmds.makeIdentity(node, apply=True)
    return cmds.ls(node, long=True)[0]


def floor(name="groundSoil_C_test0001_GEP", size=60.0):
    node = cmds.polyPlane(w=size, h=size, sx=30, sy=30, ch=False, name=name)[0]
    return cmds.ls(node, long=True)[0]


def boundary_edges(mesh):
    """How many edges of a mesh tuple are open (used by one face)."""
    counts, conn = mesh[1], mesh[2]
    seen, k = {}, 0
    for n in counts:
        ids = conn[k:k + n]
        k += n
        for a in range(n):
            e = (min(ids[a], ids[(a + 1) % n]), max(ids[a], ids[(a + 1) % n]))
            seen[e] = seen.get(e, 0) + 1
    return sum(1 for v in seen.values() if v == 1)


def base(tb, **kw):
    s = dict(tb["MOSS_DEFAULTS"], coverage=0.75, clump_size=0.06, size_var=0.4, thickness=0.018, mess=0.5,
             slope=115.0, crevices=0.6, edges=1.0, patchiness=0.75, patch_size=0.3, creases=0.4, strands=1.4,
             strand_length=0.01, droop=0.3, lumps=0.45, capsules=0.0, seed=3, detail="Normal")  # the bench's
    s.update(kw)
    return s


def run():
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    M = tb["scene_m_per_unit"]()

    # defaults: neutral for old groups, the realistic look for new Scatter layers
    md = tb["MOSS_DEFAULTS"]
    check("the new moss settings default to off (old groups grow as before)",
          md["exposure"] == 0 and md["feather"] == 0 and md["strays"] == 0 and md["ragged"] == 0
          and md["clump_merge"] == 0 and md["shoot_form"] == "Star" and md["spill"] == 0
          and tb["DEBRIS_DEFAULTS"]["on_moss"] is False)
    data = {"layers": []}
    lay = tb["_sc_new_layer"](data, "Moss")
    check("a new Scatter Moss layer gets the realistic look",
          all(lay["s"][k] == v for k, v in tb["MOSS_NEW_LOOK"].items()), str({k: lay["s"][k] for k in tb["MOSS_NEW_LOOK"]}))
    lay2 = tb["_sc_new_layer"](data, "Moss", {"exposure": 0.2})
    check("settings given to a new layer still win", lay2["s"]["exposure"] == 0.2)
    lv = tb["_sc_new_layer"](data, "Leaves")
    check("a new Leaves layer rests on moss", lv["s"].get("on_moss") is True)
    old = {"id": "L9", "type": "Moss", "s": {"coverage": 0.7}}
    check("an old layer without the keys reads them as off",
          tb["sc_settings"](old)["exposure"] == 0 and tb["sc_settings"](old)["shoot_form"] == "Star")
    missing = [k for k in ("exposure", "spill", "feather", "ragged", "strays", "clump_merge", "shoot_form", "on_moss")
               if k not in tb["SC_FIELDS"]]
    laid = set()
    for typ in ("Moss", "Leaves", "Leaf piles", "Jungle leaves"):
        for _, _, keys in tb["SC_LAYOUT"][typ]:
            laid.update(keys)
    check("every new setting has a field and a place in the panel",
          not missing and all(k in laid for k in ("exposure", "spill", "feather", "ragged", "strays", "clump_merge",
                                                  "shoot_form", "on_moss")), str(missing))

    # an older toolbox, same scene, same settings: identical moss (old groups regrow as they did)
    old_path = os.environ.get("UNLOK_OLD_TOOLBOX")
    stone = rock()
    if old_path and os.path.isfile(old_path):
        tbo = load_toolbox(old_path)
        for detail in ("Normal", "High"):
            s = base(tb, detail=detail)
            so = {k: v for k, v in s.items() if k in tbo["MOSS_DEFAULTS"]}
            a = tb["moss_build"]([stone], s, instances=True)
            b = tbo["moss_build"]([stone], so, instances=True)
            same = a["moss"][0] == b["moss"][0] and a["moss"][2] == b["moss"][2] and a["strands"][0] == b["strands"][0]
            sa, sb = a.get("shoots"), b.get("shoots")
            same = same and ((sa is None and sb is None) or (sa and sb and sa[-1]["pos"] == sb[-1]["pos"]
                                                          and sa[0] == sb[0]))
            check("%s moss with the new settings off is the same as before" % detail, same,
                  "bed %d / %d pts" % (len(a["moss"][0]), len(b["moss"][0])))
        del tbo
    else:
        print("SKIP  old toolbox comparison (set UNLOK_OLD_TOOLBOX)")

    # Bare ridges: a block's sharp top edges go bare, its flat top keeps its moss
    blk = block()
    top_edge = lambda p: p[1] > 5.5 and (abs(p[0]) > 2.4 or abs(p[2]) > 2.4)
    mid_top = lambda p: p[1] > 5.5 and abs(p[0]) < 1.5 and abs(p[2]) < 1.5
    a = tb["moss_build"]([blk], base(tb, coverage=0.9, slope=120.0, patchiness=0.0))["moss"][0]
    b = tb["moss_build"]([blk], base(tb, coverage=0.9, slope=120.0, patchiness=0.0, exposure=1.0))["moss"][0]
    ea, eb = sum(1 for p in a if top_edge(p)), sum(1 for p in b if top_edge(p))
    ma, mb = sum(1 for p in a if mid_top(p)), sum(1 for p in b if mid_top(p))
    check("Bare ridges: less moss along the sharp edges", eb < 0.6 * ea, "%d -> %d bed points" % (ea, eb))
    check("Bare ridges: the flat top keeps most of its moss", mb > 0.75 * ma, "%d -> %d" % (ma, mb))
    cmds.delete(blk)

    # Ragged outline: more open edge (a frayed outline) for the same coverage
    a = tb["moss_build"]([stone], base(tb, coverage=0.55))["moss"]
    b = tb["moss_build"]([stone], base(tb, coverage=0.55, ragged=1.0))["moss"]
    check("Ragged outline: a longer, frayed outline", boundary_edges(b[:3]) > 1.08 * boundary_edges(a[:3]),
          "%d -> %d open edges" % (boundary_edges(a[:3]), boundary_edges(b[:3])))

    # Soft edges: a lower rim (mean bed height off the surface), fewer shoots at High
    def mean_lift(mesh):
        surf = tb["_MiSurface"]([stone])
        tot = n = 0
        for p in mesh[0][::7]:
            hit = surf.closest(tuple(p))
            if hit:
                tot += hit[0]
                n += 1
        return tot / max(1, n)
    sh = base(tb, coverage=0.6, detail="High")
    a = tb["moss_build"]([stone], sh, instances=True)
    b = tb["moss_build"]([stone], dict(sh, feather=1.0), instances=True)
    la, lb = mean_lift(a["moss"]), mean_lift(b["moss"])
    check("Soft edges: a thinner bed overall (the rim tapers further in)", lb < 0.95 * la, "%.4f -> %.4f dm" % (la, lb))
    na, nb = len(a["shoots"][-1]["pos"]), len(b["shoots"][-1]["pos"])
    check("Soft edges: fewer shoots towards the edges", nb < na, "%d -> %d shoots" % (na, nb))

    # Stray tufts: more shoots, some of them off the bed
    c = tb["moss_build"]([stone], dict(sh, strays=1.0), instances=True)
    nc = len(c["shoots"][-1]["pos"])
    check("Stray tufts: shoots outside the patches", nc > na * 1.01, "%d -> %d shoots" % (na, nc))
    # (the strays draw no rays when off: moss without them is untouched)
    d = tb["moss_build"]([stone], dict(sh, strays=0.0), instances=True)
    check("Stray tufts off: the same shoots", d["shoots"][-1]["pos"] == a["shoots"][-1]["pos"])

    # Leafy: leafier shapes, more shoots
    e = tb["moss_build"]([stone], dict(sh, shoot_form="Leafy"), instances=True)
    fa = sum(f for _, f, _ in a["shoots"][6]) / float(len(a["shoots"][6]))
    fe = sum(f for _, f, _ in e["shoots"][6]) / float(len(e["shoots"][6]))
    ne = len(e["shoots"][-1]["pos"])
    check("Shoot shape Leafy: leafier shapes", fe > 1.5 * fa, "%.0f -> %.0f faces a shape" % (fa, fe))
    check("Shoot shape Leafy: more shoots", ne > 1.3 * na, "%d -> %d" % (na, ne))
    real = tb["moss_instances_mesh"](e["shoots"])
    check("Leafy shoots bake to real geometry", len(real[1]) == sum(e["shoots"][6][i][1] for i in e["shoots"][-1]["index"]))

    # Hero: instances keep it under the point cap
    hero = tb["moss_build"]([stone], base(tb, coverage=0.75, detail="Hero", shoot_form="Leafy"), instances=True)
    nh = len(hero["shoots"][-1]["pos"]) if hero.get("shoots") else 0
    check("Hero grows its shoots as instances, under the caps",
          nh > 0 and len(hero["strands"][0]) < tb["MI_MAX_VERTS"] and nh < tb["MOSS_MAX_INSTANCES"],
          "%d shoots, %d strand points" % (nh, len(hero["strands"][0])))

    # Merge: Clumps lower and wider
    def peak(mesh):
        surf = tb["_MiSurface"]([stone])
        best = 0.0
        for p in mesh[0][::3]:
            hit = surf.closest(tuple(p))
            if hit:
                best = max(best, hit[0])
        return best
    cl = base(tb, style="Clumps", coverage=0.7)
    a = tb["moss_build"]([stone], cl)["moss"]
    b = tb["moss_build"]([stone], dict(cl, clump_merge=1.0))["moss"]
    check("Merge: lower clumps", peak(b) < 0.85 * peak(a), "%.3f -> %.3f dm" % (peak(a), peak(b)))
    check("Merge: wider clumps (more bed)", len(b[1]) > len(a[1]), "%d -> %d faces" % (len(a[1]), len(b[1])))

    # Floor spill: on a floor, moss only near the foot of the rock
    gnd = floor()
    far = lambda mesh: max([math.hypot(p[0], p[2]) for p in mesh[0] if p[1] < 0.3] or [0.0])
    sp = base(tb, coverage=0.75, slope=80.0)
    a = tb["moss_build"]([stone, gnd], sp)["moss"]
    b = tb["moss_build"]([stone, gnd], dict(sp, spill=0.4))["moss"]
    check("Floor spill off: the floor mossed like any surface", far(a) > 20.0, "%.1f dm" % far(a))
    check("Floor spill: moss on the floor stays by the rock", 0.0 < far(b) < 3.0 + 0.4 / M + 1.5,
          "furthest %.1f dm" % far(b))
    c = tb["moss_build"]([gnd], dict(sp, spill=0.4))["moss"]
    check("Floor spill with only a floor: the floor still mosses", far(c) > 20.0, "%.1f dm" % far(c))
    # a rock on a huge floor, a ring of the floor picked: the rock keeps its fine bed (only picked faces count)
    big = cmds.ls(cmds.polyPlane(w=2400.0, h=2400.0, sx=240, sy=240, ch=False, name="groundSoil_C_test0002_GEP")[0], long=True)[0]
    near = [f for f in range(240 * 240)  # (a 240 x 240 grid of 10 dm faces: the ones within 12 dm of the middle)
            if math.hypot(-1195.0 + 10.0 * (f % 240), -1195.0 + 10.0 * (f // 240)) < 12.0]
    nf = cmds.polyEvaluate(stone, face=True)
    r1 = tb["moss_build"]([stone], sp)
    r2 = tb["moss_build"]([stone, big], dict(sp, spill=0.4), faces={stone: list(range(nf)), big: near})
    on_rock = lambda m: sum(1 for p in m[0] if p[1] > 0.3)
    check("a rock on a huge floor (a ring picked) keeps its fine bed", not r2["capped"] and
          on_rock(r2["moss"]) > 0.8 * on_rock(r1["moss"]), "%d vs %d bed points on the rock, capped %s" % (
              on_rock(r2["moss"]), on_rock(r1["moss"]), r2["capped"]))
    cmds.delete(big)

    # Rest on moss: leaves on a mossed floor land on top of the moss
    stone2 = rock("rockGrey_C_test0002_GEP")
    cmds.move(100, 0, 0, stone2)
    cmds.delete(stone)
    rep = tb["create_scatter_group"]([gnd], "Moss", dict(tb["MOSS_DEFAULTS"], coverage=1.0, thickness=0.04,
                                                         detail="Normal", seed=2), select=False)
    root = rep["root"]
    lid_l = tb["sc_add_layer"](root, "Leaves", {"leaves": 40.0, "on_moss": False})
    data = tb["sc_data"](root)
    lid_l = data["layers"][-1]["id"]

    def leaf_y():
        node = tb["sc_parts"](root).get(lid_l + "/litter")
        if not node:
            return None
        pts = cmds.xform(node + ".vtx[*]", q=True, ws=True, t=True)
        ys = pts[1::3]
        return sum(ys) / len(ys)
    y0 = leaf_y()
    tb["sc_update"](root, lid_l, {"on_moss": True})
    y1 = leaf_y()
    check("Rest on moss: leaves land on the moss, not through it", y0 is not None and y1 is not None and y1 > y0 + 0.1,
          "mean leaf height %s -> %s dm" % (y0, y1))
    lid_m = data["layers"][0]["id"]
    tb["sc_update"](root, lid_m, {"thickness": 0.08})
    y2 = leaf_y()
    check("Rest on moss: a thicker moss lifts the leaves", y2 is not None and y2 > y1 + 0.1, "%s -> %s dm" % (y1, y2))

    # shading data: the bed carries mossData (patch noise, height in the bed, how far inside a patch)
    import maya.api.OpenMaya as om
    bed = tb["sc_parts"](root)[lid_m + "/moss"]
    shape = cmds.listRelatives(bed, shapes=True, fullPath=True)[0]
    sets = cmds.polyColorSet(shape, q=True, allColorSets=True) or []
    sel = om.MSelectionList()
    sel.add(shape)
    fn = om.MFnMesh(sel.getDagPath(0))
    cs = fn.getColors("mossData") if "mossData" in sets else []
    rs, gs, bs = [c.r for c in cs], [c.g for c in cs], [c.b for c in cs]
    check("the moss bed carries its shading data (colour set mossData, a colour per point)",
          "mossData" in sets and len(cs) == fn.numVertices, "%s, %d colours, %d points" % (sets, len(cs), fn.numVertices))
    check("... patch noise, height in the bed and how far inside a patch, each 0..1 and varied",
          cs and all(0.0 <= min(v) and max(v) <= 1.0001 and max(v) - min(v) > 0.2 for v in (rs, gs, bs)),
          "R %.2f..%.2f G %.2f..%.2f B %.2f..%.2f" % (min(rs), max(rs), min(gs), max(gs), min(bs), max(bs)) if cs else "")
    back = tb["_sc_read_part"](bed)
    check("reading the bed back keeps its shading data", getattr(back[0], "col", None) and len(back[0].col) == len(cs))
    tb["sc_update"](root, lid_m, {"style": "Clumps"})
    bed = tb["sc_parts"](root)[lid_m + "/moss"]
    shape = cmds.listRelatives(bed, shapes=True, fullPath=True)[0]
    sel = om.MSelectionList()
    sel.add(shape)
    fn = om.MFnMesh(sel.getDagPath(0))
    cs = fn.getColors("mossData") if "mossData" in (cmds.polyColorSet(shape, q=True, allColorSets=True) or []) else []
    check("Clumps: a random value per cushion", len(cs) == fn.numVertices and len(set(round(c.r, 4) for c in cs)) > 20,
          "%d distinct" % len(set(round(c.r, 4) for c in cs)))
    tb["sc_update"](root, lid_m, {"style": "Carpet"})

    # Shoots Mesh with Leafy: the same shoots as real geometry (what Bake makes)
    mm = tb["moss_build"]([stone2], dict(sh, shoot_form="Leafy"), instances=False)
    mi = tb["moss_build"]([stone2], dict(sh, shoot_form="Leafy"), instances=True)
    nf = sum(mi["shoots"][6][i][1] for i in mi["shoots"][-1]["index"]) + len(mi["strands"][1])
    check("Shoots Mesh, Leafy: the shoots in the strands mesh, as instanced", len(mm["strands"][1]) == nf,
          "%d vs %d faces" % (len(mm["strands"][1]), nf))
    col = getattr(mm["strands"][0], "col", None)
    check("... each with its own random shading value", col and len(col) == len(mm["strands"][0]) and
          len(set(round(c[0], 4) for c in col)) > 50)

    # Moss Look: the starter materials on the moss parts (one Ctrl+Z)
    try:
        cmds.loadPlugin("mtoa", quiet=True)
    except Exception:
        pass
    arnold = bool(cmds.pluginInfo("mtoa", query=True, loaded=True))
    got = tb["sc_moss_look"]([root])
    sg = tb["_sc_sg"](tb["sc_parts"](root)[lid_m + "/moss"])
    shader = (cmds.listConnections(sg + ".surfaceShader") or [None])[0] if sg else None
    check("Moss Look puts mossGreen_MAT on the bed (%s)" % ("Arnold" if arnold else "no Arnold"),
          shader == "mossGreen_MAT" and cmds.nodeType(shader) == ("aiStandardSurface" if arnold else "standardSurface")
          and got["parts"] >= 2, "%s %s %s" % (sg, shader, got))
    if arnold:
        udc = cmds.ls(type="aiUserDataColor") or []
        check("... reading the shading data", any(cmds.getAttr(u + ".attribute") == "mossData" for u in udc), str(udc))
        check("... and the bed exports it to Arnold", cmds.getAttr(shape + ".aiExportColors"))
    again = tb["sc_moss_look"]([root])
    check("Moss Look again reuses the materials", len(cmds.ls("mossGreen_MAT*", type=("aiStandardSurface",
                                                                                     "standardSurface"))) == 1)
    cmds.undo()
    cmds.undo()
    check("one Ctrl+Z each takes it off", not cmds.objExists("mossGreen_MAT") and
          tb["_sc_sg"](tb["sc_parts"](root)[lid_m + "/moss"]) == "initialShadingGroup",
          str(tb["_sc_sg"](tb["sc_parts"](root)[lid_m + "/moss"])))


try:
    run()
except Exception:
    traceback.print_exc()
    check("no exceptions", False, traceback.format_exc().splitlines()[-1])
finally:
    bad = [r for r in RESULTS if not r[1]]
    print("\n%d checks, %d failed" % (len(RESULTS), len(bad)))
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(1 if bad else 0)
