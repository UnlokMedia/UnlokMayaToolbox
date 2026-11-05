"""Headless moss report (mayapy): the bench boulder grown at a Detail
through Scatter, then the edits the user drags (Coverage, Patch size,
Strands), each timed with sc_update (what the panel runs). Prints faces per
part and the scene file's size (.mb and .ma) after the first grow.

    mayapy tests/bench_moss_scene.py [--detail High] [--out <folder>]
"""
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "bench_moss.py")).read()
src = src[:src.index("\ntry:\n    main()")]
g = {"__name__": "bench_moss_scene", "__file__": os.path.join(HERE, "bench_moss.py")}
exec(compile(src, "bench_moss.py", "exec"), g)
cmds, maya = g["cmds"], g["maya"]
DETAIL = g["arg"]("--detail", "High")
OUT = g["arg"]("--out") or os.path.join(HERE, "_out", "bench_moss_scene")


def parts_report(tb, root):
    rows = []
    for key, node in sorted(tb["sc_parts"](root).items()):
        if not cmds.getAttr(node + ".visibility"):
            continue
        rows.append((key.split("/")[-1], int(cmds.polyEvaluate(node, face=True)),
                     int(cmds.polyEvaluate(node, vertex=True))))
    for key, node in sorted(tb.get("sc_shoots", lambda r: {})(root).items()):  # instanced shoots
        if not cmds.getAttr(node + ".visibility"):
            continue
        ps = tb["_sc_shoot_nodes"](node)[0]
        got = tb["_sc_read_shoots"](node)
        n = cmds.particle(ps, q=True, count=True)
        per = [f for _, f, _ in got[6]]
        rows.append(("shoots x%d" % n, sum(per[i] for i in got[7]["index"]), len(got[0])))
    return rows


def main():
    tb = g["load"]()
    rock = g["make_rock"]()
    s = dict(g["BASE"], detail=DETAIL)
    t = time.perf_counter()
    rep = tb["create_scatter_group"]([rock], "Moss", s, select=False)
    first = time.perf_counter() - t
    root = rep["root"]
    lid = tb["sc_data"](root)["layers"][0]["id"]
    print("first grow %-6s %6.2f s" % (DETAIL, first))
    for name, faces, verts in parts_report(tb, root):
        print("  part %-14s faces %8d  verts %8d" % (name, faces, verts))
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    for ext, typ in ((".mb", "mayaBinary"), (".ma", "mayaAscii")):
        path = os.path.join(OUT, "moss_" + DETAIL + ext)
        cmds.file(rename=path)
        cmds.file(save=True, type=typ, force=True)
        print("scene %s %.1f MB" % (ext, os.path.getsize(path) / 1048576.0))
    for label, change in (("Coverage 0.72 -> 0.6", {"coverage": 0.6}), ("Patch size 0.3 -> 0.25", {"patch_size": 0.25}),
                          ("Strands 1.4 -> 1.0", {"strands": 1.0})):
        t = time.perf_counter()
        tb["sc_update"](root, lid, change)
        print("%-24s %6.2f s" % (label, time.perf_counter() - t))
        sys.stdout.flush()


try:
    main()
except Exception:
    traceback.print_exc()
finally:
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(0)
