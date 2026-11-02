"""Headless tests for the Roof tool's corrugated metal covering (mayapy).

    mayapy tests/test_corrugated_roof.py

Builds every roof shape in clean and makeshift metal and checks: no sky
seen from inside (rays up over the footprint all hit metal), no sheet
passes through another (rays down enter and leave solids in turn), sheets
are closed solids with their real thickness, the frame (purlins, rafters)
is under the sheets, the laps (side laps in corrugations, end laps on a
purlin), both UV modes (stacked variations in their tiles / columns; all
laid out with no two shells overlapping), real-world sizes in a decimetre
scene, switching an old thatch roof to metal and back (old roofs are left
as they were), undo, live edits and speed.
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


def volume_area(fn):
    pts = fn.getPoints(om.MSpace.kWorld)
    counts, conn = fn.getVertices()
    vol, area, k = 0.0, 0.0, 0
    for c in counts:
        ids = conn[k:k + c]
        k += c
        a = pts[ids[0]]
        for i in range(1, c - 1):
            b, d = pts[ids[i]], pts[ids[i + 1]]
            vol += (a.x * (b.y * d.z - b.z * d.y) - a.y * (b.x * d.z - b.z * d.x) + a.z * (b.x * d.y - b.y * d.x))
            area += ((b - a) ^ (d - a)).length() * 0.5
    return vol / 6.0, area


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


def rays_through(tb, node, x0, x1, z0, z1, top, n=24):
    """Rays straight down through a closed-solids mesh: at every hit the ray must alternately enter (the
    face looks up at it) and leave. Two sheets passing through each other break the order. Returns the
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
            hits, params, faces = res[0], res[1], res[2]
            seq = []
            last = None
            for h, prm, f in zip(hits, params, faces):
                if last is not None and abs(prm - last) < 1e-5:
                    continue  # the same point on an edge, found twice
                last = prm
                nrm = fn.getPolygonNormal(f, om.MSpace.kWorld)
                if abs(nrm.y) < 0.05:
                    continue  # grazing an edge wall
                seq.append(nrm.y > 0.0)
            most = max(most, len(seq))
            want = True
            for up in seq:
                if up != want:
                    bad.append((round(x, 2), round(z, 2)))
                    break
                want = not want
    return bad, most


