# Unlok Maya Toolbox

Fast, stable modeling helpers for Maya in one tabbed window. The whole toolbox
is a **single self-contained Python file**: paste it into the Script Editor and
run it. No install, no extra folders, no third-party packages, so it works in
locked-down / secure Maya setups.

Built for **Maya 2023** (Python 3.9, PySide2); also runs on 2024 and 2025.

## Run it

1. Open `UnlokToolbox.py`, select all, copy.
2. In Maya: **Windows > General Editors > Script Editor**, open a **Python** tab, paste.
3. Run it (Ctrl+Enter, or the run button).

Running it again just replaces the window. To make a shelf button, select the
pasted code in the Script Editor and middle-mouse-drag it onto a shelf.

## Tools

### Modeling > Path Scatter

Draw a path on any surface and lay objects along it: neat arrays,
roof shingles, fences, kerbs, or randomly scattered rocks. It's a light,
crash-free replacement for the MASH path workflow.

**Basic flow**

1. Pick a source: **Cube / Cylinder / Plane / Sphere** (sized in the tool), or
   select your own objects and press **Use Selected Meshes**. Picking several
   gives you random variants.
2. Press **Draw Path** and drag across a mesh. The stroke sticks to whatever
   you start drawing on. With nothing under the cursor it draws on the grid.
   - **Shift**: straight line (still follows the surface)
   - **Ctrl**: add another path to the same scatter
   - **Q**: finish drawing
   Or select an existing curve, or **polygon edges** (e.g. a roof eave), and
   press **Use Selection as Path**.
3. Tweak the settings. Everything updates live.
4. **Bake** as Instances, Copies or one Combined Mesh.

**Settings at a glance**

| Section | What it does |
| --- | --- |
| Source | Preset type and size (Length runs along the path), which axis of your mesh faces forward / up, and the pivot (Bottom = rests on the surface). |
| Distribution | *Fit to Size* packs items end to end using their real length plus *Gap*. Also *Spacing* or exact *Count*, and start/end trims. |
| Rows (grid) | Repeat the line side by side. *Stagger* 0.5 gives a brick/shingle offset, *Row lift* raises each row so they overlap, and negative *Row spacing* flips the side. |
| Orientation | Follow the path, align to the surface normal or world up, snap to the surface, plus rotation offsets (e.g. *Rotate Z* to tilt shingles). |
| Scale | Overall and per-axis scale (handy for your own meshes). |
| Randomness | Seed / Re-roll, scale range, per-axis jitter, random rotation, position jitter, skip %, random or cycled variants. |
| Drawing & Output | Stroke smoothing, a max-items safety cap, bounding-box preview for heavy meshes. |

**Recipes:** the *Recipe* dropdown at the top of Source sets everything up
for a common job in one click: Neat Array, Roof Shingles, Messy Thatch,
Rocks / Debris or Fence Posts. Then tweak from there.

**Shingles:** pick the *Roof Shingles* recipe and draw along the eave. If the
rows go downhill instead of up, flip the sign of *Row spacing*. Change *Seed*
or tweak the jitter until it looks hand-laid.

**Thatch / straw roof:** pick *Messy Thatch* and draw along each eave (Ctrl
adds the second side). Each strand is a thin cube whose *Width* is the strand
length, so strands run down the slope. Twelve overlapping rows with *Row lift*
build up the layers, while random tilt, fan (*Rotate Y +/-*), stretch, side
jitter and *Skip %* make it messy. Want it shaggier? Raise *Rotate X +/-*
and *Offset side +/-*. Thicker? Lower *Spacing*. A full roof of about 5,500
strands rebuilds in about 0.2 s, and rotation tweaks take about 0.06 s.

**Drawing tips:** a stroke follows whatever mesh is under the cursor, so you
can cross several pieces. If you have meshes selected when you press Draw
Path, strokes stick to those. Glancing off an edge (onto a wall under the
eave) is ignored automatically.

