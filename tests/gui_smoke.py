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

    # --- section tools: delete a section, then rebuild it from its group
    def section_item(name):
        for i in range(udim.tree.topLevelItemCount()):
            if udim.tree.topLevelItem(i).text(0) == name:
                return udim.tree.topLevelItem(i)
        return None

    def section_names():
        return sorted(udim.tree.topLevelItem(i).text(0) for i in range(udim.tree.topLevelItemCount()))

    udim.tree.clearSelection()
    section_item("eastWing").setSelected(True)
    udim.delete_sections()
    pump()
    check("Delete Section moves its meshes to another section", section_names() == ["house", "westWing"] and
          not udim.snapshot["unassigned"], "%s | %s" % (section_names(), udim.status.text()))
    cmds.select("|house_GRP|eastWing_GRP")
    udim.section_from_group(name="eastWing")
    pump()
    check("Section from Group rebuilds it from the selected group",
          section_names() == ["eastWing", "house", "westWing"] and section_item("eastWing").childCount() >= 3,
          "%s | %s" % (section_names(), udim.status.text()))
    # --- a material group follows a Maya group: meshes added to it later join live
    asset = udim._asset()
    west = cmds.ls("|house_GRP|westWing_GRP", long=True)[0]
    porch = cmds.ls(cmds.group(empty=True, name="porch_GRP", parent=west), long=True)[0]
    sec = section_item("westWing")
    mat_item = sec.child(0)
    target = mat_item.data(0, ns["QtCore"].Qt.UserRole)
    udim.tree.clearSelection()
    mat_item.setSelected(True)
    cmds.select(porch, replace=True)
    udim.follow_selected_groups()
    pump()
    cube = cmds.polyCube(name="ropeTan_C_tie0001_GEP")[0]
    cube = cmds.ls(cmds.parent(cube, porch)[0], long=True)[0]  # like dragging it in the Outliner
    deadline = time.time() + 2.0
    while time.time() < deadline:
        pump(1)
    members = asset.assignments().get(cube, [])
    check("a mesh dropped into a followed group joins its material group by itself",
          [s for s, _ in members] == [target], "%s | %s" % (members, udim.status.text()[:150]))
    check("the list marks the followed group", mat_item is not None and "Follows" in (
        [udim.tree.topLevelItem(i) for i in range(udim.tree.topLevelItemCount())
         if udim.tree.topLevelItem(i).text(0) == "westWing"][0].child(0).toolTip(0)))
    cmds.delete(porch)  # leave the scene as the later checks expect it
    pump()
    udim.refresh()

    # --- Check & Fix Groups: a stray mesh in no group gets sorted in
    stray = cmds.polyCube(name="woodBrown_C_stray0001_GEP")[0]
    stray = cmds.ls(cmds.parent(stray, "|house_GRP")[0], long=True)[0]
    report = asset.group_health()
    dlg = ns["GroupHealthDialog"](report, udim)
    dlg.show()
    pump()
    dlg.grab().save(os.path.join(OUT, "08b_check_fix_groups.png"))
    dlg.close()
    udim.check_groups(confirm=False)
    pump()
    check("Check & Fix Groups sorts a mesh that's in no group", stray in asset.assignments() and
          ("Groups fixed" in udim.status.text() or "in order" in udim.status.text()), udim.status.text()[:200])
    cmds.delete(stray)
    pump()
    udim.refresh()
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
    open_steps = [c.number for c in udim.steps if c.expanded]
    check("progressive disclosure: only the current step (and ones needing a look) are open",
          udim.step_scan.state == "done" and not udim.step_scan.expanded and udim.step_scan.summary.text(),
          "open %s, scan summary %r" % (open_steps, udim.step_scan.summary.text()))
    udim.step_nav.go(udim.step_scan)
    pump()
    check("the step strip opens a folded step", udim.step_scan.expanded)
    udim.step_scan.toggle()
    pump()

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
    # marking is just set membership: instant, no re-scoring
    scored = udim.auto_result
    third = cmds.ls("woodBrown_C_rafter0003_GEP", long=True)[0]
    cmds.select(third)
    t_mark = time.time()
    udim.mark_status("keep")
    t_mark = time.time() - t_mark
    row = [r for r in udim.auto_result["rows"] if r["mesh"] == third][0]
    check("Keep UVs is instant: no re-scoring, the row just updates", udim.auto_result is scored and
          row["action"] == "keep UVs" and t_mark < 1.0, "%.2fs, %s" % (t_mark, row["action"]))
    udim.mark_status("auto")
    check("...and back to Auto restores 'will unwrap' from the known score",
          [r for r in udim.auto_result["rows"] if r["mesh"] == third][0]["action"] == "will unwrap")
    # undo only refreshes the panel when the asset itself changed
    import maya.utils as mu
    udim.refresh()
    cmds.undoInfo(openChunk=True, chunkName="unrelated edit")
    cmds.spaceLocator(name="unrelatedLoc")
    cmds.undoInfo(closeChunk=True)
    udim._refresh_timer.stop()
    cmds.undo()
    mu.processIdleEvents()
    unrelated = udim._refresh_timer.isActive()
    dirty_unrelated = udim._dirty
    cmds.select(third)
    udim.mark_status("keep")
    udim._refresh_timer.stop()
    cmds.undo()
    mu.processIdleEvents()
    related = udim._refresh_timer.isActive()
    dirty_after_mark_undo = udim._dirty
    pump(5)
    check("undo skips the panel refresh for unrelated edits, but not for the asset's own",
          not unrelated and related, "unrelated refresh %s, mark undo refresh %s, dirty %s, unrelated dirty %s" % (
              unrelated, related, dirty_after_mark_undo, dirty_unrelated))
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

    # --- UV status colours, select by colour, Auto UV Selected
    udim.colour_box.setChecked(True)  # like a click: colours the meshes
    pump()
    legend = {s: udim.legend[s].text() for s in udim.legend}
    coloured = cmds.ls("unlokUV_*_SG") or []
    check("the colour toggle colours meshes and fills the legend", coloured and
          any(t.split()[-1] != "0" for t in legend.values()), "%s | %s" % (coloured, legend))
    udim._select_state("handsoff")
    check("clicking a legend entry selects those meshes", cmds.ls(selection=True, long=True) == [rafter],
          str(cmds.ls(selection=True)))
    other = cmds.ls("woodBrown_C_rafter0002_GEP", long=True)[0]
    rows_before = udim.auto_tree.topLevelItemCount()
    cmds.select(other)
    udim.auto_uv(selected=True)
    pump()
    check("Auto UV Selected runs on just the selection and keeps the full list",
          "Auto UV in" in udim.status.text() and udim.auto_tree.topLevelItemCount() == rows_before and
          udim.states.get(other) in ("auto", "good", "keep", "problem"),
          "%s | state %s" % (udim.status.text()[:120], udim.states.get(other)))
    window.grab().save(os.path.join(OUT, "10b_uv_colours.png"))
    udim.colour_box.setChecked(False)
    pump()
    check("unticking puts the real materials back", not cmds.ls("unlokUV_*_SG"), str(cmds.ls("unlokUV_*_SG")))

    # --- inspector: click a red mesh, see why, fix it
    victim = cmds.ls("woodBrown_C_rafter0002_GEP", long=True)[0]
    asset = udim._asset()
    asset.update_tool_sets(add={"problem": [victim]})
    udim.refresh()
    cmds.select(victim, replace=True)
    udim.inspect_selection()
    pump()
    txt = udim.inspect_label.text()
    check("clicking a red mesh shows why it's red and what to do", "Why it" in txt and "Fix:" in txt and
          not udim.inspect_row.isHidden(), txt[:300])
    hit = udim._auto_items.get(victim)
    check("...and highlights its row in the list", hit is not None and hit[0].isSelected())
    udim.problems_only.setChecked(True)
    pump()
    shown = [udim.auto_tree.topLevelItem(i).data(0, ns["QtCore"].Qt.UserRole)
             for i in range(udim.auto_tree.topLevelItemCount()) if not udim.auto_tree.topLevelItem(i).isHidden()]
    check("Show only problems lists just the red meshes", victim in shown and
          all(udim.states.get(m) == "problem" for m in shown), str([m.split("|")[-1] for m in shown]))
    udim.problems_only.setChecked(False)
    udim.inspector_fix()
    pump()
    check("Fix clears an out-of-date flag (the UVs score fine)", udim.states.get(victim) != "problem",
          udim.states.get(victim))
    window.grab().save(os.path.join(OUT, "10c_inspector.png"))

    # --- Plan with a mesh that still has junk UVs: it's left out, and the panel says so
    junk = cmds.polyPlane(w=2, h=2, sx=40, sy=40, name="woodGreen_C_junk0001_GEP")[0]
    cmds.polyForceUV(junk, unitize=True)
    cmds.polyMapCut(junk + ".e[*]", constructionHistory=False)
    junk = cmds.ls(cmds.parent(junk, "|house_GRP|westWing_GRP")[0], long=True)[0]
    udim.scan()
    udim.lay_mode.setValue("Fixed density")  # these checks are about a set density
    udim._update_layout_enabled()
    udim.lay_density.setValue(2048.0)
    udim.lay_map.setValue("1024")
    udim.plan_layout()
    pump()
    check("Plan leaves out meshes that aren't ready, and says so",
          junk in (udim._collected or {}).get("not_ready", {}) and "Left out" in udim.layout_summary.text() and
          "aren't ready" in udim.next_banner.text.text(),
          "%s | %s" % (udim.layout_summary.text()[-160:], udim.next_banner.text.text()[:100]))
    cmds.delete(junk)
    udim.refresh()
    udim.plan_layout()
    pump()
    check("Plan fills the UDIM map", len(udim.udim_map.shells) > 0 and udim.udim_map.tiles,
          "%d shells, tiles %s | %s" % (len(udim.udim_map.shells), sorted(udim.udim_map.tiles),
                                        udim.layout_summary.text()[:160]))
    udim.lay_mode.setValue("Fit sections to rows")
    udim.plan_layout()
    check("Fit sections to rows puts every section on its own row", "Every section fits on its own row"
          in udim.layout_summary.text(), udim.layout_summary.text()[:200])
    udim.lay_mode.setValue("Fixed density")
    udim.plan_layout()
    check("UDIM map shows the hands-off piece", len(udim.udim_map.fixed) > 0 and
          "hands-off" in udim.layout_summary.text(), udim.layout_summary.text()[-200:])
    check("Step 7 shows only the options people change", not hasattr(udim, "lay_handsoff") and
          not hasattr(udim, "lay_rows") and not hasattr(udim, "lay_squares") and udim.labels_btn.isHidden())
    udim.plan_layout()
    pump()
    udim.lay_density.spin.setValue(1024.0)  # like a user edit: emits, so it live re-plans from cached shells
    deadline = time.time() + 5.0
    while time.time() < deadline and not (udim._worker is None and "1024 px/m" in udim.layout_summary.text()):
        pump(1)
    check("changing a setting re-plans live (in the background)", "1024 px/m" in udim.layout_summary.text(),
          udim.layout_summary.text()[:120])

    # --- Find Largest Shell and Fit largest shell
    top = udim.find_largest_shell()
    sel = cmds.ls(selection=True, long=True, flatten=True) or []
    check("Find Largest Shell selects the largest shell's faces and lists the next ones",
          top and sel and all(".f[" in s and s.startswith(top[0]["mesh"] + ".") for s in sel) and
          "Largest shell" in udim.layout_summary.text(),
          "%d faces | %s" % (len(sel), udim.layout_summary.text()[:120]))
    udim.lay_mode.setValue(ns["FIT_LARGEST"])
    udim.plan_layout()
    pump()
    check("Fit largest shell lays everything out at the largest shell's density",
          udim._plan and abs(udim._plan["density"] - top[0]["density"]) < 0.01 * top[0]["density"] and
          "Set by the largest shell" in udim.layout_summary.text(), udim.layout_summary.text()[:160])

    # --- background Plan, the UV Viewer and labels in Maya's UV Editor
    udim.lay_mode.setValue("Fit sections to rows")
    udim.plan_live()
    started = udim._worker is not None
    deadline = time.time() + 30.0
    while udim._worker is not None and time.time() < deadline:
        pump(1)
    check("Plan runs in the background and lands in the panel",
          started and udim._worker is None and "Every section fits on its own row" in udim.layout_summary.text(),
          udim.layout_summary.text()[:160])
    udim.open_viewer()
    pump()
    viewer = udim.viewer
    check("UV Viewer shows the plan", viewer.isVisible() and len(viewer.items) > 0 and viewer.tiles and viewer.rows,
          "%d items, tiles %s, rows %s" % (len(viewer.items), sorted(viewer.tiles), viewer.rows))
    viewer.grab().save(os.path.join(OUT, "11b_uv_viewer_plan.png"))
    viewer.mode.setValue("Texel density")
    viewer.canvas.update()
    pump()
    check("UV Viewer colours by texel density", viewer.colour_of(viewer.items[0]).name() != "#6a6a6a")
    viewer.grab().save(os.path.join(OUT, "11c_uv_viewer_density.png"))
    # --- drag a group onto another tile: it's pinned there and re-planned
    QtCore, QtGui = ns["QtCore"], ns["QtGui"]
    viewer.canvas.frame()
    pump()
    item = viewer.items[0]
    group = item["group"]
    target_tile = max(viewer.tiles) + 1 if (max(viewer.tiles) - 1001) % 10 < 9 else max(viewer.tiles) + 10
    cx = sum(a for a, _ in item["hull"]) / len(item["hull"])
    cy = sum(b for _, b in item["hull"]) / len(item["hull"])
    start = viewer.canvas.to_px(cx, cy).toPoint()
    tu, tv = (target_tile - 1001) % 10, (target_tile - 1001) // 10
    end = viewer.canvas.to_px(tu + 0.5, tv + 0.5).toPoint()

    def mouse(kind, pos, buttons):
        return QtGui.QMouseEvent(kind, QtCore.QPointF(pos), QtCore.Qt.LeftButton, buttons, QtCore.Qt.NoModifier)

    viewer.canvas.mousePressEvent(mouse(QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton))
    mid = QtCore.QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2)
    viewer.canvas.mouseMoveEvent(mouse(QtCore.QEvent.MouseMove, mid, QtCore.Qt.LeftButton))
    viewer.canvas.mouseMoveEvent(mouse(QtCore.QEvent.MouseMove, end, QtCore.Qt.LeftButton))
    viewer.grab().save(os.path.join(OUT, "11e_uv_viewer_drag.png"))
    viewer.canvas.mouseReleaseEvent(mouse(QtCore.QEvent.MouseButtonRelease, end, QtCore.Qt.NoButton))
    deadline = time.time() + 30.0
    while udim._worker is not None and time.time() < deadline:
        pump(1)
    pump()
    pinned = ns["group_pin"](cmds.ls(cmds.ls(group, uuid=True)[0])[0]) if cmds.objExists(group) else []
    st = [v for k, v in (udim._plan or {}).get("stats", {}).items() if k == group or v.get("uuid") ==
          (cmds.ls(group, uuid=True) or [None])[0]]
    check("dragging a group onto a tile in the UV Viewer pins it there and re-plans",
          pinned == [target_tile] and st and target_tile in st[0]["tiles"],
          "pin %s, tiles %s, target %d" % (pinned, st and st[0]["tiles"], target_tile))
    viewer.grab().save(os.path.join(OUT, "11f_uv_viewer_dropped.png"))
    udim.pin_groups([group], [])
    deadline = time.time() + 30.0
    while udim._worker is not None and time.time() < deadline:
        pump(1)

    # --- Quick Plan: squares from 3D area, drag one to pin its group, then Plan
    check("the in-panel UDIM map is hidden (the UV Viewer button shows the layout)", udim.udim_map.isHidden())
    check("Plan packs each material group into its own square(s)", (udim._plan or {}).get("squares") and
          viewer.blocks, "%d squares" % len(viewer.blocks))
    viewer.close()
    pump()
    t0 = time.time()
    udim.quick_plan()
    pump()
    secs = time.time() - t0
    blocks = [it for it in viewer.items if it.get("block")]
    check("Quick Plan opens the UV Viewer: a row per section, materials listed, estimated squares",
          viewer.isVisible() and blocks and (udim._plan or {}).get("quick") and secs < 3.0 and
          all(chr(10) in t for t in viewer.rows.values()),
          "%d squares, %.2fs | %s" % (len(blocks), secs, udim.layout_summary.text()[:120]))
    viewer.canvas.frame()
    pump()
    viewer.grab().save(os.path.join(OUT, "11g_quick_plan.png"))
    fixed = [it for it in viewer.items if it.get("fixed")]
    clash = [(it["key"], f["key"]) for it in blocks for f in fixed
             if it["box"][0] < f["box"][2] and f["box"][0] < it["box"][2] and
             it["box"][1] < f["box"][3] and f["box"][1] < it["box"][3]]
    check("Quick Plan shows hands-off pieces where they are, squares around them", fixed and not clash,
          "%d hands-off, overlaps %s" % (len(fixed), clash[:3]))
    # click a tile: its group's meshes are selected
    b = blocks[0]["box"]
    at = viewer.canvas.to_px((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0).toPoint()
    viewer.canvas.mousePressEvent(mouse(QtCore.QEvent.MouseButtonPress, at, QtCore.Qt.LeftButton))
    viewer.canvas.mouseReleaseEvent(mouse(QtCore.QEvent.MouseButtonRelease, at, QtCore.Qt.NoButton))
    want = set(ns["expand_members"](blocks[0]["group"])[0])
    got = set(cmds.ls(selection=True, long=True, objectsOnly=True) or [])
    check("clicking a Quick Plan square selects its group's meshes", want and want <= got,
          "%d of %d selected" % (len(want & got), len(want)))
    # drag the bottom section's name to the top row: the sections reorder
    rows = sorted(viewer.row_sections)
    first, last = viewer.row_sections[rows[0]], viewer.row_sections[rows[-1]]
    band_x = viewer.canvas.origin.x() - viewer.canvas.band_width() / 2.0
    p0 = QtCore.QPoint(int(band_x), int(viewer.canvas.to_px(0, rows[0] + 0.5).y()))
    p1 = QtCore.QPoint(int(band_x), int(viewer.canvas.to_px(0, rows[-1] + 0.5).y()))
    viewer.canvas.mousePressEvent(mouse(QtCore.QEvent.MouseButtonPress, p0, QtCore.Qt.LeftButton))
    viewer.canvas.mouseMoveEvent(mouse(QtCore.QEvent.MouseMove, p1, QtCore.Qt.LeftButton))
    viewer.grab().save(os.path.join(OUT, "11g2_quick_plan_reorder.png"))
    viewer.canvas.mouseReleaseEvent(mouse(QtCore.QEvent.MouseButtonRelease, p1, QtCore.Qt.NoButton))
    pump()
    secs_now = udim._asset().sections()
    check("dragging a section's name to the top row moves that section last (top)",
          secs_now and secs_now[-1] == first and (udim._plan or {}).get("quick") and
          viewer.row_sections.get(max(viewer.row_sections)) == first,
          "order %s" % [ns["short_name"](s) for s in secs_now])
    cmds.undo()  # the reorder
    udim.refresh()
    udim.quick_plan()
    pump()
    check("...and one Ctrl+Z puts it back", udim._asset().sections()[0] == first and last in udim._asset().sections())
    blocks = [it for it in viewer.items if it.get("block")]
    item = blocks[0]
    group = item["group"]
    target_tile = max(viewer.tiles) + 1 if (max(viewer.tiles) - 1001) % 10 < 9 else max(viewer.tiles) + 10
    b = item["box"]
    start = viewer.canvas.to_px((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0).toPoint()
    tu, tv = (target_tile - 1001) % 10, (target_tile - 1001) // 10
    end = viewer.canvas.to_px(tu + 0.5, tv + 0.5).toPoint()
    viewer.canvas.mousePressEvent(mouse(QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton))
    mid = QtCore.QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2)
    viewer.canvas.mouseMoveEvent(mouse(QtCore.QEvent.MouseMove, mid, QtCore.Qt.LeftButton))
    viewer.canvas.mouseMoveEvent(mouse(QtCore.QEvent.MouseMove, end, QtCore.Qt.LeftButton))
    viewer.canvas.mouseReleaseEvent(mouse(QtCore.QEvent.MouseButtonRelease, end, QtCore.Qt.NoButton))
    pump()
    uid = (cmds.ls(group, uuid=True) or [None])[0]
    node = cmds.ls(uid)[0] if uid else group
    st = [v for k, v in (udim._plan or {}).get("stats", {}).items() if v.get("uuid") == uid]
    check("dragging a Quick Plan square pins its group there and stays a Quick Plan",
          ns["group_pin"](node)[:1] == [target_tile] and (udim._plan or {}).get("quick") and st and
          target_tile in st[0]["tiles"], "pin %s, tiles %s" % (ns["group_pin"](node), st and st[0]["tiles"]))
    viewer.grab().save(os.path.join(OUT, "11h_quick_plan_dragged.png"))
    udim.plan_live()
    deadline = time.time() + 30.0
    while udim._worker is not None and time.time() < deadline:
        pump(1)
    pump()
    st = [v for k, v in (udim._plan or {}).get("stats", {}).items() if v.get("uuid") == uid]
    check("Plan after a Quick Plan packs the real shells, keeping the pin",
          udim._plan and not udim._plan.get("quick") and udim._plan["placements"] and st and
          set(st[0]["tiles"]) <= set(ns["group_pin"](node)) and target_tile in st[0]["tiles"],
          "tiles %s, pin %s | %s" % (st and st[0]["tiles"], ns["group_pin"](node),
                                                        udim.layout_summary.text()[:120]))
    viewer.grab().save(os.path.join(OUT, "11i_plan_after_quick.png"))
    udim.pin_groups([cmds.ls(uid)[0]], [])
    deadline = time.time() + 30.0
    while udim._worker is not None and time.time() < deadline:
        pump(1)

    viewer.show_scene()
    pump()
    check("UV Viewer reads the scene's UVs", viewer.source == "scene" and len(viewer.items) > 0,
          "%d items" % len(viewer.items))
    viewer.mode.setValue("UV status")
    pump()
    viewer.grab().save(os.path.join(OUT, "11d_uv_viewer_scene.png"))
    viewer.close()
    udim.labels_btn.setChecked(True)
    pump()
    label_mesh = ns["UV_LABEL_MESH"]
    check("Labels in UV Editor adds the helper mesh", cmds.objExists(label_mesh) and
          label_mesh in (cmds.ls(selection=True) or []), udim.status.text())
    udim.labels_btn.setChecked(False)
    pump()
    check("...and unticking removes it", not cmds.objExists(label_mesh))
    for w in QtWidgets.QApplication.topLevelWidgets():  # the UV Editor it opened
        if w.isVisible() and "UV Editor" in (w.windowTitle() or ""):
            w.close()
    # --- shells too big for a UDIM: the plan says so, Apply's split cuts them
    # at their 50% line and plans again (its Ctrl+Z: tests/test_squares.py)
    udim.lay_mode.setValue("Fixed density")
    old_density = udim.lay_density.value()
    udim.lay_density.setValue(top[0]["density"] * 1.5)
    udim.plan_layout()
    said = "bigger than a UDIM" in udim.layout_summary.text()
    n_before = sum(len(g["shells"]) for g in udim._collected["groups"])
    n_split = udim._split_big_shells()
    n_after = sum(len(g["shells"]) for g in udim._collected["groups"])
    check("a shell too big for a UDIM: the plan says so, and Apply's split cuts it and plans again",
          said and n_split and n_after - n_before >= n_split,
          "said %s, split %s, shells %d -> %d | %s" % (said, n_split, n_before, n_after,
                                                      udim.layout_summary.text()[:160]))
    udim.lay_density.setValue(old_density)
    udim._collected, udim._plan = None, None
    udim.plan_layout()
    first = udim.tree.topLevelItem(0).child(0)
    first.setCheckState(udim.COL_LOCK, ns["QtCore"].Qt.Checked)
    pump()
    udim.apply_layout()
    pump()
    check("Apply Layout writes it and the step completes", udim.step_layout.state == "done" and
          "Laid out" in udim.status.text(), udim.status.text())
    check("Apply leaves the hands-off rafter's UVs alone", cmds.polyEditUV(rafter + ".map[*]", q=True) == rafter_uvs)
    first_mat = udim.tree.topLevelItem(0).child(1) or udim.tree.topLevelItem(0).child(0)
    udim.tree.clearSelection()
    first_mat.setSelected(True)
    udim.relayout_selected()
    pump()
    check("Re-layout Selected lays out just the highlighted group", "Re-laid out 1 group" in udim.status.text(),
          udim.status.text()[:200])
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

    # --- save, close, reopen: the panel picks up where it was
    rows_before = udim.auto_tree.topLevelItemCount()
    states = lambda: [c.state for c in (udim.step_prep, udim.step_auto, udim.step_layout,  # noqa: E731
                                        udim.step_check)]
    states_before = states()
    udim.lay_padding.setValue(12)
    udim.plan_layout(quiet=True)
    udim._save_session()
    scene = os.path.join(OUT, "udim_resume.ma")
    cmds.file(rename=scene)
    cmds.file(save=True, type="mayaAscii", force=True)
    cmds.file(new=True, force=True)
    import maya.utils
    maya.utils.processIdleEvents()  # scriptJob events wait for idle while a script runs
    pump(10)
    check("a new scene clears the panel", udim._asset() is None and udim.auto_tree.topLevelItemCount() == 0,
          udim.next_banner.text.text())
    udim.lay_padding.setValue(4)
    cmds.file(scene, open=True, force=True)
    maya.utils.processIdleEvents()
    pump(20)
    check("reopening the scene picks up where it left off", udim._asset() is not None and
          udim.auto_tree.topLevelItemCount() == rows_before and states() == states_before and
          not udim.resume_label.isHidden() and udim.lay_padding.value() == 12,
          "%d rows (was %d), steps %s (were %s), padding %d | %s" % (
              udim.auto_tree.topLevelItemCount(), rows_before, states(), states_before, udim.lay_padding.value(),
              udim.resume_label.text()[:120]))
    scroll = udim.step_root.parentWidget().parentWidget().parentWidget()
    if hasattr(scroll, "ensureWidgetVisible"):
        scroll.ensureWidgetVisible(udim.step_root)
    pump()
    window.grab().save(os.path.join(OUT, "14b_resumed.png"))
    udim.start_fresh()
    pump()
    check("Start Fresh forgets the saved progress", udim.resume_label.isHidden() and
          udim.auto_result is None and udim.step_layout.state != "done", udim.status.text())

    # --- Do It All on a fresh asset: Auto UV, layout and validation in one click
    cmds.file(new=True, force=True)
    maya.utils.processIdleEvents()
    pump(5)
    window.tabs.setCurrentIndex([window.tabs.tabText(i) for i in range(window.tabs.count())].index("UV"))
    shed = cmds.group(empty=True, name="shed_GRP")
    for wing in ("front_GRP", "back_GRP"):
        grp = cmds.group(empty=True, name=wing, parent=shed)
        for i, nm in enumerate(("woodBrown_C_plank%04d_GEP", "brickRed_C_wall%04d_GEP")):
            c = cmds.polyCube(w=2, h=1, d=0.2, sx=4, name=nm % (i + 1))[0]
            if i == 1:
                cmds.polyMapDel(c + ".f[*]", constructionHistory=False)  # no UVs: Auto UV's job
            cmds.parent(c, grp)
    cmds.select(shed)
    udim.pick_root()
    udim.from_groups.setValue(True)
    udim.lay_density.setValue(256.0)
    out = udim.do_it_all(confirm=False)
    pump()
    check("Do It All runs Auto UV, layout and validation in one go",
          out and udim.layout_applied and udim.validation and "Do It All finished" in udim.status.text() and
          udim.step_layout.state == "done" and len(udim._asset().sections()) == 2,
          udim.status.text()[:300])
    window.grab().save(os.path.join(OUT, "14c_do_it_all.png"))

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
