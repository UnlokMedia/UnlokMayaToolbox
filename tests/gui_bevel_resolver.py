"""GUI smoke test for the Bevel Resolver: run inside an interactive Maya.

Opens the toolbox, drives the Bevel Resolver panel on bevelled meshes (a wall
with two windows and a box with a boss), checks the result and saves
before / after screenshots, wireframe and smooth-mesh preview, plus the panel.

Launch (Maya 2023+), with UNLOK_TEST_DIR set to this folder:

    maya.exe -script tests/run_gui_bevel_resolver.mel

Outputs go to $UNLOK_TEST_OUT (default: tests/_out/bevel_resolver).
"""

import json
import os
import traceback

import maya.cmds as cmds
import maya.api.OpenMaya as om

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "bevel_resolver")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append({"name": name, "ok": bool(cond), "detail": str(detail)})
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))


def pump(n=5):
    app = QtWidgets.QApplication.instance()
    for _ in range(n):
        app.processEvents()
    cmds.refresh(force=True)


def snap(name, width=1400, height=900):
    path = os.path.join(OUT, name)
    cmds.refresh(force=True)
    cmds.playblast(frame=[cmds.currentTime(q=True)], format="image", compression="png", completeFilename=path,
                   viewer=False, showOrnaments=False, percent=100, widthHeight=(width, height), offScreen=True)
    return path


def dag(node):
    sel = om.MSelectionList()
    sel.add(node)
    return sel.getDagPath(0)


def ngons(node):
    return sum(1 for c in om.MFnMesh(dag(node)).getVertices()[0] if c > 4)


def faces_where(node, pred):
    it = om.MItMeshPolygon(dag(node))
    out = []
    while not it.isDone():
        if pred(it.center()):
            out.append(it.index())
        it.next()
    return out


def edges_where(node, pred):
    it = om.MItMeshEdge(dag(node))
    out = []
    while not it.isDone():
        if pred(it.point(0), it.point(1)):
            out.append("%s.e[%d]" % (node, it.index()))
        it.next()
    return out


def build_wall():
    """Wall with two window recesses; only the windows' vertical edges are
    bevelled (Chamfer off), so the bevels end on the flat wall."""
    w = cmds.polyCube(w=6, h=4, d=0.4, sx=5, sy=3, sz=1, name="wall")[0]
    xs = (-1.2, 1.2)
    fs = faces_where(w, lambda c: c.z > 0.19 and abs(c.y) < 0.1 and any(abs(c.x - x) < 0.1 for x in xs))
    cmds.polyExtrudeFacet(["%s.f[%d]" % (w, f) for f in fs], ltz=-0.15, keepFacesTogether=False)
    rim = edges_where(w, lambda a, b: abs(a.z - 0.2) < 1e-4 and abs(b.z - 0.2) < 1e-4 and abs(a.x - b.x) < 1e-3
                      and abs(a.y) < 0.7 and abs(b.y) < 0.7 and any(abs(a.x - x) < 0.61 for x in xs))
    cmds.polyBevel3(rim, segments=2, chamfer=False, offset=0.08, offsetAsFraction=False)
    return cmds.ls(w, long=True)[0]


def build_boss():
    c = cmds.polyCube(w=4, h=1, d=4, sx=3, sz=3, name="boss")[0]
    top = faces_where(c, lambda p: abs(p.y - 0.5) < 1e-4 and abs(p.x) < 0.1 and abs(p.z) < 0.1)
    cmds.polyExtrudeFacet("%s.f[%d]" % (c, top[0]), ltz=0.6)
    cmds.polyBevel3(edges_where(c, lambda a, b: max(abs(a.x), abs(a.z), abs(b.x), abs(b.z)) < 0.7
                                and abs(a.y - b.y) > 0.3), segments=2, chamfer=False, offset=0.08,
                    offsetAsFraction=False)
    cmds.move(0, -2.0, 4.5, c)
    return cmds.ls(c, long=True)[0]


