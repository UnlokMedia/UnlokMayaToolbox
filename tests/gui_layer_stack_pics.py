"""Pictures of scatter layers on top of each other (On layers below): jungle
leaves above loose grass piles, grass above jungle leaves, small dead leaves
above scattered grass, each on its own floor by a wall: run inside an
interactive Maya.

UNLOK_TEST_OUT picks the folder (default tests/_out/layer_stack_pics).

    maya.exe -script tests/run_gui_layer_stack_pics.mel
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
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "layer_stack_pics")


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


COLOURS = {"grass": ("pic_grass", (0.80, 0.66, 0.36)), "green": ("pic_jungle", (0.18, 0.42, 0.12)),
           "dry": ("pic_jungle_dry", (0.45, 0.27, 0.10)), "litter": ("pic_leaf", (0.62, 0.30, 0.10))}


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
    piles = ns["sc_preset"]("Grass", "Small messy piles")
    scattered = ns["sc_preset"]("Grass", "Scattered blades")
    jungle = dict(ns["sc_start_settings"]("Jungle leaves"), jungle=1.5, coverage=0.8)
    leaves = dict(ns["sc_start_settings"]("Leaves"), leaves=25.0, coverage=0.8)
    grass_top = dict(ns["sc_start_settings"]("Grass"), grass=4.0, grass_pile=0.0, grass_strays=30.0, coverage=0.85)
    # (name, bottom layer, top layer)
    scenes = (("jungle_on_piles", ("Grass", dict(piles, seed=3)),
               ("Jungle leaves", dict(jungle, jungle=4.0, seed=5))),
              ("grass_on_jungle", ("Jungle leaves", dict(jungle, seed=5)), ("Grass", dict(grass_top, seed=3))),
              ("leaves_on_blades", ("Grass", dict(scattered, seed=3)), ("Leaves", dict(leaves, seed=6))))
    for k, (name, low, top) in enumerate(scenes):
        x = k * 100.0
        flr = box("floor_" + name, (24, 1, 24), (x, -0.5, 0), div=4.0)
        wall = box("wall_" + name, (24, 8, 1), (x, 4, -12.5), div=4.0)
        shade([flr, wall], "pic_ground", (0.42, 0.42, 0.42))
        root = ns["create_scatter_group"]([flr, wall], low[0], low[1], select=False)["root"]
        ns["sc_add_layer"](root, top[0], top[1])
        lid = ns["sc_data"](root)["layers"][1]["id"]
        ns["sc_move_layer"](root, lid, -1)  # the second layer goes to the top of the list: on top
        for key, node in ns["sc_parts"](root).items():
            got = COLOURS.get(key.split("/")[-1])
            if got:
                shade(node, got[0], got[1])
    cmds.select(clear=True)
    for k, (name, _, _) in enumerate(scenes):
        x = k * 100.0
        look((x, 0.5, -2.0), (x + 9.0, 7.0, 12.0))
        snap("%s.png" % name)
        look((x + 1.0, 0.8, -3.0), (x + 6.0, 2.2, 5.0))
        snap("%s_low.png" % name)
        look((x, 0.0, -1.0), (x + 0.5, 26.0, 7.0))
        snap("%s_top.png" % name)


try:
    main()
except Exception:
    traceback.print_exc()
if os.environ.get("UNLOK_TEST_QUIT") == "1":
    cmds.quit(force=True)
