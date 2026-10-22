"""Headless tests for the speed-ups (mayapy).

    mayapy tests/test_speedups.py

- projection_clean: flat-sided pieces skip Unfold3D, curved / tilted ones don't
- Auto UV gives the same quality with the skip
- remembered scores: unchanged meshes aren't re-scored; an edit invalidates
- Scan: progress, and Esc rolls it back without touching the previous step
"""

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "speedups_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def project(m):
    cmds.polyAutoProjection(m + ".f[*]", planes=6, layoutMethod=0, layout=0, optimize=1, percentageSpace=0.2,
                            scaleMode=1, constructionHistory=False)


def run():
    tb = ns["load_toolbox"]()
    cmds.loadPlugin("Unfold3D", quiet=True)

    # --- projection_clean
    box = cmds.polyCube(w=4, h=2, d=0.3, sx=3, name="wallBox")[0]
    cyl = cmds.polyCylinder(r=0.3, h=2, sx=16, name="col")[0]
    tilt = cmds.polyPlane(w=2, h=2, sx=2, sy=2, name="tilted")[0]
    cmds.rotate(45, 0, 0, tilt)
    cmds.makeIdentity(tilt, apply=True)
    for m in (box, cyl, tilt):
        project(m)
    check("a projected box is clean (no unfold needed)", tb["projection_clean"](box))
    check("a projected cylinder isn't", not tb["projection_clean"](cyl))
    check("a piece tilted 45 deg to the projection planes isn't (it's squashed): it gets unfolded",
          not tb["projection_clean"](tilt))
    cmds.polyEditUV(tilt + ".map[*]", scaleU=2.0, pivotU=0.5, pivotV=0.5)  # squash it 2:1
    check("a squashed (stretched one way) projection isn't", not tb["projection_clean"](tilt))

    # --- Auto UV: walls skip Unfold3D, same quality as before
    cmds.file(new=True, force=True)
    root, kinds = ns["build_building"]()
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    first = []
    orig = tb["auto_unwrap"]

    def spy(meshes, **kw):
        kw["on_unfolded"] = lambda done: first.append(list(done)) if not first else None
        return orig(meshes, **kw)

    tb["auto_unwrap"] = spy
    res = tb["run_auto_uv"](asset)
    tb["auto_unwrap"] = orig
    walls = [m for m, k in kinds.items() if k == "stretched"]
    skipped = set(first[0]) if first else set()
    check("flat-sided pieces skip Unfold3D (all the walls)", set(walls) <= skipped,
          "%d skipped, %d walls" % (len(skipped), len(walls)))
    rows = res["rows"]
    check("...with the same result quality (nothing failed or flagged)",
          not any(r["action"] in ("failed", "check") for r in rows) and
          sum(1 for r in rows if r["action"] == "unwrapped") >= 30,
          "%d unwrapped" % sum(1 for r in rows if r["action"] == "unwrapped"))

    # --- remembered scores
    cache = {}
    t0 = time.time()
    a = tb["run_auto_uv"](asset, analyse_only=True, score_cache=cache)
    t_first = time.time() - t0
    t0 = time.time()
    b = tb["run_auto_uv"](asset, analyse_only=True, score_cache=cache)
    t_second = time.time() - t0
    n = len([r for r in a["rows"] if r["before"] is not None])
    check("unchanged meshes aren't scored again", a["cached"] == 0 and b["cached"] == n and
          [r["before"] for r in a["rows"]] == [r["before"] for r in b["rows"]],
          "%d meshes: %.2fs then %.2fs (%d reused)" % (n, t_first, t_second, b["cached"]))
    wall = walls[0]
    cmds.move(0, 0.5, 0, wall + ".vtx[0]", relative=True)
    c = tb["run_auto_uv"](asset, analyse_only=True, score_cache=cache)
    check("editing a mesh invalidates just its score", c["cached"] == n - 1, "%d reused" % c["cached"])
    d = tb["run_auto_uv"](asset, analyse_only=True, score_cache=cache, keep_score=0.5)
    check("changing the options invalidates the scores", d["cached"] == 0, "%d reused" % d["cached"])

    # the user's flow: Check UVs, mark a few Keep UVs / Hands off, then Auto UV
    tb["run_auto_uv"](asset, analyse_only=True, score_cache=cache)
    asset.set_uv_status([walls[1]], "keep")
    asset.set_uv_status([walls[2]], "handsoff")
    broken = [m for m, k in kinds.items() if k == "no uvs"][0]
    cmds.polyMapDel(broken + ".f[*]", constructionHistory=False)  # something left for Auto UV to do
    scored = []
    orig_q = tb["uv_quality"]

    def counting(xform, *a, **k):
        scored.append(xform)
        return orig_q(xform, *a, **k)

    tb["uv_quality"] = counting
    res = tb["run_auto_uv"](asset, score_cache=cache)
    tb["uv_quality"] = orig_q
    unwrapped = [r["mesh"] for r in res["rows"] if r["action"] in ("unwrapped", "check")]
    before_scoring = [m for m in scored if m not in unwrapped]
    check("Auto UV after Check UVs re-scores nothing (Keep UVs ones aren't scored at all)",
          not before_scoring and walls[1] not in scored,
          "%d scored before unwrapping: %s" % (len(before_scoring), before_scoring[:3]))
    check("...and afterwards checks only what it unwrapped", set(scored) <= set(unwrapped) and unwrapped,
          "%d checked, %d unwrapped" % (len(scored), len(unwrapped)))

    # --- Auto UV doesn't score: it uses the last Check UVs (if any), else unwraps everything unmarked
    cmds.file(new=True, force=True)
    root, kinds = ns["build_building"]()
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    good = [m for m, k in kinds.items() if k == "good" and "column" in m]
    calls = []
    orig_q = tb["uv_quality"]
    tb["uv_quality"] = lambda xform, *a, **k: (calls.append(xform), orig_q(xform, *a, **k))[1]
    res = tb["run_auto_uv"](asset, score="known", score_cache={}, pack=False)
    act = {r["mesh"]: r["action"] for r in res["rows"]}
    unwrapped = set(m for m, a in act.items() if a in ("unwrapped", "check"))
    check("Auto UV with no Check UVs unwraps every unmarked mesh, scoring nothing first",
          all(act[m] in ("unwrapped", "check") for m in good) and set(calls) <= unwrapped,
          "%d unwrapped, %d scored outside the after-check" % (len(unwrapped), len(set(calls) - unwrapped)))
    tb["uv_quality"] = orig_q
    cmds.undo()
    cache = {}
    tb["run_auto_uv"](asset, analyse_only=True, score_cache=cache)  # the optional Check UVs
    edited = good[1]
    cmds.polyEditUV(edited + ".map[0]", u=0.3, v=0.2)  # touched since the check
    calls[:] = []
    tb["uv_quality"] = lambda xform, *a, **k: (calls.append(xform), orig_q(xform, *a, **k))[1]
    res = tb["run_auto_uv"](asset, score="known", score_cache=cache, pack=False)
    tb["uv_quality"] = orig_q
    act = {r["mesh"]: r["action"] for r in res["rows"]}
    unwrapped = set(m for m, a in act.items() if a in ("unwrapped", "check"))
    check("after a Check UVs, meshes it found good are kept, without scoring again",
          act[good[0]] == "kept" and set(calls) <= unwrapped, "%s, %d scored" % (act[good[0]], len(calls)))
    check("...but a mesh edited since the check gets unwrapped", act[edited] in ("unwrapped", "check"),
          act[edited])

    # --- a heavy Hands off mesh is never chewed through
    heavy = cmds.polySphere(r=2, sx=400, sy=400, name="stoneGrey_C_heavy0001_GEP")[0]
    heavy = cmds.ls(cmds.parent(heavy, root + "|westWing_GRP")[0], long=True)[0]
    asset.scan()
    asset.set_uv_status([heavy], "handsoff")
    calls[:] = []
    tb["uv_quality"] = lambda xform, *a, **k: (calls.append(xform), orig_q(xform, *a, **k))[1]
    t0 = time.time()
    tb["run_auto_uv"](asset, score="known", score_cache=cache)
    t_auto = time.time() - t0
    tb["run_auto_uv"](asset, analyse_only=True, score_cache=cache)
    tb["uv_quality"] = orig_q
    check("Hands off meshes are never scored (Auto UV or Check UVs)", heavy not in calls)
    t0 = time.time()
    tb["show_uv_colours"](asset, {heavy: "handsoff"})
    t_col = time.time() - t0
    t0 = time.time()
    tb["collect_shells"](asset)
    t_plan1 = time.time() - t0
    t0 = time.time()
    tb["collect_shells"](asset)
    t_plan2 = time.time() - t0
    t0 = time.time()
    tb["validate_layout"](asset)
    t_val = time.time() - t0
    check("a 160,000-face Hands off mesh doesn't stall colours, Plan or Validate",
          t_col < 1.0 and t_plan2 < 3.0 and t_val < 10.0,
          "colours %.2fs, Plan %.1fs then %.1fs (remembered), Validate %.1fs, Auto UV %.1fs" % (
              t_col, t_plan1, t_plan2, t_val, t_auto))

    # --- Scan: progress, Esc rolls back, previous step intact
    cmds.file(new=True, force=True)
    root, kinds = ns["build_building"]()
    asset = tb["SmartUdimAsset"].for_group(root)
    cmds.undoInfo(openChunk=True, chunkName="user action")
    loc = cmds.spaceLocator(name="userMarker")[0]
    cmds.undoInfo(closeChunk=True)
    log = []

    def cancel(fraction, text):
        log.append(text)
        if "Sorting meshes" in text and " of " in text:
            raise tb["Cancelled"]("test")

    pr = tb["Progress"]("Scan", [("scan", 1)], cancel)
    try:
        with pr:
            asset.scan(sections_from_groups=True, progress=pr)
        ok = False
    except tb["Cancelled"]:
        ok = True
    snap = asset.read()
    check("Esc during Scan rolls it back", ok and not snap["sections"] and
          len(snap["unassigned"]) == len(snap["meshes"]), "%d sections" % len(snap["sections"]))
    check("...and keeps the previous undo step", cmds.objExists(loc))
    pr = tb["Progress"]("Scan", [("scan", 1)], log.append and (lambda f, t: log.append(t)))
    with pr:
        out = asset.scan(sections_from_groups=True, progress=pr)
    check("Scan reports progress per mesh", out["added"] > 0 and any("Sorting meshes" in t for t in log))


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
