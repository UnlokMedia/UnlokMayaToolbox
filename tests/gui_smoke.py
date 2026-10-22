"""GUI smoke test: run inside an interactive Maya session.

Opens the toolbox, draws paths through the real viewport (simulated strokes
that go through the same ray-casting as the mouse), drives the panel, saves
screenshots and writes a results log. Then quits Maya if UNLOK_TEST_QUIT=1.

Launch (Maya 2023+):

    maya.exe -script tests/run_gui_smoke.mel

Outputs go to $UNLOK_TEST_OUT (default: tests/_out).
"""

import json
import os
import time
import traceback

import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaUI as omui

try:
    from PySide2 import QtWidgets
except ImportError:
    from PySide6 import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append({"name": name, "ok": bool(cond), "detail": str(detail)})
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))


def pump(n=5):
    app = QtWidgets.QApplication.instance()
    for _ in range(n):
        app.processEvents()
    cmds.refresh(force=True)


def screen_point(view, p):
    res = view.worldToView(om.MPoint(*p))
    return float(res[0]), float(res[1])


def snap(name, width=1280, height=720):
    path = os.path.join(OUT, name)
    cmds.refresh(force=True)
    cmds.playblast(frame=[cmds.currentTime(q=True)], format="image", compression="png", completeFilename=path,
                   viewer=False, showOrnaments=False, percent=100, widthHeight=(width, height), offScreen=True)
    return path


def build_roof():
    """Gable roof: two sloped slabs meeting at a ridge, plus walls."""
    house = cmds.polyCube(w=8, h=4, d=6, name="house")[0]
    cmds.move(0, 2, 0, house)
    left = cmds.polyPlane(w=8.6, h=4.6, sx=8, sy=4, name="roofLeft")[0]
    cmds.rotate(-35, 0, 0, left)
    cmds.move(0, 5.3, -1.85, left)
    right = cmds.polyPlane(w=8.6, h=4.6, sx=8, sy=4, name="roofRight")[0]
    cmds.rotate(35, 0, 0, right)
    cmds.move(0, 5.3, 1.85, right)
    for n in (left, right):
        cmds.makeIdentity(n, apply=True)
    return house, left, right


