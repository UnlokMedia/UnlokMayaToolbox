"""GUI test for Rope Lashing: run inside an interactive Maya.

Opens the toolbox, drives the Rope Lashing panel (lash a post and a beam,
edit it live, undo / redo with the automatic re-tie, presets, a whole
frame) and saves close-ups of each rope style and of the panel.

Launch (Maya 2023+), with UNLOK_TEST_DIR set to this folder:

    maya.exe -script tests/run_gui_rope_lashing.mel

Outputs go to $UNLOK_TEST_OUT (default: tests/_out/rope_lashing).
"""

import json
import os
import traceback

import maya.cmds as cmds
import maya.api.OpenMaya as om

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "rope_lashing")
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


def log(name, r=0.15, h=3.0, move=(0, 0, 0), rot=(0, 0, 0)):
    node = cmds.polyCylinder(r=r, h=h, sx=32, sy=24, name=name, constructionHistory=False)[0]
    cmds.rotate(rot[0], rot[1], rot[2], node)
    cmds.move(move[0], move[1], move[2], node)
    return cmds.ls(node, long=True)[0]


def verts(node):
    shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
    sel = om.MSelectionList()
    sel.add(shape)
    return om.MFnMesh(sel.getDagPath(0)).numVertices


def frame_on(node, persp, direction=(1.0, 0.45, 1.4), dist=2.4):
    bb = cmds.exactWorldBoundingBox(node)
    c = [(bb[i] + bb[i + 3]) * 0.5 for i in range(3)]
    size = max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])
    ln = sum(v * v for v in direction) ** 0.5
    cmds.setAttr("persp.translate", *[c[i] + direction[i] / ln * size * dist for i in range(3)])
    cmds.viewLookAt("persp", position=c)
    cmds.select(clear=True)
    pump()


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    ns = {"__name__": "__main__", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    import __main__

    # --- opening the toolbox with logs selected must not lash or preview anything
    cmds.file(new=True, force=True)
    cmds.select(log("pre_a", move=(0, 1.5, 0)), log("pre_b", rot=(0, 0, 90), move=(0, 2.0, 0.3)))
    ns["show"]()
    pump(20)
    check("opening the toolbox with logs selected makes nothing", not ns["rope_previews"]() and
          not ns["ropes_in"](), "%d previews" % len(ns["rope_previews"]()))

    window = getattr(__main__, ns["REGISTRY_KEY"])["window"]
    panel = [p for p in window.panels() if p.TOOL_NAME == "Rope Lashing"][0]
    names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    window.tabs.setCurrentIndex(names.index("Modeling"))
    page = window.pages[names.index("Modeling")]
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Rope Lashing"][0].click()
    pump(20)
    check("Rope Lashing panel is in the Modeling tab", panel.isVisible())
    check("switching to Rope Lashing previews the selected logs", len(ns["rope_previews"]()) == 1)
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Log Noise"][0].click()
    pump(5)
    check("switching to another tool removes the preview", not ns["rope_previews"]())
    window.tabs.setCurrentIndex(names.index("UV"))
    pump(5)
    cmds.select(cmds.ls("pre_a", "pre_b", long=True))
    pump(20)
    check("selecting logs while another tab is open previews nothing", not ns["rope_previews"]())
    window.tabs.setCurrentIndex(names.index("Modeling"))
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Rope Lashing"][0].click()
    pump(20)

    cmds.file(new=True, force=True)
    view = cmds.getPanel(type="modelPanel")
    persp = [p for p in view if cmds.modelPanel(p, q=True, camera=True) == "persp"][0]
    cmds.setFocus(persp)
    cmds.modelEditor(persp, e=True, displayAppearance="smoothShaded", grid=False, headsUpDisplay=False,
                     cameras=False)
    cmds.setAttr("persp.focalLength", 50)

    post = log("post", move=(0, 1.5, 0))
    beam = log("beam", rot=(0, 0, 90), move=(0, 2.0, 0.3))
    cmds.select(post, beam)
    pump()
    panel._sync_from_selection()
    pump()
    previews = ns["rope_previews"]()
    check("selecting two logs shows a live preview", len(previews) == 1 and
          panel.next_banner.tag.text() == "PREVIEW" and "Square" in panel.next_banner.text.text(),
          "%d previews | %s" % (len(previews), panel.next_banner.text.text()))
    check("the preview leaves the selection alone", sorted(cmds.ls(selection=True, long=True)) == sorted([post, beam]),
          str(cmds.ls(selection=True)))
    check("the preview can't be picked or saved", previews and
          cmds.getAttr(previews[0] + ".overrideDisplayType") == 2)
    for i, kind in enumerate(("Diagonal", "Bands", "Square")):
        panel.f["lashing"].buttons[kind].click()
        panel._apply_pending()
        pump()
        shown = [cmds.getAttr(x + "." + ns["ROPE_PREVIEW_ATTR"]) for x in ns["rope_previews"]()]
        check("clicking %s re-draws the preview" % kind, shown == [kind], str(shown))
        frame_on(ns["rope_previews"]()[0], persp)
        cmds.select(post, beam)
        snap("00_preview_%d_%s.png" % (i, kind))
    panel.f["lashing"].buttons["Auto"].click()
    panel._apply_pending()
    pump()
    window.grab().save(os.path.join(OUT, "00_panel_preview.png"))

    # --- the preview stays on its logs when they're deselected
    cmds.select(clear=True)
    panel._sync_from_selection()
    pump()
    check("deselecting keeps the preview", len(ns["rope_previews"]()) == 1 and
          panel.next_banner.tag.text() == "PREVIEW" and panel.lash_btn.text() == "Lash Preview",
          "%s | %s" % (panel.lash_btn.text(), panel.next_banner.text.text()))
    n_twisted = verts(ns["rope_previews"]()[0])
    panel.f["style"].buttons["3 strands"].click()
    panel._apply_pending()
    pump()
    check("with nothing selected, changes still update the preview",
          verts(ns["rope_previews"]()[0]) != n_twisted)
    frame_on(ns["rope_previews"]()[0], persp)
    snap("00_preview_deselected_3strands.png")
    panel.f["style"].buttons["Twisted"].click()
    panel._apply_pending()
    pump()
    n_preview = verts(ns["rope_previews"]()[0])

    panel.lash()  # nothing selected: keeps the preview
    pump()
    ropes = ns["ropes_in"]()
    check("Lash Selected ties one lashing", len(ropes) == 1, panel.status.text())
    check("status reports the lashing", "Tied 1 lashing" in panel.status.text(), panel.status.text())
    rope = ropes[0]
    panel._sync_from_selection()
    check("the new lashing is selected and being edited", panel.step_rope.state == "current" and
          panel.next_banner.tag.text() == "EDITING", panel.next_banner.text.text())
    check("Lash keeps exactly what the preview showed", verts(rope) == n_preview and not ns["rope_previews"](),
          "%d vs %d verts" % (verts(rope), n_preview))
    frame_on(rope, persp)
    snap("01_square_twisted.png")
    frame_on(rope, persp, direction=(0.001, 0.001, 1.0))
    snap("02_square_front.png")

    # --- live edit through the panel's own fields
    cmds.select(rope)
    pump()
    n0 = verts(rope)
    panel.f["style"].setValue("3 strands")
    panel._queue("style")
    panel._apply_pending()
    pump()
    check("style edit re-ties live", ns["rope_data"](rope)["style"] == "3 strands" and verts(rope) != n0,
          panel.status.text())
    frame_on(rope, persp)
    snap("03_square_3strands.png")
    window.grab().save(os.path.join(OUT, "04_panel.png"))
    cmds.select(rope)
    panel.f["thickness"].setValue(0.16)
    panel._queue("thickness")
    panel._apply_pending()
    pump()
    check("thickness edit", abs(ns["rope_data"](rope)["thickness"] - 0.16) < 1e-6, panel.status.text())

    # --- undo / redo: the redo re-ties from the stored settings
    cmds.select(post, beam)
    panel.f["style"].setValue("Smooth tube")
    panel.lash()
    pump()
    second = [r for r in ns["ropes_in"]() if r != rope][0]
    n1 = verts(second)
    cmds.undo()
    pump()
    check("Ctrl+Z removes the new lashing", not cmds.objExists(second))
    cmds.redo()
    pump(10)
    panel._rebuild_stale()  # what the Redo scriptJob's timer runs
    pump()
    check("redo comes back fully tied", cmds.objExists(second) and verts(second) == n1,
          "%d vs %d" % (verts(second) if cmds.objExists(second) else -1, n1))
    cmds.delete(second)

    # --- presets
    var = ns["ROPE_PRESET_VAR"]
    old = cmds.optionVar(q=var) if cmds.optionVar(exists=var) else None
    try:
        ns["rope_save_preset"]("gui test", panel._settings())
        panel._fill_presets("gui test")
        check("saved preset shows in the list", panel.preset_combo.currentText() == "gui test")
        i = panel.preset_combo.findText("Background (light)")
        panel.preset_combo.setCurrentIndex(i)
        cmds.select(rope)
        panel.load_preset()
        pump()
        check("loading a preset onto a selected lashing re-ties it",
              ns["rope_data"](rope)["style"] == "Smooth tube" and not ns["rope_data"](rope)["hitches"],
              panel.status.text())
    finally:
        if old is None:
            cmds.optionVar(remove=var)
        else:
            cmds.optionVar(stringValue=(var, old))

    # --- a frame of logs, all styles side by side
    cmds.file(new=True, force=True)
    logs = []
    for i, (x, z) in enumerate(((0, 0), (2, 0), (0, 2), (2, 2))):
        logs.append(log("post%d" % i, r=0.14, move=(x, 1.5, z)))
    for i, (pos, rot) in enumerate((((1, 2.5, 0.28), (0, 0, 90)), ((1, 2.5, 2.28), (0, 0, 90)),
                                    ((0.28, 2.0, 1), (90, 0, 0)), ((2.28, 2.0, 1), (90, 0, 0)))):
        logs.append(log("beam%d" % i, r=0.14, h=2.6, move=pos, rot=rot))
    ns["add_log_noise"](logs, {"bump": 0.05, "bend": 0.01}, seeds={x: i + 3 for i, x in enumerate(logs)})
    cmds.select(logs)
    panel.f["style"].setValue("Twisted")
    panel.f["thickness"].setValue(0.1)
    panel.f["hitches"].setValue(True)
    panel.lash()
    pump()
    made = ns["ropes_in"]()
    check("a whole frame: one lashing per touching pair", len(made) == 8, panel.status.text())
    cmds.setAttr("persp.translate", 5.0, 4.0, 6.0)
    cmds.viewLookAt("persp", position=(1, 2.1, 1))
    cmds.select(clear=True)
    pump()
    snap("05_frame.png")
    frame_on(made[0], persp)
    snap("06_frame_closeup.png")

    cmds.select(logs[0], logs[4])
    panel.live.setValue(False)
    panel._sync_from_selection()
    check("Live preview off: no preview", not ns["rope_previews"]() and panel.next_banner.tag.text() == "NEXT")
    panel.preview_selected()
    check("Preview Selected works with live preview off", len(ns["rope_previews"]()) == 1)
    panel.live.setValue(True)
    cmds.select(clear=True)
    panel._sync_from_selection()
    check("the preview survives deselecting", len(ns["rope_previews"]()) == 1)
    panel.clear_preview()
    check("Clear Preview removes it", not ns["rope_previews"]() and panel.next_banner.tag.text() == "NEXT")
    panel.lash()
    check("no selection gives a warning", "Select" in panel.status.text(), panel.status.text())

    # --- Bake with nothing selected: the preview plus every lashing, in one Ctrl+Z
    def baked():
        return [s for s in cmds.ls(type="mesh", long=True) or []
                if cmds.attributeQuery(ns["ROPE_BAKED"], node=s, exists=True)]
    cmds.select(logs[1], logs[4])
    panel._sync_from_selection()
    cmds.select(clear=True)
    panel._sync_from_selection()
    check("a preview is showing with nothing selected", len(ns["rope_previews"]()) == 1)
    panel.bake()
    pump()
    check("Bake with nothing selected bakes the preview and every lashing",
          not ns["rope_previews"]() and not ns["ropes_in"]() and len(baked()) == 9,
          "%d baked | %s" % (len(baked()), panel.status.text()))
    cmds.undo()
    pump()
    check("one Ctrl+Z undoes the whole bake", len(ns["ropes_in"]()) == 8 and not baked(),
          "%d lashings, %d baked" % (len(ns["ropes_in"]()), len(baked())))


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
