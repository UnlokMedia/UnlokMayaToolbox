"""Headless tests for the Renamer (UnlokRenamer inside the toolbox; mayapy).

    mayapy tests/test_renamer.py

The naming maths matches the standalone unlok_renamer.py (loaded from the
UnlokRenamer repo next to this one, when it's there) over a corpus of
names; Set From Selection reads every format back into fields that rebuild
the same name; renaming several objects numbers them and is one Ctrl+Z;
the family fix gives the documented results, is idempotent and one Ctrl+Z;
each check finds what it should.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
STANDALONE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "UnlokRenamer", "build", "unlok_renamer.py"))

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def load_toolbox():
    ns = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    return ns


def load_standalone():
    if not os.path.isfile(STANDALONE):
        return None
    ns = {"__name__": "unlok_renamer_ref", "__file__": STANDALONE}
    with open(STANDALONE) as f:
        exec(compile(f.read(), STANDALONE, "exec"), ns)
    return ns


CORPUS = [
    "paintGrey_C_wing0001_GEP", "paintGrey_C_wing_0001_GEP", "wing_GEP1", "wing_GEP", "wing0002_GEP",
    "glassClearA_F_pane0001_GEP", "glassClear_F_pane0002_GEP", "glassClearC_F_pane0003_GEP",
    "woodMoulding_L_trim_GES", "steel_C_beam0001_GEP", "pCube1", "MainGroup_GRP", "MainGroup_0001_GRP",
    "group_GRP3", "a1_GES", "a0001_GES", "stone_C_wall12_PLY", "brickRed_B_wall0001_CRV", "x_y_z",
    "chair0003_GES", "paintGrey_C_hiResBlockA_GEP", "paintGrey_X_hiResBlockA0001_GEO", "_GEP", "GEP",
]


def rename_all(nodes, names):
    out = []
    for n, name in zip(nodes, names):
        out.append(cmds.rename(n, name))
    return out


def main():
    tb = load_toolbox()
    ref = load_standalone()

    # --- the shared maths matches the standalone tool
    if ref is None:
        print("(UnlokRenamer repo not found at %s: parity checks skipped)" % STANDALONE)
    else:
        sw = ref["SanityCheckWidget"]
        diffs = []
        for name in CORPUS:
            pairs = [("parse_name", tb["ur_parse_name"](name), ref["parse_name"](name)),
                     ("family_key", tb["ur_family_key"](name), ref["family_key"](name)),
                     ("invalid_reason", tb["ur_invalid_reason"](name), sw.invalid_reason(None, name)),
                     ("soft_reasons", tb["ur_soft_reasons"](name), sw.soft_reasons(None, name)),
                     ("split", tb["ur_split_material_color_variant"](name.split("_")[0]),
                      ref["split_material_color_variant"](name.split("_")[0]))]
            diffs += ["%s(%s): %r != %r" % (k, name, a, b) for k, a, b in pairs if a != b]
        check("parse / family / invalid / soft / material split match unlok_renamer.py", not diffs, diffs[:3])
        check("material variant issues match unlok_renamer.py",
              tb["ur_material_variant_issues"](CORPUS) == ref["material_variant_issues"](CORPUS))
        for args in (("wing", "GEP", 3, False, 4), ("wing", "GEP", 12, True, 4), ("", "GES", 1, True, 4),
                     ("MainGroup", "GRP", 2, True, 4), ("x", None, 7, False, 5)):
            check("compose_name%r matches" % (args,), tb["ur_compose_name"](*args) == ref["compose_name"](*args))
        check("lists match (materials, colours, positions, numbers, suffixes)",
              (tb["UR_MATERIALS"], tb["UR_COLORS"], tb["UR_POSITIONS"], tb["UR_NUMBERS"], tb["UR_SUFFIXES"]) ==
              (ref["MATERIALS"], ref["COLORS"], ref["POSITIONS"], ref["NUMBERS"], ref["SUFFIXES"]))

    # --- names from fields, and Set From Selection reading them back
    gen, read = tb["ur_generate_name"], tb["ur_fields_from_name"]
    d = dict(tb["UR_RENAME_DEFAULTS"], material="paint", color="Grey", position="C", name="hiResBlockA")
    check("default format: attached number", gen(d, 1) == "paintGrey_C_hiResBlockA0001_GES", gen(d, 1))
    check("underscore before number", gen(dict(d, underscore=True), 12) == "paintGrey_C_hiResBlockA_0012_GES")
    check("no numbers", gen(dict(d, use_number=False), 3) == "paintGrey_C_hiResBlockA_GES")
    check("variant letter", gen(dict(d, material="glass", color="Clear", variant="a"), 1) ==
          "glassClearA_C_hiResBlockA0001_GES")
    grp = dict(tb["UR_RENAME_DEFAULTS"], **tb["UR_GROUP_MODE"])
    check("group mode", gen(dict(grp, name="MainGroup"), 1) == "MainGroup_GRP")
    for name in ("paintGrey_C_hiResBlockA0001_GEP", "paintGrey_C_hiResBlockA_0001_GEP",
                 "paintGrey_C_hiResBlockA_GEP", "glassClearB_F_pane00012_PLY", "woodMoulding_L_trim_GES",
                 "MainGroup_GRP", "MainGroup_0001_GRP"):
        fields, err = read(name)
        base = dict(tb["UR_RENAME_DEFAULTS"])
        base.update(tb["UR_GROUP_MODE"] if fields and fields["group"] else tb["UR_GEOMETRY_MODE"])
        base.update(fields or {})
        number = int(name.split("_")[-2][-4:]) if name.split("_")[-2][-1:].isdigit() else 1
        check("Set From Selection round trip: %s" % name, err is None and gen(base, number) == name,
              err or gen(base, number))
    fields, err = read("paintGrey_C_wing_GEP1")
    check("a suffix variant (GEP1) reads as GEP with numbering on",
          err is None and fields["suffix"] == "GEP" and fields["use_number"], fields)
    check("an unknown suffix is reported", read("pCube1")[1] is not None)
    check("a material that isn't word + Word is reported", read("steel_C_beam0001_GEP")[1] is not None)

    # --- the family engine (no scene)
    ft = tb["ur_family_targets"]
    members = [("u%d" % i, "chair%04d_GES" % i) for i in range(1, 6)] + [("dup", "chair0003_GES")]
    out = ft(("chair", "GES"), members)
    check("a duplicated chair0003 in chair0001..0005 becomes chair0006, the rest stay",
          out == [("dup", "chair0006_GES")], out)
    out = dict(ft(("wing", "GEP"), [("u%d" % i, "wing0001_GEP") for i in range(10)]))
    check("ten wing0001_GEP become wing0001..wing0010 (the first keeps 0001)",
          sorted(out.values()) == ["wing%04d_GEP" % i for i in range(2, 11)], sorted(out.values()))
    out = dict(ft(("wing", "GEP"), [("a", "wing_GEP"), ("b", "wing_GEP1"), ("c", "wing_GEP2")]))
    check("wing_GEP / GEP1 / GEP2 become wing0001..0003",
          sorted(out.values()) == ["wing0001_GEP", "wing0002_GEP", "wing0003_GEP"], out)
    out = dict(ft(("a", "GES"), [("x", "a0001_GES"), ("y", "a0001_GES"), ("z", "a0003_GES")]))
    check("a0001, a0001, a0003: only the clash moves, into the gap", out == {"y": "a0002_GES"}, out)
    check("a clean family is left alone", ft(("a", "GES"), [("x", "a0001_GES"), ("y", "a0002_GES")]) == [])

    # --- scene: Rename Selected
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    cubes = [cmds.polyCube(name="pCube%d" % (i + 1))[0] for i in range(3)]
    before = sorted(cmds.ls(type="transform"))
    names = tb["ur_rename"](cubes, dict(d, use_number=False, suffix="GEP"))
    check("renaming 3 objects numbers them (numbers forced on)",
          names == ["paintGrey_C_hiResBlockA%04d_GEP" % i for i in (1, 2, 3)], names)
    cmds.undo()
    check("one Ctrl+Z undoes the whole rename", sorted(cmds.ls(type="transform")) == before,
          sorted(cmds.ls(type="transform")))
    cmds.redo()
    check("redo brings it back", cmds.objExists("paintGrey_C_hiResBlockA0003_GEP"))
    names = tb["ur_rename"](["paintGrey_C_hiResBlockA0001_GEP"], dict(d, name="solo", use_number=False))
    check("one object without numbers stays unnumbered", names == ["paintGrey_C_solo_GES"], names)

    # --- scene: the checks and the fix
    cmds.file(new=True, force=True)
    root = cmds.group(empty=True, name="asset_GRP")
    a = cmds.group(empty=True, name="left_GRP", parent=root)
    b = cmds.group(empty=True, name="right_GRP", parent=root)
    for parent in (a, b):  # same names under two groups: duplicates
        for i in range(1, 4):
            c = cmds.polyCube(name="tmp")[0]
            c = cmds.parent(c, parent)[0]
            cmds.rename(c, "woodBrown_C_plank%04d_GEP" % i)
    for name in ("woodBrown_C_rail_GEP1", "woodBrown_C_rail_GEP2", "woodBrown_C_post7_GEP", "pCube9",
                 "glassClear_F_pane0001_GEP", "glassClearA_F_pane0002_GEP"):
        c = cmds.polyCube(name="tmp")[0]
        c = cmds.parent(c, root)[0]
        cmds.rename(c, name)
    root = cmds.ls(root, long=True)[0]
    tr = tb["ur_transforms"](root)
    dups = tb["ur_scan_duplicates"](tr)
    check("Duplicates: the planks under both groups, one family",
          len(dups) == 1 and len(list(dups.values())[0]) == 6, list(dups))
    inv = tb["ur_scan_invalid"](tr)
    check("Invalid Naming: the rail variants and the under-padded post",
          sorted(sorted(o.split("|")[-1] for o in v) for v in inv.values()) ==
          [["woodBrown_C_post7_GEP"], ["woodBrown_C_rail_GEP1", "woodBrown_C_rail_GEP2"]], list(inv))
    soft = tb["ur_scan_soft"](tr)
    check("Soft Checks: pCube9's suffix", [o.split("|")[-1] for o in soft.get("Unrecognized suffix", [])] ==
          ["pCube9"], soft.keys())
    var = tb["ur_scan_variants"](tr)
    check("Material Variants: glassClear next to glassClearA", len(var) == 1 and "glassClear" in list(var)[0], var)
    names0 = sorted(o.split("|")[-1] for o in tr)
    objects = [o for v in list(dups.values()) + list(inv.values()) for o in v]
    n = tb["ur_fix_families"](root, objects)
    tr2 = tb["ur_transforms"](root)
    check("Fix All renames only what clashes or is malformed", n == 6, n)
    check("after the fix nothing is duplicated or fixable",
          not tb["ur_scan_duplicates"](tr2) and not tb["ur_scan_invalid"](tr2))
    short = sorted(o.split("|")[-1] for o in tr2)
    check("the planks are numbered 1..6, rails 1..2, post keeps 7",
          [s for s in short if "plank" in s] == ["woodBrown_C_plank%04d_GEP" % i for i in range(1, 7)] and
          [s for s in short if "rail" in s] == ["woodBrown_C_rail0001_GEP", "woodBrown_C_rail0002_GEP"] and
          "woodBrown_C_post0007_GEP" in short, short)
    check("a second fix finds nothing to do", tb["ur_fix_families"](root, objects) == 0)
    cmds.undo()
    check("one Ctrl+Z undoes the fix", sorted(o.split("|")[-1] for o in tb["ur_transforms"](root)) == names0)

    print("")
    failed = [r for r in RESULTS if not r[1]]
    print("%d checks, %d failed" % (len(RESULTS), len(failed)))
    for r in failed:
        print("  FAIL", r[0], r[2])
    return not failed


if __name__ == "__main__":
    ok = False
    try:
        ok = main()
    except Exception:
        traceback.print_exc()
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(0 if ok else 1)
