"""Headless tests for the freeze / scene-safety guards (mayapy).

    mayapy tests/test_guards.py

Junk UVs (every face its own shell, as un-UV'd imports often are) used to make
Check UVs and Plan grind for many minutes with no way out. Now: junk is
flagged cheaply, Plan only lays out meshes that are ready, every heavy step
can be cancelled, and a cancelled Apply / Bevel Resolve / Log Noise rolls
back without touching the user's previous undo step.
"""

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "guards_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def cancel_on(word, tb):
    """A progress callback that presses Esc as soon as `word` shows up."""
    def cb(fraction, text):
        if word in text:
            raise tb["Cancelled"](word)
    return cb


def marker():
    """A user action in its own undo step, to prove cancels don't undo it."""
    cmds.undoInfo(openChunk=True, chunkName="user action")
    loc = cmds.spaceLocator(name="userMarker")[0]
    cmds.undoInfo(closeChunk=True)
    return loc


def run():
    tb = ns["load_toolbox"]()
    cmds.loadPlugin("Unfold3D", quiet=True)
    root, kinds = ns["build_building"]()
    junk = []
    for i in range(2):
        p = cmds.polyPlane(w=4, h=4, sx=100, sy=100, name="woodBrown_C_junk%04d_GEP" % (i + 1))[0]
        cmds.polyForceUV(p, unitize=True)
        cmds.polyMapCut(p + ".e[*]", constructionHistory=False)  # every face its own shell
        junk.append(cmds.ls(cmds.parent(p, root + "|westWing_GRP")[0], long=True)[0])
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    meshes = asset.meshes()[0]

    # --- junk is flagged cheaply
    t0 = time.time()
    flags = {m: tb["oversplit"](m) for m in meshes}
    check("junk / over-split UVs are flagged, quickly", all(flags[j] for j in junk) and
          sum(1 for v in flags.values() if v) == 2, "%.2fs, %s" % (time.time() - t0, flags[junk[0]]))
    t0 = time.time()
    scores = {m: tb["uv_quality"](m)[0] for m in meshes}
    dt = time.time() - t0
    check("Check UVs is quick even with 20,000 junk shells", dt < 10.0 and all(scores[j] < 0.85 for j in junk),
          "%.1fs for %d meshes" % (dt, len(meshes)))

    # --- Plan leaves out what isn't ready
    t0 = time.time()
    col = tb["collect_shells"](asset)
    dt = time.time() - t0
    nr = col["not_ready"]
    stretched = [m for m, k in kinds.items() if k == "stretched"]
    check("Plan reads only ready meshes: junk and un-UV'd ones are left out (and listed)",
          all(j in nr and nr[j].startswith("over-split") for j in junk) and all(m in nr for m in stretched) and
          not any(sh.mesh in nr for g in col["groups"] for sh in g["shells"]),
          "%.2fs, %d left out, e.g. %s" % (dt, len(nr), nr[stretched[0]]))
    plan = tb["make_plan"](col, dict(tb["LAYOUT_DEFAULTS"], texel_density=128.0, map_size="2048",
                                     mode="Fit to tiles"))
    check("Fit to tiles on the ready meshes finishes", plan["placements"], "%d placed" % len(plan["placements"]))

    # --- every heavy step can be cancelled
    pr = tb["Progress"]("Plan", [("read", 1)], cancel_on("Reading", tb))
    try:
        with pr:
            pr.stage("read", len(meshes), "Reading UV shells")
            tb["collect_shells"](asset, progress=pr)
        ok = False
    except tb["Cancelled"]:
        ok = True
    check("Esc stops Plan while it reads shells", ok)
    pr = tb["Progress"]("Plan", [("fit", 1)], cancel_on("trying", tb))
    try:
        with pr:
            pr.stage("fit", 46, "Finding the density")
            tb["make_plan"](col, dict(tb["LAYOUT_DEFAULTS"], mode="Fit to tiles"), progress=pr)
        ok = False
    except tb["Cancelled"]:
        ok = True
    check("Esc stops Fit to tiles", ok)

    # --- Apply: Esc rolls back fully, and never undoes the user's previous step
    tb["run_auto_uv"](asset)
    col = tb["collect_shells"](asset)
    plan = tb["make_plan"](col, dict(tb["LAYOUT_DEFAULTS"], texel_density=128.0, map_size="2048"))
    probe = [sh.mesh for g in col["groups"] for sh in g["shells"]][0]
    before = cmds.polyEditUV(probe + ".map[*]", query=True)
    loc = marker()
    pr = tb["Progress"]("Apply", [("write", 1)], cancel_on("Writing UVs", tb))
    try:
        with pr:
            tb["apply_layout"](asset, col, plan, progress=pr)
        ok = False
    except tb["Cancelled"]:
        ok = True
    check("Esc during Apply rolls back everything it wrote", ok and
          cmds.polyEditUV(probe + ".map[*]", query=True) == before and not asset.tool_members("laidout"))
    check("...and doesn't undo the user's previous action", cmds.objExists(loc))
    cmds.delete(loc)

    # --- Validate and the hand-off sheet don't grind on junk
    tb["apply_layout"](asset, col, plan)
    cmds.polyForceUV(junk[0], unitize=True)  # Auto UV fixed the junk: break one again
    cmds.polyMapCut(junk[0] + ".e[*]", constructionHistory=False)
    t0 = time.time()
    res = tb["validate_layout"](asset)
    dt = time.time() - t0
    check("Validate reports junk meshes instead of checking 20,000 shells", dt < 20.0 and
          junk[0] in set(it["mesh"] for it in res["items"]["oversplit"]),
          "%.1fs, %d junk" % (dt, len(res["items"]["oversplit"])))
    t0 = time.time()
    img = tb["render_handoff_sheet"](asset, px_per_tile=128)
    check("the hand-off sheet skips junk meshes", not img.isNull() and time.time() - t0 < 20.0,
          "%.1fs" % (time.time() - t0))

    # --- pre-process reports progress and can be cancelled before it changes anything
    pr = tb["Progress"]("Pre-process", [("geo", 1), ("uvs", 1)], cancel_on("Checking geometry", tb))
    try:
        with pr:
            tb["preprocess"](meshes, progress=pr)
        ok = False
    except tb["Cancelled"]:
        ok = True
    check("Esc stops Pre-process", ok)

    # --- Bevel Resolver and Log Noise: Esc rolls back, previous step intact
    cyl = cmds.polyCylinder(r=0.15, h=2, sx=24, sy=20, name="log")[0]
    loc = marker()
    pr = tb["Progress"]("Log Noise", [("logs", 1)], cancel_on("Adding noise", tb))
    try:
        with pr:
            tb["add_log_noise"]([cmds.ls(cyl, long=True)[0]], progress=pr)
        ok = False
    except tb["Cancelled"]:
        ok = True
    check("Esc during Log Noise apply changes nothing and keeps the previous step",
          ok and cmds.objExists(loc) and not tb["has_log_noise"](cmds.ls(cyl, long=True)[0]))
    box = cmds.polyCube(sx=3, sy=3, sz=3, name="bevelBox")[0]
    cmds.polyBevel3(box + ".e[0]", chamfer=False, segments=2, offset=0.1)
    faces_before = cmds.polyEvaluate(box, face=True)
    pr = tb["Progress"]("Bevel", [("resolve", 1)], cancel_on("Resolving", tb))
    try:
        with pr:
            tb["resolve_bevel_ngons"]({cmds.ls(box, long=True)[0]: None}, progress=pr)
        ok = False
    except tb["Cancelled"]:
        ok = True
    check("Esc during Bevel Resolver changes nothing and keeps the previous step",
          ok and cmds.objExists(loc) and cmds.polyEvaluate(box, face=True) == faces_before)
    check("undo_if_last only undoes its own step", not tb["undo_if_last"]("some other step") and cmds.objExists(loc))


try:
    run()
except Exception:
    traceback.print_exc()
    RESULTS.append(("exception", False, ""))
finally:
    failed = [r for r in RESULTS if not r[1]]
    print("\n%d passed, %d failed" % (len(RESULTS) - len(failed), len(failed)))
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(1 if failed else 0)
