"""GUI test for Thatch Roof: run inside an interactive Maya.

Opens the toolbox, drives the Thatch Roof panel (box on a house, Make Roof,
live edits through the fields, the roof following its box, undo / redo with
the automatic rebuild, bake) and saves pictures of each roof shape and
thatch style, and of the panel.

Launch (Maya 2023+), with UNLOK_TEST_DIR set to this folder:

    maya.exe -script tests/run_gui_thatch_roof.mel

Outputs go to $UNLOK_TEST_OUT (default: tests/_out/thatch_roof).
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
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "thatch_roof")
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
    """Let timers fire (the box-follow and redo timers)."""
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


def frame_on(nodes, direction=(1.0, 0.55, 1.3), dist=1.9):
    bb = cmds.exactWorldBoundingBox(nodes)
    c = [(bb[i] + bb[i + 3]) * 0.5 for i in range(3)]
    size = max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])
    ln = sum(v * v for v in direction) ** 0.5
    cmds.undoInfo(stateWithoutFlush=False)  # camera moves mustn't come between the test's edits and its undos
    try:
        cmds.setAttr("persp.translate", *[c[i] + direction[i] / ln * size * dist for i in range(3)])
        cmds.viewLookAt("persp", position=c)
    finally:
        cmds.undoInfo(stateWithoutFlush=True)
    pump()


def centre_x(node):
    bb = cmds.exactWorldBoundingBox(node)
    return (bb[0] + bb[3]) * 0.5


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
    panel = [p for p in window.panels() if p.TOOL_NAME == "Thatch Roof"][0]
    names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    window.tabs.setCurrentIndex(names.index("Modeling"))
    page = window.pages[names.index("Modeling")]
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Thatch Roof"][0].click()
    pump(20)
    check("the panel is on screen", panel.isVisible())

    view = cmds.getPanel(type="modelPanel")
    persp = [p for p in view if cmds.modelPanel(p, q=True, camera=True) == "persp"][0]
    cmds.setFocus(persp)
    cmds.modelEditor(persp, e=True, displayAppearance="smoothShaded", grid=False, headsUpDisplay=False,
                     cameras=False, wireframeOnShaded=False)
    cmds.setAttr("persp.focalLength", 50)

    # --- a house, a box on it, a roof
    house = cmds.polyCube(w=8, h=3, d=5, name="house", constructionHistory=False)[0]
    cmds.move(0, 1.5, 0, house)
    cmds.select(house)
    pump()
    panel._sync_from_selection()
    check("NEXT offers Create Box on the house", "Create Box" in panel.next_banner.text.text() and
          panel.box_btn.property("unlokPrimary"), panel.next_banner.text.text())
    panel.create_box()
    pump()
    box = cmds.ls(selection=True, long=True)[0]
    check("Create Box sits a box on the house and selects it", "thatchBox" in box and
          abs(cmds.exactWorldBoundingBox(box)[1] - 3.0) < 1e-4, box)
    panel._sync_from_selection()
    check("NEXT says Make Roof", "Make Roof" in panel.next_banner.text.text(), panel.next_banner.text.text())
    window.grab().save(os.path.join(OUT, "00_panel_box.png"))
    panel.make_roof()
    pump()
    roofs = ns["thatch_roofs"]()
    check("Make Roof thatches the box", len(roofs) == 1, panel.status.text())
    root = roofs[0]
    panel._sync_from_selection()
    check("the banner says EDITING", panel.next_banner.tag.text() == "EDITING", panel.next_banner.text.text())
    cmds.select(clear=True)
    pump()
    panel._sync_from_selection()
    check("the roof stays on the panel when deselected", panel.target() == root)
    frame_on([root, house])
    snap("01_surface_hipped.png")
    window.grab().save(os.path.join(OUT, "02_panel_editing.png"))

    def edit(**values):
        for k, v in values.items():
            panel.f[k].setValue(v)
            panel._queue(k)
        panel._apply_pending()
        pump()

    shots = [("03_gable_points", {"end_a": "Gable", "end_b": "Gable", "pattern": "Points"}),
             ("04_half_hip", {"end_a": "Half-hip", "end_b": "Half-hip", "pattern": "Scallops", "levels": 2}),
             ("05_tiered", {"end_a": "Hip", "end_b": "Hip", "levels": 4, "lip": 0.6, "softness": 0.35}),
             ("06_cone", {"shape": "Cone", "levels": 2}),
             ("07_lean_to", {"shape": "Lean-to", "end_a": "Gable", "end_b": "Hip", "levels": 1}),
             ("08_planes", {"shape": "Ridge", "end_a": "Hip", "end_b": "Gable", "levels": 3, "lip": 0.35,
                            "style": "Planes", "stacks": 3}),
             ("09_pieces3d", {"style": "3D Pieces"})]
    for name, values in shots:
        edit(**values)
        data = ns["thatch_data"](root)
        check("%s: the field edits rebuild the roof" % name, all(data[k] == v for k, v in values.items()) and
              "Updated" in panel.status.text(), panel.status.text())
        frame_on([root, house])
        snap(name + ".png")
    straw = ns["thatch_parts"](root)["straw"]
    frame_on(straw, direction=(0.2, 0.25, 1.0), dist=0.5)
    snap("10_pieces3d_close.png")
    edit(style="Planes")
    snap("10_planes_close.png")
    edit(style="3D Pieces")
    check("pieces rows show, surface rows hide", not panel.piece_sec.isHidden() and panel.surf_sec.isHidden() and
          not panel._rows["sides"][1].isHidden())
    window.grab().save(os.path.join(OUT, "11_panel_pieces.png"))
    edit(style="Surface")

    # --- look presets: Cambodian shacks and a grass hut
    for name in ("Cambodian shack (leaf panels)", "Cambodian shack (straw)", "Grass hut (messy)"):
        panel.preset_combo.setCurrentIndex(panel.preset_combo.findText(name))
        panel.load_preset()
        pump()
        check("%s loads" % name, ns["thatch_data"](root)["style"] == panel.f["style"].value() and
              "on 1 roof" in panel.status.text(), panel.status.text())
        frame_on([root, house])
        snap("12_%s.png" % name.lower().replace(" (", "_").replace(")", "").replace(" ", "_"))
        if name.startswith("Cambodian shack (leaf"):
            frame_on(ns["thatch_parts"](root)["straw"], direction=(0.3, 0.15, 1.0), dist=0.55)
            snap("13_leaf_panels_close.png")
            frame_on([root, house], direction=(0.6, -0.25, 1.3))
            snap("13_leaf_panels_below.png")
            window.grab().save(os.path.join(OUT, "14_panel_leaf.png"))
    panel.preset_combo.setCurrentIndex(panel.preset_combo.findText("Cottage (hipped)"))
    panel.load_preset()
    edit(style="Surface", warp=0.0, ridge_sag=0.0, ragged=0.0, gaps=0.0)

    # --- the roof follows its box
    box = ns["thatch_box"](root)
    x0 = centre_x(ns["thatch_parts"](root)["straw"])
    cmds.move(4, 0, 0, box, relative=True)
    wait(0.6)
    x1 = centre_x(ns["thatch_parts"](root)["straw"])
    check("moving the box moves the roof (once it stops)", abs((x1 - x0) - 4.0) < 0.05,
          "%.3f -> %.3f | %s" % (x0, x1, panel.status.text()))
    cmds.undo()
    wait(0.6)
    check("undoing the move puts the roof back", abs(centre_x(ns["thatch_parts"](root)["straw"]) - x0) < 0.05)

    # --- moving the box's vertices warps the roof (an API callback starts the timer)
    straw = ns["thatch_parts"](root)["straw"]
    before = cmds.exactWorldBoundingBox(straw)
    top = [v for v in ("%s.vtx[%d]" % (box, i) for i in range(8)) if cmds.pointPosition(v, world=True)[1] > 4.0]
    cmds.move(0, 1.2, 0, [v for v in top if cmds.pointPosition(v, world=True)[0] > 0], relative=True)
    wait(1.6)  # two polls: one sees it change, the next sees it settled
    after = cmds.exactWorldBoundingBox(straw)
    check("raising one end of the box's top raises that end of the roof", after[4] - before[4] > 0.5,
          "top %.2f -> %.2f | %s" % (before[4], after[4], panel.status.text()))
    cmds.undo()
    wait(1.6)
    check("undoing the vertex move puts the roof back", abs(cmds.exactWorldBoundingBox(straw)[4] - before[4]) < 0.05,
          "%.2f vs %.2f" % (cmds.exactWorldBoundingBox(straw)[4], before[4]))
    cmds.redo()
    wait(1.6)
    frame_on([root, house])
    snap("15_warped_box.png")
    corners = ["%s.vtx[%d]" % (box, i) for i in range(8)]
    left = [v for v in corners if cmds.pointPosition(v, world=True)[0] < 0]
    cmds.move(0, 0, -0.9, [v for v in left if cmds.pointPosition(v, world=True)[2] > 0], relative=True)
    cmds.move(0, 0, 0.9, [v for v in left if cmds.pointPosition(v, world=True)[2] < 0], relative=True)
    wait(1.6)
    frame_on([root, house])
    snap("16_tapered_box.png")
    check("tapering the box tapers the roof", cmds.exactWorldBoundingBox(straw)[4] > before[4] + 0.5)

    # --- presets
    i = panel.preset_combo.findText("Roundhouse")
    panel.preset_combo.setCurrentIndex(i)
    panel.load_preset()
    pump()
    check("a preset loads onto the roof", ns["thatch_data"](root)["shape"] == "Cone" and
          panel.f["shape"].value() == "Cone", panel.status.text())

    # --- undo / redo of Make Roof: the redo rebuilds
    cmds.select(house)
    panel.create_box()
    box2 = cmds.ls(selection=True, long=True)[0]
    cmds.move(12, 0, 0, box2, relative=True)
    panel._sync_from_selection()
    panel.make_roof()
    pump()
    root2 = [r for r in ns["thatch_roofs"]() if r != root][0]
    nfaces = len(cmds.ls(ns["thatch_parts"](root2)["straw"] + ".f[*]", flatten=True))
    cmds.undo()
    pump()
    check("undo removes the second roof", not cmds.objExists(root2))
    cmds.redo()
    pump()
    panel._rebuild_stale()  # what the Redo scriptJob's timer runs (a scripted redo sends no Redo event)
    pump()
    check("redo brings it back, rebuilt", cmds.objExists(root2) and
          len(cmds.ls(ns["thatch_parts"](root2)["straw"] + ".f[*]", flatten=True)) == nfaces, panel.status.text())

    # --- bake
    cmds.select(root2)
    panel._sync_from_selection()
    panel.bake()
    pump()
    check("bake keeps the meshes and removes the box", not ns["is_thatch_roof"](root2) and cmds.objExists(root2) and
          not cmds.objExists(box2), panel.status.text())


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
