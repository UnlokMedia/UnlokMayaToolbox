"""GUI test for Moss and Ivy: run inside an interactive Maya.

Opens the toolbox, drives the Moss and Ivy panel (grow moss on a plank
roof, edit it live, undo / redo with the automatic regrow, moss in a stone
wall's crevices, ivy up a shack post and the wall behind it, ivy from
picked seeds) and saves pictures of each plus the panel.

Launch (Maya 2023+), with UNLOK_TEST_DIR set to this folder:

    maya.exe -script tests/run_gui_moss_ivy.mel

Outputs go to $UNLOK_TEST_OUT (default: tests/_out/moss_ivy).
"""

import json
import os
import random
import time
import traceback

import maya.cmds as cmds

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "moss_ivy")
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


def snap(name, width=1400, height=900):
    path = os.path.join(OUT, name)
    cmds.refresh(force=True)
    cmds.playblast(frame=[cmds.currentTime(q=True)], format="image", compression="png", completeFilename=path,
                   viewer=False, showOrnaments=False, percent=100, widthHeight=(width, height), offScreen=True)
    return path


def look(at, eye):
    cmds.undoInfo(stateWithoutFlush=False)  # camera moves mustn't come between the test's edits and its undos
    try:
        cmds.setAttr("persp.translate", *eye)
        cmds.viewLookAt("persp", position=at)
    finally:
        cmds.undoInfo(stateWithoutFlush=True)
    pump()


def box(name, size, at, rot=(0, 0, 0), parent=None):
    node = cmds.polyCube(w=size[0], h=size[1], d=size[2], name=name, constructionHistory=False)[0]
    cmds.rotate(rot[0], rot[1], rot[2], node)
    cmds.move(at[0], at[1], at[2], node)
    if parent:
        node = cmds.parent(node, parent)[0]
    return cmds.ls(node, long=True)[0]


_SG = {}


def shade(nodes, name, rgb, vary=0):
    """Test colours, out of the undo queue (the test's undos are for the tool's steps)."""
    sel = cmds.ls(selection=True, long=True)
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        _shade(nodes, name, rgb, vary)
        if sel:  # making shader nodes selects them
            cmds.select(sel, replace=True)
        else:
            cmds.select(clear=True)
    finally:
        cmds.undoInfo(stateWithoutFlush=True)


def deselect():
    """Clear the selection out of the undo queue (the test's undos are for the tool's steps)."""
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        cmds.select(clear=True)
    finally:
        cmds.undoInfo(stateWithoutFlush=True)


def _shade(nodes, name, rgb, vary):
    if name not in _SG:
        m = cmds.shadingNode("lambert", asShader=True, name=name)
        cmds.setAttr(m + ".color", *rgb, type="double3")
        if vary:  # colour drifting across the scene, as a real moss / leaf texture set would
            frac = cmds.shadingNode("solidFractal", asTexture=True, name=name + "Vary")
            place = cmds.shadingNode("place3dTexture", asUtility=True)
            cmds.setAttr(place + ".scale", vary, vary, vary, type="double3")
            cmds.connectAttr(place + ".worldInverseMatrix[0]", frac + ".placementMatrix")
            cmds.setAttr(frac + ".amplitude", 1.0)
            cmds.setAttr(frac + ".ratio", 0.75)
            cmds.setAttr(frac + ".colorGain", rgb[0] * 1.5, rgb[1] * 1.5, rgb[2] * 1.5, type="double3")
            cmds.setAttr(frac + ".colorOffset", rgb[0] * 0.35, rgb[1] * 0.35, rgb[2] * 0.35, type="double3")
            cmds.connectAttr(frac + ".outColor", m + ".color")
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name + "SG")
        cmds.connectAttr(m + ".outColor", sg + ".surfaceShader")
        _SG[name] = sg
    cmds.sets(nodes, e=True, forceElement=_SG[name])


def shade_parts(ns, root):
    parts = ns["mi_parts"](root)
    colours = {"moss": ("testMoss", (0.11, 0.18, 0.04), 1.5), "strands": ("testStrand", (0.36, 0.33, 0.12), 1.5),
               "stems": ("testStem", (0.24, 0.17, 0.10), 0), "leaves": ("testLeaf", (0.07, 0.20, 0.04), 12.0)}
    for part, node in parts.items():
        name, rgb, vary = colours[part]
        shade(node, name, rgb, vary)