**Good to know**

- Select any part of a scatter in the viewport or Outliner and the panel
  loads it back, settings and all. Tick *Keep live system* when baking if
  you want to come back to it later.
- Editing your source mesh, moving curve CVs or changing the surface
  updates the scatter live.
- Your own meshes are used in their object space. Where they sit in the
  scene doesn't matter, and the tool never moves or changes them.
- Live tweaks don't fill your undo queue. **Bake cannot be undone with
  Ctrl+Z**: delete the baked group instead, or tick *Keep live system* first.
- **Bake modes for big counts:**
  - **Combined Mesh** is the fastest (about 0.4 s for 6,000 pieces). It
    keeps UVs, hard edges and per-face materials.
  - **Copies** is quick too.
  - **Instances** gets slow beyond a couple of thousand, because Maya itself
    slows down per instance. The tool warns you and offers the faster modes.
- Live scatters rebuild their preview when you open a scene with the toolbox
  open, or when you open the toolbox.

### Modeling > Bevel Resolver

Cleans up after hard-surface bevels for SubD. A bevel with **Chamfer off**
keeps edges sharp when smoothed, but wherever a bevelled edge chain *ends* it
leaves 5-, 6- and 7-sided faces: the chamfer corner spills an extra vertex
into every face around it. Bevel Resolver turns those into quads in one click.

![Before and after: n-gons at the bevel ends (left), resolved quads (right)](docs/images/bevel-resolver.png)

1. Select one or more meshes (the whole mesh is checked), or some faces,
   edges or vertices (only the n-gons there are resolved).
2. Optional: **Select N-gons** shows what it will work on, changing nothing.
3. Press **Resolve**. One Ctrl+Z undoes everything.

**What it does**

- **Chamfers side by side merge:** when two chamfer tips land on the same
  face, they're joined straight across, so the bevels run into each other.
- **A lone chamfer gets one diagonal** from its corner up to a vertex on the
  next loop (two cuts meeting at one vertex where two chamfers share it).
  The pole that leaves sits on the flat area, not on the bevel.
- **Support loops carry across:** a face where loops end on opposite sides
  in matching numbers (the top of a boss with bevelled sides) gets the loops
  continued straight through, as a grid, with no poles.
- **Odd-sided faces are paired:** a 5- or 7-sided face can't become quads on
  its own. It's paired with the odd face next to it (the shared edge gets one
  new vertex), or a short edge loop runs between the two through flat quads.
  New vertices go on flat edges, never on a hard corner.

**Options:** *Faces* (bevel n-gons only, or every n-gon), *Strip ratio* (how
thin a quad must be to count as a bevel strip), *Max loop* (how far a pairing
loop may run) and *Loops may end on an open border*.

**Left alone and listed** (click a row to select them): faces with holes,
faces over 16 sides, zero-area faces (Maya's bevel makes these where two
recesses touch), odd faces with no partner nearby, and n-gons with no clean
split. The original vertices never move: it only adds edges and vertices.

**Speed:** about 0.3 s for a façade with 24 windows (200 n-gons), 1 s for 50
windows. A 200-window wall (1,600 n-gons) takes about 10 s with the bevel
still in its history, because every Maya poly command re-evaluates the
history. Delete history first to halve that.

### Modeling > Log Noise

Turns cylinders into natural-looking logs for shack supports, posts and
fences.

1. **Select** cylinders with some height and axis subdivisions (e.g.
   24 x 20). Selecting vertices instead, soft selection included, roughens
   just that part of a log.
2. **Apply to Selected:** each log gets its own random seed. One Ctrl+Z
   undoes it.
3. **Shape:** the sliders edit the selected logs live, like the Channel Box
   on several nodes.
   - Bumps, Bump size and Grain shape the surface; Grain stretches the bumps
     along the log like wood grain.
   - Bulge, Bend and Taper shape the log as a whole. The ends stay put when
     it bends.
   - Detail and Axis are under Advanced.
   - Randomize Seeds gives each log a new seed.
   - Everything is relative to the log's own radius and length, so it works
     at any scale.
