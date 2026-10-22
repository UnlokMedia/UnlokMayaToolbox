"""Headless tests for Auto UV progress reporting and cancelling (mayapy).

    mayapy tests/test_auto_uv_progress.py

Runs Auto UV on a bigger generated building (the test building, three
times over), recording every progress update: every stage reports, the bar
only moves forward, there are no long silences, and a cancel in the middle
stops cleanly, with one Ctrl+Z putting the original UVs back.
"""

import os
import re
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "auto_uv_progress_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def build(tb):
    root, kinds = ns["build_building"]()
    for i in (1, 2):  # three copies of every piece: a bigger asset
        for mesh in list(kinds):
            parts = mesh.split("|")[-1].split("_")
            parts[2] = "dup%d%s" % (i, parts[2])  # brickRed_C_dup1wall0001_GEP: still a valid name
            cmds.rename(cmds.duplicate(mesh)[0], "_".join(parts))
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    return asset


def run():
    tb = ns["load_toolbox"]()
    cmds.loadPlugin("Unfold3D", quiet=True)
    asset = build(tb)
    meshes = asset.meshes()[0]
    print("  %d meshes" % len(meshes))
    probe = [m for m in meshes if "wall" in m][0]
    before = cmds.polyEditUV(probe + ".map[*]", query=True)

    # --- a full run, recording progress
    log = []

    def record(fraction, text):
        log.append((time.time(), fraction, text))

    t0 = time.time()
    res = tb["run_auto_uv"](asset, progress_callback=record)
    total = time.time() - t0
    stages = [s for s in ("Scoring UVs", "Checking geometry", "Backing up UVs", "Projecting", "Cutting seams",
                          "Unfolding", "Fixing stretched shells", "Packing into UDIMs", "Checking the result")
              if any(s in t for _, _, t in log)]
    check("every stage reports", len(stages) == 9, "%s" % stages)
    fr = [f for _, f, _ in log]
    check("the bar only moves forward and ends near 100%", all(b >= a - 1e-9 for a, b in zip(fr, fr[1:])) and
          fr[-1] > 0.9, "%d updates, last %.0f%%" % (len(fr), fr[-1] * 100))
    # A long wait may only happen inside one Unfold3D call (it can't report), and
    # then the bar has just said what it's on: a batch / mesh, or a group to pack.
    marks = [(t0, "start")] + [(t, txt) for t, _, txt in log] + [(t0 + total, "end")]
    long_gaps = [(b[0] - a[0], a[1]) for a, b in zip(marks, marks[1:]) if b[0] - a[0] > 3.0]
    for gap, txt in long_gaps:
        print("   %.1fs after: %s" % (gap, txt[:110]))
    named = re.compile(r" \d+ of \d+: |: re-unfolding ")  # the label says which mesh / batch / group
    unexplained = [g for g in long_gaps if not named.search(g[1])]
    check("no unexplained silences: every long wait is under a label naming what it's on", not unexplained,
          "%.1fs run, %d updates, %d long wait(s), unexplained: %s" % (
              total, len(log), len(long_gaps), [(round(g, 1), t[:60]) for g, t in unexplained]))
    unfold = [t for _, _, t in log if "Unfolding" in t]
    check("unfolding reports batch by batch, naming what it's on", len(unfold) >= 2 and
          any("faces" in t for t in unfold), unfold[-1][:120] if unfold else "")
    check("texts read well", all(t.startswith("Auto UV - ") and "%" in t for _, _, t in log), log[len(log) // 2][2])
    check("the run itself still works", res.get("rows") and not res.get("cancelled") and
          sum(1 for r in res["rows"] if r["action"] == "unwrapped") >= 24,
          "%d rows" % len(res.get("rows", [])))
    cmds.undo()
    check("one Ctrl+Z still undoes the whole run", cmds.polyEditUV(probe + ".map[*]", query=True) == before)

    # --- cancel part-way through unfolding (as if Esc was pressed)
    def cancel_in_unfold(fraction, text):
        if "Unfolding" in text and "of" in text:
            raise tb["Cancelled"]("test")

    res = tb["run_auto_uv"](asset, progress_callback=cancel_in_unfold)
    check("cancelling stops and says where", res.get("cancelled", "").startswith("Unfolding") and
          not res["rows"], str(res.get("cancelled")))
    check("after a cancel, one Ctrl+Z puts the original UVs back",
          (cmds.undo() or True) and cmds.polyEditUV(probe + ".map[*]", query=True) == before)

    # --- analyse reports too
    log[:] = []
    tb["run_auto_uv"](asset, analyse_only=True, progress_callback=record)
    check("Analyse reports progress", log and all(t.startswith("Analyse UVs - Scoring UVs") for _, _, t in log),
          log[-1][2] if log else "")


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
