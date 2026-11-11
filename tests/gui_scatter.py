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
import math
import os
import time
import traceback

import maya.cmds as cmds

try:
    from PySide2 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets

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
    """The viewport read back as it is (width / height: unused). Not a playblast: in a scripted session one
    can empty the undo queue, and then a later Ctrl+Z check finds nothing to undo (it failed now and then)."""
    import maya.OpenMaya as om1
    import maya.OpenMayaUI as omui1
    path = os.path.join(OUT, name)
    cmds.refresh(force=True)
    img = om1.MImage()
    omui1.M3dView.active3dView().readColorBuffer(img, True)
    img.writeToFile(path, "png")
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
                "leaves": ("testLeaf", (0.07, 0.20, 0.04)), "green": ("testJungle", (0.10, 0.32, 0.06)),
                "dry": ("testJungleDry", (0.50, 0.36, 0.16)), "specks": ("testSpeck", (0.16, 0.30, 0.05)),
                "dirt": ("testDirt", (0.22, 0.15, 0.08))}


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

    # --- the box beside the group: click it, drag the group into a publish group, delete the box, Make Box
    bx = ns["sc_box"](root)
    cmds.select(clear=True)
    panel._sync_from_selection()
    cmds.select(bx)
    panel._sync_from_selection()
    pump()
    check("the box is beside the group, and clicking it picks the group",
          not cmds.listRelatives(bx, parent=True) and panel._root == root and panel.box_btn.isHidden())
    pub = cmds.group(empty=True, world=True, name="publish_GRP")
    cmds.xform(pub, translation=(5, 2, 0), rotation=(0, 20, 0))
    moved = cmds.ls(cmds.parent(root, pub)[0], long=True)[0]
    cmds.select(clear=True)
    panel._refresh()
    pump()
    check("dragged into a moved publish group, the panel still edits it", panel._root == moved and
          panel.layer_list.count() == 1 and ns["sc_box"](moved) == bx, str(panel._root))
    cmds.delete(bx)
    panel._refresh()
    pump()
    check("its box deleted: Make Box shows", not panel.box_btn.isHidden())
    panel.box_btn.click()
    pump()
    nb = ns["sc_box"](moved)
    check("Make Box puts one back beside it", nb and not cmds.listRelatives(nb, parent=True) and
          panel.box_btn.isHidden(), panel.status.text())
    cmds.parent(moved, world=True)
    cmds.delete(pub)
    cmds.select(root)
    panel._sync_from_selection()
    pump()

    # --- add layers through the panel
    def add(typ, edits):
        cmds.select(root)
        panel.add_layer(typ)
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
    drawing(ns, panel, window)
    jungle_leaves(ns, panel, window)
    moss_and_specks(ns, panel, window)
    pause_play(ns, panel, window)
    draft_mode(ns, panel, window)
    height_fade(ns, panel, window)


def pause_play(ns, panel, window):
    """Pause, make edits (nothing grows, the changed layers marked), Play
    grows them, one Ctrl+Z takes the paused edits back."""
    cmds.file(new=True, force=True)
    _SG.clear()
    grp, nodes = quiet(porch)
    shade(list(nodes.values()), "testWood", (0.42, 0.34, 0.25))
    cmds.select([nodes["roof"], nodes["sill"], nodes["floor"]])
    panel._sync_from_selection()
    panel.start_type.setCurrentIndex(panel.start_type.findText("Moss"))
    panel._show_layer()
    panel.new_btn.click()
    pump()
    root = panel._root
    moss = panel._lid
    cmds.select(root)
    panel.add_layer("Leaves")
    pump()
    leaves = panel._lid

    def verts(lid, part):
        node = ns["sc_parts"](root).get(lid + "/" + part)
        return cmds.polyEvaluate(node, vertex=True) if node and cmds.getAttr(node + ".visibility") else 0

    def rows():
        return [panel.layer_list.item(k).text() for k in range(panel.layer_list.count())]

    v0 = (verts(moss, "moss"), verts(leaves, "litter"))
    check("Pause shows near the top, live by default", panel.pause_btn.isVisible() and
          panel.pause_btn.text() == "Pause" and not ns["sc_paused"](), panel.pause_label.text())
    panel.pause_btn.click()
    pump()
    check("Pause: the button turns to Play, the banner says PAUSED", panel.pause_btn.text() == "Play" and
          panel.next_banner.tag.text() == "PAUSED", panel.next_banner.text.text())
    item = [panel.layer_list.item(k) for k in range(panel.layer_list.count())
            if panel.layer_list.item(k).data(QtCore.Qt.UserRole) == leaves][0]
    item.setCheckState(QtCore.Qt.Unchecked)
    pump()
    panel._lid = moss
    panel._show_layer()
    t0 = time.time()
    for value in (0.9, 1.0):
        panel.f["Moss"]["coverage"].setValue(value)
        panel._pending.add("coverage")
        panel._apply_pending()
    dt = time.time() - t0
    pump()
    check("paused edits grow nothing", verts(moss, "moss") == v0[0] and verts(leaves, "litter") == v0[1] and
          "Play" in panel.status.text(), "%.3fs | %s" % (dt, panel.status.text()))
    check("the changed layers are marked, and counted", all("(changed)" in r for r in rows()) and
          "2 layers changed" in panel.pause_label.text(), "%s | %s" % (rows(), panel.pause_label.text()))
    window.grab().save(os.path.join(OUT, "14_panel_paused.png"))
    t0 = time.time()
    panel.pause_btn.click()
    pump()
    v1 = (verts(moss, "moss"), verts(leaves, "litter"))
    check("Play grows the changes, once", v1[0] > v0[0] and v1[1] == 0 and "grew 2 layers" in panel.status.text(),
          "%s -> %s, %.2fs | %s" % (v0, v1, time.time() - t0, panel.status.text()))
    check("... and the marks go, live again", not any("(changed)" in r for r in rows()) and
          panel.pause_btn.text() == "Pause" and panel.next_banner.tag.text() != "PAUSED", str(rows()))
    window.grab().save(os.path.join(OUT, "14_panel_played.png"))
    name = cmds.undoInfo(q=True, undoName=True)
    cmds.undo()
    panel._after_undo()
    check("one Ctrl+Z takes Play's edits back", verts(moss, "moss") == v0[0],
          "%s: %d -> %d" % (name, v1[0], verts(moss, "moss")))

    # a live edit too big to grow quickly: paused with a warning (the edit kept), Play grows it anyway
    keep = ns["MOSS_WARN_CELLS"]
    ns["MOSS_WARN_CELLS"] = 1000
    v2 = verts(moss, "moss")
    panel.f["Moss"]["coverage"].setValue(0.37)  # (a value no other section grows: a cached bed is quick, so never too big)
    panel._pending.add("coverage")
    panel._apply_pending()
    pump()
    check("a moss edit too big to grow quickly pauses, with a warning", ns["sc_paused"]() and
          panel.pause_btn.text() == "Play" and "minute or more" in panel.status.text() and
          verts(moss, "moss") == v2, panel.status.text())
    window.grab().save(os.path.join(OUT, "14_panel_too_big.png"))
    panel.pause_btn.click()
    pump()
    check("... Play grows it anyway", not ns["sc_paused"]() and verts(moss, "moss") != v2, panel.status.text())
    ns["MOSS_WARN_CELLS"] = keep