4. **Finish:**
   - **Bake** keeps the shape and forgets the settings.
   - **Reset** puts the cylinder back.
   - **Select Logs With Noise** finds them all.

No plugin and no extra nodes: each mesh stores its original shape and
settings in hidden attributes, so scenes open anywhere and you can come back
and re-tweak later. About 0.13 s per update for a 3,900-vertex log.

### UV > Smart UDIM (in progress)

Organises an asset for UDIM layout by **section** (one band of UDIM rows,
e.g. west wing / east wing) and **material group**, at consistent texel
density. The actual layout is still being built; see
[docs/smart-udim-plan.md](docs/smart-udim-plan.md). Available now:

1. **Pick the root:** select the asset's top group (e.g. `house_GRP`) and
   press **Use Selected Group**.
   - **Your progress is saved with the scene.** Save the scene, reopen it
     later (or reopen the toolbox), and Smart UDIM picks up where you left
     off: the pre-process report, analysis and Auto UV results, the
     validation report and all your settings.
   - Groups, Keep UVs / Hands off marks and locks come straight from the
     scene's sets, as before.
   - **More than one setup in a scene:** the most recently used one opens;
     switch between them under **Setups**.
   - **Start Fresh** forgets the saved reports and results. It leaves
     groups, marks, locks and UVs alone.
2. **Scan:** sorts every mesh into sections and material groups.
   - **Section from Group** (step 3): select one or more groups in the
     Outliner and press it. Each becomes a section named after the group
     (`westWing_GRP` -> `westWing`; with one group you can change the name)
     holding every mesh inside, each in its own material group. The section
     stays linked to the group, so meshes you add there later go into it on
     the next Scan.
   - **Move to Section:** highlight a section, select meshes, faces or
     groups in the scene, press it.
   - **Delete Section:** its meshes go back to the section of the group
     they're in (or the first section).
   - **Move to Group / New Material Group** do the same for material groups
     inside a section. Every button accepts groups as well as meshes,
     right-clicking the list offers the same actions, and empty material
     groups are tidied away. Each action is one Ctrl+Z.
   - **Material groups:** come from the UnlokRenamer naming
     (`woodGreen_C_beam0001_GEP` goes into `woodGreen`). A variant letter
     after the colour makes its own group (`glassClearA`, `glassClearB`).
     Meshes whose names don't follow it fall back to their assigned Maya
     material, per face.
   - **Sections:** tick *New sections from top-level groups* to make each
     child group (e.g. `westWing_GRP`) its own section.
   - **Re-scanning:** only sorts new meshes; existing groups are kept.
3. **Edit:** use the tree, or the sets themselves.
   - **Groups are plain Maya sets:** `house_smartUDIM_SET` contains
     `westWing_UDS`, which contains `td100_woodGreen`. Rename a set to
     `td150_woodGreen` to give it 150% texel density, or add `_stack` to
     stack identical shells. You can make sets by hand too.
   - **In the tree:** double-click **TD %** to edit it, tick **Stack**,
     **Assign Selection** to move meshes or faces between groups, **New
     Group / New Section**, and **Move Up / Down** to set the section order.
4. **Naming issues:** lists meshes whose names break the convention, so you
   can fix them in UnlokRenamer and re-scan.
