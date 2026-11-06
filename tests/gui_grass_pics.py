"""Pictures of dry grass bunches: flat (Pile height 0, how they were), a new
Grass layer (Pile height 0.6) and the Loose piles preset, side by side on
the same floor with a wall and a step: run inside an interactive Maya.

UNLOK_TEST_OUT picks the folder (default tests/_out/grass_pics).

    maya.exe -script tests/run_gui_grass_pics.mel
"""

import os
import traceback

import maya.cmds as cmds

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "grass_pics")


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


def box(name, size, at, div=2.0):
    node = cmds.polyCube(w=size[0], h=size[1], d=size[2], sx=max(1, int(size[0] / div)), sy=max(1, int(size[1] / div)),
                         sz=max(1, int(size[2] / div)), name=name, constructionHistory=False)[0]
    cmds.move(at[0], at[1], at[2], node)
    return cmds.ls(node, long=True)[0]


_SG = {}


def shade(nodes, name, rgb):
    if name not in _SG:
        m = cmds.shadingNode("lambert", asShader=True, name=name)
        cmds.setAttr(m + ".color", *rgb, type="double3")
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name + "SG")
        cmds.connectAttr(m + ".outColor", sg + ".surfaceShader")
        _SG[name] = sg
    cmds.sets(nodes, e=True, forceElement=_SG[name])


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
    cmds.setAttr("persp.focalLength", 45)
    looks = (("flat", {"grass_pile": 0.0}),  # how bunches were
             ("pile", {}),  # a new Grass layer: Pile height 0.6
             ("loose", ns["sc_preset"]("Grass", "Loose piles")))
    for k, (name, s) in enumerate(looks):
        x = k * 100.0
        flr = box("floor_" + name, (24, 1, 24), (x, -0.5, 0), div=4.0)
        wall = box("wall_" + name, (24, 8, 1), (x, 4, -12.5), div=4.0)
        step = box("step_" + name, (6, 1.5, 4), (x + 7, 0.75, -8), div=1.0)
        shade([flr, wall, step], "pic_ground", (0.42, 0.42, 0.42))
        s = dict(s)
        s.update({"grass": 4.0, "coverage": 0.85, "seed": 3})
        root = ns["create_scatter_group"]([flr, wall, step], "Grass", s)["root"]
        for key, node in ns["sc_parts"](root).items():
            shade(node, "pic_grass", (0.78, 0.64, 0.36))
    cmds.select(clear=True)
    for k, (name, s) in enumerate(looks):
        x = k * 100.0
        look((x, 0.5, -2.0), (x + 9.0, 7.0, 12.0))
        snap("%s.png" % name)
        look((x + 1.0, 0.8, -3.0), (x + 6.0, 2.2, 5.0))
        snap("%s_low.png" % name)


try:
    main()
except Exception:
    traceback.print_exc()
if os.environ.get("UNLOK_TEST_QUIT") == "1":
    cmds.quit(force=True)
