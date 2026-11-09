"""Headless tests for the Scatter control group (mayapy).

    mayapy tests/test_scatter_control.py

A scatter group (scatteredObjects####_GRP) holds only plain, visible
geometry, so it can be dragged into a publish hierarchy as it is. Everything
that isn't for publishing - the bounding box and any instanced shoots (a
particle, an instancer, hidden prototype shapes) - lives in its control group
(scatterControl####_GRP), made beside the box. Parts that come out empty are
deleted, not hidden. A group laid out the old way (box alone, shoots and
hidden parts inside the group) is moved over without touching its geometry.
"""

import os
import re
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


def load_toolbox(path=TOOLBOX):
    ns = {"__name__": "unlok_test", "__file__": path}
    with open(path) as f:
        exec(compile(f.read(), path, "exec"), ns)
    return ns


def scene():
    r = cmds.polySphere(r=3.0, sx=20, sy=14, ch=False, name="rockGrey_C_test0001_GEP")[0]
    cmds.move(0, 2.0, 0, r)
    cmds.makeIdentity(r, apply=True)
    f = cmds.polyPlane(w=20, h=20, sx=6, sy=6, ch=False, name="groundSoil_C_test0001_GEP")[0]
    return [cmds.ls(x, long=True)[0] for x in (r, f)]


def short(n):
    return n.split("|")[-1] if n else n


def parent_of(n):
    p = cmds.listRelatives(n, parent=True, fullPath=True)
    return p[0] if p else None


def publishable(root):
    """Problems that would stop root being published as it is (empty: fine)."""
    bad = []
    for t in cmds.listRelatives(root, allDescendents=True, fullPath=True) or []:
        typ = cmds.nodeType(t)
        if typ == "transform":
            if not cmds.getAttr(t + ".visibility"):
                bad.append("hidden " + short(t))
            shapes = cmds.listRelatives(t, shapes=True, fullPath=True) or []
            if not shapes and not cmds.listRelatives(t, children=True):
                bad.append("empty " + short(t))
        elif typ != "mesh":
            bad.append("%s %s" % (typ, short(t)))
    return bad


def instances(tb, root):
    sh = tb["sc_shoots"](root)
    if not sh:
        return 0
    return len(tb["_sc_read_shoots"](list(sh.values())[0])[7]["pos"])


def rig_ok(tb, root, ctl):
    """The instanced shoots: in the control group, named nicely."""
    sh = list(tb["sc_shoots"](root).values())
    if len(sh) != 1:
        return False, "shoots nodes %d" % len(sh)
    node = sh[0]
    if parent_of(node) != ctl:
        return False, "shoots under %s" % short(parent_of(node))
    kids = [short(k) for k in cmds.listRelatives(node, children=True, fullPath=True) or []]
    m = re.match(r"^(\w+?)Shoots(\d{4})_GRP$", short(node))
    if not m:
        return False, "shoots node " + short(node)
    base, num = m.group(1) + "Shoots", m.group(2)
    protos = [short(p) for p in cmds.listRelatives(node + "|" + base + "Shapes" + num + "_GRP",
                                                   children=True, fullPath=True) or []] \
        if cmds.objExists(node + "|" + base + "Shapes" + num + "_GRP") else []
    ok = (base + num + "_INS") in kids and protos and \
        all(re.match(r"^\w+_C_shoot[A-Z]+%s_GEP$" % num, p) for p in protos)
    return ok, "%s %s %s" % (short(node), kids, protos)