5. **Pre-process:**
   - **Fixes:** lamina faces, non-manifold geometry and zero-area faces.
   - **Warns:** about n-gons (they're left alone) and flipped UV faces.
   - **Lists for skipping:** meshes with missing UVs, faces without UVs, and
     instanced meshes.

6. **Auto UV**: for assets that are modelled, named and grouped but don't
   have good UVs yet. It gives you an organised, usable base to polish from;
   it doesn't aim for perfect UVs.
   - **UV status colours** (the strip at the top of the panel): tick
     *Colour meshes by UV status* to see where you are in the viewport.
     - **Yellow:** needs UVs.
     - **Red:** a problem, for example Auto UV failed, or the mesh is
       instanced.
     - **Greens:** Good UVs, Keep UVs (your marks) and Auto UV'd.
     - **Light blue:** laid out by Smart Layout.
     - **Blue:** Hands off.

     Meshes change colour live as Auto UV works through them. Each legend
     entry shows a count; click it to select those meshes (e.g. select every
     Good UVs mesh and mark it Keep UVs). The colours are temporary preview
     materials. Your real shading is stored on each mesh, Scan keeps reading
     it, and unticking puts it back exactly (per face too).
   - **Tracking sets:** Auto UV records what it unwrapped in
     `<asset>_uvAuto_SET` and what needs a human in `<asset>_uvProblem_SET`.
     Smart Layout records what it placed in `<asset>_uvLaidOut_SET`. They
     stay separate from your own Keep UVs / Hands off sets, so you can
     always tell your hand-laid work from Auto UV's.
   - **Auto UV Selected:** only the selected meshes or groups, so you can
     work through an asset bit by bit. Packing covers just the material
     groups they're in, around their finished members; Hands off meshes are
     never moved.
   - **Check UVs** (was Analyse) scores every mesh's UVs from 0 (none or garbage) to 1
     (clean) and lists them worst first. A face counts as bad if it has no
     UVs, is collapsed, folded or overlapping, or is stretched more than 4x
     compared with the rest of its own shell. Rectangulated or straightened
     shells and shells at different densities aren't penalised.
   - **Auto UV** works through these steps:
     1. backs up the current UVs into `map1_backup` (only if that set doesn't
        exist yet, so re-runs keep your originals)
     2. cleans bad geometry
     3. re-unwraps every mesh scoring below *Keep above* (0.85): normal-based
        projection, sew soft edges, cut hard edges and edges sharper than
        *Seam angle* as seams, Unfold3D auto-seams for closed shapes, relax,
        then extra cuts where shells are still stretched
     4. packs each material group into its own UDIM tile, at even density
        and as big as fits, with sections on their own rows and each
        material in the same column for every section. This uses the
        toolbox's own packer: 1.7 s instead of 46 s with Unfold3D's
        layout on a 141-mesh building, and fuller tiles (77% vs 72%).
   - **Progress:** Maya's progress bar at the bottom of the window, and the
     Auto UV step itself, show each stage, the mesh or batch it's on, a
     percentage and the time left. Press **Esc** to stop at the next mesh;
     one Ctrl+Z then undoes what was done. A long pause only happens inside
     one Unfold3D call on a big mesh, and the bar names it first.
   - **Restore Backup** copies the backup set back into `map1` for the
     selected meshes, or for all of them if nothing is selected.
   - **Meshes you've already UV'd:** select them and press one of these
     buttons (or double-click the **Status** column to cycle). The marks
     live in two sets under the asset's root set, `<asset>_uvKeep_SET` and
     `<asset>_uvHandsOff_SET`, so you can also check or edit them in the
     Outliner.
     - **Keep UVs:** UV'd but not laid out. They're never re-unwrapped, but
       still sorted into groups, scaled to texel density and packed with
       everything else.
     - **Hands off:** finished and already in their UDIM. Auto UV and the
       layout never touch them (no unwrap, no backup copy, no moving), and
       Auto UV's packing starts above their tiles. Validation still checks
       them for overlaps, tile crossings and padding, but not for density.
     - **Auto:** back to normal, where the score decides.
   - About 7 s for a 47-mesh test building that includes a 19,000-face dome.
     The whole run is one Ctrl+Z.

7. **Smart layout**: the even-density UDIM layout.
   - Set *Density px/m* and *Map size*, then press **Plan**. The UDIM Map
     previews every shell coloured by material: hover for density, coverage
     and tiles, click to select a group, and locked tiles show hatched.
     Changing a setting re-plans instantly. **Apply Layout** writes it.
   - **Density:** every shell is scaled to exactly the target texel density,
     times its group's and section's TD %. A group renamed `td150_...` gets
     1.5x.
   - **Orientation:**
     - *Main axis*: the longest direction along U, lying flat. Packs
       tightest.
     - *Upright*: world up along +V, so brick courses stay level and walls
       read upright. Flat pieces fall back to Main axis.
     - *Keep*: never rotate, for shells you've already straightened.

     Override it per group with the **Orient** column (double-click to
     cycle), or put `_up` / `_keep` / `_axis` in the set name.
   - **Packing:** a 2D packer places the biggest pieces first, each in the
     lowest free spot. Small pieces fill the gaps left under bigger ones, and
     in Main axis mode a piece may turn 90 degrees if that sits lower. On the
     test building this fills about 83% of each tile, up from 65% with the
     old row packer, and needs 7 tiles instead of 9.
     - A group stays in neighbouring tiles: it may top up the tiles the
       previous group ended on, then opens new ones.
     - No shell crosses a tile border, and each section starts on a new row.
     - The same scene always gives the same layout.
   - **Stacking:** in a group marked `_stack` (Stack column), identical
     pieces such as repeated windows or tiles share one spot, so they cost
     one footprint, not N. Validation knows these overlaps are intentional.
   - **Hands-off tiles:** what happens to the tiles your Hands off meshes
     sit in. Either way they stay exactly where they are, show hatched in
     the map, and their tiles are never handed out as fresh tiles.
     - *Pack around them* (default): other pieces fill the free space
       around them, keeping the padding. Their own group gets first go.
     - *Reserve their tiles:* nothing else goes in those tiles. The plan
       warns when a hands-off piece fills under half its tile.
   - **Fit to tiles:** finds the highest density that fits your tile budget.
   - **Auto-compensate:** lowers only a group whose piece is bigger than a
     tile, and tells you so.
   - **Locks (Lock column):** a locked group keeps its UVs and its tiles stay
     reserved, so you can re-lay everything else around finished work.
     Groups whose geometry changed since they were laid out get flagged.
     *Spare room %* leaves slack around every shell so small changes still
     fit.
   - **Coverage:** written into the set names (`c222` = 2.22 tiles).

8. **Check & hand off**:
   - **Validate** checks the finished layout. Click any finding to select
     its faces.
     - Problems: UVs outside the UDIM range, shells crossing tile borders,
       overlapping shells (intentional `_stack` groups excepted).
     - Warnings: flipped shells, shells under 2 px, density more than 10%
       off the layout's target (locked groups excepted), shells closer
       together than the padding.
   - **Save Sheet PNG** / **Copy Sheet** gives texture artists a picture of
     the whole layout:
     - every shell filled and outlined in its material's colour (the same
       colour in every section)
     - tile numbers and section names per row
     - a title line with the asset, density, map size and date
     - a legend with each group's section, tiles, TD % and coverage

     Copy Sheet is there for locked-down machines where saving files isn't
     allowed. Sheet size is Small, Medium or Large (256, 512 or 1024 px per
     tile).

