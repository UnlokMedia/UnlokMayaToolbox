"""GUI test for the Roof panel's Roof Map (the clickable roof picture).

Opens the toolbox on the Roof panel and, for each covering (palm, straw,
metal, tiles), end shape and view (Cut open, Slice, From above), checks that
every part drawn can be found under the mouse, that a click opens and
flashes its settings, that a quick choice edits the field the panel's own
way, and that lean-to / cone and folding work. Saves a picture of each view.

Launch (Maya 2023+), with UNLOK_TEST_DIR set to this folder:

    maya.exe -script tests/run_gui_roof_map.mel

Outputs go to $UNLOK_TEST_OUT (default: tests/_out/roof_map).
"""

import json
import os
import traceback

import maya.cmds as cmds

try:
    from PySide2 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "roof_map")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append({"name": name, "ok": bool(cond), "detail": str(detail)})
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))


def pump(n=5):
    app = QtWidgets.QApplication.instance()
    for _ in range(n):
        app.processEvents()


def find_point(rmap, part, end):
    """A widget point where the canvas finds this part (None: nowhere)."""
    canvas = rmap.canvas
    s, ox, oy = canvas._xf()
    for p_, e_, kind, data, hit in rmap.drawing.items:
        if p_ != part or e_ != end or hit is None:
            continue
        r = hit.boundingRect()
        steps = 9
        for i in range(steps + 1):
            for j in range(steps + 1):
                x = r.left() + r.width() * i / float(steps)
                y = r.top() + r.height() * j / float(steps)
                if not hit.contains(QtCore.QPointF(x, y)):
                    continue
                w = QtCore.QPoint(int(round(x * s + ox)), int(round(y * s + oy)))
                if canvas.part_at(w) == (part, end):
                    return w
    return None