def draft_mode(ns, panel, window):
    """Draft (the user: "scattering moss is slowwwwwww"): on, a moss edit
    grows a quick rough look (the row marked, no strands), Full detail
    grows it properly, Draft off with no drafts left just says so."""
    cmds.file(new=True, force=True)
    _SG.clear()
    grp, nodes = quiet(porch)
    shade(list(nodes.values()), "testWood", (0.42, 0.34, 0.25))
    cmds.select([nodes["roof"], nodes["sill"], nodes["floor"]])
    panel._sync_from_selection()
    panel.start_type.setCurrentIndex(panel.start_type.findText("Moss"))
    panel._show_layer()
    panel.new_btn.click()
    pump()
    root, moss = panel._root, panel._lid
    shade_part(ns["sc_parts"](root)[moss + "/moss"], "moss")

    def verts(part):
        node = ns["sc_parts"](root).get(moss + "/" + part)
        n = cmds.polyEvaluate(node, vertex=True) if node and cmds.getAttr(node + ".visibility") else 0
        if part == "strands":  # instanced shoots count as strands
            sh = ns["sc_shoots"](root).get(moss + "/shoots")
            if sh and cmds.getAttr(sh + ".visibility"):
                ps = ns["_sc_shoot_nodes"](sh)[0]
                n += cmds.particle(ps, q=True, count=True) if ps else 0
        return n

    def row():
        return [panel.layer_list.item(k).text() for k in range(panel.layer_list.count())
                if panel.layer_list.item(k).data(QtCore.Qt.UserRole) == moss][0]

    def edit(value):
        panel.f["Moss"]["coverage"].setValue(value)
        panel._pending.add("coverage")
        t0 = time.time()
        panel._apply_pending()
        pump()
        return time.time() - t0

    t_full = edit(0.6)
    full = (verts("moss"), verts("strands"))
    check("Draft and Full detail show under Pause, Draft off, nothing to grow in full",
          panel.draft_btn.isVisible() and not panel.draft_btn.isChecked() and not panel.full_btn.isEnabled(),
          panel.draft_label.text())
    panel.draft_btn.click()
    pump()
    check("Draft on: the button lights, the line says what it does", panel.draft_btn.isChecked() and
          ns["sc_drafting"]() and "quick rough look" in panel.draft_label.text(), panel.draft_label.text())
    edit(0.52)  # the first draft lays its coarse grid out
    t_draft = edit(0.53)  # (not 0.55: the group grew in full at that when made, so that comes from the cache)
    d = (verts("moss"), verts("strands"))
    check("a moss edit in Draft: quick, rough, the layer marked (draft)", d[1] == 0 and 0 < d[0] < full[0] and
          "(draft)" in row() and panel.full_btn.isEnabled() and "Full detail" in panel.status.text() and
          t_draft < t_full, "%.2fs (full %.2fs), %s vs %s | %s | %s" % (t_draft, t_full, d, full, row(),
                                                                        panel.status.text()))
    window.grab().save(os.path.join(OUT, "15_panel_draft.png"))
    cmds.select(clear=True)
    look(*VIEWS[0][1:])
    snap("15_draft_overview.png")
    look(*VIEWS[2][1:])
    snap("15_draft_gutter.png")
    panel.full_btn.click()
    pump()
    f = (verts("moss"), verts("strands"))
    check("Full detail grows it properly, the mark goes", f[0] > d[0] and f[1] > 0 and "(draft)" not in row() and
          not panel.full_btn.isEnabled() and "grew 1 draft layer" in panel.status.text(),
          "%s -> %s | %s" % (d, f, panel.status.text()))
    window.grab().save(os.path.join(OUT, "15_panel_full_detail.png"))
    cmds.select(clear=True)
    look(*VIEWS[0][1:])
    snap("15_full_overview.png")
    look(*VIEWS[2][1:])
    snap("15_full_gutter.png")
    edit(0.5)
    panel.draft_btn.click()  # Draft off with a draft: grows it in full
    pump()
    check("Draft off grows the drafts in full", not ns["sc_drafting"]() and not panel.draft_btn.isChecked() and
          verts("strands") > 0 and "(draft)" not in row(), panel.status.text())

    def saved():
        layer = [lay for lay in ns["sc_data"](root)["layers"] if lay["id"] == moss][0]
        return ns["sc_settings"](layer)["coverage"]

    # a slow layer (the speed pass: a drag at High queued a rebuild per tick): while its slider is held a moss
    # edit grows the quick draft look; let go, the layer grows in full
    field = panel.f["Moss"]["coverage"]
    # this layer grew slowly last time (remembered per layer): a held slider drafts from its very first tick,
    # whatever the last update of another layer took
    panel._slow = False
    panel._took[(panel._root, panel._lid)] = 1.0
    field.slider.setSliderDown(True)
    field.setValue(0.47)
    panel._pending.add("coverage")
    panel._apply_pending()
    pump()
    held = (abs(saved() - 0.47) < 1e-6, moss in ns["sc_drafted"](root), verts("strands") == 0,
            panel._edit_timer.isActive())
    field.slider.setSliderDown(False)
    panel._edit_timer.stop()
    panel._apply_pending()
    pump()
    let_go = (moss not in ns["sc_drafted"](root), verts("strands") > 0, "(draft)" not in row())
    check("a slow moss layer: a held slider grows the draft look, let go it grows in full",
          all(held) and all(let_go), "held %s, let go %s | %s" % (held, let_go, panel.status.text()))

