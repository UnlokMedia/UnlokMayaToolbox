"""Headless tests for Rope Lashing (mayapy).

    mayapy tests/test_rope_lashing.py

Ties square, diagonal, round, sheer and band lashings on plain and Log
Noise logs in every rope style, and checks: the rope clears the logs and
itself, UVs fill 0..1 without leaving it, undo / redo (the redo re-ties
the seed plane), save / reopen, live edits, refit after moving a log,
whole-frame pairing, presets (optionVar) and speed.
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


def log(name, r=0.15, h=3.0, move=(0, 0, 0), rot=(0, 0, 0)):
    node = cmds.ls(cmds.polyCylinder(r=r, h=h, sx=24, sy=16, name=name, constructionHistory=False)[0], long=True)[0]
    cmds.rotate(rot[0], rot[1], rot[2], node)
    cmds.move(move[0], move[1], move[2], node)
    return node


def log_between(name, p0, p1, r):
    """A cylinder running from p0 to p1."""
    v = [p1[i] - p0[i] for i in range(3)]
    length = math.sqrt(sum(c * c for c in v))
    node = cmds.polyCylinder(r=r, h=length, sx=24, sy=12, name=name, constructionHistory=False)[0]
    y = [c / length for c in v]
    x = [0, 0, 1] if abs(y[2]) < 0.9 else [1, 0, 0]
    z = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]]
    zl = math.sqrt(sum(c * c for c in z))
    z = [c / zl for c in z]
    x = [y[1] * z[2] - y[2] * z[1], y[2] * z[0] - y[0] * z[2], y[0] * z[1] - y[1] * z[0]]
    mid = [(p0[i] + p1[i]) * 0.5 for i in range(3)]
    cmds.xform(node, matrix=x + [0] + y + [0] + z + [0] + mid + [1], worldSpace=True)
    return cmds.ls(node, long=True)[0]


def mesh_fn(tb, node):
    return om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))


def run():
    tb = load_toolbox()
    cmds.undoInfo(state=True, infinity=True)

    # --- the joint maths picks the right lashing
    post = log("post", move=(0, 1.5, 0))
    beam = log("beam", rot=(0, 0, 90), move=(0, 2.0, 0.3))
    a = log("braceA", rot=(0, 0, 20), move=(3, 1.5, 0))
    b = log("braceB", rot=(0, 0, -20), move=(3, 1.5, 0.3))
    c = log("sideA", move=(6, 1.5, 0))
    d = log("sideB", move=(6.3, 1.5, 0))
    e = log("legA", move=(9, 1.5, 0))
    f = log("legB", move=(9.4, 1.5, 0))
    P = tb["RopePole"]
    J = tb["rope_joint"](P(post), P(beam))
    check("pole fit: radius and axis of a cylinder", abs(P(post).r - 0.15) < 0.01 and
          abs(abs(P(post).a[1]) - 1.0) < 1e-6, "r %.4f" % P(post).r)
    check("square joint: 90 deg, touching", abs(J["angle"] - 90) < 0.5 and abs(J["gap"]) < 0.01,
          "angle %.1f gap %.4f" % (J["angle"], J["gap"]))
    kind = tb["rope_lashing_kind"]
    check("auto kinds: square / diagonal / round",
          kind({}, 90) == "Square" and kind({}, 40) == "Diagonal" and kind({}, 0) == "Round")
    check("forced kinds fit the angle", kind({"lashing": "Square"}, 5) == "Round" and
          kind({"lashing": "Sheer"}, 80) == "Diagonal" and kind({"lashing": "Bands"}, 80) == "Bands")

    # --- every lashing in every style
    def clearance(path, poles):
        X, rr = path["points"], path["radius"]
        h = math.dist(X[0], X[1])
        skip = int(3.0 * 2.0 * rr / h) + 2
        worst_self = 9.0
        cell = 2.0 * rr
        grid = {}
        for i, p in enumerate(X):
            key = tuple(int(math.floor(v / cell)) for v in p)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for j in grid.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                            if j < i - skip:
                                worst_self = min(worst_self, math.dist(p, X[j]))
            grid.setdefault(key, []).append(i)
        worst_pole = 9.0
        for pole in poles:
            for p in X:
                t = pole.closest_t(p)
                if pole.t0 < t < pole.t1:
                    v = tb["_rl_perp"](pole.a, tb["_rl_sub"](p, pole.center(t)))
                    worst_pole = min(worst_pole, tb["_rl_len"](v) - pole.radius(t))
        return worst_self / (2.0 * rr), worst_pole / rr

    cases = [("Square", [post, beam], {}), ("Diagonal", [a, b], {"lashing": "Diagonal"}),
             ("Round", [c, d], {}), ("Sheer", [e, f], {"lashing": "Sheer"}),
             ("Sheer", [c, d], {"lashing": "Sheer"}), ("Bands", [post, beam],
                                                                                {"lashing": "Bands"})]
    for name, logs, extra in cases:
        poles = [P(x) for x in logs]
        s = dict(extra, seed=5)
        path = tb["rope_path"](poles, s)
        self_c, pole_c = clearance(path, poles)
        check("%s: rope clears itself and the logs" % name, self_c > 0.75 and pole_c > 0.2,
              "self %.2f dia, logs %.2f radii (%d points)" % (self_c, pole_c, len(path["points"])))
        check("%s: tied as %s" % (name, name), path["kind"] == name, path["kind"])
    for style in ("3 strands", "Twisted", "Smooth tube"):
        t0 = time.time()
        rep = tb["lash"]([post, beam], {"style": style, "seed": 2})
        dt = time.time() - t0
        node = rep["made"][0]
        fn = mesh_fn(tb, node)
        us, vs = fn.getUVs()
        ok_uv = min(us) >= 0 and max(us) <= 1 and min(vs) >= 0 and max(vs) <= 1
        check("%s: mesh, UVs inside 0..1" % style, fn.numVertices > 1000 and ok_uv and
              fn.numUVs() >= fn.numVertices, "%d verts, %d uvs, u %.3f..%.3f v %.3f..%.3f" % (
                  fn.numVertices, fn.numUVs(), min(us), max(us), min(vs), max(vs)))
        shells = cmds.polyEvaluate(node, uvShell=True)
        check("%s: few UV shells (one per strip)" % style, 1 <= shells <= 40, "%d shells" % shells)
        flipped = cmds.polyUVOverlap(node + ".f[*]", overlappingComponents=True) or []
        check("%s: no overlapping UVs" % style, not flipped, "%d overlapping" % len(flipped))
        check("%s: under 1.5 s" % style, dt < 1.5, "%.2fs" % dt)
        cmds.delete(node)
    check("rope named by convention, in lashings_GRP",
          cmds.ls("lashings_GRP") and rep["made"][0].split("|")[-1].startswith("ropeNatural_C_lashing"),
          rep["made"][0])

    # --- undo / redo / save / reopen
    rep = tb["lash"]([post, beam], {"seed": 3})
    node = rep["made"][0]
    nv = mesh_fn(tb, node).numVertices
    cmds.undo()
    check("Ctrl+Z removes the lashing", not cmds.objExists(node))
    cmds.redo()
    fn = mesh_fn(tb, node)
    check("redo brings back the seed plane", fn.numVertices == 4)
    stale = tb["rebuild_stale_ropes"]()
    check("rebuild_stale_ropes re-ties it the same", len(stale) == 1 and mesh_fn(tb, node).numVertices == nv,
          "%d vs %d" % (mesh_fn(tb, node).numVertices, nv))
    folder = tempfile.mkdtemp(prefix="ropetest")
    path = os.path.join(folder, "rope.mb")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaBinary", force=True)
    cmds.file(new=True, force=True)
    cmds.file(path, open=True, force=True)
    node = tb["ropes_in"]()[0]
    check("save / reopen keeps the rope", mesh_fn(tb, node).numVertices == nv)
    check("reopened rope isn't stale", not tb["rebuild_stale_ropes"]())

    # --- live edits and refit
    post = cmds.ls("post", long=True)[0]
    rep = tb["update_ropes"]({node: {"thickness": 0.2, "style": "Smooth tube"}})
    data = tb["rope_data"](node)
    check("live edit re-ties with the new settings", rep["done"] == [node] and data["thickness"] == 0.2 and
          data["style"] == "Smooth tube")
    before = cmds.exactWorldBoundingBox(node)
    cmds.move(0.5, 0, 0, post, relative=True)
    tb["update_ropes"]({node: {}})
    after = cmds.exactWorldBoundingBox(node)
    check("refit follows a moved log", abs((after[0] + after[3]) - (before[0] + before[3]) - 0.5 * 2) < 0.2,
          "centre x %.3f -> %.3f" % ((before[0] + before[3]) / 2, (after[0] + after[3]) / 2))
    q = cmds.undoInfo(q=True, undoName=True)
    check("live edits stay out of the undo queue", q != "Rope edit", q)
    cmds.delete(cmds.ls("beam", long=True)[0])
    rep = tb["update_ropes"]({node: {"wobble": 0.5}})
    check("a deleted log is reported, not crashed on", rep["lost"] == [node])
    check("bake drops the settings", tb["bake_ropes"]([node]) == [node] and not tb["is_rope"](node))

    # --- a frame: every touching pair, nothing else
    cmds.file(new=True, force=True)
    logs = []
    for i, (x, z) in enumerate(((0, 0), (2, 0), (0, 2), (2, 2))):
        logs.append(log("post%d" % i, move=(x, 1.5, z)))
    for i, (pos, rot) in enumerate((((1, 2.5, 0.3), (0, 0, 90)), ((1, 2.5, 2.3), (0, 0, 90)),
                                    ((0.3, 2.0, 1), (90, 0, 0)), ((2.3, 2.0, 1), (90, 0, 0)))):
        logs.append(log("beam%d" % i, h=2.6, move=pos, rot=rot))
    t0 = time.time()
    rep = tb["lash"](logs, {"style": "Twisted"})
    dt = time.time() - t0
    check("frame of 4 posts + 4 beams: 8 lashings", len(rep["made"]) == 8, "%d made, kinds %s, skipped %s" % (
        len(rep["made"]), rep["kinds"], rep["skipped"]))
    check("frame: under 14 s", dt < 14.0, "%.2fs" % dt)  # 8 joints with the settle: ~10-11 s on the dev machine
    cmds.undo()
    check("one Ctrl+Z removes the whole frame's lashings", not tb["ropes_in"]())

    # --- log noise logs: the rope sits on the bumps
    g = log("g", r=0.17, move=(0, 1.5, 0))
    hh = log("h", r=0.13, rot=(10, 0, 85), move=(0, 2.0, 0.29))
    tb["add_log_noise"]([g, hh], {"bump": 0.08, "bend": 0.03}, seeds={g: 11, hh: 12})
    poles = [P(g), P(hh)]
    path = tb["rope_path"](poles, {"seed": 1})
    self_c, _ = clearance(path, poles)
    inside = 0
    for pole in poles:
        for p in path["points"]:
            t = pole.closest_t(p)
            if pole.t0 < t < pole.t1:
                v = tb["_rl_perp"](pole.a, tb["_rl_sub"](p, pole.center(t)))
                dist = tb["_rl_len"](v)
                if dist < 1.2 * pole.r:
                    surf = pole.surface(t, tb["_rl_norm"](v))
                    if dist < surf:
                        inside += 1
    check("Log Noise logs: rope centre never under the bumpy surface", inside == 0 and self_c > 0.75,
          "%d inside, self %.2f" % (inside, self_c))

    # --- live preview: same rope as Lash, not undoable, never saved
    cmds.file(new=True, force=True)
    post = log("post", move=(0, 1.5, 0))
    beam = log("beam", rot=(0, 0, 90), move=(0, 2.0, 0.3))
    cmds.select(post)
    rep = tb["show_rope_previews"]([post, beam], {"style": "Smooth tube"})
    prev = rep["made"]
    check("preview: one mesh, selection untouched", len(prev) == 1 and cmds.ls(selection=True, long=True) == [post])
    pv = mesh_fn(tb, prev[0]).numVertices
    tb["show_rope_previews"]([post, beam], {"style": "Smooth tube", "lashing": "Diagonal"})
    check("preview: a new setting replaces it", len(tb["rope_previews"]()) == 1 and
          cmds.getAttr(tb["rope_previews"]()[0] + "." + tb["ROPE_PREVIEW_ATTR"]) == "Diagonal")
    path = os.path.join(folder, "preview.mb")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaBinary", force=True)
    cmds.file(new=True, force=True)
    cmds.file(path, open=True, force=True)
    check("preview: never saved with the scene", not tb["rope_previews"]() and cmds.objExists("post"))
    post, beam = cmds.ls("post", long=True)[0], cmds.ls("beam", long=True)[0]
    tb["show_rope_previews"]([post, beam], {"style": "Smooth tube"})
    tb["clear_rope_previews"]()
    rep = tb["lash"]([post, beam], {"style": "Smooth tube"})
    check("Lash keeps exactly what the preview showed", mesh_fn(tb, rep["made"][0]).numVertices == pv and
          not tb["rope_previews"]())

    # --- baked lashings: plain meshes, never logs, and a redo still rebuilds them
    cmds.file(new=True, force=True)
    post = log("post", move=(0, 1.5, 0))
    beam = log("beam", rot=(0, 0, 90), move=(0, 2.0, 0.3))
    rep = tb["lash"]([post, beam], {"style": "Smooth tube"}, bake=True)
    node = rep["made"][0]
    nb = mesh_fn(tb, node).numVertices
    check("lash(bake=True): a plain mesh, not a lashing", nb > 100 and not tb["is_rope"](node) and
          not tb["ropes_in"]())
    cmds.undo()
    check("one Ctrl+Z removes the baked lashing", not cmds.objExists(node))
    cmds.redo()
    tb["rebuild_stale_ropes"]()
    check("redo rebuilds the baked lashing too", mesh_fn(tb, node).numVertices == nb and not tb["is_rope"](node),
          "%d vs %d" % (mesh_fn(tb, node).numVertices, nb))
    cmds.select(node, post, beam)
    ropes, logs, _ = tb["rope_selection"]()
    check("a baked lashing is never taken for a log", not ropes and sorted(logs) == sorted([post, beam]), str(logs))
    live = tb["lash"]([post, beam], {"style": "Smooth tube"})["made"][0]
    tb["bake_ropes"]([live])
    cmds.undo()
    check("undoing a bake makes it a lashing again", tb["is_rope"](live))

    # --- Smart UDIM: lashings come in as Keep UVs (never re-unwrapped or scored, still laid out)
    cmds.file(new=True, force=True)
    shack = cmds.ls(cmds.group(empty=True, name="shack_GRP"), long=True)[0]
    post = cmds.ls(cmds.parent(log("wood_C_post_GEP", move=(0, 1.5, 0)), shack)[0], long=True)[0]
    beam = cmds.ls(cmds.parent(log("wood_C_beam_GEP", rot=(0, 0, 90), move=(0, 2.0, 0.3)), shack)[0], long=True)[0]
    baked_rope = tb["lash"]([post, beam], {"style": "Smooth tube"}, bake=True)["made"][0]
    live_rope = tb["lash"]([post, beam], {"style": "Smooth tube", "lashing": "Bands"})["made"][0]
    ropes = [cmds.ls(cmds.parent(r, shack)[0], long=True)[0] for r in (baked_rope, live_rope)]
    def uv_layout(r):  # UV count and shells: an unwrap changes them, packing only moves the shells
        return mesh_fn(tb, r).numUVs(), cmds.polyEvaluate(r, uvShell=True)
    uvs_before = {r: uv_layout(r) for r in ropes}
    asset = tb["SmartUdimAsset"].for_group(shack)
    res = asset.scan()
    st = asset.uv_status()
    check("Scan marks lashings Keep UVs, logs stay Auto", all(st.get(r) == "keep" for r in ropes) and
          post not in st and res.get("ready") == 2, "%s ready=%s" % (st, res.get("ready")))
    auto = tb["run_auto_uv"](asset)
    rows = {r["mesh"]: r for r in auto.get("rows", [])}
    same = all(uv_layout(r) == uvs_before[r] for r in ropes)
    check("Auto UV doesn't re-unwrap or score lashings (only packs them)", same and
          all("Keep" in rows.get(r, {}).get("reason", "Keep") for r in ropes),
          str([rows.get(r, {}).get("reason") for r in ropes]))
    asset.set_uv_status([ropes[0]], "auto")
    asset.scan()
    check("marking a lashing Auto sticks through the next Scan", ropes[0] not in asset.uv_status() and
          asset.uv_status().get(ropes[1]) == "keep")

    # --- the settle: gravity sags free rope, Settle 0 switches the simulation off (and is faster)
    cmds.file(new=True, force=True)
    e = log("legA", move=(9, 1.5, 0))
    f = log("legB", move=(9.4, 1.5, 0))
    def low_free(path):
        X, rr = path["points"], path["radius"]
        ys = [p[1] for p in X if min(tb["_rl_len"](tb["_rl_perp"](q.a, tb["_rl_sub"](p, q.center(q.closest_t(p)))))
                                    - q.radius(q.closest_t(p)) for q in poles) > 2.0 * rr]
        return min(ys) if ys else None
    sheer_s = {"lashing": "Sheer", "seed": 4, "wobble": 0.0}
    t0 = time.time()
    flat = tb["rope_path"]([P(e), P(f)], dict(sheer_s, settle=0))
    t_off = time.time() - t0
    t0 = time.time()
    tight = tb["rope_path"]([P(e), P(f)], dict(sheer_s, tension=0.5, gravity=0.0))
    t_on = time.time() - t0
    poles = [P(e), P(f)]
    sag = tb["rope_path"](poles, dict(sheer_s, tension=0.0, gravity=1.5))
    check("Gravity sags rope that isn't on a log", low_free(sag) is not None and low_free(tight) is not None and
          low_free(sag) < low_free(tight) - 0.5 * tight["radius"],
          "lowest free point %.4f vs %.4f" % (low_free(sag) or 0, low_free(tight) or 0))
    check("Settle 0 skips the simulation (faster)", len(flat["points"]) > 100 and t_off < t_on,
          "%.2fs off vs %.2fs on" % (t_off, t_on))

    # --- logs that end at another: a saddle lashing; several logs at one joint: each tied in once
    cmds.file(new=True, force=True)
    post = log("post", r=0.12, move=(0, 1.5, 0))
    beam = log("beam", r=0.1, rot=(0, 0, 90), move=(0, 3.1, 0))
    poles = [P(post), P(beam)]
    path = tb["rope_path"](poles, {"seed": 2})
    self_c, pole_c = clearance(path, poles)
    check("post under a beam: a Saddle lashing that clears itself and the logs",
          path["kind"] == "Saddle" and self_c > 0.75 and pole_c > 0.2,
          "%s, self %.2f dia, logs %.2f radii" % (path["kind"], self_c, pole_c))
    rafter = log_between("rafter", (0.26, 3.29, 0.0), (0.3, 4.6, -1.6), 0.09)  # ends resting on the beam,
    rafter2 = log_between("rafter2", (-0.26, 3.29, 0.0), (-0.3, 4.6, 1.6), 0.09)  # one each side of the post
    four = [P(x) for x in (post, beam, rafter, rafter2)]
    path = tb["rope_path"](four, {"seed": 2})
    self_c, pole_c = clearance(path, four)
    check("four logs at one joint: one continuous rope that clears itself and the logs",
          # one rope binding three joints stacks more turns at one spot: allow a little more squeeze
          path["kind"] == "Combined" and len(path["poles"]) == 4 and self_c > 0.7 and pole_c > 0.2,
          "%s %s, self %.2f dia, logs %.2f radii" % (path["kind"], path.get("parts"), self_c, pole_c))
    rep = tb["lash"]([post, beam, rafter, rafter2], {"style": "Smooth tube"})
    tied = set()
    for r in rep["made"]:
        tied |= set(tb["rope_data"](r)["poles"])
    every = all(cmds.ls(x, uuid=True)[0] in tied for x in (post, beam, rafter, rafter2))
    check("selecting the four logs binds them all with one lashing",
          every and len(rep["made"]) == 1, "%d lashings %s, skipped %s" % (len(rep["made"]), rep["kinds"],
                                                                        rep["skipped"]))
    node = rep["made"][0]
    n0 = mesh_fn(tb, node).numVertices
    up = tb["update_ropes"]({node: {"style": "Twisted"}})
    check("a combined lashing re-ties live like any other", up["done"] == [node] and
          mesh_fn(tb, node).numVertices != n0, str(up))

    # --- presets live in an optionVar
    var = tb["ROPE_PRESET_VAR"]
    old = cmds.optionVar(q=var) if cmds.optionVar(exists=var) else None
    try:
        tb["rope_save_preset"]("test shack", dict(tb["ROPE_DEFAULTS"], thickness=0.07, style="3 strands"))
        s = tb["rope_preset"]("test shack")
        check("user preset saves and loads", s and s["thickness"] == 0.07 and s["style"] == "3 strands")
        check("built-in preset fills in defaults", tb["rope_preset"]("Hero (close-ups)")["style"] == "3 strands"
              and tb["rope_preset"]("Hero (close-ups)")["wraps"] == 0)
        check("user preset deletes", tb["rope_delete_preset"]("test shack") and
              tb["rope_preset"]("test shack") is None)
    finally:
        if old is None:
            cmds.optionVar(remove=var)
        else:
            cmds.optionVar(stringValue=(var, old))


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
