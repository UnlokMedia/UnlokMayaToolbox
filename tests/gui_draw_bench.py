"""Benchmark: how live does path drawing feel? Run inside GUI Maya.

Strokes across a roof the way a user would (one drag event per mouse move),
in a busy scene with a live scatter, and times each drag event including the
UI work Maya does afterwards. Writes draw_bench.json to $UNLOK_TEST_OUT.

Set UNLOK_TOOLBOX to benchmark a different copy of the toolbox file, and
UNLOK_BENCH_PROFILE=1 to save a Python profile of the first stroke.
Launch: set UNLOK_TEST_DIR to the tests folder, then
    maya.exe -script tests/run_gui_draw_bench.mel
"""

import json
import os
import time
import traceback

import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaUI as omui

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out")


def pump():
    QtWidgets.QApplication.instance().processEvents()


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    ns = {"__name__": "__main__", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    import __main__
    panel = getattr(__main__, ns["REGISTRY_KEY"])["window"].panels()[0]

    cmds.file(new=True, force=True)
    roof = cmds.polyPlane(w=12, h=8, sx=24, sy=16, name="roof")[0]
    cmds.rotate(-30, 0, 0, roof)
    cmds.makeIdentity(roof, apply=True)
    # A busy scene: lots of other meshes the stroke could hit.
    for i in range(400):
        c = cmds.polyCube(w=0.3, h=0.3, d=0.3)[0]
        cmds.move((i % 20) * 0.8 - 8, -3, (i // 20) * 0.8 - 8, c)
    # A live scatter already in the scene, selected (Channel Box shows it).
    curve = cmds.curve(degree=1, point=[(-5.5, 0, 3), (5.5, 0, 3)], name="eave")
    cmds.select(curve)
    panel.use_selected_path()
    panel.apply_recipe("Messy Thatch")
    cmds.select(roof)
    panel.use_selected_surface()
    panel.rebuild()
    cmds.select(panel.system.root())
    cmds.setAttr("persp.translate", 0, 9, 16)
    cmds.viewLookAt("persp", position=(0, 0, 0))
    cmds.refresh(force=True)
    pump()
    view = omui.M3dView.active3dView()

    def screen(p):
        r = view.worldToView(om.MPoint(*p))
        return float(r[0]), float(r[1])

    drawer = panel.drawer
    drawer.forced_surfaces = []
    if hasattr(drawer, "_ensure_preview"):  # what activate() does when Draw Path is pressed
        drawer._ensure_preview()
    # Let Maya finish the idle work queued by the setup (UI rebuilds, first draw).
    settle_until = time.time() + 3.0
    while time.time() < settle_until:
        pump()
        cmds.refresh()

    # Break the per-event cost down by stage.
    prof = {}

    def timed(label, fn):
        def wrapper(*a, **k):
            t0 = time.time()
            try:
                return fn(*a, **k)
            finally:
                prof[label] = prof.get(label, 0.0) + (time.time() - t0) * 1000.0
        return wrapper

    for name in ("_cast", "_update_preview", "_create_preview", "_delete_preview"):
        if hasattr(drawer, name):
            setattr(drawer, name, timed(name, getattr(drawer, name)))
    real_refresh = cmds.refresh
    cmds.refresh = timed("cmds.refresh", real_refresh)
    pump_timed = timed("processEvents", pump)
    results = {"toolbox": TOOLBOX, "scatter_items": panel.system.last_count}
    import gc
    gc_log = []
    gc_start = {}

    def gc_cb(phase, info):
        if phase == "start":
            gc_start["t"] = time.time()
        else:
            gc_log.append((info.get("generation"), round((time.time() - gc_start.get("t", time.time())) * 1000.0, 1)))

    gc.callbacks.append(gc_cb)
    strokes = [("freehand", "none"), ("freehand_2", "none"), ("freehand_3", "none"), ("straight", "shift")]
    profile_first = os.environ.get("UNLOK_BENCH_PROFILE") == "1"
    for label, mod in strokes:
        if profile_first and label == strokes[0][0]:
            import cProfile
            pyprof = cProfile.Profile()
            pyprof.enable()
        a = screen((-5, 0.5, 2))
        b = screen((5, 0.5, -1))
        drawer.press_at(a[0], a[1], mod)
        times = []
        n = 150
        for i in range(1, n + 1):
            t = float(i) / n
            x = a[0] + (b[0] - a[0]) * t
            y = a[1] + (b[1] - a[1]) * t + 25.0 * ((i % 7) - 3) / 3.0  # a bit of wobble
            t0 = time.time()
            drawer.drag_at(x, y)
            pump_timed()  # the UI work Maya does between mouse moves
            times.append(((time.time() - t0) * 1000.0, i))
        if profile_first and label == strokes[0][0]:
            pyprof.disable()
            import io
            import pstats
            buf = io.StringIO()
            pstats.Stats(pyprof, stream=buf).sort_stats("cumulative").print_stats(40)
            with open(os.path.join(OUT, "first_stroke_python.txt"), "w") as fh:
                fh.write(buf.getvalue())
        t0 = time.time()
        drawer.release()
        pump()
        release_ms = (time.time() - t0) * 1000.0
        times.sort()
        results[label] = {
            "events": n,
            "avg_ms": round(sum(t for t, _ in times) / n, 2),
            "p90_ms": round(times[int(n * 0.9)][0], 2),
            "max_ms": round(times[-1][0], 2),
            "max_at_event": times[-1][1],
            "top3": [(round(t, 1), i) for t, i in times[-3:]],
            "slow_gc": [g for g in gc_log if g[1] > 20],
            "release_ms": round(release_ms, 1),
            "paths": len(panel.system.paths()) if panel.system else 0,
            "stage_totals_ms": {k: round(v, 1) for k, v in prof.items()},
        }
        prof.clear()
        del gc_log[:]
    cmds.refresh = real_refresh
    return results


def run():
    try:
        res = main()
    except Exception:
        res = {"error": traceback.format_exc()}
    with open(os.path.join(OUT, "draw_bench.json"), "w") as f:
        json.dump(res, f, indent=2)
    if os.environ.get("UNLOK_TEST_QUIT") == "1":
        cmds.quit(force=True)


cmds.evalDeferred(run, lowestPriority=True)
