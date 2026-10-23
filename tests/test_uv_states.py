"""Headless tests for UV states, status colours and Auto UV Selected (mayapy).

    mayapy tests/test_uv_states.py
"""

import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "uv_states_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def shader(name, rgb):
    mat = cmds.shadingNode("lambert", asShader=True, name=name)
    cmds.setAttr(mat + ".color", *rgb, type="double3")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name + "SG")
    cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader")
    return sg


def setup(tb):
    root, kinds = ns["build_building"]()
    cmds.scale(100, 100, 100, root)
    cmds.makeIdentity(root, apply=True, scale=True)
    trim = cmds.polyCube(name="trimPiece", sx=2)[0]
    trim = cmds.ls(cmds.parent(trim, root + "|westWing_GRP")[0], long=True)[0]
    cmds.sets(trim + ".f[0:4]", edit=True, forceElement=shader("paintedTrim_MAT", (1, 0, 0)))
    cmds.sets(trim + ".f[5:]", edit=True, forceElement=shader("metal_rusty", (0.4, 0.4, 0.4)))
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    return root, kinds, trim, asset


def sg_of(tb, mesh):
    return sorted(tb["_shading_of"](mesh))


def run():
    tb = ns["load_toolbox"]()
    cmds.loadPlugin("Unfold3D", quiet=True)
    root, kinds, trim, asset = setup(tb)
    by = {m.split("|")[-1]: m for m in list(kinds) + [trim]}
    keep, off = by["brickRed_C_wall0001_GEP"], by["woodBrown_C_post0001_GEP"]
    asset.set_uv_status([keep], "keep")
    asset.set_uv_status([off], "handsoff")

    # --- check UVs -> states
    rows = tb["run_auto_uv"](asset, analyse_only=True)["rows"]
    scores = {r["mesh"]: r["before"] for r in rows if r["before"] is not None}
    states = tb["uv_states"](asset, scores)
    check("states from marks and scores", states[keep] == "keep" and states[off] == "handsoff" and
          states[by["brickRed_C_wall0002_GEP"]] == "needs" and states[by["stoneGrey_C_column0001_GEP"]] == "good",
          str(sorted(set(states.values()))))
    check("unscored meshes are 'not checked'", tb["uv_states"](asset)[by["brickRed_C_wall0002_GEP"]] == "unknown")

    # --- colours on: preview materials, real shading remembered
    trim_before = tb["_shading_of"](trim)
    tb["show_uv_colours"](asset, states)
    check("colours: each mesh gets its state's preview material",
          sg_of(tb, keep) == ["unlokUV_keep_SG"] and sg_of(tb, by["brickRed_C_wall0002_GEP"]) == ["unlokUV_needs_SG"]
          and sg_of(tb, off) == ["unlokUV_handsoff_SG"] and tb["uv_colours_on"](asset),
          "%s / %s" % (sg_of(tb, keep), sg_of(tb, by["brickRed_C_wall0002_GEP"])))
    cmd_groups = sorted(tb["shader_face_groups"](trim))
    check("while coloured, Scan still sees the real shaders", cmd_groups == ["metalRusty", "paintedTrimMAT"],
          str(cmd_groups))
    check("colours add no undo steps", (cmds.undoInfo(q=True, undoName=True) or "") != "")  # nothing new queued

    # --- Auto UV with live colours: unwrapped meshes go green, tracked in the Auto UV'd set
    res = tb["run_auto_uv"](asset, colours=True)
    auto = asset.tool_members("auto")
    unwrapped = [r["mesh"] for r in res["rows"] if r["action"] == "unwrapped"]
    check("Auto UV puts what it unwrapped in the Auto UV'd set", unwrapped and set(unwrapped) <= auto and
          keep not in auto, "%d unwrapped, %d in set" % (len(unwrapped), len(auto)))
    trouble = [r["mesh"] for r in res["rows"] if r["action"] in ("failed", "check")]
    check("failures and poor results go in the Problem set", set(trouble) <= asset.tool_members("problem"),
          str([m.split("|")[-1] for m in trouble]))
    states = tb["uv_states"](asset, {r["mesh"]: r["before"] for r in res["rows"] if r["before"] is not None})
    check("unwrapped meshes are 'auto' and coloured as they finished",
          all(states[m] in ("auto", "problem") for m in unwrapped) and
          all(sg_of(tb, m) == ["unlokUV_auto_SG"] for m in unwrapped if states[m] == "auto"))
    cmds.undo()
    check("one Ctrl+Z undoes the run, tracking sets included", not asset.tool_members("auto"))
    cmds.redo()

    # --- layout -> laid out
    col = tb["collect_shells"](asset)
    plan = tb["make_plan"](col, dict(tb["LAYOUT_DEFAULTS"], texel_density=128.0, map_size="2048"))
    tb["apply_layout"](asset, col, plan)
    laid = asset.tool_members("laidout")
    states = tb["uv_states"](asset, {})
    check("Smart Layout puts what it placed in the Laid out set", laid and states[keep] == "laidout" and
          states[off] == "handsoff", "%d laid out" % len(laid))

    # --- save / reopen with colours on, then colours off restores real shading
    tb["show_uv_colours"](asset, states)
    scene = os.path.join(tempfile.mkdtemp(prefix="uvstates"), "b.ma")
    cmds.file(rename=scene)
    cmds.file(save=True, type="mayaAscii")
    cmds.file(new=True, force=True)
    cmds.file(scene, open=True, force=True)
    asset = tb["SmartUdimAsset"].all()[0]
    trim = cmds.ls("trimPiece", long=True)[0]
    check("colours and tracking survive save / reopen", tb["uv_colours_on"](asset) and
          sg_of(tb, trim) != sorted(trim_before) and asset.tool_members("laidout"))
    tb["hide_uv_colours"](asset)
    check("colours off puts the real shading back exactly (per face too)",
          tb["_shading_of"](trim) == trim_before and not tb["uv_colours_on"](asset) and
          not cmds.ls("unlokUV_*_SG"), "%s vs %s" % (tb["_shading_of"](trim), trim_before))

    # --- Auto UV Selected: only those meshes, only their groups packed
    cmds.file(new=True, force=True)
    root, kinds, trim, asset = setup(tb)
    west = [m for m in asset.meshes()[0] if "|westWing_GRP|" in m]
    east = [m for m in asset.meshes()[0] if "|eastWing_GRP|" in m]
    east_uvs = {m: cmds.polyEditUV(m + ".map[*]", query=True) for m in east
                if cmds.polyEvaluate(m, uvcoord=True)}
    res = tb["run_auto_uv"](asset, only=west)
    done = set(r["mesh"] for r in res["rows"])
    check("Auto UV Selected only works on the selection", done <= set(west) and
          asset.tool_members("auto") <= set(west) and asset.tool_members("auto"),
          "%d rows, %d in Auto UV'd" % (len(done), len(asset.tool_members("auto"))))
    check("meshes outside the selection keep their UVs",
          all(cmds.polyEditUV(m + ".map[*]", query=True) == uvs for m, uvs in east_uvs.items()))
    west_sec = [s for s in asset.sections() if "westWing" in s][0]
    west_sets = set(asset.materials(west_sec))
    check("it packs only the groups the selection is in", res["tiles"] and
          all(mat in west_sets for mat, _ in res["tiles"]), str([m for m, _ in res["tiles"]]))
    # a mesh Auto UV did earlier, later marked Hands off, must not move when its
    # group is packed again for another selected mesh
    posts = sorted(m for m in asset.tool_members("auto") if "post" in m and "|westWing_GRP|" in m)
    off, other = posts[0], posts[1]
    asset.set_uv_status([off], "handsoff")
    before = cmds.polyEditUV(off + ".map[*]", query=True)
    tb["run_auto_uv"](asset, only=[other])
    check("Auto UV Selected never moves a Hands off mesh in the same group",
          cmds.polyEditUV(off + ".map[*]", query=True) == before)

    # --- Skip scoring: every unmarked mesh is unwrapped, marks still respected
    cmds.file(new=True, force=True)
    root, kinds, trim, asset = setup(tb)
    by = {m.split("|")[-1]: m for m in list(kinds) + [trim]}
    kept = by["stoneGrey_C_column0001_GEP"]
    asset.set_uv_status([kept], "keep")
    kept_uvs = cmds.polyEvaluate(kept, uvcoord=True)
    res = tb["run_auto_uv"](asset, score=False, pack=False)
    act = {r["mesh"]: r for r in res["rows"]}
    good = by["stoneGrey_C_column0002_GEP"]  # good UVs, not marked: scoring would have kept it
    check("Skip scoring unwraps every unmarked mesh, even ones with good UVs",
          act[good]["action"] in ("unwrapped", "check") and act[good]["before"] is None and
          "Scoring UVs" not in str(res.get("timing")), "%s / before %s" % (act[good]["action"], act[good]["before"]))
    check("...but still never touches Keep UVs meshes", act[kept]["action"] == "keep UVs" and
          cmds.polyEvaluate(kept, uvcoord=True) == kept_uvs)
    check("Check UVs still scores when asked", all(
        r["before"] is not None for r in tb["run_auto_uv"](asset, analyse_only=True, score=False)["rows"]
        if r["action"] not in ("hands off", "skip")))

    # --- problem bookkeeping and the inspector's diagnosis
    rows = dict((r["mesh"], r) for r in res["rows"])
    unwrapped = [m for m, r in rows.items() if r["action"] in ("unwrapped", "check")]
    check("rows after unwrapping explain the result, not the old score",
          all(rows[m]["reason"].startswith("unwrapped") for m in unwrapped),
          str([rows[m]["reason"] for m in unwrapped][:3]))
    victim = by["stoneGrey_C_column0003_GEP"]
    cmds.polyEditUV(victim + ".map[0:3]", scaleU=12.0, scaleV=12.0)  # wreck a few faces
    detail = {}
    score, why = tb["uv_quality"](victim, detail=detail)
    check("uv_quality says what's wrong and how much", "stretched" in why and "%" in why and detail.get("stretched"),
          "%.2f %s, %d stretched faces" % (score, why, len(detail.get("stretched", []))))
    asset.update_tool_sets(add={"problem": [victim]})
    st = tb["uv_states"](asset)
    check("a flagged mesh is red", st[victim] == "problem")
    asset.set_uv_status([victim], "keep")
    st = tb["uv_states"](asset)
    check("marking it Keep UVs makes it green and drops the flag", st[victim] == "keep" and
          victim not in asset.tool_members("problem"))
    asset.set_uv_status([victim], "auto")
    check("...and it doesn't come back when the mark is cleared", tb["uv_states"](asset)[victim] != "problem")


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
