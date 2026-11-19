"""Headless test: Scatter's settle-later live edits (mayapy).

    mayapy tests/test_scatter_settle.py

The user (2026-11-19): "feels very heavy when you start getting like 3 or 4
layers". New leaves / grass layers rest on moss and On layers below, so a
live edit low in the stack grew every layer resting on it in the same edit.
A live edit with settle=False grows only the edited layer and keeps the
resting ones as they were; sc_settle grows them once the edits stop. Checks
on the yard (Light moss + Scattered blades + Dead leaves): one layer built
per live edit, stale ids reported, the settled result equal to a full
regrow, no readback of a stale layer, Pause / Play and Bake settle.
"""

import os
import sys
import time
import traceback

from PySide2 import QtWidgets
APP = QtWidgets.QApplication(sys.argv)
import maya.standalone  # noqa: E402
maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402
import maya.api.OpenMaya as om  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
RESULTS = []
BUILT = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def yard(tb):
    src = open(os.path.join(HERE, "test_moss_slope.py")).read()
    ns = {"__name__": "x", "om": om, "cmds": cmds}
    exec(compile(src[src.index("def wall_ring("):src.index("def face_png(")], "ring", "exec"), ns)
    cmds.file(new=True, force=True)
    floor = cmds.polyPlane(w=40, h=40, sx=4, sy=4, name="floor", constructionHistory=False)[0]
    ring = ns["wall_ring"](tb, "wallRing")
    box = cmds.polyCube(w=6, h=4, d=6, name="crate", constructionHistory=False)[0]
    cmds.move(-8, 2, 5, box)
    return cmds.group(floor, ring, box, name="yard_GRP")


def snapshot(tb, root):
    """{part key: (vertex count, world points)} of the group's parts."""
    out = {}
    for key, node in tb["sc_parts"](root).items():
        fn = om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))
        out[key] = [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kWorld)]
    return out


def same(a, b, lids=None, tol=1e-4):
    keys = [k for k in set(a) | set(b) if lids is None or k.split("/")[0] in lids]
    for k in keys:
        if k not in a or k not in b or len(a[k]) != len(b[k]):
            return False, k
        for p, q in zip(a[k], b[k]):
            if abs(p[0] - q[0]) > tol or abs(p[1] - q[1]) > tol or abs(p[2] - q[2]) > tol:
                return False, k
    return True, None


def run():
    tb = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), tb)
    build = tb["_sc_build_layer"]

    def counted(layer, *a, **k):
        BUILT.append(layer["id"])
        return build(layer, *a, **k)
    tb["_sc_build_layer"] = counted

    grp = yard(tb)
    tb["mi_clear_caches"]()
    rep = tb["create_scatter_group"]([grp], "Moss", tb["sc_quick_settings"]("Moss", "Light moss"), select=False)
    root = rep["root"]
    tb["sc_add_layer"](root, "Leaves", tb["sc_quick_settings"]("Leaves", "Dead leaves"))
    tb["sc_add_layer"](root, "Grass", tb["sc_quick_settings"]("Grass", "Scattered blades"))
    layers = tb["sc_data"](root)["layers"]
    moss, leaves, grass = [l["id"] for l in layers]
    s = tb["sc_settings"](layers[1])
    check("resting layers", s.get("on_moss") and s.get("on_layers"), "leaves rest on moss and layers below")

    # a full live edit (settle=True, the old way): every resting layer grows again
    del BUILT[:]
    t0 = time.time()
    tb["sc_update"](root, moss, {"coverage": 0.55})
    full_t = time.time() - t0
    check("old way grows the stack", set(BUILT) >= {moss, leaves}, "built %s in %.2f s" % (BUILT, full_t))

    # a live edit with settle=False: only the edited layer
    before = snapshot(tb, root)
    del BUILT[:]
    t0 = time.time()
    rep = tb["sc_update"](root, moss, {"coverage": 0.45}, settle=False)
    live_t = time.time() - t0
    stale = set(rep.get("stale") or ())
    check("live edit builds one layer", BUILT == [moss], "built %s in %.2f s (full %.2f s)" % (BUILT, live_t, full_t))
    check("stale reported", leaves in stale and tb["sc_stale"](root) == stale, "stale %s" % sorted(stale))
    mid = snapshot(tb, root)
    check("resting layers kept", same(before, mid, lids=stale)[0], "")
    import json
    grown = json.loads(cmds.getAttr(root + "." + tb["SC_GROWN"]))
    check("grown JSON leaves stale out", not [l for l in grown["layers"] if l["id"] in stale],
          [l["id"] for l in grown["layers"]])

    # another live edit on a stale layer's neighbour keeps it stale; a readback regrow never reads a stale one
    del BUILT[:]
    rep = tb["sc_update"](root, moss, {"coverage": 0.5}, settle=False)
    check("still stale after another live edit", leaves in tb["sc_stale"](root), "built %s" % BUILT)

    # settle: the result equals a full regrow from nothing
    del BUILT[:]
    t0 = time.time()
    rep = tb["sc_settle"](root)
    settle_t = time.time() - t0
    check("settle grows the stale layers", rep is not None and leaves in BUILT and moss not in BUILT,
          "built %s in %.2f s" % (BUILT, settle_t))
    check("nothing stale after settle", not tb["sc_stale"](root) and tb["sc_settle"](root) is None, "")
    settled = snapshot(tb, root)
    tb["mi_clear_caches"]()
    tb["_SC_BUILT"].clear()
    tb["sc_regrow"](root, readback=False)
    fresh = snapshot(tb, root)
    ok, bad = same(settled, fresh)
    check("settled = full regrow", ok, "differs at %s" % bad)

    # readback guard: a stale layer is never read back by a regrow with readback on
    tb["sc_update"](root, moss, {"coverage": 0.6}, settle=False)
    stale = tb["sc_stale"](root)
    tb["_SC_BUILT"].clear()
    del BUILT[:]
    tb["sc_regrow"](root)
    check("regrow grows stale layers (no readback)", stale and stale <= set(BUILT) and not tb["sc_stale"](root),
          "stale %s built %s" % (sorted(stale), BUILT))

    # paused: settle waits, Play settles
    tb["sc_update"](root, moss, {"coverage": 0.65}, settle=False)
    tb["sc_pause"]()
    check("paused: settle waits", tb["sc_settle"](root) is None and tb["sc_stale"](root), "")
    tb["sc_play"]()
    check("Play settles", not tb["sc_stale"](root), "")

    # bake settles first
    tb["sc_update"](root, moss, {"coverage": 0.55}, settle=False)
    want = set(tb["sc_stale"](root))
    del BUILT[:]
    done = tb["bake_scatter"]([root])
    check("bake settles first", done and want and want <= set(BUILT) and not tb["sc_stale"](root),
          "built %s" % BUILT)


if __name__ == "__main__":
    code = 0
    try:
        run()
    except Exception:
        traceback.print_exc()
        code = 1
    failed = [r for r in RESULTS if not r[1]]
    print("\n%d checks, %d failed" % (len(RESULTS), len(failed)))
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(1 if failed or code else 0)
