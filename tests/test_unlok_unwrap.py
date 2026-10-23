"""Headless tests for the Unlok unwrapper (mayapy).

    mayapy tests/test_unlok_unwrap.py

- a box and a plank unfold into one shell (box unfolding), with no stretch
- a cylinder's side unrolls exactly; a sphere gets one pelt shell
- a torus (not a disk) is split until it flattens, nothing flipped
- a combined grid of copies is unwrapped once and copied
- cancelling stops it; one Ctrl+Z undoes a run
- the test building: Unlok vs Unfold3D, time and quality
"""

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "unlok_unwrap_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def run():
    tb = ns["load_toolbox"]()
    cmds.loadPlugin("Unfold3D", quiet=True)
    UNLOK = tb["UNWRAP_METHODS"][0]

    def unwrap(meshes, **opts):
        t = time.time()
        failed = tb["auto_unwrap"](meshes, method=UNLOK, opts=opts)
        return failed, time.time() - t, dict(getattr(tb["auto_unwrap"], "last_stats", {}))

    def shells(m):
        return tb["_mesh_fn"](m).getUvShellsIds("map1")[0]

    def quality(m):
        return tb["uv_quality"](m)[0]

    def stretch(m):
        """Worst singular-value spread over the mesh's triangles."""
        fn = tb["_mesh_fn"](m)
        d = tb["_uw_read"](m)
        _, ids = fn.getAssignedUVs("map1")
        us, vs = fn.getUVs("map1")
        P, UV, T = [], [], []
        k = 0
        for f, fv in enumerate(d["faces"]):
            start = len(P)
            for i, v in enumerate(fv):
                P.append(d["pts"][v])
                UV.append((us[ids[k + i]], vs[ids[k + i]]))
            T += [(start + a, start + b, start + c) for a, b, c in d["tris"][f]]
            k += len(fv)
        return tb["_uw_stretch"](P, T, UV)

    # --- a box: one shell, flat, no stretch
    box = cmds.polyCube(w=2, h=1, d=1, name="crate")[0]
    failed, secs, st = unwrap([box])
    flips, good, worst = stretch(box)
    check("box: unwrapped", not failed, "%s %.3fs %s" % (failed, secs, st))
    check("box: sewn into one shell (box unfold)", shells(box) == 1, "%d shells" % shells(box))
    check("box: no stretch, nothing flipped", flips == 0 and worst < 1.01, "flips %d worst %.3f" % (flips, worst))

    # --- a plank with some divisions: one shell
    plank = cmds.polyCube(w=4, h=0.1, d=0.3, sx=6, sy=1, sz=2, name="plank")[0]
    failed, secs, st = unwrap([plank])
    flips, good, worst = stretch(plank)
    check("plank: one shell, no stretch", not failed and shells(plank) == 1 and flips == 0 and worst < 1.01,
          "%d shells, worst %.3f, %s" % (shells(plank), worst, st))
    check("plank: UV quality is clean", quality(plank) >= 0.95, "%.3f" % quality(plank))

    # --- cylinder: side unrolled exactly
    cyl = cmds.polyCylinder(r=0.5, h=3, sx=16, sy=3, name="column")[0]
    failed, secs, st = unwrap([cyl])
    flips, good, worst = stretch(cyl)
    check("cylinder: unrolled with no stretch", not failed and flips == 0 and worst < 1.02,
          "%d shells, worst %.3f, %s" % (shells(cyl), worst, st))
    check("cylinder: side + caps (3 shells or fewer)", shells(cyl) <= 3, "%d shells" % shells(cyl))

    # --- sphere: organic, one pelt
    sph = cmds.polySphere(r=1, sx=24, sy=16, name="rock")[0]
    failed, secs, st = unwrap([sph])
    flips, good, worst = stretch(sph)
    check("sphere: organic pelt, nothing flipped", not failed and flips == 0 and st.get("organic") == 1,
          "%d shells, good %.2f, %.2fs, %s" % (shells(sph), good, secs, st))
    check("sphere: few shells", shells(sph) <= 4, "%d shells" % shells(sph))
    check("sphere: UV quality ok", quality(sph) >= 0.7, "%.3f" % quality(sph))

    # --- dense sphere: big curved charts relax coarse-to-fine, no Unfold3D
    dense = cmds.polySphere(r=1, sx=120, sy=60, name="denseRock")[0]
    failed, secs, st = unwrap([dense])
    flips, good, worst = stretch(dense)
    check("dense sphere (7,200 faces): relaxed here, nothing left for Unfold3D",
          not failed and flips == 0 and not st.get("heavy") and not st.get("rough"),
          "%d shells, good %.2f, %.2fs, %s" % (shells(dense), good, secs, st))
    check("dense sphere: UV quality ok", quality(dense) >= 0.7, "%.3f" % quality(dense))

    # --- torus: not a disk, gets split until it flattens
    tor = cmds.polyTorus(r=1, sr=0.3, sx=24, sy=12, name="ring")[0]
    failed, secs, st = unwrap([tor])
    flips, good, worst = stretch(tor)
    check("torus: flattened, nothing flipped", not failed and flips == 0,
          "%d shells, good %.2f, %.2fs, %s" % (shells(tor), good, secs, st))

    # --- combined grid of copies: one unwrap, the rest copied
    parts = []
    for i in range(36):
        c = cmds.polyCylinder(r=0.2, h=1, sx=12, sy=2, name="peg%d" % i)[0]
        cmds.move((i % 6) * 1.0, 0, (i // 6) * 1.0, c)
        cmds.rotate(0, i * 10, 0, c)
        parts.append(c)
    grid = cmds.polyUnite(parts, constructionHistory=False, name="pegGrid")[0]
    failed, secs, st = unwrap([grid])
    check("grid of 36 copies: unwrapped once, 35 copied", not failed and st.get("copies") == 35,
          "%.2fs %s" % (secs, st))
    flips, good, worst = stretch(grid)
    check("grid: every copy clean", flips == 0 and worst < 1.02, "worst %.3f" % worst)
    one = cmds.polyCylinder(r=0.2, h=1, sx=12, sy=2, name="pegOne")[0]
    t = time.time()
    unwrap([one])
    single = time.time() - t
    check("grid: about the cost of one piece (copies are cheap)", secs < single * 8 + 0.5,
          "grid %.2fs, one %.2fs" % (secs, single))

    # --- cancel
    ctl = {"cancel": True}
    try:
        tb["unlok_unwrap_data"]([tb["_uw_read"](sph)], None, ctl)
        stopped = False
    except tb["Cancelled"]:
        stopped = True
    check("cancel stops the worker", stopped)

    # --- the building: Unlok vs Unfold3D through run_auto_uv (one Ctrl+Z)
    timings = {}
    scores = {}
    for method in tb["UNWRAP_METHODS"]:
        cmds.file(new=True, force=True)
        root, kinds = ns["build_building"]()
        asset = tb["SmartUdimAsset"].for_group(root)
        asset.scan(sections_from_groups=True)
        first = list(kinds)[0]
        before = cmds.polyEditUV(first + ".map[*]", q=True)
        t = time.time()
        res = tb["run_auto_uv"](asset, score=False, unwrapper=method)
        timings[method] = time.time() - t
        after = [quality(m) for m in kinds]
        scores[method] = sum(after) / len(after)
        bad = [r for r in res["rows"] if r["action"] == "failed"]
        check("building (%s): nothing failed" % method, not bad, str(bad[:3]))
        if method == tb["UNWRAP_METHODS"][0]:
            cmds.undo()
            check("building (Unlok): one Ctrl+Z restores the UVs", cmds.polyEditUV(first + ".map[*]", q=True) == before)
    print("INFO  building Auto UV: Unlok %.1fs, Unfold3D %.1fs" % (timings[UNLOK], timings[tb["UNWRAP_METHODS"][1]]))
    datas = [tb["_uw_read"](m) for m in kinds]
    rest = [d for d in datas if "dome" not in d["mesh"]]
    t = time.time()
    out = tb["unlok_unwrap_data"](rest)
    t_rest = time.time() - t
    check("building: everything but the dense dome unwraps in under a second", t_rest < 1.0,
          "%.2fs for %d meshes" % (t_rest, len(rest)))
    dome = [d for d in datas if "dome" in d["mesh"]]
    t = time.time()
    out = tb["unlok_unwrap_data"](dome)
    t_dome = time.time() - t
    st = list(out.values())[0]["stats"]
    check("building: the 19,200-face dome relaxes here, in under 15 s", t_dome < 15.0 and not st["heavy"],
          "%.2fs %s" % (t_dome, dict((k, v) for k, v in st.items() if v)))
    check("building: Unlok quality at least as good (within 0.03)",
          scores[UNLOK] >= scores[tb["UNWRAP_METHODS"][1]] - 0.03,
          "Unlok %.3f, Unfold3D %.3f" % (scores[UNLOK], scores[tb["UNWRAP_METHODS"][1]]))


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