def set_view(meshes, smooth):
    for m in meshes:
        cmds.displaySmoothness(m, polygonObject=3 if smooth else 1)
    cmds.select(clear=True)


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    ns = {"__name__": "__main__", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    import __main__
    window = getattr(__main__, ns["REGISTRY_KEY"])["window"]
    panel = [p for p in window.panels() if p.TOOL_NAME == "Bevel Resolver"][0]
    names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    window.tabs.setCurrentIndex(names.index("Modeling"))
    page = window.pages[names.index("Modeling")]
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Bevel Resolver"][0].click()
    pump()
    check("Bevel Resolver panel is in the Modeling tab", panel.isVisible())

    cmds.file(new=True, force=True)
    wall, boss = build_wall(), build_boss()
    meshes = [wall, boss]
    before = {m: ngons(m) for m in meshes}
    check("test meshes have bevel n-gons", all(before.values()), str(before))
    view = cmds.getPanel(type="modelPanel")
    persp = [p for p in view if cmds.modelPanel(p, q=True, camera=True) == "persp"][0]
    cmds.setFocus(persp)
    cmds.modelEditor(persp, e=True, displayAppearance="smoothShaded", wireframeOnShaded=True, grid=False,
                     headsUpDisplay=False)
    cmds.setAttr("persp.translate", 4.5, 3.5, 11)
    cmds.viewLookAt("persp", position=(0, -0.6, 1.8))
    pump()
    set_view(meshes, smooth=False)
    snap("01_before_wire.png")
    set_view(meshes, smooth=True)
    snap("02_before_smooth.png")
    set_view(meshes, smooth=False)

    cmds.select(meshes)
    panel.find()
    pump()
    sel = cmds.ls(selection=True, flatten=True) or []
    check("Select N-gons selects the bevel n-gons", len(sel) == sum(before.values()) and ngons(wall) == before[wall],
          "%d selected | %s" % (len(sel), panel.status.text()))

    cmds.select(meshes)
    panel.resolve()
    pump()
    check("Resolve leaves no n-gons", all(ngons(m) == 0 for m in meshes), panel.status.text())
    check("status reports success", "Resolved" in panel.status.text(), panel.status.text())
    check("NEXT banner says it's done, steps ticked", panel.next_banner.tag.text() == "DONE"
          and panel.step_resolve.state == "done" and panel.step_check.state == "done",
          "%s: %s" % (panel.next_banner.tag.text(), panel.next_banner.text.text()))
    items = [panel.report_tree.topLevelItem(i).text(0) for i in range(panel.report_tree.topLevelItemCount())]
    check("report lists both meshes", len(items) == 2 and all("resolved" in t for t in items), str(items))
    # Before the screenshots: their display / selection changes are undo steps too.
    cmds.undo()
    pump()
    check("one Ctrl+Z restores both meshes", {m: ngons(m) for m in meshes} == before)
    cmds.redo()
    pump()
    check("redo", all(ngons(m) == 0 for m in meshes))
    set_view(meshes, smooth=False)
    snap("03_after_wire.png")
    set_view(meshes, smooth=True)
    snap("04_after_smooth.png")
    set_view(meshes, smooth=False)
    window.grab().save(os.path.join(OUT, "05_panel.png"))

    # --- something it can't resolve: listed, and clicking the row selects it
    cmds.file(new=True, force=True)
    cyl = cmds.ls(cmds.polyCylinder(sx=24, sy=1, sc=0, name="drum")[0], long=True)[0]
    panel.scope.setValue("All n-gons")
    cmds.select(cyl)
    panel.resolve()
    pump()
    top = panel.report_tree.topLevelItem(0)
    check("leftovers turn the banner into a CHECK", panel.next_banner.tag.text() == "CHECK"
          and panel.step_check.state == "current", panel.next_banner.text.text())
    check("unresolved faces get a report row", top is not None and top.childCount() == 1,
          top.child(0).text(0) if top and top.childCount() else panel.status.text())
    cmds.select(clear=True)
    if top is not None and top.childCount():
        top.child(0).setSelected(True)
        pump()
    sel = cmds.ls(selection=True, flatten=True) or []
    check("clicking a report row selects those faces", len(sel) == 2 and all(".f[" in s for s in sel), str(sel))
    window.grab().save(os.path.join(OUT, "06_panel_unresolved.png"))
    panel.scope.setValue("Bevel n-gons")

    # --- nothing selected: a warning, no exception
    cmds.select(clear=True)
    panel.resolve()
    check("no selection gives a warning", "Select" in panel.status.text(), panel.status.text())
    check("with nothing selected the banner asks for a selection", "Select" in panel.next_banner.text.text()
          and panel.step_select.state == "current", panel.next_banner.text.text())


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
