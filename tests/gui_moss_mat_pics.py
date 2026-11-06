"""Pictures of the moss Mat style next to the Carpet on a rock (_GES), a
block and a floor: the cage (wireframe), its smooth preview, and the mat
subdivided twice and displaced in Python (a stand-in for Arnold: world noise
x the edge mask) to show its rolled edge staying down: run inside an
interactive Maya.

UNLOK_TEST_OUT picks the folder (default tests/_out/moss_mat_pics).

    maya.exe -script tests/run_gui_moss_mat_pics.mel
"""

import math
import os
import traceback

import maya.cmds as cmds
import maya.api.OpenMaya as om

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "moss_mat_pics")


def pump(n=5):
    app = QtWidgets.QApplication.instance()
    for _ in range(n):
        app.processEvents()
    cmds.refresh(force=True)


def snap(name):
    import maya.OpenMaya as om1
    import maya.OpenMayaUI as omui1
    cmds.refresh(force=True)
    img = om1.MImage()
    omui1.M3dView.active3dView().readColorBuffer(img, True)
    img.writeToFile(os.path.join(OUT, name), "png")


def look(at, eye):
    cmds.setAttr("persp.translate", *eye)
    cmds.viewLookAt("persp", position=at)
    pump()


_SG = {}


def shade(nodes, name, rgb):
    if name not in _SG:
        m = cmds.shadingNode("lambert", asShader=True, name=name)
        cmds.setAttr(m + ".color", *rgb, type="double3")
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name + "SG")
        cmds.connectAttr(m + ".outColor", sg + ".surfaceShader")
        _SG[name] = sg
    cmds.sets(nodes, e=True, forceElement=_SG[name])


def scene(x):
    r = cmds.polySphere(r=3.0, sx=12, sy=8, ch=False, name="rockGrey_C_pic%04d_GES" % int(x))[0]
    cmds.scale(1.0, 0.7, 0.85, r)
    cmds.move(x, 1.6, 0, r)
    cmds.makeIdentity(r, apply=True)
    cmds.displaySmoothness(r, polygonObject=3)
    b = cmds.polyCube(w=5.0, h=3.0, d=5.0, ch=False, name="woodPlank_C_pic%04d_GEP" % int(x))[0]
    cmds.move(x + 7, 1.5, -2, b)
    cmds.makeIdentity(b, apply=True)
    f = cmds.polyPlane(w=26, h=20, sx=4, sy=4, ch=False, name="groundSoil_C_pic%04d_GEP" % int(x))[0]
    cmds.move(x + 3, 0, 0, f)
    cmds.makeIdentity(f, apply=True)
    nodes = [cmds.ls(n, long=True)[0] for n in (r, b, f)]
    shade(nodes, "pic_ground", (0.45, 0.43, 0.40))
    return nodes


