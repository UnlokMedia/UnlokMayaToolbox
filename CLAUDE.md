# Unlok Maya Toolbox: notes for Claude

## Hard constraints
- **Single pasteable file.** Everything ships in `UnlokToolbox.py`. It must run
  by pasting into the Maya Script Editor in secure environments with no file
  or network access: no imports from sibling files, no pip packages, no
  numpy, no reading or writing files at runtime, no `userSetup`/module install.
- **Target Maya 2023** (Python 3.9, PySide2). Keep 3.9 syntax (no `match`,
  no `X | Y` types). PySide6 fallback import exists for 2025+.
- **Stability over features.** The user is replacing MASH because it lags
  and crashes. Every UI callback goes through `ui_safe`. Never touch the
  scene from inside Maya API callbacks (only queue a QTimer). Clean up
  script jobs and callbacks on close and on re-paste (`_registry()` in
  `__main__`).

## Architecture
- Tools are QWidget panels registered in `TOOL_REGISTRY` (category tab ->
  panel classes). Each panel needs `TOOL_NAME`, `TOOL_TIP` and `shutdown()`.
- Path Scatter: `PathScatterSystem` (scene state on a root node: settings as
  JSON, inputs via message attrs), `SurfacePathDrawer` (draggerContext;
  `press_at` / `drag_at` / `release` are scriptable), `PathScatterPanel` (UI).
- Live preview = one `instancer` node fed static arrays through OpenMaya 1
  `MFnArrayAttrsData` (OM2 has no equivalent). Creating real per-item DAG
  nodes is about 1 ms each, which is too slow for live updates. Only bake
  creates them.
- Live edits run inside `NoUndo` so slider drags don't flood the undo queue.
- Stroke preview must stay cheap per mouse move:
  - One preview curve (1,024 CVs, never saved, hidden in the Outliner) is made
    when Draw Path starts, and only its CVs are moved through the API.
  - Never create nodes, change the selection or toggle undo mid-stroke. A
    new node or a selection change sends Maya into UI and viewport rebuilds
    costing hundreds of ms.
  - The panel never rebuilds a scatter mid-stroke (`drawer.anchor` is set):
    ray casts flag the surface dirty, and a dense rebuild stalls the stroke.
  - Measure with `tests/gui_draw_bench.py`.
- Strokes: each point hits the nearest mesh under the cursor. Selected meshes
  restrict drawing, but only if the stroke starts on them. On release, meshes
  that got under 15% of the points count as "grazed": they are dropped as
  surfaces and their points are removed, so the path doesn't dip off the edge.
- `RECIPES` holds one-click presets (overrides on `PS_DEFAULTS`). The user's
  benchmark jobs are roof shingles and a messy thatch/straw roof.

## Maya API gotchas found so far
- OM2 `M3dView.viewToWorld(x, y, MPoint, MVector)` fills output args. It
  does not return a tuple.
- OM2 `MFnMesh.closestIntersection`: pass accel params by keyword
  (`accelParams=`). `None` positionally for faceIds raises, and `[]` means
  "no faces". A miss returns `None`.
- OM2 `MFnNurbsCurve.form` is a property.
- `polyUnite` on *instanced* meshes hard-crashes Maya. Bake real copies
  (`MFnMesh.copy`) first.
- Duplicating several instances together keeps them instanced to each other.
- `MFnMesh.copy` does not carry shading. Use `copy_shading()` (handles
  per-face assignments).
- mayapy standalone has a QGuiApplication, so QWidgets can't be built
  headless. UI tests must run in GUI Maya (`tests/gui_smoke.py`).

## Testing
Maya 2024 and 2025 are installed locally (no 2023). Run
`mayapy tests/test_toolbox.py` for the engine. For the UI, launch GUI Maya
with `tests/run_gui_smoke.mel` (see README) and check the screenshots in
the output folder.
