"""GUI timing test: how long a selection change takes with the toolbox open.

The user's bug (2026-11-05): with the toolbox open, selecting meshes (to
start a scatter) sometimes froze Maya; with it closed, any number was fine.
Every built panel has a SelectionChanged scriptJob, and some did real work
for hidden tabs (Quad Fill hunted for holes on every mesh picked whole).

Scene: 200 detailed spheres (64 x 64) and two small scatter groups. Every
panel is built (as if each tab had been opened that session), then the
toolbox sits on the Scatter tab. Each selection change (all 200, one, none)
is timed with cProfile from cmds.select until every panel's selection
timer has fired: the time spent in the toolbox's own callbacks.

The test is a generator stepped by Qt timers: scriptJobs only run once
Maya idles, which it never does inside one long scripted call.

Launch (Maya 2023+), with UNLOK_TEST_DIR set to this folder:

    maya.exe -script tests/run_gui_selection_speed.mel

UNLOK_TOOLBOX picks another copy of UnlokToolbox.py (to time an old one).
Outputs go to $UNLOK_TEST_OUT (default: tests/_out/selection_speed).
"""

import cProfile
import io
import json
import os
import pstats
import time
import traceback

import maya.cmds as cmds

try:
    from PySide2 import QtCore, QtWidgets
except ImportError:
    from PySide6 import QtCore, QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "selection_speed")
RESULTS = []
TIMES = {}
N_MESHES = 200
LIMIT = 0.1  # seconds of toolbox work per selection change, at most
STATE = {}


def check(name, cond, detail=""):
    RESULTS.append({"name": name, "ok": bool(cond), "detail": str(detail)})
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))


def timers(window):
    out = []
    for panel in window.built_panels():
        for name in ("_sel_timer", "_inspect_timer"):
            t = getattr(panel, name, None)
            if isinstance(t, QtCore.QTimer):
                out.append(t)
    return out


def settle(window):
    """Yields until Maya has idled and every selection timer has fired."""
    yield 0.4
    for _ in range(40):
        if not any(t.isActive() for t in timers(window)):
            break
        yield 0.1
    yield 0.1


def toolbox_seconds(prof, tool_file):
    """Time spent in the toolbox's own functions called from Qt / scriptJobs:
    the cumulative time of the outermost toolbox frames."""
    st = pstats.Stats(prof)
    total = 0.0
    for (fname, line, func), (cc, nc, tt, ct, callers) in st.stats.items():
        if os.path.normcase(fname) != os.path.normcase(tool_file):
            continue
        if any(os.path.normcase(c[0]) == os.path.normcase(tool_file) for c in callers):
            continue
        total += ct
    return total


def timed(label, window, nodes, reps=3):
    runs = []
    top = ""
    for _ in range(reps):
        cmds.select(clear=True)
        for w in settle(window):
            yield w
        prof = cProfile.Profile()
        prof.enable()
        if nodes:
            cmds.select(nodes, replace=True)
        else:
            cmds.select(clear=True)
        for w in settle(window):
            yield w
        prof.disable()
        runs.append(toolbox_seconds(prof, TOOLBOX))
        s = io.StringIO()
        pstats.Stats(prof, stream=s).sort_stats("cumulative").print_stats(r"UnlokToolbox", 14)
        top = s.getvalue()
    worst = max(runs)  # a run can miss the event (0.0): the slowest is the one that counts
    TIMES[label] = {"toolbox_s": round(worst, 4), "runs": [round(r, 4) for r in runs]}
    print("TIME %-40s toolbox %.4f s (runs %s)" % (label, worst,", ".join("%.4f" % r for r in runs)))
    with open(os.path.join(OUT, "profile_%s_%s.txt" % (os.environ.get("UNLOK_TEST_TAG", "run"),
                                                        label.replace(" ", "_").replace(",", ""))), "w") as f:
        f.write(top)


