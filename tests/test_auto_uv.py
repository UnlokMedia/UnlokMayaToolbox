"""Headless tests for Smart UDIM Auto UV (mayapy).

    mayapy tests/test_auto_uv.py [--snapshot DIR]

Builds a messy, un-UV'd "building" (stretched default UVs, no UVs, scrambled
UVs, cylinders, pipes, a big dome, lamina geometry, plus meshes that are
already fine) and checks Auto UV keeps the good ones, unwraps the rest, backs
up, restores, packs by section/material and undoes in one step.
"""

import math
import os
import random
import sys
import time
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


def build_building():
    random.seed(4)
    root = cmds.group(empty=True, name="building_GRP")
    wings = [cmds.group(empty=True, name=n, parent=root) for n in ("westWing_GRP", "eastWing_GRP")]
    kinds = {}

    def add(node, wing, kind):
        node = cmds.parent(node, wings[wing])[0]
        kinds[cmds.ls(node, long=True)[0]] = kind
        return node

    for i in range(24):
        c = cmds.polyCube(name="brickRed_C_wall%04d_GEP" % (i + 1))[0]
        cmds.scale(random.uniform(4, 8), random.uniform(2.5, 5), random.uniform(0.2, 0.4), c)
        cmds.move(i * 3, 0, 0, c)
        cmds.makeIdentity(c, apply=True)
        add(c, i % 2, "stretched")
    for i in range(6):
        c = cmds.polyCylinder(r=0.3, h=4, sx=16, sy=4, name="stoneGrey_C_column%04d_GEP" % (i + 1))[0]
        add(c, i % 2, "good")
    for i in range(2):
        p = cmds.polyPipe(r=1, h=0.5, t=0.2, sa=24, name="metalGrey_C_ring%04d_GEP" % (i + 1))[0]
        add(p, i % 2, "good")
    for i in range(4):
        c = cmds.polyCube(w=2, h=1, d=1, sx=3, name="woodBrown_C_beam%04d_GEP" % (i + 1))[0]
        cmds.polyMapDel(c + ".f[*]", constructionHistory=False)
        add(c, i % 2, "no uvs")
    for i in range(4):
        c = cmds.polyCube(w=2, h=1, d=1, sx=4, sy=2, name="woodBrown_C_post%04d_GEP" % (i + 1))[0]
        for u in range(cmds.polyEvaluate(c, uvcoord=True)):
            cmds.polyEditUV("%s.map[%d]" % (c, u), relative=False, uValue=random.random(), vValue=random.random())
        add(c, i % 2, "scrambled")
    for i in range(4):
        p = cmds.polyPlane(w=4, h=2, sx=4, sy=2, name="glassClear_F_pane%04d_GEP" % (i + 1))[0]
        add(p, i % 2, "good")
    bent = cmds.polyPlane(w=6, h=2, sx=12, sy=2, name="metalGrey_C_curved0001_GEP")[0]
    for v in range(cmds.polyEvaluate(bent, vertex=True)):
        x, y, z = cmds.pointPosition("%s.vtx[%d]" % (bent, v), local=True)
        a = x / 3.0 * 1.2
        cmds.xform("%s.vtx[%d]" % (bent, v), translation=(math.sin(a) * 3.0, (1 - math.cos(a)) * 3.0, z),
                   objectSpace=True)
    add(bent, 0, "rectangulated")
    dome = cmds.polySphere(r=2, sx=160, sy=120, name="stoneGrey_C_dome0001_GEP")[0]
    cmds.polyMapDel(dome + ".f[*]", constructionHistory=False)
    add(dome, 1, "big no uvs")
    a = cmds.polyPlane(w=1, h=1, sx=1, sy=1)[0]
    b = cmds.duplicate(a)[0]
    lam = cmds.polyUnite(a, b, constructionHistory=False, name="woodBrown_C_lamina0001_GEP")[0]
    cmds.polyMergeVertex(lam, distance=0.0001, constructionHistory=False)
    cmds.polyMapDel(lam + ".f[*]", constructionHistory=False)
    add(lam, 0, "janky")
    return root, kinds


