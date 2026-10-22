"""Headless tests for Smart UDIM section tools (mayapy).

    mayapy tests/test_sections.py

Section from group, move to section, delete section, empty-group pruning,
group selection and later Scans.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")

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


def shader(name, rgb):
    mat = cmds.shadingNode("lambert", asShader=True, name=name)
    cmds.setAttr(mat + ".color", *rgb, type="double3")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name + "SG")
    cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader")
    return sg


def build():
    house = cmds.group(empty=True, name="house_GRP")
    west = cmds.group(empty=True, name="westWing_GRP", parent=house)
    east = cmds.group(empty=True, name="eastWing_GRP", parent=house)
    made = {}
    for name, parent in (("woodGreen_C_beam0001_GEP", west), ("woodGreen_C_beam0002_GEP", west),
                         ("glassClear_F_window0001_GEP", west), ("brickRed_B_wall0001_GES", east),
                         ("woodGreen_C_beam0003_GEP", east)):
        node = cmds.parent(cmds.polyCube(name=name)[0], parent)[0]
        made[name] = cmds.ls(node, long=True)[0]
    mixed = cmds.parent(cmds.polyCube(name="trimPiece", sx=2)[0], west)[0]
    made["trimPiece"] = cmds.ls(mixed, long=True)[0]
    cmds.sets(mixed + ".f[0:4]", edit=True, forceElement=shader("paintedTrim_MAT", (1, 0, 0)))
    cmds.sets(mixed + ".f[5:]", edit=True, forceElement=shader("metal_rusty", (0.4, 0.4, 0.4)))
    return house, west, east, made


def where(asset, mesh):
    """{(section key, material key)} holding the mesh (or some of its faces)."""
    out = set()
    for sec in asset.sections():
        for mat in asset.materials(sec):
            if mesh in tb["expand_members"](mat)[0]:
                out.add((tb["parse_group_name"](sec)["key"], tb["parse_group_name"](mat)["key"]))
    return out


def empty_groups(asset):
    return [m for s in asset.sections() for m in asset.materials(s) if not cmds.sets(m, q=True)]


def run():
    global tb
    tb = load_toolbox()
    A = tb["SmartUdimAsset"]
    house, west, east, made = build()
    asset = A.for_group(house)
    asset.scan()
    check("a plain scan makes one section", [tb["parse_group_name"](s)["key"] for s in asset.sections()] ==
          ["house"])
    check("section names come from group names", A.section_name_for("|a|westWing_GRP") == "westWing" and
          A.section_name_for("porch_01_GRP") == "porch" and A.section_name_for("roof") == "roof")

    # --- section from group
    sec, moved = asset.section_from_group(west)
    beam = made["woodGreen_C_beam0001_GEP"]
    check("section from group takes every mesh inside, keeping material groups",
          tb["parse_group_name"](sec)["key"] == "westWing" and where(asset, beam) == {("westWing", "woodGreen")} and
          where(asset, made["glassClear_F_window0001_GEP"]) == {("westWing", "glassClear")} and
          where(asset, made["woodGreen_C_beam0003_GEP"]) == {("house", "woodGreen")},
          "%s / %s" % (where(asset, beam), where(asset, made["woodGreen_C_beam0003_GEP"])))
    check("faces split across two material groups stay split", where(asset, made["trimPiece"]) ==
          {("westWing", "paintedTrimMAT"), ("westWing", "metalRusty")}, str(where(asset, made["trimPiece"])))
    check("emptied material groups are tidied away", not empty_groups(asset), str(empty_groups(asset)))
    cmds.undo()
    check("one Ctrl+Z undoes it", len(asset.sections()) == 1 and where(asset, beam) == {("house", "woodGreen")})
    cmds.redo()
    again, _ = asset.section_from_group(west)
    check("doing it again reuses the linked section", len(asset.sections()) == 2 and again == sec)

    # --- selecting a group selects every mesh under it
    cmds.select(east)
    items = tb["selection_items"]()
    check("a selected group counts as every mesh under it", set(items) == {
        made["brickRed_B_wall0001_GES"], made["woodGreen_C_beam0003_GEP"]}, str(sorted(items)))

    # --- move to section
    asset.move_to_section({made["woodGreen_C_beam0003_GEP"]: None}, sec)
    check("move to section keeps the material group", where(asset, made["woodGreen_C_beam0003_GEP"]) ==
          {("westWing", "woodGreen")})
    asset.move_to_section({made["trimPiece"]: {0, 1}}, asset.sections()[0])
    check("moving some faces moves just those faces", where(asset, made["trimPiece"]) ==
          {("house", "paintedTrimMAT"), ("westWing", "paintedTrimMAT"), ("westWing", "metalRusty")},
          str(where(asset, made["trimPiece"])))

    # --- a later scan sorts new meshes under the group into its section
    new = cmds.ls(cmds.parent(cmds.polyCube(name="woodGreen_C_beam0009_GEP")[0], west)[0], long=True)[0]
    asset.scan()
    check("Scan sorts new meshes in a linked group into its section", where(asset, new) ==
          {("westWing", "woodGreen")}, str(where(asset, new)))

    # --- rename and delete
    renamed = asset.rename_section(sec, "leftWing")
    check("rename a section", tb["parse_group_name"](renamed)["key"] == "leftWing")
    moved = asset.delete_section(renamed)
    check("delete section sends its meshes to another section", len(asset.sections()) == 1 and
          where(asset, beam) == {("house", "woodGreen")} and where(asset, new) == {("house", "woodGreen")} and
          moved >= 5 and not empty_groups(asset), "%d moved, %s" % (moved, where(asset, beam)))
    cmds.undo()
    check("delete section is one Ctrl+Z", len(asset.sections()) == 2 and
          where(asset, beam) == {("leftWing", "woodGreen")})
    cmds.redo()
    try:
        asset.delete_section(asset.sections()[0])
        ok = False
    except RuntimeError:
        ok = True
    check("the last section can't be deleted", ok and len(asset.sections()) == 1)
    snap = asset.read()
    check("nothing unassigned or doubled up after all that", not snap["unassigned"] and not snap["overlaps"],
          "%s %s" % (snap["unassigned"], snap["overlaps"]))


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