Every Smart UDIM action is a single Ctrl+Z.

## How it stays fast

- **Preview:** the live preview is a single `instancer` node whose point data
  is written directly from Python. There is no MASH network and there are no
  per-item nodes.
- **Surface snapping:** uses Maya's accelerated mesh intersector, about 60x
  faster than the plain closest-point query.
- **Caching:** placement (path sampling and snapping) is cached, so rotation
  and scale tweaks don't redo it.
- **Bakes:** Combined Mesh is built in a single API call instead of
  `polyUnite`.

Measured on Maya 2024 (`tests/bench_scatter.py`):

| Case | Before | Now |
| --- | --- | --- |
| Thatch roof, ~5,900 strands, rebuild | 2.7 s | ~0.2 s |
| Same, after changing a rotation | 2.7 s | ~0.06 s |
| 20,000-item array, rebuild | 0.43 s | ~0.2-0.3 s |
| Bake 5,900 pieces to Combined Mesh | 17 s | ~0.4 s |

## Development

- `UnlokToolbox.py`: the whole toolbox (the file you paste).
- `tests/test_toolbox.py`: headless engine and bake tests:
  ```bash
  "C:/Program Files/Autodesk/Maya2024/bin/mayapy.exe" tests/test_toolbox.py
  ```
- `tests/test_auto_uv.py`: headless Auto UV tests on a messy generated
  building (`--snapshot DIR` also writes a UV snapshot).
