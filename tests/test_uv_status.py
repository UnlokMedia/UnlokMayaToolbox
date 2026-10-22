"""Headless tests for per-mesh UV status: Keep UVs and Hands off (mayapy).

    mayapy tests/test_uv_status.py

Keep UVs: never re-unwrapped, still laid out. Hands off: never touched by Auto
UV or the layout; the layout either packs around those shells or reserves their
tiles.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "uv_status_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def udim(p):
    return 1001 + p[0] + 10 * p[1]


def run():
    tb = ns["load_toolbox"]()
    cmds.loadPlugin("Unfold3D", quiet=True)
    root, kinds = ns["build_building"]()
    cmds.scale(100, 100, 100, root)
    cmds.makeIdentity(root, apply=True, scale=True)
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    by_name = {m.split("|")[-1]: m for m in kinds}
    wall1, wall2 = by_name["brickRed_C_wall0001_GEP"], by_name["brickRed_C_wall0002_GEP"]
    post = by_name["woodBrown_C_post0001_GEP"]
    pane = by_name["glassClear_F_pane0001_GEP"]
    fn = tb["_mesh_fn"]

    # --- marking
    n_sections = len(asset.sections())
    asset.set_uv_status([wall1], "keep")
    asset.set_uv_status([post], "handsoff")
    st = asset.uv_status()
    check("meshes can be marked Keep UVs and Hands off", st.get(wall1) == "keep" and st.get(post) == "handsoff",
          str(sorted((k.split("|")[-1], v) for k, v in st.items())))
    keep_set, off_set = asset.status_set("keep"), asset.status_set("handsoff")
    check("status lives in two sets under the root, not as sections",
          keep_set and off_set and len(asset.sections()) == n_sections and
          tb["set_role"](keep_set) == "uvkeep", "%s, %s" % (keep_set, off_set))
    asset.set_uv_status([wall2], "handsoff")
    cmds.undo()
    check("marking is one Ctrl+Z", wall2 not in asset.uv_status())
    asset.set_uv_status([wall1], "handsoff")
    asset.set_uv_status([wall1], "keep")
    check("re-marking moves a mesh between statuses", asset.uv_status().get(wall1) == "keep")
    asset.sync_names()
    check("renaming groups leaves the status sets alone", cmds.objExists(keep_set) and
          asset.uv_status().get(post) == "handsoff")

    # --- Auto UV respects both
    post_uvs = [list(a) for a in fn(post).getUVs("map1")]
    post_sets = fn(post).getUVSetNames()
    wall1_uvs = fn(wall1).numUVs("map1")
    res = tb["run_auto_uv"](asset)
    act = {r["mesh"]: r["action"] for r in res["rows"]}
    check("Auto UV reports the marks", act.get(wall1) == "keep UVs" and act.get(post) == "hands off" and
          act.get(wall2) == "unwrapped", "%s / %s / %s" % (act.get(wall1), act.get(post), act.get(wall2)))
    check("Keep UVs mesh isn't re-cut", fn(wall1).numUVs("map1") == wall1_uvs, "%d UVs" % wall1_uvs)
    check("Hands off mesh is untouched (UVs and UV sets)",
          [list(a) for a in fn(post).getUVs("map1")] == post_uvs and fn(post).getUVSetNames() == post_sets,
          str(fn(post).getUVSetNames()))
    post_tiles = set(t for t, _, _ in tb["uv_footprints"](post))
    packed = set(t for _, t in res["tiles"])
    check("Auto UV packing avoids the hands-off tiles", packed and not (packed & post_tiles),
          "hands off on %s, packed into %s" % (sorted(post_tiles), sorted(packed)))

    # --- layout: pack around a small hands-off piece
    asset.set_uv_status([pane], "handsoff")
    pane_uvs = [list(a) for a in fn(pane).getUVs("map1")]
    settings = dict(tb["LAYOUT_DEFAULTS"], texel_density=128.0, map_size="2048")
    col = tb["collect_shells"](asset)
    fixed = col["fixed"]
    fixed_tiles = sorted(set(f["udim"] for f in fixed))
    pane_tile = [f["udim"] for f in fixed if f["mesh"] == pane][0]
    check("layout reads hands-off shells as fixed footprints", fixed and
          not any(sh.mesh in (post, pane) for g in col["groups"] for sh in g["shells"]),
          "%d fixed shells on %s" % (len(fixed), fixed_tiles))
    plan = tb["make_plan"](col, dict(settings, handsoff_tiles="Pack around them"))
    pad = settings["padding_px"] / 2048.0
    in_fixed = [p for p in plan["placements"].values() if udim(p) in fixed_tiles]
    clash = 0
    for p in in_fixed:
        for f in fixed:
            if f["udim"] != udim(p):
                continue
            b = f["box"]
            if p[2] < b[2] + pad - 1e-9 and b[0] < p[2] + p[6] + pad - 1e-9 and \
                    p[3] < b[3] + pad - 1e-9 and b[1] < p[3] + p[7] + pad - 1e-9:
                clash += 1
    check("Pack around: other pieces use the free space in hands-off tiles", any(
        udim(p) == pane_tile for p in in_fixed), "%d pieces in tiles %s" % (len(in_fixed), fixed_tiles))
    check("Pack around: nothing lands on (or within padding of) a hands-off shell", clash == 0,
          "%d too close" % clash)
    tiles_around = len(plan["new_tiles"])
    tb["apply_layout"](asset, col, plan)
    check("Apply leaves hands-off UVs exactly as they were",
          [list(a) for a in fn(pane).getUVs("map1")] == pane_uvs and
          [list(a) for a in fn(post).getUVs("map1")] == post_uvs)
    val = tb["validate_layout"](asset)
    others = [it for it in val["items"]["overlap"] if it["mesh"] != post]  # the post's own UVs are scrambled
    dens = [it for it in val["items"]["density"] if it["mesh"] in (post, pane)]
    check("validation: no new overlaps; hands-off density isn't flagged", not others and not dens,
          "%d overlaps, %d density" % (len(others), len(dens)))
    unit = 0.01 ** 2
    expected = sum(len(tb["_mesh_shells"](m, "map1", unit)) for m in asset.meshes()[0])
    check("validation still checks hands-off shells (overlaps, tiles, padding)", val["shells"] == expected and
          len(tb["_mesh_shells"](pane, "map1", unit)) > 0, "%d of %d shells checked" % (val["shells"], expected))

    # --- layout: reserve their tiles
    col = tb["collect_shells"](asset)
    plan = tb["make_plan"](col, dict(settings, handsoff_tiles="Reserve their tiles"))
    in_fixed = [p for p in plan["placements"].values() if udim(p) in fixed_tiles]
    check("Reserve: nothing else goes in hands-off tiles", not in_fixed, "%d pieces" % len(in_fixed))
    warned = [w for w in plan["warnings"] if str(pane_tile) in w and "Pack around" in w]
    check("Reserve: warns when a small hands-off piece leaves its tile mostly empty", warned,
          warned[0] if warned else str(plan["warnings"]))
    check("Reserve needs at least as many new tiles as Pack around", len(plan["new_tiles"]) >= tiles_around,
          "%d vs %d" % (len(plan["new_tiles"]), tiles_around))
    stats = [st for st in plan["stats"].values() if st.get("handsoff")]
    check("group stats count hands-off pieces and their tiles", stats and all(
        set(st["tiles"]) & set(fixed_tiles) for st in stats), str([(s["key"], s["tiles"]) for s in stats]))
    fit = tb["make_plan"](col, dict(settings, mode="Fit to tiles", max_tiles=6))
    check("Fit to tiles still keeps its budget with hands-off tiles", len(fit["new_tiles"]) <= 6,
          "%d tiles at %.0f px/m" % (len(fit["new_tiles"]), fit["density"]))

    # --- packer unit: free space around a blocked box
    free = tb["_TilePacker"].free_around([(0.3, 0.3, 0.7, 0.7)], 0.01)
    pk = tb["_TilePacker"]((0, 0), 0.01)
    pk.use_free(free)
    placed = []
    for _ in range(200):
        spot = pk.find(0.06, 0.06)
        if spot is None:
            break
        pk.place(spot, 0.06, 0.06)
        placed.append((spot[3], spot[4]))
    bad = [q for q in placed if q[0] < 0.71 - 1e-9 and q[0] + 0.06 > 0.3 + 1e-9 and q[1] < 0.71 - 1e-9 and
           q[1] + 0.06 > 0.3 + 1e-9]
    check("packer fills around a blocked box without touching it", len(placed) > 100 and not bad,
          "%d placed, %d on the box" % (len(placed), len(bad)))

    # --- back to auto
    asset.set_uv_status([post, pane, wall1], "auto")
    check("Auto clears the marks", not asset.uv_status())


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