def colonnade():
    """Columns 3 m high (decimetres) on a floor: A a cylinder; B1 and B2
    one mesh; C a base, shaft and capital (three meshes)."""
    grp = cmds.group(empty=True, name="colonnade_GRP")
    floor = box("floor", (70, 1, 34), (0, -0.5, 0), parent=grp)

    def cyl(name, x, z, h=30.0, y0=0.0):
        c = cmds.polyCylinder(name=name, r=2.5, h=h, sx=24, sy=max(1, int(h / 2.5)), sc=1,
                              constructionHistory=False)[0]
        cmds.move(x, y0 + 0.5 * h, z, c)
        return c

    a = cyl("colA", -22, 0)
    b = cmds.polyUnite(cyl("colB1", -8, 3), cyl("colB2", 6, 3), constructionHistory=False, name="colB")[0]
    base = box("colC_base", (8, 3, 8), (20, 1.5, -2), div=1.0)
    shaft = cyl("colC_shaft", 20, -2, h=24.0, y0=3.0)
    cap = box("colC_cap", (8, 3, 8), (20, 28.5, -2), div=1.0)
    cols = [cmds.ls(cmds.parent(n, grp)[0], long=True)[0] for n in (a, b, base, shaft, cap)]
    return cmds.ls(grp, long=True)[0], floor, cols


