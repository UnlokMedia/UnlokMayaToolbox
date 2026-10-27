"""Headless tests for managing a finished layout (mayapy).

    mayapy tests/test_manage_layout.py

- parse_tiles reads '1012', '1012-1014, 1021'
- a pinned group lands on its tile, and nothing else goes there
- a group too big for its pin spills over with a warning
- re-layout of some groups leaves every other mesh's UVs untouched, stays
  in its own tiles and doesn't overlap the rest
- Auto UV fits a pinned group's meshes into its pinned tile
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "manage_layout_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
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
    check("parse_tiles", tb["parse_tiles"]("1012-1014, 1021") == [1012, 1013, 1014, 1021] and
          tb["parse_tiles"]("nope") == [] and tb["parse_tiles"]("1001") == [1001])

    root, kinds = ns["build_building"]()
    cmds.scale(100, 100, 100, root)
    cmds.makeIdentity(root, apply=True, scale=True)
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    tb["run_auto_uv"](asset, score=False, unwrapper=tb["UNWRAP_METHODS"][0], pack="fit")
    base = dict(tb["LAYOUT_DEFAULTS"], texel_density=128.0, map_size="2048")
    col = tb["collect_shells"](asset)
    plan = tb["make_plan"](col, base)
    tb["apply_layout"](asset, col, plan)
    uids = [g["uuid"] for g in col["groups"]]
    name = lambda uid: cmds.ls(uid)[0]  # noqa: E731  (Apply renames sets: coverage goes in the name)
    target = name(uids[0])

    # --- pin
    tb["set_group_pin"](target, [1035])
    col = tb["collect_shells"](asset)
    plan = tb["make_plan"](col, dict(base, texel_density=32.0))  # small enough to fit one tile
    target = name(uids[0])
    st = plan["stats"][target]
    others = set(t for s, v in plan["stats"].items() if s != target and v.get("tiles") for t in v["tiles"])
    check("a pinned group lands on its tile", st["tiles"] == [1035], str(st["tiles"]))
    check("...and no other group goes there", 1035 not in others, str(sorted(others)))
    big = dict(base, texel_density=4096.0)
    plan_big = tb["make_plan"](col, big)
    check("a group too big for its pin spills over, with a warning",
          len(plan_big["stats"][target]["tiles"]) > 1 and any("pinned" in w for w in plan_big["warnings"]),
          "%s | %s" % (plan_big["stats"][target]["tiles"], plan_big["warnings"][:1]))
    fit = tb["make_plan"](col, dict(base, mode=tb["FIT_ROWS"]))
    check("Fit sections to rows ignores pinned groups", fit["density"] > 64, "%.0f px/m" % fit["density"])
    tb["apply_layout"](asset, col, plan)
    tb["set_group_pin"](name(uids[0]), [])

    # --- re-layout of one group
    pick = name(uids[1])
    members = set(tb["expand_members"](pick)[0])
    before = dict((m, cmds.polyEditUV(m + ".map[*]", q=True)) for m in kinds if m not in members)
    old_tiles = tb["collect_shells"](asset)
    old_tiles = [g for g in old_tiles["groups"] if g["set"] == pick][0]["tiles"]
    col = tb["collect_shells"](asset, only=[pick])
    check("re-layout reads only the chosen group", [g["set"] for g in col["groups"]] == [pick],
          str([g["set"] for g in col["groups"]]))
    plan = tb["make_plan"](col, base)
    tb["apply_layout"](asset, col, plan)
    pick_now = name(uids[1])
    same = all(cmds.polyEditUV(m + ".map[*]", q=True) == uv for m, uv in before.items())
    check("every other mesh's UVs are untouched", same)
    new_tiles = plan["stats"][pick]["tiles"]  # keyed by the name at plan time
    check("it stays in its own tiles", set(new_tiles) <= set(old_tiles), "%s -> %s" % (old_tiles, new_tiles))
    res = tb["validate_layout"](asset)
    check("...without overlapping anything", not res["items"].get("overlap"),
          str(res["items"].get("overlap", [])[:2]))

    # --- Auto UV honours a pin
    tb["set_group_pin"](pick_now, [1042])
    mesh = sorted(members)[0]
    out = tb["run_auto_uv"](asset, score=False, unwrapper=tb["UNWRAP_METHODS"][0], pack="fit", only=[mesh])
    check("Auto UV fits a pinned group's mesh into its pinned tile", dict(out["tiles"]).get(mesh) == 1042,
          str(out["tiles"]))


def bundles(tb):
    """Each multi-shell mesh's shells end up close together (and nothing else
    sits among them) with keep_meshes on."""
    cmds.file(new=True, force=True)
    root = cmds.group(empty=True, name="ropes_GRP")
    import random as _r
    _r.seed(3)
    for i in range(6):
        parts = []
        for j in range(5):
            t = cmds.polyCylinder(r=_r.uniform(1, 3), h=_r.uniform(5, 30), sx=8, sy=2)[0]
            cmds.move(j * 10, 0, i * 20, t)
            parts.append(t)
        rope = cmds.polyUnite(parts, constructionHistory=False, name="ropeTan_C_bind%04d_GEP" % (i + 1))[0]
        cmds.parent(rope, root)
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan()
    tb["run_auto_uv"](asset, score=False, unwrapper=tb["UNWRAP_METHODS"][0], pack="fit")
    col = tb["collect_shells"](asset)

    def spread(settings):
        plan = tb["make_plan"](col, settings)
        boxes = {}
        for g in col["groups"]:
            for sh in g["shells"]:
                pl = plan["placements"][id(sh)]
                x0, y0 = pl[0] + pl[2], pl[1] + pl[3]
                boxes.setdefault(sh.mesh, []).append((x0, y0, x0 + pl[6], y0 + pl[7]))
        intruders = 0
        for m, bs in boxes.items():
            u0, v0 = min(b[0] for b in bs), min(b[1] for b in bs)
            u1, v1 = max(b[2] for b in bs), max(b[3] for b in bs)
            for o, obs in boxes.items():
                if o == m:
                    continue
                for b in obs:
                    cx, cy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
                    if u0 < cx < u1 and v0 < cy < v1:
                        intruders += 1
        return intruders, len(plan["new_tiles"])

    base = dict(tb["LAYOUT_DEFAULTS"], texel_density=64.0, map_size="2048")
    loose, tiles_loose = spread(base)
    kept, tiles_kept = spread(dict(base, keep_meshes=True, group_similar=True))
    check("keep meshes together: no other mesh's shells sit among a mesh's shells", kept == 0 and loose > 0,
          "%d intruders with it, %d without" % (kept, loose))
    check("...without needing many more tiles", tiles_kept <= tiles_loose + 1, "%d vs %d" % (tiles_kept, tiles_loose))


try:
    run()
    bundles(ns["load_toolbox"]())
except Exception:
    traceback.print_exc()
    RESULTS.append(("exception", False, ""))
finally:
    failed = [r for r in RESULTS if not r[1]]
    print("\n%d passed, %d failed" % (len(RESULTS) - len(failed), len(failed)))
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(1 if failed else 0)
