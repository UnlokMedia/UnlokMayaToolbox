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
    check("frame: under 6 s", dt < 6.0, "%.2fs" % dt)
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