def displaced(ns, node, height):
    """The mat subdivided twice, each point pushed out along its normal by
    world noise x the mossData B edge mask (as Moss Look's displacement)."""
    dup = cmds.duplicate(node, name=node.split("|")[-1] + "_disp")[0]
    cmds.polySmooth(dup, divisions=2, keepBorder=True, constructionHistory=False)
    sel = om.MSelectionList()
    sel.add(dup)
    fn = om.MFnMesh(sel.getDagPath(0))
    pts = fn.getPoints(om.MSpace.kWorld)
    nrm = fn.getVertexNormals(False, om.MSpace.kWorld)
    try:
        cols = fn.getVertexColors("mossData")
    except RuntimeError:
        cols = None
    m = ns["scene_m_per_unit"]()
    out = om.MPointArray()
    for i, p in enumerate(pts):
        mask = 1.0
        if cols is not None:
            b = cols[i].b
            mask = max(0.0, min(1.0, b / 0.25))
            mask = mask * mask * (3.0 - 2.0 * mask)
        s1 = m / 0.025
        s2 = m / 0.005
        n1 = 0.5 + 0.5 * ns["_moss_noise3"](p.x * s1, p.y * s1, p.z * s1, 5)
        n2 = 0.5 + 0.5 * ns["_moss_noise3"](p.x * s2, p.y * s2, p.z * s2, 9)
        d = height * mask * (0.65 * n1 + 0.35 * n2)
        out.append(om.MPoint(p.x + nrm[i].x * d, p.y + nrm[i].y * d, p.z + nrm[i].z * d))
    fn.setPoints(out, om.MSpace.kWorld)
    return cmds.ls(dup, long=True)[0]


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    ns = {"__name__": "unlok_pics", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    cmds.file(new=True, force=True)
    pump(10)
    view = cmds.getPanel(type="modelPanel")
    persp = [p for p in view if cmds.modelPanel(p, q=True, camera=True) == "persp"][0]
    cmds.setFocus(persp)
    cmds.modelEditor(persp, e=True, displayAppearance="smoothShaded", grid=False, headsUpDisplay=False,
                     cameras=False, wireframeOnShaded=False, twoSidedLighting=True, shadows=False)
    cmds.setAttr("persp.focalLength", 40)
    base = {"coverage": 0.6, "seed": 2, "detail": "Normal", "strands": 0.0, "capsules": 0.0}
    looks = (("carpet", dict(base, style="Carpet")), ("mat_simple", dict(base, style="Mat", bumps=0.0, growths=0.0)),
             ("mat", dict(base, style="Mat")),
             ("mat_lumpy", dict(base, style="Mat", bumps=0.85, growths=0.7, lumps=0.7, thickness=0.03)))
    beds = {}
    for k, (name, s) in enumerate(looks):
        x = k * 60.0
        nodes = scene(x)
        root = ns["create_scatter_group"](nodes, "Moss", s)["root"]
        for key, node in ns["sc_parts"](root).items():
            if key.endswith("/moss"):
                beds[name] = node
                shade(node, "pic_moss", (0.30, 0.45, 0.12))
            else:
                cmds.setAttr(node + ".visibility", False)
        for key, node in ns["sc_shoots"](root).items():
            cmds.setAttr(node + ".visibility", False)
    cmds.select(clear=True)
    for name in [n for n, _ in looks]:
        x = [n for n, _ in looks].index(name) * 60.0
        cmds.modelEditor(persp, e=True, wireframeOnShaded=True)
        look((x + 3, 0.5, 0.0), (x + 9.0, 14.0, 16.0))
        snap("%s_wire.png" % name)
        cmds.modelEditor(persp, e=True, wireframeOnShaded=False)
        if name != "carpet":
            cmds.displaySmoothness(beds[name], polygonObject=3)
        look((x + 3, 0.5, 0.0), (x + 9.0, 14.0, 16.0))
        snap("%s.png" % name)
        look((x + 2.5, 0.6, 1.0), (x + 6.0, 2.0, 7.0))
        snap("%s_low.png" % name)
    cmds.modelEditor(persp, e=True, wireframeOnShaded=True)
    for name in ("mat", "mat_lumpy"):
        x = [n for n, _ in looks].index(name) * 60.0
        cmds.displaySmoothness(beds[name], polygonObject=1)
        look((x + 2.5, 0.6, 1.0), (x + 6.0, 2.0, 7.0))
        snap("%s_low_wire.png" % name)
    cmds.modelEditor(persp, e=True, wireframeOnShaded=False)
    # displaced in place of the mat (2 cm, twice Displacement: the edge must still stay down)
    for name in ("mat", "mat_lumpy"):
        x = [n for n, _ in looks].index(name) * 60.0
        disp = displaced(ns, beds[name], 0.02 / ns["scene_m_per_unit"]())
        shade(disp, "pic_moss", (0.30, 0.45, 0.12))
        cmds.setAttr(beds[name] + ".visibility", False)
        look((x + 3, 0.5, 0.0), (x + 9.0, 14.0, 16.0))
        snap("%s_displaced.png" % name)
        look((x + 2.5, 0.6, 1.0), (x + 6.0, 2.0, 7.0))
        snap("%s_displaced_low.png" % name)
        look((x + 6.5, 0.2, 4.2), (x + 8.5, 0.9, 7.5))
        snap("%s_displaced_edge.png" % name)


try:
    main()
except Exception:
    traceback.print_exc()
if os.environ.get("UNLOK_TEST_QUIT") == "1":
    cmds.quit(force=True)
