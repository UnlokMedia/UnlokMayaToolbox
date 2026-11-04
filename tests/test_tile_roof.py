"""Headless tests for the Roof tool's clay tile covering (mayapy).

    mayapy tests/test_tile_roof.py

Builds every roof shape in clean and makeshift tiles (barrel everywhere,
Roman and plain on a gable and a hip) and checks: no sky seen from inside
(rays up over the footprint hit tiles, ridge / hip / verge tiles, or, where
a makeshift tile is missing, the underlay), no tile passes through another
(rays down enter and leave solids in turn, tiles and trim together), every
tile a closed solid, the frame under the tiles, the gauge and battens, both
UV modes with no shared UV space between parts, real-world sizes in a
decimetre scene, parts made only with geometry, old roofs unchanged,
switching covering, undo / redo, save / reopen, bake and speed.
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


def mesh_fn(tb, node):
    return om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))


def boundary_edges(fn):
    it = om.MItMeshEdge(fn.dagPath())
    n = 0
    while not it.isDone():
        if it.onBoundary():
            n += 1
        it.next()
    return n


def signed_volume(fn):
    pts = fn.getPoints(om.MSpace.kWorld)
    counts, conn = fn.getVertices()
    vol, k = 0.0, 0
    for c in counts:
        ids = conn[k:k + c]
        k += c
        a = pts[ids[0]]
        for i in range(1, c - 1):
            b, d = pts[ids[i]], pts[ids[i + 1]]
            vol += (a.x * (b.y * d.z - b.z * d.y) - a.y * (b.x * d.z - b.z * d.x) + a.z * (b.x * d.y - b.y * d.x))
    return vol / 6.0


def box(name, size=(60.0, 20.0, 40.0), move=(0.0, 30.0, 0.0)):
    node = cmds.ls(cmds.polyCube(w=1, h=1, d=1, name=name, constructionHistory=False)[0], long=True)[0]
    cmds.xform(node, scale=size, translation=move)
    return node


def rays_up(tb, nodes, x0, x1, z0, z1, y, n=30):
    """Rays straight up from inside the house over its walls: the ones that miss all the nodes' meshes."""
    fns = [mesh_fn(tb, nd) for nd in nodes]
    accs = [fn.autoUniformGridParams() for fn in fns]
    miss = []
    for i in range(n + 1):
        for j in range(n + 1):
            x = x0 + (x1 - x0) * i / float(n)
            z = z0 + (z1 - z0) * j / float(n)
            hit = False
            for fn, acc in zip(fns, accs):
                if fn.closestIntersection(om.MFloatPoint(x, y, z), om.MFloatVector(0.0, 1.0, 0.0), om.MSpace.kWorld,
                                          1e4, False, accelParams=acc):
                    hit = True
                    break
            if not hit:
                miss.append((round(x, 2), round(z, 2)))
    return miss


