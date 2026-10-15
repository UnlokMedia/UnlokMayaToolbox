"""Headless tests for Smart UDIM smart layout (mayapy).

    mayapy tests/test_smart_layout.py

Builds the messy test building from test_auto_uv.py, runs Auto UV to get UVs,
then checks the even-density layout: exact texel density, nothing crossing
tile borders, sections on their own rows, fit-to-tiles, auto-compensation,
locks, change detection, coverage in set names and one-step undo.
"""

import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]  # reuse its helpers (and maya.standalone init)
ns = {"__name__": "smart_layout_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]
import maya.api.OpenMaya as om  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def shell_stats(tb, xform, res):
    """[(px_per_m, (umin, vmin, umax, vmax))] for every UV shell of a mesh."""
    fn = tb["_mesh_fn"](xform)
    counts, ids = fn.getAssignedUVs("map1")
    nf = len(counts)
    a3, auv = tb["_face_areas"](xform, nf)
    _, shell_of = fn.getUvShellsIds("map1")
    us, vs = fn.getUVs("map1")
    unit = 0.01 ** 2  # test scenes are in cm
    acc = {}
    k = 0
    for f, c in enumerate(counts):
        s = shell_of[ids[k]]
        e = acc.setdefault(s, [0.0, 0.0, 1e9, 1e9, -1e9, -1e9])
        e[0] += a3[f] * unit
        e[1] += auv[f]
        for i in range(c):
            u, v = us[ids[k + i]], vs[ids[k + i]]
            e[2], e[3], e[4], e[5] = min(e[2], u), min(e[3], v), max(e[4], u), max(e[5], v)
        k += c
    return [(math.sqrt(e[1] / e[0]) * res if e[0] > 1e-12 else 0.0, (e[2], e[3], e[4], e[5])) for e in acc.values()]


def run():
    tb = ns["load_toolbox"]()
    cmds.loadPlugin("Unfold3D", quiet=True)
    root, kinds = ns["build_building"]()
    # real-world scale: the shared test building is in centimetres (4-8 cm walls); make it metres
    cmds.scale(100, 100, 100, root)
    cmds.makeIdentity(root, apply=True, scale=True)
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    tb["run_auto_uv"](asset)  # a usable unwrap to lay out
    scores_before = {m: tb["uv_quality"](m)[0] for m in asset.meshes()[0]}

    # give one group 150% density to check per-group TD %
    brick_east = [m for s in asset.sections() if "eastWing" in s for m in asset.materials(s)
                  if "brickRed" in m][0]
    brick_east = asset.set_group_values(brick_east, td=150)
    brick_east_uuid = cmds.ls(brick_east, uuid=True)[0]  # names change when coverage is written

    settings = dict(tb["LAYOUT_DEFAULTS"], texel_density=128.0, map_size="2048")
    t0 = time.time()
    col = tb["collect_shells"](asset)
    t_col = time.time() - t0
    t0 = time.time()
    plan = tb["make_plan"](col, settings)
    t_plan = time.time() - t0
    n_shells = len(plan["placements"])
    check("collect + plan are fast", t_col < 3.0 and t_plan < 0.5,
          "collect %.2fs, plan %.3fs for %d shells" % (t_col, t_plan, n_shells))
    rects = []
    for g in col["groups"]:
        for sh in g["shells"]:
            tu, tv, x, y, k, a, w, h = plan["placements"][id(sh)]
            rects.append((tu + x, tv + y, tu + x + w, tv + y + h))
    overl = 0
    rects.sort()
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if rects[j][0] >= rects[i][2] - 1e-9:
                break
            a, b = rects[i], rects[j]
            if a[0] < b[2] - 1e-9 and b[0] < a[2] - 1e-9 and a[1] < b[3] - 1e-9 and b[1] < a[3] - 1e-9:
                overl += 1
    check("planned shells never overlap", overl == 0, "%d overlapping pairs" % overl)

    t0 = time.time()
    res = tb["apply_layout"](asset, col, plan)
    t_apply = time.time() - t0
    check("apply is quick", t_apply < 10.0, "%.2fs for %d shells on %d meshes" % (t_apply, res["shells"],
                                                                                  res["meshes"]))
    # exact density + nothing over a tile border
    meshes = asset.meshes()[0]
    dens_100, dens_150, crossing, total = [], [], 0, 0
    brick_east = cmds.ls(brick_east_uuid)[0]
    brick_east_meshes = set(tb["expand_members"](brick_east)[0])
    for m in meshes:
        for d, (u0, v0, u1, v1) in shell_stats(tb, m, 2048.0):
            total += 1
            if math.floor(u0 + 1e-6) != math.floor(u1 - 1e-6) or math.floor(v0 + 1e-6) != math.floor(v1 - 1e-6):
                crossing += 1
            (dens_150 if m in brick_east_meshes else dens_100).append(d)
    check("no shell crosses a tile border", crossing == 0, "%d of %d" % (crossing, total))
    comp = {st["key"] for st in plan["stats"].values() if st.get("density") and st["density"] < 127.9}
    d100 = [d for d in dens_100]
    spread = (max(d100) / min(d100)) if d100 else 0
    check("texel density even across all groups (+-2%)", max(abs(d / 128.0 - 1) for d in d100) < 0.02,
          "min %.1f max %.1f px/m (compensated groups: %s)" % (min(d100), max(d100), comp or "none"))
    check("TD 150% group gets 1.5x density", dens_150 and max(abs(d / 192.0 - 1) for d in dens_150) < 0.02,
          "%.1f..%.1f px/m" % (min(dens_150), max(dens_150)))
    # layout only moves / rotates / uniformly scales whole shells, so it must never make a mesh worse
    worse = [(m.split("|")[-1], round(scores_before[m], 3), round(tb["uv_quality"](m)[0], 3)) for m in meshes
             if tb["uv_quality"](m)[0] < scores_before[m] - 0.005]
    check("layout never makes a mesh's UVs worse (no new overlaps)", not worse, str(worse[:4]))
    rows_of = {}
    for _, st in plan["stats"].items():
        mat = cmds.ls(st["uuid"])[0]  # sets were renamed (coverage) by apply
        sec = [s for s in asset.sections() if mat in asset.materials(s)][0]
        rows_of.setdefault(sec, set()).update((t - 1001) // 10 for t in st["tiles"])
    check("each section on its own rows", all(not (a & b) for i, a in enumerate(rows_of.values())
                                              for j, b in enumerate(rows_of.values()) if i < j),
          str({k.split("_")[0]: sorted(v) for k, v in rows_of.items()}))
    names = [m for s in asset.sections() for m in asset.materials(s)]
    check("coverage written into set names", all("_c" in n for n in names), str(names[:4]))

    # undo
    probe = meshes[0]
    after_uvs = cmds.polyEditUV(probe + ".map[*]", q=True)
    cmds.undo()
    check("one Ctrl+Z undoes the layout", cmds.polyEditUV(probe + ".map[*]", q=True) != after_uvs)
    cmds.redo()

    # fit to N tiles
    fit = tb["make_plan"](tb["collect_shells"](asset), dict(settings, mode="Fit to tiles", max_tiles=6))
    more = tb["plan_layout"](tb["collect_shells"](asset), dict(settings, texel_density=fit["density"] * 1.06))
    check("fit to tiles respects the budget", len(fit["new_tiles"]) <= 6, "%d tiles at %.0f px/m" % (
        len(fit["new_tiles"]), fit["density"]))
    check("fit to tiles finds (about) the highest density", len(more["new_tiles"]) > 6,
          "+6%% density needs %d tiles" % len(more["new_tiles"]))

    # locks: lock west glass, change density and re-apply; glass stays put, its tiles stay reserved
    col = tb["collect_shells"](asset)
    plan = tb["make_plan"](col, settings)
    tb["apply_layout"](asset, col, plan)
    glass_w = [m for s in asset.sections() if "westWing" in s for m in asset.materials(s) if "glassClear" in m][0]
    glass_meshes = list(tb["expand_members"](glass_w)[0])
    glass_before = [cmds.polyEditUV(m + ".map[*]", q=True) for m in glass_meshes]
    glass_tiles = set(int(t) for t in cmds.getAttr(glass_w + ".unlokUdimTiles").split(","))
    tb["set_group_lock"](glass_w, True)
    col = tb["collect_shells"](asset)
    plan = tb["make_plan"](col, dict(settings, texel_density=100.0))
    tb["apply_layout"](asset, col, plan)
    check("locked group keeps its UVs", [cmds.polyEditUV(m + ".map[*]", q=True) for m in glass_meshes] ==
          glass_before)
    others = set()
    for mat, st in plan["stats"].items():
        if not st.get("locked"):
            others.update(st["tiles"])
    check("nobody else lands in a locked group's tiles", not (others & glass_tiles),
          "locked %s, others %s" % (sorted(glass_tiles), sorted(others)))

    # change detection
    beam = [m for m, k in kinds.items() if "wall" in m and m in tb["expand_members"](
        [x for s in asset.sections() if "westWing" in s for x in asset.materials(s) if "brickRed" in x][0])[0]][0]
    cmds.polyExtrudeFacet(beam + ".f[0]", localTranslateZ=0.2)
    plan = tb["make_plan"](tb["collect_shells"](asset), settings)
    changed = [st["key"] for st in plan["stats"].values() if st.get("changed")]
    check("geometry changes since the last layout are flagged", "brickRed" in changed, str(changed))

    # oversized piece: auto-compensate lowers that group only, and it fits a tile
    huge = cmds.polyCube(w=600, h=400, d=10, name="concreteGrey_C_slab0001_GEP")[0]  # 6 x 4 m (scene in cm)
    cmds.parent(huge, "|building_GRP|westWing_GRP")
    asset.scan()
    tb["run_auto_uv"](asset, pack=False)
    col = tb["collect_shells"](asset)
    plan = tb["make_plan"](col, dict(settings, texel_density=2048.0))
    slab = [st for st in plan["stats"].values() if st["key"] == "concreteGrey"][0]
    check("auto-compensate lowers just the oversized group", slab["density"] < 2048.0 and
          any("concreteGrey" in w for w in plan["warnings"]),
          "%.0f px/m; %s" % (slab["density"], plan["warnings"][:1]))
    big = max(max(plan["placements"][id(sh)][6], plan["placements"][id(sh)][7]) for g in col["groups"]
              if g["key"] == "concreteGrey"
              for sh in g["shells"])
    check("oversized piece now fits in a tile", big <= 1.0, "%.3f" % big)


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
