"""GUI test for Quad Fill: run inside an interactive Maya.

Opens the toolbox, drives the Quad Fill panel (a hole in a sphere, a
cylinder's open end, an uneven hole in a grid, an odd one): the preview
follows the selection and the sliders, Fill Hole fills the mesh itself, one
Ctrl+Z undoes it, and the preview goes when the panel is left. Saves before
/ preview / after pictures (Maya's own Fill Hole beside it for comparison)
and the panel.

Launch (Maya 2023+), with UNLOK_TEST_DIR set to this folder:

    maya.exe -script tests/run_gui_quad_fill.mel

Outputs go to $UNLOK_TEST_OUT (default: tests/_out/quad_fill).
"""

import json
import math
import os
import time
import traceback

import maya.cmds as cmds
import maya.api.OpenMaya as om

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "quad_fill")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append({"name": name, "ok": bool(cond), "detail": str(detail)})
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))


def pump(n=5):
    app = QtWidgets.QApplication.instance()
    for _ in range(n):
        app.processEvents()
    cmds.refresh(force=True)


def wait(seconds):
    """Let the panel's timers fire."""
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
    cmds.refresh(force=True)


def snap(name, width=1200, height=800):
    path = os.path.join(OUT, name)
    cmds.refresh(force=True)
    cmds.playblast(frame=[cmds.currentTime(q=True)], format="image", compression="png", completeFilename=path,
                   viewer=False, showOrnaments=False, percent=100, widthHeight=(width, height), offScreen=True)
    return path


def quiet(fn, *args, **kwargs):
    """Scene dressing out of the undo queue (the test's undos are for the tool)."""
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        return fn(*args, **kwargs)
    finally:
        cmds.undoInfo(stateWithoutFlush=True)


def look(at, eye):
    def go():
        cmds.setAttr("persp.translate", *eye)
        cmds.viewLookAt("persp", position=at)
    quiet(go)
    pump()


def shape_of(node):
    return cmds.listRelatives(node, shapes=True, fullPath=True, noIntermediate=True)[0]


def mfn(node):
    sel = om.MSelectionList()
    sel.add(shape_of(node))
    return om.MFnMesh(sel.getDagPath(0))


def delete_faces(node, test):
    fn = mfn(node)
    out = []
    for f in range(fn.numPolygons):
        vs = fn.getPolygonVertices(f)
        c = [sum(fn.getPoint(v)[k] for v in vs) / len(vs) for k in range(3)]
        if test(*c):
            out.append("%s.f[%d]" % (node, f))
    cmds.delete(out)


def border_edge(node, test=lambda x, y, z: True):
    fn = mfn(node)
    sel = om.MSelectionList()
    sel.add(shape_of(node))
    it = om.MItMeshEdge(sel.getDagPath(0))
    while not it.isDone():
        if it.onBoundary():
            a, b = fn.getEdgeVertices(it.index())
            pa, pb = fn.getPoint(a, om.MSpace.kWorld), fn.getPoint(b, om.MSpace.kWorld)
            if test((pa.x + pb.x) / 2, (pa.y + pb.y) / 2, (pa.z + pb.z) / 2):
                return "%s.e[%d]" % (node, it.index())
        it.next()
    raise RuntimeError("no border edge")


_SG = {}


def shade(node, name, rgb):
    def go():
        if name not in _SG:
            m = cmds.shadingNode("blinn", asShader=True, name=name)
            cmds.setAttr(m + ".color", *rgb, type="double3")
            cmds.setAttr(m + ".specularColor", 0.25, 0.25, 0.25, type="double3")
            sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name + "SG")
            cmds.connectAttr(m + ".outColor", sg + ".surfaceShader")
            _SG[name] = sg
        cmds.sets(node, e=True, forceElement=_SG[name])
    quiet(go)


