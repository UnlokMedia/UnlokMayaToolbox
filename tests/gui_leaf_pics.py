"""Pictures of dropped leaves, close and low, to see gaps under them: run
inside an interactive Maya (no panel needed).

A 30 degree ramp, a lumpy rock, a corrugated roof, a dense floor and a leaf
pile, each with Leaves (and Jungle leaves on some), seen from low down.
UNLOK_TOOLBOX picks the toolbox file (an older one for "before" pictures),
UNLOK_TEST_OUT the folder (default tests/_out/leaf_pics), UNLOK_PIC_TAG a
prefix for the file names.

    maya.exe -script tests/run_gui_leaf_pics.mel
"""

import math
import os
import traceback

import maya.cmds as cmds

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "leaf_pics")
TAG = os.environ.get("UNLOK_PIC_TAG", "")


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
    img.writeToFile(os.path.join(OUT, TAG + name), "png")


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


COLOURS = {"litter": (0.75, 0.38, 0.08), "piles": (0.62, 0.30, 0.06), "green": (0.15, 0.55, 0.10),
           "dry": (0.70, 0.55, 0.25)}


def grow(ns, nodes, layers):
    root = None
    for typ, s in layers:
        if root is None:
            root = ns["create_scatter_group"](nodes, typ, dict(s))["root"]
        else:
            ns["sc_add_layer"](root, typ, dict(s))
    for key, node in ns["sc_parts"](root).items():
        part = key.split("/")[1]
        if part in COLOURS:
            shade(node, "pic_" + part, COLOURS[part])
    return root


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
    cmds.setAttr("persp.focalLength", 50)
    small = {"leaves": 30.0, "coverage": 0.85, "slope": 45.0}
    big = {"jungle": 3.0, "coverage": 0.85, "slope": 45.0}

    ramp = cmds.polyPlane(name="ramp", w=30, h=30, sx=15, sy=15, constructionHistory=False)[0]
    cmds.rotate(30, 0, 0, ramp)
    shade([ramp], "pic_ground", (0.45, 0.45, 0.45))
    grow(ns, [cmds.ls(ramp, long=True)[0]], [("Leaves", small)])

    rock = cmds.polySphere(name="rock", r=8, sx=48, sy=32, constructionHistory=False)[0]
    import maya.api.OpenMaya as om
    fn = om.MFnMesh(ns["get_dag_path"](ns["_log_shape"](rock)))
    ps = fn.getPoints()
    for i, p in enumerate(ps):
        n = (math.sin(1.7 * p.x + 0.3) * math.cos(1.3 * p.z) + 0.6 * math.sin(2.9 * p.y + 1.1 * p.x)) * 0.5
        s = (1.0 + 0.06 * n) * (0.55 if p.y < 0.0 else 1.0)
        ps[i] = om.MPoint(p.x * (1.0 + 0.04 * n), p.y * s, p.z * (1.0 + 0.04 * n))
    fn.setPoints(ps)
    cmds.move(0, 4, 100, rock)
    flr = box("rockFloor", (40, 1, 40), (0, -0.5, 100), div=4.0)
    shade([rock, flr], "pic_ground", (0.45, 0.45, 0.45))
    grow(ns, [cmds.ls(rock, long=True)[0], flr], [("Leaves", small), ("Jungle leaves", big)])

    house = box("house", (24, 10, 16), (100.0, 5.0, 0.0), div=8.0)
    rep = ns["make_thatch_roof"](house, {"covering": "Corrugated", "m_mode": "Clean", "overhang": 0.03,
                                         "shape": "Lean-to", "end_a": "Gable", "end_b": "Gable"})
    grow(ns, [rep["root"]], [("Leaves", small), ("Jungle leaves", dict(big, jungle=1.5))])

    dense = box("denseFloor", (20, 1, 20), (100, -0.5, 100), div=4.0)
    shade([dense], "pic_ground", (0.45, 0.45, 0.45))
    grow(ns, [dense], [("Leaves", {"leaves": 250.0, "coverage": 1.0}), ("Leaf piles", {"coverage": 0.85})])
    cmds.select(clear=True)

    shots = (("ramp.png", (0.0, 0.0, 0.0), (9.0, 2.5, 12.0)),
             ("rock.png", (0.0, 7.0, 100.0), (9.0, 13.0, 113.0)),
             ("rock_low.png", (2.0, 1.5, 104.0), (8.0, 2.2, 112.0)),
             ("corrugated.png", (100.0, 11.0, 0.0), (106.0, 15.0, 9.0)),
             ("dense_low.png", (100.0, 0.0, 100.0), (104.0, 1.0, 104.0)),
             ("dense.png", (100.0, 0.0, 100.0), (106.0, 6.0, 108.0)))
    for name, at, eye in shots:
        look(at, eye)
        snap(name)


try:
    main()
except Exception:
    traceback.print_exc()
if os.environ.get("UNLOK_TEST_QUIT") == "1":
    cmds.quit(force=True)
