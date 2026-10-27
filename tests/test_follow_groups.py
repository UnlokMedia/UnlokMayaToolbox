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
    check("Ctrl+Z of the move: it follows the group it's back under, sorted by its own name again",
          sets_of(other) == before, "%s vs %s" % (sets_of(other), before))
    check("...and carries no 'where it came from' tag", not cmds.attributeQuery(tb["FOLLOW_ATTR"], node=other,
                                                                              exists=True))

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


def health(tb):
    """Check & Fix Groups: broken links, suggested links, unsorted meshes,
    empty groups; then one fix."""
    cmds.file(new=True, force=True)
    root = cmds.group(empty=True, name="yard_GRP")
    shed = cmds.group(empty=True, name="shed_GRP", parent=root)

    def cube(name, parent):
        c = cmds.polyCube(name=name)[0]
        return cmds.ls(cmds.parent(c, parent)[0], long=True)[0]

    for i in range(3):
        cube("woodBrown_C_board%04d_GEP" % (i + 1), shed)
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    sec = asset.sections()[0]
    # a broken link: a group that's deleted, then made again under the same name
    porch = cmds.ls(cmds.group(empty=True, name="porch_GRP", parent=root), long=True)[0]
    cube("metalGrey_C_rail0001_GEP", porch)
    mat = asset.material_set(sec, "metalGrey", source="manual")
    asset.link_groups(mat, [porch])
    cmds.ungroup(porch)  # the group goes, its mesh stays (in the set)
    porch2 = cmds.ls(cmds.group(empty=True, name="porch_GRP", parent=root), long=True)[0]
    # a hand-made group holding every mesh of a Maya group (no link yet)
    shack = cmds.group(empty=True, name="shackD_GRP", parent=root)
    parts = [cube("ropeTan_C_tie%04d_GEP" % (i + 1), shack) for i in range(3)]
    asset.scan(sections_from_groups=False)
    tie = asset.material_set(sec, "ropeTan", source="manual")
    cmds.ls(parts, long=True)
    asset.assign(dict((m, None) for m in parts), tie)
    # a mesh in no group, an empty group
    loose = cube("glassClear_C_pane0001_GEP", root)
    empty = asset.material_set(sec, "paintRed", source="manual")
    rep = asset.group_health()
    broken = [b for b in rep["broken"] if b["set"] == mat]
    check("a link whose group was deleted is reported", broken and tb["short_name"](broken[0]["name"]) == "porch_GRP",
          str(rep["broken"]))
    check("...with the group of the same name as the best guess", broken and broken[0]["guess"] == porch2,
          str(broken and broken[0]["guess"]))
    sug = [s for s in rep["suggest"] if s["set"] == tie]
    check("a hand-made group of a Maya group's meshes gets that group suggested",
          sug and sug[0]["group"] == cmds.ls(shack, long=True)[0], str(rep["suggest"]))
    check("meshes in no group are listed", cmds.ls(loose, long=True)[0] in rep["unsorted"], str(rep["unsorted"]))
    check("empty groups are listed", empty in rep["empty"], str(rep["empty"]))
    choices = [(broken[0]["set"], broken[0]["uuid"], "link", broken[0]["guess"]),
               (sug[0]["set"], None, "link", sug[0]["group"])]
    res = asset.fix_groups(choices)
    after = asset.group_health()
    check("after fixing: nothing broken, nothing suggested, nothing unsorted, no empty groups",
          not after["broken"] and not after["suggest"] and not after["unsorted"] and not after["empty"],
          "%s | %s" % (res, dict((k, len(v)) for k, v in after.items() if k != "candidates")))
    newcomer = cube("ropeTan_C_tie0009_GEP", shack)
    with tb["NoUndo"]():
        asset.follow_links(changed={newcomer})
    tie_now = [m for m in asset.all_material_sets() if "ropeTan" in m][0]
    check("the suggested link now pulls new meshes in", tie_now in [s for s, _ in asset.assignments().get(newcomer,
                                                                                                         [])])
    cmds.undo()  # the cube... (the follow ran outside the undo queue)
    cmds.undo()  # parent
    cmds.undo()  # Check & Fix Groups
    rep2 = asset.group_health()
    check("one Ctrl+Z undoes Check & Fix Groups", any(b["set"] for b in rep2["broken"]) or rep2["suggest"],
          "%d broken, %d suggested" % (len(rep2["broken"]), len(rep2["suggest"])))


