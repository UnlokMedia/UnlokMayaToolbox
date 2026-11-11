"""GUI test for the Scatter influence paint: run inside an interactive Maya.

A yard (a floor that's one big quad, a wall at its back, a beam on the
floor) with a moss layer and a leaves layer. Paint Influence opens the
brush on the layer being edited; scripted strokes (press / drag / release
at screen points) paint moss out of a band across the floor (opacity 1),
then build it up subtly on the wall with 10% strokes, each stroke one
Ctrl+Z; Flood Remove + a stroke puts leaves only along the stroke; paused
strokes grow at Play; Stop Painting removes the overlay. Saves before /
after pictures and the panel.

Launch (Maya 2023+), with UNLOK_TEST_DIR set to this folder:

    maya.exe -script tests/run_gui_scatter_paint.mel

Outputs go to $UNLOK_TEST_OUT (default: tests/_out/scatter_paint).
"""

import json
import os
import time
import traceback

import maya.cmds as cmds

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "scatter_paint")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append({"name": name, "ok": bool(cond), "detail": str(detail)})
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))


def pump(n=5):
    app = QtWidgets.QApplication.instance()
    for _ in range(n):
        app.processEvents()
    cmds.refresh(force=True)


def snap(name):
    """The viewport as it is (read back, not a playblast: a playblast empties the undo queue in a
    scripted session, and this test's Ctrl+Z checks come after its pictures)."""
    import maya.OpenMaya as om1
    import maya.OpenMayaUI as omui1
    path = os.path.join(OUT, name)
    cmds.refresh(force=True)
    img = om1.MImage()
    omui1.M3dView.active3dView().readColorBuffer(img, True)
    img.writeToFile(path, "png")
    return path


def look(at, eye):
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        cmds.setAttr("persp.translate", *eye)
        cmds.viewLookAt("persp", position=at)
    finally:
        cmds.undoInfo(stateWithoutFlush=True)
    pump()


def quiet(fn):
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        return fn()
    finally:
        cmds.select(clear=True)
        cmds.undoInfo(stateWithoutFlush=True)


def box(name, size, at, parent=None, div=3.0):
    node = cmds.polyCube(w=size[0], h=size[1], d=size[2], sx=max(1, int(size[0] / div)),
                         sy=max(1, int(size[1] / div)), sz=max(1, int(size[2] / div)), name=name,
                         constructionHistory=False)[0]
    cmds.move(at[0], at[1], at[2], node)
    if parent:
        node = cmds.parent(node, parent)[0]
    return cmds.ls(node, long=True)[0]


_SG = {}


def shade(nodes, name, rgb):
    def go():
        if name not in _SG:
            m = cmds.shadingNode("lambert", asShader=True, name=name)
            cmds.setAttr(m + ".color", *rgb, type="double3")
            sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name + "SG")
            cmds.connectAttr(m + ".outColor", sg + ".surfaceShader")
            _SG[name] = sg
        cmds.sets(nodes, e=True, forceElement=_SG[name])
    quiet(go)


COLOURS = {"moss": ("testMoss", (0.12, 0.24, 0.05)), "strands": ("testStrand", (0.20, 0.30, 0.07)),
           "capsules": ("testSpore", (0.35, 0.15, 0.06)), "litter": ("testLitter", (0.50, 0.28, 0.10))}


def shade_parts(ns, root):
    for key, node in ns["sc_parts"](root).items():
        part = key.split("/")[1]
        if part in COLOURS:
            shade(node, *COLOURS[part])