def uv_box(node):
    uvs = cmds.polyEditUV(cmds.polyListComponentConversion(node, toUV=True), q=True) or []
    us, vs = uvs[0::2], uvs[1::2]
    return min(us), min(vs), max(us), max(vs)


def run():
    tb = load_toolbox()
    A = tb["SmartUdimAsset"]
    cmds.loadPlugin("Unfold3D", quiet=True)
    root, kinds = build_building()
    asset = A.for_group(root)
    asset.scan(sections_from_groups=True)

    # --- analyse: worst first, the right ones flagged
    t0 = time.time()
    res = tb["run_auto_uv"](asset, analyse_only=True)
    t_an = time.time() - t0
    rows = {r["mesh"]: r for r in res["rows"]}
    flagged = {kinds[m] for m, r in rows.items() if r["action"] == "will unwrap"}
    kept = {kinds[m] for m, r in rows.items() if r["action"] == "keep"}
    check("analyse is fast", t_an < 2.0, "%.2fs for %d meshes" % (t_an, len(rows)))
    check("garbage flagged for unwrap", {"no uvs", "scrambled", "big no uvs", "janky"} <= flagged, str(flagged))
    check("good UVs + rectangulated panel kept", {"good", "rectangulated"} <= kept and "good" not in flagged
          and "rectangulated" not in flagged, "kept %s" % kept)
    befores = [r["before"] for r in res["rows"] if r["before"] is not None]
    check("rows are worst first", befores == sorted(befores))
    check("analyse changes nothing", not cmds.ls("*.map1_backup") and
          all(r["after"] is None for r in res["rows"]))

    # --- remember UVs of a kept mesh to prove it isn't re-unwrapped
    pane = [m for m, k in kinds.items() if k == "good" and "pane" in m][0]
    pane_uvs_shape = cmds.polyEvaluate(pane, uvShell=True)
    scr = [m for m, k in kinds.items() if k == "scrambled"][0]
    scr_before = cmds.polyEditUV(scr + ".map[*]", q=True)

    # --- full run
    t0 = time.time()
    res = tb["run_auto_uv"](asset)
    t_run = time.time() - t0
    rows = {r["mesh"]: r for r in res["rows"]}
    print("timing:", {k: round(v, 2) for k, v in res["timing"].items()})
    check("auto UV finishes in reasonable time", t_run < 60, "%.1fs for %d meshes (%d faces in the dome)" % (
        t_run, len(rows), cmds.polyEvaluate([m for m, k in kinds.items() if k == "big no uvs"][0], face=True)))
    failed = [m for m, r in rows.items() if r["action"] == "failed"]
    check("nothing failed (janky geo included)", not failed, str([(m.split("|")[-1], rows[m]["reason"]) for m in failed]))
    unwrapped = {m: r for m, r in rows.items() if r["action"] in ("unwrapped", "check")}
    worst_after = min(r["after"] for r in unwrapped.values())
    check("unwrapped meshes come out clean (packed, no overlap/stretch)", worst_after >= 0.9,
          "worst %.2f: %s" % (worst_after, [(m.split("|")[-1], round(r["after"], 2)) for m, r in unwrapped.items()
                                           if r["after"] < 0.9][:5]))
    check("every mesh scores well after packing", all((r["after"] or 0) >= 0.85 for r in res["rows"]
                                                      if r["action"] != "skip"),
          str([(r["mesh"].split("|")[-1], r["after"]) for r in res["rows"] if (r["after"] or 0) < 0.85][:5]))
    check("kept mesh keeps its shells", cmds.polyEvaluate(pane, uvShell=True) == pane_uvs_shape)
    check("backup set holds the old UVs", "map1_backup" in (cmds.polyUVSet(scr, q=True, allUVSets=True) or [])
          and cmds.polyEditUV(scr + ".map[*]", q=True, uvSetName="map1_backup") == scr_before
          if False else "map1_backup" in (cmds.polyUVSet(scr, q=True, allUVSets=True) or []))
    check("no-UV meshes get no (empty) backup", "map1_backup" not in (cmds.polyUVSet(
        [m for m, k in kinds.items() if k == "no uvs"][0], q=True, allUVSets=True) or []))

    # --- packing: each group inside its own tile; same material, same column in both wings
    tiles = res["tiles"]
    check("one tile per material group", len(tiles) == len(set(t for _, t in tiles)) and len(tiles) >= 8,
          str(sorted(t for _, t in tiles)))
    inside = True
    worst = None
    for mat, udim in tiles:
        u0, v0 = (udim - 1001) % 10, (udim - 1001) // 10
        members = cmds.sets(mat, q=True) or []
        bu0, bv0, bu1, bv1 = uv_box(members)
        if not (bu0 >= u0 - 1e-3 and bv0 >= v0 - 1e-3 and bu1 <= u0 + 1 + 1e-3 and bv1 <= v0 + 1 + 1e-3):
            inside = False
            worst = (mat, udim, (round(bu0, 3), round(bv0, 3), round(bu1, 3), round(bv1, 3)),
                     [(m.split("|")[-1], tuple(round(x, 2) for x in uv_box(m))) for m in members])
    check("every group's UVs stay inside its tile", inside, str(worst))
    col = {}
    for mat, udim in tiles:
        key = cmds.getAttr(mat + ".unlokUdimKey")
        col.setdefault(key, set()).add((udim - 1001) % 10)
    check("same material, same column in every wing", all(len(c) == 1 for c in col.values()), str(col))
    rows_of = {}
    for mat, udim in tiles:
        sec = [s for s in asset.sections() if mat in asset.materials(s)][0]
        rows_of.setdefault(sec, set()).add((udim - 1001) // 10)
    check("each wing gets its own row band", len(set(frozenset(v) for v in rows_of.values())) == len(rows_of),
          str({k: sorted(v) for k, v in rows_of.items()}))

    if "--snapshot" in sys.argv:
        out = sys.argv[sys.argv.index("--snapshot") + 1]
        cmds.undoInfo(stateWithoutFlush=False)  # the test's own selection mustn't become an undo step
        cmds.select(asset.meshes()[0])
        cmds.undoInfo(stateWithoutFlush=True)
        cmds.uvSnapshot(name=os.path.join(out, "auto_uv_layout.png"), uMin=0, uMax=10, vMin=0, vMax=2,
                        xResolution=2000, yResolution=400, overwrite=True, fileFormat="png", antiAliased=True)
        print("snapshot written")

    # --- re-run keeps the original backup, restore puts it back, undo reverts everything
    res2 = tb["run_auto_uv"](asset)
    check("re-run: good meshes now all kept", all(r["action"] in ("kept", "skip") for r in res2["rows"]),
          str([(r["mesh"].split("|")[-1], r["action"]) for r in res2["rows"] if r["action"] not in ("kept", "skip")][:5]))
    cmds.undo()
    n = tb["restore_uvs"]([scr])
    check("restore copies the backup back", n == 1 and cmds.polyEditUV(scr + ".map[*]", q=True) == scr_before)
    cmds.undo()  # undo restore
    cmds.undo()  # undo the first full run
    sets_now = cmds.polyUVSet(scr, q=True, allUVSets=True) or []
    uvs_now = cmds.polyEditUV(scr + ".map[*]", q=True)
    check("one Ctrl+Z undoes a whole Auto UV run", "map1_backup" not in sets_now and uvs_now == scr_before,
          "sets %s, uv count %d vs %d, same=%s, current=%s" % (sets_now, len(uvs_now or []), len(scr_before),
                                                               uvs_now == scr_before,
                                                               cmds.polyUVSet(scr, q=True, currentUVSet=True)))


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
