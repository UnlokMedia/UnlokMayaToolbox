"""Where Smart Layout's Plan spends its time on a bigger asset (mayapy).

    mayapy tests/bench_plan.py [COPIES] [--ropes N] [--freeform] [--profile]

Builds the test building, copies its wings COPIES times (default 6, about
250 meshes; the 19,200-face dome is left out of the copies), Auto UVs it
once, then times collect_shells (reading the scene) and make_plan (the
search) for each layout mode, twice, so the second Plan shows what the
shell cache saves. Squares (one per material group) unless --freeform;
also times a Quick Plan (no shells read) and prints its density.
"""

import cProfile
import os
import pstats
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "bench_plan", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]
COPIES = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 6


def run():
    tb = ns["load_toolbox"]()
    root, kinds = ns["build_building"]()
    dome = [m for m in kinds if "dome" in m]
    wings = cmds.listRelatives(root, children=True, fullPath=True) or []
    for i in range(COPIES - 1):
        for w in wings:
            dup = cmds.duplicate(w, name=w.split("|")[-1].replace("_GRP", "%d_GRP" % (i + 2)))[0]
            for m in cmds.listRelatives(dup, allDescendents=True, fullPath=True, type="transform") or []:
                if "dome" in m:
                    cmds.delete(m)
    ropes = int(sys.argv[sys.argv.index("--ropes") + 1]) if "--ropes" in sys.argv else 0
    if ropes:  # multi-shell meshes (rope binds): many small shells each
        grp = cmds.group(empty=True, name="ropes_GRP", parent=root)
        import random as _r
        _r.seed(5)
        for i in range(ropes):
            parts = []
            for j in range(30):
                c = cmds.polyCylinder(r=_r.uniform(0.005, 0.02), h=_r.uniform(0.05, 0.3), sx=8, sy=1)[0]
                cmds.move(_r.uniform(0, 1), _r.uniform(0, 1), i * 0.1, c)
                parts.append(c)
            r = cmds.polyUnite(parts, constructionHistory=False, name="ropeTan_C_bind%04d_GEP" % (i + 1))[0]
            cmds.parent(r, grp)
    cmds.scale(100, 100, 100, root)
    cmds.makeIdentity(root, apply=True, scale=True)
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    meshes = asset.meshes()[0]
    t = time.time()
    tb["run_auto_uv"](asset, score=False, unwrapper=tb["UNWRAP_METHODS"][0], pack="fit")
    print("%d meshes, %d sections; Auto UV %.1fs" % (len(meshes), len(asset.sections()), time.time() - t))
    settings = dict(tb["LAYOUT_DEFAULTS"], texel_density=128.0, map_size="2048", orientation="Upright",
                    group_similar=True, keep_meshes=True, squares="--freeform" not in sys.argv)
    t = time.time()
    q = tb["quick_groups"](asset)
    qp = tb["make_plan"](q, dict(settings, mode=tb["FIT_ROWS"], squares=True))
    print("Quick Plan: %.2fs, %d px/m, %d tiles" % (time.time() - t, qp["density"], len(qp["new_tiles"])))
    prof = cProfile.Profile() if "--profile" in sys.argv else None
    for attempt in (1, 2):
        t = time.time()
        if prof and attempt == 1:
            prof.enable()
        col = tb["collect_shells"](asset)
        if prof and attempt == 1:
            prof.disable()
        t_col = time.time() - t
        n = sum(len(g["shells"]) for g in col["groups"])
        line = "Plan %d: read %.2fs (%d shells, %d groups)" % (attempt, t_col, n, len(col["groups"]))
        for mode in ("Fixed density", "Fit to tiles", tb["FIT_ROWS"]):
            t = time.time()
            plan = tb["make_plan"](col, dict(settings, mode=mode))
            line += " | %s %.2fs (%d tiles, %d px/m)" % (mode, time.time() - t, len(plan["new_tiles"]),
                                                         plan["density"])
        print(line)
    if prof:
        prof2 = cProfile.Profile()
        prof2.enable()
        tb["make_plan"](col, dict(settings, mode=tb["FIT_ROWS"]))
        prof2.disable()
        pstats.Stats(prof).sort_stats("cumulative").print_stats(14)
        pstats.Stats(prof2).sort_stats("cumulative").print_stats(14)


try:
    run()
except Exception:
    traceback.print_exc()
finally:
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(0)
