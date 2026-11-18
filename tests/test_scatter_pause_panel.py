"""Headless test: while Scatter is paused, no panel slider grows anything (mayapy).

    mayapy tests/test_scatter_pause_panel.py

The user (2026-11-18): "some of the tools still trigger even in pause ...
moving some of the sliders and stuff still causes it to load". Every
layer type's every field in the Scatter panel is changed while paused
(the panel's own path: changed -> _queue -> _apply_pending), and a moss
slider is dragged and let go (the slow-layer draft path, which grew the
layer in full on release). Nothing may build until Play; Play then grows.
"""

import os
import sys
import traceback

from PySide2 import QtWidgets
APP = QtWidgets.QApplication(sys.argv)
import maya.standalone  # noqa: E402
maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def nudge(v):
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        return v + 1
    if isinstance(v, float):
        return v * 0.7 + 0.05
    return v


def run():
    tb = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), tb)
    cmds.file(new=True, force=True)
    plane = cmds.polyPlane(w=10, h=10, sx=2, sy=2, name="ground", constructionHistory=False)[0]
    builds = []
    real = tb["sc_build"]

    def counted(*a, **k):
        builds.append(a[0])
        return real(*a, **k)

    tb["sc_build"] = counted
    rep = tb["create_scatter_group"]([plane], "Moss", {"detail": "Proxy", "coverage": 0.3}, select=False)
    root = rep["root"]
    lids = {}
    for typ in tb["SC_TYPES"]:
        if typ == "Moss":
            lids[typ] = tb["sc_data"](root)["layers"][0]["id"]
            continue
        lids[typ] = tb["sc_add_layer"](root, typ, {"detail": "Proxy", "coverage": 0.3})[1]
    panel = tb["ScatterPanel"]()
    tb["sc_pause"]()
    del builds[:]
    stamp = cmds.getAttr(root + "." + tb["SC_STAMP"])
    tried = 0
    for typ, lid in lids.items():
        panel._root, panel._lid = root, lid
        panel._show(typ, tb["sc_settings"](tb["sc_layer"](tb["sc_data"](root), lid)))
        for key, widget in panel.f[typ].items():
            try:
                widget.setValue(nudge(widget.value()))
            except Exception:
                pass
            panel._queue(typ, key)
            panel._apply_pending()
            tried += 1
        if builds:
            check("paused: %s sliders grow nothing" % typ, False, "built %d times" % len(builds))
            del builds[:]
    check("paused: no slider of any layer type grows anything", not builds and
          cmds.getAttr(root + "." + tb["SC_STAMP"]) == stamp, "%d fields tried" % tried)

    # a slow moss layer, its slider dragged then let go (the draft path)
    typ, lid = "Moss", lids["Moss"]
    panel._root, panel._lid = root, lid
    panel._took[(root, lid)] = 5.0
    slider = panel.f[typ]["coverage"].slider
    slider.setSliderDown(True)
    panel.f[typ]["coverage"].setValue(0.6)
    panel._queue(typ, "coverage")
    panel._apply_pending()
    slider.setSliderDown(False)
    panel._apply_pending()
    check("paused: a moss slider dragged and let go grows nothing", not builds, "built %d times" % len(builds))
    check("... and its edit is saved", abs(float(tb["sc_layer"](tb["sc_data"](root), lid)["s"]["coverage"]) -
                                          0.6) < 1e-6)
    tb["sc_play"]()
    check("Play grows the edits", bool(builds) and cmds.getAttr(root + "." + tb["SC_STAMP"]) != stamp,
          "built %d times" % len(builds))
    panel.deleteLater()


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
