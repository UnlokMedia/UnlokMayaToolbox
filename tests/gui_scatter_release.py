"""GUI test: the Scatter panel lets go of a group. Two groups on two planes, the second baked; picking a plain
mesh keeps the group (flagged NOT SELECTED, for Add Selected), picking the baked one, empty space or Release
lets it go, and picking a group's box picks it again.

    maya.exe -script tests/run_gui_scatter_release.mel   (UNLOK_TEST_DIR set to this folder)

Results: $UNLOK_TEST_OUT (default tests/_out/scatter_release)/results.json."""
import json
import os
import traceback

import maya.cmds as cmds

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "scatter_release")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append({"name": name, "ok": bool(cond), "detail": str(detail)})
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))


def pump(n=5):
    app = QtWidgets.QApplication.instance()
    for _ in range(n):
        app.processEvents()


def main():
    ns = {"__name__": "__main__", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    import __main__
    cmds.file(new=True, force=True)
    ns["show"]()
    pump(20)
    window = getattr(__main__, ns["REGISTRY_KEY"])["window"]
    panel = [p for p in window.panels() if p.TOOL_NAME == "Scatter"][0]
    names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    window.tabs.setCurrentIndex(names.index("Modeling"))
    page = window.pages[names.index("Modeling")]
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Scatter"][0].click()
    pump(20)

    planes = []
    for i in range(3):
        p = cmds.polyPlane(w=30, h=30, sx=6, sy=6, ch=False, name="floor%d" % (i + 1))[0]
        cmds.move(i * 40, 0, 0, p)
        planes.append(cmds.ls(p, long=True)[0])
    q = ns["sc_quick_settings"]
    live = ns["create_scatter_group"]([planes[0]], "Leaves", q("Leaves"), select=False)["root"]
    other = ns["create_scatter_group"]([planes[1]], "Leaves", q("Leaves"), select=False)["root"]
    ns["bake_scatter"]([other])
    baked_part = [n for n in (cmds.listRelatives(other, allDescendents=True, type="transform", fullPath=True) or [])
                  if cmds.listRelatives(n, shapes=True)]
    check("the second group baked to meshes", not ns["is_scatter"](other) and baked_part,
          "%s %s" % (other, cmds.listRelatives(other, allDescendents=True, fullPath=True)))

    def pick(nodes, label):
        if nodes:
            cmds.select(nodes, replace=True)
        else:
            cmds.select(clear=True)
        panel._sync_from_selection()  # a scripted selection change sends no SelectionChanged event
        pump()
        return panel._root

    def banner():
        return panel.next_banner.text.text()

    def locked():
        return not panel.step_look.isEnabled() and not panel.step_layers.isEnabled()

    check("picking the group's box edits it", pick([ns["sc_box"](live)], "box") == live and not locked(),
          panel._root)
    check("Release shows while a group is edited", panel.release_btn.isVisible())
    check("no Continue editing while the group is selected", not panel.resume_btn.isVisible())

    check("picking a plain mesh keeps the group open (for Add Selected)", pick([planes[2]], "mesh") == live)
    check("... but locks its layers and settings", locked())
    check("... says the mesh wasn't made with Scatter", "wasn't made with Scatter" in banner() and
          "CAN'T EDIT" in panel.next_banner.tag.text(), banner())
    check("... and covers the whole panel with CAN'T EDIT", panel.block.isVisible() and
          panel.block.geometry() == panel.rect() and "wasn't made with Scatter" in panel.block_title.text(),
          panel.block_title.text())
    window.grab().save(os.path.join(OUT, "block_plain.png"))
    panel.block_resume.click()
    pump()
    check("Edit previous group unlocks it, selection left alone, cover gone", not locked() and
          panel._root == live and not panel.block.isVisible() and
          cmds.ls(selection=True, long=True) == [planes[2]], banner())
    panel._update_states()
    pump()
    check("... and doesn't come back while the selection is the same", not panel.block.isVisible())

    check("picking baked scatter keeps the group open but locked", pick(baked_part[:1], "baked") == live and
          locked())
    check("... and the cover says it's baked", panel.block.isVisible() and
          "baked scatter" in panel.block_title.text(), panel.block_title.text())
    window.grab().save(os.path.join(OUT, "block_baked.png"))
    panel.block_dismiss.click()
    pump()
    check("Dismiss lets the group go and keeps the Maya selection", panel._root is None and
          not panel.block.isVisible() and cmds.ls(selection=True, long=True) == baked_part[:1],
          cmds.ls(selection=True, long=True))
    pick([ns["sc_box"](live)], "box")
    pick([planes[2]], "mesh")
    panel.block_dismiss.click()
    pump()
    check("after Dismiss on a plain mesh, New Scatter Group is offered on it", panel._root is None and
          "New Scatter Group" in banner(), banner())
    pick([ns["sc_box"](live)], "box")
    pick(baked_part[:1], "baked")

    cmds.select(planes[2] + ".f[0:3]", replace=True)
    panel._sync_from_selection()
    pump()
    check("picked faces don't lock (Use Picked Area needs them)", panel._root == live and not locked(), banner())

    check("clicking empty space lets it go", pick([], "none") is None and not locked(), panel._root)
    check("... and Release hides", not panel.release_btn.isVisible())
    check("picking baked scatter with nothing open warns", pick(baked_part[:1], "baked") is None and
          "baked scatter" in banner(), banner())
    check("... and offers Continue editing the last group", panel.resume_btn.isVisible() and
          "scatteredObjects0001_GRP" in panel.resume_btn.text(), panel.resume_btn.text())
    panel.resume()
    pump()
    check("Continue editing brings the last group back, unlocked", panel._root == live and not locked())
    window.grab().save(os.path.join(OUT, "continued.png"))

    pick(baked_part[:1], "baked")
    window.grab().save(os.path.join(OUT, "locked_baked.png"))
    pick([ns["sc_box"](live)], "box")
    panel.release()
    pump()
    check("Release lets it go", panel._root is None and "No scatter group" in panel.group_label.text(),
          panel.group_label.text())
    check("... and stays let go with a plain mesh picked", pick([planes[2]], "mesh") is None and not locked())


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


if __name__ == "gui_scatter_release":
    cmds.evalDeferred(run, lowestPriority=True)