def steps():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    ns = {"__name__": "__main__", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    import __main__

    cmds.file(new=True, force=True)
    cmds.undoInfo(stateWithoutFlush=False)
    meshes = []
    for i in range(N_MESHES):
        m = cmds.polySphere(subdivisionsX=64, subdivisionsY=64, radius=1, constructionHistory=False,
                            name="rock%03d" % i)[0]
        cmds.setAttr(m + ".translate", (i % 20) * 3.0, 0, (i // 20) * 3.0)
        meshes.append(cmds.ls(m, long=True)[0])
    groups = []
    for i in range(2):
        p = cmds.polyPlane(width=4, height=4, subdivisionsX=4, subdivisionsY=4, constructionHistory=False,
                           name="ground%d" % i)[0]
        cmds.setAttr(p + ".translate", -10.0 - 6 * i, 0, 0)
        s = dict(ns["sc_defaults"]("Specks"))
        rep = ns["create_scatter_group"]([cmds.ls(p, long=True)[0]], "Specks", s, [], {})
        groups.append(rep["root"])
    cmds.undoInfo(stateWithoutFlush=True)
    cmds.select(clear=True)
    check("two scatter groups made", len(groups) == 2 and all(cmds.objExists(g) for g in groups), groups)

    ns["show"]()
    yield 1.0
    window = getattr(__main__, ns["REGISTRY_KEY"])["window"]
    panels = window.panels()  # every tab opened this session
    check("every panel built", len(panels) > 5, len(panels))
    window.show_tool("Quad Fill")
    yield 0.5
    window.show_tool("Scatter")
    yield 1.0
    sc = [p for p in panels if p.TOOL_NAME == "Scatter"][0]
    qf = [p for p in panels if p.TOOL_NAME == "Quad Fill"][0]
    check("Scatter tab on screen", sc.isVisible() and not qf.isVisible())

    for w in timed("Scatter tab, 200 meshes", window, meshes):
        yield w
    cmds.select(meshes, replace=True)
    for w in settle(window):
        yield w
    check("Scatter sees the 200 meshes", "200 mesh" in sc.next_banner.text.text(), sc.next_banner.text.text())
    for w in timed("Scatter tab, 1 mesh", window, meshes[:1]):
        yield w
    for w in timed("Scatter tab, none", window, []):
        yield w
    for w in timed("Scatter tab, a scatter group", window, groups[:1]):
        yield w
    check("Scatter edits the picked group", sc._root == groups[0], sc._root)

    window.show_tool("Quad Fill")
    yield 0.5
    for w in timed("Quad Fill tab, 200 meshes", window, meshes, reps=1):
        yield w
    check("Quad Fill asks for an edge with many meshes picked whole",
          not qf.holes and "picked whole" in qf.hole_label.text(), qf.hole_label.text()[:200])
    for w in timed("Quad Fill tab, 1 mesh", window, meshes[:1], reps=1):
        yield w
    check("Quad Fill: one closed mesh has no holes", "no holes" in qf.hole_label.text(), qf.hole_label.text())

    window.hide()
    yield 0.5
    for w in timed("Toolbox hidden, 200 meshes", window, meshes, reps=1):
        yield w
    window.show()
    yield 0.5

    best = TIMES["Scatter tab, 200 meshes"]["toolbox_s"]
    check("200 meshes on the Scatter tab: under %.2f s of toolbox work" % LIMIT, best < LIMIT, "%.4f s" % best)
    check("toolbox hidden: next to nothing", TIMES["Toolbox hidden, 200 meshes"]["toolbox_s"] < 0.02,
          TIMES["Toolbox hidden, 200 meshes"])


def finish():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    with open(os.path.join(OUT, os.environ.get("UNLOK_TEST_TAG", "results") + ".json"), "w") as f:
        json.dump({"results": RESULTS, "times": TIMES, "toolbox": TOOLBOX}, f, indent=2)
    if os.environ.get("UNLOK_TEST_QUIT") == "1":
        cmds.quit(force=True)


def step():
    try:
        wait = next(STATE["gen"])
    except StopIteration:
        finish()
        return
    except Exception:
        RESULTS.append({"name": "exception", "ok": False, "detail": traceback.format_exc()})
        traceback.print_exc()
        finish()
        return
    QtCore.QTimer.singleShot(int(wait * 1000), step)


def run():
    STATE["gen"] = steps()
    step()


cmds.evalDeferred(run, lowestPriority=True)
