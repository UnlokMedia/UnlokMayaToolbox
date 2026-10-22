# Unlok Maya Toolbox: notes for Claude

## Hard constraints
- **Single pasteable file.** Everything ships in `UnlokToolbox.py`. It must run
  by pasting into the Maya Script Editor in secure environments with no file
  or network access: no imports from sibling files, no pip packages, no
  numpy, no reading or writing files at runtime, no `userSetup`/module install.
- **Target Maya 2023** (Python 3.9, PySide2). Keep 3.9 syntax (no `match`,
  no `X | Y` types). PySide6 fallback import exists for 2025+.
- **Pure ASCII source.** Use `\uXXXX` escapes for symbols. Real non-ASCII
  characters get garbled by tools that read the file with Windows' default
  encoding (a test enforces this).
- **Stability over features.** The user is replacing MASH because it lags
  and crashes. Every UI callback goes through `ui_safe`. Never touch the
  scene from inside Maya API callbacks (only queue a QTimer). Clean up
  script jobs and callbacks on close and on re-paste (`_registry()` in
  `__main__`).

## Workflow
- **The repo lives on Google Drive** (by choice). Drive keeps recreating
  `desktop.ini` files inside `.git`, which breaks git ("bad object
  refs/desktop.ini", fetch "did not send all necessary objects"). Fix with
  `find .git -name desktop.ini -delete` and check with `git fsck`. Don't
  move `.git` off Drive.
- **Push to main as you go.** Commit tested work on `main` and push. No PRs
  and no stacked branches. Parallel sessions rebase onto `origin/main` and
  fast-forward.

## Context
- **Film pipeline.** Don't add game-only features such as lightmap UVs,
  tiling or trim-sheet UVs, or engine export.
- **Naming convention:** comes from the UnlokRenamer repository
  (`../../UnlokRenamer/build`). Treat it as reference: edit it only when the
  user asks for a change there (they did for material variants,
  2026-10-22). Keep `UR_MATERIALS` / `UR_COLORS` and the split helpers here
  in sync with it. Material tokens are a guide: any lowercase word, then
  capitalised word(s) (`woodGreen`, `woodMoulding`), then an optional
  capital variant letter (`glassClearA`). Only other shapes get flagged,
  and each variant is its own material group.
- **Upcoming tool:** Smart UDIM. The plan and its decisions are in
  `docs/smart-udim-plan.md`.

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
- **Speed (Path Scatter compute):**
  - **Cached stages:** compute runs in two stages, cached on the
    `PathScatterSystem` instance. `_place` (curve sampling, surface snapping,
    frames) only reruns when placement settings change. `_finish`
    (scale/rotation) is cheap.
  - **When rotation and scale count as placement:** in Fit to Size they change
    spacing, so there they are placement keys (`_placement_key`).
  - **Invalidation:** `invalidate()` runs on input changes (set_paths,
    surfaces, sources, proxies, presets, and the panel's dirty callbacks).
  - **Surface queries:** use `_SurfaceQuery` (`MMeshIntersector`, ~3 us),
    never `MFnMesh.getClosestPointAndNormal` (~200 us, brute force). The
    intersector answers in object space, so normals go through the inverse
    transpose.
  - **Randoms:** per-item randoms come from `_rand12` (splitmix64), not
    `random.Random` per item.
  - **Measuring:** `tests/bench_scatter.py`.
- **Bakes:**
  - **Combined Mesh:** built in one `MFnMesh.create`, copying UVs, hard edges
    (mapped as face + edge-in-face slots) and per-face shading. It's about
    50x faster than `polyUnite`, which is superlinear. Above 3M points it
    falls back to copies + polyUnite.
  - **Copies:** shaders are assigned with one batched `MDGModifier`.
  - **Instances:** real DAG instances are quadratic inside Maya (each new
    instance gets slower; unshaded too), so the panel warns above 1,500
    and offers Copies or Combined.
- **The instancer's `inputPoints` isn't saved with the scene** (not
  storable; a dynamic arrayAttrs attribute doesn't serialise either), so
  `restore_scatter_previews()` rebuilds every live scatter when the
  toolbox opens and on SceneOpened.
- **UI pattern:** each tool panel has a `ToolHeader`, a `NextBanner`
  ("NEXT: the one thing to do now", updated by `_update_guidance()`) and
  numbered `StepCard`s (todo / current / done). Advanced options go in
  collapsed `Section`s inside step cards.
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

- **Log Noise** (Modeling tab): plugin-free port of a logNoise deformer.
  - **Why no plugin:** a node would need a plugin file written at runtime,
    and every machine opening the scene would need it.
  - **Storage:** the mesh shape stores `unlokLogRest` (doubleArray rest
    points), optional `unlokLogWeights` (from a soft/vertex selection) and
    `unlokLogNoise` (JSON settings).
  - **Engine:** `log_noise_points` is the deformer's maths unchanged.
    `tests/test_log_noise.py` checks it against
    `contrib/log_noise/log_noise.py` to 1e-8.
  - **Writes:** `_ln_write` sets vertex tweaks (`shape.pnts`) as deltas.
  - **Undo:** apply / reset / bake are UndoChunks; slider edits run in
    NoUndo, like Path Scatter's previews.
  - **Topology change:** logs whose topology changed are reported, not
    touched.
- **Bevel Resolver** (Modeling tab): turns the n-gons a chamfer-off bevel
  leaves at its ends into quads. Engine `resolve_mesh` /
  `resolve_bevel_ngons`, panel `BevelResolverPanel`.
  - **Finding:** `bevel_ngons` keeps n-gons touching a thin quad
    (`strip_faces`, short/long side < *Strip ratio*), plus n-gons up to two
    shared-vertex steps away. A component selection resolves every n-gon in
    it, whatever the scope.
  - **Pass 1, parity:** an odd-sided face can never be quadded alone.
    `plan_parity` pairs odd faces through a small Dijkstra (`_br_odd_paths`):
    across a shared edge (one new vertex: the "merge"), straight through
    quads (an edge loop that cuts them), or through even target n-gons (two
    new vertices, no cut). New vertices on bent edges (`edge_bend`) cost
    more. Pairs are chosen by exact bitmask matching per cluster
    (`_br_best_matching`), since greedy pairing strands faces.
  - **Pass 2, split:** `plan_grid` carries support loops straight across a
    rectangle-like n-gon whose opposite sides carry matching extra vertices
    (crossing cuts get exact intersection points). Otherwise `plan_quads`
    scores every diagonal-only split (`_br_splits`: 3 for 6 sides, 7,752 for
    16) by quad squareness plus valence: spilled vertices want a 4th edge,
    and poles cost 4x more on bevel-strip vertices. A 180-degree quad corner
    is allowed but costly (the triangle-shaped quad support loops end in);
    only clearly reflex corners are rejected.
  - **Executing:** plan from one snapshot per pass, since Maya keeps
    indices when it cuts. Cuts are packed into a few `polyConnectComponents`
    calls (`_br_batches`), never one command per cut (see gotchas).
  - **Reported, not touched:** faces with holes, over 16 sides, zero-area or
    with coincident corners (Maya's bevel makes these where recesses touch
    or a bevel runs off a box corner), unpaired odd faces, no clean split.

- **Smart UDIM** (UV tab):
  - **Sets:** state lives in plain Maya objectSets (root `*_smartUDIM_SET`,
    then sections `*_UDS`, then material sets `td100_woodGreen_c085[_stack]`).
  - **Who owns which values:** names are what users edit, so `sync_names()`
    reads `td` and `stack` from names into attributes, and writes the
    tool-owned coverage back into the name.
  - **Unique names:** Maya set names are global, so we add `_2` and `_3`
    ourselves. Parsing ignores all-digit tokens.
  - **Undo:** every scene edit runs inside `UndoChunk`, so it's undoable,
    unlike Path Scatter's live preview.
  - **Status:** milestones 1-2 are done, plus Auto UV (scoring,
    re-unwrapping, packing one tile per group); the plan is in
    `docs/smart-udim-plan.md`.
  - **Auto UV** (`run_auto_uv`):
    - `uv_quality` scores 0..1 by the 3D-area share of good faces, comparing
      each face's area ratio to its own shell's median so rectangulated
      shells pass.
    - `auto_unwrap` isolates failures per mesh.
    - `pack_udims` puts one tile per material group, with sections on rows
      and the same column per material.
      - Pure maths: `_read_shells` (shared with `collect_shells`) gives
        LayoutShells, and `_pack_one_tile` bisects one group-wide scale
        until the skyline packer fits them all (even density, main axis,
        90-degree turns allowed).
      - It writes through `_place_shell` / `write_uvs`, the same code path
        as `apply_layout`.
      - It replaced `u3dLayout`: 46 s down to 1.7 s on the 141-mesh building,
        with fill up from 72% to 77%.
    - Backups go to `map1_backup` and are never overwritten.
    - **Progress** (`Progress`, `Cancelled`):
      - Maya's main progress bar (Esc sets `isCancelled`) plus a panel
        callback, throttled to ~10 updates a second.
      - The panel callback only `repaint()`s its own widgets and never
        processes events, so no timer or scriptJob runs in the middle of a
        scene edit.
      - `u3dAutoSeam` / `u3dUnfold` run in batches of about 8,000 faces
        (`_unwrap_batches`) so progress moves; a single Unfold3D call can't
        report.
      - Unwrapping (Unfold3D) is now the slow part; packing is pure maths
        (below).
  - **Do It All** (`SmartUdimPanel.do_it_all`): Scan (only if needed) ->
    `auto_uv()` -> `apply_layout()` (re-plans itself) -> `validate()`.
    - Each step method returns its result (None when cancelled or failed),
      and the chain stops there.
    - The steps stay separate undo chunks: nesting them would break
      `undo_if_last` on cancel.
    - `confirm=False` skips the question (used by the GUI test).
  - **UV states and colours** (`uv_states`, `show_uv_colours`,
    `hide_uv_colours`):
    - States, in order of precedence: handsoff > laidout > problem > auto >
      keep > good / needs (by score) > unknown. Instanced meshes are
      problems.
    - The panel's scores are each row's `before` from the last Check /
      Auto UV run; what happened since is in the tracking sets (roles
      `uvauto`, `uvlaidout`, `uvproblem`, via `update_tool_sets` inside
      the action's undo chunk).
    - Colours are lambert preview shaders `unlokUV_<state>_SG`, assigned
      in NoUndo. The real shading (`_shading_of`: SG -> face ranges) is
      JSON in `unlokOrigShading` on the shape. `shader_face_groups` reads
      it while coloured, so Scan isn't fooled.
    - `hide_uv_colours` restores only meshes still on a preview SG (the
      user's own re-shading wins), then deletes unused preview shaders.
    - Instanced meshes are never coloured.
    - Live: `auto_unwrap(on_unfolded=...)` colours each finished batch, and
      `Progress.refresh_view` redraws the viewport about once a second.
    - Auto UV Selected (`only=`) packs only the touched groups
      (`pack_udims(only_groups=)`), excluding members that still need UVs.
      Every Hands off mesh in the asset is excluded and its tiles avoided,
      even ones Auto UV did earlier (regression-tested).
  - **Sections** (`section_from_group`, `move_to_section`, `delete_section`,
    `rename_section`, `prune_empty_groups`):
    - Moving keeps each mesh's material key (`_material_keys_of`; unassigned
      faces are sorted by name / shader).
    - `section_from_group` links the section to the group (`UDIM_GROUP`),
      so Scan's `_section_for` sorts later meshes into it.
    - `delete_section` holds sets by uuid: `sync_names` renames them
      mid-move.
    - `selection_items()` expands a selected group to every mesh under it.
  - **Saved session** (`save_session`, `load_session`):
    - The panel's progress is JSON in `unlokUdimSession` on the root set:
      pre-process report, Auto UV / Analyse result, layout_applied,
      validation (`pack_validation`: faces as ranges, 500 items per category)
      and every setting widget (`_widgets()`).
    - It's written after each step, inside NoUndo.
    - `set_asset` restores it. `pick_startup_asset` opens the setup saved
      most recently (`saved_at`).
    - Scene New / Open use `om.MSceneMessage` kAfterNew / kAfterOpen, which
      only start a QTimer. scriptJob NewSceneOpened / SceneOpened events
      didn't reach the panel during a scripted GUI session (the GUI test
      opens scenes from a script).
  - **UV status** (per mesh, whole meshes only):
    - Stored as membership of two child sets of the root set, roles
      `uvkeep` / `uvhandsoff` (`status_set`, `uv_status`, `set_uv_status`).
      `sections()` ignores them because they have a role.
    - Auto UV:
      - Keep UVs meshes are scored but never unwrapped.
      - Hands off meshes aren't scored, backed up, set-switched or packed.
      - `pack_udims(avoid_tiles=...)` starts its rows above their tiles.
    - Layout:
      - `collect_shells` turns Hands off members into `fixed` footprints via
        `uv_footprints` (reads UVs without switching the current set).
      - `plan_layout` always takes their tiles out of the fresh-tile
        iterator.
      - *Pack around them*: each such tile becomes a `_TilePacker` in
        gaps-only mode (`free_around` blocks the boxes plus pad; cached per
        collected), offered first to the groups that own those shells and
        then carried like any tile.
      - *Reserve their tiles*: no packer at all, and a warning when the
        pieces fill under half the tile.
      - Group stats include their tiles, coverage and a `handsoff` count.
  - **Smart layout** (`collect_shells` -> `make_plan` -> `apply_layout`):
    - `collect_shells` reads every shell once (3D/UV area, points, PCA
      angle).
    - `plan_layout` is pure math: exact density per shell, a 2D packer
      tile by tile, sections on new rows, locked tiles reserved.
      `plan_fit_to_tiles` binary-searches the density.
    - `apply_layout` writes through `write_uvs` (undoable) and stores
      tiles, a fingerprint and coverage on each set.
    - Locks live in `unlokUdimLock`; tiles in `unlokUdimTiles`.
    - Orientation:
      - Each `LayoutShell` stores `dims[mode] = (angle, w0, h0)` for 'axis',
        'up' and 'keep', so switching modes is a re-plan with no scene read.
      - 'up' comes from `_shell_up_direction`: world height gradient in UV,
        accumulated over edges.
      - The per-group override is the `unlokUdimOrient` attribute plus the
        `_up` / `_keep` / `_axis` name token.
    - Placements are `(tile_u, tile_v, x, y, scale, angle, w, h)`.
    - `_stack` groups share placements for shells with the same signature
      `(uv count, w, h)` after density scaling.
    - Packing: `_TilePacker` per tile.
      - It's a skyline bottom-left packer plus a list of the gaps left under
        overhangs, which are reused first with a guillotine split.
      - Rects are reserved with `pad` on their right and top, inside
        [pad, 1].
      - Pieces are sorted by long side, then area, then (mesh, first UV id),
        so the same input always gives the same layout.
      - Main axis may turn a piece 90 degrees (angle + pi/2, w/h swapped).
        Upright and Keep never turn.
      - A group may use the tiles the previous group in its section ended
        on, then opens new ones.
      - Packing isn't monotonic in density, so `plan_fit_to_tiles` probes
        upward in 2% steps after its binary search.
      - About 50 ms for 1,200 shells.
    - The plan keys stats by set name *and* uuid: names change when
      coverage is written.
  - **Validation and hand-off** (`validate_layout`, `render_handoff_sheet`):
    - Apply stores its settings as JSON in `unlokUdimLayout` on the root
      set, which gives validation the target density, map size and padding.
    - Overlap candidates come from a bounding-box sweep, then are confirmed
      by `polyUVOverlap`, which works across meshes too.
    - The sheet is QPainter on a QImage (works headless in mayapy).
      Colours come from `GROUP_PALETTE` via `set_key_palette` (sorted
      keys), not a hash, so groups never look alike.

## Speed on big assets
- `expand_members` (MFnSet.getMembers) and `SmartUdimAsset.meshes()`
  (MItDag) use the API: 0.74 s down to 0.08 s per refresh at 3,000
  meshes. `tests/test_fast_reads.py` checks they match the cmds versions
  (`_expand_members_cmds` is kept as a fallback). They differ in one way:
  every transform sharing an instanced shape is reported as instanced.
- Panel refresh is driven by change flags:
  - `MObjectSetMessage.addSetMembersModifiedCallback` (the OM2 name; there
    is no ...ChangedCallback), attribute and name callbacks on the asset's
    sets (`_watch_sets`), and node added / removed for meshes and sets.
  - They only start the refresh timer; the panel's own bookkeeping
    attributes are ignored. Undoing unrelated work no longer refreshes.
- `projection_clean()`: same UV/3D length ratio on every edge of a shell
  (within 15%), nothing flipped or collapsed. Those meshes skip Unfold3D.
- `cached_quality()` + `mesh_fingerprint()` (counts, world area, UV sums):
  the panel keeps `score_cache` in the saved session.
- **The panel's Auto UV never scores** (`run_auto_uv(score="known")`):
  - It unwraps every unmarked mesh, except ones the last Check UVs found
    good that are unchanged since (`known_quality`).
  - The engine default is still `score=True` (score first), so tests and
    scripts keep the old behaviour.
  - The after-check covers only what was unwrapped.
- **Hands off meshes stay cheap everywhere:**
  - never scored
  - `uv_footprints` reads whole meshes per UV and remembers them by
    fingerprint (`_FOOTPRINTS`)
  - Auto UV packing only reads their top V row
  - Validate only range-checks them
  - one-shader meshes skip the per-face shading loop (`_shading_of`,
    `shader_face_groups`)

## Scene safety (freezes and half-done edits)
- **Junk UVs are the main freeze risk:** every face its own shell (common
  on un-UV'd imports). Anything that loops over shells must check
  `oversplit()` first: more than LAYOUT_SHELL_CAP (4,000) shells, or more
  shells than half the faces. Plan, Validate and the sheet skip such meshes
  and report them.
- **collect_shells(ready_only=True)** lays out only Keep / Auto UV'd / laid
  out meshes, or ones scoring at least keep_score. Everything else goes in
  `not_ready`.
- **uv_quality** only runs polyUVOverlap when it can change the verdict, and
  only on shells whose boxes overlap. On 30,000 junk shells the old version
  didn't finish Check UVs in 6+ minutes; now it takes about 3 s.
- **Long steps take a Progress** (Esc raises Cancelled from `item()` /
  `update()`). Panels use `status_progress(label)` as the callback.
- **Cancelling inside an UndoChunk:** roll back with
  `undo_if_last(chunk_name)`, never a bare `cmds.undo()`. A run cancelled
  before it changed anything leaves no step, and `cmds.undo()` would then
  undo the user's previous action.
- **Live re-plans** stop above LIVE_REPLAN_WORK (shells x packs); the user
  presses Plan, which shows progress.

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
- `polyCleanupArgList` argument [1]: the script's header says "select
  only (0/1)", but its code uses **1 = clean up** and **2 = select only**.
- Maya 2024+'s default material is `standardSurface1`, not `lambert1`.
  Don't hard-code either.
- `cmds.instance` puts the new instance at the world root, not under the
  original's parent.
- Selection changes made after an undo chunk closes become separate Ctrl+Z
  steps. Put detection, the fix and any re-checks inside one `UndoChunk`.
- Keeping OpenMaya objects (MObject, MPlug, data) across `file -new` or
  `file -open` and then using them hard-crashes Maya. Re-resolve after
  scene changes.
- **`u3dLayout -box` is `[uMin, uMax, vMin, vMax]`**, not
  `[uMin, vMin, uMax, vMax]`. Its default layout scale mode (2) fits the
  shells to the box.
- `polyAutoProjection`, `polyMapSewMove` and `polyMapCut` only take one object
  per call; loop over meshes. `u3dUnfold` and `u3dLayout` accept many.
- **`u3dAutoSeam` fails with several meshes selected** ("Doesn't work with
  multiple objects selected"). It only prints an error and does nothing,
  so it looks like it worked. Run it one mesh at a time (`_auto_seam`).
  Until 2026-10-22 every multi-mesh batch silently lost its seams. Fixing
  it also made Auto UV much faster: 65 s down to 16 s on the 141-mesh
  building.
- `polyEvaluate -worldFaceArea` / `-uvFaceArea` give per-face areas in C++
  (fast scoring). `-uvFaceArea` reads the *current* UV set.
- Switch a mesh's current UV set inside `NoUndo` (it's view state).
  Otherwise stray undo steps land between tool actions and Ctrl+Z stops
  undoing whole runs.
- Writing UVs:
  - `MFnMesh.setUVs` sticks on the *current* UV set even with history, but
    it isn't undoable, and writes to another set get recomputed away on
    history meshes.
  - For undoable bulk writes use `write_uvs()`. Without history it's one
    `setAttr` on `shape.uvst[i].uvsp[a:b]`; with history it adds a
    polyTweakUV (via one `polyEditUV`) and does one `setAttr` on
    `.uvTweak[a:b]`.
- Tiny shells (a few % of a tile with thousands of faces) trip
  `polyUVOverlap` and absolute area thresholds. Treat only *exactly* zero
  UV area as collapsed, and test layouts at real-world scale (metres).
- mayapy standalone has a QGuiApplication, so QWidgets can't be built
  headless. UI tests must run in GUI Maya (`tests/gui_smoke.py`).
- Keeping an `MFnMesh` across a `cmds` topology edit (polySplit etc.) can
  hard-crash Maya. Make a new one from the dag path after every edit.
- Writing vertex positions undoably: `cmds.setAttr(shape.pnts[a:b], *xyz,
  type="float3")`. Without `type="float3"` the values are stored, but a mesh
  with no construction history doesn't update (getPoints / pointPosition
  stay old). Writing `.vrts` doesn't update either.
- Poly edits keep indices: existing vertices, edges and faces keep their
  index and new ones are appended. A split edge keeps its index for one
  half; a split face keeps it for one part.
- `polySplit` in Python: use `ip=[(edge, factor), ...]` (`ep`/`fp` print a
  deprecation warning). `ch=False` is ignored on a mesh with history.
- With construction history, every new poly node re-evaluates the chain
  (a polyBevel3 node on a 4k-face mesh costs ~0.15 s per command). Cost is
  in the number of commands, not cuts: batch them.
- `polyConnectComponents` takes many vertices and/or edges in one call and
  joins any two selected components that share a face (edges at their
  mid-points, chaining through quads). Fine for batching if no face holds
  two selected components except the cut you mean (`_br_batches`).
- `polyBevel3` with `chamfer=False` keeps the shape (support loops); the
  n-gons it leaves are where a bevelled edge chain ends. Closed loops miter
  into all quads.

## Testing
- **Set `MAYA_DISABLE_CER=1`** for every mayapy / maya.exe test run. A Maya
  that crashes or gets killed otherwise pops Autodesk's error-report window
  on the user's screen (they share the machine). Always shut down cleanly
  (`maya.standalone.uninitialize()` before `os._exit`), and keep runs few:
  full suites plus the GUI smoke once before a push.
Maya 2024 and 2025 are installed locally (no 2023). Run
`mayapy tests/test_toolbox.py`, `tests/test_smart_udim.py` and
`tests/test_bevel_resolver.py` for the engines, and
`tests/bench_scatter.py [--profile]` for speed. The Bevel Resolver GUI test
is `tests/run_gui_bevel_resolver.mel` (screenshots in
`tests/_out/bevel_resolver`). For the UI, launch GUI Maya
with `tests/run_gui_smoke.mel` (see README) and check the screenshots in
the output folder.