def height_fade(ns, panel, window):
    """Height fade (the user: "moss and ivy growing up columns from the
    bottom fading out towards the top"): before, moss stays on the floor
    and ivy climbs to the top; Height fade From base (its rows showing as
    it is turned on, the height by part or metres) and the moss climbs
    each column's foot, ivy (Column base) stops part way up."""
    cmds.file(new=True, force=True)
    _SG.clear()
    grp, floor, cols = quiet(colonnade)
    shade([floor] + cols, "testStone", (0.62, 0.60, 0.55))

    def make(sel, typ, preset, extra):
        cmds.select(sel)
        panel._sync_from_selection()
        panel._root, panel._lid = None, None  # a new group, not a preset on the layer being edited
        panel.start_type.setCurrentIndex(panel.start_type.findText(typ))
        panel._show_layer()
        panel.preset_combo.setCurrentIndex(panel.preset_combo.findText(preset))
        panel.load_preset()
        for key, value in extra.items():
            panel.f[typ][key].setValue(value)
        panel.new_btn.click()
        pump()
        root = panel._root
        for key, node in ns["sc_parts"](root).items():
            shade_part(node, key.split("/")[1])
        return root

    def on_columns(root, part):
        node = [n for k, n in ns["sc_parts"](root).items() if k.endswith("/" + part)]
        if not node or not cmds.getAttr(node[0] + ".visibility"):
            return []
        import maya.api.OpenMaya as om
        fn = om.MFnMesh(ns["get_dag_path"](ns["_log_shape"](node[0])))
        return [p.y for p in fn.getPoints(om.MSpace.kWorld) if p.y > 0.6 and abs(p.z) < 10.0 and
                min(abs(p.x - x) for x in (-22, -8, 6, 20)) < 5.0]

    def pictures(tag):
        cmds.select(clear=True)
        look((0, 12, 0), (14, 34, 80))
        snap("16_%s_overview.png" % tag)
        look((-22, 12, 0), (-8, 18, 34))
        snap("16_%s_column.png" % tag)
        look((20, 12, -2), (34, 16, 30))
        snap("16_%s_stack.png" % tag)

    moss_root = make([grp], "Moss", "Jungle roof", {"coverage": 0.6})
    ivy_root = make(cols, "Ivy", "Column base", {"fade": "Off"})
    m0, i0 = on_columns(moss_root, "moss"), on_columns(ivy_root, "stems")
    pictures("before")

    # ivy: turn the fade on
    cmds.select(ivy_root)
    panel._sync_from_selection()
    panel.f["Ivy"]["fade"].setValue("From base")
    panel._pending.add("fade")
    panel._apply_pending()
    pump()
    for key, node in ns["sc_parts"](ivy_root).items():
        shade_part(node, key.split("/")[1])
    i1 = on_columns(ivy_root, "stems")

    # ivy: Vines are Per mesh, 2 each: every column gets its own
    fi = panel.f["Ivy"]
    rows = [k for k in ("vines_by", "vine_spacing", "climb_var") if fi[k].isVisible()]
    check("the Ivy panel shows Vines are, Spacing and Climb variation", len(rows) == 3, str(rows))
    fi["vines_by"].buttons["Per mesh"].click()
    fi["vines"].setValue(2)
    fi["climb_var"].setValue(0.5)
    panel._pending.update(("vines_by", "vines", "climb_var"))
    panel._apply_pending()
    pump()
    window.grab().save(os.path.join(OUT, "16_panel_ivy.png"))
    for key, node in ns["sc_parts"](ivy_root).items():
        shade_part(node, key.split("/")[1])
    stems = [n for k, n in ns["sc_parts"](ivy_root).items() if k.endswith("/stems")]
    import maya.api.OpenMaya as om
    fn = om.MFnMesh(ns["get_dag_path"](ns["_log_shape"](stems[0])))
    xs = set(min((-22, -8, 6, 20), key=lambda x: abs(p.x - x)) for p in fn.getPoints(om.MSpace.kWorld)
             if p.y > 0.6 and abs(p.z) < 10.0 and min(abs(p.x - x) for x in (-22, -8, 6, 20)) < 5.0)
    check("Vines are Per mesh: ivy on every column", xs == {-22, -8, 6, 20}, str(sorted(xs)))

    # moss: the rows follow Height fade and Fade by
    cmds.select(moss_root)
    panel._sync_from_selection()
    pump()
    f = panel.f["Moss"]
    panel.fade_sec["Moss"].header.setChecked(True)

    def shown():
        return [k for k in ("fade_by", "fade_part", "fade_height", "fade_soft") if not f[k].isHidden()]

    off_rows = shown()
    f["fade"].buttons["From base"].click()
    pump()
    on_rows = shown()
    f["fade_by"].buttons["Metres"].click()
    pump()
    metre_rows = shown()
    f["fade_by"].buttons["Object height"].click()
    check("Height fade: its rows show when it is on, the height as a part or in metres",
          off_rows == [] and on_rows == ["fade_by", "fade_part", "fade_soft"] and
          metre_rows == ["fade_by", "fade_height", "fade_soft"], "%s / %s / %s" % (off_rows, on_rows, metre_rows))
    f["fade_part"].setValue(0.5)
    f["fade_soft"].setValue(0.6)
    panel._pending.update(("fade", "fade_by", "fade_part", "fade_soft"))
    panel._apply_pending()
    pump()
    for key, node in ns["sc_parts"](moss_root).items():
        shade_part(node, key.split("/")[1])
    m1 = on_columns(moss_root, "moss")
    window.grab().save(os.path.join(OUT, "16_panel_fade.png"))
    check("moss climbs the columns from their feet, no higher than half way",
          sum(1 for y in m1 if 4.0 < y < 26.0) > 4 * max(50, sum(1 for y in m0 if 4.0 < y < 26.0)) and max(m1) < 16.0,
          "%d -> %d points up the columns (4..26), top %.1f" %
          (sum(1 for y in m0 if 4.0 < y < 26.0), sum(1 for y in m1 if 4.0 < y < 26.0), max(m1 or [0])))
    check("ivy (Column base) stops part way up", i0 and i1 and max(i1) < 22.0 < max(i0),
          "stems top %.1f -> %.1f" % (max(i0 or [0]), max(i1 or [0])))
    pictures("fade")


