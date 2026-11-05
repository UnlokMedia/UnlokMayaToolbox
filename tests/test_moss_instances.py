"""Headless tests for instanced moss shoots (mayapy).

    mayapy tests/test_moss_instances.py

Scatter moss at High grows its shoots as instances (a particle shape and an
instancer of a few shoot shapes) by default; Shoots Mesh puts them back in
the strands mesh. The instancer puts every shoot where the engine says
(its axes and length: the rotation convention), the shapes share the
strands part's UDIM tiles, the instances survive a save and reopen (and an
edit after it regrows from what was read back), Bake turns them into real
geometry in the strands mesh (one Ctrl+Z brings the instancer back),
removing the layer removes them, an old layer (no Shoots setting) grows
instances, and the scene is much lighter than with Mesh.
"""

import math
import os
import random
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402
import maya.OpenMaya as om1  # noqa: E402
import maya.OpenMayaFX as omfx1  # noqa: E402

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


def rock(name="rockGrey_C_test0001_GEP"):
    """A lumpy boulder ~6 dm across (decimetres): tops, sides, an overhang."""
    node = cmds.polySphere(r=3.0, sx=24, sy=16, ch=False, name=name)[0]
    cmds.scale(1.0, 0.7, 0.85, node)
    cmds.move(0, 1.6, 0, node)
    cmds.makeIdentity(node, apply=True)
    return cmds.ls(node, long=True)[0]


def instances(inst):
    """World matrices (4x4 lists) of an instancer's instances."""
    sel = om1.MSelectionList()
    sel.add(inst)
    dp = om1.MDagPath()
    sel.getDagPath(0, dp)
    fn = omfx1.MFnInstancer(dp)
    out = []
    for i in range(fn.particleCount()):
        m = om1.MMatrix()
        paths = om1.MDagPathArray()
        fn.instancesForParticle(i, paths, m)
        out.append([[m(r, c) for c in range(4)] for r in range(4)])
    return out


