"""Headless test: Scatter's Add Layer (mayapy).

    mayapy tests/test_scatter_add_layers.py

The user (2026-11-19): "add layer somewhere specific in the stack (add
below, add above, etc.) Also more options for layer types, I don't see a
grass scattered blades option, moss option is the heaviest one that takes
a while to load ... Each layer option should build with a light preset,
then the user can bump up or select a more detailed preset if needed."

On the user's yard (a 40 x 40 dm floor, a one-piece wall ring 2 thick and
6 tall, a crate): the quick picks are in the menu, each grows something
and starts light; Light moss against the full Moss mat (time, vertices);
Add Above / Add Below / Duplicate put the layer where asked, and the list
in the panel is the group's (build) order; the step-up tip. Pictures of
the add menu and the right-click menu in tests/_out/scatter_add.
"""

import os
import sys
import time
import traceback

from PySide2 import QtWidgets, QtCore
APP = QtWidgets.QApplication(sys.argv)
import maya.standalone  # noqa: E402
maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402
import maya.api.OpenMaya as om  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.path.join(HERE, "_out", "scatter_add")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def yard(tb):
    src = open(os.path.join(HERE, "test_moss_slope.py")).read()
    ns = {"__name__": "x", "om": om, "cmds": cmds}
    exec(compile(src[src.index("def wall_ring("):src.index("def face_png(")], "ring", "exec"), ns)
    cmds.file(new=True, force=True)
    floor = cmds.polyPlane(w=40, h=40, sx=4, sy=4, name="floor", constructionHistory=False)[0]
    ring = ns["wall_ring"](tb, "wallRing")
    box = cmds.polyCube(w=6, h=4, d=6, name="crate", constructionHistory=False)[0]
    cmds.move(-8, 2, 5, box)
    return cmds.group(floor, ring, box, name="yard_GRP")


def layer_verts(tb, root, lid):
    n = 0
    for key, node in tb["sc_parts"](root).items():
        if key.split("/")[0] == lid:
            n += cmds.polyEvaluate(node, vertex=True)
    return n