def moss_and_specks(ns, panel, window):
    """Moss as a carpet, then as Clumps (before / after) on a fresh porch;
    then Specks on a window pane in front of the shack's wall."""
    cmds.file(new=True, force=True)
    _SG.clear()
    grp, nodes = quiet(porch)
    shade(list(nodes.values()), "testWood", (0.42, 0.34, 0.25))
    glass = quiet(lambda: box("windowGlass", (16, 10, 0.1), (0, 9, -11.7), div=1.0))
    shade([glass], "testGlass", (0.62, 0.74, 0.80))

    def grow(sel, typ, preset, extra=None):
        cmds.select(sel)
        panel._sync_from_selection()
        panel.start_type.setCurrentIndex(panel.start_type.findText(typ))
        panel._show_layer()
        panel.preset_combo.setCurrentIndex(panel.preset_combo.findText(preset))
        panel.load_preset()
        for key, value in (extra or {}).items():
            panel.f[typ][key].setValue(value)
        t0 = time.time()
        panel.new_btn.click()
        pump()
        root = panel._root
        for key, node in ns["sc_parts"](root).items():
            shade_part(node, key.split("/")[1])
        cmds.undoInfo(stateWithoutFlush=False)
        cmds.select(clear=True)
        cmds.undoInfo(stateWithoutFlush=True)
        return root, time.time() - t0

    roof = (0, 22, -5), (10, 40, 18)
    root, dt = grow([nodes["roof"], nodes["sill"], nodes["floor"]], "Moss", "Moss")
    carpet = sum(cmds.polyEvaluate(n, face=True) for k, n in ns["sc_parts"](root).items() if k.endswith("/moss"))
    look(*roof)
    snap("12_moss_carpet.png")
    look((0, 1, -6), (10, 9, 6))
    snap("12_moss_carpet_sill.png")
    quiet(lambda: cmds.delete(root))
    root, dt = grow([nodes["roof"], nodes["sill"], nodes["floor"]], "Moss", "Moss", {"style": "Clumps"})
    rep = panel.status.text()
    clumps = sum(cmds.polyEvaluate(n, face=True) for k, n in ns["sc_parts"](root).items() if k.endswith("/moss"))
    check("Moss Style Clumps from the panel: separate cushions, lighter than the carpet",
          "moss clumps" in rep and 0 < clumps < carpet, "%d faces vs %d | %.2fs | %s" % (clumps, carpet, dt, rep))
    check("the Clumps section shows for Clumps only", not panel.clump_sec["Moss"].isHidden())
    window.grab().save(os.path.join(OUT, "12_panel_moss_clumps.png"))
    look(*roof)
    snap("12_moss_clumps.png")
    look((0, 1, -6), (10, 9, 6))
    snap("12_moss_clumps_sill.png")
    quiet(lambda: cmds.delete(root))
    for name, extra in (("even", {"clump_group": 0.0}), ("grouped", {"clump_group": 1.0, "clump_pack": 0.9}),
                        ("heights", {"clump_group": 0.8, "clump_pack": 0.7, "clump_hvar": 0.8, "clump_mounds": 0.5,
                                     "clump_ghvar": 0.9})):
        extra["style"] = "Clumps"
        root, dt = grow([nodes["roof"], nodes["sill"], nodes["floor"]], "Moss", "Moss", extra)
        look(*roof)
        snap("12_moss_clumps_%s.png" % name)
        quiet(lambda: cmds.delete(root))
    panel.f["Moss"]["style"].setValue("Carpet")
    panel._style_rows("Moss")
    check("... and hides for Carpet", panel.clump_sec["Moss"].isHidden())

    root, dt = grow([glass], "Specks", "Moss and dirt specks")
    rep = panel.status.text()
    check("Specks on a window pane from the panel", "specks" in rep and
          sorted(k.split("/")[1] for k in ns["sc_parts"](root)) == ["dirt", "specks"], "%.2fs | %s" % (dt, rep))
    window.grab().save(os.path.join(OUT, "13_panel_specks.png"))
    look((0, 9, -11.7), (8, 14, 4))
    snap("13_specks_glass.png")
    look((1, 8, -11.7), (2.2, 8.8, -8.6))
    snap("13_specks_close.png")