def run():
    tb = load_toolbox()
    cmds.file(new=True, force=True)

    # the rotation convention, alone: axes -> XYZ degrees -> axes, and a Maya transform agrees
    random.seed(4)
    worst = 0.0
    for _ in range(200):
        y = tb["_rl_norm"]((random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-1, 1)))
        x = tb["_rl_norm"](tb["_rl_cross"](y, tb["_rl_any_perp"](y)))
        z = tb["_rl_cross"](x, y)
        e = tb["_mi_euler_xyz"](x, y, z)
        back = tb["_mi_axes_xyz"](*e)
        worst = max(worst, max(abs(a - b) for u, v in zip((x, y, z), back) for a, b in zip(u, v)))
    t = cmds.createNode("transform")
    cmds.setAttr(t + ".rotate", *e)
    m = cmds.xform(t, q=True, matrix=True, worldSpace=True)
    rows = [m[0:3], m[4:7], m[8:11]]
    mw = max(abs(a - b) for u, v in zip(rows, (x, y, z)) for a, b in zip(u, v))
    cmds.delete(t)
    check("axes -> XYZ rotation -> axes, and a transform's matrix rows are the axes", worst < 1e-9 and mw < 1e-6,
          "round trip %.1e, Maya %.1e" % (worst, mw))

    stone = rock()
    s = {"detail": "High", "coverage": 0.8, "strands": 1.2, "strand_length": 0.012, "droop": 0.6, "seed": 2}
    rep = tb["create_scatter_group"]([stone], "Moss", s, select=False)
    root = rep["root"]
    lid = tb["sc_data"](root)["layers"][0]["id"]
    shoots = tb["sc_shoots"](root)
    node = shoots.get(lid + "/shoots")
    ps, inst, shapes = tb["_sc_shoot_nodes"](node) if node else (None, None, [])
    counts = tb["sc_counts"](root) if "sc_counts" in tb else {}
    n = cmds.particle(ps, q=True, count=True) if ps else 0
    check("High grows its shoots as instances: a particle shape, an instancer, 8 shoot shapes (hidden)",
          node and inst and len(shapes) == 8 and n > 2000 and not cmds.getAttr(cmds.listRelatives(
              shapes[0], parent=True, fullPath=True)[0] + ".visibility"),
          "%s shoots, %d shapes, %s" % (n, len(shapes), counts))

    # the instancer puts each shoot where the engine says
    got = tb["_sc_read_shoots"](node)
    data = got[7]
    mats = instances(inst)
    worst = 0.0
    for i in range(0, len(mats), max(1, len(mats) // 300)):
        M = mats[i]
        L = data["scale"][i]
        for r, ax in enumerate(data["axes"][i]):
            worst = max(worst, max(abs(M[r][c] - ax[c] * L) for c in range(3)))
        worst = max(worst, max(abs(M[3][c] - data["pos"][i][c]) for c in range(3)))
    check("every instance sits at its shoot's root, turned onto its axes, scaled by its length",
          len(mats) == n and worst < 1e-4, "%d instances, worst %.1e" % (len(mats), worst))

    # the shapes share the strands part's UDIM tiles
    parts = tb["sc_parts"](root)
    st = parts.get(lid + "/strands")
    su = tb["_sc_read_part"](st) if st else None
    tiles_shoots = set(int(math.floor(u)) for u in got[3])
    tiles_strands = set(int(math.floor(u)) for u in su[3]) if su else set()
    check("the shoot shapes' UVs are in the strands part's tiles (one mossStrand texture)",
          su and tiles_shoots <= tiles_strands, "shoots %s strands %s" % (sorted(tiles_shoots), sorted(tiles_strands)))

    # Mesh: back in the strands mesh, about as many shoots
    st_faces = int(cmds.polyEvaluate(st, face=True)) if st else 0
    real = tb["moss_instances_mesh"](got)
    tb["sc_update"](root, lid, {"shoots": "Mesh"})
    parts = tb["sc_parts"](root)
    mesh_faces = int(cmds.polyEvaluate(parts[lid + "/strands"], face=True))
    hidden = not cmds.getAttr(node + ".visibility")
    check("Shoots Mesh: the shoots are real geometry in the strands mesh again, the instancer hides",
          hidden and abs(mesh_faces - (st_faces + len(real[1]))) < 0.15 * mesh_faces,
          "mesh %d vs strands %d + instanced %d" % (mesh_faces, st_faces, len(real[1])))
    tmp = tempfile.mkdtemp()
    mesh_mb = os.path.join(tmp, "mesh.mb")
    cmds.file(rename=mesh_mb)
    cmds.file(save=True, type="mayaBinary", force=True)
    tb["sc_update"](root, lid, {"shoots": "Instances"})
    check("back to Instances: the instancer shows again", cmds.getAttr(node + ".visibility"))

    # save, reopen, an edit grows from what was read back
    path = os.path.join(tmp, "inst.mb")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaBinary", force=True)
    size_i, size_m = os.path.getsize(path), os.path.getsize(mesh_mb)
    check("the scene with instances is much lighter than with Mesh", size_i < 0.5 * size_m,
          "%.1f MB vs %.1f MB" % (size_i / 1048576.0, size_m / 1048576.0))
    cmds.file(new=True, force=True)
    tb = load_toolbox()
    cmds.file(path, open=True, force=True)
    root = tb["sc_groups"]()[0]
    node = tb["sc_shoots"](root)[lid + "/shoots"]
    ps, inst, shapes = tb["_sc_shoot_nodes"](node)
    cmds.currentTime(12)
    cmds.currentTime(1)
    check("reopened: every instance is still there (through frame changes)",
          cmds.particle(ps, q=True, count=True) == n and len(instances(inst)) == n,
          "%d of %d" % (cmds.particle(ps, q=True, count=True), n))
    tb["sc_update"](root, lid, {"thickness": 0.03})
    node = tb["sc_shoots"](root)[lid + "/shoots"]
    ps = tb["_sc_shoot_nodes"](node)[0]
    check("an edit after reopening regrows the instances", ps and cmds.particle(ps, q=True, count=True) > 2000)

    # select an instance's node: its layer
    owner = tb["sc_owner"](tb["_sc_shoot_nodes"](node)[1])
    check("the instancer belongs to its group and layer", owner == (root, lid), str(owner))

    # Bake: real geometry, one Ctrl+Z brings the instancer back
    before = tb["_sc_read_shoots"](node)
    strands = tb["sc_parts"](root).get(lid + "/strands")
    sf = int(cmds.polyEvaluate(strands, face=True)) if strands else 0
    cmds.undoInfo(state=True, infinity=True)
    cmds.flushUndo()
    tb["bake_scatter"]([root])
    left = cmds.ls(type=("particle", "instancer"))
    baked = [n2 for n2 in cmds.listRelatives(root, children=True, fullPath=True) or [] if "mossStrand" in n2]
    bf = int(cmds.polyEvaluate(baked[0], face=True)) if baked else 0
    want = sf + len(tb["moss_instances_mesh"](before)[1])
    check("Bake: no particles or instancer left, the strands mesh holds the shoots as geometry",
          not left and len(baked) == 1 and bf == want, "%s | %d faces vs %d" % (left, bf, want))
    cmds.undo()
    check("one Ctrl+Z: the live group and its instancer are back",
          tb["is_scatter"](root) and cmds.ls(type="instancer"), str(cmds.ls(type="instancer")))

    # an old layer: no Shoots setting stored -> instances
    cmds.file(new=True, force=True)
    stone = rock()
    rep = tb["create_scatter_group"]([stone], "Moss", s, select=False)
    root = rep["root"]
    data = tb["sc_data"](root)
    data["layers"][0]["s"].pop("shoots", None)
    tb["_sc_set_text"](root, tb["SC_ATTR"], tb["json"].dumps(data))
    tb["sc_regrow"](root, readback=False)
    node = tb["sc_shoots"](root).get(data["layers"][0]["id"] + "/shoots")
    check("an old layer with no Shoots setting grows instances", node and cmds.getAttr(node + ".visibility"))
    tb["sc_remove_layer"](root, data["layers"][0]["id"])
    check("removing the layer removes its instanced shoots", not tb["sc_shoots"](root))

    # Ctrl+Z / Ctrl+Y / Ctrl+Z over a new group, then any command (Maya frees the undone nodes): this crashed
    # Maya when the particle shape came before the instancer
    cmds.file(new=True, force=True)
    stone = rock()
    rep = tb["create_scatter_group"]([stone], "Moss", dict(s, detail="Normal"), select=False)
    node = list(tb["sc_shoots"](rep["root"]).values())[0]
    kids = cmds.listRelatives(node, children=True, fullPath=True)
    check("the instancer comes first under the shoots node", cmds.nodeType(kids[0]) == "instancer",
          str([cmds.nodeType(k) for k in kids]))
    cmds.undo()
    cmds.redo()
    tb["sc_sync"]()
    cmds.undo()
    cmds.polyCube(name="afterUndo")
    check("a new group undone, redone, undone, then a new command: Maya carries on", cmds.objExists("afterUndo"))


try:
    run()
except Exception:
    traceback.print_exc()
    RESULTS.append(("exception", False, traceback.format_exc()))
finally:
    bad = [r for r in RESULTS if not r[1]]
    print("%d passed, %d failed" % (len(RESULTS) - len(bad), len(bad)))
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(0)
