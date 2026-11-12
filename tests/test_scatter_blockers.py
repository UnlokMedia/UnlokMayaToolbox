"""Headless tests for Scatter blockers (mayapy).

    mayapy tests/test_scatter_blockers.py

A yard in decimetres (a floor, a wall at its back). A blocker box over part
of the floor: moss, leaves and grass grow nowhere inside it and as before
away from it; ivy on the wall avoids a blocker across it. Add Blocker makes
a red box in the group's control group that picks the group when selected
and is never grown on; Use Selected makes any mesh a blocker; moving one
is noticed (and grows round it again); Remove; one Ctrl+Z; Bake deletes the
tool's box and keeps yours.
"""

import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402
import maya.api.OpenMaya as om  # noqa: E402

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


def box(name, size, at, parent=None, div=2.0):
    node = cmds.polyCube(w=size[0], h=size[1], d=size[2], sx=max(1, int(size[0] / div)), sy=max(1, int(size[1] / div)),
                         sz=max(1, int(size[2] / div)), name=name, constructionHistory=False)[0]
    cmds.move(at[0], at[1], at[2], node)
    if parent:
        node = cmds.parent(node, parent)[0]
    return cmds.ls(node, long=True)[0]


def part_points(tb, root, key):
    node = tb["sc_parts"](root).get(key)
    if not node or not cmds.getAttr(node + ".visibility"):
        return []
    fn = om.MFnMesh(tb["get_dag_path"](tb["_log_shape"](node)))
    return [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kWorld)]


# the blocked area on the floor: x -16..-4, z -6..6 (a 12 x 12 dm box); "deep" inside it, past what an item
# standing just outside could reach over
def deep(p, m=1.5):
    return -16.0 + m < p[0] < -4.0 - m and -6.0 + m < p[2] < 6.0 - m and p[1] < 3.0


def far(p):
    return p[0] > 4.0 and p[1] < 1.5 and p[2] > -12.0


