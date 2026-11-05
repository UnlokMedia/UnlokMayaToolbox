"""Put an Unlok Toolbox button on the AM_Custom shelf (run once, in Maya).

Paste this into the Script Editor (Python tab) and run it, with this repo
on the machine. It:

1. copies TAB_UnlokToolbox_icon_128px.png into your prefs icons folder
   (icons/tabIcons, where the other AM_Custom tab icons live);
2. adds a 104 x 34 icon button to the AM_Custom shelf (making the shelf if
   there isn't one). Running it again replaces the button. An older button
   holding a pasted copy of the toolbox ("Unlok Tools", python icon) is
   replaced in its place;
3. copies shelf_AM_Custom.mel to shelf_AM_Custom.mel.bak, then saves the
   shelves.

The button runs UnlokToolbox.py from TOOLBOX below each time it's clicked,
so it always opens the toolbox as it is in that folder (no re-install after
an update). The toolbox itself still works by pasting, for machines without
the repo. This installer is not part of the paste.
"""
import os
import shutil

import maya.cmds as cmds
import maya.mel as mel

# Edit these if the repo lives somewhere else.
REPO = r"G:/My Drive/UNLOK DRIVE/Projects/UnlokMayaToolbox/UnlokMayaToolbox"
TOOLBOX = REPO + "/UnlokToolbox.py"
ICON_SRC = REPO + "/shelf/TAB_UnlokToolbox_icon_128px.png"
SHELF = "AM_Custom"
LABEL = "UNLOK - Toolbox"

COMMAND = '''import os, __main__
import maya.cmds as cmds
p = r"%s"
if os.path.isfile(p):
    with open(p) as f:
        exec(compile(f.read(), p, "exec"), __main__.__dict__)
else:
    cmds.warning("Unlok Toolbox: no file at " + p)
''' % TOOLBOX


def _icon():
    folder = os.path.join(cmds.internalVar(userBitmapsDir=True), "tabIcons")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    dst = os.path.join(folder, os.path.basename(ICON_SRC)).replace("\\", "/")
    shutil.copyfile(ICON_SRC, dst)
    return dst


def _shelf():
    top = mel.eval("$_unlokTmp = $gShelfTopLevel")
    if not cmds.shelfLayout(SHELF, exists=True):
        mel.eval('addNewShelfTab "%s"' % SHELF)
    return top, top + "|" + SHELF


def _old_buttons(shelf):
    """(our button, a pasted toolbox copy) already on the shelf."""
    found = []
    for b in cmds.shelfLayout(shelf, query=True, childArray=True) or []:
        if cmds.objectTypeUI(b) != "shelfButton":
            continue
        label = cmds.shelfButton(b, query=True, label=True) or ""
        cmd = cmds.shelfButton(b, query=True, command=True) or ""
        if label == LABEL or cmd.startswith('"""\nUnlok Maya Toolbox'):
            found.append(b)
    return found


def install():
    if not os.path.isfile(ICON_SRC):
        raise RuntimeError("No icon at %s: set REPO at the top of this script." % ICON_SRC)
    shelf_file = os.path.join(cmds.internalVar(userPrefDir=True), "shelves", "shelf_%s.mel" % SHELF)
    if os.path.isfile(shelf_file):
        shutil.copyfile(shelf_file, shelf_file + ".bak")
    icon = _icon()
    top, shelf = _shelf()
    old = _old_buttons(shelf)
    kids = cmds.shelfLayout(shelf, query=True, childArray=True) or []
    position = kids.index(old[0]) + 1 if old else None
    for b in old:
        cmds.deleteUI(b)
    button = cmds.shelfButton(
        parent=shelf, width=104, height=34, style="iconOnly", image=icon, image1=icon,
        label=LABEL, annotation="Unlok Toolbox: modelling, UVs, naming and camera tools",
        sourceType="python", command=COMMAND, flat=True, marginWidth=0, marginHeight=1)
    if position:
        cmds.shelfLayout(shelf, edit=True, position=(button.split("|")[-1], position))
    cmds.saveAllShelves(top)
    print("Unlok Toolbox button %s on the %s shelf (icon %s; replaced %d old)."
          % ("added", SHELF, icon, len(old)))


install()