def yard():
    grp = cmds.group(empty=True, name="yard_GRP")
    nodes = [box("floor", (40, 1, 30), (0, -0.5, 0), grp, div=100.0),
             box("wall", (40, 15, 1), (0, 7.5, -13.5), grp, div=100.0),
             box("beam", (24, 1.2, 1.2), (0, 0.6, 4.0), grp, div=100.0)]
    return cmds.ls(grp, long=True)[0], nodes


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
    window.resize(440, 1150)
    panel = [p for p in window.panels() if p.TOOL_NAME == "Scatter"][0]
    names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    window.tabs.setCurrentIndex(names.index("Modeling"))
    page = window.pages[names.index("Modeling")]
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Scatter"][0].click()
    pump(20)
    view = cmds.getPanel(type="modelPanel")
    persp = [p for p in view if cmds.modelPanel(p, q=True, camera=True) == "persp"][0]
    cmds.setFocus(persp)
    cmds.modelEditor(persp, e=True, displayAppearance="smoothShaded", grid=False, headsUpDisplay=False,
                     cameras=False, wireframeOnShaded=False, twoSidedLighting=True)
    cmds.setAttr("persp.focalLength", 40)

    grp, nodes = quiet(yard)
    floor, wall = nodes[0], nodes[1]
    shade(nodes, "testWood", (0.42, 0.36, 0.28))
    cmds.select(grp)
    panel._sync_from_selection()
    panel.start_type.setCurrentIndex(panel.start_type.findText("Moss"))
    panel._show_layer()
    panel.f["Moss"]["coverage"].setValue(0.5)
    panel.f["Moss"]["detail"].setValue("Normal")
    panel.new_btn.click()
    pump()
    root = ns["sc_groups"]()[0]
    moss = ns["sc_data"](root)["layers"][0]["id"]
    shade_parts(ns, root)
    VIEW = ((0, 3, -2), (0, 32, 44))
    look(*VIEW)
    cmds.select(clear=True)
    snap("00_before.png")

    def moss_pts(x0, x1, z0, z1, y1=1.5):
        node = ns["sc_parts"](root).get(moss + "/moss")
        if not node or not cmds.getAttr(node + ".visibility"):
            return 0
        fn = ns["om"].MFnMesh(ns["get_dag_path"](ns["_log_shape"](node)))
        return sum(1 for p in fn.getPoints(ns["om"].MSpace.kWorld)
                   if x0 < p.x < x1 and z0 < p.z < z1 and p.y < y1)

    band0 = moss_pts(-3.0, 3.0, -11.0, 14.0)
    rest0 = moss_pts(10.0, 20.0, -11.0, 14.0)

    def to_screen(p):
        r = ns["omui"].M3dView.active3dView().worldToView(ns["om"].MPoint(p[0], p[1], p[2]))
        return r[0], r[1]

    def stroke(pts, mod="none"):
        xs = [to_screen(p) for p in pts]
        panel.painter.press_at(xs[0][0], xs[0][1], mod)
        for x, y in xs[1:]:
            panel.painter.drag_at(x, y)
        panel.painter.release()
        pump()

    # --- open the brush
    panel.layer_list.setCurrentRow(0)
    panel.paint_btn.click()
    pump()
    check("Paint Influence opens the brush on the layer being edited",
          panel.painter.is_active() and cmds.currentCtx() == ns["SC_PAINT_CTX"] and panel.painter.lid == moss and
          panel.paint_btn.text() == "Stop Painting" and panel.next_banner.tag.text() == "PAINTING",
          panel.next_banner.text.text())

    # --- Remove a band across the floor, opacity 1
    panel.paint_mode.setValue("Remove")
    panel.paint_opacity.setValue(1.0)
    panel.paint_radius.setValue(0.7)
    t0 = time.time()
    stroke([(0.0, 0.0, z) for z in range(-11, 15)])
    dt = time.time() - t0
    layer = ns["sc_layer"](ns["sc_data"](root), moss)
    band1 = moss_pts(-3.0, 3.0, -11.0, 14.0)
    rest1 = moss_pts(10.0, 20.0, -11.0, 14.0)
    check("a Remove stroke paints the layer out along it (and it grows again at once)",
          bool(layer.get("paint")) and band1 < 0.15 * band0 and abs(rest1 - rest0) <= 0.1 * rest0,
          "band %d -> %d points, elsewhere %d -> %d, %.2fs, %d dabs" % (band0, band1, rest0, rest1, dt,
                                                                       panel.painter.dabs))
    # (undoInfo -undoName answers "" in a scripted GUI session: go by the paint and the moss. The redo
    # comes before the events are pumped: in a scripted session something at idle after an undo empties
    # the redo list)
    cmds.undo()
    panel._after_undo()  # a scripted undo sends no Undo event
    undone_n = moss_pts(-3.0, 3.0, -11.0, 14.0)
    undone = not ns["sc_layer"](ns["sc_data"](root), moss).get("paint") and undone_n > 0.8 * band0
    cmds.redo()
    panel._after_undo()  # a scripted redo sends no Redo event
    pump(5)
    check("the stroke is one Ctrl+Z (it grows back), Ctrl+Y paints it out again",
          undone and moss_pts(-3.0, 3.0, -11.0, 14.0) == band1, "band %d -> %d -> %d points" % (
              band1, undone_n, moss_pts(-3.0, 3.0, -11.0, 14.0)))
    show = panel.painter.show
    check("the overlay shows the painted cells", show and cmds.objExists(show) and
          cmds.polyEvaluate(show, face=True) > 50 and cmds.getAttr(show + ".visibility"),
          cmds.polyEvaluate(show, face=True) if show and cmds.objExists(show) else "none")
    check("the overlay isn't saved and can't be picked", show and
          not ns["om"].MFnDependencyNode(ns["get_dag_path"](show).node()).canBeWritten() and
          cmds.getAttr(show + ".overrideDisplayType") == 2)
    check("the panel says what's painted", "Painted:" in panel.paint_label.text() and
          "(painted)" in panel.layer_list.item(0).text(), panel.paint_label.text())
    snap("01_removed_band_overlay.png")

    # --- 10% strokes on the wall build up
    panel.paint_mode.setValue("Add")
    panel.paint_opacity.setValue(0.1)
    panel.paint_radius.setValue(0.5)
    wall_pts = [(x, 6.0, -13.0) for x in range(-16, -3)]

    def wall_moss():
        return moss_pts(-18.0, -2.0, -13.2, -12.0, y1=14.0) - moss_pts(-18.0, -2.0, -13.2, -12.0, y1=1.5)

    w0 = wall_moss()
    stroke(wall_pts)
    vals = [ns["_MiPaint"](ns["sc_layer"](ns["sc_data"](root), moss)["paint"]).at((-10.0, 6.0, -13.0))]
    w1 = wall_moss()
    for _ in range(7):
        stroke(wall_pts)
    vals.append(ns["_MiPaint"](ns["sc_layer"](ns["sc_data"](root), moss)["paint"]).at((-10.0, 6.0, -13.0)))
    w8 = wall_moss()
    check("10% strokes: the first nudges, eight build it up on the wall", 0.05 < vals[0] < 0.2 and vals[1] > 0.45 and
          w8 > w1 >= w0 and w8 > w0 + 20, "influence %.2f -> %.2f, wall moss %d -> %d -> %d points" % (
              vals[0], vals[1], w0, w1, w8))
    snap("02_wall_built_up_overlay.png")
    cmds.undo()
    panel._after_undo()  # a scripted undo sends no Undo event
    pump(10)
    v7 = ns["_MiPaint"](ns["sc_layer"](ns["sc_data"](root), moss)["paint"]).at((-10.0, 6.0, -13.0))
    check("Ctrl+Z takes back one stroke (and regrows)", vals[0] < v7 < vals[1] - 0.03 and
          wall_moss() <= w8, "%.2f -> %.2f" % (vals[1], v7))
    cmds.redo()
    panel._after_undo()  # a scripted redo sends no Redo event
    pump(5)

    # Ctrl inverts
    stroke([(-10.0, 6.0, -13.0)], mod="ctrl")
    v_ctrl = ns["_MiPaint"](ns["sc_layer"](ns["sc_data"](root), moss)["paint"]).at((-10.0, 6.0, -13.0))
    check("Ctrl while painting takes it away instead", v_ctrl < vals[1] - 0.05, "%.2f -> %.2f" % (vals[1], v_ctrl))

    # --- pause: strokes wait for Play
    panel.pause_btn.click()
    pump()
    before = moss_pts(8.0, 20.0, -11.0, 14.0)
    band_before = moss_pts(12.0, 16.0, -11.0, 14.0)
    panel.paint_mode.setValue("Remove")
    panel.paint_opacity.setValue(1.0)
    stroke([(14.0, 0.0, z) for z in range(-11, 15)])
    pend = ns["sc_pending"](root)
    check("paused: the stroke is saved, the layer marked changed, nothing grows",
          pend and moss in pend[0] and moss_pts(8.0, 20.0, -11.0, 14.0) == before and
          "(changed)" in panel.layer_list.item(0).text(), panel.layer_list.item(0).text())
    panel.pause_btn.click()
    pump()
    band_after = moss_pts(12.0, 16.0, -11.0, 14.0)
    check("Play grows it", band_before > 50 and band_after < 0.2 * band_before,
          "%d -> %d points by x = 1.4 m" % (band_before, band_after))
    snap("03_after_overlay.png")
    window.grab().save(os.path.join(OUT, "04_panel_painting.png"))

    # --- Stop Painting: the overlay goes
    panel.paint_btn.click()
    pump()
    check("Stop Painting: the tool and its overlay go", not panel.painter.is_active() and
          not cmds.ls("scatterPaintShow*") and not cmds.ls("scatterPaintBrush*") and
          panel.paint_btn.text() == "Paint Influence")
    shade_parts(ns, root)
    look(*VIEW)
    snap("05_after.png")

    # --- leaves: Flood Remove, then one stroke: only along it
    panel.add_layer("Leaves")
    pump()
    leaves = panel._lid
    panel.f["Leaves"]["leaves"].setValue(25.0)
    panel._queue("Leaves", "leaves")
    panel._apply_pending()
    pump()
    panel.paint_mode.setValue("Remove")
    panel.paint_opacity.setValue(1.0)
    panel.flood_paint()
    pump()
    check("Flood Remove at 1: no leaves left", not ns["sc_parts"](root).get(leaves + "/litter") or
          not cmds.getAttr(ns["sc_parts"](root)[leaves + "/litter"] + ".visibility"), panel.status.text())
    panel.paint_btn.click()
    pump()
    panel.paint_mode.setValue("Add")
    panel.paint_radius.setValue(0.6)
    stroke([(x, 0.0, 10.0 + 0.15 * x) for x in range(-18, 19)])
    node = ns["sc_parts"](root).get(leaves + "/litter")
    fn = ns["om"].MFnMesh(ns["get_dag_path"](ns["_log_shape"](node)))
    pts = fn.getPoints(ns["om"].MSpace.kWorld)
    near = sum(1 for p in pts if abs(p.z - (10.0 + 0.15 * p.x)) < 8.0)
    check("... then a stroke puts leaves only along it", len(pts) > 100 and near >= 0.97 * len(pts),
          "%d of %d leaf points by the stroke" % (near, len(pts)))
    snap("06_leaves_stroke_overlay.png")
    panel.painter.deactivate()
    pump()
    shade_parts(ns, root)
    look(*VIEW)
    snap("07_leaves_stroke.png")
    panel.flood_paint(clear=True)
    pump()
    check("Clear: leaves everywhere again, the layer unpainted",
          not ns["sc_layer"](ns["sc_data"](root), leaves).get("paint") and
          "Nothing painted" in panel.paint_label.text(), panel.paint_label.text())
    window.grab().save(os.path.join(OUT, "08_panel.png"))


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


if __name__ == "gui_scatter_paint":
    cmds.evalDeferred(run, lowestPriority=True)