def set_field(panel, key, value):
    w = panel.f[key]
    w.setValue(value)
    w.changed.emit()
    pump()


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    ns = {"__name__": "__main__", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    import __main__

    cmds.file(new=True, force=True)
    ns["show"]()
    pump(20)
    window = getattr(__main__, ns["REGISTRY_KEY"])["window"]
    panel = [p for p in window.panels() if p.TOOL_NAME == "Roof"][0]
    names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    window.tabs.setCurrentIndex(names.index("Modeling"))
    page = window.pages[names.index("Modeling")]
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Roof"][0].click()
    pump(20)
    rmap = panel.roof_map
    if not rmap.fold.isChecked():
        rmap.fold.setChecked(True)
        pump()
    check("the map is on screen with a picture", rmap.canvas.isVisible() and rmap.drawing is not None and
          len(rmap.drawing.items) > 50, len(rmap.drawing.items) if rmap.drawing else None)
    window.grab().save(os.path.join(OUT, "00_panel.png"))

    looks = [("palm", {"covering": "Thatch", "style": "Palm Fronds", "end_a": "Hip", "end_b": "Gable",
                       "ridge_fronds": True, "ridge_poles": True, "lashings": True, "hip_poles": True}),
             ("palm_half", {"end_a": "Half-hip", "end_b": "Hip", "frond_layout": "Bundles", "ridge_poles": False}),
             ("straw", {"style": "Planes", "end_a": "Gable", "end_b": "Hip", "pattern": "Scallops", "top": 0.15,
                        "cap": 1.0}),
             ("metal", {"covering": "Corrugated", "m_mode": "Makeshift", "end_a": "Hip"}),
             ("tiles", {"covering": "Tiles", "end_a": "Gable", "end_b": "Half-hip", "t_mode": "Makeshift"})]
    expect = {"palm": {"ridge", "pole", "corner", "verge", "eave", "outer", "neat", "underlay", "rafters", "battens",
                       "beam", "end"},
              "straw": {"ridge", "corner", "verge", "eave", "outer", "underlay", "rafters", "end"},
              "metal": {"ridge", "corner", "eave", "outer", "rafters", "battens", "end"},
              "tiles": {"ridge", "corner", "verge", "eave", "outer", "underlay", "rafters", "end"}}
    for name, values in looks:
        for k, v in values.items():
            if k in panel.f:
                set_field(panel, k, v)
        check("%s: the map reads the panel" % name, rmap.state["cov"] == name.split("_")[0], rmap.state["cov"])
        for view in ("Cut open", "Slice", "From above"):
            rmap.views.setValue(view)
            rmap.views.changed.emit()
            pump()
            d = rmap.drawing
            parts = sorted({(p, e) for p, e, k, dt, h in d.items if p and h is not None}, key=str)
            missing = [pe for pe in parts if find_point(rmap, *pe) is None]
            check("%s / %s: every part can be pointed at" % (name, view), not missing and parts,
                  "missing %s of %s" % (missing, parts))
            if view == "Cut open" and name.split("_")[0] in expect:
                got = {p for p, e in parts}
                want = set(expect[name.split("_")[0]])
                if not panel.f["ridge_poles"].value():
                    want.discard("pole")
                if panel.f["end_a"].value() == "Gable":  # the cut view shows the + end's corner lines only
                    want.discard("corner")
                check("%s: the cut-open roof shows its parts" % name, want <= got, sorted(want - got))
            rmap.canvas.grab().save(os.path.join(OUT, "%s_%s.png" % (name, view.replace(" ", "_").lower())))

    # --- hover names, click jumps
    set_field(panel, "covering", "Thatch")
    set_field(panel, "style", "Palm Fronds")
    set_field(panel, "end_a", "Hip")
    rmap.views.setValue("Cut open")
    rmap.views.changed.emit()
    pump()
    pt = find_point(rmap, "ridge", None)
    rmap.hover(rmap.canvas.part_at(pt), None)
    check("hover names the top line", "Top line" in rmap.hint.text(), rmap.hint.text())
    rmap.hover(None, None)
    panel.poles_sec.header.setChecked(False)
    panel.step_shape.set_expanded(False, user=True)
    pump()
    rmap.open_part(("ridge", None))
    pump(10)
    check("a click on the top line opens Ridge, poles and ties", panel.poles_sec.header.isChecked(), "")
    check("... and lights its rows", len(rmap._flashed) >= 2, len(rmap._flashed))
    rmap.open_part(("end", "a"))
    pump(10)
    lbl = panel._rows["end_a"][0]
    check("a click on the + end opens step 3 and lights + end", panel.step_shape.expanded and
          any(w is lbl for w, _ in rmap._flashed), "")
    sb = rmap.scroll.verticalScrollBar().value()
    rmap.open_part(("rafters", None))
    pump(10)
    check("a click on the rafters scrolls down to the frame", rmap.scroll.verticalScrollBar().value() > sb and
          panel.frame_sec.header.isChecked(), (sb, rmap.scroll.verticalScrollBar().value()))
    rmap._unflash()
    check("the flash goes back", all(not w.styleSheet() for w, _ in rmap._flashed) and not rmap._flashed, "")

    # --- quick choices edit the field the panel's way
    choices = ns["_rm_choices"]("end", "a", rmap.state)
    check("quick choices for an end offer its shape", choices and choices[0][1] == "end_a", choices[:1])
    rmap._set("end_a", "Half-hip")
    pump()
    check("a quick choice sets the field and redraws", panel.f["end_a"].value() == "Half-hip" and
          rmap.state["endA"] == "half", panel.f["end_a"].value())
    rmap._set("ridge_poles", False)
    pump()
    check("switching the top pole off takes it off the map", not any(p == "pole" for p, e, k, dt, h in
                                                                     rmap.drawing.items), "")
    # --- lean-to, cone
    for shape in ("Lean-to", "Cone"):
        set_field(panel, "shape", shape)
        missing = [pe for pe in {(p, e) for p, e, k, dt, h in rmap.drawing.items if p and h is not None}
                   if find_point(rmap, *pe) is None]
        check("%s: a simple picture, every part findable" % shape, rmap.drawing and not missing, missing)
        rmap.canvas.grab().save(os.path.join(OUT, "shape_%s.png" % shape.lower()))
    set_field(panel, "shape", "Ridge")
    # --- fold
    rmap.fold.setChecked(False)
    pump()
    check("folded: no picture kept", rmap.drawing is None and not rmap.canvas.isVisible(), "")
    rmap.fold.setChecked(True)
    pump()
    check("unfolded: drawn again", rmap.drawing is not None and rmap.canvas.isVisible(), "")
    check("the view is remembered", cmds.optionVar(q=ns["RM_VIEW_VAR"]) == rmap.views.value(), "")
    window.grab().save(os.path.join(OUT, "01_panel_after.png"))
    rmap.shutdown()
    check("shutdown stops its timers", not rmap._flash_timer.isActive() and not rmap._scroll_timer.isActive(), "")


def run():
    try:
        main()
    except Exception:
        RESULTS.append({"name": "exception", "ok": False, "detail": traceback.format_exc()})
        traceback.print_exc()
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(RESULTS, f, indent=2)
    if os.environ.get("UNLOK_TEST_QUIT") == "1":
        cmds.quit(force=True)


cmds.evalDeferred(run, lowestPriority=True)