def run():
    tb = load_toolbox()
    cmds.undoInfo(state=True, infinity=True)
    D = tb["THATCH_DEFAULTS"]
    k = 1.0 / tb["scene_m_per_unit"]()
    check("a decimetre scene: 10 units a metre", abs(k - 10.0) < 1e-9, str(k))

    # --- every shape, clean and makeshift: covered, nothing through anything, closed thin solids, frame under
    combos = [("gable", {"end_a": "Gable", "end_b": "Gable"}), ("hip", {"end_a": "Hip", "end_b": "Hip"}),
              ("half-hip", {"end_a": "Half-hip", "end_b": "Half-hip"}),
              ("gable+hip", {"end_a": "Gable", "end_b": "Hip"}),
              ("lean-to", {"shape": "Lean-to", "end_a": "Gable", "end_b": "Gable"}),
              ("lean-to hip", {"shape": "Lean-to", "end_a": "Hip", "end_b": "Gable"}),
              ("cone", {"shape": "Cone"})]
    for mode in ("Clean", "Makeshift"):
        cmds.file(new=True, force=True)
        for n, (label, over) in enumerate(combos):
            b = box("b%d" % n, move=(n * 100.0, 30.0, 0.0))
            s = {"covering": "Corrugated", "m_mode": mode, "overhang": 0.03}
            s.update(over)
            t0 = time.time()
            rep = tb["make_thatch_roof"](b, s)
            dt = time.time() - t0
            root = rep["root"]
            parts = tb["thatch_parts"](root)
            name = "%s %s" % (mode, label)
            check("%s: builds (%.2fs) with sheets, trim, fixings and a frame" % (name, dt),
                  set(parts) == {"sheets", "trim", "fixings", "frame"} and rep["pieces"] > 4 and dt < 8.0 and
                  all(cmds.getAttr(parts[p] + ".visibility") for p in parts),
                  "%d sheets, parts %s" % (rep["pieces"], sorted(parts)))
            x0, x1 = n * 100.0 - 29.5, n * 100.0 + 29.5
            if label == "cone":  # inside the walls of a round house
                miss = [m for m in rays_up(tb, [parts["sheets"], parts["trim"]], x0, x1, -19.5, 19.5, 15.0)
                        if ((m[0] - n * 100.0) / 30.0) ** 2 + (m[1] / 20.0) ** 2 < 0.96]
            else:
                miss = rays_up(tb, [parts["sheets"], parts["trim"]], x0, x1, -19.5, 19.5, 15.0)
            check("%s: no gaps: every ray up from inside hits metal" % name, not miss,
                  "%d of 961 see the sky: %s" % (len(miss), miss[:6]))
            fn = mesh_fn(tb, parts["sheets"])
            vol, area = volume_area(fn)
            t = D["m_thickness"] * k
            check("%s: sheets are closed solids, facing out, %.2f mm thick" % (name, 2.0 * vol / area / k * 1000),
                  boundary_edges(fn) == 0 and vol > 0.0 and 0.6 * t < 2.0 * vol / area < 1.6 * t,
                  "%d open edges, volume %.4f" % (boundary_edges(fn), vol))
            bad, most = rays_through(tb, parts["sheets"], x0, x1, -19.5, 19.5, 200.0)
            check("%s: no sheet passes through another (rays down enter and leave in turn)" % name, not bad,
                  "%d rays out of order: %s; up to %d surfaces" % (len(bad), bad[:6], most))
            # the frame sits under the sheets: straight down, metal comes first everywhere
            ffn = mesh_fn(tb, parts["frame"])
            tfn = mesh_fn(tb, parts["trim"])
            facc, sacc, tacc = ffn.autoUniformGridParams(), fn.autoUniformGridParams(), tfn.autoUniformGridParams()
            above = []
            for i in range(21):
                for j in range(21):
                    p = om.MFloatPoint(x0 + 59.0 * i / 20.0, 200.0, -19.5 + 39.0 * j / 20.0)
                    hf = ffn.closestIntersection(p, om.MFloatVector(0, -1, 0), om.MSpace.kWorld, 1e4, False,
                                                 accelParams=facc)
                    hs = fn.closestIntersection(p, om.MFloatVector(0, -1, 0), om.MSpace.kWorld, 1e4, False,
                                                accelParams=sacc)
                    ht = tfn.closestIntersection(p, om.MFloatVector(0, -1, 0), om.MSpace.kWorld, 1e4, False,
                                                 accelParams=tacc)
                    top = min([h[1] for h in (hs, ht) if h] or [1e9])
                    if hf and hf[1] < top - 1e-4:
                        above.append((round(p.x, 2), round(p.z, 2)))
            check("%s: the frame is under the sheets" % name, not above,
                  "%d of 441 rays meet timber first: %s" % (len(above), above[:6]))
    # --- laps and purlins (clean gable, rows of sheets)
    cmds.file(new=True, force=True)
    b = box("laps")
    s = dict(D, covering="Corrugated", end_a="Gable", end_b="Gable", m_full_length=False, m_sheet_length=2.4)
    frame = tb["thatch_frame"](b)
    F = tb["ThatchField"](frame["L"], frame["W"], frame["H"], dict(s, softness=0.0, sag=0.0, lumps=0.0))
    sz = tb["_mt_sizes"](s, F, 0.1, 2)
    faces = tb["_mt_faces"](F, sz, "Clean")
    heights = tb["_mt_purlins"](F, sz)
    sheets = tb["_mt_layout_clean"](faces, sz, heights, 1)
    f0 = [sh for sh in sheets if sh["face"] == 0]
    row0 = sorted([sh for sh in f0 if sh["row"] == 0], key=lambda sh: sh["ac"])
    side = [(a["ac"] + 0.5 * a["w"]) - (b_["ac"] - 0.5 * b_["w"]) for a, b_ in zip(row0, row0[1:])]
    check("clean: sheets lap one corrugation (76 mm) side by side, 762 mm cover",
          all(abs(x - 0.76) < 1e-6 for x in side) and abs(row0[0]["w"] - 8.36) < 1e-6,
          "laps %s, sheet %.3f" % (sorted(set(round(x, 3) for x in side)), row0[0]["w"]))
    cols = {}
    for sh in f0:
        cols.setdefault(sh["col"], []).append(sh)
    purl = tb["_mt_face_purlins"](faces[0], heights)
    ends_ok = True
    longest = 0.0
    for col in cols.values():
        col.sort(key=lambda sh: sh["row"])
        for lo, hi in zip(col, col[1:]):
            top = lo["sc"] + 0.5 * lo["len"]
            bot = hi["sc"] - 0.5 * hi["len"]
            mid = 0.5 * (top + bot)
            ends_ok = ends_ok and abs(top - bot - 1.5) < 1e-6 and min(abs(mid - p) for p in purl) < 1e-6
        longest = max(longest, max(sh["len"] for sh in col))
    check("clean rows: 150 mm end laps, each centred on a purlin, sheets no longer than 2.4 m",
          ends_ok and len(f0) > len(row0) and longest <= 24.0 + 1e-6, "%d rows, longest %.2f" % (
              len(f0) // len(row0), longest))
    gaps = [b_ - a for a, b_ in zip(heights, heights[1:])]
    m = F.ms
    sp = [g * math.sqrt(1 + m * m) / m for g in gaps]
    check("purlins at no more than 900 mm down the slope", max(sp) <= 9.0 + 1e-6 and len(heights) >= 3,
          "%d purlins, %s" % (len(heights), [round(x, 2) for x in sp]))
    seen = [sh["lift_l"] for sh in row0]
    check("laid away from the weather: every sheet but the first laps over the one before (End A: from -x)",
          seen[0] is False and all(seen[1:]) and row0[0]["ac"] < row0[-1]["ac"])

    # --- UVs: variations (stacked, one tile or column a stack) and all laid out (no overlaps)
    rep = tb["make_thatch_roof"](b, dict(s, stacks=3))
    root = rep["root"]
    parts = tb["thatch_parts"](root)
    fn = mesh_fn(tb, parts["sheets"])
    us, vs = fn.getUVs()
    tiles = set(int(math.floor(u)) for u in us)
    check("variations: 3 stacks in UDIM tiles 1001-1003, all inside their tile",
          tiles == {0, 1, 2} and min(vs) >= 0.0 and max(vs) <= 1.0, str(sorted(tiles)))
    sh = tb["_log_shape"](parts["sheets"])
    check("variations are stacked (Smart UDIM leaves them alone)", cmds.getAttr(sh + "." + tb["UV_STACKED_ATTR"]))
    tb["update_thatch_roofs"]({root: {"stack_layout": "Atlas columns"}})
    fn = mesh_fn(tb, parts["sheets"])
    us, vs = fn.getUVs()
    check("variations as atlas columns: all in 0..1", min(us) >= 0.0 and max(us) <= 1.0 and max(vs) <= 1.0)
    # texel density: a 2.4 m sheet is 0.6 of a 4 m tile tall
    counts, ids = fn.getAssignedUVs()
    tb["update_thatch_roofs"]({root: {"m_uv_mode": "All laid out", "stack_layout": "UDIM tiles"}})
    fn = mesh_fn(tb, parts["sheets"])
    check("all laid out: not stacked", not cmds.getAttr(sh + "." + tb["UV_STACKED_ATTR"]))
    us, vs = fn.getUVs()
    nshell, ids_ = fn.getUvShellsIds()
    boxes = {}
    for uvid, shell in enumerate(ids_):
        u, v = us[uvid], vs[uvid]
        b0 = boxes.get(shell)
        boxes[shell] = (min(b0[0], u), min(b0[1], v), max(b0[2], u), max(b0[3], v)) if b0 else (u, v, u, v)
    # sheet tops and undersides (the edge strips are a hair wide)
    big = sorted([bx for bx in boxes.values() if min(bx[2] - bx[0], bx[3] - bx[1]) > 0.002], key=lambda q: q[0])
    overlaps = 0
    for i, a in enumerate(big):
        for c in big[i + 1:]:
            if c[0] >= a[2] - 1e-7:
                break
            if c[1] < a[3] - 1e-7 and a[1] < c[3] - 1e-7:
                overlaps += 1
    in_tile = all(math.floor(bx[0] + 1e-7) == math.floor(bx[2] - 1e-7) and
                  math.floor(bx[1] + 1e-7) == math.floor(bx[3] - 1e-7) for bx in big)
    tall = sum(1 for bx in big if bx[3] - bx[1] >= bx[2] - bx[0]) / float(len(big))
    check("all laid out: every sheet top and underside its own UV space, none overlapping, each inside a tile",
          overlaps == 0 and in_tile and len(big) >= 2 * rep["pieces"],
          "%d shells, %d overlaps, %d sheets" % (len(big), overlaps, rep["pieces"]))
    check("all laid out: long sides all run up V", tall > 0.99, "%.1f%% upright" % (tall * 100))
    heights_uv = sorted(bx[3] - bx[1] for bx in big)
    want = longest / (D["m_uv_tile"] * k)
    check("all laid out: one density (the longest sheet over 4 m tiles)", abs(heights_uv[-1] - want) < 0.01,
          "%.3f, want %.3f" % (heights_uv[-1], want))
    tfn = mesh_fn(tb, parts["trim"])
    tus, tvs = tfn.getUVs()
    check("trim UVs laid out in 0..1", min(tus) >= 0.0 and max(tus) <= 1.0 and min(tvs) >= 0.0 and max(tvs) <= 1.0)

    # --- real sizes in decimetres: pitch, depth, the sheets' rise
    cmds.file(new=True, force=True)
    b = box("size")
    rep = tb["make_thatch_roof"](b, {"covering": "Corrugated", "end_a": "Gable", "end_b": "Gable", "m_fixings": False,
                                     "frame": False, "m_ridge_cap": False, "m_barge": False})
    fn = mesh_fn(tb, tb["thatch_parts"](rep["root"])["sheets"])
    pts = fn.getPoints(om.MSpace.kWorld)
    # a ray down the middle of a sheet at mid slope: heights of the top surface along x show the corrugation
    acc = fn.autoUniformGridParams()
    prof = []
    for i in range(200):
        x = 0.5 + i * 0.019
        hit = fn.closestIntersection(om.MFloatPoint(x, 100.0, 10.0), om.MFloatVector(0, -1, 0), om.MSpace.kWorld, 1e3,
                                     False, accelParams=acc)
        prof.append(hit[0].y if hit else None)
    prof = [p for p in prof if p is not None]
    depth = max(prof) - min(prof)
    peaks = [i for i in range(1, len(prof) - 1) if prof[i] >= prof[i - 1] and prof[i] > prof[i + 1] and
             prof[i] > min(prof) + 0.7 * depth]
    pitch = (peaks[-1] - peaks[0]) * 0.019 / max(1, len(peaks) - 1) if len(peaks) > 1 else 0.0
    check("decimetres: 76 mm pitch is 0.76 units, 18 mm deep is 0.18 units (seen vertically on a 45-degree roof)",
          abs(pitch - 0.76) < 0.05 and abs(depth - 0.18 * math.sqrt(2.0)) < 0.06,
          "pitch %.3f, depth %.3f" % (pitch, depth))
    bb = cmds.exactWorldBoundingBox(tb["thatch_parts"](rep["root"])["sheets"])
    check("sheets run 50 mm past the eave into the gutter line", bb[5] > 20.0 + 0.3 and bb[5] < 20.0 + 0.6,
          "%.3f" % bb[5])

    # --- old thatch roofs: left exactly as they were, and switching to metal and back
    cmds.file(new=True, force=True)
    b = box("old", size=(6.0, 3.0, 4.0), move=(0.0, 4.0, 0.0))
    rep = tb["make_thatch_roof"](b, {"resolution": 40})
    root = rep["root"]
    data = json.loads(cmds.getAttr(root + "." + tb["THATCH_SETTINGS"]))
    for key in list(data):
        if key == "covering" or key.startswith("m_"):
            del data[key]
    cmds.setAttr(root + "." + tb["THATCH_SETTINGS"], json.dumps(data), type="string")  # as an older tool left it
    straw = tb["thatch_parts"](root)["straw"]
    before = mesh_fn(tb, straw).getPoints(om.MSpace.kWorld)
    tb["update_thatch_roofs"]({root: {}})
    after = mesh_fn(tb, straw).getPoints(om.MSpace.kWorld)
    same = len(before) == len(after) and all((p - q).length() < 1e-6 for p, q in zip(before, after))
    check("an old thatch roof (no covering stored) rebuilds exactly as before and needs no upgrade",
          same and not tb["thatch_needs_upgrade"](root) and set(tb["thatch_parts"](root)) ==
          {"straw", "underlay", "frame"}, "%d -> %d points" % (len(before), len(after)))
    rep = tb["roof_set_covering"]([root], "Corrugated")
    parts = tb["thatch_parts"](root)
    check("switching it to corrugated adds the metal meshes and hides the thatch",
          {"sheets", "trim", "fixings"} <= set(parts) and cmds.getAttr(parts["sheets"] + ".visibility") and
          not cmds.getAttr(parts["straw"] + ".visibility") and rep["done"] == [root], str(sorted(parts)))
    tb["roof_set_covering"]([root], "Thatch")
    again = mesh_fn(tb, straw).getPoints(om.MSpace.kWorld)
    check("and back to thatch: the same straw again, the metal hidden",
          len(again) == len(before) and all((p - q).length() < 1e-6 for p, q in zip(before, again)) and
          not cmds.getAttr(parts["sheets"] + ".visibility") and cmds.getAttr(parts["straw"] + ".visibility"))
    cmds.undo()  # the switch back is a live edit; the undo takes out the added meshes
    check("one undo removes the meshes the switch added", "sheets" not in tb["thatch_parts"](root),
          str(sorted(tb["thatch_parts"](root))))
    # undo / redo of a new metal roof
    cmds.file(new=True, force=True)
    b = box("undo")
    rep = tb["make_thatch_roof"](b, {"covering": "Corrugated"})
    root = rep["root"]
    check("a metal roof is named as metal", "metalRoof" in root and all(
        "metalRoof" in tb["short_name"](n) for n in tb["thatch_parts"](root).values()), root)
    cmds.undo()
    check("undo removes it", not cmds.objExists(root))
    cmds.redo()
    tb["rebuild_stale_thatch"]()
    fn = mesh_fn(tb, tb["thatch_parts"](root)["sheets"])
    check("redo brings it back built", fn.numPolygons > 100, "%d faces" % fn.numPolygons)
    # live edits: profile, mode, detail
    for change in ({"m_profile": "Box", "m_pitch": 0.19, "m_depth": 0.029}, {"m_mode": "Makeshift"},
                   {"detail": "Proxy"}, {"detail": "Hero"}, {"m_sag": 1.0}):
        t0 = time.time()
        rep = tb["update_thatch_roofs"]({root: change})
        check("live edit %s (%.2fs)" % (change, time.time() - t0), rep["done"] == [root] and not rep["errors"])
    # moving the box rebuilds (the panel's follow): the stored frame changes
    cmds.move(5, 0, 0, b, relative=True)
    check("moving the box marks the roof moved", tb["thatch_box_moved"](root))
    # save and reopen
    path = os.path.join(os.environ.get("TEMP", "."), "unlok_corrugated_test.ma")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaAscii", force=True)
    cmds.file(path, open=True, force=True)
    roofs = tb["thatch_roofs"]()
    check("save / reopen keeps the roof live", len(roofs) == 1 and
          tb["thatch_data"](roofs[0])["covering"] == "Corrugated")
    try:
        os.remove(path)
    except OSError:
        pass
    # bake
    done, gone = tb["bake_thatch"](roofs)
    check("bake keeps the metal meshes as plain meshes", done and not tb["thatch_roofs"]() and
          all(cmds.objExists(n) for n in tb["thatch_parts"](done[0]).values()), str(gone))

    # --- speed: a big roof
    cmds.file(new=True, force=True)
    b = box("big", size=(160.0, 40.0, 90.0))
    for mode in ("Clean", "Makeshift"):
        t0 = time.time()
        rep = tb["make_thatch_roof"](b, {"covering": "Corrugated", "m_mode": mode, "end_a": "Hip", "end_b": "Gable"})
        dt = time.time() - t0
        check("speed: a 16 x 9 m %s roof under 8 s" % mode, dt < 8.0, "%.2fs, %d sheets" % (dt, rep["pieces"]))
        check("a 16 x 9 m %s roof isn't reported as capped (its cappings aren't the vertex cap)" % mode,
              not rep["capped"])


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