def run():
    tb = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), tb)
    if not os.path.isdir(OUT):
        os.makedirs(OUT)

    # --- light moss against the full moss (each on a fresh yard, nothing cached)
    took = {}
    for preset in ("Moss mat", "Light moss"):
        grp = yard(tb)
        tb["mi_clear_caches"]()
        s = tb["sc_quick_settings"]("Moss", preset)
        t0 = time.time()
        rep = tb["create_scatter_group"]([grp], "Moss", s, select=False)
        took[preset] = (time.time() - t0, layer_verts(tb, rep["root"], tb["sc_data"](rep["root"])["layers"][0]["id"]))
        print("moss %s: %.2f s, %d verts" % (preset, took[preset][0], took[preset][1]))
    full, light = took["Moss mat"], took["Light moss"]
    check("Light moss grows something, no shoots / strands / capsules",
          light[1] > 0 and tb["sc_quick_settings"]("Moss")["strands"] == 0.0, "%d verts" % light[1])
    check("Light moss is much quicker and lighter than the full Moss mat",
          light[0] < 0.5 * full[0] and light[1] < 0.1 * full[1],
          "%.2f s / %d verts against %.2f s / %d verts" % (light[0], light[1], full[0], full[1]))
    check("Moss: full is today's new moss layer exactly",
          tb["sc_quick_settings"]("Moss", "Moss mat") == tb["sc_start_settings"]("Moss"))
    check("a new layer of a type starts light (SC_LIGHT)",
          tb["SC_LIGHT"]["Moss"] == "Light moss" and tb["SC_LIGHT"]["Grass"] == "Scattered blades" and
          all(t in tb["SC_LIGHT"] for t in tb["SC_TYPES"]), str(tb["SC_LIGHT"]))
    check("every quick pick names a real preset and a fuller one",
          all(q[2] in tb["SC_PRESETS"][q[1]] and q[3] in tb["SC_PRESETS"][q[1]] for q in tb["SC_QUICK"] if q))

    # --- every quick pick grows something on the yard
    grp = yard(tb)
    tb["mi_clear_caches"]()
    rep = tb["create_scatter_group"]([grp], "Moss", tb["sc_quick_settings"]("Moss"), select=False)
    root = rep["root"]
    rows = []
    for q in tb["SC_QUICK"]:
        if not q:
            continue
        t0 = time.time()
        # on top: nothing above it lies on it, so only it grows (added at the bottom, every layer above with
        # On layers below grows again on it)
        lid = tb["sc_add_layer"](root, q[1], tb["sc_quick_settings"](q[1], q[2]), top=True)[1]
        dt = time.time() - t0
        rows.append((q[0], dt, layer_verts(tb, root, lid)))
        print("  %-34s %5.2f s  %8d verts" % rows[-1])
    check("every quick pick grows something", all(r[2] > 0 for r in rows),
          ", ".join("%s %d" % (r[0], r[2]) for r in rows if r[2] <= 0))
    lite = [r for r in rows if "full" not in r[0]]
    check("every light quick pick grows in under 4 s here (added on top)", all(r[1] < 4.0 for r in lite),
          ", ".join("%s %.1fs" % (r[0], r[1]) for r in lite if r[1] >= 4.0))
    check("every light quick pick is under the full moss's vertices",
          all(r[2] < full[1] for r in lite), ", ".join("%s %d" % (r[0], r[2]) for r in lite if r[2] >= full[1]))

    # --- the panel: menus, where layers go, duplicate, the tip
    grp = yard(tb)
    rep = tb["create_scatter_group"]([grp], "Moss", tb["sc_quick_settings"]("Moss"), select=False)
    root = rep["root"]
    panel = tb["ScatterPanel"]()
    panel._root = root
    panel._lid = tb["sc_data"](root)["layers"][0]["id"]
    panel._refresh()
    texts = [a.text() for a in panel.add_btn.menu().actions()]
    check("Add Layer's menu has the quick picks, Grass: scattered blades among them",
          all(q[0] in texts for q in tb["SC_QUICK"] if q) and "Grass: scattered blades" in texts, str(texts))
    check("... and where new layers go (top / bottom / above / below)",
          all(panel.add_where[k].text() in texts for k in tb["SC_ADD_WHERE"]) and panel.add_top is
          panel.add_where["top"])

    def order():
        return [l["id"] for l in tb["sc_data"](root)["layers"]]

    def list_order():
        return [panel.layer_list.item(i).data(QtCore.Qt.UserRole) for i in range(panel.layer_list.count())]

    a = order()[0]
    panel.add_layer("Grass", "Scattered blades", where="bottom", label="Grass: scattered blades")
    b = panel._lid
    check("Add at the bottom", order() == [a, b], str(order()))
    check("the step-up tip is in the status", "Loose wisps" in panel.status.text() and "Presets" in
          panel.status.text(), panel.status.text())
    panel._lid = b
    panel.add_layer("Leaves", where="above")
    c = panel._lid
    check("Add Above the picked layer", order() == [a, c, b], str(order()))
    panel._lid = a
    panel.add_layer("Specks", where="below")
    d = panel._lid
    check("Add Below the picked layer", order() == [a, d, c, b], str(order()))
    panel._lid = c
    panel.duplicate_layer()
    e = panel._lid
    layers = tb["sc_data"](root)["layers"]
    check("Duplicate goes right above its source", order() == [a, d, e, c, b] and
          layers[2]["type"] == "Leaves", str(order()))
    panel.add_where["top"].setChecked(True)
    panel.add_layer("Ivy")
    f = panel._lid
    check("New layers go on top (the remembered choice)", order()[0] == f and not panel.add_where["bottom"].isChecked())
    panel.add_where["below"].setChecked(True)
    check("one where-choice at a time, remembered", [k for k in tb["SC_ADD_WHERE"] if panel.add_where[k].isChecked()]
          == ["below"] and cmds.optionVar(q=tb["SC_ADD_WHERE_VAR"]) == "below")
    panel._lid = b
    panel.add_layer("Moss tufts")
    g = panel._lid
    check("... and used by Add Layer (below the picked one)", order()[-1] == g and order()[-2] == b, str(order()))
    panel.add_where["top"].setChecked(True)
    check("the panel's list is the group's order (the build order)", list_order() == order())
    check("a light Moss layer added through the panel is light",
          tb["sc_settings"](tb["sc_layer"](tb["sc_data"](root), a))["strands"] == 0.0)

    # pictures: the add menu and the right-click menu
    menu = panel.add_btn.menu()
    menu.adjustSize()
    menu.grab().save(os.path.join(OUT, "add_menu.png"))
    rc = QtWidgets.QMenu()
    above, below = rc.addMenu("Add Above"), rc.addMenu("Add Below")
    panel._quick_actions(above, "above")
    panel._quick_actions(below, "below")
    rc.addSeparator()
    for t in ("Duplicate", "Move Up", "Move Down", "Delete"):
        rc.addAction(t)
    rc.adjustSize()
    rc.grab().save(os.path.join(OUT, "layer_right_click.png"))
    above.adjustSize()
    above.grab().save(os.path.join(OUT, "add_above_submenu.png"))
    panel.step_layers.adjustSize()
    panel.step_layers.grab().save(os.path.join(OUT, "layers_card.png"))
    print("pictures:", OUT)
    with open(os.path.join(OUT, "timings.txt"), "w") as fh:
        fh.write("moss full (Moss mat): %.2f s, %d verts\nmoss light (Light moss): %.2f s, %d verts\n" % (
            full[0], full[1], light[0], light[1]))
        for r in rows:
            fh.write("%-34s %5.2f s  %8d verts\n" % r)
    panel.deleteLater()


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
