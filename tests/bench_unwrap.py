"""Where the Unlok unwrapper spends its time on the test building (mayapy).

    mayapy tests/bench_unwrap.py [--profile]

Prints read / unwrap / write time per mesh (slowest first) and, with
--profile, the hot functions of the pure-maths part.
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
ns = {"__name__": "bench_unwrap", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]


def run():
    tb = ns["load_toolbox"]()
    root, kinds = ns["build_building"]()
    meshes = list(kinds)
    rows = []
    t0 = time.time()
    datas = []
    for m in meshes:
        t = time.time()
        datas.append(tb["_uw_read"](m))
        rows.append([m, time.time() - t, 0.0, 0.0, len(datas[-1]["faces"]), {}])
    t_read = time.time() - t0
    prof = cProfile.Profile() if "--profile" in sys.argv else None
    shared = {}
    opts = dict(tb["UNWRAP_DEFAULTS"])
    t0 = time.time()
    results = {}
    for row, d in zip(rows, datas):
        t = time.time()
        if prof:
            prof.enable()
        results[d["mesh"]] = res = tb["_uw_mesh"](d, opts, {}, shared)
        if prof:
            prof.disable()
        row[2] = time.time() - t
        row[5] = res["stats"]
    t_un = time.time() - t0
    t0 = time.time()
    for row, d in zip(rows, datas):
        t = time.time()
        tb["_uw_write"](d["mesh"], d, results[d["mesh"]], "map1")
        row[3] = time.time() - t
    t_wr = time.time() - t0
    print("read %.2fs  unwrap %.2fs  write %.2fs  (%d meshes)" % (t_read, t_un, t_wr, len(rows)))
    for m, r, u, w, nf, st in sorted(rows, key=lambda x: -(x[1] + x[2] + x[3]))[:12]:
        st = dict((k, v) for k, v in st.items() if v)
        print("%-34s %6d faces  read %.2f  unwrap %.2f  write %.2f  %s" % (m.split("|")[-1], nf, r, u, w, st))
    if prof:
        pstats.Stats(prof).sort_stats("cumulative").print_stats(25)


try:
    run()
except Exception:
    traceback.print_exc()
finally:
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(0)