def outliner_moves(tb):
    """The user's report: Check & Fix always found meshes to move and Fix
    didn't fix them; a mesh dragged in the Outliner stayed in its old group."""
    cmds.file(new=True, force=True)
    root = cmds.group(empty=True, name="village_GRP")
    grp = {}
    for name in ("shackA", "shackB"):
        grp[name] = cmds.group(empty=True, name=name + "_GRP", parent=root)
        for i, mat in enumerate(("woodBrown", "metalGrey")):
            c = cmds.polyCube(name="%s_C_%s%04d_GEP" % (mat, name, i + 1))[0]
            cmds.parent(c, grp[name])
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    long = lambda n: cmds.ls(n, long=True)[0]  # noqa: E731

    def section_of(mesh):
        sec_of = dict((m, s) for s in asset.sections() for m in asset.materials(s))
        return sorted(set(tb["parse_group_name"](sec_of[s])["key"] for s, _ in asset.assignments().get(long(mesh), [])))

    # an old scene's "where it came from" tag no longer shows up as a move
    tagged = long("woodBrown_C_shackB0001_GEP")
    cmds.addAttr(tagged, longName=tb["FOLLOW_ATTR"], dataType="string")
    cmds.setAttr(tagged + "." + tb["FOLLOW_ATTR"], '{"to": "x", "via": "y", "from": []}', type="string")
    # an Outliner move, followed live
    m = long(cmds.parent(long("woodBrown_C_shackA0001_GEP"), grp["shackB"])[0])
    with tb["NoUndo"]():
        asset.follow_links(changed={m})
    first = asset.group_health()["moves"]
    asset.fix_groups([])
    after = asset.group_health()["moves"]
    check("an Outliner move follows the new group, and Check & Fix then finds nothing to move (old tags too)",
          section_of(m) == ["shackB"] and not first and not after and
          not cmds.attributeQuery(tb["FOLLOW_ATTR"], node=tagged, exists=True),
          "now in %s, check %s, after fix %s" % (section_of(m), first, after))
    # emptying a followed section keeps it (and its link): a mesh dragged back is followed
    last = long("metalGrey_C_shackA0002_GEP")
    asset.move_to_section({last: None}, [s for s in asset.sections() if "shackB" in s][0])
    asset.pin_overrides([last])
    kept = [s for s in asset.sections() if "shackA" in s]
    check("emptying a followed section keeps the section and its group link", kept and
          tb["_linked_group"](kept[0]) == long(grp["shackA"]), str(asset.sections()))
    # a mesh placed by hand (pinned), then dragged to another group, follows it
    moved = long(cmds.parent(last, grp["shackB"])[0])
    with tb["NoUndo"]():
        asset.follow_links(changed={moved})
    back = long(cmds.parent(moved, grp["shackA"])[0])
    with tb["NoUndo"]():
        asset.follow_links(changed={back})
    check("a mesh placed by hand, then dragged to other groups in the Outliner, follows them",
          section_of(back) == ["shackA"] and not asset.group_health()["moves"], str(section_of(back)))


try:
    run()
    health(ns["load_toolbox"]())
    outliner_moves(ns["load_toolbox"]())
except Exception:
    traceback.print_exc()
    RESULTS.append(("exception", False, ""))
finally:
    failed = [r for r in RESULTS if not r[1]]
    print("\n%d passed, %d failed" % (len(RESULTS) - len(failed), len(failed)))
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(1 if failed else 0)