def rays_through(tb, node, x0, x1, z0, z1, top, n=30):
    """Rays straight down through a closed-solids mesh: at every hit the ray must alternately enter (the
    face looks up at it) and leave. Two tiles passing through each other break the order. Returns the
    rays that broke it and the most surfaces one ray crossed."""
    fn = mesh_fn(tb, node)
    acc = fn.autoUniformGridParams()
    bad, most = [], 0
    for i in range(n + 1):
        for j in range(n + 1):
            x = x0 + (x1 - x0) * (i + 0.37) / float(n + 1)
            z = z0 + (z1 - z0) * (j + 0.61) / float(n + 1)
            res = fn.allIntersections(om.MFloatPoint(x, top, z), om.MFloatVector(0.0, -1.0, 0.0), om.MSpace.kWorld,
                                      1e4, False, accelParams=acc, sortHits=True)
            if not res:
                continue
            hits, params, faces, tris = res[0], res[1], res[2], res[3]
            seq = []
            last = None
            for h, prm, f, tri in zip(hits, params, faces, tris):
                # the hit triangle's own normal: a long, slightly twisted wall quad folds along its
                # diagonal, and a grazing ray crosses both halves (in and out) under one polygon normal
                ids = fn.getPolygonTriangleVertices(f, tri)
                p0, p1, p2 = [fn.getPoint(i, om.MSpace.kWorld) for i in ids]
                nrm = (p1 - p0) ^ (p2 - p0)
                ln = nrm.length()
                if ln < 1e-12:
                    continue
                nrm /= ln  # Maya's triangles keep the face's winding
                if abs(nrm.y) < 0.002:
                    continue  # parallel to an upright wall (a slanting edge wall counts: rays enter through it)
                up = nrm.y > 0.0
                if last is not None and abs(prm - last[0]) < 1e-5 and up == last[1]:
                    continue  # the same point on an edge, found twice (two tiles touching: one out, one in)
                last = (prm, up)
                seq.append((up, prm))
            most = max(most, len(seq))
            # an overlap under 1 mm (0.01 units: the raster's resolution) counts as touching: swap the pair
            i = 0
            while i + 1 < len(seq):
                if seq[i][0] and not seq[i + 1][0] and i % 2 == 1 and seq[i + 1][1] - seq[i][1] < 0.01:
                    seq[i], seq[i + 1] = seq[i + 1], seq[i]
                i += 1
            want = True
            for up, _ in seq:
                if up != want:
                    bad.append((round(x, 2), round(z, 2)))
                    break
                want = not want
    return bad, most


def joined(tb, nodes, name):
    """A copy of several meshes as one (for the enter / leave test across parts)."""
    copies = [cmds.duplicate(n)[0] for n in nodes]
    if len(copies) == 1:
        return cmds.ls(cmds.rename(copies[0], name), long=True)[0]
    out = cmds.polyUnite(copies, constructionHistory=False, name=name)[0]
    return cmds.ls(out, long=True)[0]


def uv_boxes(fn, fill=0.0):
    """UV shells' boxes; fill > 0 keeps only shells whose UV area fills that much of their box (the edge
    strips round a tile follow its slanting sides and crack lines, so their boxes cross the tile's own)."""
    us, vs = fn.getUVs()
    nshell, ids_ = fn.getUvShellsIds()
    boxes = {}
    for uvid, shell in enumerate(ids_):
        u, v = us[uvid], vs[uvid]
        b0 = boxes.get(shell)
        boxes[shell] = (min(b0[0], u), min(b0[1], v), max(b0[2], u), max(b0[3], v)) if b0 else (u, v, u, v)
    if fill <= 0.0:
        return list(boxes.values())
    area = dict.fromkeys(boxes, 0.0)
    counts, uv_ids = fn.getAssignedUVs()
    k = 0
    for c in counts:
        ids = uv_ids[k:k + c]
        k += c
        a = 0.0
        for i in range(c):
            p, q = ids[i], ids[(i + 1) % c]
            a += us[p] * vs[q] - us[q] * vs[p]
        area[ids_[ids[0]]] += abs(0.5 * a)
    return [bx for sh, bx in boxes.items()
            if area[sh] >= fill * (bx[2] - bx[0]) * (bx[3] - bx[1])]


def udim_set(fn):
    us, vs = fn.getUVs()
    return set(1001 + int(math.floor(u + 1e-6)) + 10 * int(math.floor(v + 1e-6)) for u, v in zip(us, vs))


PROFILES = ("Barrel", "Roman", "Plain")


def profile_settings(tb, prof):
    sizes = tb["TILE_PROFILE_SIZES"][prof]
    s = dict(zip(("t_length", "t_width", "t_headlap", "t_thickness", "t_rise"), sizes))
    s["t_profile"] = prof
    return s


