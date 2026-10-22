"""Headless tests for Smart UDIM (milestones 1-2: sets, naming, scan, pre-process).

    mayapy tests/test_smart_udim.py
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


def shader(name, color):
    mat = cmds.shadingNode("lambert", asShader=True, name=name)
    cmds.setAttr(mat + ".color", *color)
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name + "SG")
    cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader")
    return sg


def build_house():
    """house_GRP
         westWing_GRP: woodGreen beams x2, glassClear window, a freeform mesh with 2 shaders
         eastWing_GRP: woodGreen beam, brickRed wall, a badly named mesh, a mesh with no UVs
         roofTile (directly under root, convention name)
    """
    root = cmds.group(empty=True, name="house_GRP")
    west = cmds.group(empty=True, name="westWing_GRP", parent=root)
    east = cmds.group(empty=True, name="eastWing_GRP", parent=root)
    made = {}

    def cube(name, parent, **kw):
        node = cmds.polyCube(name=name, **kw)[0]
        node = cmds.parent(node, parent)[0]
        made[name] = cmds.ls(node, long=True)[0]
        return made[name]

    cube("woodGreen_C_beam0001_GEP", west)
    cube("woodGreen_C_beam0002_GEP", west)
    cube("glassClear_F_window0001_GEP", west)
    mixed = cube("trimPiece", west, sx=2)  # freeform: two shaders per face
    sg_a = shader("paintedTrim_MAT", (1, 0, 0))
    sg_b = shader("metal_rusty", (0.4, 0.4, 0.4))
    cmds.sets(mixed + ".f[0:4]", edit=True, forceElement=sg_a)
    cmds.sets(mixed + ".f[5:]", edit=True, forceElement=sg_b)
    cube("woodGreen_C_beam0003_GEP", east)
    cube("brickRed_B_wall0001_GES", east)
    cube("Mesh_final_v2", east)
    cube("woodGreen_C_post0001_GEP", east)  # gets instanced by the test
    no_uv = cube("stoneGrey_C_step0001_GEP", east)
    cmds.polyMapDel(no_uv + ".f[*]", constructionHistory=False)
    cube("rockGrey_C_roofTile0001_GEP", root)
    return root, made


def run():
    tb = load_toolbox()
    A = tb["SmartUdimAsset"]

    # ------------------------------------------------------------ naming
    mk = tb["material_key_from_name"]
    check("convention name -> material key", mk("|g|woodGreen_C_beam0001_GEP") == ("woodGreen", None))
    check("legacy underscore number", mk("paintGrey_C_hiResBlockA_0001_GES")[0] == "paintGrey")
    check("any word + Word(s) is a valid material token (it's a guide)",
          all(mk(n)[1] is None for n in ("steelRusty_C_beam_GEP", "woodMoulding_C_trim0001_GEP",
                                           "metalBrushed_C_rail0001_GEP", "wood_C_beam0001_GEP")),
          str([mk(n) for n in ("steelRusty_C_beam_GEP", "woodMoulding_C_trim0001_GEP")]))
    check("a one-word unknown material is still usable, flagged", mk("steel_C_beam_GEP")[0] == "steel"
          and "woodBrown" in (mk("steel_C_beam_GEP")[1] or ""))
    check("suffix variant flagged", "variant" in (mk("woodGreen_C_beam0001_GEP1")[1] or ""))
    check("material variant letters are valid and their own key",
          mk("glassClearA_F_pane0001_GEP") == ("glassClearA", None) and
          mk("woodBrownB_C_beam0001_GEP") == ("woodBrownB", None) and mk("glassClear_F_pane_GEP")[1] is None,
          "%s / %s" % (mk("glassClearA_F_pane0001_GEP"), mk("woodBrownB_C_beam0001_GEP")))
    check("variant split", tb["ur_split_material_color_variant"]("glassClearA") == ("glass", "Clear", "A") and
          tb["ur_split_material_color_variant"]("woodBrown") == ("wood", "Brown", "") and
          tb["ur_split_material_color_variant"]("steelRustyA") == ("steel", "Rusty", "A") and
          tb["ur_split_material_color_variant"]("Steel")[0] is None and
          tb["ur_split_material_color_variant"]("steel")[0] is None)
    check("no suffix -> unusable", mk("pCube1")[0] is None)
    check("namespaced name parses", mk("asset:woodGreen_C_beam0001_GEP")[0] == "woodGreen")
    pg = tb["parse_group_name"]
    check("parse full material set name", pg("td100_woodGreen_c085_stack") ==
          {"key": "woodGreen", "td": 100.0, "cov": 85.0, "stack": True})
    check("parse hand-typed name", pg("td150_woodGreen") == {"key": "woodGreen", "td": 150.0, "cov": None,
                                                            "stack": False})
    check("uniqueness suffix ignored", pg("td100_woodGreen_c012_3")["key"] == "woodGreen"
          and pg("td100_woodGreen_c012_3")["cov"] == 12.0)
    check("parse section name", pg("td80_westWing_UDS") ==
          {"key": "westWing", "td": 80.0, "cov": None, "stack": False})
    check("compose material name", tb["compose_material_set_name"]("woodGreen", 100, 85.4, True) ==
          "td100_woodGreen_c085_stack")
    check("compose section name", tb["compose_section_set_name"]("westWing", 100) == "westWing_UDS"
          and tb["compose_section_set_name"]("westWing", 80) == "td80_westWing_UDS")
    check("shader names sanitised", tb["sanitize_key"]("ns:metal_rusty") == "metalRusty"
          and tb["sanitize_key"]("3dGlass") == "m3dGlass")
    check("face ranges", tb["face_ranges"]([0, 1, 2, 5, 7, 8]) == ["f[0:2]", "f[5]", "f[7:8]"])

    # ------------------------------------------------------------ scan
    cmds.file(new=True, force=True)
    root, made = build_house()
    post = made["woodGreen_C_post0001_GEP"]
    cmds.instance(post, name="postInstance")
    asset = A.for_group(root)
    check("root set created and linked", asset.root_set() == "house_smartUDIM_SET"
          and asset.root_group() == cmds.ls(root, long=True)[0], asset.root_set())
    check("for_group finds the existing asset", A.for_group(root).uuid == asset.uuid)

    res = asset.scan(sections_from_groups=True)
    snap = asset.read()
    secs = {s["key"]: s for s in snap["sections"]}
    check("sections from top-level groups (+ loose meshes)", set(secs) == {"westWing", "eastWing", "house"},
          str(sorted(secs)))
    west_keys = sorted(m["key"] for m in secs["westWing"]["materials"])
    check("west wing groups: names + per-face shaders", west_keys ==
          ["glassClear", "metalRusty", "paintedTrimMAT", "woodGreen"], str(west_keys))
    east_keys = sorted(m["key"] for m in secs["eastWing"]["materials"])
    default_key = tb["sanitize_key"](cmds.listConnections("initialShadingGroup.surfaceShader")[0])
    check("badly named mesh falls back to its shader", default_key in east_keys, "%s (default %s)" % (
        east_keys, default_key))
    wood = [m for m in secs["westWing"]["materials"] if m["key"] == "woodGreen"][0]
    check("material set named td100_woodGreen", wood["set"].startswith("td100_woodGreen") and wood["objects"] == 2,
          wood["set"])
    trim = [m for m in secs["westWing"]["materials"] if m["key"] == "paintedTrimMAT"][0]
    check("per-face shader group holds faces", trim["partial"] == 1, str(trim))
    check("identical material keys in two sections stay unique",
          len(set(m["set"] for s in snap["sections"] for m in s["materials"] if m["key"] == "woodGreen")) == 2)
    check("instanced mesh skipped", post in snap["instanced"] and post not in snap["meshes"],
          str(snap["instanced"]))
    check("nothing unassigned, no overlaps", not snap["unassigned"] and not snap["overlaps"],
          "%s %s" % (snap["unassigned"], snap["overlaps"]))
    naming = {cmds.ls(n["node"])[0].split("|")[-1]: n for n in snap["naming"]}
    check("naming hand-off lists bad names, not valid ones", "Mesh_final_v2" in naming and "trimPiece" in naming
          and "glassClear_F_window0001_GEP" not in naming,  # Clear is a colour now
          str(sorted(naming)))

    cmds.undo()
    check("one Ctrl+Z undoes a whole scan", not asset.sections(), str(asset.sections()))
    cmds.redo()
    check("redo brings it back", len(asset.sections()) == 3, str(asset.sections()))

    before = sorted(m["set"] for s in snap["sections"] for m in s["materials"])
    res2 = asset.scan(sections_from_groups=True)
    after = sorted(m["set"] for s in asset.read()["sections"] for m in s["materials"])
    check("re-scan is idempotent", res2["added"] == 0 and before == after, str(res2))

    # new mesh appears later -> rescan sorts only that one
    new = cmds.parent(cmds.polyCube(name="glassClear_F_window0002_GEP")[0], "|house_GRP|westWing_GRP")[0]
    res3 = asset.scan()
    glass = [m for s in asset.read()["sections"] if s["key"] == "westWing" for m in s["materials"]
             if m["key"] == "glassClear"][0]
    check("new mesh joins the existing group", res3["added"] == 1 and glass["objects"] == 2, str(res3))

    # hand edits outside the tool are respected
    wood_set = wood["set"]
    renamed = cmds.rename(wood_set, "td150_woodGreen_stack")
    asset.sync_names()
    m = [x for s in asset.read()["sections"] for x in s["materials"] if x["set"].startswith("td150_woodGreen")]
    check("renaming a set by hand changes TD and stack", m and m[0]["td"] == 150.0 and m[0]["stack"],
          str(m and m[0]))
    manual = cmds.sets(empty=True, name="td80_glassFrosted")
    cmds.sets(manual, add=[s for s in asset.sections() if "westWing" in s][0])
    asset.sync_names()
    m = [x for s in asset.read()["sections"] for x in s["materials"] if x["key"] == "glassFrosted"]
    check("hand-made set under a section is picked up", m and m[0]["td"] == 80.0 and m[0]["source"] == "manual",
          str(m and m[0]))

    # tool edits
    node = asset.set_group_values(m[0]["set"], td=120, stack=True)
    check("set TD/stack from the tool renames the set", node.startswith("td120_glassFrosted_stack"), node)
    secs = asset.sections()
    asset.move_section(secs[-1], -1)
    check("section order changes", asset.sections()[-2] == secs[-1], str(asset.sections()))

    # exclusive assignment: move two faces of a beam into glassFrosted
    beam = cmds.ls("woodGreen_C_beam0001_GEP", long=True)[0]
    asset.assign({beam: {0, 1}}, node)
    snap = asset.read()
    wood = [x for s in snap["sections"] for x in s["materials"] if x["set"].startswith("td150_woodGreen")][0]
    frost = [x for s in snap["sections"] for x in s["materials"] if x["key"] == "glassFrosted"][0]
    check("assigning faces splits a whole-mesh membership", wood["partial"] == 1 and frost["objects"] == 1
          and not snap["overlaps"], "%s / %s" % (wood, frost))
    asset.assign({beam: None}, node)
    snap = asset.read()
    check("assigning the whole mesh moves it out entirely", not snap["overlaps"] and
          [x for s in snap["sections"] for x in s["materials"] if x["key"] == "glassFrosted"][0]["objects"] == 1)
    cmds.undo()
    check("assign is undoable", not asset.read()["overlaps"])

    # overlap detection when users break exclusivity by hand
    cmds.sets(beam, add=frost["set"])
    cmds.sets(beam, add=wood["set"])
    check("overlaps reported", any(beam == x for x, _ in asset.read()["overlaps"]))

    # ------------------------------------------------------------ pre-process
    cmds.file(new=True, force=True)
    root = cmds.group(empty=True, name="prep_GRP")
    good = cmds.parent(cmds.polyCube(name="woodGreen_C_ok0001_GEP")[0], root)[0]
    lam = cmds.parent(cmds.polyPlane(name="woodGreen_C_lam0001_GEP", sx=1, sy=1)[0], root)[0]
    dup = cmds.duplicate(lam)[0]
    lam = cmds.polyUnite(lam, dup, constructionHistory=False, name="woodGreen_C_lam0001_GEP")[0]
    lam = cmds.parent(lam, root)[0]
    cmds.polyMergeVertex(lam, distance=0.0001, constructionHistory=False)
    ngon = cmds.parent(cmds.polyCylinder(name="metalGrey_C_pipe0001_GEP", sx=8, sc=0)[0], root)[0]
    nouv = cmds.parent(cmds.polyCube(name="stoneGrey_C_step0001_GEP")[0], root)[0]
    cmds.polyMapDel(nouv + ".f[*]", constructionHistory=False)
    flip = cmds.parent(cmds.polyPlane(name="paintRed_C_sign0001_GEP", sx=2, sy=2)[0], root)[0]
    zero = cmds.parent(cmds.polyPlane(name="metalGrey_C_flat0001_GEP", sx=2, sy=1)[0], root)[0]
    # collapse face 0 to zero area: pull its top edge down onto its bottom edge
    for v in (3, 4):
        x, y, z = cmds.pointPosition("%s.vtx[%d]" % (zero, v - 3), local=True)
        cmds.xform("%s.vtx[%d]" % (zero, v), translation=(cmds.pointPosition("%s.vtx[%d]" % (zero, v),
                                                                              local=True)[0], y, z),
                   objectSpace=True)
    cmds.polyEditUV(flip + ".map[*]", scaleU=-1, pivotU=0.5, pivotV=0.5)
    asset = A.for_group(root)
    meshes, instanced = asset.meshes()
    issues = tb["detect_geometry_issues"](meshes)
    lam_l = cmds.ls(lam, long=True)[0]
    check("lamina faces detected", issues["lamina"].get(lam_l, 0) > 0, str(issues["lamina"]))
    check("n-gons detected", sum(issues["ngons"].values()) == 2, str(issues["ngons"]))
    check("clean mesh has no issues", not any(cmds.ls(good, long=True)[0] in v for v in issues.values()))
    zero_l = cmds.ls(zero, long=True)[0]
    check("zero-area faces detected (select-only cleanup)", issues["zeroarea"].get(zero_l, 0) >= 1,
          str(issues["zeroarea"]))
    zero_faces_before = cmds.polyEvaluate(zero, face=True)
    report = tb["preprocess"](meshes, instanced)
    check("pre-process fixed lamina", "lamina" in report and not cmds.polyInfo(lam, laminaFaces=True),
          str(report.get("lamina")))
    check("zero-area face removed", cmds.polyEvaluate(zero, face=True) < zero_faces_before,
          "%d -> %d" % (zero_faces_before, cmds.polyEvaluate(zero, face=True)))
    check("only the agreed fixes ran (no triangulation)", cmds.polyEvaluate(good, face=True) == 6)
    check("n-gons reported but left alone", "ngons" in report and
          len([c for c in om_counts(ngon) if c > 4]) == 2, str(report.get("ngons")))
    check("mesh with no UVs will be skipped", cmds.ls(nouv, long=True)[0] in report.get("no_uvs", {}),
          str(report.get("no_uvs")))
    check("flipped UV faces reported", report.get("flipped", {}).get(cmds.ls(flip, long=True)[0]) == 4,
          str(report.get("flipped")))
    check("skipped_meshes lists the no-UV mesh", cmds.ls(nouv, long=True)[0] in tb["skipped_meshes"](report))
    cmds.undo()
    check("one Ctrl+Z undoes the clean-up", bool(cmds.polyInfo(lam, laminaFaces=True)))


def om_counts(node):
    import maya.api.OpenMaya as om
    sel = om.MSelectionList()
    sel.add(cmds.listRelatives(node, shapes=True, fullPath=True)[0])
    return om.MFnMesh(sel.getDagPath(0)).getVertices()[0]


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
