"""Headless tests for the embedded Reframe (mayapy).

    mayapy tests/test_reframe_embed.py

The embedded copy is up to date with the MayaReframeTool repo (when it's
next to this one); nothing of it is imported until reframe_package() runs;
it then serves every module from memory, a re-paste replaces it cleanly
(one finder), the numpy-free camera solver round-trips a known camera, and
the scene state loads and saves on its network node.
"""

import os
import random
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
EMBED = os.path.join(os.path.dirname(HERE), "tools", "embed_reframe.py")
REFRAME_REPO = os.path.normpath(os.path.join(HERE, "..", "..", "..", "MayaReframeTool"))

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def load_toolbox():
    ns = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    return ns


def bundle_finders():
    return [f for f in sys.meta_path if getattr(f, "_reframe_bundle", False)]


def main():
    if os.path.isdir(REFRAME_REPO):
        sys.path.insert(0, os.path.dirname(EMBED))
        import embed_reframe
        sys.path.pop(0)
        mods = embed_reframe.collect_modules(REFRAME_REPO)
        tb = load_toolbox()
        check("embedded Reframe matches the MayaReframeTool package (tools/embed_reframe.py)",
              tb["_REFRAME_SOURCES"] == mods, "%d vs %d modules" % (len(tb["_REFRAME_SOURCES"]), len(mods)))
    else:
        print("(MayaReframeTool not found at %s: up-to-date check skipped)" % REFRAME_REPO)
        tb = load_toolbox()

    srcs = tb["_REFRAME_SOURCES"]
    check("16 modules embedded, version %s" % tb["REFRAME_VERSION"], len(srcs) >= 16 and tb["REFRAME_VERSION"])
    bad = []
    for name, (_, source) in srcs.items():
        try:
            compile(source, name, "exec")
        except SyntaxError as exc:
            bad.append("%s: %s" % (name, exc))
    check("every embedded module compiles", not bad, bad)
    check("loading the toolbox imports nothing of Reframe", "reframe" not in sys.modules)

    rf = tb["reframe_package"]()
    import reframe.core.camera_solver as cs
    check("modules come from the toolbox's in-memory importer",
          getattr(cs.__spec__.loader, "_reframe_bundle", False) and sys.modules["reframe"] is rf)
    check("a second call reuses it", tb["reframe_package"]() is rf)
    tb2 = load_toolbox()  # a re-paste
    rf2 = tb2["reframe_package"]()
    check("a re-paste replaces the copy, one finder left", rf2 is not rf and len(bundle_finders()) == 1,
          len(bundle_finders()))

    from reframe.core import camera_solver as cs
    rng = random.Random(2)
    image = (1920, 1080)
    truth = cs.CameraParams(0.2, -0.1, 0.02, (3, 2, 25), 1500)
    pts = [(rng.uniform(-8, 8), rng.uniform(0, 12), rng.uniform(-20, 0)) for _ in range(9)]
    uv, _ = cs.project(truth, pts, image)
    res = cs.solve(pts, uv, image)
    check("the solver finds a known camera without numpy", res.success and abs(res.camera.focal_px - 1500) < 1.0,
          res)

    cmds.file(new=True, force=True)
    from reframe.core import state as st
    state = st.load()
    st.save(state)
    check("scene state saves to its network node and loads back",
          cmds.objExists(st.NODE_NAME) and st.load().to_json() == state.to_json())

    for name in [n for n in srcs if n.startswith("reframe.ui")]:
        try:
            __import__(name)
            ok = True
        except Exception:
            ok = traceback.format_exc()
        check("imports %s" % name, ok is True, ok)

    print("")
    failed = [r for r in RESULTS if not r[1]]
    print("%d checks, %d failed" % (len(RESULTS), len(failed)))
    for r in failed:
        print("  FAIL", r[0], r[2])
    return not failed


if __name__ == "__main__":
    ok = False
    try:
        ok = main()
    except Exception:
        traceback.print_exc()
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(0 if ok else 1)
