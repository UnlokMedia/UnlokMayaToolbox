"""GUI test for Scatter: run inside an interactive Maya.

Opens the toolbox, drives the Scatter panel on a shack porch (a floor, the
shack's wall, a sill beam, two posts, a lean-to roof and its gutter, all
under shack_GRP): a new scatter group from the Maya group with a Leaf
piles layer, then Moss (flat only), Leaves, Grass and a second, sparse
Moss layer added through the panel, live edits, a layer turned off and
back with one Ctrl+Z, a part clicked in the viewport picks its layer, and
saves pictures of each plus the panel.

Launch (Maya 2023+), with UNLOK_TEST_DIR set to this folder:

    maya.exe -script tests/run_gui_scatter.mel

Outputs go to $UNLOK_TEST_OUT (default: tests/_out/scatter).
"""

import json
import os
import time
import traceback

import maya.cmds as cmds

try:
    from PySide2 import QtCore, QtWidgets
except ImportError:
    from PySide6 import QtCore, QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "scatter")
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


def look(at, eye):
    cmds.undoInfo(stateWithoutFlush=False)  # camera moves mustn't come between the test's edits and its undos
    try:
        cmds.setAttr("persp.translate", *eye)
        cmds.viewLookAt("persp", position=at)
    finally:
        cmds.undoInfo(stateWithoutFlush=True)
    pump()


def quiet(fn):
    """Scene set-up out of the undo queue (the test's undos are for the tool's steps)."""
    sel = cmds.ls(selection=True, long=True)
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        return fn()
    finally:
        if sel:
            cmds.select([s for s in sel if cmds.objExists(s)], replace=True)
        else:
            cmds.select(clear=True)
        cmds.undoInfo(stateWithoutFlush=True)


def box(name, size, at, rot=(0, 0, 0), parent=None, div=3.0):
    node = cmds.polyCube(w=size[0], h=size[1], d=size[2], sx=max(1, int(size[0] / div)),
                         sy=max(1, int(size[1] / div)), sz=max(1, int(size[2] / div)), name=name,
                         constructionHistory=False)[0]
    cmds.rotate(rot[0], rot[1], rot[2], node)
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


PART_COLOURS = {"moss": ("testMoss", (0.12, 0.22, 0.05)), "strands": ("testStrand", (0.20, 0.30, 0.07)),
                "capsules": ("testSpore", (0.35, 0.15, 0.06)), "grass": ("testGrass", (0.55, 0.47, 0.30)),
                "litter": ("testLitter", (0.45, 0.26, 0.10)), "piles": ("testPile", (0.55, 0.30, 0.10)),
                "tufts": ("testTuft", (0.14, 0.28, 0.05)), "stems": ("testStem", (0.24, 0.17, 0.10)),
                "leaves": ("testLeaf", (0.07, 0.20, 0.04))}


def shade_part(node, part):
    name, rgb = PART_COLOURS[part]
    shade(node, name, rgb)


def porch():
    """A shack porch in decimetres: floor (top y 0), the shack's wall at z
    -12, a sill beam along its foot, two posts, a lean-to roof from the
    wall's top down to the posts, a gutter at its low edge."""
    grp = cmds.group(empty=True, name="shack_GRP")
    nodes = {
        "floor": box("floor", (70, 1, 44), (0, -0.5, 4), parent=grp),
        "wall": box("shackWall", (70, 26, 1), (0, 13, -12.5), parent=grp),
        "sill": box("sillBeam", (50, 1.6, 1.6), (0, 0.8, -6), parent=grp),
        "postA": box("postA", (1.6, 21, 1.6), (-24, 10.5, 2), parent=grp, div=2.0),
        "postB": box("postB", (1.6, 21, 1.6), (24, 10.5, 2), parent=grp, div=2.0),
        "roof": box("porchRoof", (60, 0.4, 15.6), (0, 23.3, -5.0), rot=(-17, 0, 0), parent=grp, div=2.0),
        "gutterB": box("gutterBottom", (60, 0.3, 1.8), (0, 20.6, 3.6), parent=grp, div=1.0),
        "gutterA": box("gutterSideA", (60, 1.6, 0.2), (0, 21.3, 2.6), parent=grp, div=1.0),
        "gutterC": box("gutterSideB", (60, 1.6, 0.2), (0, 21.3, 4.6), parent=grp, div=1.0),
    }
    return cmds.ls(grp, long=True)[0], nodes


