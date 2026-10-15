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
    check("first-fit packing uses no more tiles than before (9)", len(plan["new_tiles"]) <= 9,
          "%d tiles, %.0f%% of usable area filled" % (len(plan["new_tiles"]), eff * 100))
    print("  packing efficiency (main axis): %.1f%%" % (eff * 100))

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