def plank_roof(parent):
    """A shack roof: two slopes of planks with gaps between them, a ridge
    board, on a plank house (decimetres)."""
    planks = []
    pitch = 18.0
    for side in (-1, 1):
        for i in range(11):
            d = 1.2 + i * 2.15  # down the slope from the ridge
            y = 30.0 - d * 0.309
            z = side * d * 0.951
            planks.append(box("roofPlank%d_%02d" % (side + 1, i), (44, 0.35, 2.0), (0, y, z), (side * pitch, 0, 0),
                              parent))
    planks.append(box("ridgeBoard", (44, 0.8, 1.6), (0, 30.25, 0), parent=parent))
    walls = [box("wallFront", (40, 22, 0.6), (0, 11, 18), parent=parent),
             box("wallBack", (40, 22, 0.6), (0, 11, -18), parent=parent)]
    return planks, walls


def stone_wall(parent):
    """A dry stone wall: rows of stones with gaps, a coping ledge on top."""
    random.seed(3)
    stones = []
    y = 0.0
    for row in range(6):
        h = random.uniform(2.2, 3.0)
        x = -20.0 + (row % 2) * 1.5
        while x < 20.0:
            w = random.uniform(3.0, 6.0)
            stones.append(box("stone%02d_%02d" % (row, len(stones)), (w - 0.3, h - 0.25, 4.0 + random.uniform(-0.3, 0.3)),
                              (x + w * 0.5, y + h * 0.5, random.uniform(-0.15, 0.15)), parent=parent))
            x += w
        y += h
    stones.append(box("coping", (42, 1.0, 5.4), (0, y + 0.5, 0), parent=parent))
    return stones


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
    window.resize(420, 1000)
    panel = [p for p in window.panels() if p.TOOL_NAME == "Moss and Ivy"][0]
    names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    window.tabs.setCurrentIndex(names.index("Modeling"))
    page = window.pages[names.index("Modeling")]
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Moss and Ivy"][0].click()
    pump(20)
    check("Moss and Ivy panel is in the Modeling tab", panel.isVisible())
    check("NEXT asks for meshes", "Select the meshes" in panel.next_banner.text.text(), panel.next_banner.text.text())

    view = cmds.getPanel(type="modelPanel")
    persp = [p for p in view if cmds.modelPanel(p, q=True, camera=True) == "persp"][0]
    cmds.setFocus(persp)
    cmds.modelEditor(persp, e=True, displayAppearance="smoothShaded", grid=False, headsUpDisplay=False,
                     cameras=False, wireframeOnShaded=False, twoSidedLighting=True, displayTextures=True)
    cmds.setAttr("persp.focalLength", 45)
    try:
        cmds.setAttr("hardwareRenderingGlobals.ssaoEnable", 1)
        cmds.setAttr("hardwareRenderingGlobals.multiSampleEnable", 1)
        cmds.setAttr("hardwareRenderingGlobals.transparencyAlgorithm", 3)
    except Exception:
        pass

    # --- moss on a plank roof, through the panel
    house = cmds.group(empty=True, name="shack_GRP")
    planks, walls = plank_roof(house)
    shade(planks + walls, "testWood", (0.42, 0.33, 0.24))
    cmds.select(planks)
    panel._sync_from_selection()  # a scripted selection change sends no SelectionChanged event
    check("NEXT offers Grow Moss", "Grow Moss" in panel.next_banner.text.text(), panel.next_banner.text.text())
    window.grab().save(os.path.join(OUT, "00_panel_ready.png"))
    t0 = time.time()
    panel.grow_btn.click()
    pump()
    roots = ns["mi_systems"]()
    check("Grow Moss makes a moss patch and selects it", len(roots) == 1 and
          cmds.ls(selection=True, long=True) == roots, "%.2fs | %s" % (time.time() - t0, panel.status.text()))
    root = roots[0]
    shade_parts(ns, root)
    panel._sync_from_selection()
    check("the panel edits the new moss", panel._mode == "edit" and panel.next_banner.tag.text() == "EDITING",
          panel.next_banner.text.text())
    window.grab().save(os.path.join(OUT, "01_panel_editing.png"))
    faces0 = cmds.polyEvaluate(ns["mi_parts"](root)["moss"], face=True)
    panel.f["Moss"]["coverage"].spin.setValue(0.8)  # like typing it in: queues the edit
    check("the edit is queued", "coverage" in panel._pending)
    panel._apply_pending()  # the edit timer's job
    faces1 = cmds.polyEvaluate(ns["mi_parts"](root)["moss"], face=True)
    check("a slider edits the moss live", faces1 > faces0 and ns["mi_data"](root)["coverage"] == 0.8,
          "%d -> %d faces | %s" % (faces0, faces1, panel.status.text()))
    # undo / redo first: a playblast empties the undo queue in a scripted session
    last = cmds.undoInfo(q=True, undoName=True)
    cmds.undo()
    pump()
    check("one Ctrl+Z removes the moss", not ns["mi_systems"](), "undid: %s" % last)
    cmds.redo()
    panel._rebuild_stale()  # a scripted redo sends no Redo event
    pump()
    check("redo brings the moss back, regrown", len(ns["mi_systems"]()) == 1 and
          cmds.polyEvaluate(ns["mi_parts"](ns["mi_systems"]()[0])["moss"], face=True) == faces0)
    for r in ns["mi_systems"]():
        shade_parts(ns, r)
    deselect()
    look((0, 24, 6), (34, 46, 52))
    snap("02_roof_moss.png")
    look((8, 27, 6), (16, 31, 15))
    snap("03_roof_moss_close.png")
    look((0, 20, 19), (6, 18, 34))
    snap("04_roof_moss_eave.png")
    cmds.delete(ns["mi_systems"]())

    # --- directed: a clump round each picked point (top edges' middles), then moss only on picked faces
    cmds.select(["%s.e[1]" % planks[3], "%s.e[2]" % planks[8], "%s.e[1]" % planks[16]])
    panel._sync_from_selection()
    check("NEXT says where the clumps go", "picked point" in panel.next_banner.text.text(),
          panel.next_banner.text.text())
    panel.grow()
    roots = ns["mi_systems"]()
    check("Grow Moss grows a clump at each picked point", len(roots) == 1 and
          len(ns["mi_data"](roots[0])["seeds"]) == 3, panel.status.text())
    for r in roots:
        shade_parts(ns, r)
    deselect()
    look((0, 24, 6), (34, 46, 52))
    snap("05a_roof_moss_clumps.png")
    cmds.delete(roots)
    cmds.select(["%s.f[1]" % planks[i] for i in (2, 3, 4, 13, 14)])
    panel._sync_from_selection()
    check("NEXT says the moss keeps to the picked faces", "picked face" in panel.next_banner.text.text(),
          panel.next_banner.text.text())
    panel.grow()
    roots = ns["mi_systems"]()
    check("Grow Moss keeps to the picked faces", len(roots) == 1 and ns["mi_data"](roots[0])["faces"],
          panel.status.text())
    for r in roots:
        shade_parts(ns, r)
    deselect()
    look((0, 24, 6), (34, 46, 52))
    snap("05b_roof_moss_faces.png")
    cmds.delete(roots)

    # --- a thick carpet preset on the roof, shaggy over the eaves
    cmds.select(planks)
    panel._sync_from_selection()
    panel.preset_combo.setCurrentIndex(panel.preset_combo.findText("Shaggy hanging"))
    panel.load_preset()
    panel.grow()
    root = ns["mi_systems"]()[0]
    shade_parts(ns, root)
    deselect()
    look((0, 20, 19), (6, 18, 34))
    snap("05_roof_shaggy_eave.png")
    cmds.delete(ns["mi_systems"](), house)

    # --- moss in a stone wall's crevices
    wall = cmds.group(empty=True, name="stoneWall_GRP")
    stones = stone_wall(wall)
    shade(stones, "testStone", (0.45, 0.44, 0.42))
    cmds.select(stones)
    panel._sync_from_selection()
    panel.preset_combo.setCurrentIndex(panel.preset_combo.findText("Crevices only"))
    panel.load_preset()
    panel.grow()
    root = ns["mi_systems"]()[0]
    shade_parts(ns, root)
    rep = ns["update_moss_ivy"]({root: {}})
    check("moss grows in the wall's crevices", rep["clumps"] > 10, panel.status.text())
    deselect()
    look((0, 8, 0), (12, 14, 34))
    snap("06_wall_crevices.png")
    look((-4, 10, 2), (2, 13, 12))
    snap("07_wall_crevices_close.png")
    cmds.delete(ns["mi_systems"](), wall)

    # --- ivy up a shack post and the wall behind it
    panel.kind.buttons["Ivy"].click()
    pump()
    check("the Ivy fields show", panel.box["Ivy"].isVisibleTo(panel) and not panel.box["Moss"].isVisibleTo(panel)
          and "Ivy" in panel.grow_btn.text())
    window.grab().save(os.path.join(OUT, "08_panel_ivy.png"))
    shack = cmds.group(empty=True, name="shackPost_GRP")
    ground = box("ground", (80, 1, 60), (0, -0.5, 0), parent=shack)
    post = box("post", (2.4, 32, 2.4), (0, 16, 8), parent=shack)
    beam = box("beam", (40, 2.4, 2.4), (0, 33.2, 8), parent=shack)
    back = box("backWall", (40, 34, 0.6), (0, 17, -2), parent=shack)
    shade([ground], "testGround", (0.30, 0.26, 0.20))
    shade([post, beam, back], "testWood", (0.42, 0.33, 0.24))
    cmds.select(post, beam)
    panel._sync_from_selection()
    panel.f["Ivy"]["vines"].setValue(4)
    panel.f["Ivy"]["length"].setValue(4.5)
    t0 = time.time()
    panel.grow()
    pump()
    roots = ns["mi_systems"](kind="Ivy")
    check("Grow Ivy on the post", len(roots) == 1, "%.2fs | %s" % (time.time() - t0, panel.status.text()))
    shade_parts(ns, roots[0])
    stems = ns["mi_parts"](roots[0])["stems"]
    top = cmds.exactWorldBoundingBox(stems)[4]
    check("ivy climbs the post to the beam", top > 30.0, "top at %.1f" % top)
    deselect()
    look((0, 18, 8), (28, 24, 46))
    snap("09_ivy_post.png")
    look((0, 12, 9), (6, 14, 20))
    snap("10_ivy_post_close.png")
    look((0, 33, 9), (10, 28, 22))
    snap("11_ivy_beam.png")

    # ivy on the wall from picked seeds (its two front bottom corners)
    cmds.select(back + ".vtx[0:1]")
    panel._sync_from_selection()
    seeds = ns["mi_selection"]()[2]
    check("picked vertices are seeds", len(seeds) == 2, str(seeds))
    panel.f["Ivy"]["vines"].setValue(6)
    panel.f["Ivy"]["length"].setValue(3.5)
    panel.f["Ivy"]["gravity"].setValue(0.6)
    panel.grow()
    roots = ns["mi_systems"](kind="Ivy")
    check("Grow Ivy from picked seeds", len(roots) == 2, panel.status.text())
    for r in roots:
        shade_parts(ns, r)
    deselect()
    look((0, 16, 0), (30, 22, 50))
    snap("12_ivy_wall_and_post.png")

    # live: Randomize on the selected ivy
    cmds.select(roots[-1])
    panel._sync_from_selection()
    before = cmds.polyEvaluate(ns["mi_parts"](roots[-1])["leaves"], face=True)
    seed0 = ns["mi_data"](roots[-1])["seed"]
    panel.randomize()
    check("Randomize regrows the selected ivy", ns["mi_data"](roots[-1])["seed"] != seed0,
          "%d -> %d leaves faces" % (before, cmds.polyEvaluate(ns["mi_parts"](roots[-1])["leaves"], face=True)))
    window.grab().save(os.path.join(OUT, "13_panel_ivy_editing.png"))

    # bake everything, one Ctrl+Z
    deselect()
    panel._sync_from_selection()
    panel.bake()
    check("Bake with nothing selected bakes all", not ns["mi_systems"]() and len(ns["mi_systems"](baked=True)) == 2,
          panel.status.text())
    cmds.undo()
    check("one Ctrl+Z undoes the bake", len(ns["mi_systems"]()) == 2)


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
