"""Headless tests for Smart UDIM's saved session (mayapy).

    mayapy tests/test_session.py

The panel's progress (reports, Auto UV results, validation, settings) is
stored on the asset's root set, so it's saved with the scene and picked up
again on reopen. This checks the engine side: the data round-trips through
a real save / reopen, validation packs and unpacks, missing meshes drop out,
and saving never adds an undo step.
"""

import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "session_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
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
    root, kinds = ns["build_building"]()
    cmds.scale(100, 100, 100, root)
    cmds.makeIdentity(root, apply=True, scale=True)
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    check("a new setup has no saved session", tb["load_session"](asset) == {})

    auto = tb["run_auto_uv"](asset)
    col = tb["collect_shells"](asset)
    plan = tb["make_plan"](col, dict(tb["LAYOUT_DEFAULTS"], texel_density=128.0, map_size="2048"))
    tb["apply_layout"](asset, col, plan)
    val = tb["validate_layout"](asset, target_density=256.0)  # off target: plenty of findings to keep
    data = {"version": 1, "saved": "22 Oct 14:32", "saved_at": 1.0, "report": {"ngons": {root: 3}},
            "auto": auto, "layout_applied": {"tiles": len(plan["new_tiles"]), "density": plan["density"]},
            "validation": tb["pack_validation"](val), "settings": {"lay_density": 128.0, "uv_set": "map1"}}
    marker = cmds.polyEditUV(list(kinds)[0] + ".map[0]", query=True)
    tb["save_session"](asset, data)
    cmds.undo()  # must undo the layout, not the session write
    check("saving the session adds no undo step",
          tb["load_session"](asset).get("saved") == "22 Oct 14:32" and
          cmds.polyEditUV(list(kinds)[0] + ".map[0]", query=True) != marker)
    cmds.redo()

    scene = os.path.join(tempfile.mkdtemp(prefix="udimsession"), "building.ma")
    cmds.file(rename=scene)
    cmds.file(save=True, type="mayaAscii")
    cmds.file(new=True, force=True)
    cmds.file(scene, open=True, force=True)
    assets = tb["SmartUdimAsset"].all()
    loaded = tb["load_session"](assets[0]) if assets else {}
    check("the session survives saving and reopening the scene", len(assets) == 1 and
          loaded.get("saved") == "22 Oct 14:32" and len(loaded["auto"]["rows"]) == len(auto["rows"]) and
          loaded["settings"]["lay_density"] == 128.0, "%d rows" % len(loaded.get("auto", {}).get("rows", [])))
    check("summary says how far it got", tb["session_summary"](loaded) ==
          "pre-process, Auto UV, layout applied, validated", tb["session_summary"](loaded))
    back = tb["unpack_validation"](loaded["validation"])
    same = all(sorted((i["mesh"], tuple(i["faces"])) for i in back["items"][c]) ==
               sorted((i["mesh"], tuple(i["faces"])) for i in val["items"][c][:tb["SESSION_MAX_ITEMS"]])
               for c in tb["VALIDATION_ORDER"])
    check("validation results round-trip (faces kept as ranges)", same and back["shells"] == val["shells"],
          "%d shells, %d items" % (back["shells"], sum(len(v) for v in back["items"].values())))
    gone = [i for i in val["items"]["density"] + val["items"]["padding"] + val["items"]["tiny"]][:1]
    victim = gone[0]["mesh"] if gone else list(kinds)[0]
    cmds.delete(victim)
    back = tb["unpack_validation"](loaded["validation"])
    check("deleted meshes drop out of restored results",
          not any(i["mesh"] == victim for v in back["items"].values() for i in v))
    tb["save_session"](assets[0], {})
    check("Start Fresh clears it", tb["load_session"](assets[0]) == {} and
          tb["session_summary"]({}) == "set up")


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