def run():
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    nodes = scene()

    # -- a new group: geometry in the group, the box in a control group beside it
    cmds.select(clear=True)
    s = dict(tb["sc_start_settings"]("Moss"), detail="Normal")  # Proxy grows no shoots
    root = tb["create_scatter_group"](nodes, "Moss", s)["root"]
    lid = tb["sc_data"](root)["layers"][0]["id"]
    ctl, box = tb["sc_control"](root), tb["sc_box"](root)
    check("new: a control group", ctl and re.match(r"^scatterControl\d{4}_GRP$", short(ctl)), short(ctl))
    check("new: the box is in it", box and parent_of(box) == ctl, short(parent_of(box)))
    check("new: control at world, not in the group", parent_of(ctl) is None and parent_of(root) is None)
    check("new: a layer starts with mesh shoots",
          tb["sc_settings"](tb["sc_layer"](tb["sc_data"](root), lid))["shoots"] == "Mesh")
    check("new: the group is all plain visible geometry", not publishable(root), str(publishable(root)))
    check("new: control and box resolve to the group",
          tb["sc_owner"](ctl)[0] == root and tb["sc_owner"](box)[0] == root)

    # -- empty parts are deleted, not hidden
    tb["sc_update"](root, lid, {"capsules": 0.0, "strands": 0.0})
    check("empty parts deleted", not publishable(root), str(publishable(root)))
    tb["sc_update"](root, lid, {"strands": 1.0})

    # -- instanced shoots go in the control group
    pub = cmds.group(empty=True, name="publish_GRP")
    root = cmds.ls(cmds.parent(root, pub)[0], long=True)[0]
    tb["sc_update"](root, lid, {"shoots": "Instances"})
    ok, detail = rig_ok(tb, root, ctl)
    check("instances: rig in the control group, named", ok, detail)
    check("instances: the group stays publishable", not publishable(root), str(publishable(root)))
    check("instances: some instances", instances(tb, root) > 0, str(instances(tb, root)))
    proto = tb["_sc_shoot_nodes"](list(tb["sc_shoots"](root).values())[0])[2][0]
    check("instances: a prototype resolves to the group", tb["sc_owner"](proto)[0] == root)
    cmds.select(proto)
    check("instances: selecting a prototype picks the group", (tb["sc_selection"]() or {}).get("root") == root)
    tb["sc_update"](root, lid, {"coverage": 0.5})  # an edit with the group in a publish folder
    check("edit in publish folder: nothing hidden added", not publishable(pub), str(publishable(pub)))
    tb["sc_update"](root, lid, {"shoots": "Mesh"})
    check("mesh shoots: the rig is gone", not tb["sc_shoots"](root)
          and not cmds.listRelatives(ctl, allDescendents=True, type="instancer"))
    check("mesh shoots: the control group keeps the box", parent_of(tb["sc_box"](root)) == ctl)

    # -- a Ctrl+D copy gets its own control group, box and rig
    tb["sc_update"](root, lid, {"shoots": "Instances"})
    n0 = instances(tb, root)
    cp = cmds.ls(cmds.duplicate(root)[0], long=True)[0]
    tb["sc_fix_box"](cp)
    tb["sc_regrow"](cp)
    cctl = tb["sc_control"](cp)
    check("copy: its own control group", cctl and cctl != ctl, "%s %s" % (short(cctl), short(ctl)))
    check("copy: its own box in it", tb["sc_box"](cp) and parent_of(tb["sc_box"](cp)) == cctl)
    check("copy: its own shoots in it", instances(tb, cp) > 0 and rig_ok(tb, cp, cctl)[0], rig_ok(tb, cp, cctl)[1])
    check("copy: the original untouched", instances(tb, root) == n0 and tb["sc_control"](root) == ctl)

    # -- bake: the instances become geometry, the control group goes with the rig
    tb["bake_scatter"]([cp])
    check("bake: the control group goes", not cmds.objExists(cctl))
    cmds.undo()
    tb["sc_sync"]()
    check("bake undone: control group and shoots back",
          tb["sc_control"](cp) and instances(tb, cp) > 0)

    # -- an old-layout group: box alone at world, shoots + a hidden part inside the group
    cmds.select(clear=True)
    r2 = tb["create_scatter_group"](nodes, "Moss", dict(s, shoots="Instances"))["root"]
    l2 = tb["sc_data"](r2)["layers"][0]["id"]
    ctl2, box2 = tb["sc_control"](r2), tb["sc_box"](r2)
    sh = list(tb["sc_shoots"](r2).values())[0]
    n2 = instances(tb, r2)
    sh = cmds.parent(sh, r2)[0]
    cmds.rename(cmds.ls(sh, long=True)[0], "mossStrandShoots_C_" + short(r2))
    cmds.parent(box2, world=True)
    cmds.delete(ctl2)
    cmds.deleteAttr(r2 + "." + tb["SC_CTL_ID"])
    junk = cmds.polyCube(ch=False, name="mossSpore_C_old0001_GEP")[0]
    cmds.addAttr(cmds.listRelatives(junk, shapes=True)[0], longName=tb["SC_PART"], dataType="string")
    cmds.setAttr(cmds.listRelatives(junk, shapes=True, fullPath=True)[0] + "." + tb["SC_PART"],
                 l2 + "/capsules", type="string")
    junk = cmds.parent(junk, r2)[0]
    cmds.setAttr(r2 + "|" + junk + ".visibility", 0)
    pub2 = cmds.group(empty=True, name="publishOld_GRP")
    r2 = cmds.ls(cmds.parent(r2, pub2)[0], long=True)[0]
    geo = sorted(short(g) for g in cmds.listRelatives(r2, children=True, fullPath=True)
                 if cmds.getAttr(g + ".visibility") and cmds.listRelatives(g, shapes=True, type="mesh"))
    check("old layout: really old", not tb["sc_control"](r2) and publishable(r2), str(publishable(r2)))

    tb["sc_fix_box"](r2)
    c2 = tb["sc_control"](r2)
    check("upgrade: a control group beside the box", c2 and parent_of(c2) is None, short(c2))
    check("upgrade: the box in it", parent_of(tb["sc_box"](r2)) == c2)
    check("upgrade: the group left where it was", parent_of(r2) == cmds.ls(pub2, long=True)[0])
    ok, detail = rig_ok(tb, r2, c2)
    check("upgrade: shoots moved to the control group, renamed", ok, detail)
    check("upgrade: every instance kept", instances(tb, r2) == n2, "%d / %d" % (instances(tb, r2), n2))
    check("upgrade: the group now publishable", not publishable(r2), str(publishable(r2)))
    after = sorted(short(g) for g in cmds.listRelatives(r2, children=True, fullPath=True))
    check("upgrade: the geometry left as it was", after == geo, "%s / %s" % (after, geo))
    tb["sc_update"](r2, l2, {"coverage": 0.55})
    check("upgrade: edits after work", not publishable(r2) and instances(tb, r2) > 0)


try:
    run()
except Exception:
    traceback.print_exc()
    check("ran without errors", False)
fails = [r for r in RESULTS if not r[1]]
print("%d checks, %d failed" % (len(RESULTS), len(fails)))
sys.stdout.flush()
try:
    maya.standalone.uninitialize()
except Exception:
    pass
os._exit(1 if fails else 0)
