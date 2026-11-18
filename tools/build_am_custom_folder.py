"""Build the AM_Custom Maya folder: copy its 'prefs' and 'scripts' into a Maya.

    mayapy tools/build_am_custom_folder.py [--src C:/Users/andre/Documents/maya/2024] [--out <folder>]

The user (2026-11-18): "upload it to drive > download on my work PC > set
it up in Maya ... just a folder I can drag and drop into prefs", kept with
the students' CUSTOM PREFS, one "PREFS - Andy - <month year>" folder each
(the May 2022 one is laid out the same way). Reads this machine's
AM_Custom shelf (Maya 2024 prefs) and writes OUT (default: CUSTOM
PREFS/PREFS - Andy - <this month>) as:

  PREFS - Andy - November 2026/
    READ ME - copy prefs and scripts into Documents maya 20XX.txt
    prefs/
      shelves/shelf_AM_Custom.mel   (icons by file name, no machine paths)
      icons/                        (every icon the shelf uses)
    scripts/                        (the shelf's tools + UnlokToolbox.py)

On another PC, with Maya closed: copy 'prefs' and 'scripts' into
Documents/maya/<version>/ (merge, replace files). Maya finds icons in
prefs/icons by name; <version>/scripts is Maya's own user scripts folder
(cmds.internalVar(userScriptDir=True)), on its script and Python paths.
The UNLOK - Toolbox button runs the repo's UnlokToolbox.py where the repo
is (this machine), else the copy in scripts. Run again after an update.
tests/test_am_custom_folder.py checks a build in a throwaway MAYA_APP_DIR.
"""
import datetime
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = "C:/Users/andre/Documents/maya/2024"
STUDENT_PREFS = "G:/My Drive/UNLOK DRIVE/MENTORING/Students/RESOURCES/MAYA/CUSTOM PREFS"
OUT = os.path.join(STUDENT_PREFS, "PREFS - Andy - " + datetime.date.today().strftime("%B %Y"))
SHELF = "AM_Custom"
UNLOK_LABEL = "UNLOK - Toolbox"
SKIP_DIRS = {"__pycache__", "site-packages", "modelChecker-main", "osbTools-master"}  # (not used by the shelf)
SKIP_FILES = {"desktop.ini", "RS_Renamer.pyc"}  # (Python 3.7 bytecode: no Maya from 2023 on can load it)
README_NAME = "READ ME - copy prefs and scripts into Documents maya 20XX.txt"

UNLOK_COMMAND = '''import os, __main__
import maya.cmds as cmds
repo = r"%s"
p = repo if os.path.isfile(repo) else os.path.join(cmds.internalVar(userScriptDir=True), "UnlokToolbox.py")
if os.path.isfile(p):
    with open(p) as f:
        exec(compile(f.read(), p, "exec"), __main__.__dict__)
else:
    cmds.warning("Unlok Toolbox: no UnlokToolbox.py in " + os.path.dirname(p))
''' % (REPO.replace("\\", "/") + "/UnlokToolbox.py")

README = """AM_Custom shelf + Unlok Toolbox for Maya (%s)
==================================================

Install (or update) on any PC:

1. Close Maya (it rewrites shelves when it quits).
2. Copy BOTH folders in here, 'prefs' and 'scripts', into
       Documents/maya/<your Maya version>/      (e.g. Documents/maya/2023/)
   and say yes to merge folders / replace files.
3. Start Maya: the AM_Custom shelf is there with all its icons and tools.

What's inside:
    prefs/shelves/shelf_AM_Custom.mel   the shelf (replaces an AM_Custom shelf)
    prefs/icons/                        its icons
    scripts/                            its tools, and UnlokToolbox.py

To update only the Unlok Toolbox later, copy a newer scripts/UnlokToolbox.py
over the old one (the UNLOK - Toolbox button runs that file).

Not included: RS Renamer's RS_Renamer.pyc (built for Python 3.7, it can't
load in Maya 2023 or later) and the renamer_tool button's script (not on
the PC this was made on), so those two buttons won't open.

Made by tools/build_am_custom_folder.py in the UnlokMayaToolbox repo.
"""


def mel_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def copy_tree(src, dst):
    n = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(root, src)
        out = dst if rel == "." else os.path.join(dst, rel)
        if not os.path.isdir(out):
            os.makedirs(out)
        for f in files:
            if f in SKIP_FILES:
                continue
            shutil.copy2(os.path.join(root, f), os.path.join(out, f))
            n += 1
    return n


def main(argv):
    src, out = SRC, OUT
    if "--src" in argv:
        src = argv[argv.index("--src") + 1]
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    prefs, scripts = os.path.join(out, "prefs"), os.path.join(out, "scripts")
    for d in (prefs, scripts):
        if os.path.isdir(d):
            shutil.rmtree(d)
    for d in (os.path.join(prefs, "shelves"), os.path.join(prefs, "icons"), scripts):
        os.makedirs(d)
    for old in os.listdir(out):  # an older read-me
        if old.startswith("READ ME") and old != README_NAME:
            os.remove(os.path.join(out, old))

    # scripts: <ver>/scripts, then <ver>/prefs/scripts over it (Maya reads both), then the toolbox
    n = 0
    for s in (os.path.join(src, "scripts"), os.path.join(src, "prefs", "scripts")):
        if os.path.isdir(s):
            n += copy_tree(s, scripts)
    shutil.copy2(os.path.join(REPO, "UnlokToolbox.py"), os.path.join(scripts, "UnlokToolbox.py"))
    print("scripts: %d files (+ UnlokToolbox.py)" % n)

    # shelf: icons by file name (found in prefs/icons on any PC), the toolbox button portable
    with open(os.path.join(src, "prefs", "shelves", "shelf_%s.mel" % SHELF), "rb") as f:
        text = f.read().decode("utf-8", "replace")
    look = [os.path.join(src, "prefs", "icons", "tabIcons"), os.path.join(src, "prefs", "icons")]
    missing, icons = [], set()

    def icon(m):
        flag, path = m.group(1), m.group(2)
        if "/" not in path and "\\" not in path:
            return m.group(0)  # one of Maya's own (pythonFamily.png)
        name = os.path.basename(path.replace("\\", "/"))
        for cand in [path] + [os.path.join(d, name) for d in look]:
            if os.path.isfile(cand):
                shutil.copy2(cand, os.path.join(prefs, "icons", name))
                icons.add(name)
                break
        else:
            missing.append(path)
        return '%s "%s"' % (flag, name)

    text = re.sub(r'(-image1?) "([^"]*)"', icon, text)
    blocks = re.split(r"(?m)^(?=    shelfButton\b)", text)
    done = False
    for i, b in enumerate(blocks):
        if '-label "%s"' % UNLOK_LABEL in b:
            blocks[i] = re.sub(r'-command "(?:[^"\\]|\\.)*"', lambda _m: "-command " + mel_str(UNLOK_COMMAND), b,
                               count=1)
            done = True
    text = "".join(blocks)
    with open(os.path.join(prefs, "shelves", "shelf_%s.mel" % SHELF), "wb") as f:
        f.write(text.encode("utf-8"))
    print("shelf: %d buttons, %d icons%s; toolbox button %s" % (
        len(blocks) - 1, len(icons), (", MISSING: %s" % missing) if missing else "", "portable" if done else
        "NOT FOUND"))
    with open(os.path.join(out, README_NAME), "w") as f:
        f.write(README % datetime.date.today().strftime("%B %Y"))
    print("built: %s" % out)
    return 0 if done and not missing else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
