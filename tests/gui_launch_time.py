"""Launch time + every-tab GUI check: run inside an interactive Maya session.

Times what pasting the toolbox costs (read, compile, run the module, show()
the window, first paint), a few times over, in an empty scene and in a scene
with a few hundred meshes. Then opens every category tab and every tool in
it, timing each first open, checking nothing raised, and saving a picture of
each. A cProfile of one warm show() goes into the results too.

Launch (Maya 2023+), from an empty working folder:

    set MAYA_DISABLE_CER=1
    set MAYA_SKIP_USERSETUP_PY=1
    set UNLOK_TEST_QUIT=1
    set UNLOK_TEST_DIR=<this folder>
    maya.exe -script <this folder>/run_gui_launch_time.mel

Outputs go to $UNLOK_TEST_OUT (default: tests/_out/launch_time):
results.json (checks + timings), profile.txt, tab_*.png.
"""

import cProfile
import io
import json
import os
import pstats
import sys
import time
import traceback

import maya.cmds as cmds

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "launch_time")
RESULTS = []
TIMES = {}


def check(name, cond, detail=""):
    RESULTS.append({"name": name, "ok": bool(cond), "detail": str(detail)})
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))


def pump(n=6):
    app = QtWidgets.QApplication.instance()
    for _ in range(n):
        app.processEvents()


def paste_once(profile=None):
    """What a Script Editor paste does: compile the text, run it as __main__
    (minus the show() at the bottom, which is timed on its own)."""
    t0 = time.perf_counter()
    with open(TOOLBOX) as f:
        src = f.read()
    t1 = time.perf_counter()
    code = compile(src, "<maya console>", "exec")
    t2 = time.perf_counter()
    ns = {"__name__": "unlok_launch"}
    exec(code, ns)
    t3 = time.perf_counter()
    if profile is not None:
        profile.enable()
    window = ns["show"]()
    if profile is not None:
        profile.disable()
    t4 = time.perf_counter()
    pump()
    t5 = time.perf_counter()
    return ns, window, {"read": t1 - t0, "compile": t2 - t1, "module": t3 - t2, "show": t4 - t3,
                        "first_paint": t5 - t4, "total": t5 - t1}


def script_editor_paste():
    """The real path: the text goes into a Python Script Editor field (with
    its syntax colouring) and Execute All runs it as __main__, show() and
    all. Returns (set text, execute) seconds."""
    win = cmds.window(title="paste test", widthHeight=(600, 300))
    cmds.columnLayout(adjustableColumn=True)
    field = cmds.cmdScrollFieldExecuter(sourceType="python", height=280)
    cmds.showWindow(win)
    pump()
    with open(TOOLBOX) as f:
        src = f.read()
    t0 = time.perf_counter()
    cmds.cmdScrollFieldExecuter(field, edit=True, text=src)
    pump()
    t1 = time.perf_counter()
    cmds.cmdScrollFieldExecuter(field, edit=True, executeAll=True)
    pump()
    t2 = time.perf_counter()
    cmds.deleteUI(win)
    pump()
    return t1 - t0, t2 - t1


def timed_runs(label, n):
    runs = []
    ns = window = None
    for _ in range(n):
        ns, window, t = paste_once()
        runs.append(t)
    TIMES[label] = runs
    best = min(r["total"] for r in runs)
    print("%s: %s" % (label, ", ".join("%.3fs" % r["total"] for r in runs)))
    check("%s: window opens" % label, window is not None and window.isVisible(), "best %.3fs" % best)
    return ns, window


def category_tabs(window):
    return [window.tabs.tabText(i) for i in range(window.tabs.count())]


def tool_buttons(page):
    return [b for b in page.findChildren(QtWidgets.QPushButton) if b.property("unlokSegment")
            and b.parent() is page]


def walk_tabs(ns, window):
    """Open every tab and every tool once; time each first open."""
    opened = {}
    errors_before = len(RESULTS)
    for ti, name in enumerate(category_tabs(window)):
        t0 = time.perf_counter()
        window.tabs.setCurrentIndex(ti)
        pump()
        page = window.tabs.widget(ti)
        buttons = tool_buttons(page)
        opened["%s (tab)" % name] = time.perf_counter() - t0
        targets = buttons or [None]
        for bi, btn in enumerate(targets):
            label = btn.text() if btn is not None else name
            t0 = time.perf_counter()
            try:
                if btn is not None:
                    btn.click()
                pump()
                ok = True
                detail = ""
            except Exception:
                ok = False
                detail = traceback.format_exc()
            opened["%s / %s" % (name, label)] = time.perf_counter() - t0
            stack = getattr(page, "stack", None)
            current = stack.currentWidget() if stack is not None else page
            check("open %s / %s" % (name, label), ok and current is not None and current.isVisible(), detail)
            try:
                window.grab().save(os.path.join(OUT, "tab_%02d_%02d_%s.png" % (ti, bi, label.replace(" ", "_")
                                                                                 .replace("/", "_"))))
            except Exception:
                pass
    TIMES["first_open"] = opened
    return len(RESULTS) == errors_before


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    cmds.file(new=True, force=True)
    # Cold: the first paste in this Maya session (Qt / module imports not warm yet).
    timed_runs("empty scene, first paste", 1)
    timed_runs("empty scene, re-paste", 3)

    prof = cProfile.Profile()
    ns, window, t = paste_once(prof)
    stream = io.StringIO()
    stats = pstats.Stats(prof, stream=stream)
    stats.sort_stats("cumulative").print_stats(45)
    stats.sort_stats("tottime").print_stats(25)
    with open(os.path.join(OUT, "profile.txt"), "w") as f:
        f.write(stream.getvalue())

    pastes = [script_editor_paste() for _ in range(2)]
    TIMES["script editor paste (set text, execute)"] = pastes
    print("script editor paste: %s" % pastes)
    import __main__
    window = getattr(__main__, "_unlok_toolbox_registry", {}).get("window")
    check("script editor paste opens the window", window is not None and window.isVisible())

    # A scene with some content: anything that scans the scene at launch shows up here.
    cmds.file(new=True, force=True)
    root = cmds.group(empty=True, name="asset_GRP")
    for i in range(300):
        c = cmds.polyCube(name="woodBrown_C_plank%04d_GEP" % (i + 1))[0]
        cmds.move(i % 20, (i // 20) * 1.5, 0, c)
        cmds.parent(c, root)
    ns, window = timed_runs("300 meshes, re-paste", 3)

    walk_tabs(ns, window)

    # Re-paste after every tab was opened: one window, nothing left behind.
    ns, window, t = paste_once()
    pump()
    windows = [w for w in QtWidgets.QApplication.instance().topLevelWidgets()
               if w.objectName() == ns["WINDOW_OBJECT_NAME"] and w.isVisible()]
    check("re-paste after opening every tab leaves one window", len(windows) == 1, str(len(windows)))
    window.close()
    pump()


def run():
    try:
        main()
    except Exception:
        RESULTS.append({"name": "exception", "ok": False, "detail": traceback.format_exc()})
        traceback.print_exc()
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump({"maya": cmds.about(version=True), "python": sys.version.split()[0],
                   "checks": RESULTS, "times": TIMES}, f, indent=2)
    if os.environ.get("UNLOK_TEST_QUIT") == "1":
        cmds.quit(force=True)


cmds.evalDeferred(run, lowestPriority=True)
