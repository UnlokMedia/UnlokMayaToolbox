"""Pictures of clumping stray grass (Clumping strays: Clumping, Clump size,
Build-up, Heaps on clumps): even strays, then more and more clumped, built
up and heaped, each on its own floor by a wall: run inside an interactive
Maya.

UNLOK_TEST_OUT picks the folder (default tests/_out/grass_clump_pics);
UNLOK_PIC_ONLY=name,... picks scenes; UNLOK_PIC_EXTRA=name:key=v;up.key=v|...
adds scenes (up.<key>: a second Grass layer on top, On layers below, greener).

    maya.exe -script tests/run_gui_grass_clump_pics.mel
"""

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
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "grass_clump_pics")


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
    cmds.setAttr("persp.focalLength", 40)
    strays = dict(ns["sc_start_settings"]("Grass"), grass=0.0, grass_pile=0.0, grass_strays=120.0, coverage=0.9,
                  patchiness=0.2, seed=3)
    extra = os.environ.get("UNLOK_PIC_EXTRA")  # name:key=v;key=v|name:...
    scenes = [("even", {}),
              ("clumped", {"stray_clump": 0.7, "stray_clump_size": 1.2}),
              ("built_up", {"stray_clump": 1.0, "stray_clump_size": 1.5, "stray_buildup": 1.2}),
              ("heaped", {"stray_clump": 1.0, "stray_clump_size": 1.5, "stray_buildup": 1.0, "stray_heaps": 0.8,
                          "grass_pile": 0.8}),
              ("small_heaps", {"stray_clump": 1.3, "stray_clump_size": 0.6, "stray_buildup": 1.5, "stray_heaps": 1.0,
                               "grass_strays": 200.0})]
    for part in (extra or "").split("|"):
        if ":" in part:
            name, kv = part.split(":", 1)
            scenes.append((name, dict((k, float(v)) for k, v in (x.split("=") for x in kv.split(";")))))
    only = [n for n in os.environ.get("UNLOK_PIC_ONLY", "").split(",") if n]
    scenes = [x for x in scenes if not only or x[0] in only]
    log = open(os.path.join(OUT, "log.txt"), "w")
    for k, (name, over) in enumerate(scenes):
        x = k * 100.0
        flr = box("floor_" + name, (40, 1, 40), (x, -0.5, 0), div=4.0)
        wall = box("wall_" + name, (40, 8, 1), (x, 4, -20.5), div=4.0)
        shade([flr, wall], "pic_ground", (0.36, 0.33, 0.30))
        t0 = time.time()
        upper = dict((kk[3:], v) for kk, v in over.items() if kk.startswith("up."))  # a second layer on top
        over = dict((kk, v) for kk, v in over.items() if not kk.startswith("up."))
        rep = ns["create_scatter_group"]([flr, wall], "Grass", dict(strays, **over), select=False)
        if upper:
            got, lid = ns["sc_add_layer"](rep["root"], "Grass", dict(strays, **dict(over, seed=11, **upper)),
                                          top=True)
            rep = dict(rep, bunches="%s + %s" % (rep.get("bunches"), (got or {}).get("bunches")))
        log.write("%s %.2fs %s\n" % (name, time.time() - t0, dict((kk, rep.get(kk)) for kk in
                                                                   ("bunches", "strays", "faces"))))
        log.flush()
        first = ns["sc_data"](rep["root"])["layers"][-1]["id"] if upper else None
        for key, node in ns["sc_parts"](rep["root"]).items():
            if upper and not key.startswith(first + "/"):  # the top layer greener, to tell them apart
                shade(node, "pic_grass_top", (0.55, 0.66, 0.30))
            else:
                shade(node, "pic_grass", (0.80, 0.66, 0.36))
    cmds.select(clear=True)
    for k, (name, _) in enumerate(scenes):
        x = k * 100.0
        look((x, 0.0, -2.0), (x + 4.0, 34.0, 14.0))
        snap("%s_top.png" % name)
        look((x, 0.5, -4.0), (x + 12.0, 8.0, 14.0))
        snap("%s.png" % name)
        look((x + 1.0, 0.3, -4.0), (x + 6.0, 2.0, 3.0))
        snap("%s_low.png" % name)
    log.close()


try:
    main()
except Exception:
    traceback.print_exc()
    with open(os.path.join(OUT, "error.txt"), "w") as f:
        f.write(traceback.format_exc())
if os.environ.get("UNLOK_TEST_QUIT") == "1":
    cmds.quit(force=True)