- `tests/test_smart_layout.py`: headless smart layout tests (exact density,
  tile borders, fit-to-tiles, locks, change detection, undo).
- `tests/test_validation_handoff.py`: headless validation + hand-off sheet
  tests (breaks shells on purpose and checks each problem is found;
  `--sheet PATH` saves the rendered sheet).
- `tests/test_uv_states.py`: UV states, status colours (and the real
  shading coming back), tracking sets, Auto UV Selected.
- `tests/test_sections.py`: section from group, move to section, delete
  section, split faces, later Scans, undo.
- `tests/test_session.py`: Smart UDIM's saved progress survives a scene
  save and reopen, validation round-trips, deleted meshes drop out, and
  saving adds no undo step.
- `tests/test_auto_uv_progress.py`: Auto UV progress on a 141-mesh
  building (every stage reports, no unexplained silences, Esc cancels
  cleanly, one Ctrl+Z after a cancel).
- `tests/test_uv_status.py`: Keep UVs / Hands off marks through Auto UV,
  both hands-off tile modes and validation.
- `tests/test_layout_extras.py`: orientation modes, `_stack` stacking and
  2D packing (fill, padding, stable re-plans, speed).
- `tests/test_smart_udim.py`: headless Smart UDIM tests (naming, sets, scan,
  assignment, pre-process, undo):
  ```bash
  "C:/Program Files/Autodesk/Maya2024/bin/mayapy.exe" tests/test_smart_udim.py
  ```
- `tests/test_bevel_resolver.py`: headless Bevel Resolver tests (walls with
  window recesses, a boss, single edges, side-by-side chamfers, selection,
  reports, undo, speed):
  ```bash
  "C:/Program Files/Autodesk/Maya2024/bin/mayapy.exe" tests/test_bevel_resolver.py
  ```
- `tests/test_log_noise.py`: headless Log Noise tests. It checks shapes
  against the original deformer (`contrib/log_noise`), plus undo, live edits,
  masks, reset, bake, save/reopen and speed.
- `tests/gui_bevel_resolver.py`: drives the Bevel Resolver panel in a real
  Maya session and saves before / after screenshots (wireframe and smooth
  preview) to `tests/_out/bevel_resolver`. Launch it like the smoke test
  below, with `tests/run_gui_bevel_resolver.mel`.
- `tests/gui_smoke.py`: runs inside a real Maya session (opens the window,
  draws strokes through the viewport, saves screenshots to `tests/_out`).
  Set `UNLOK_TEST_DIR` to the `tests` folder (and `UNLOK_TEST_QUIT=1` to close
  Maya afterwards), then launch `maya.exe -script tests/run_gui_smoke.mel`.
- `tests/bench_scatter.py`: Path Scatter rebuild and bake timings
  (`--profile` prints the hot functions, `--quick` skips the slow
  Instances bake).
- `tests/gui_draw_bench.py`: measures how responsive path drawing is (time
  per mouse move in a busy scene). Launch it the same way with
  `tests/run_gui_draw_bench.mel`.