def stroke(drawer, view, world_pts, mod="none", steps=40):
    pts = [screen_point(view, p) for p in world_pts]
    drawer.press_at(pts[0][0], pts[0][1], mod)
    for i in range(1, steps + 1):
        t = float(i) / steps
        seg = min(int(t * (len(pts) - 1)), len(pts) - 2)
        lt = t * (len(pts) - 1) - seg
        x = pts[seg][0] + (pts[seg + 1][0] - pts[seg][0]) * lt
        y = pts[seg][1] + (pts[seg + 1][1] - pts[seg][1]) * lt
        drawer.drag_at(x, y)
    drawer.release()


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    ns = {"__name__": "__main__", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    import __main__
    window = getattr(__main__, ns["REGISTRY_KEY"])["window"]
    panel = window.panels()[0]
    PSS = ns["PathScatterSystem"]
    check("window opens", window.isVisible())
    check("fresh panel says what to do first", "Draw Path" in panel.next_banner.text.text(),
          panel.next_banner.text.text())
    window.grab().save(os.path.join(OUT, "00_path_scatter_start.png"))

    cmds.file(new=True, force=True)
    house, left, right = build_roof()
    cmds.setAttr("persp.translate", 18, 13, 15)
    cmds.viewLookAt("persp", position=(0, 4.5, 0))
    pump()
    view = omui.M3dView.active3dView()
    check("viewport available", view.portWidth() > 0, "%dx%d" % (view.portWidth(), view.portHeight()))

    # --- draw a freehand stroke along the eave of the right-hand roof slab
    cmds.select(clear=True)
    panel.toggle_draw()
    check("draw tool activates", ns["SurfacePathDrawer"].is_active())
    eave = [(-3.8, 3.85, 3.4), (0.0, 3.9, 3.35), (3.8, 3.85, 3.4)]
    stroke(panel.drawer, view, eave)
    pump()
    panel.rebuild()
    system = panel.system
    check("stroke creates a scatter system", system is not None and system.exists())
    check("stroke locked onto the roof surface", any("roofRight" in s for s in system.surfaces()), str(system.surfaces()))
    curve = system.paths()[0]
    fn = om.MFnMesh(ns["get_dag_path"](right))
    cvs = cmds.getAttr(curve + ".cv[*]")
    worst = max((fn.getClosestPoint(om.MPoint(*cv), om.MSpace.kWorld)[0] - om.MPoint(*cv)).length() for cv in cvs)
    check("drawn curve lies on the surface", worst < 0.15, "max CV distance %.3f" % worst)

    # --- shingles: rows up the slope, staggered, lifted, tilted
    settings = dict(panel.settings(), size_x=0.6, size_y=0.04, size_z=0.45, gap=0.02, rows=10,
                    row_spacing=-0.38, row_stagger=0.5, row_lift=0.0, rot_z=0.0, surface_offset=0.02)
    panel.set_settings(settings)
    t0 = time.time()
    panel.rebuild()
    ms = (time.time() - t0) * 1000
    count = system.last_count
    check("shingle grid builds", count > 80, "%d items in %.0f ms (%s)" % (count, ms, panel.status.text()))
    snap("01_shingles_one_side.png")
    window.grab().save(os.path.join(OUT, "03b_path_scatter_live.png"))
    check("guidance: drawing instructions while drawing, Bake is the current step",
          panel.next_banner.tag.text() == "DRAWING" and panel.step_bake.state == "current",
          panel.next_banner.text.text())

    # --- Ctrl+stroke adds a second path on the other slab (seen from behind)
    cmds.setAttr("persp.translate", 18, 13, -15)
    cmds.viewLookAt("persp", position=(0, 4.5, 0))
    pump()
    eave2 = [(3.8, 3.85, -3.4), (-3.8, 3.85, -3.4)]
    stroke(panel.drawer, view, eave2, mod="ctrl")
    pump()
    panel.rebuild()
    check("ctrl-stroke adds a path", len(system.paths()) == 2, str(system.paths()))
    check("both roof slabs are surfaces", len(system.surfaces()) == 2, str(system.surfaces()))
    snap("02_shingles_both_sides.png")
    cmds.setAttr("persp.translate", 18, 13, 15)
    cmds.viewLookAt("persp", position=(0, 4.5, 0))
    pump()

    # --- shift = straight line (still follows the surface)
    stroke(panel.drawer, view, [(-3.5, 4.5, 2.4), (3.5, 4.5, 2.4)], mod="shift")
    pump()
    check("shift-stroke replaces with a single straight path", len(system.paths()) == 1)
    panel.toggle_draw()
    check("draw tool deactivates", not ns["SurfacePathDrawer"].is_active())
    check("guidance points at Bake once drawing stops", "Bake" in panel.next_banner.text.text(),
          panel.next_banner.text.text())

    # --- heavy-ish preview timing
    panel.set_settings(dict(panel.settings(), rows=40, row_spacing=-0.1, size_x=0.1, size_z=0.1, gap=0.0))
    t0 = time.time()
    panel.rebuild()
    check("large preview stays fast", system.last_count > 2000,
          "%d items in %.0f ms" % (system.last_count, (time.time() - t0) * 1000))

    # --- mesh variants (rocks), hidden sources must not hide instances
    rocks = []
    for i in range(3):
        r = cmds.polySphere(r=0.25, sx=8, sy=6, name="rock%d" % i)[0]
        cmds.move(-6 + i, 0, 6, r)
        rocks.append(r)
    path = cmds.curve(degree=3, point=[(-6, 0, 4), (-3, 0, 7), (0, 0, 4), (3, 0, 8), (6, 0, 5)], name="rockPath")
    panel.new_system()
    cmds.select(rocks)
    panel.use_selected_meshes()
    cmds.select(path)
    panel.use_selected_path()
    panel.set_settings(dict(panel.settings(), rows=1, dist_mode="Spacing", spacing=0.35, rand_scale_min=0.5,
                            rand_scale_max=1.4, rand_rot_x=180, rand_rot_y=180, rand_rot_z=180,
                            rand_side=0.4, up_mode="World Up", snap_surface=False, scale=1.0))
    panel.rebuild()
    rock_system = panel.system
    check("rock scatter", rock_system is not None and rock_system.last_count > 20 and rock_system is not system,
          panel.status.text())
    cmds.select(clear=True)
    snap("03_rocks_and_roof.png")

    # --- selecting a system's node loads it back into the panel
    check("scene script jobs installed", len(panel._jobs) == 4 and all(cmds.scriptJob(exists=j) for j in panel._jobs))
    cmds.select(system.instancer())
    panel._on_selection_changed()  # the job itself only fires once Maya is idle
    pump()
    check("selecting a scatter loads it", panel.system is not None and panel.system.uuid == system.uuid)
    check("its settings come back", panel.fields["rows"].value() == 40, str(panel.fields["rows"].value()))

    # --- live update when the user edits the path curve
    cmds.select(rock_system.root())
    panel._on_selection_changed()
    pump()
    cmds.move(0, 0, 2, "rockPath.cv[2]", relative=True)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        pump(1)
    check("editing a curve keeps working (no crash)", rock_system.exists())

    # --- bake
    panel.fields["bake_mode"].setValue("Instances")
    panel.bake()
    baked = cmds.ls(selection=True, long=True)
    check("bake instances from panel", baked and cmds.listRelatives(baked[0], children=True), panel.status.text())
    window.grab().save(os.path.join(OUT, "04_panel.png"))

    # --- undo after all this must not crash and must not resurrect weirdness
    for _ in range(5):
        try:
            cmds.undo()
        except RuntimeError:
            pass
    pump()
    check("undo after tool use is safe", True)

    # --- messy thatch roof from the recipe, both slabs
    cmds.file(new=True, force=True)
    house, left, right = build_roof()
    panel.new_system()
    panel.apply_recipe("Messy Thatch")
    check("recipe sets thatch strands", abs(panel.fields["size_z"].value() - 1.2) < 1e-6
          and panel.fields["rows"].value() == 12)
    cmds.setAttr("persp.translate", 18, 13, 15)
    cmds.viewLookAt("persp", position=(0, 4.5, 0))
    pump()
    view = omui.M3dView.active3dView()
    panel.toggle_draw()
    stroke(panel.drawer, view, [(-4.2, 3.85, 3.4), (4.2, 3.85, 3.4)])
    cmds.setAttr("persp.translate", 18, 13, -15)
    cmds.viewLookAt("persp", position=(0, 4.5, 0))
    pump()
    view = omui.M3dView.active3dView()
    stroke(panel.drawer, view, [(4.2, 3.85, -3.4), (-4.2, 3.85, -3.4)], mod="ctrl")
    panel.toggle_draw()
    t0 = time.time()
    panel.rebuild()
    ms = (time.time() - t0) * 1000
    thatch = panel.system
    info = [(c.split("|")[-1], round(cmds.arclen(c), 2)) for c in thatch.paths()]
    check("thatch strokes land on the visible roof slabs, not the wall behind",
          sorted(x.split("|")[-1] for x in thatch.surfaces()) == ["roofLeft", "roofRight"], str(thatch.surfaces()))
    check("thatch builds", thatch is not None and thatch.last_count > 4000,
          "%d strands in %.0f ms, paths %s, surfaces %s" % (thatch.last_count, ms, info, thatch.surfaces()))
    times = []
    for seed in range(3):
        panel.fields["seed"].setValue(seed + 10)
        t0 = time.time()
        panel.rebuild()
        times.append((time.time() - t0) * 1000)
    check("thatch re-rolls stay interactive", max(times) < 1500, "rebuilds: %s ms" % [int(t) for t in times])
    cmds.setAttr("persp.translate", 14, 9, 12)
    cmds.viewLookAt("persp", position=(0, 4.5, 0))
    cmds.select(clear=True)
    snap("06_thatch.png")
    cmds.setAttr("persp.translate", 5, 5.5, 6)
    cmds.viewLookAt("persp", position=(1, 4.2, 2.5))
    snap("07_thatch_closeup.png")
    cmds.setAttr("persp.translate", 14, 9, -12)
    cmds.viewLookAt("persp", position=(0, 4.5, 0))
    snap("08_thatch_back.png")

    # --- Smart UDIM panel: pick root, scan, edit, pre-process
    cmds.file(new=True, force=True)
    window = getattr(__main__, ns["REGISTRY_KEY"])["window"]
    udim = [p for p in window.panels() if p.TOOL_NAME == "Smart UDIM"][0]
    window.tabs.setCurrentIndex([window.tabs.tabText(i) for i in range(window.tabs.count())].index("UV"))
    house = cmds.group(empty=True, name="house_GRP")
    for wing in ("westWing_GRP", "eastWing_GRP"):
        grp = cmds.group(empty=True, name=wing, parent=house)
        for i, nm in enumerate(("woodGreen_C_beam%04d_GEP", "glassClear_F_window%04d_GEP", "brickRed_B_wall%04d_GES")):
            node = cmds.polyCube(name=nm % (i + 1))[0]
            cmds.parent(node, grp)
    bad = cmds.parent(cmds.polyCylinder(name="pipe_final", sx=8, sc=0)[0], house)[0]
    cmds.select(house)
    udim.pick_root()
    udim.from_groups.setValue(True)
    udim.scan()
    pump()
    sections = [udim.tree.topLevelItem(i).text(0) for i in range(udim.tree.topLevelItemCount())]
    check("Smart UDIM scan fills the tree", sorted(sections) == ["eastWing", "house", "westWing"],
          "%s | %s" % (sections, udim.status.text()))
    first = udim.tree.topLevelItem(0)
    mat_item = first.child(0)
    mat_item.setText(udim.COL_TD, "150")
    pump()
    udim.refresh()
    tds = [udim.tree.topLevelItem(0).child(i).text(udim.COL_TD) for i in range(udim.tree.topLevelItem(0).childCount())]
    check("editing TD % in the tree renames the set", "150" in tds, str(tds))
    listed = {udim.naming_list.topLevelItem(i).text(0): udim.naming_list.topLevelItem(i).text(1)
              for i in range(udim.naming_list.topLevelItemCount())}
    check("naming hand-off lists the bad name (and soft issues like glassClear)",
          "pipe_final" in listed and "suffix" in listed["pipe_final"]
          and all("glassClear" in k for k in listed if k != "pipe_final"), str(listed))
    udim.run_preprocess()
    cats = [udim.report_tree.topLevelItem(i).text(0) for i in range(udim.report_tree.topLevelItemCount())]
    check("pre-process report shows n-gons", any("N-gons" in c for c in cats), "%s | %s" % (cats, udim.status.text()))
    pump()
    window.grab().save(os.path.join(OUT, "09_smart_udim_panel.png"))

    # --- Auto UV through the panel: analyse, then unwrap + pack
    for i in range(3):
        c = cmds.polyCube(name="woodBrown_C_rafter%04d_GEP" % (i + 1))[0]
        cmds.polyMapDel(c + ".f[*]", constructionHistory=False)
        cmds.parent(c, "|house_GRP|westWing_GRP")
    udim.scan()
    udim.analyse_uvs()
    pump()
    actions = [udim.auto_tree.topLevelItem(i).text(3) for i in range(udim.auto_tree.topLevelItemCount())]
    check("Analyse lists the un-UV'd rafters first", actions[:3] == ["will unwrap"] * 3, str(actions[:6]))
    udim.auto_uv()
    pump()
    actions = [udim.auto_tree.topLevelItem(i).text(3) for i in range(udim.auto_tree.topLevelItemCount())]
    check("Auto UV unwraps them and keeps the rest", actions.count("unwrapped") >= 3 and "failed" not in actions,
          "%s | %s" % (actions, udim.status.text()))
    check("Auto UV step shows done", udim.step_auto.state == "done", udim.next_banner.text.text())
    udim.step_auto.parentWidget().parentWidget().parentWidget().ensureWidgetVisible(udim.step_auto) \
        if hasattr(udim.step_auto.parentWidget().parentWidget().parentWidget(), "ensureWidgetVisible") else None
    pump()
    window.grab().save(os.path.join(OUT, "10_auto_uv.png"))

    # --- per-mesh UV status: mark a rafter Hands off from the selection
    rafter = cmds.ls("woodBrown_C_rafter0001_GEP", long=True)[0]
    cmds.select(rafter, replace=True)
    udim.mark_status("handsoff")
    pump()
    status_col = {udim.auto_tree.topLevelItem(i).data(0, ns["QtCore"].Qt.UserRole):
                  udim.auto_tree.topLevelItem(i).text(4) for i in range(udim.auto_tree.topLevelItemCount())}
    check("Hands off button marks the selection (Status column + hint)", status_col.get(rafter) == "Hands off" and
          "1 Hands off" in udim.status_hint.text(), "%s | %s" % (status_col.get(rafter), udim.status_hint.text()))
    rafter_uvs = cmds.polyEditUV(rafter + ".map[*]", q=True)

    # --- Smart layout through the panel: plan (map), lock a group, apply
    udim.lay_density.setValue(2048.0)
    udim.lay_map.setValue("1024")
    udim.plan_layout()
    pump()
    check("Plan fills the UDIM map", len(udim.udim_map.shells) > 0 and udim.udim_map.tiles,
          "%d shells, tiles %s | %s" % (len(udim.udim_map.shells), sorted(udim.udim_map.tiles),
                                        udim.layout_summary.text()[:160]))
    check("UDIM map shows the hands-off piece", len(udim.udim_map.fixed) > 0 and
          "hands-off" in udim.layout_summary.text(), udim.layout_summary.text()[-200:])
    udim.lay_handsoff.setValue("Reserve their tiles")
    udim.plan_layout()
    check("Hands-off tiles can be reserved instead", "tiles reserved" in udim.layout_summary.text(),
          udim.layout_summary.text()[-200:])
    udim.lay_handsoff.setValue("Pack around them")
    udim.plan_layout()
    pump()
    udim.lay_density.spin.setValue(1024.0)  # like a user edit: emits, so it live re-plans from cached shells
    deadline = time.time() + 1.0
    while time.time() < deadline:
        pump(1)
    check("changing a setting re-plans live", "1024 px/m" in udim.layout_summary.text(),
          udim.layout_summary.text()[:120])
    first = udim.tree.topLevelItem(0).child(0)
    first.setCheckState(udim.COL_LOCK, ns["QtCore"].Qt.Checked)
    pump()
    udim.apply_layout()
    pump()
    check("Apply Layout writes it and the step completes", udim.step_layout.state == "done" and
          "Laid out" in udim.status.text(), udim.status.text())
    check("Apply leaves the hands-off rafter's UVs alone", cmds.polyEditUV(rafter + ".map[*]", q=True) == rafter_uvs)
    check("locked group shows as locked in the map", bool(udim.udim_map.locked_tiles),
          str(sorted(udim.udim_map.locked_tiles)))
    scroll = udim.step_layout.parentWidget().parentWidget().parentWidget()
    if hasattr(scroll, "ensureWidgetVisible"):
        scroll.ensureWidgetVisible(udim.udim_map)
    pump()
    window.grab().save(os.path.join(OUT, "11_smart_layout.png"))
    udim.udim_map.grab().save(os.path.join(OUT, "12_udim_map.png"))

    # --- validate + hand-off sheet through the panel
    udim.validate()
    pump()
    cats = [udim.check_tree.topLevelItem(i).text(0) for i in range(udim.check_tree.topLevelItemCount())]
    check("Validate fills the report", bool(cats), "%s | %s" % (cats, udim.status.text()))
    QtWidgets.QApplication.clipboard().clear()
    udim.copy_sheet()
    pump()
    clip = QtWidgets.QApplication.clipboard().image()
    check("Copy Sheet puts the hand-off sheet on the clipboard", not clip.isNull() and clip.width() > 200,
          "%dx%d" % (clip.width(), clip.height()))
    clip.save(os.path.join(OUT, "13_handoff_sheet.png"))
    check("step 8 is the current step or done", udim.step_check.state in ("current", "done"),
          udim.next_banner.text.text())
    scroll = udim.step_check.parentWidget().parentWidget().parentWidget()
    if hasattr(scroll, "ensureWidgetVisible"):
        scroll.ensureWidgetVisible(udim.step_check)
    pump()
    window.grab().save(os.path.join(OUT, "14_check_handoff.png"))

    # --- Log Noise: select cylinders, apply, live slider, bake
    cmds.file(new=True, force=True)
    tabs = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    window.tabs.setCurrentIndex(tabs.index("Modeling"))
    lognoise = [p for p in window.panels() if p.TOOL_NAME == "Log Noise"][0]
    window.tabs.currentWidget().stack.setCurrentWidget(lognoise)
    logs = []
    for i in range(5):
        c = cmds.polyCylinder(r=0.15, h=2, sx=24, sy=20, name="log%d" % (i + 1))[0]
        cmds.move(i * 0.6 - 1.2, 1, 0, c)
        logs.append(c)
    cmds.select(logs[1:])
    pump()
    lognoise._sync_from_selection()
    check("Log Noise asks to apply once logs are selected", "Apply" in lognoise.next_banner.text.text(),
          lognoise.next_banner.text.text())
    vtx = logs[1] + ".vtx[300]"
    rest = cmds.pointPosition(vtx, local=True)
    lognoise.apply()
    pump()
    shaped = cmds.pointPosition(vtx, local=True)
    check("Apply to Selected shapes every selected log", all(ns["has_log_noise"](cmds.ls(l, long=True)[0])
                                                              for l in logs[1:]) and shaped != rest and
          "Added noise to 4" in lognoise.status.text(), lognoise.status.text())
    lognoise.f["bend"].spin.setValue(0.12)  # like a user edit: emits, live update
    deadline = time.time() + 1.0
    while time.time() < deadline:
        pump(1)
    check("a slider edits the selected logs live", cmds.pointPosition(vtx, local=True) != shaped and
          all(ns["log_settings"](cmds.ls(l, long=True)[0])["bend"] == 0.12 for l in logs[1:]),
          lognoise.status.text())
    window.grab().save(os.path.join(OUT, "15_log_noise.png"))
    cmds.select(clear=True)
    cmds.setAttr("persp.translate", 0, 1.2, 6)
    cmds.setAttr("persp.rotate", 0, 0, 0)
    snap("16_log_noise_viewport.png")
    cmds.select(logs[1:])
    lognoise.bake()
    pump()
    check("Bake keeps the logs and drops the settings", not any(ns["has_log_noise"](cmds.ls(l, long=True)[0])
                                                                 for l in logs) and
          cmds.pointPosition(vtx, local=True) != rest, lognoise.status.text())

    # --- re-paste replaces the window cleanly
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), {"__name__": "__main__", "__file__": TOOLBOX})
    pump()
    windows = [w for w in QtWidgets.QApplication.instance().topLevelWidgets()
               if w.objectName() == ns["WINDOW_OBJECT_NAME"] and w.isVisible()]
    check("re-running the script leaves one window", len(windows) == 1, str(len(windows)))
    windows[0].grab().save(os.path.join(OUT, "05_fresh_window.png"))


def run():
    try:
        main()
    except Exception:
        RESULTS.append({"name": "exception", "ok": False, "detail": traceback.format_exc()})
        traceback.print_exc()
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(RESULTS, f, indent=2)
    if os.environ.get("UNLOK_TEST_QUIT") == "1":
        cmds.quit(force=True)


cmds.evalDeferred(run, lowestPriority=True)
