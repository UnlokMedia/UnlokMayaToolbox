"""Headless benchmark: where a live edit's time goes in a 4-layer scatter group (mayapy).

    mayapy tests/bench_scatter_layers.py [--profile]

The user (2026-11-19): "this has a lot of loading and feels very heavy when
you start getting like 3 or 4 layers". On the yard (40 x 40 dm floor, wall
ring, crate) grows Moss mat + Scattered blades + Dead leaves + Young shoots
(ivy), then times live edits (sc_update, as a slider does) on each layer and
a no-op edit, split into stages by wrapping the engine's functions.
"""

import cProfile
import io
import os
import pstats
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
STAGES = ("_mi_surface", "sc_surfaces", "_sc_grown_layers", "_sc_read_layer", "_sc_build_layer", "_sc_place_udims",
          "_sc_write", "_rope_fill", "_mi_write_colors", "_sc_write_layer_shoots", "_sc_fit_box", "sc_fix_box",
          "_mi_drop_repeats", "_sc_set_text")
T = {}


def wrap(tb, name):
    fn = tb[name]

    def timed(*a, **k):
        t0 = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            T[name] = T.get(name, 0.0) + time.perf_counter() - t0
    tb[name] = timed


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


def report(label, dt):
    parts = ", ".join("%s %.2f" % (k.lstrip("_"), v) for k, v in sorted(T.items(), key=lambda x: -x[1]) if v >= 0.005)
    print("%-34s %6.2f s | %s" % (label, dt, parts))
    sys.stdout.flush()


def run():
    tb = {"__name__": "unlok_bench", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), tb)
    for name in STAGES:
        wrap(tb, name)
    profile = "--profile" in sys.argv
    moss = os.environ.get("BENCH_MOSS", "Moss mat")
    grp = yard(tb)
    tb["mi_clear_caches"]()
    stack = [("Moss", moss), ("Grass", "Scattered blades"), ("Leaves", "Dead leaves"), ("Ivy", "Young shoots")]
    T.clear()
    t0 = time.perf_counter()
    rep = tb["create_scatter_group"]([grp], stack[0][0], tb["sc_quick_settings"](*stack[0]), select=False)
    root = rep["root"]
    report("create + %s" % stack[0][1], time.perf_counter() - t0)
    for typ, preset in stack[1:]:
        T.clear()
        t0 = time.perf_counter()
        tb["sc_add_layer"](root, typ, tb["sc_quick_settings"](typ, preset))
        report("add %s" % preset, time.perf_counter() - t0)
    layers = tb["sc_data"](root)["layers"]
    verts = sum(cmds.polyEvaluate(n, vertex=True) for n in tb["sc_parts"](root).values())
    print("layers %s, %d verts in parts" % ([l["type"] for l in layers], verts))
    edits = {"Moss": ("coverage", 0.61), "Grass": ("density", None), "Leaves": ("density", None),
             "Ivy": ("seed", None)}
    for layer in layers:
        typ = layer["type"]
        s = tb["sc_settings"](layer)
        for key in ("coverage", "density", "amount", "count", "spread", "seed"):
            if isinstance(s.get(key), (int, float)) and not isinstance(s.get(key), bool):
                break
        val = s[key]
        for i in range(2):
            new = val + (1 if key == "seed" else 0.03 * (i + 1) * (1 if val < 0.9 else -1))
            T.clear()
            pr = cProfile.Profile() if profile and i == 1 else None
            t0 = time.perf_counter()
            if pr:
                pr.enable()
            tb["sc_update"](root, layer["id"], {key: new})
            if pr:
                pr.disable()
            report("edit %s.%s #%d" % (typ, key, i + 1), time.perf_counter() - t0)
            if pr:
                out = io.StringIO()
                pstats.Stats(pr, stream=out).sort_stats("cumulative").print_stats(28)
                print(out.getvalue())
    # the same edits as the panel makes them now: settle=False (only the edited layer), then sc_settle
    for layer in layers:
        s = tb["sc_settings"](layer)
        for key in ("coverage", "density", "seed"):
            if isinstance(s.get(key), (int, float)) and not isinstance(s.get(key), bool):
                break
        new = s[key] + (1 if key == "seed" else -0.05)
        T.clear()
        t0 = time.perf_counter()
        rep = tb["sc_update"](root, layer["id"], {key: new}, settle=False)
        report("live %s.%s (stale %s)" % (layer["type"], key, ",".join(rep.get("stale") or []) or "-"),
               time.perf_counter() - t0)
        T.clear()
        t0 = time.perf_counter()
        tb["sc_settle"](root)
        report("  then settle", time.perf_counter() - t0)
    # nothing changed at all: the fixed cost of an edit (every layer a cache hit)
    for i in range(2):
        T.clear()
        t0 = time.perf_counter()
        tb["sc_regrow"](root)
        report("regrow, all cached #%d" % (i + 1), time.perf_counter() - t0)
    # a rename (no growth) through the panel's path
    T.clear()
    t0 = time.perf_counter()
    tb["sc_update"](root, layers[-1]["id"], {}, layer_change={"name": "x"})
    report("layer_change only", time.perf_counter() - t0)
    # draft on, moss edit
    tb["sc_set_draft"](True)
    T.clear()
    t0 = time.perf_counter()
    tb["sc_update"](root, layers[0]["id"], {"coverage": 0.5})
    report("edit Moss, Draft on", time.perf_counter() - t0)
    tb["sc_set_draft"](False)


if __name__ == "__main__":
    code = 0
    try:
        run()
    except Exception:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(code)