def maya_fill(node):
    """Maya's own Fill Hole on a copy, for the comparison pictures."""
    cmds.polyCloseBorder(node, constructionHistory=False)


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
    window.resize(420, 900)
    panel = [p for p in window.panels() if p.TOOL_NAME == "Quad Fill"][0]
    names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    window.tabs.setCurrentIndex(names.index("Modeling"))
    page = window.pages[names.index("Modeling")]
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Quad Fill"][0].click()
    pump(20)
    check("Quad Fill panel is in the Modeling tab", panel.isVisible())
    check("NEXT asks for a border edge", "border" in panel.next_banner.text.text(), panel.next_banner.text.text())

    view = cmds.getPanel(type="modelPanel")
    persp = [p for p in view if cmds.modelPanel(p, q=True, camera=True) == "persp"][0]
    cmds.setFocus(persp)
    cmds.modelEditor(persp, e=True, displayAppearance="smoothShaded", grid=False, headsUpDisplay=False,
                     cameras=False, wireframeOnShaded=True, twoSidedLighting=False, selectionHiliteDisplay=False)
    cmds.setAttr("persp.focalLength", 45)
    try:
        cmds.setAttr("hardwareRenderingGlobals.multiSampleEnable", 1)
    except Exception:
        pass

    # ---------------------------------------------------- undo / redo first: a playblast
    # empties the undo queue in a scripted session
    tile = cmds.polyPlane(w=6, h=6, sx=6, sy=6, name="undoQuadFill", constructionHistory=False)[0]
    cmds.move(0, -40, 0, tile)
    cmds.delete(tile + ".f[14:15]", tile + ".f[20:21]")
    nf = cmds.polyEvaluate(tile, face=True)
    cmds.select(border_edge(tile, lambda x, y, z: abs(x) < 1.5 and abs(z) < 1.5))
    panel._sync_from_selection()
    panel.fill_btn.click()
    pump()
    filled = cmds.polyEvaluate(tile, face=True)
    cmds.undo()  # (undoInfo -undoName answers "" in a scripted GUI session, so go by the faces)
    check("one Ctrl+Z undoes the fill", filled == nf + 4 and cmds.polyEvaluate(tile, face=True) == nf,
          "%d -> %d -> %d faces" % (nf, filled, cmds.polyEvaluate(tile, face=True)))
    cmds.redo()
    check("redo fills it again", cmds.polyEvaluate(tile, face=True) == nf + 4)
    quiet(cmds.delete, tile)

    # ---------------------------------------------------- a hole in a sphere
    ball =cmds.polySphere(r=10, sx=24, sy=24, name="ballQuadFill", constructionHistory=False)[0]
    delete_faces(ball, lambda x, y, z: z > 0 and abs(math.atan2(x, z)) < math.radians(30) and abs(y) < 5)
    ref = cmds.duplicate(ball, name="ballMayaFill")[0]
    cmds.move(-24, 0, 0, ref)
    shade(ball, "testClay", (0.55, 0.47, 0.40))
    shade(ref, "testClay", (0.55, 0.47, 0.40))
    look((-12, 0, 0), (-12, 6, 52))
    snap("01_sphere_before.png")
    uuid = cmds.ls(ball, uuid=True)[0]
    cmds.select(border_edge(ball, lambda x, y, z: x > -12))
    panel._sync_from_selection()  # a scripted selection change sends no SelectionChanged event
    pump()
    node = panel.preview.node()
    check("selecting a border edge shows the preview", node and cmds.objExists(node),
          panel.hole_label.text())
    check("NEXT says Fill Hole", "Fill Hole" in panel.next_banner.text.text(), panel.next_banner.text.text())
    window.grab().save(os.path.join(OUT, "00_panel.png"))
    snap("02_sphere_preview.png")
    topo = panel.preview.topo
    panel.f["offset"].setValue(2)
    panel._replan()
    check("Offset re-lays the preview", panel.preview.topo != topo and panel.preview.node() == node)
    panel.f["offset"].setValue(0)
    panel._replan()
    nf = cmds.polyEvaluate(ball, face=True)
    panel.fill_btn.click()
    pump()
    check("Fill Hole fills the mesh itself", cmds.polyEvaluate(ball, face=True) > nf
          and cmds.ls(ball, uuid=True)[0] == uuid and not cmds.objExists(node), panel.status.text())
    check("the preview is gone after the fill", panel.preview.node() is None)
    quiet(maya_fill, ref)
    quiet(cmds.select, clear=True)
    pump()
    snap("03_sphere_after_maya_fill_left_quad_fill_right.png")
    look((0, 0, 0), (26, 4, 26))
    snap("04_sphere_after_side.png")

    # ---------------------------------------------------- an open tube end
    tube = cmds.polyCylinder(r=5, h=12, sx=20, sy=6, sc=0, name="tubeQuadFill", constructionHistory=False)[0]
    cmds.move(40, 0, 0, tube)
    delete_faces(tube, lambda x, y, z: y > 5.9)
    ref = cmds.duplicate(tube, name="tubeMayaFill")[0]
    cmds.move(28, 0, 0, ref)
    shade(tube, "testMetal", (0.45, 0.5, 0.55))
    shade(ref, "testMetal", (0.45, 0.5, 0.55))
    look((34, 3, 0), (34, 26, 30))
    snap("05_tube_before.png")
    cmds.select(border_edge(tube, lambda x, y, z: x > 34 and y > 5))
    panel._sync_from_selection()
    pump()
    snap("06_tube_preview.png")
    panel.fill_btn.click()
    quiet(maya_fill, ref)
    quiet(cmds.select, clear=True)
    pump()
    snap("07_tube_after_maya_fill_left_quad_fill_right.png")
    ys = [p.y for p in mfn(tube).getPoints(om.MSpace.kWorld)]
    check("the tube end closes flat", max(ys) < 6.01, "top %.3f" % max(ys))

    # ---------------------------------------------------- an uneven hole in a grid
    grid = cmds.polyPlane(w=20, h=20, sx=10, sy=10, name="gridQuadFill", constructionHistory=False)[0]
    cmds.move(0, 0, 60, grid)
    cells = [(i, j) for i in range(3, 7) for j in range(3, 6)] + [(7, 4), (5, 6), (6, 6), (2, 3)]
    cmds.delete(["%s.f[%d]" % (grid, j * 10 + i) for i, j in cells])
    ref = cmds.duplicate(grid, name="gridMayaFill")[0]
    cmds.move(-22, 0, 60, ref)
    shade(grid, "testTile", (0.6, 0.6, 0.55))
    shade(ref, "testTile", (0.6, 0.6, 0.55))
    look((-11, 0, 60), (-11, 38, 76))
    snap("08_grid_before.png")
    cmds.select(border_edge(grid, lambda x, y, z: abs(x) < 6 and abs(z - 60) < 6))
    panel._sync_from_selection()
    pump()
    snap("09_grid_preview.png")
    panel.fill_btn.click()
    quiet(maya_fill, border_edge(ref, lambda x, y, z: abs(x + 22) < 6 and abs(z - 60) < 6))
    quiet(cmds.select, clear=True)
    pump()
    snap("10_grid_after_maya_fill_left_quad_fill_right.png")
    sizes = [len(mfn(grid).getPolygonVertices(f)) for f in range(mfn(grid).numPolygons)]
    check("the uneven hole is all quads", set(sizes) == {4}, str(sorted(set(sizes))))

    # ---------------------------------------------------- Straight grid: Smooth (left) vs Straight (right)
    def bent_hole(name, dx):
        node = cmds.polyPlane(w=10, h=10, sx=10, sy=10, name=name, constructionHistory=False)[0]
        cmds.delete(["%s.f[%d]" % (node, j * 10 + i) for i in range(3, 7) for j in range(2, 8)])
        fn = mfn(node)
        for v in range(fn.numVertices):
            pt = fn.getPoint(v)
            x, z = pt.x, pt.z
            if 1.5 < abs(x) < 2.5 and abs(z) < 3.5 or 2.5 < abs(z) < 3.5 and abs(x) < 2.5:
                cmds.move(0.35 * math.sin(1.7 * z + x), 0, 0.3 * math.cos(1.3 * x - z), "%s.vtx[%d]" % (node, v),
                          relative=True)
        cmds.move(dx, 0, 90, node)
        shade(node, "testTile", (0.6, 0.6, 0.55))
        return node

    soft, hard = bent_hole("smoothGrid", -5.5), bent_hole("straightGrid", 5.5)
    panel.f["rings"].setValue("0")
    panel.f["smooth"].setValue(0.0)
    panel.f["follow"].setValue(0.0)
    cmds.select(border_edge(soft, lambda x, y, z: abs(x + 5.5) < 2.7 and abs(z - 90) < 3.7))
    panel._sync_from_selection()
    panel.fill_btn.click()
    panel.f["grid"].setValue("Straight")
    panel._replan()  # the edit timer's job
    check("Straight greys out Smooth", not panel.f["smooth"].isEnabled())
    cmds.select(border_edge(hard, lambda x, y, z: abs(x - 5.5) < 2.7 and abs(z - 90) < 3.7))
    panel._sync_from_selection()
    look((0, 0, 90), (0, 30, 91))
    snap("11_straight_preview.png")
    panel.fill_btn.click()
    quiet(cmds.select, clear=True)
    pump()
    snap("12_grid_smooth_left_straight_right.png")
    panel.reset_settings()

    # ---------------------------------------------------- odd hole: the triangle warning
    odd = cmds.polyPlane(w=8, h=8, sx=8, sy=8, name="oddHole", constructionHistory=False)[0]
    cmds.delete(["%s.f[%d]" % (odd, j * 8 + i) for i in range(2, 5) for j in range(3, 5)])
    cmds.polySubdivideEdge(border_edge(odd, lambda x, y, z: abs(x - 0.5) < 0.1 and 0 < z < 2), divisions=1,
                           constructionHistory=False)
    cmds.move(0, 0, 120, odd)
    cmds.select(border_edge(odd, lambda x, y, z: abs(x) < 3 and abs(z - 120) < 2))
    panel._sync_from_selection()
    pump()
    check("an odd hole warns about the triangle and how to avoid it",
          not panel.tri_label.isHidden() and "split one border edge" in panel.tri_label.text()
          and panel.step_fill.tone == "warn", panel.tri_label.text())
    check("NEXT mentions the triangle", "triangle" in panel.next_banner.text.text(), panel.next_banner.text.text())
    window.grab().save(os.path.join(OUT, "13_panel_triangle_warning.png"))
    panel.fill_btn.click()
    pump()
    check("after the fill the status says how to get all quads", "Ctrl+Z" in panel.status.text()
          and "split one border edge" in panel.status.text(), panel.status.text())
    check("the warning goes once the hole is filled", panel.tri_label.isHidden())

    # ---------------------------------------------------- leaving the panel hides the preview
    cmds.select(border_edge(grid, lambda x, y, z: abs(x) > 9))  # the plane's own rim: still a "hole"
    panel._sync_from_selection()
    pump()
    had = panel.preview.node()
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Log Noise"][0].click()
    pump()
    check("switching tools removes the preview", had and not cmds.objExists(had) and panel.preview.node() is None)
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Quad Fill"][0].click()
    wait(0.3)
    check("coming back brings it back", panel.preview.node() is not None)
    window.close()
    pump()
    check("closing the toolbox removes the preview",
          not [x for x in cmds.ls(type="transform") if cmds.attributeQuery("unlokQuadFillPreview", node=x,
                                                                           exists=True)])


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
