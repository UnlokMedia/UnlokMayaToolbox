"""Headless check of the built AM_Custom prefs folder (mayapy).

    mayapy tests/test_am_custom_folder.py ["<built folder>"]

Copies the folder's 'prefs' and 'scripts' into a throwaway MAYA_APP_DIR
(never the real prefs), as the read-me says, starts Maya there and checks
what a work PC would get: every shelf icon is in prefs/icons (or one of
Maya's own), no machine paths left in the shelf, the shelf's Python tools
are found on Maya's path (found, not imported: some build their UI on
import, which kills a headless Maya), its MEL scripts are found, and the
UNLOK - Toolbox button runs the copy in scripts when the repo isn't there.
"""
import datetime
import os
import re
import shutil
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join("G:/My Drive/UNLOK DRIVE/MENTORING/Students/RESOURCES/MAYA/CUSTOM PREFS",
                       "PREFS - Andy - " + datetime.date.today().strftime("%B %Y"))
BUILT = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
TMP = tempfile.mkdtemp(prefix="am_custom_")
VER = "2024"
shutil.copytree(os.path.join(BUILT, "prefs"), os.path.join(TMP, VER, "prefs"))
shutil.copytree(os.path.join(BUILT, "scripts"), os.path.join(TMP, VER, "scripts"))
os.environ["MAYA_APP_DIR"] = TMP

from PySide2 import QtWidgets  # noqa: E402
APP = QtWidgets.QApplication(sys.argv)  # (the toolbox opens its window: a headless Qt app for it)
import maya.standalone  # noqa: E402
maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402
import maya.mel as mel  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def run():
    scripts = cmds.internalVar(userScriptDir=True)
    check("Maya reads the throwaway prefs", os.path.normpath(scripts).startswith(os.path.normpath(TMP)), scripts)
    shelf = os.path.join(TMP, VER, "prefs", "shelves", "shelf_AM_Custom.mel")
    text = open(shelf, "rb").read().decode("utf-8", "replace")
    images = re.findall(r'-image1? "([^"]*)"', text)
    icons = os.path.join(TMP, VER, "prefs", "icons")
    builtin = {"pythonFamily.png", "commandButton.png"}
    bad = [i for i in images if i not in builtin and not os.path.isfile(os.path.join(icons, i))]
    check("every shelf icon is in prefs/icons (or Maya's own)", images and not bad, "%d images; missing %s" % (
        len(images), bad))
    paths = re.findall(r'-image1? "([A-Za-z]:[^"]*)"', text)
    check("no machine paths in the icons", not paths, str(paths[:3]))
    import importlib.util
    failed = []
    for mod in ("dropToFloor", "GN_QuadFillHole", "ig_EzRename", "maya_fspy", "modelChecker", "lookdev_kit",
                "UnlokRenamer"):
        spec = importlib.util.find_spec(mod)
        if spec is None or not os.path.normpath(spec.origin or (list(spec.submodule_search_locations or [""])[0])
                                                ).startswith(os.path.normpath(TMP)):
            failed.append(mod)
    check("the shelf's Python tools are on Maya's path (from the copied scripts)", not failed, str(failed))
    missing = [m for m in ("Quick_rename_tool", "GN_AutomaticUVsByHardEdges")
               if "found in" not in mel.eval('whatIs "%s.mel"' % m) and not os.path.isfile(os.path.join(scripts,
                                                                                                     m + ".mel"))]
    check("the shelf's MEL scripts are there", not missing, str(missing))
    check("UnlokToolbox.py is in scripts", os.path.isfile(os.path.join(scripts, "UnlokToolbox.py")))
    m = re.search(r'-label "UNLOK - Toolbox".*?-command "((?:[^"\\]|\\.)*)"', text, re.S)
    cmd = m.group(1).encode("utf-8").decode("unicode_escape") if m else ""
    away = cmd.replace(re.search(r'repo = r"([^"]*)"', cmd).group(1), "Z:/no/repo/UnlokToolbox.py") if cmd else ""
    ran = {}
    try:
        ns = {"__name__": "__main__"}
        import __main__
        before = set(__main__.__dict__)
        exec(compile(away, "<shelf button>", "exec"), ns)
        ran["new"] = sorted(set(__main__.__dict__) - before)
        ran["file"] = ns.get("p", "")
    except Exception as exc:
        ran["error"] = repr(exc)
    check("the UNLOK - Toolbox button runs the scripts copy without the repo",
          "error" not in ran and "create_scatter_group" in ran.get("new", []) and
          os.path.normpath(ran.get("file", "")).startswith(os.path.normpath(TMP)), "ran %s" % ran.get("file", ran))


try:
    run()
except Exception:
    traceback.print_exc()
    RESULTS.append(("crashed", False, ""))
failed = [r for r in RESULTS if not r[1]]
print("\n%d checks, %d failed" % (len(RESULTS), len(failed)))
for name, _, detail in failed:
    print("FAILED: %s  %s" % (name, detail))
sys.stdout.flush()
maya.standalone.uninitialize()
shutil.rmtree(TMP, ignore_errors=True)
os._exit(1 if failed else 0)