def drawing(ns, panel, window):
    """Draw on Surfaces over a fresh porch (nothing selected), Ctrl+Z a
    stroke, Scatter on Drawing (moss), add leaves on the same drawing."""
    cmds.file(new=True, force=True)
    _SG.clear()  # the new scene has none of the test shaders
    grp, nodes = porch()
    shade(list(nodes.values()), "testWood", (0.42, 0.34, 0.25))
    cmds.select(clear=True)
    panel._sync_from_selection()
    look((0, 10, -4), (26, 36, 58))

    def to_screen(p):
        r = ns["omui"].M3dView.active3dView().worldToView(ns["om"].MPoint(p[0], p[1], p[2]))
        return r[0], r[1]

    def stroke(pts):
        xs = [to_screen(p) for p in pts]
        panel.drawer.press_at(*xs[0])
        for x, y in xs[1:]:
            panel.drawer.drag_at(x, y)
        panel.drawer.release()
        pump()

    panel.draw_btn.click()
    pump()
    check("Draw on Surfaces starts the drawing tool", panel.drawer.is_active() and
          panel.draw_btn.text() == "Stop Drawing")
    stroke([(x, 24.6, -8.0) for x in range(-22, 23, 2)])                                        # along the roof
    stroke([(x, 0.2, 8.0) for x in range(-22, 12, 2)])                                          # across the floor
    stroke([(8 + 3 * math.sin(y * 0.5), y, -11.9) for y in range(2, 20)])                      # up the wall
    stroke([(x, 0.2, 14.0) for x in range(-10, 10, 2)])                                         # a mistake
    n_before = len(panel.drawer.strokes)
    undo_name = cmds.undoInfo(q=True, undoName=True)
    ev = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
    QtWidgets.QApplication.sendEvent(ns["maya_main_window"](), ev)
    pump(10)
    check("Ctrl+Z while drawing takes the last stroke back (not Maya's undo)",
          n_before == 4 and len(panel.drawer.strokes) == 3 and cmds.undoInfo(q=True, undoName=True) == undo_name,
          "%d -> %d strokes" % (n_before, len(panel.drawer.strokes)))
    meshes = sorted(ns["short_name"](m) for m in panel.drawer.meshes())
    check("the strokes landed on the meshes under them (floor, wall)", {"floor", "shackWall"} <= set(meshes),
          str(meshes))
    window.grab().save(os.path.join(OUT, "05_panel_drawing.png"))
    snap("05_drawing.png")

    panel.start_type.setCurrentIndex(panel.start_type.findText("Moss"))
    panel._show_layer()
    panel.f["Moss"]["coverage"].setValue(0.42)
    panel.f["Moss"]["draw_width"].setValue(0.4)
    t0 = time.time()
    panel.scatter_draw_btn.click()
    pump()
    roots = ns["sc_groups"]()
    root = roots[0] if roots else None
    data = ns["sc_data"](root) if root else {"layers": []}
    check("Scatter on Drawing makes a group from the strokes alone",
          len(roots) == 1 and len(data["layers"]) == 1 and ns["sc_area"](data["layers"][0])[2] == 3 and
          not panel.drawer.is_active(), "%.2fs | %s" % (time.time() - t0, panel.status.text()))
    check("its surfaces are the meshes drawn on", sorted(ns["short_name"](n) for n in ns["sc_surfaces"](data)) ==
          meshes, str(sorted(ns["short_name"](n) for n in ns["sc_surfaces"](data))))
    check("the Drawing settings show for a drawn layer", not panel.draw_sec["Moss"].isHidden())
    panel.start_type.setCurrentIndex(panel.start_type.findText("Leaves"))
    panel._update_states()
    check("with a group open it adds a layer on the drawing", panel.scatter_draw_btn.text() == "Add Layer on Drawing")
    panel.scatter_draw_btn.click()
    pump()
    data = ns["sc_data"](root)
    leaves = data["layers"][-1]["id"]
    check("a leaves layer along the same strokes", len(data["layers"]) == 2 and
          data["layers"][-1]["type"] == "Leaves" and ns["sc_area"](data["layers"][-1])[2] == 3)
    panel.f["Leaves"]["leaves"].setValue(40.0)
    panel.f["Leaves"]["draw_width"].setValue(0.6)
    panel._queue("Leaves", "leaves")
    panel._queue("Leaves", "draw_width")
    panel._apply_pending()
    check("Width is live", ns["sc_settings"](ns["sc_layer"](ns["sc_data"](root), leaves))["draw_width"] == 0.6)
    # Ctrl+Z straight after, as a user would: the live edits mustn't get in its way. (Checked after the pictures
    # and Clear below, it failed now and then: in one long scripted call Maya's undo queue isn't dependable once
    # many steps outside it have run.)
    pump()
    cmds.undo()
    panel._after_undo()
    n_undo = len(ns["sc_data"](root)["layers"])
    cmds.redo()
    panel._after_undo()
    n_redo = len(ns["sc_data"](root)["layers"])
    check("one Ctrl+Z takes the drawn leaves layer away (live edits and all), redo puts it back",
          n_undo == 1 and n_redo == 2 and ns["sc_layer"](ns["sc_data"](root), leaves) is not None,
          "%d layers after the undo, %d after the redo; %s" % (n_undo, n_redo, panel.status.text()))
    panel._lid = leaves
    panel._refresh()
    panel._queue("Leaves", "leaves")  # the redo is the layer as added: the live edits again, for the pictures
    panel._queue("Leaves", "draw_width")
    panel._apply_pending()
    for key, node in ns["sc_parts"](root).items():
        shade_part(node, key.split("/")[1])
    cmds.undoInfo(stateWithoutFlush=False)
    cmds.select(clear=True)
    cmds.undoInfo(stateWithoutFlush=True)
    window.grab().save(os.path.join(OUT, "06_panel_drawn_layer.png"))
    look((0, 10, -4), (26, 36, 58))
    snap("06_drawn_overview.png")
    look((2, 8, -10), (16, 18, 14))
    snap("06_drawn_wall.png")
    look((0, 22, -5), (10, 40, 18))
    snap("06_drawn_roof.png")
    panel.clear_drawing()
    pump()
    look((0, 10, -4), (26, 36, 58))
    snap("07_drawing_cleared.png")
    check("Clear removes the strokes and their lines", not panel.drawer.strokes and
          not cmds.ls("scatterDrawing*", type="transform"))
    check("Clear leaves what the layers were drawn on", len(ns["sc_data"](root)["layers"]) == 2 and
          ns["sc_area"](ns["sc_layer"](ns["sc_data"](root), leaves))[2] == 3)

    # --- the leaves layer's strokes one by one: listed, Show Strokes, click a line, Delete Stroke, Ctrl+Z
    def button(text):
        found = [w for w in panel.findChildren(QtWidgets.QPushButton) if w.text() == text]
        return found[0] if found else None

    def strokes_now():
        return ns["sc_area"](ns["sc_layer"](ns["sc_data"](root), leaves))[2]

    panel._lid = leaves
    panel._refresh()
    pump()
    rows = [panel.stroke_list.item(i).text() for i in range(panel.stroke_list.count())]
    check("Drawn strokes lists the layer's strokes and the meshes they're on",
          panel.stroke_sec.isVisible() and len(rows) == 3 and "floor" in " ".join(rows) and
          "shackWall" in " ".join(rows), str(rows))
    panel.stroke_show.click()
    pump()
    lines = list(panel.stroke_view.curves)
    check("Show Strokes draws them in the viewport", len(lines) == 3 and all(c and cmds.objExists(c) for c in lines),
          str(lines))
    wall_row = [i for i, r in enumerate(rows) if r.endswith(": shackWall")][0]
    kept = [r.split(": ", 1)[1] for i, r in enumerate(rows) if i != wall_row]
    cmds.select(lines[wall_row])
    panel._sync_from_selection()
    pump()
    check("clicking a stroke's line picks it in the list (the group and layer stay open)",
          panel._picked_strokes() == [wall_row] and panel._root == root and panel._lid == leaves,
          "%s | %s" % (panel._picked_strokes(), panel.status.text()))
    window.grab().save(os.path.join(OUT, "08_panel_strokes.png"))
    look((0, 10, -4), (26, 36, 58))
    snap("08_stroke_picked.png")
    button("Delete Stroke").click()
    pump()
    rows = [panel.stroke_list.item(i).text() for i in range(panel.stroke_list.count())]
    check("Delete Stroke takes just that stroke out of the layer",
          strokes_now() == 2 and [r.split(": ", 1)[1] for r in rows] == kept and
          len(panel.stroke_view.curves) == 2, "%s | %s" % (rows, panel.status.text()))
    snap("08_stroke_deleted.png")
    cmds.undo()
    panel._after_undo()
    pump()
    check("one Ctrl+Z puts it back", strokes_now() == 3 and panel.stroke_list.count() == 3 and
          len(panel.stroke_view.curves) == 3, panel.status.text())
    panel.stroke_show.click()
    pump()
    check("Show Strokes off takes the lines away", not cmds.ls("scatterStroke*", type="transform"))

    # --- Draw on Selected: only the wall takes strokes (one across the floor lands nowhere)
    panel.draw_on.setValue("Selected")
    cmds.select(nodes["wall"])
    panel.draw_btn.click()
    pump()
    stroke([(x, 0.2, 10.0) for x in range(-10, 10, 2)])                    # across the floor: not selected
    stroke([(8 + 3 * math.sin(y * 0.5), y, -11.9) for y in range(2, 20)])  # up the wall
    on = sorted(ns["short_name"](m) for m in panel.drawer.meshes())
    check("Draw on Selected: strokes land only on the selected meshes", len(panel.drawer.strokes) == 1 and
          on == ["shackWall"], "%d strokes on %s" % (len(panel.drawer.strokes), on))
    panel.draw_btn.click()
    panel.clear_drawing()
    panel.draw_on.setValue("Surfaces")
    pump()


