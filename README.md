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
strands rebuilds in roughly 0.3 s.

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

### UV > Smart UDIM (in progress)

Organises an asset for UDIM layout by **section** (one band of UDIM rows,
e.g. west wing / east wing) and **material group**, at consistent texel
density. The actual layout is still being built; see
[docs/smart-udim-plan.md](docs/smart-udim-plan.md). Available now:

1. **Pick the root:** select the asset's top group (e.g. `house_GRP`) and
   press **Use Selected Group**.
2. **Scan:** sorts every mesh into sections and material groups.
   - **Material groups:** come from the UnlokRenamer naming
     (`woodGreen_C_beam0001_GEP` goes into `woodGreen`). Meshes whose names
     don't follow it fall back to their assigned Maya material, per face.
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

Every Smart UDIM action is a single Ctrl+Z.

## How it stays fast

The live preview is a single `instancer` node whose point data is written
directly from Python. There is no MASH network and no per-item nodes, so even
tens of thousands of items update in milliseconds. Real geometry is only
created when you bake.

## Development

- `UnlokToolbox.py`: the whole toolbox (the file you paste).
- `tests/test_toolbox.py`: headless engine and bake tests:
  ```bash
  "C:/Program Files/Autodesk/Maya2024/bin/mayapy.exe" tests/test_toolbox.py
  ```
- `tests/test_smart_udim.py`: headless Smart UDIM tests (naming, sets, scan,
  assignment, pre-process, undo):
  ```bash
  "C:/Program Files/Autodesk/Maya2024/bin/mayapy.exe" tests/test_smart_udim.py
  ```
- `tests/gui_smoke.py`: runs inside a real Maya session (opens the window,
  draws strokes through the viewport, saves screenshots to `tests/_out`).
  Set `UNLOK_TEST_DIR` to the `tests` folder (and `UNLOK_TEST_QUIT=1` to close
  Maya afterwards), then launch `maya.exe -script tests/run_gui_smoke.mel`.
- `tests/gui_draw_bench.py`: measures how responsive path drawing is (time
  per mouse move in a busy scene). Launch it the same way with
  `tests/run_gui_draw_bench.mel`.