def setup_view():
    view = cmds.getPanel(type="modelPanel")
    persp = [p for p in view if cmds.modelPanel(p, q=True, camera=True) == "persp"][0]
    cmds.setFocus(persp)
    cmds.modelEditor(persp, e=True, displayAppearance="smoothShaded", grid=False, headsUpDisplay=False,
                     cameras=False, wireframeOnShaded=False, twoSidedLighting=True, displayTextures=True)
    cmds.setAttr("persp.focalLength", 45)
    try:
        cmds.setAttr("hardwareRenderingGlobals.ssaoEnable", 1)
        cmds.setAttr("hardwareRenderingGlobals.multiSampleEnable", 1)
    except Exception:
        pass


VIEWS = [("overview", (0, 8, -2), (30, 34, 62)), ("wall_foot", (-6, 1, -10), (6, 12, 6)),
         ("gutter", (-4, 21, 3.6), (8, 32, 16)), ("post_foot", (24, 1, 2), (32, 10, 14))]


def shoot(prefix):
    for name, at, eye in VIEWS:
        look(at, eye)
        snap("%s_%s.png" % (prefix, name))


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
    window.resize(440, 1100)
    panel = [p for p in window.panels() if p.TOOL_NAME == "Scatter"][0]
    names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    window.tabs.setCurrentIndex(names.index("Modeling"))
    page = window.pages[names.index("Modeling")]
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Scatter"][0].click()
    pump(20)
    check("the Scatter panel is in the Modeling tab", panel.isVisible())
    check("there's no Moss and Ivy panel any more", not [p for p in window.panels() if p.TOOL_NAME == "Moss and Ivy"])
    setup_view()

    grp, nodes = quiet(porch)
    shade(list(nodes.values()), "testWood", (0.42, 0.34, 0.25))
    cmds.select(grp)
    panel._sync_from_selection()  # a scripted selection change sends no SelectionChanged event
    check("NEXT offers New Scatter Group", "New Scatter Group" in panel.next_banner.text.text(),
          panel.next_banner.text.text())

    # --- new group: leaf piles, Gutters and wall bases
    panel.start_type.setCurrentIndex(panel.start_type.findText("Leaf piles"))
    panel._show_layer()
    i = panel.preset_combo.findText("Gutters and wall bases")
    panel.preset_combo.setCurrentIndex(i)
    panel.load_preset()
    window.grab().save(os.path.join(OUT, "00_panel_ready.png"))
    t0 = time.time()
    panel.new_btn.click()
    pump()
    roots = ns["sc_groups"]()
    check("New makes scatteredObjects0001_GRP and selects it", len(roots) == 1 and
          ns["short_name"](roots[0]) == "scatteredObjects0001_GRP" and cmds.ls(selection=True, long=True) == roots,
          "%.2fs | %s" % (time.time() - t0, panel.status.text()))
    root = roots[0]
    check("the panel edits it", panel._root == root and panel.layer_list.count() == 1 and
          panel.next_banner.tag.text() == "EDITING", panel.next_banner.text.text())
    check("its surfaces list shows the Maya group", panel.surf_list.count() == 1 and
          "(G)" in panel.surf_list.item(0).text(), panel.surf_list.item(0).text() if panel.surf_list.count() else "")
    data = ns["sc_data"](root)
    piles = data["layers"][0]["id"]
    check("the first layer has the preset", ns["sc_settings"](data["layers"][0])["creases"] == 1.3)

    # --- add layers through the panel
    def add(typ, edits):
        panel.add_type.setCurrentIndex(panel.add_type.findText(typ))
        cmds.select(root)
        panel.add_layer()
        pump()
        lid = panel._lid
        for key, value in edits.items():
            panel.f[typ][key].setValue(value)
            panel._pending.add(key)
        panel._apply_pending()
        return lid

    moss = add("Moss", {"slope": 25.0, "coverage": 0.6, "capsules": 0.0})
    leaves = add("Leaves", {"leaves": 14.0, "coverage": 0.7})
    grass = add("Grass", {"grass": 1.2, "coverage": 0.5})
    moss2 = add("Moss", {"slope": 90.0, "coverage": 0.25, "patchiness": 0.9, "strands": 0.3})
    data = ns["sc_data"](root)
    check("four layers added through the panel", [l["type"] for l in data["layers"]] ==
          ["Leaf piles", "Moss", "Leaves", "Grass", "Moss"] and panel.layer_list.count() == 5,
          str([l["name"] for l in data["layers"]]))
    parts = dict((k, n) for k, n in ns["sc_parts"](root).items() if cmds.getAttr(n + ".visibility"))
    check("the flat moss and the sparse moss each have their own parts",
          any(k.startswith(moss + "/") for k in parts) and any(k.startswith(moss2 + "/") for k in parts) and
          not any(k == moss + "/capsules" for k in parts), str(sorted(ns["short_name"](n) for n in parts.values())))
    check("the flat moss keeps to flat surfaces (Slope limit 25)", ns["sc_settings"](
        ns["sc_layer"](data, moss))["slope"] == 25.0)
    for key, node in parts.items():
        shade_part(node, key.split("/")[1])
    cmds.select(clear=True)
    shoot("01")

    # --- turn a layer off from the list, one Ctrl+Z back
    item = [panel.layer_list.item(k) for k in range(panel.layer_list.count())
            if panel.layer_list.item(k).data(QtCore.Qt.UserRole) == grass][0]
    cmds.select(root)
    panel._sync_from_selection()
    item = [panel.layer_list.item(k) for k in range(panel.layer_list.count())
            if panel.layer_list.item(k).data(QtCore.Qt.UserRole) == grass][0]
    item.setCheckState(QtCore.Qt.Unchecked)
    pump()
    gnode = ns["sc_parts"](root)[grass + "/grass"]
    check("unticking a layer hides it", not cmds.getAttr(gnode + ".visibility") and
          not ns["sc_layer"](ns["sc_data"](root), grass)["on"])
    cmds.undo()
    panel._after_undo()  # a scripted undo sends no Undo event
    check("one Ctrl+Z ticks it back on", cmds.getAttr(gnode + ".visibility") and
          panel.layer_list.item([l["id"] for l in ns["sc_data"](root)["layers"]].index(grass)).checkState() ==
          QtCore.Qt.Checked)

    # --- clicking a part edits its layer
    cmds.select(ns["sc_parts"](root)[leaves + "/litter"])
    panel._sync_from_selection()
    check("clicking a part edits its layer", panel._root == root and panel._lid == leaves and
          panel.box["Leaves"].isVisible(), panel.step_look.title.text())
    window.grab().save(os.path.join(OUT, "02_panel_editing_layer.png"))
    cmds.select(ns["sc_box"](root))
    panel._sync_from_selection()
    check("clicking the box edits the group", panel._root == root)
    look((0, 10, -2), (40, 40, 70))
    snap("03_box.png")

    # --- delete a layer, Duplicate
    cmds.select(root)
    panel._sync_from_selection()
    panel._lid = moss2
    panel.delete_layer()
    check("Delete removes the layer", panel.layer_list.count() == 4 and not any(
        k.startswith(moss2 + "/") for k in ns["sc_parts"](root)))
    panel._lid = piles
    panel.duplicate_layer()
    check("Duplicate copies the layer", panel.layer_list.count() == 5 and
          ns["sc_data"](root)["layers"][-1]["type"] == "Leaf piles", panel.status.text())
    panel.delete_layer()

    # --- pictures of piles alone, at the wall's foot / in the gutter
    for lid in (moss, leaves, grass):
        ns["sc_set_layer"](root, lid, on=False)
    cmds.select(clear=True)
    shoot("04_piles_only")


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


if __name__ == "gui_scatter":
    cmds.evalDeferred(run, lowestPriority=True)
