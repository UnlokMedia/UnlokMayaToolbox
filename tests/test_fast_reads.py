"""The fast API readers (expand_members, SmartUdimAsset.meshes) must give
exactly what the old cmds versions did, and be fast at 3,000 meshes (mayapy).

    mayapy tests/test_fast_reads.py
"""

import os
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


def old_meshes(tb, group):
    """The previous cmds implementation of SmartUdimAsset.meshes."""
    meshes, instanced = [], []
    for shape in cmds.listRelatives(group, allDescendents=True, type="mesh", fullPath=True,
                                    noIntermediate=True) or []:
        xform = tb["long_name"](cmds.listRelatives(shape, parent=True, fullPath=True)[0])
        if len(cmds.ls(shape, allPaths=True) or []) > 1:
            if xform not in instanced:
                instanced.append(xform)
        elif xform not in meshes:
            meshes.append(xform)
    if cmds.listRelatives(group, shapes=True, type="mesh", noIntermediate=True) and group not in meshes:
        meshes.insert(0, group)
    return meshes, instanced


def run():
    tb = {"__name__": "fast_reads", "__file__": TOOLBOX}
    exec(compile(open(TOOLBOX).read(), TOOLBOX, "exec"), tb)

    # --- a messy scene: per-face members, shape members, instances, nested sets,
    #     curves, intermediate shapes (a deformed mesh), a mesh on the root itself
    root = cmds.polyCube(name="root_GEP")[0]  # the root itself is a mesh
    root = cmds.ls(root, long=True)[0]
    g = cmds.group(empty=True, name="wing_GRP", parent=root)
    a = cmds.parent(cmds.polyCube(name="a")[0], g)[0]
    b = cmds.parent(cmds.polyCube(name="b", sx=3)[0], g)[0]
    c = cmds.parent(cmds.polySphere(name="c")[0], g)[0]
    cmds.cluster(c)  # c gets an intermediate (orig) shape
    inst = cmds.instance(cmds.parent(cmds.polyCube(name="inst")[0], g)[0])[0]
    if not cmds.listRelatives(inst, parent=True):
        cmds.parent(inst, root)  # instanced under the asset too
    curve = cmds.parent(cmds.curve(p=[(0, 0, 0), (1, 0, 0)], d=1, name="crv"), g)[0]
    s1 = cmds.sets(empty=True, name="s1")
    cmds.sets([a, b + ".f[0:3]", b + ".f[7]", cmds.listRelatives(c, shapes=True, fullPath=True)[0], curve,
               root], add=s1)
    s2 = cmds.sets(empty=True, name="s2")
    cmds.sets([s1, b + ".e[0:2]", b], add=s2)  # nested set, edges, then the whole of b
    s3 = cmds.sets(empty=True, name="s3")
    cmds.sets([b + ".f[0:5]", b + ".f[2:9]"], add=s3)
    for s in (s1, s2, s3, cmds.sets(empty=True, name="empty")):
        new, old = tb["expand_members"](s), tb["_expand_members_cmds"](s)
        check("expand_members matches the old reader (%s)" % s,
              new[0] == old[0] and sorted(new[1]) == sorted(old[1]),
              "new %s | old %s" % (new, old) if new != old else "%d members" % len(new[0]))
    asset = tb["SmartUdimAsset"].for_group(root)
    new, old = asset.meshes(), old_meshes(tb, root)
    # instanced: the API walk sees every transform sharing an instanced shape (the old reader saw one)
    check("meshes() matches the old reader (same meshes, root first, instanced ones all found)",
          sorted(new[0]) == sorted(old[0]) and new[0][0] == old[0][0] and set(new[1]) >= set(old[1]),
          "new %s | old %s" % (new, old))

    # --- speed at 3,000 meshes
    cmds.file(new=True, force=True)
    town = cmds.group(empty=True, name="town_GRP")
    for gi in range(10):
        grp = cmds.group(empty=True, name="block%02d_GRP" % gi, parent=town)
        for i in range(300):
            cmds.parent(cmds.polyCube(name="woodBrown_C_piece%04d_GEP" % (i + 1), constructionHistory=False)[0],
                        grp)
    asset = tb["SmartUdimAsset"].for_group(town)
    asset.scan(sections_from_groups=True)
    t0 = time.time()
    snap = asset.read()
    t_read = time.time() - t0
    t0 = time.time()
    tb["uv_states"](asset, {}, meshes=snap["meshes"], instanced=snap["instanced"], status=snap["status"])
    t_states = time.time() - t0
    check("a panel refresh's reads take well under a second at 3,000 meshes", t_read + t_states < 0.35,
          "read %.2fs + states %.2fs (was about 0.54 + 0.20)" % (t_read, t_states))


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