def jungle_leaves(ns, panel, window):
    """Before / after on a fresh porch: Leaf piles (Gutters and wall bases),
    then Jungle leaves from the panel (its own settings), then fronds."""
    cmds.file(new=True, force=True)
    _SG.clear()
    grp, nodes = quiet(porch)
    shade(list(nodes.values()), "testWood", (0.42, 0.34, 0.25))

    def grow(typ, preset):
        cmds.select(grp)
        panel._sync_from_selection()
        panel.start_type.setCurrentIndex(panel.start_type.findText(typ))
        panel._show_layer()
        panel.preset_combo.setCurrentIndex(panel.preset_combo.findText(preset))
        panel.load_preset()
        t0 = time.time()
        panel.new_btn.click()
        pump()
        root = panel._root
        for key, node in ns["sc_parts"](root).items():
            shade_part(node, key.split("/")[1])
        cmds.undoInfo(stateWithoutFlush=False)  # (quiet() would put the selection back)
        cmds.select(clear=True)
        cmds.undoInfo(stateWithoutFlush=True)
        return root, time.time() - t0

    def close_ups(root, prefix):
        """A close look at the first leaf of each part (its stalk is vertex 0)."""
        for key, node in sorted(ns["sc_parts"](root).items()):
            p = cmds.pointPosition(node + ".vtx[0]", world=True)
            look(tuple(p), (p[0] + 7.0, p[1] + 9.0, p[2] + 11.0))
            snap("%s_%s.png" % (prefix, key.split("/")[1]))

    root, _ = grow("Leaf piles", "Gutters and wall bases")
    shoot("08_before_piles")
    quiet(lambda: cmds.delete(root))
    root, dt = grow("Jungle leaves", "Fallen jungle leaves")
    rep = panel.status.text()
    check("Jungle leaves: a group of big fallen leaves from the panel", "big leaves" in rep, "%.2fs | %s" % (dt, rep))
    check("Jungle leaves have their own settings (Shape, Per cluster, Green)",
          not panel.f["Jungle leaves"]["jungle_shape"].isHidden() and
          panel.f["Jungle leaves"]["jungle_cluster"].value() == 3)
    window.grab().save(os.path.join(OUT, "09_panel_jungle.png"))
    shoot("09_after_jungle")
    close_ups(root, "09_close")
    panel.f["Jungle leaves"]["jungle_shape"].setValue("Frond")
    panel.f["Jungle leaves"]["jungle_size"].setValue(1.0)
    for key in ("jungle_shape", "jungle_size"):
        panel._queue("Jungle leaves", key)
    panel._apply_pending()
    for key, node in ns["sc_parts"](root).items():
        shade_part(node, key.split("/")[1])
    check("Shape Frond is live", ns["sc_settings"](ns["sc_layer"](ns["sc_data"](root), panel._lid))["jungle_shape"] ==
          "Frond", panel.status.text())
    has = all("drape" in panel.f[t] for t in ("Leaves", "Leaf piles", "Jungle leaves"))
    panel.f["Jungle leaves"]["drape"].setValue(1.0)
    panel._queue("Jungle leaves", "drape")
    panel._apply_pending()
    for key, node in ns["sc_parts"](root).items():
        shade_part(node, key.split("/")[1])
    check("Drape (under More) on Leaves, Leaf piles and Jungle leaves, live", has and ns["sc_settings"](
        ns["sc_layer"](ns["sc_data"](root), panel._lid))["drape"] == 1.0, panel.status.text())
    look((0, 8, -2), (30, 34, 62))
    snap("10_fronds_overview.png")
    close_ups(root, "10_close")

    # --- leave the floor out of the Maya group from the panel, then put it back
    def low_points():
        return sum(1 for node in ns["sc_parts"](root).values() if cmds.getAttr(node + ".visibility")
                   for p in cmds.xform(node + ".vtx[*]", q=True, worldSpace=True, translation=True)[1::3]
                   if p < 0.5)

    floor_pts = low_points()
    cmds.select(nodes["floor"])
    panel._sync_from_selection()
    panel.remove_surfaces()
    pump()
    items = [panel.surf_list.item(i).text() for i in range(panel.surf_list.count())]
    check("Remove on a mesh inside the group leaves just it out (listed under the group)",
          len(items) == 2 and "(G)" in items[0] and "floor" in items[1] and "(left out)" in items[1],
          "%s | %s" % (items, panel.status.text()))
    check("nothing grows on the floor left out", floor_pts > 0 and low_points() == 0,
          "%d -> %d points" % (floor_pts, low_points()))
    for key, node in ns["sc_parts"](root).items():
        shade_part(node, key.split("/")[1])
    cmds.undoInfo(stateWithoutFlush=False)
    cmds.select(clear=True)
    cmds.undoInfo(stateWithoutFlush=True)
    window.grab().save(os.path.join(OUT, "11_panel_left_out.png"))
    look((0, 8, -2), (30, 34, 62))
    snap("11_floor_left_out.png")

    # --- New Group from This / Duplicate Group: the same surfaces (the floor still left out), nothing reselected
    def surf_rows():
        return [panel.surf_list.item(i).text() for i in range(panel.surf_list.count())]

    def button(text):
        found = [b for b in panel.findChildren(QtWidgets.QPushButton) if b.text() == text]
        return found[0] if found else None

    def back_to_root():
        cmds.select(root)
        panel._sync_from_selection()
        pump()

    back_to_root()
    rows, nl = surf_rows(), len(ns["sc_data"](root)["layers"])
    b_from, b_dup = button("New Group from This"), button("Duplicate Group")
    check("New Group from This and Duplicate Group show in step 1", b_from is not None and b_dup is not None and
          b_from.isVisible() and b_dup.isVisible())
    b_from.click()
    pump()
    new = panel._root
    check("New Group from This: an empty group on the same surfaces (the floor left out too), open and selected",
          new != root and ns["is_scatter"](new) and panel.layer_list.count() == 0 and surf_rows() == rows and
          cmds.ls(selection=True, long=True) == [new] and "Add Layer" in panel.status.text(),
          "%s vs %s | %s" % (surf_rows(), rows, panel.status.text()))
    window.grab().save(os.path.join(OUT, "12_panel_new_group_from.png"))
    cmds.undo()
    pump()
    check("one Ctrl+Z takes the new group away", not cmds.objExists(new) and cmds.objExists(root),
          cmds.undoInfo(q=True, undoName=True))
    back_to_root()
    b_dup.click()
    pump()
    new = panel._root
    check("Duplicate Group: the same surfaces and every layer, grown, open in the panel",
          new != root and panel.layer_list.count() == nl and surf_rows() == rows and
          len(ns["sc_parts"](new)) == len(ns["sc_parts"](root)), panel.status.text())
    cmds.undo()
    pump()
    check("one Ctrl+Z takes the duplicate away", not cmds.objExists(new) and cmds.objExists(root),
          cmds.undoInfo(q=True, undoName=True))
    back_to_root()
    panel.surf_list.item(1).setSelected(True)
    panel.add_surfaces()
    pump()
    check("picking it in the list and Add Selected puts it back",
          panel.surf_list.count() == 1 and low_points() > 0, panel.status.text())


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
