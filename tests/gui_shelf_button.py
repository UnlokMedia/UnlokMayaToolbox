"""GUI check for shelf/install_shelf_button.py: run inside an interactive Maya
whose prefs are a throwaway folder (MAYA_APP_DIR), never the user's own.

Makes an AM_Custom shelf holding a button with a pasted copy of the toolbox
(what the user had), runs the installer twice (pointed at this checkout),
then checks: one button with our label, in the old button's place, icon
copied into prefs icons/tabIcons, shelf file saved with it and backed up to
.bak, and clicking it (running its command) opens the toolbox.

    set MAYA_APP_DIR=<empty folder>
    set MAYA_DISABLE_CER=1
    set UNLOK_TEST_QUIT=1
    set UNLOK_TEST_DIR=<this folder>
    maya.exe -script <this folder>/run_gui_shelf_button.mel

Writes results.json to $UNLOK_TEST_OUT (default tests/_out/shelf_button).
"""

import json
import os
import traceback

import maya.cmds as cmds
import maya.mel as mel

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
REPO = os.path.dirname(HERE).replace("\\", "/")
INSTALLER = os.path.join(REPO, "shelf", "install_shelf_button.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "shelf_button")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append({"name": name, "ok": bool(cond), "detail": str(detail)})
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))


def buttons(shelf):
    out = []
    for b in cmds.shelfLayout(shelf, query=True, childArray=True) or []:
        if cmds.objectTypeUI(b) == "shelfButton":
            out.append((b, cmds.shelfButton(b, query=True, label=True)))
    return out


def run_installer():
    with open(INSTALLER) as f:
        src = f.read()
    marker = 'REPO = r"G:/My Drive/UNLOK DRIVE/Projects/UnlokMayaToolbox/UnlokMayaToolbox"'
    assert marker in src
    src = src.replace(marker, "REPO = %r" % REPO)
    exec(compile(src, INSTALLER, "exec"), {"__name__": "install_shelf_button"})


def main():
    prefs = cmds.internalVar(userPrefDir=True)
    check("prefs are a throwaway folder (MAYA_APP_DIR)",
          os.environ.get("MAYA_APP_DIR") and os.path.normcase(os.path.abspath(prefs)).startswith(
              os.path.normcase(os.path.abspath(os.environ["MAYA_APP_DIR"]))), prefs)
    if not RESULTS[-1]["ok"]:
        return
    top = mel.eval("$_unlokTmp = $gShelfTopLevel")
    if not cmds.shelfLayout("AM_Custom", exists=True):
        mel.eval('addNewShelfTab "AM_Custom"')
    shelf = top + "|AM_Custom"
    for b in cmds.shelfLayout(shelf, query=True, childArray=True) or []:
        cmds.deleteUI(b)
    cmds.shelfButton(parent=shelf, label="MODEL - A", image="pythonFamily.png", command="pass",
                     sourceType="python")
    cmds.shelfButton(parent=shelf, label='"""\nUnlok Maya Toolbox\n...', image="pythonFamily.png",
                     command='"""\nUnlok Maya Toolbox\n==================\n"""\nprint("old copy")\n',
                     sourceType="python")
    cmds.shelfButton(parent=shelf, label="CAM - B", image="pythonFamily.png", command="pass",
                     sourceType="python")
    cmds.saveAllShelves(top)
    shelf_file = os.path.join(prefs, "shelves", "shelf_AM_Custom.mel")
    check("test shelf saved", os.path.isfile(shelf_file), shelf_file)

    run_installer()
    run_installer()  # again: still one button
    labels = [label for _, label in buttons(shelf)]
    check("old pasted button replaced in place, ours once",
          labels == ["MODEL - A", "UNLOK - Toolbox", "CAM - B"], labels)
    ours = [b for b, label in buttons(shelf) if label == "UNLOK - Toolbox"][0]
    icon = cmds.shelfButton(ours, query=True, image=True)
    check("icon copied into prefs icons/tabIcons",
          os.path.isfile(icon) and icon.replace("\\", "/").endswith("icons/tabIcons/TAB_UnlokToolbox_icon_128px.png"),
          icon)
    check("button is 104 x 34, icon only",
          (cmds.shelfButton(ours, query=True, width=True), cmds.shelfButton(ours, query=True, height=True),
           cmds.shelfButton(ours, query=True, style=True)) == (104, 34, "iconOnly"))
    with open(shelf_file) as f:
        saved = f.read()
    check("shelf file saved with the button, old copy gone",
          '"UNLOK - Toolbox"' in saved and "old copy" not in saved)
    check("shelf file backed up to .bak", os.path.isfile(shelf_file + ".bak"))

    cmd = cmds.shelfButton(ours, query=True, command=True)
    check("button runs UnlokToolbox.py from the repo folder", REPO + "/UnlokToolbox.py" in cmd)
    exec(compile(cmd, "<shelf button>", "exec"), {"__name__": "__main__"})
    for _ in range(6):
        QtWidgets.QApplication.instance().processEvents()
    import __main__
    name = getattr(__main__, "WINDOW_OBJECT_NAME", None)
    wins = [w for w in QtWidgets.QApplication.instance().topLevelWidgets()
            if name and w.objectName() == name and w.isVisible()]
    check("clicking it opens the toolbox (run in __main__, like a paste)", len(wins) == 1, name)
    for w in wins:
        w.close()


def run():
    try:
        main()
    except Exception:
        RESULTS.append({"name": "exception", "ok": False, "detail": traceback.format_exc()})
        traceback.print_exc()
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump({"maya": cmds.about(version=True), "checks": RESULTS}, f, indent=2)
    if os.environ.get("UNLOK_TEST_QUIT") == "1":
        cmds.quit(force=True)


cmds.evalDeferred(run, lowestPriority=True)