def run():
    tb = load_toolbox()
    cmds.undoInfo(state=True, infinity=True)
    k = 1.0 / tb["scene_m_per_unit"]()
    check("a decimetre scene: 10 units a metre", abs(k - 10.0) < 1e-9, str(k))

    # --- every shape, clean and makeshift: covered, nothing through anything, closed solids, frame under
    combos = [("gable", {"end_a": "Gable", "end_b": "Gable"}, PROFILES),
              ("hip", {"end_a": "Hip", "end_b": "Hip"}, PROFILES),
              ("half-hip", {"end_a": "Half-hip", "end_b": "Half-hip"}, ("Barrel",)),
              ("gable+hip", {"end_a": "Gable", "end_b": "Hip"}, ("Barrel", "Plain")),
              ("lean-to", {"shape": "Lean-to", "end_a": "Gable", "end_b": "Gable"}, ("Barrel",)),
              ("cone", {"shape": "Cone"}, ("Barrel", "Plain"))]
    for mode in ("Clean", "Makeshift"):
        cmds.file(new=True, force=True)
        n = 0
        for label, over, profs in combos:
            for prof in profs:
                b = box("b%d" % n, move=(n * 100.0, 30.0, 0.0))
                s = {"covering": "Tiles", "t_mode": mode, "overhang": 0.03}
                s.update(profile_settings(tb, prof))
                s.update(over)
                if mode == "Makeshift":
                    s["t_sag"] = 0.6
                t0 = time.time()
                rep = tb["make_thatch_roof"](b, s)
                dt = time.time() - t0
                root = rep["root"]
                parts = tb["thatch_parts"](root)
                name = "%s %s %s" % (mode, prof, label)
                cl = rep["clay"] or {}
                want = {"tiles", "tile_trim", "tile_underlay", "frame"}
                check("%s: builds (%.2fs) with tiles, trim, underlay and a frame" % (name, dt),
                      set(parts) == want and cl.get("tiles", 0) > 50 and dt < 8.0 and
                      all(cmds.getAttr(parts[p] + ".visibility") for p in parts),
                      "%s, parts %s" % (cl, sorted(parts)))
                if mode == "Makeshift":
                    check("%s: makeshift has missing, slipped and cracked tiles" % name,
                          cl.get("missing", 0) > 0 and cl.get("slipped", 0) > 0 and cl.get("cracked", 0) > 0, str(cl))
                x0, x1 = n * 100.0 - 29.5, n * 100.0 + 29.5
                cover = [parts["tiles"], parts["tile_trim"]]
                if mode == "Makeshift":
                    cover.append(parts["tile_underlay"])  # holes show the underlay, never sky
                miss = rays_up(tb, cover, x0, x1, -19.5, 19.5, 15.0)
                if label == "cone":  # inside the walls of a round house
                    miss = [m for m in miss if ((m[0] - n * 100.0) / 30.0) ** 2 + (m[1] / 20.0) ** 2 < 0.96]
                check("%s: no sky: every ray up from inside hits %s" % (
                    name, "tiles" if mode == "Clean" else "tiles or underlay"), not miss,
                    "%d of 961 see the sky: %s" % (len(miss), miss[:6]))
                for part in ("tiles", "tile_trim", "tile_underlay"):
                    fn = mesh_fn(tb, parts[part])
                    open_ = boundary_edges(fn)
                    vol = signed_volume(fn)
                    check("%s: %s are closed solids facing out" % (name, part), open_ == 0 and vol > 0.0,
                          "%d open edges, volume %.4f" % (open_, vol))
                both = joined(tb, [parts["tiles"], parts["tile_trim"]], "probe%d" % n)
                bad, most = rays_through(tb, both, x0, x1, -19.5, 19.5, 200.0)
                check("%s: no tile passes through another (rays down enter and leave in turn)" % name, not bad,
                      "%d rays out of order: %s; up to %d surfaces" % (len(bad), bad[:6], most))
                cmds.delete(both)
                # the frame and the underlay sit under the tiles: straight down, clay comes first
                ffn = mesh_fn(tb, parts["frame"])
                ufn = mesh_fn(tb, parts["tile_underlay"])
                cfns = [mesh_fn(tb, parts["tiles"]), mesh_fn(tb, parts["tile_trim"])]
                accs = [f_.autoUniformGridParams() for f_ in [ffn, ufn] + cfns]
                above = []
                for i in range(21):
                    for j in range(21):
                        p = om.MFloatPoint(x0 + 59.0 * i / 20.0, 200.0, -19.5 + 39.0 * j / 20.0)
                        hits = [f_.closestIntersection(p, om.MFloatVector(0, -1, 0), om.MSpace.kWorld, 1e4, False,
                                                       accelParams=a) for f_, a in zip([ffn, ufn] + cfns, accs)]
                        clay = min([h[1] for h in hits[2:] if h] or [1e9])
                        under = min([h[1] for h in hits[:2] if h] or [1e9])
                        if mode == "Clean" and under < clay - 1e-4:
                            above.append((round(p.x, 2), round(p.z, 2)))
                check("%s: the frame and underlay are under the tiles" % name, mode != "Clean" or not above,
                      "%d of 441 rays meet timber / underlay first: %s" % (len(above), above[:6]))
                n += 1

    # --- gauge, battens, headlap (clean gable, each profile)
    cmds.file(new=True, force=True)
    b = box("gauge")
    frame = tb["thatch_frame"](b)
    for prof in PROFILES:
        s = dict(tb["THATCH_DEFAULTS"], covering="Tiles", end_a="Gable", end_b="Gable", **profile_settings(tb, prof))
        out = tb["tile_build"](frame, s)
        L, W, lap = s["t_length"], s["t_width"], s["t_headlap"]
        g = (L - lap) / (2.0 if prof == "Plain" else 1.0)
        check("%s: gauge = %s (%.3f m), courses from the eave to the ridge" % (
            prof, "(length - headlap) / 2" if prof == "Plain" else "length - headlap", g),
            abs(out["clay"]["gauge"] - g) < 1e-6 and out["clay"]["courses"] >= int(2.6 / g),
            str(out["clay"]))
        F = out["field"]
        sz = tb["_tl_sizes"](s, F, 0.1, 2)
        faces = tb["_mt_faces"](F, sz, "Clean")
        for f in faces:
            tb["_tl_face_setup"](f, F)
        tiles, courses = tb["_tl_layout"](F, faces, sz, 1, 1)
        bs = courses[0]
        steps = set(round((q - p) / k, 6) for p, q in zip(bs, bs[1:]))
        check("%s: courses exactly a gauge apart" % prof, steps == {round(g, 6)}, str(sorted(steps)))
        f0 = sorted([t for t in tiles if t["face"] == 0 and t["course"] == 0], key=lambda t: t["ac"])
        if prof == "Barrel":
            pans = [t for t in f0 if t["kind"] == "pan"]
            covers = [t for t in f0 if t["kind"] == "cover"]
            mid = all(any(abs(c["ac"] - 0.5 * (p["ac"] + q["ac"])) < 1e-6 for c in covers) for p, q in zip(pans, pans[1:]))
            check("Barrel: a cover over every joint between two pans", mid and len(covers) >= len(pans), "%d pans, %d covers" % (
                len(pans), len(covers)))
        if prof == "Plain":
            c1 = sorted([t for t in tiles if t["face"] == 0 and t["course"] == 1], key=lambda t: t["ac"])
            off = min(abs(a["ac"] - b_["ac"]) for a in f0[1:-1] for b_ in c1)
            check("Plain: bonded courses (joints half a tile apart)", abs(off - 0.5 * sz["pitch"]) < 0.02 * sz["pitch"],
                  "%.3f of %.3f" % (off, sz["pitch"]))
    # battens: one under every course's head
    rep = tb["make_thatch_roof"](b, {"covering": "Tiles", "end_a": "Gable", "end_b": "Gable"})
    nb = rep["clay"]["courses"]
    check("a batten under every course (frame built)", nb >= 7 and cmds.objExists(tb["thatch_parts"](rep["root"])["frame"]),
          "%d courses" % nb)
    cmds.delete(rep["root"])

    # --- real sizes in decimetres: a barrel tile is 0.45 m long, 0.2 wide
    s = dict(tb["THATCH_DEFAULTS"], covering="Tiles", end_a="Gable", end_b="Gable", t_ridge=False, frame=False,
             t_verge="Undercloak")
    out = tb["tile_build"](frame, s)
    pts = out["tiles"][0]
    sizes = tb["_tl_sizes"](s, out["field"], 0.1, 2)
    check("decimetres: tiles 4.5 units long, 2 wide, 0.15 thick", abs(sizes["len"] - 4.5) < 1e-9 and
          abs(sizes["w"] - 2.0) < 1e-9 and abs(sizes["t"] - 0.15) < 1e-9)
    zmax = max(p[2] for p in pts)
    # 50 mm down the slope past the eave (0.35 units across at 45 degrees), plus the tiles' height over the
    # plane (about 0.25 m at a barrel eave), which leans out with the slope
    check("the bottom course reaches 50 mm past the eave", 20.0 + 0.25 < zmax < 20.0 + 0.35 + 2.6 * 0.71,
          "%.3f" % zmax)

    # --- UVs: variations (stacked) and all laid out (no overlaps); no part shares UV space with another
    cmds.file(new=True, force=True)
    b = box("uv")
    rep = tb["make_thatch_roof"](b, {"covering": "Tiles", "end_a": "Gable", "end_b": "Hip", "stacks": 3,
                                     "t_mode": "Makeshift", "t_underlay": "Boards"})
    root = rep["root"]
    parts = tb["thatch_parts"](root)
    fn = mesh_fn(tb, parts["tiles"])
    us, vs = fn.getUVs()
    tiles = set(int(math.floor(u)) for u in us)
    check("variations: 3 stacks in UDIM tiles 1001-1003, all inside their tile",
          tiles == {0, 1, 2} and min(vs) >= 0.0 and max(vs) <= 1.0, str(sorted(tiles)))
    sh = tb["_log_shape"](parts["tiles"])
    check("variations are stacked (Smart UDIM leaves them alone)", cmds.getAttr(sh + "." + tb["UV_STACKED_ATTR"]))
    used = {}
    for part, node in parts.items():
        used[part] = udim_set(mesh_fn(tb, node))
    clash = [(a, b_) for a in used for b_ in used if a < b_ and used[a] & used[b_]]
    check("no two parts share a UDIM tile", not clash, str({p: sorted(t) for p, t in used.items()}))
    tb["update_thatch_roofs"]({root: {"t_uv_mode": "All laid out"}})
    fn = mesh_fn(tb, parts["tiles"])
    check("all laid out: not stacked", not cmds.getAttr(sh + "." + tb["UV_STACKED_ATTR"]))
    # tile tops and undersides (the thin edge strips beside each follow a tapered tile's slanting sides and a
    # cracked tile's crack line, so their boxes overlap its top's box while the UVs don't: leave them out)
    big = sorted([bx for bx in uv_boxes(fn, fill=0.5) if min(bx[2] - bx[0], bx[3] - bx[1]) > 0.03],
                 key=lambda q: q[0])
    overlaps = 0
    for i, a in enumerate(big):
        for c in big[i + 1:]:
            if c[0] >= a[2] - 1e-7:
                break
            if c[1] < a[3] - 1e-7 and a[1] < c[3] - 1e-7:
                overlaps += 1
    in_tile = all(math.floor(bx[0] + 1e-7) == math.floor(bx[2] - 1e-7) and
                  math.floor(bx[1] + 1e-7) == math.floor(bx[3] - 1e-7) for bx in big)
    check("all laid out: every tile top and underside its own UV space, none overlapping, each inside a tile",
          overlaps == 0 and in_tile and len(big) >= 1.6 * rep["clay"]["tiles"],
          "%d shells, %d overlaps, %d tiles" % (len(big), overlaps, rep["clay"]["tiles"]))
    used = dict((part, udim_set(mesh_fn(tb, node))) for part, node in tb["thatch_parts"](root).items())
    clash = [(a, b_) for a in used for b_ in used if a < b_ and used[a] & used[b_]]
    check("all laid out: still no two parts in one tile", not clash)
    # one density: a 0.45 m tile is 0.225 of a 2 m UV tile tall
    hs = sorted(bx[3] - bx[1] for bx in big)
    want = 0.45 * k / (2.0 * k)
    check("all laid out: one real-world density (2 m a UV tile)", abs(hs[len(hs) // 2] - want) < 0.03,
          "median shell height %.3f, want ~%.3f" % (hs[len(hs) // 2], want))

    # --- parts only with geometry: no underlay mesh with None, no frame mesh with Frame off
    cmds.file(new=True, force=True)
    b = box("parts")
    rep = tb["make_thatch_roof"](b, {"covering": "Tiles", "t_underlay": "None", "frame": False, "end_a": "Hip",
                                     "end_b": "Hip", "t_ridge": False, "t_hip": False})
    root = rep["root"]
    check("a tile roof makes only the parts it has geometry for", set(tb["thatch_parts"](root)) == {"tiles"},
          str(sorted(tb["thatch_parts"](root))))
    check("tile roofs are named tileRoof####", "tileRoof" in tb["short_name"](root) and all(
        "tileRoof" in tb["short_name"](n) for n in tb["thatch_parts"](root).values()), root)
    tb["update_thatch_roofs"]({root: {"t_underlay": "Felt", "frame": True, "t_ridge": True}})
    parts = tb["thatch_parts"](root)
    check("turning things on makes their parts (felt underlay named fabricFelt)",
          {"tiles", "tile_underlay", "frame", "tile_trim"} <= set(parts) and
          tb["short_name"](parts["tile_underlay"]).startswith("fabricFelt_"), str(sorted(parts)))
    tb["update_thatch_roofs"]({root: {"t_underlay": "Reed mat"}})
    parts = tb["thatch_parts"](root)
    check("Reed mat renames the underlay grassReed", tb["short_name"](parts["tile_underlay"]).startswith("grassReed_"),
          tb["short_name"](parts["tile_underlay"]))
    tb["update_thatch_roofs"]({root: {"t_underlay": "None"}})
    parts = tb["thatch_parts"](root)
    check("None hides the underlay (no placeholder written)", not cmds.getAttr(parts["tile_underlay"] + ".visibility")
          and mesh_fn(tb, parts["tile_underlay"]).numVertices > 4)
    done, gone = tb["bake_thatch"]([root])
    check("bake deletes a tile roof's hidden parts", "tile_underlay" not in tb["thatch_parts"](root) and
          "tiles" in tb["thatch_parts"](root), str(sorted(tb["thatch_parts"](root))))

    # --- old thatch / metal roofs: unchanged; switching to tiles and back
    cmds.file(new=True, force=True)
    b = box("old", size=(6.0, 3.0, 4.0), move=(0.0, 4.0, 0.0))
    rep = tb["make_thatch_roof"](b, {"resolution": 40})
    root = rep["root"]
    data = json.loads(cmds.getAttr(root + "." + tb["THATCH_SETTINGS"]))
    for key in list(data):
        if key == "covering" or key.startswith("m_") or key.startswith("t_"):
            del data[key]
    cmds.setAttr(root + "." + tb["THATCH_SETTINGS"], json.dumps(data), type="string")  # as an older tool left it
    straw = tb["thatch_parts"](root)["straw"]
    before = mesh_fn(tb, straw).getPoints(om.MSpace.kWorld)
    tb["update_thatch_roofs"]({root: {}})
    after = mesh_fn(tb, straw).getPoints(om.MSpace.kWorld)
    same = len(before) == len(after) and all((p - q).length() < 1e-6 for p, q in zip(before, after))
    check("an old thatch roof (no covering stored) rebuilds exactly as before and needs no upgrade",
          same and not tb["thatch_needs_upgrade"](root), "%d -> %d points" % (len(before), len(after)))
    rep = tb["roof_set_covering"]([root], "Tiles")
    parts = tb["thatch_parts"](root)
    check("switching it to tiles adds the tile meshes and hides the thatch",
          {"tiles", "tile_trim", "tile_underlay"} <= set(parts) and cmds.getAttr(parts["tiles"] + ".visibility") and
          not cmds.getAttr(parts["straw"] + ".visibility") and rep["done"] == [root], str(sorted(parts)))
    check("a switched roof needs no upgrade", not tb["thatch_needs_upgrade"](root))
    tb["roof_set_covering"]([root], "Thatch")
    again = mesh_fn(tb, straw).getPoints(om.MSpace.kWorld)
    check("and back to thatch: the same straw again, the tiles hidden",
          len(again) == len(before) and all((p - q).length() < 1e-6 for p, q in zip(before, again)) and
          not cmds.getAttr(parts["tiles"] + ".visibility") and cmds.getAttr(parts["straw"] + ".visibility"))
    b2 = box("metal", move=(100.0, 30.0, 0.0))
    rep = tb["make_thatch_roof"](b2, {"covering": "Corrugated"})
    sheets = tb["thatch_parts"](rep["root"])["sheets"]
    before = mesh_fn(tb, sheets).getPoints(om.MSpace.kWorld)
    tb["update_thatch_roofs"]({rep["root"]: {}})
    after = mesh_fn(tb, sheets).getPoints(om.MSpace.kWorld)
    check("a metal roof rebuilds exactly as before", len(before) == len(after) and
          all((p - q).length() < 1e-6 for p, q in zip(before, after)))

    # --- undo / redo, live edits, save / reopen, duplicate
    cmds.file(new=True, force=True)
    b = box("undo")
    rep = tb["make_thatch_roof"](b, {"covering": "Tiles"})
    root = rep["root"]
    cmds.undo()
    check("undo removes a new tile roof", not cmds.objExists(root))
    cmds.redo()
    stale = tb["rebuild_stale_thatch"]()
    fn = mesh_fn(tb, tb["thatch_parts"](root)["tiles"])
    check("redo brings it back built", fn.numPolygons > 1000 and stale, "%d faces" % fn.numPolygons)
    for change in (profile_settings(tb, "Roman"), profile_settings(tb, "Plain"), {"t_mode": "Makeshift"},
                   {"detail": "Proxy"}, {"detail": "Hero"}, {"t_sag": 1.0}, {"end_a": "Gable"},
                   {"t_verge": "Undercloak"}, {"shape": "Cone"}):
        t0 = time.time()
        rep = tb["update_thatch_roofs"]({root: change})
        check("live edit %s (%.2fs)" % (sorted(change), time.time() - t0), rep["done"] == [root] and not rep["errors"]
              and rep.get("clay"), str(rep.get("clay")))
    path = os.path.join(os.environ.get("TEMP", "."), "unlok_tile_test.ma")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaAscii", force=True)
    cmds.file(path, open=True, force=True)
    roofs = tb["thatch_roofs"]()
    check("save / reopen keeps the roof live", len(roofs) == 1 and tb["thatch_data"](roofs[0])["covering"] == "Tiles"
          and not tb["rebuild_stale_thatch"]())
    try:
        os.remove(path)
    except OSError:
        pass
    dup = tb["duplicate_thatch_roof"](roofs[0])
    check("Duplicate Roof copies a tile roof with its tile meshes",
          tb["thatch_data"](dup["root"])["covering"] == "Tiles" and "tiles" in tb["thatch_parts"](dup["root"]) and
          dup["clay"]["tiles"] > 0)
    # presets
    for name in [n for n in tb["THATCH_PRESETS"] if n.startswith("Tiles:")]:
        s = tb["thatch_preset"](name)
        check("preset %s sets Tiles and its profile's sizes" % name, s["covering"] == "Tiles" and
              abs(s["t_length"] - tb["TILE_PROFILE_SIZES"][s["t_profile"]][0]) < 1e-9)

    # --- speed: a big roof
    cmds.file(new=True, force=True)
    b = box("big", size=(160.0, 40.0, 90.0))
    for prof in PROFILES:
        for mode in ("Clean", "Makeshift"):
            t0 = time.time()
            rep = tb["make_thatch_roof"](b, dict(profile_settings(tb, prof), covering="Tiles", t_mode=mode,
                                                 end_a="Hip", end_b="Gable"))
            dt = time.time() - t0
            check("speed: a 16 x 9 m %s %s roof under 12 s" % (mode, prof), dt < 12.0 and not rep["capped"],
                  "%.2fs, %d tiles" % (dt, rep["clay"]["tiles"]))
            cmds.delete(rep["root"])


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
