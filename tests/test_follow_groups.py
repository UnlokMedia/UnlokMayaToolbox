"""Headless tests for sets that follow Maya groups (mayapy).

    mayapy tests/test_follow_groups.py

- a material group following shackA_GRP takes every mesh in it, and new
  meshes added to the group later
- a mesh moved in follows; moved out (or Ctrl+Z of the move) it goes back
- a mesh assigned by hand elsewhere is pinned and left alone
- followed sections sort new meshes (and moved ones) in, keeping materials
- links survive renaming the group; unlinking stops it
- following is cheap when nothing changed
"""

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "follow_groups_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
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
    root = cmds.group(empty=True, name="shed_GRP")
    groups = {}
    for g in ("shackA_GRP", "shackB_GRP"):
        groups[g] = cmds.group(empty=True, name=g, parent=root)
    mk = {}

    def cube(name, parent):
        c = cmds.polyCube(name=name)[0]
        return cmds.ls(cmds.parent(c, parent)[0], long=True)[0]

    for name, grp in (("woodBrown_C_plank0001_GEP", "shackA_GRP"), ("metalGrey_C_sheet0001_GEP", "shackA_GRP"),
                      ("woodBrown_C_plank0002_GEP", "shackB_GRP"), ("metalGrey_C_sheet0002_GEP", "shackB_GRP")):
        mk[name] = cube(name, groups[grp])
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    long = lambda n: cmds.ls(n, long=True)[0]  # noqa: E731

    def sets_of(mesh):
        return sorted(s for s, _ in asset.assignments().get(long(mesh), []))

    def section_key(mesh):
        sec_of = dict((m, s) for s in asset.sections() for m in asset.materials(s))
        return sorted(set(tb["parse_group_name"](sec_of[s])["key"] for s in sets_of(mesh)))

    secA = [s for s in asset.sections() if "shackA" in s][0]
    wood_a = [m for m in asset.materials(secA) if "woodBrown" in m][0]

    # --- link: everything under the group joins the material group
    moved = asset.link_groups(wood_a, [long("shackA_GRP")])
    check("following a group pulls in every mesh under it",
          sets_of("metalGrey_C_sheet0001_GEP") == [wood_a] and sets_of("woodBrown_C_plank0001_GEP") == [wood_a],
          "%d moved" % len(moved))
    check("the snapshot shows what it follows", any(
        long("shackA_GRP") in mat["follows"] for sec in asset.read()["sections"] for mat in sec["materials"]))

    # --- new mesh added to the group later
    new = cube("ropeTan_C_tie0001_GEP", long("shackA_GRP"))
    with tb["NoUndo"]():
        moved = asset.follow_links(changed={new})
    check("a new mesh added to the group joins it automatically", sets_of(new) == [wood_a], str(moved))

    # --- an existing mesh moved in, then out again
    other = long("metalGrey_C_sheet0002_GEP")
    before = sets_of(other)
    moved_in = long(cmds.parent(other, long("shackA_GRP"))[0])
    with tb["NoUndo"]():
        asset.follow_links(changed={moved_in})
    check("a mesh moved into the group follows it", sets_of(moved_in) == [wood_a], str(sets_of(moved_in)))
    cmds.undo()  # Ctrl+Z of the reparent
    with tb["NoUndo"]():
        asset.follow_links(changed={other})
    check("Ctrl+Z of the move puts it back in its old group", sets_of(other) == before,
          "%s vs %s" % (sets_of(other), before))
    check("...and forgets where it came from", not cmds.attributeQuery(tb["FOLLOW_ATTR"], node=other, exists=True))

    # --- pinned: assigned by hand somewhere else, links leave it
    secB = [s for s in asset.sections() if "shackB" in s][0]
    metal_b = [m for m in asset.materials(secB) if "metalGrey" in m][0]
    pinned = long("metalGrey_C_sheet0001_GEP")
    asset.assign({pinned: None}, metal_b)
    with tb["NoUndo"]():
        asset.follow_links(changed={pinned})
    check("a mesh you assign elsewhere by hand stays there (pinned)", sets_of(pinned) == [metal_b],
          str(sets_of(pinned)))

    # --- followed sections: new meshes sorted in by name, moved ones keep their material
    sec_c, _ = asset.section_from_group(cmds.group(empty=True, name="shackC_GRP", parent=root))
    fresh = cube("glassClear_C_pane0001_GEP", long("shackC_GRP"))
    with tb["NoUndo"]():
        asset.follow_links(changed={fresh})
    check("a new mesh in a followed section is sorted into it by name",
          section_key(fresh) == ["shackC"] and "glassClear" in sets_of(fresh)[0], str(sets_of(fresh)))
    plank = long(cmds.parent(long("woodBrown_C_plank0002_GEP"), long("shackC_GRP"))[0])
    with tb["NoUndo"]():
        asset.follow_links(changed={plank})
    check("a mesh moved into a followed section moves there, keeping its material",
          section_key(plank) == ["shackC"] and "woodBrown" in sets_of(plank)[0], str(sets_of(plank)))
    untouched = long("woodBrown_C_plank0001_GEP")
    check("meshes nobody moved stay where they are", sets_of(untouched) == [wood_a])

    # --- renaming the group keeps the link
    cmds.rename(long("shackA_GRP"), "shackA_renamed_GRP")
    late = cube("woodBrown_C_plank0009_GEP", long("shackA_renamed_GRP"))
    with tb["NoUndo"]():
        asset.follow_links(changed={late})
    check("renaming the group keeps the link", sets_of(late) == [wood_a], str(sets_of(late)))

    # --- speed when nothing changed
    big = cmds.group(empty=True, name="crowd_GRP", parent=long("shackA_renamed_GRP"))
    for i in range(400):
        c = cmds.polyCube(name="woodBrown_C_crate%04d_GEP" % i)[0]
        cmds.parent(c, big)
    with tb["NoUndo"]():
        asset.follow_links(changed={long(big)})
    t = time.time()
    with tb["NoUndo"]():
        again = asset.follow_links(changed=set())
    secs = time.time() - t
    check("following is cheap when nothing changed", not again and secs < 0.5, "%.3fs for %d meshes" % (
        secs, len(asset.meshes()[0])))

    # --- unlink
    asset.unlink_groups(wood_a)
    after = cube("woodBrown_C_plank0010_GEP", long("shackA_renamed_GRP"))
    with tb["NoUndo"]():
        asset.follow_links(changed={after})
    check("after Stop Following, new meshes go by the section again (by name)",
          sets_of(after) and sets_of(after) != [wood_a] or section_key(after) == ["shackA"], str(sets_of(after)))


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
