"""Headless tests for smart layout orientation modes, _stack stacking and
first-fit packing (mayapy).

    mayapy tests/test_layout_extras.py
"""

import math
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "layout_extras_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def efficiency(plan, settings):
    res = float(settings["map_size"])
    pad = settings["padding_px"] / res
    area = sum(p[6] * p[7] for p in plan["placements"].values())
    return area / (len(plan["new_tiles"]) * (1 - 2 * pad) ** 2)


def run():
    tb = ns["load_toolbox"]()
    cmds.loadPlugin("Unfold3D", quiet=True)
    root, kinds = ns["build_building"]()
    cmds.scale(100, 100, 100, root)
    cmds.makeIdentity(root, apply=True, scale=True)
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    tb["run_auto_uv"](asset)
    base = dict(tb["LAYOUT_DEFAULTS"], texel_density=128.0, map_size="2048")

    # --- packing: first-fit fills row ends; the old shelf packer needed 9 tiles here
    col = tb["collect_shells"](asset)
    plan = tb["make_plan"](col, base)
    eff = efficiency(plan, base)
    check("2D packing needs fewer tiles than the old shelf packer (9)", len(plan["new_tiles"]) <= 8,
          "%d tiles, %.0f%% of usable area filled" % (len(plan["new_tiles"]), eff * 100))
    print("  packing efficiency (main axis): %.1f%%" % (eff * 100))
    pad = base["padding_px"] / float(base["map_size"])
    by_tile = {}
    for p in plan["placements"].values():
        by_tile.setdefault((p[0], p[1]), []).append((p[2], p[3], p[2] + p[6], p[3] + p[7]))
    inside = all(b[0] >= pad - 1e-9 and b[1] >= pad - 1e-9 and b[2] <= 1 - pad + 1e-9 and b[3] <= 1 - pad + 1e-9
                 for boxes in by_tile.values() for b in boxes)
    clash = 0
    for boxes in by_tile.values():
        boxes.sort()
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                if b[0] >= a[2] + pad - 1e-9:
                    break
                if b[1] < a[3] + pad - 1e-9 and a[1] < b[3] + pad - 1e-9:
                    clash += 1
    check("planned boxes stay inside their tile and keep the padding apart", inside and clash == 0,
          "%d boxes, %d too close" % (sum(len(b) for b in by_tile.values()), clash))
    turned = sum(1 for g in col["groups"] for sh in g["shells"]
                 if abs(plan["placements"][id(sh)][5] - sh.dims["axis"][0]) > 1e-6)
    tb["apply_layout"](asset, col, plan)
    worst = 0.0
    for g in col["groups"]:
        for sh in g["shells"]:
            tu, tv, x, y, k, a, w, h = plan["placements"][id(sh)]
            us, vs = tb["_mesh_fn"](sh.mesh).getUVs("map1")
            su = [us[i] for i in sh.uv_ids]
            sv = [vs[i] for i in sh.uv_ids]
            worst = max(worst, abs(min(su) - tu - x), abs(min(sv) - tv - y),
                        abs(max(su) - min(su) - w), abs(max(sv) - min(sv) - h))
    px = 1.0 / float(base["map_size"])
    check("turned and unturned pieces land where planned (within a pixel)", turned > 0 and worst < px,
          "%d turned 90 deg, worst error %.2f px" % (turned, worst / px))
    col = tb["collect_shells"](asset)
    res = tb["validate_layout"](asset)
    bad = dict((c, len(res["items"][c])) for c in ("out_of_range", "crossing", "overlap", "padding")
               if res["items"][c])
    check("validation finds no overlap, crossing or padding issues after packing", not bad, str(bad))

    # --- stable: the same shells in another order give the same layout
    def spots(c, pl):
        return sorted((sh.mesh, sh.uv_ids[0], tuple(round(v, 9) for v in pl["placements"][id(sh)]))
                      for g in c["groups"] for sh in g["shells"])
    first = spots(col, tb["make_plan"](col, base))
    for g in col["groups"]:
        g["shells"].reverse()
    check("re-planning is stable whatever order shells were read in",
          spots(col, tb["make_plan"](col, base)) == first)

    # --- speed: 1,200 synthetic shells in 12 groups (pure math, no scene)
    rng = __import__("random").Random(7)
    groups = []
    for gi in range(12):
        shells = []
        for _ in range(100):
            w, h = rng.uniform(0.02, 0.6), rng.uniform(0.01, 0.15)
            sh = tb["LayoutShell"]("m", [0, 1, 2, 3], w * h, w * h, [(0, 0), (w, 0), (w, h), (0, h)])
            shells.append(sh)
        groups.append({"set": "g%d" % gi, "uuid": "u%d" % gi, "key": "k%d" % gi, "section_index": gi // 4,
                       "td": 100.0, "shells": shells, "print": "", "old_print": "", "stack": False,
                       "orient": None, "tiles": []})
    synth = {"groups": groups, "locked": [], "skipped": [], "conflicts": 0}
    synth_settings = dict(base, texel_density=1.0, map_size="1", padding_px=0.002)
    t0 = __import__("time").time()
    sp = tb["plan_layout"](synth, synth_settings)
    dt = __import__("time").time() - t0
    check("plans 1,200 shells fast", dt < 0.25, "%.0f ms, %d tiles, %.0f%% filled" % (
        dt * 1000, len(sp["new_tiles"]), efficiency(sp, synth_settings) * 100))

    # --- Fit sections to rows: the default mode
    fr = tb["make_plan"](col, dict(base, mode=tb["FIT_ROWS"]))
    rows = tb["section_rows"](col, fr)
    dens = set(round(st["density"], 3) for st in fr["stats"].values() if st.get("density"))
    check("Fit sections to rows: every section on its own single row, one texel density for all",
          rows and all(len(r) == 1 for r in rows.values()) and len(set(min(r) for r in rows.values())) == len(rows)
          and len(dens) == 1, "rows %s, density %s px/m" % (sorted(rows.items()), sorted(dens)))
    denser = tb["plan_layout"](col, dict(base, new_row_per_section=True), fr["density"] / base["texel_density"] * 1.06)
    check("...at about the highest density that allows it", any(
        len(r) > 1 for r in tb["section_rows"](col, denser).values()), "%.0f px/m" % fr["density"])

    # --- Upright: world up runs along +V for walls
    up_settings = dict(base, orientation="Upright")
    plan = tb["make_plan"](col, up_settings)
    tb["apply_layout"](asset, col, plan)
    unit = 0.01 ** 2
    errors = []
    for m, k in kinds.items():
        if k != "stretched":
            continue
        cache = tb["_mesh_cache"](m, "map1", unit)
        shells = {}
        for f in range(cache["nf"]):
            shells.setdefault(cache["uv_shell"][cache["face_uvs"][f][0]], []).append(f)
        for fs in shells.values():
            d = tb["_shell_up_direction"](cache, fs)
            if d is not None:  # side walls; tops / bottoms are flat
                errors.append(abs(math.degrees(math.atan2(d[0], d[1]))))
    check("Upright: world up maps to +V on every wall shell", errors and max(errors) < 3.0,
          "%d shells, worst %.2f deg off" % (len(errors), max(errors) if errors else -1))

    # --- per-group override: woodBrown set to keep -> its shells don't rotate
    wood = [m for s in asset.sections() for m in asset.materials(s) if "woodBrown" in m][0]
    wood = asset.set_group_values(wood, orient="keep")
    check("orientation override lives in the set name", wood.endswith("_keep") and
          tb["parse_group_name"](wood).get("orient") == "keep", wood)
    col = tb["collect_shells"](asset)
    sample = [sh for g in col["groups"] if g["set"] == wood for sh in g["shells"]][0]
    fn = tb["_mesh_fn"](sample.mesh)
    us, vs = fn.getUVs("map1")
    a, b = sample.uv_ids[0], sample.uv_ids[-1]
    before = (us[b] - us[a], vs[b] - vs[a])
    plan = tb["make_plan"](col, up_settings)
    tb["apply_layout"](asset, col, plan)
    us, vs = tb["_mesh_fn"](sample.mesh).getUVs("map1")
    after = (us[b] - us[a], vs[b] - vs[a])
    ang = abs(math.degrees(math.atan2(before[0] * after[1] - before[1] * after[0],
                                      before[0] * after[0] + before[1] * after[1])))
    check("Keep: shells keep their orientation", ang < 0.5, "turned %.3f deg" % ang)
    check("plan reports the per-group orientation", any(st.get("orientation") == "keep"
                                                         for st in plan["stats"].values()))

    # --- _stack: identical glass panes share one spot
    glass = [m for s in asset.sections() for m in asset.materials(s) if "glassClear" in m]
    col = tb["collect_shells"](asset)
    plain = tb["make_plan"](col, base)
    plain_cov = sum(st["coverage"] for st in plain["stats"].values() if st["key"] == "glassClear")
    for gset in glass:
        asset.set_group_values(gset, stack=True)
    col = tb["collect_shells"](asset)
    plan = tb["make_plan"](col, base)
    stacked = sum(st.get("stacked", 0) for st in plan["stats"].values() if st["key"] == "glassClear")
    cov = sum(st["coverage"] for st in plan["stats"].values() if st["key"] == "glassClear")
    spots = set()
    n = 0
    for g in col["groups"]:
        if g["key"] == "glassClear":
            for sh in g["shells"]:
                p = plan["placements"][id(sh)]
                spots.add((p[0], p[1], round(p[2], 6), round(p[3], 6)))
                n += 1
    check("_stack: identical panes stack onto shared spots", stacked > 0 and len(spots) < n,
          "%d shells on %d spots, %d stacked" % (n, len(spots), stacked))
    check("_stack: stacked group takes less space", cov < plain_cov * 0.75,
          "coverage %.1f%% vs %.1f%% unstacked" % (cov, plain_cov))
    tb["apply_layout"](asset, col, plan)
    res = tb["validate_layout"](asset)
    glass_meshes = set(m for gset in [cmds.ls(cmds.ls(x, uuid=True)[0])[0] if cmds.objExists(x) else x
                                      for x in glass] for m in [])
    overlaps = [it for it in res["items"]["overlap"] if "glassClear" in it["mesh"]]
    check("validation doesn't flag intentional stacks as overlaps", not overlaps,
          "%d glass overlaps reported" % len(overlaps))


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
