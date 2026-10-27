"""Headless tests for the live UV viewer's engine side (mayapy).

    mayapy tests/test_live_view.py

- shell hulls, and plan outlines landing exactly where _place_shell puts them
- make_plan's on_attempt hook (live view) and stopping a search from it
- PlanWorker: same plan as planning directly; stop() ends the thread
- scene_shell_outlines: shells, remembered, density matches the layout
- the UV Editor label mesh: built from rects, outside the asset, removable
"""

import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "live_view_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def run():
    tb = ns["load_toolbox"]()
    cmds.loadPlugin("Unfold3D", quiet=True)

    hull = tb["convex_hull"]([(0, 0), (1, 0), (1, 1), (0, 1), (0.5, 0.5), (0.2, 0.7)])
    check("convex hull keeps the corners, drops inside points", sorted(hull) == [(0, 0), (0, 1), (1, 0), (1, 1)])

    root, kinds = ns["build_building"]()
    cmds.scale(100, 100, 100, root)
    cmds.makeIdentity(root, apply=True, scale=True)
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    tb["run_auto_uv"](asset)
    col = tb["collect_shells"](asset)
    shells = [sh for g in col["groups"] for sh in g["shells"]]
    check("every shell has an outline", shells and all(len(sh.hull) >= 3 for sh in shells), "%d shells" % len(shells))

    base = dict(tb["LAYOUT_DEFAULTS"], texel_density=128.0, map_size="2048")
    plan = tb["make_plan"](col, base)
    worst = 0.0
    for sh in shells:
        pl = plan["placements"][id(sh)]
        q = tb["placed_outline"](sh, pl)
        u0, v0 = min(a for a, _ in q), min(b for _, b in q)
        u1, v1 = max(a for a, _ in q), max(b for _, b in q)
        worst = max(worst, abs(u0 - (pl[0] + pl[2])), abs(v0 - (pl[1] + pl[3])),
                    abs(u1 - (pl[0] + pl[2] + pl[6])), abs(v1 - (pl[1] + pl[3] + pl[7])))
    check("plan outlines sit exactly on their placements", worst < 1e-4, "worst %.2g UV" % worst)

    # --- live hook
    seen = []
    rows = tb["make_plan"](col, dict(base, mode=tb["FIT_ROWS"]), on_attempt=seen.append)
    check("Fit rows shows every attempt to the live view", len(seen) > 10 and rows["density"] > 0,
          "%d attempts" % len(seen))

    def stop_early(p):
        if len(seen) > 3:
            raise tb["Cancelled"]("superseded")
        seen.append(p)

    del seen[:]
    try:
        tb["make_plan"](col, dict(base, mode=tb["FIT_ROWS"]), on_attempt=stop_early)
        stopped = False
    except tb["Cancelled"]:
        stopped = True
    check("the hook can stop a search", stopped and len(seen) == 4)

    # --- background worker
    got = []
    w = tb["PlanWorker"](col, dict(base, mode=tb["FIT_ROWS"]))
    w.finished.connect(lambda worker, p, err: got.append((p, err)))
    w._run()  # on this thread, so the signal is delivered directly
    check("the worker finds the same plan as planning directly",
          got and got[0][1] is None and abs(got[0][0]["density"] - rows["density"]) < 1e-6,
          "%s" % (got and round(got[0][0]["density"], 2)))
    w = tb["PlanWorker"](col, dict(base, mode=tb["FIT_ROWS"]))
    t0 = time.time()
    w.start()
    w.stop()
    check("stop() ends a background search promptly", not w.thread.is_alive() and time.time() - t0 < 5.0,
          "%.2f s" % (time.time() - t0))

    # --- scene outlines
    tb["apply_layout"](asset, col, plan)
    wall = [m for m, k in kinds.items() if k == "stretched"][0]
    fn = tb["_mesh_fn"](wall)
    n_shells = fn.getUvShellsIds("map1")[0]
    unit = tb["_UNIT_TO_M"][cmds.currentUnit(q=True, linear=True)] ** 2
    outs = tb["scene_shell_outlines"](wall, "map1", unit, density=True)
    check("scene outlines: one per UV shell", len(outs) == n_shells, "%d / %d" % (len(outs), n_shells))
    dens = [o["density"] * 2048 for o in outs if o["density"]]
    check("scene outline density matches the layout target",
          dens and all(abs(d / 128.0 - 1.0) < 0.1 for d in dens), "%s px/m" % [round(d) for d in dens[:4]])
    check("scene outlines are remembered until the mesh changes",
          tb["scene_shell_outlines"](wall, "map1", unit, density=True) is outs)
    cmds.polyEditUV(wall + ".map[0]", u=0.01)
    check("...and re-read after a UV edit", tb["scene_shell_outlines"](wall, "map1", unit, density=True) is not outs)

    # --- UV Editor labels
    tiles = set(plan["tiles"])
    rects = tb["uv_label_rects"](tiles, {0: "westWing"})
    check("labels: borders, tile numbers and a section name in negative U",
          len(rects) > 4 * len(tiles) and any(r[2] < 0 for r in rects), "%d rects" % len(rects))
    meshes_before = set(asset.meshes()[0])
    lab = tb["build_uv_label_mesh"](tiles, {0: "westWing"})
    fn = tb["_mesh_fn"](lab)
    check("label mesh carries the rects as UVs", fn is not None and fn.numUVs("map1") == 4 * len(rects))
    check("...and isn't part of the asset", set(asset.meshes()[0]) == meshes_before)
    tb["build_uv_label_mesh"](tiles, {})
    check("rebuilding replaces it (one label mesh)", len(cmds.ls(tb["UV_LABEL_MESH"] + "*", type="transform")) == 1)
    tb["remove_uv_label_mesh"]()
    check("remove deletes it", not cmds.ls(tb["UV_LABEL_MESH"] + "*", type="transform"))


try:
    run()
except Exception:
    traceback.print_exc()
    RESULTS.append(("exception", False, ""))
finally:
    failed = [r for r in RESULTS if not r[1]]
    print("\n%d passed, %d failed" % (len(RESULTS) - len(failed), len(failed)))
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(1 if failed else 0)