def run():
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    grp = cmds.ls(cmds.group(empty=True, name="yard_GRP"), long=True)[0]
    floor = box("floor", (40, 1, 30), (0, -0.5, 0), grp, div=100.0)
    wall = box("wall", (40, 15, 1), (0, 7.5, -13.5), grp, div=5.0)
    check("scene in decimetres", abs(tb["scene_m_per_unit"]() - 0.1) < 1e-9)

    rep = tb["create_scatter_group"]([grp], "Moss", {"style": "Carpet", "coverage": 0.6, "detail": "Proxy",
                                                       "patchiness": 0.3}, select=False)
    root = rep["root"]
    moss = tb["sc_data"](root)["layers"][0]["id"]
    base = part_points(tb, root, moss + "/moss")
    b_in, b_far = sum(map(deep, base)), sum(map(far, base))
    check("moss grows in the area to block and away from it", b_in > 50 and b_far > 100, "%d / %d" % (b_in, b_far))

    # a plain mesh as a blocker (Use Selected)
    blk = box("myBlocker", (12, 4, 12), (-10.0, 1.0, 0.0), div=100.0)
    t0 = time.time()
    tb["sc_set_blockers"](root, add=[blk])
    dt = time.time() - t0
    pts = part_points(tb, root, moss + "/moss")
    n_in, n_far = sum(map(deep, pts)), sum(map(far, pts))
    check("Moss: none inside the blocker, the rest as it was", n_in == 0 and abs(n_far - b_far) <= 0.1 * b_far,
          "inside %d -> %d, away %d -> %d (%.2fs)" % (b_in, n_in, b_far, n_far, dt))
    check("stored on the group, a blocker is never grown on", tb["sc_data"](root)["blockers"] ==
          cmds.ls(blk, uuid=True) and blk not in tb["sc_surfaces"](tb["sc_data"](root)) and
          not [p for p in pts if p[1] > 1.2 and -16 < p[0] < -4 and -6 < p[2] < 6])
    edge = [p for p in pts if -16.0 < p[0] < -4.0 and -6.0 < p[2] < 6.0 and p[1] < 3.0]
    check("... not even at its edge (a soft gap just outside)", len(edge) <= 0.02 * max(1, b_in), "%d" % len(edge))

    # debris: each item's own spot is checked too
    for typ, part, extra in (("Leaves", "litter", {"leaves": 25.0, "coverage": 0.7}),
                             ("Grass", "grass", {"grass": 3.0, "coverage": 0.7, "detail": "Proxy",
                                                 "grass_strays": 20.0})):
        _, lid = tb["sc_add_layer"](root, typ, extra)
        p1 = part_points(tb, root, lid + "/" + part)
        i1, f1 = sum(map(deep, p1)), sum(map(far, p1))
        tb["sc_set_blockers"](root, remove=[blk])
        p0 = part_points(tb, root, lid + "/" + part)
        i0, f0 = sum(map(deep, p0)), sum(map(far, p0))
        tb["sc_set_blockers"](root, add=[blk])
        check("%s: none inside the blocker, the rest as it was" % typ,
              i0 > 30 and i1 == 0 and abs(f1 - f0) <= 0.1 * f0, "inside %d -> %d, away %d -> %d" % (i0, i1, f0, f1))
        tb["sc_remove_layer"](root, lid)

    # moving it is noticed, and grows round it again
    check("nothing moved: not stale", not tb["sc_blockers_moved"](root))
    cmds.move(20.0, 0, 0, blk, relative=True)
    check("a blocker moved: noticed", tb["sc_blockers_moved"](root))
    tb["sc_regrow"](root)
    pts = part_points(tb, root, moss + "/moss")
    moved_far = [p for p in pts if 4.0 + 1.5 < p[0] < 16.0 - 1.5 and -4.5 < p[2] < 4.5 and p[1] < 3.0]
    check("... and the regrow follows it", not tb["sc_blockers_moved"](root) and sum(map(deep, pts)) > 50 and
          not moved_far, "%d back where it was, %d where it is" % (sum(map(deep, pts)), len(moved_far)))
    cmds.move(-20.0, 0, 0, blk, relative=True)
    sb = tb["_ScBlocked"](None, [tb["_th_blocker_box"](rb) for rb in [box("rotBox", (10, 2, 2), (0, 0, 0), div=100.0)]
                                 if not cmds.rotate(0, 45, 0, rb)])
    check("rotated: its own box through its transform (+45 on Y: its length along x = -z)",
          sb.blocked((3.0, 0.0, -3.0)) and not sb.blocked((3.0, 0.0, 3.0)) and sb.at((3.0, 0.0, -3.0)) == -1.0 and
          sb.at((0.0, 0.0, 9.0)) == 0.0)
    cmds.delete("rotBox")

    tb["sc_set_blockers"](root, remove=[blk])
    check("Remove: grows there again, the mesh stays", sum(map(deep, part_points(tb, root, moss + "/moss"))) > 50 and
          cmds.objExists(blk) and not tb["sc_data"](root)["blockers"])

    # Add Blocker: the tool's own box
    undo0 = cmds.undoInfo(q=True, undoName=True)
    rep, node = tb["sc_create_blocker"](root)
    ctl = tb["sc_control"](root)
    check("Add Blocker: a red wireframe box in the control group, selected, linked",
          node and cmds.objExists(node) and (not ctl or node.startswith(ctl + "|")) and
          cmds.ls(selection=True, long=True) == [node] and cmds.getAttr(node + ".overrideColor") == 13 and
          tb["sc_data"](root)["blockers"] == cmds.ls(node, uuid=True), node)
    check("... never renders", not cmds.getAttr(tb["_log_shape"](node) + ".primaryVisibility"))
    check("... picks its group when clicked", tb["sc_owner"](node) == (root, None) and
          tb["sc_selection"]()["root"] == root and not tb["sc_selection"]()["surfaces"])
    bb = cmds.exactWorldBoundingBox(node)
    pts = part_points(tb, root, moss + "/moss")
    inside = [p for p in pts if bb[0] + 1.5 < p[0] < bb[3] - 1.5 and bb[2] + 1.5 < p[2] < bb[5] - 1.5 and
              p[1] < bb[4]]
    check("... and nothing grows in it", not inside and bb[0] < 0 < bb[3], "%d points" % len(inside))
    check("one Ctrl+Z", cmds.undoInfo(q=True, undoName=True) == "Scatter blocker" and undo0 != "Scatter blocker",
          cmds.undoInfo(q=True, undoName=True))
    cmds.undo()
    tb["sc_sync"]()
    check("Ctrl+Z takes it away (box and link)", not cmds.objExists(node) and
          not tb["sc_data"](root).get("blockers"))
    cmds.redo()
    tb["sc_sync"]()
    check("Ctrl+Y puts it back", cmds.objExists(node) and tb["sc_data"](root)["blockers"] == cmds.ls(node, uuid=True))

    # ivy avoids a blocker across the wall
    tb["sc_set_blockers"](root, remove=[node])
    _, ivy = tb["sc_add_layer"](root, "Ivy", {"vines": 8, "length": 2.0, "detail": "Proxy"})
    tb["sc_set_surfaces"](root, remove=[floor])

    def ivy_mid():
        p = part_points(tb, root, ivy + "/leaves") + part_points(tb, root, ivy + "/stems")
        return sum(1 for q in p if -7.0 < q[0] < 7.0), len(p)

    i0 = ivy_mid()
    wb = box("wallBlocker", (16, 20, 4), (0.0, 7.0, -13.5), div=100.0)
    tb["sc_set_blockers"](root, add=[wb])
    i1 = ivy_mid()
    check("Ivy: avoids a blocker across the wall", i0[0] > 100 and i1[0] < 0.1 * i0[0],
          "middle %d -> %d (all %d -> %d)" % (i0[0], i1[0], i0[1], i1[1]))
    tb["sc_remove_layer"](root, ivy)
    tb["sc_set_surfaces"](root, add=[floor])
    tb["sc_set_blockers"](root, add=[node])

    # Bake: the tool's box goes, yours stays
    done = tb["bake_scatter"]([root])
    check("Bake: the tool's blocker box goes, your blocker mesh stays", done == [root] and not cmds.objExists(node) and
          cmds.objExists(wb))
    cmds.undo()
    check("... one Ctrl+Z brings both back", tb["is_scatter"](root) and cmds.objExists(node))

    # a group made before blockers (no "blockers" key) grows exactly as before
    data = json.loads(cmds.getAttr(root + "." + tb["SC_ATTR"]))
    data.pop("blockers", None)
    cmds.setAttr(root + "." + tb["SC_ATTR"], json.dumps(data, sort_keys=True), type="string")
    tb["sc_regrow"](root, readback=False)
    check("no blockers: grows exactly as before", part_points(tb, root, moss + "/moss") == base)
    cmds.delete(root)


try:
    run()
except Exception:
    traceback.print_exc()
    RESULTS.append(("crashed", False, ""))
failed = [r for r in RESULTS if not r[1]]
print("\n%d checks, %d failed" % (len(RESULTS), len(failed)))
for name, _, detail in failed:
    print("FAILED: %s  %s" % (name, detail))
sys.stdout.flush()
maya.standalone.uninitialize()
os._exit(1 if failed else 0)
