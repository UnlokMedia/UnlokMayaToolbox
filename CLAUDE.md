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
  collapsed `Section`s inside step cards ("Options").
  - **Look:** the page is darker (`unlokColumn`); cards have a coloured
    left strip by state (grey todo, teal current, green done, amber
    `unlokTone="warn"`). Section headers are teal.
  - **Folding:** every `StepCard` folds when its header is clicked. Folded,
    it shows `set_summary(text, tone)` instead of its explanation.
  - **Progressive disclosure:** `card.enable_auto()` (Smart UDIM only) opens
    a card when it becomes current or gets a "warn" summary, and folds it
    when it's done or not yet reached, until the user opens or closes it
    themselves; that choice lasts until the state changes.
  - `StepNav` (Smart UDIM's strip of numbered chips) jumps to a step.
  - Smart UDIM fills the summaries in `_summarise_steps`. Its UV legend
    only shows while colours are on.
  - **Tests:** checks that a widget inside a card is shown use
    `not w.isHidden()`, since `isVisible()` is False inside a folded card.
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

- **Rope Lashing** (Modeling tab): ties logs with real lashing recipes.
  Engine `rope_path` (pure maths plus ray casts) -> `rope_mesh`; scene side
  `lash`, `update_ropes`, `rebuild_stale_ropes`; panel `RopeLashingPanel`.
  - **Logs:** `RopePole` fits a straight main axis (joint maths) plus
    per-slice centres and radii (bent / Log Noise logs). Slice borders
    snap into the widest gap between vertex rings: a border through a ring
    pulls that half ring's centre sideways (13 cm on a tilted log).
  - **Path:** `_RopeTie` builds samples (S on a log surface or free, u the
    side the rope sits on, log index). Loops are the convex hull of the
    logs' cross-sections in a plane (ellipses: support points); Square uses
    half-turn arcs per log with corners solved for any angle. Fraps are a
    spiral around where the wraps cross the gap between the logs (no room
    to stack them along it where logs touch).
  - **Finish** (`_rl_finish`): even resample -> press onto the real surface
    (ray casts, max filter = a taut rope bridges dips) -> `_rl_avoid` (out
    of the *other* log) -> tails -> wobble -> `_rl_ride_over` (later rope
    lifts over earlier rope, with ramps) alternating with `_rl_avoid`.
  - **Mesh:** strips with U around, V along, cut into columns that fill
    0..1. Twisted rotates the ring with the lay so the grooves follow edge
    loops.
  - **Undo:** API meshes can't be undone, so `lash` makes a 1-face
    polyPlane plus the settings JSON inside the chunk, then fills it with
    `createInPlace` in NoUndo. A redo brings the plane back, and the
    panel's Redo scriptJob runs `rebuild_stale_ropes` (4 verts / 1 face and
    `unlokRopeVerts` != 4). Live edits are NoUndo, like Log Noise.
  - **Live preview** (`show_rope_previews`): with logs selected, the panel
    shows what Lash would make. Same `_rope_plan` as `lash` (seeds come
    from `_rope_pair_seed`, so preview and result match). Meshes are made
    through the API in NoUndo, `setDoNotWrite`, reference display (not
    selectable) and tagged `unlokRopePreview`; the selection never changes,
    so no SelectionChanged loop. The panel pins the preview to its logs
    (`_pin`: uuids + target), so it survives deselecting; selecting other
    logs (live on) re-pins, selecting lashings (edit mode), Clear Preview
    and Lash drop it. Lash with no logs selected ties the pinned logs.
  - **Bake** renames the settings attr to `unlokRopeBaked` (not deleted), so
    a redo's empty seed plane can still be rebuilt (`rebuild_stale_ropes`
    handles both). Baked ropes are never taken for logs (`_rope_extra`). The
    panel's Bake with nothing selected lashes the preview (`lash(bake=True)`)
    and bakes every lashing inside one outer UndoChunk.
  - **UV hand-off:** rope shapes get `unlokUvReady` (UV_READY_ATTR). Smart
    UDIM's scan (`_mark_tool_uvs`) marks tagged meshes with no status Keep
    UVs; `set_uv_status(..., "auto")` deletes the tag so the choice sticks.
  - **Hitches and ends:** `clove_z` is 1.6 turns (turn two stops before the
    diagonal; a full second turn lay on top of itself). Hitches meet the
    rope coming in / going out tangentially (`loop(tangent=)`), not head-on
    through the air (that lifted turns 12+ radii off the log). Cut ends are
    `_rl_tuck`ed: bent onto the log under the turns, placed first in
    `_rl_ride_over` (`first=`) and never lifted or ramped (a ramped end made
    the turns climb every pass), and left out of the final smoothing.
  - **End joints:** `rope_joint` flags `endA` / `endB`; `rope_path` turns a
    crossing where a log ends into a **Saddle** (`_rl_saddle`). `rope_pairs`
    groups touching pairs into joints (pairs sharing a spot) and keeps a
    spanning set per joint, preferring the joint's hub (the log most
    members touch, thickest first: the post), then the log a member bears on.
  - **Crowded logs in a combined joint:** when another member touches the
    same log within a square lashing's reach (`crowding`, from contacts
    between *all* the joint's logs, tied or not), a beam crossing within 30
    deg of square goes one-sided: `_rl_saddle(inward=..., blocked=...)`,
    turns round the shared log only on the free side (starting past the
    beam), passes over the beam only on a side no other member crosses.
    Without it the two lashings stacked on the same stretch of post and the
    later rope floated off it. With only one side of the beam free, every
    turn goes under the beam there, up its face and a whole turn round the
    post, back down that side; alternating half turns left every other turn
    on the wrong side, cutting across to the beam through the air. No room
    on a short beam stub for the end hitch: it goes on the post. In a
    combined chain the rope runs along the shared log's surface to the next
    member. (Tried and worse: a full turn round the beam; starting the
    turns past a brace crossing the post's far side; picking the turns'
    side by which way the post is freer.)
  - **Side by side (3+ logs within 25 deg of their mean direction)**:
    `_rl_side_by_side` runs before the joint chain. Height: the target, or
    where the logs pack closest without clashing (a splayed tripod's top).
    Row (spread across < 8% of along) -> `_rl_tripod`: racking turns out
    along x at z and back at z + d (crossings in each gap stack along the
    logs; explicit gap samples lift along w, lerped sideways ups were
    degenerate and flung rope out), then `tie.fraps` per gap with room;
    cluster -> `_rl_bundle` (hull loop of all sections).
  - **Combined lashings** (the user's rule: what's selected together is bound
    together): a joint with 3+ logs is one rope. Builders return (start
    hitch, body, end hitch); `rope_path` with 3+ poles walks the joint's
    edges depth first from the hub log, takes the first segment's start
    hitch, every body and the last end hitch, remaps pole indices and
    finishes it as one path. Kind "Combined"; stored with all its logs. `_rope_plan` passes the joint's other logs (`others`, kept out
    of) and earlier rope (`obstacles`, ridden over; lifts capped at 5
    diameters when crowded, since overlapping logs leave no room).
  - **Tension and order in `_rl_finish`:** smooth + unkink + avoid first,
    then the ride-over / avoid loop, then unkink and one more ride-over.
    Smoothing after the lifts flattened rope-over-rope bumps back into
    overlaps. `_rl_bridge` (inside each lift pass, idempotent so passes
    settle) fills dips shorter than 4 rope widths between lifted stretches.
    Hitches take `flow` (the rope's travel at the joint): same turning
    sense, and on-surface joins start a little ahead so the rope spirals in
    (no Z-shaped jog). Default wobble 0.05.
  - **Settle** (`_rl_settle`, after the ride-over has set the over / under
    crossings): position-based simulation on a coarse copy (one point per
    1.25 rope radii, Catmull-Rom back): segment rest lengths shrink by up
    to 5% x Tension, stiffness (Jacobi pull to neighbours' midpoint),
    Gravity on points not owned by a log, rope-rope pairs (refreshed every
    6 steps; small steps keep the topology) and fixed obstacles, logs
    (centre / radius measured every 6 steps, bumps by one ray cast per
    point), friction (keeps 35% of sliding on a log), tucked ends pinned.
    Wobble's wandering is added after it so the slider stays in control.
    Settle 0 = the old path (extra unkink + ride-over).
  - **Kinks:** `_rl_unkink` eases bends tighter than 1.5 rope radii;
    `_rl_frames` keeps the last direction where points bunch up (a flipped
    frame threw strands out as spikes). Later lift passes only re-check
    rope near what moved (`dirty`).
  - **Presets:** user presets are JSON in the `unlokRopePresets` optionVar
    (Maya writes its prefs; the tool writes no files).
- **Thatch Roof** (Modeling tab): a roof from a box. Engine `ThatchField`
  (pure maths) -> `_th_grid` -> `_th_shell_mesh` / `_th_pieces_mesh`, all in
  `thatch_build`; scene side `make_thatch_roof`, `update_thatch_roofs`,
  `rebuild_stale_thatch`, `bake_thatch`; panel `ThatchRoofPanel`.
  - **Frame** (`thatch_frame`): the box's world matrix and its mesh's local
    bounding box give roof space: x along the ridge, y up from the eaves
    (the box's bottom), z across; L / W half the length / width, H height.
    Settings sizes are fractions of the span (2W; a cone's mean diameter).
  - **Height field** (`ThatchField.height`): side planes (`_th_sabs` rounds
    the ridge only within its radius: `sqrt(z^2 + r^2) - r` lifted the whole
    slope by r, so side eaves sat 20 cm above hip eaves and the eave lip
    jumped at the corners) smooth-minned (`_th_smin`) with each hipped end's
    plane. A hip's eave overhang is scaled by the pitch ratio so the eaves
    stay level. Two hips that meet before the ridge split where they cross.
  - **Height fraction t** (h / H) drives the levels (`shell`: each level's
    lip stands proud at its bottom, decays up it) and the ridge cap (`t_cap`
    minus `drop(p)`, the scallop / point cut).
  - **Three coordinates across the slope:** `along` (arc length round the
    hip apex: UVs and the cap pattern; injective, so UVs never overlap),
    `strand_along` (constant straight down each face, blended over the
    hip by the smin weight: the straw grooves; the first version used the
    arc-length one and the straws spiralled on hips) and, on a cone, the
    angle. The plane-wise one can't be the UV: end and side points overlap.
  - **Underside:** halfway between straight down and the normal, scaled to
    keep the thickness across the slope. Along the normal it folded at hips
    rounder than the thatch is thick (ears at the eave corners); straight
    down made a tall upright eave band.
  - **Pieces:** per grid cell, expected count = area x rate (density 1 =
    about three deep), dithered by `_rand12`. Each walks up the slope
    (re-sampling the grid with `_th_cell` / `_th_sample`, never turning back
    over the ridge), lifted at the butt and tucked at the top; the bottom
    course is pushed down over the eaves. Every piece has the same UV
    layout; the stack offsets U by a tile or a column. Capped at
    `THATCH_MAX_VERTS`.
  - **Undo:** like Rope Lashing: the group and two seed planes ("straw",
    "underlay") inside the chunk, filled in NoUndo (`_th_write` via
    `_rope_fill`). An unused underlay is a hidden 4-vertex placeholder
    (`THATCH_VERTS` = 4, so it's not stale).
  - **Leaf Panels** (`_th_panels_mesh`): courses at height fractions
    `dt` apart (panel length x 0.45 / density down the slope). `_th_contour`
    finds where t crosses grid edges, sorts by (slope side, `along`) and
    splits at jumps; panels are laid along each polyline (start jittered
    per course, trimmed to 0.1 panel past the verge: untrimmed they stuck
    out as shelves). Each of a panel's columns walks up the slope with
    `_th_walk` (shared with pieces); bottoms lifted (lift x 0.25 x length,
    less and the courses didn't read), bottom points frayed. A panel whose
    contour runs the other way is reversed with U mirrored, so fronts face
    out and UVs stay upright.
  - **Makeshift** (`warp`, `ridge_sag`, `ragged`, `gaps`): warp and ridge
    sag are in `height` (so courses and levels follow them); ragged moves
    shell points near the eave down the slope (outer and inner together,
    so the shell stays closed; the cone's jags wrap a whole number of
    times); `gap_at` is clumped noise that pieces and panels skip.
  - **Presets:** `thatch_preset` resets every shape key and sets the look
    keys a preset names, so shape presets keep the style and look presets
    (Cambodian shack, Grass hut) set it.
  - **Deformed boxes:** `_th_box_corners` sorts an 8-vertex mesh's corners
    by which side of the box's middle (object space) each is on; the frame
    keeps them (world space) with `axis` and `flip` (mirrored box). The
    roof is built on the average box (L, W, H from the averaged edges) and
    `_th_to_world` maps it trilinearly through the corners (exact for a
    plain box: the old straight transform is kept for non-box meshes).
  - **Following the box:** the panel's attributeChange scriptJobs on the
    box's translate / rotate / scale / shear only restart a 150 ms timer;
    `thatch_box_moved` compares the stored frame (corners included).
    Vertex edits send nothing reliable: neither an attribute-changed nor a
    dirty-plug callback on the box's mesh fired for a scripted vertex move
    in GUI Maya 2024. So while the panel is shown, `_poll_box` compares the
    frame every 0.4 s and rebuilds once it has held still for one poll.
    Selecting a roof also checks it (changes made while the toolbox was
    closed). In GUI tests, take camera moves out of the undo queue and undo
    before playblasting: a test's undos found an empty queue after them.
  - **UV hand-off:** both meshes get `unlokUvReady`; the straw also gets
    `UV_STACKED_ATTR` (True for planes / pieces). `_mark_tool_uvs` marks
    stacked meshes Hands off, the rest Keep UVs; `set_uv_status(..., "auto")`
    deletes both tags.
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
  - **Auto UV fit** (`pack="fit"`, what the panel uses): no group layout.
    - `auto_uv_targets` picks each mesh's tile before unwrapping. Order:
      the panel's plan (`_planned_tiles`, passed as `target_tiles`), then
      the group's `unlokUdimTiles`, then the mesh's current tile
      (`_uv_tile`, majority of its UVs), then 1001.
    - `fit_meshes_to_tiles` packs each mesh's shells into its tile with
      `_pack_one_tile`.
    - `pack=True` is still the old `pack_udims` (one tile per group).
  - **Auto UV + Lay Out Selected** (`auto_uv_lay_out_selected`, the user's
    "quick look as I go"): `auto_uv(selected=True)`, then
    `lay_out_together(meshes, udim=free_tile_for(...), keys=)` in its own
    "Lay Out Selected" chunk. One square per material key (from
    `asset.assignments()`, mesh level), the same neat machinery as the
    squares layout (`_mesh_bundles`, `_similar_blocks`, `_smallest_square`,
    `_group_dims`), squares placed biggest first with a `_TilePacker`;
    the density scale starts where the biggest piece fills a tile and is
    bisected down until everything fits. `free_tile_for` uses
    `mesh_tiles` (one `polyEvaluate -boundingBox2d` per mesh via
    `handsoff_box`, never a UV read): the selection's own single tile if
    no other mesh touches it, else the first untouched UDIM. "Other" means
    what the tool placed (`tool_members("auto")`, `("laidout")`, marked
    meshes), not every mesh: untouched meshes' junk UVs, and boxes spread
    over many tiles, sent quick looks far up the grid (the user saw it).
    A mesh spread over more than 4 tiles counts only `_uv_tile`; a Hands off
    one over 16 is ignored. Nothing is
    stored (no sets, tiles, density, laid-out tracking); it drops the
    panel's `_collected` / `_plan`.
  - **Do It All** (`SmartUdimPanel.do_it_all`): Scan (only if needed) ->
    `auto_uv()` -> `apply_layout()` (re-plans itself) -> `validate()`.
    - Each step method returns its result (None when cancelled or failed),
      and the chain stops there.
    - The steps stay separate undo chunks: nesting them would break
      `undo_if_last` on cancel.
    - `confirm=False` skips the question (used by the GUI test).
  - **UV states and colours** (`uv_states`, `show_uv_colours`,
    `hide_uv_colours`):
    - States, in order of precedence: handsoff > keep / keeplayout >
      laidout > problem > auto > good / needs (by score) > unknown.
      Instanced meshes are problems unless Hands off.
    - The user's marks outrank "laidout" (since 2026-10-27), so after a
      layout the colours still separate their UVs from the tool's. Laid-out
      progress shows in the Status column (`_status_text`) and the
      inspector. Only Scan (`_mark_tool_uvs`, for tool-tagged meshes) and
      the mark buttons ever set a mark; nothing clears one.
    - Marking Keep UVs / Hands off (`set_uv_status`) also removes the mesh
      from the problem set. The flag used to outrank the mark, so marked
      meshes stayed red.
    - Rows' `reason` after an unwrap is the after-check's (`unwrapped, but:
      ...`), not the pre-run score's.
    - `uv_quality(detail={})` fills the bad faces by category (no_uv,
      stretched, folded, overlap) and forces the overlap test. Its reason
      gives a percentage per category.
    - **Inspector** (`inspect_selection`, run by a SelectionChanged
      scriptJob through a guarded timer): mirrors the selection in the
      list (`_syncing` stops the loop back to the viewport) and explains
      the state (`_why`).
      - `inspector_fix` either clears an out-of-date flag or calls
        `auto_uv(selected=True, force=True)`; `force` sets score=False.
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
  - **Following Maya groups** (`group_links`, `link_groups`,
    `unlink_groups`, `follow_links`, `pin_overrides`):
    - **Links:** sections and material sets have `unlokUdimLinks`, multi
      message connections from Maya groups; a section's `UDIM_GROUP`
      counts too. Message connections survive renames and reparenting.
      The closest linked parent decides (`_link_for`); a material link on
      the same group beats a section link.
    - **Material links are authoritative:** the whole mesh goes in.
    - **Section links** only sort unassigned meshes, plus meshes under paths
      that were just reparented or created (`changed`). Meshes placed by
      hand before links existed are never yanked.
    - **Pins:** `unlokUdimPins` on a material set holds meshes put there
      by hand against a link. `assign`, the panel's New Group / New Section
      / Move to Section call `pin_overrides`. `link_groups` unpins what's
      under the groups (explicit wins).
    - **Leaving a group:** a link-moved mesh gets `unlokUdimFollowed` JSON
      (from sets by uuid, to, via group). When it's no longer under `via`
      (moved out, or Ctrl+Z of the reparent) and still where the link put
      it, `_restore_follow` puts it back. This runs before the section
      rule, which would otherwise grab it first.
    - **Live:** `MDagMessage.addParentAddedCallback` notes the child path
      (`_reparented`, `_links_dirty`) and starts the refresh timer.
      `refresh` then runs `_follow_groups` in **NoUndo**. An undoable sync
      step would be redone the moment Ctrl+Z undid it. Membership is
      derived from the hierarchy, and Ctrl+Z of the reparent is handled by
      the restore above.
    - Scan runs `follow_links` first.
    - **Check & Fix Groups** (`group_health`, `fix_groups`,
      `GroupHealthDialog`, panel `check_groups(confirm=)`):
      - Every link is also remembered as JSON `unlokUdimLinkInfo`
        {group uuid: name}, written by `_record_links` in `link_groups` /
        `create_section` and cleared by `unlink_groups`. A remembered uuid
        that isn't connected any more is a broken link. Guess: the node
        with that uuid, else a group with the same short name.
      - Suggestions (`_suggest_group`): the closest common parent group of
        a material set's whole-mesh members, if 80%+ of the meshes under it
        are in the set and neither the set's section nor another set
        follows it.
      - The moves come from `follow_links(everything=True, dry=True)`.
      - `fix_groups` does relinks, then follow (everything), then `scan`
        (unsorted), then `prune_empty_groups`, all in one chunk.
      - **Gotchas:** `cmds.ls([])` lists every node in the scene: guard
        empty lists before an `ls` of names. Deleting a Maya group also
        deletes an *empty* set whose only connection was to it.
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
    - Stored as membership of three child sets of the root set, roles
      `uvkeep` / `uvkeeplayout` / `uvhandsoff` (`status_set`, `uv_status`,
      `set_uv_status`).
    - **Keep Layout** (`keeplayout`) is Keep UVs plus "keep the
      arrangement". `collect_shells` lists those meshes in
      `collected["keep_layout"]`.
    - `plan_layout` takes their shells out of `sizes` and packs each mesh
      as one `_layout_unit` compound: one k from the mesh's total 3D/UV
      area, shells at their current offsets (hull boxes about `cx`/`cy`),
      angle 0, shrunk to fit a tile with a warning.
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
      angle). `_read_shells` keeps them in `_SHELL_CACHE` per (mesh, UV set,
      unit, faces), checked by `_shell_signature` (`mesh_fingerprint` plus
      the world matrix, since 'up' depends on it): the panel drops
      `_collected` on every refresh, and building LayoutShells is most of a
      read (4,800 shells: 1.3 s first, 0.2 s again).
    - **Squares** (`squares`, the panel's default; engine default off):
      `plan_layout` turns each group's pieces (after bundles / similar
      blocks / Keep Layout units) into square compounds with
      `_group_squares`: the smallest square they pack into in rows
      (`_Shelves`: first fit by height over `_by_height`-sorted cells,
      PolyRaven-style; it replaced the skyline-with-gaps packer inside
      squares on 2026-10-27, same density and tiles on the test building,
      much tidier)
      (`_smallest_square`: 2% steps up from the area bound, starting from
      the step that fitted last time, `collected["_square_hints"]`, so each
      Fit attempt costs a pack or two), or whole-tile squares filled
      first-fit plus a smallest square for the rest. A section's squares are
      then placed biggest first into tiles (`_TilePacker` takes any `size`),
      shared by the whole section; pinned groups only use their pins.
      **Neat over tight** (the user's rule, 2026-10-27): rows only. A
      MaxRects packer (best short side fit) was tried inside squares and
      bundles: about 10% fuller squares, but tucked pieces into gaps, and
      the user prefers grids and rows. Don't bring it back.
      - Compared with PolyRaven itself (installed on the user's AM_Custom
        shelf, Maya 2024 prefs; MEL in the shelf button): its *Size Based
        D'n'L* groups items (objects, or shells with one mesh selected)
        whose bounding boxes match within 0.001 UV, distributes each group
        as a near-square grid ("force square"), then packs the groups'
        bounding-box proxy planes with `u3dLayout -ls 1` into 0..1
        (UDIM-aware). Its gap is 2 px at 4096. Most of its edge over ours
        was our grid bug: `_similar_blocks` used `ceil(sqrt(...))`, and with
        padding two 2:1 panes became a 4:1 strip (24% full squares, now
        95%). `_square_grid` now picks the grid with the smallest larger
        side.
      - `_similar_blocks` uses `SIMILAR_SMALL_TOL` (15%) for pieces under
        `SIMILAR_SMALL` (8% of a tile): lots of small bits read best as a
        grid.
      - `_neat_bundle` (a mesh's shells, `keep_meshes`) tries rows at five
        widths and keeps the smallest box; `hints[("bundle", mesh)]`
        remembers the winner, since the Fit searches re-plan at ~20
        densities (without it Plan went 0.13 s -> 1.7 s on 945 shells).
      - **One direction per material** (`_group_dims`, used by
        `plan_layout` and `largest_shells`): in 'up' mode, long pieces
        (`LONG_ASPECT` 1.4) vote by 3D area for lying across or up; the
        losers turn a quarter. The user's rule: every woodBrown log the same
        way, so one texture wraps along them all.
      `plan["blocks"]` lists them; stats get `placed_rows`, which
      `section_rows` prefers. Squares never overlap, so materials never fill
      each other's gaps (the user asked for this after freeform plans mixed
      colours in tiles).
    - **Quick Plan** (`quick_groups`, panel `quick_plan`): from the sets
      (names, TD %, pins, locks) plus one area per set from `_set_area`:
      `polyEvaluate -worldArea` on the whole-mesh members and summed
      `-worldFaceArea` on face members (`-worldArea` counts a face member's
      whole mesh). That's C++ only, at most two calls per set, never a
      Python loop over meshes. The user's rule: Quick Plan must not run over
      meshes. A first version looped per mesh (members, `_group_print`,
      areas) and stalled on big scenes. Measuring stops after
      `QUICK_AREA_BUDGET` (2 s); unmeasured groups have `area` None, no
      square, and are listed with `?`. `plan_layout` sizes squares with
      `_estimate_squares` / `SQUARE_FILL` (0.45: 145 vs 146 px/m on the test
      building) and gives every Quick Plan section its row even with no
      squares. The viewer lists each row's materials in its name band.
      Hands off meshes become `fixed` pieces from `HandsOffFinder` (one
      UV-box query each, never read), so squares pack around them (the
      user caught squares landing on them), and `_set_area` skips them.
      `expand_members` runs only when the asset has any.
      It's for arranging and debugging: in the viewer a section's name
      band drags to another row (`UVCanvas` row drag ->
      `UVViewer.drop_section` -> `move_section_to`, one Ctrl+Z), a click on
      a square selects the group's set (its meshes), a square drag pins.
      `pin_groups` / `_replan` / `move_section_to` re-run the quick plan
      while one is on show; `plan_layout` / `plan_live` in the panel
      re-collect when `_collected["quick"]`, so it's never applied.
      `_planned_tiles` expands members only when Auto UV asks.
    - The in-panel `UdimMapWidget` is hidden (it lagged on big plans: a
      rect per shell, hit-tested on every mouse move); the UV Viewer button
      shows the layout.
    - **Trimmed panel (2026-10-27, after a review):**
      - Step 7 keeps Density, Map size, Mode (+ Max tiles), Padding,
        Orientation and one *Tidy blocks* (`lay_tidy` = group_similar +
        keep_meshes).
      - Fixed in `_layout_settings`: squares, a new row per section,
        auto-compensate, no growth, hands-off packed around. The engine
        still has the options.
      - *Labels in UV Editor* lives in the viewer; `labels_btn` is a hidden
        panel checkbox it toggles.
      - Step 6 lost *Fit each mesh* (always "fit"), *Re-unwrap with
        Unfold3D* and *Clear problem* (Fix clears). Restore Backup is in
        Options.
      - Step 3 shows five buttons; the rest are in `_tree_menu` (plus Stack
        and Orientation). The Stack / Orient / Pin columns hide until a
        group uses them.
      - The UV set field is in step 1.
    - **Speed rules from the review:**
      - Apply writes the plan on show when `_plan_is_current()`, and
        doesn't plan again afterwards.
      - Do It All runs Auto UV with `pack=False`, since the layout places
        everything anyway.
      - `collect_shells(score_cache=)` reuses Check UVs scores through
        `known_quality`. Never use `cached_quality` here: its key includes
        check_overlap, so it would overwrite them.
      - Auto UV backs up only what it rewrites.
      - Refreshes:
        - `_timed_refresh` skips while the panel is hidden; `showEvent`
          catches up.
        - `_quietly` hides our own label mesh from the callbacks.
        - Shading-group sets are ignored (`_set_added`).
        - `_watch_sets` re-arms only when the set list changes.
      - The inspector diagnoses only problem / needs / unknown meshes (or
        any mesh with step 6 open), up to 20k faces.
      - The viewer draws only `plan["blocks"]` mid-search and turns
        antialiasing off above 2k items.
      - Ticking colours never runs Check UVs; unscored meshes show grey.
      - `hide_uv_colours` finds coloured shapes with one `ls "*.attr"`.
        It lists each node twice, so dedupe it.
    - `plan_layout` is pure math: exact density per shell, a 2D packer
      tile by tile, sections on new rows, locked tiles reserved.
      `plan_fit_to_tiles` binary-searches the density.
    - `apply_layout` writes through `write_uvs` (undoable) and stores
      tiles, a fingerprint and coverage on each set.
    - Locks live in `unlokUdimLock`; tiles in `unlokUdimTiles`.
    - Orientation:
      - **Straightening:** `LayoutShell` takes the tightest-box angle from
        its hull's edges (rotating calipers, smallest perimeter). 'axis'
        is the quarter turn with the long side along U; 'up' is the
        quarter turn that best points `_shell_up_direction` at +V (the
        PolyRaven world-orientation idea). `has_up` tells flat pieces
        apart. `_pack_one_tile` (Auto UV fit) uses 'up' and only turns
        shells without an up.
      - `ORIENTATIONS` puts "Upright" first (the panel default);
        LAYOUT_DEFAULTS keeps "Main axis" for scripts and tests.
      - **Similar blocks** (`group_similar`, panel only):
        `_similar_blocks` groups pieces within 4% on both sides into
        near-square grids packed as one rectangle (never turned).
        Placements are per cell.
      - **Compounds** (`_Compound`): pieces packed as one rectangle,
        children `(item, x, y)`, padding inside each cell; nest freely;
        `leaves()` flattens. The placement loop expands them; they never
        turn.
        - `_mesh_bundles` (`keep_meshes`, panel only) shelf-packs a mesh's
          shells (rows, tallest first, ~square). Meshes too big for a tile
          stay loose.
        - `_similar_blocks` then makes grids of near-identical pieces;
          bundles included, so identical rope binds line up.
        - `_stack` groups skip both.
      - **Pins** (`unlokUdimPin`, `parse_tiles`, `group_pin`,
        `set_group_pin`):
        - `collect_shells` reads them. `plan_layout` reserves every pinned
          tile and packs a pinned group into `pin_packer`s for its tiles.
          Overflow takes the next fresh tile and warns. A pinned group
          doesn't hand its tiles on (`carry`).
        - `section_rows` skips pinned groups, and `auto_uv_targets` uses a
          pin's first tile.
      - **Re-layout of some groups** (`collect_shells(only=...)`, panel
        `relayout_groups`):
        - Other groups go in `locked` with `kept=True`. Their tiles come
          from the stored layout plus their UV footprints, and their
          shells join `collected["fixed"]` as obstacles.
        - Kept tiles aren't reserved outright: the fixed packers leave gaps.
        - Chosen groups get `prefer` = their old tiles, reserved and
          offered to them first through the shared `pin_packer`.
        - The panel forces Fixed density at the stored density.
      - **UV Viewer drag:** `UVCanvas` keeps `_moving`; a press-and-move
        over 6 px drags the item's group (ghost outlines plus a target tile
        while dragging). Release calls `UVViewer.drop_group` ->
        `pin_groups` (re-plans if a plan was on show) or, on scene UVs,
        `relayout_groups` + `show_scene`.
      - Each `LayoutShell` stores `dims[mode] = (angle, w0, h0)` for 'axis',
        'up' and 'keep', so switching modes is a re-plan with no scene read.
      - 'up' comes from `_shell_up_direction`: world height gradient in UV,
        accumulated over edges.
      - The per-group override is the `unlokUdimOrient` attribute plus the
        `_up` / `_keep` / `_axis` name token.
    - Placements are `(tile_u, tile_v, x, y, scale, angle, w, h)`.
    - **Split big shells** (the user: never cut flat planes, "unless ... at
      a 50% line to split it into two if it's too big for a UDIM"):
      `oversize_shells(collected, plan, status)` lists shells bigger than
      the usable tile at the plan's density (`_group_dims` sizes; cols x
      rows parts) except Keep UVs / Keep Layout / Hands off meshes.
      `split_shells` bins each shell's faces by their UV centre along its
      laid-out axes (rotated by the dims angle) and `polyMapCut`s the edges
      between bins (one call per mesh; UVs don't move; a one-face shell is
      skipped). The panel's `lay_split` (More options, default on): the
      summary names them; `apply_layout` calls `_split_big_shells` first
      ("Split Big Shells" chunk, up to 3 rounds, stops when nothing could
      be cut), drops `_collected` and re-plans. Planning stays pure maths:
      Density only exists once a plan does (Fit modes), so the split can't
      happen in Auto UV. In the scripted GUI session the undo queue is
      empty there, so its Ctrl+Z is tested in `tests/test_squares.py`.
    - **Fit largest shell** (`FIT_LARGEST`, `plan_fit_largest`):
      `largest_shells` gives each shell the most global density (before TD
      %) at which its larger side, in its orientation, still fits inside
      the padding: `usable * res / (side0 * sqrt(area3d / area_uv) * td%)`.
      Keep Layout meshes count as one block. The plan is a Fixed density
      plan at the lowest of those x 0.999, with `plan['largest']`. Its
      settings keep the panel's mode and density, so `_plan_is_current`
      works. The panel's *Find Largest Shell* selects the top shell's faces
      (`_id_ranges` -> map components -> faces) and lists the next five.
      The user's loop: cut the largest, find again, until the density is
      good.
    - **Fit sections to rows** (`FIT_ROWS`, `plan_fit_rows`, the panel's
      default mode):
      - It bisects one density scale (like `plan_fit_to_tiles`) until every
        section's placed shells sit on one UDIM row (`section_rows`), with
        new_row_per_section forced on, then probes 2% steps upward.
      - The engine's LAYOUT_DEFAULTS mode stays "Fixed density", so scripts
        and tests that pass a density keep their behaviour.
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
        upward in 2% steps after its binary search (12 halvings, 8 probes;
        it was 18 and 12).
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
- **Hands off meshes are never read** (2026-10-27, the user's rule: Hands
  off is how they protect dense, fragile or deliberately odd meshes that
  would crash UV checks):
  - Never scored, never pre-processed (Pre-process skips them), never
    diagnosed by the inspector.
  - The one thing anything asks is `handsoff_box`: `polyEvaluate
    -boundingBox2d -uvSetName` works the box out inside Maya, without
    changing the current UV set (0.1 s on 2M faces).
  - `HandsOffFinder` (Plan and Quick Plan) clips that box to each UDIM it
    covers, so other squares can share a tile it barely uses. After
    `HANDSOFF_BUDGET` (20 s) the rest go in `late` (`handsoff_late`), and
    their group's stored tiles (`LAYOUT_TILES`) are blocked whole.
  - Validate range-checks the box. The sheet and the viewer's Read Scene
    UVs draw the box. The old group packing takes its top row from it.
  - `_group_print` leaves them out.
  - Don't add `uv_footprints`, `mesh_fingerprint`, `_mesh_fn` UV reads,
    `uv_quality` or `oversplit` calls on them; `tests/test_squares.py`
    traps all of those.
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
- **Working window** (`WorkingDialog`, made by `Progress.update()` after
  0.5 s in the UI):
  - It's application-modal and calls `processEvents()`, so Maya never goes
    "Not responding" and Cancel works. Its Cancel raises `Cancelled`, the
    same as Esc.
  - `_tick()` sits in hot per-face / per-shell loops and polls the running
    Progress every 2,048 calls (main thread only).
  - Because events now run mid-step, every panel timer goes through
    `_guarded(timer, fn)`, which re-arms while `toolbox_busy()`. Nothing may
    edit the scene from an event during a step (`_refresh_uv_labels`
    checks too).
- **Background planning** (`PlanWorker`, `SmartUdimPanel.plan_live`):
  - Shells are read on the main thread (Working window). `make_plan` then
    runs on a `threading.Thread`; it's pure maths and makes no Maya calls.
  - `make_plan(on_attempt=...)` shows every density tried, throttled to
    about 12 a second, which is how the UV Viewer animates. Raising
    `Cancelled` from the hook stops a superseded search.
  - Signals connect to bound panel methods, so they're queued onto the
    main thread (a lambda might not be).
  - `_stop_worker()` joins the thread (one attempt, well under a second)
    before anything else plans from the same `collected`, since
    `free_around` caches on it.
  - Results whose `collected` is no longer the panel's are dropped.
  - Apply and Do It All stop the worker and plan synchronously.
- **UV Viewer** (`UVViewer`, `UVCanvas`):
  - `LayoutShell.hull` (convex hull about the centre) plus `placed_outline`
    gives the plan outlines, using the same maths as `_place_shell`.
  - `scene_shell_outlines` reads the scene; it's cached in `_OUTLINES` by
    fingerprint.
    - Density is only computed when asked for (the density colours). It
      needs every face's area, which made opening the viewer on a big
      scene crawl.
    - A shell's outline uses at most ~400 of its UVs.
    - Meshes with 300+ shells are drawn as boxes.
    - The viewer opens without reading the scene; that waits for *Read
      Scene UVs*.
- **UV Editor labels** (`build_uv_label_mesh`):
  - A helper mesh whose UVs spell out tile borders, numbers (3x5 pixel
    font, `_GLYPHS`) and section names in negative U. Its 3D size is 1e-4
    and it doesn't render.
  - It's built in NoUndo (the API create isn't undoable) and found again by
    its `unlokUdimLabels` tag attribute.
- **Unlok unwrapper** (`unlok_unwrap`, the `_uw_*` functions;
  `auto_unwrap(method=UNWRAP_METHODS[0])`, the panel default):
  - **Threads:** `_uw_read` reads plain lists on the main thread.
    `unlok_unwrap_data` is pure maths on a worker thread
    (`_uw_run_threaded`, which drives the Progress / Working window).
    `_uw_write` then writes back.
  - **Writing (undoable):** a planar projection gives one UV per vertex,
    then `polyMapCut` cuts the planned borders, then `write_uvs` sets the
    positions. If the result's UV ids don't match the plan (pinched
    vertices), it cuts every edge and `polyMapSew`s the rest instead.
  - **Per piece:**
    - `_uw_signature` + `_uw_same_shape` find copies (same topology in
      local vertex order, all triangle edge lengths in proportion) and copy
      their UVs.
    - `_uw_kind` sorts hard surface from organic.
    - `_uw_seams` makes the first cuts.
    - Each region becomes a disk: closed regions get a pelt cut
      (`_uw_far_pair` + `_uw_path_cut`), rings a cut between their rims,
      anything else is split by normals (`_uw_split`).
    - `_uw_flatten` tries, in order: planar projection, then hinge
      unfolding (`_uw_hinge`, exact on developable surfaces), then ARAP
      (`_uw_arap`, from the hinge result, then from Tutte), checked by
      `_uw_stretch` and `_uw_overlap`.
    - `_uw_sew` joins charts across sewable cuts with a 2D rigid fit (1%
      tolerance), rejecting joins that make boundaries cross.
    - `_uw_weld` merges sewn corners onto one position; `_uw_spread` lays
      the shells out side by side.
  - **Speed:**
    - `_uw_cg` and `_uw_mv` keep every loop in C: one `map` for all the
      products, row sums from `itertools.accumulate`.
    - CG stops at a relative tolerance and ARAP stops once nothing moves.
    - Big charts (over `multilevel_from`, 6,000 triangles) go through
      `_uw_multilevel`:
      - `_uw_coarsen` does half-edge collapses (shortest first, boundary
        kept, link condition, no flips) down to ~1,000 triangles.
      - ARAP runs on that coarse version; it gives up early if even the
        coarse version won't lie flat (the chart is then split).
      - Fill-in: coarse vertices are fixed, the boundary between them is
        placed by length (left free, it folds inward), and the rest is a
        uniform-Laplacian solve.
      - Two fine ARAP passes finish it.
    - The 19,200-face dome went 104 s -> 8 s this way. A closed smooth
      chart first tries one pelt; that fails the coarse check, then it's
      split in two.
    - `unfold3d_fallback` (off) would hand unflattenable charts to
      Unfold3D; otherwise they get their best projection ("rough").
  - **Tubes and pelts:**
    - `_uw_piece` remembers how a chart was opened (`hint`): a ring with
      its two rims' edge keys, or a pelt with its cut's end vertices.
    - `_uw_shape_start` turns the hint into a convex boundary: a rectangle
      split into rim A / cut / rim B / cut runs by length, or an ellipse.
      `_uw_tutte(bpos=)` fills it, then ARAP relaxes it. A circle start
      never converged for long bent tubes.
    - `_uw_multilevel(bpos=)` uses the same start on its coarse level.
  - **The user's recipe (2026-10-27): soften, cut the folds, sew box
    unfolds, else leave it cut, never cut through flat planes.**
    - **Hardness is ignored:** `_uw_seams` / `_uw_kind` go by fold angle
      only (`hard_angle`), as if every edge were softened first. Imports
      leave stray hard edges across flat walls and floors, and trusting
      them chopped those planes. (The old rule trusted hardness when it
      was the minority; a low-poly pipe's 45-degree sides are now cut and
      sewn back into one strip instead.)
    - **Slivers** (`_uw_prepare`): faces with next to no width against
      the mesh (2 x area <= 1e-4 x longest edge x mesh size: boolean
      leftovers) borrow the normal of the neighbour across their longest
      edge for fold angles (`fold_nrm`), so they can't fake a fold in a
      flat wall. A ratio test (area vs longest edge) also caught long thin
      bevel strips and broke soft planks; don't use one.
    - **Inside corners never sew** (`m["concave"]`: g's centre in front of
      f's plane). A box unfolds round its outside corners; an inside
      corner is where two parts meet (a leg under a rail, a wall on a
      floor), so legs never hang off a rail.
    - **Box unfolds only:** a join (main pass and flaps) must leave the
      shell filling `box_fill` (0.48; a cube's cross is 0.5; "compact":
      `sew_fill` 0.7) to 101% of its tightest box (`_tight_box_area`;
      over 100% means it lies on itself), and `_uw_tris_overlap` (points
      just inside each triangle tested against the other side; only up to
      4,000 triangles) finds no faces lying flush on each other.
    - **Caps shortcut only on real tubes:** `_uw_tube_split` checks that
      cutting the caps leaves only discs and rings (skipped over 5,000
      faces: a dome cost a second more and has no railings). A railing
      (rail plus legs: a sphere with many holes) or a wall with n-gons got
      the shortcut and came out as one windy, stretched shell.
    - `_uw_absorb_small` never merges across folds over 60 degrees: a
      window's reveal glued to its wall can't lie flat (it was relaxed).
    - **Square on** (`_uw_straighten`, in `_uw_spread`): each shell's
      tightest box goes along U and V, then a quarter turn puts the mesh's
      +Y (object space; `_uw_read` reads object points) up the tile, or a
      flat-lying piece's long side along U.
    - **Symmetric caps:** flaps of equal edge length go on the edge nearest
      the middle of the shell they join, so a plank's two end caps sit on
      one column of its strip.
    - **Writing at boolean seams** (`_uw_write`): Maya keeps one UV for
      faces on different sides of a non-manifold spot even with every edge
      cut, and `polyForceUV -unshare` does nothing (no
      `polySplitTextureUV` in 2024). `assign()` puts such a UV where the
      biggest faces (3D area) want it, so the wall keeps its shape and a
      hidden back-to-back face is squashed; the write counts as planned
      when the faces that lost out are under 2% of the mesh. First come
      used to win, and a house wall came out folded.
    - The plain-cut fallback tried first (cut every face, rejoin only
      near-rectangles when a boxy piece came out windy) chopped flat slabs
      with holes into 46 shells and was removed.
    - Tests: `tests/test_unlok_unwrap.py` (railing with inset legs, stray
      hard edges, holed slab, a turned boolean house, a post's caps).
  - **Caps** (layout quality, 2026-10-27; `tests/bench_uv_quality.py`
    scores it):
    - `_uw_poly_caps`: n-gon or pole-fan seeds grown over the flat cap.
      A seed counts if it has 6+ sides or covers 1% of the area; bevel
      corners leave 5-sided faces that aren't caps.
    - `_uw_tube_caps`: the smallest eigenvector of the normals' covariance
      (`_uw_sym_eigen`) is the axis, and faces within 45 degrees of it are
      caps. It's only used on closed regions: on a U-bend's or a wobbly
      tube's side it took bits of the side for caps.
    - Neither runs on a region that's already a ring.
    - Hard pieces try caps on the whole piece first. If found, only borders
      and caps are cut (not every bevel step), so planks, crates and posts
      become ring + caps.
  - **Straight tubes:** a ring chart is first tried as `_uw_tutte(bpos=
    rectangle, chord=True)` (weights 1 / length, no ARAP). It's kept if
    nothing flips and `good` >= 0.8. Relaxing bent pipes made bananas.
  - **Small bits:** `_uw_absorb_small` merges regions under 1.5% of the
    piece into the neighbour with the longest shared sewable cut.
  - **Flaps:** after the seam sewing, `_uw_sew` attaches compact small
    groups (under 20% of the biggest, aspect <= 6) along one edge, but
    only when the edges that line up afterwards (`_flap_contact`, all of
    them, not just the aligning one) make 30% of the flap's outline
    (`flap_contact`) and the shell stays a box unfold (above). The user
    found caps hung off a corner by one edge "cut in weird places". Crumbs (under 3% of the biggest, <= 9 outline
    edges: bevel corners) still go on by any edge; loose they shattered
    planks into 10 shells. Organic pieces sew flaps only (`sew="flaps"`).
  - **Defaults:** the engine still defaults to Unfold3D
    (`run_auto_uv(unwrapper=None)`), so old tests keep their behaviour.
- **Per-shell unfold:** `distorted_faces()` lists the faces of shells whose
  projection isn't clean. Auto UV's "find" stage unfolds just those
  (component lists to `u3dUnfold` / `_auto_seam`), or the whole mesh when
  some faces have no UVs.

## Maya API gotchas found so far
- **Maya keeps infinite and NaN UVs** (an import's junk, or anything written
  past float32's 3.4e38). `polyEvaluate -boundingBox2d` then returns inf,
  and `int(math.floor(inf))` raises "cannot convert float infinity to
  integer", which stopped Auto UV's packing, Lay Out Selected and the
  sheet on a Hands off mesh (2026-10-27). Everything that turns UV
  positions or sizes into tiles goes through `_finite` first:
  `handsoff_box` returns None for a broken box, `_read_shells` drops broken
  shells, `_uv_tile` and the lock path skip broken UVs, the unwrapper
  never writes non-finite UVs (that mesh fails instead), the per-mesh fit
  skips a mesh that throws, and the segment / overlap grids treat broken
  points as "crossing" rather than crash. `tests/test_squares.py` keeps a
  Hands off mesh with an infinite UV in the scene.
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

- Building a mesh undoably from Python: `setAttr -type polyFaces` only
  works while a file loads (live it errors or leaves an empty mesh), and
  `MFnMesh.create(parent=<empty mesh node>)` fails. What works: an
  undoable `polyPlane(ch=False)` seed, then `MFnMesh.createInPlace` on it
  (see Rope Lashing).

## Testing
- **Set `MAYA_DISABLE_CER=1`** for every mayapy / maya.exe test run. A Maya
  that crashes or gets killed otherwise pops Autodesk's error-report window
  on the user's screen (they share the machine). Always shut down cleanly
  (`maya.standalone.uninitialize()` before `os._exit`), and keep runs few:
  full suites plus the GUI smoke once before a push.
- **GUI Maya: also set `MAYA_SKIP_USERSETUP_PY=1`** and pass `-script` an
  absolute path. The user's Prism module (production tracking,
  `Documents/maya/2024/modules/Prism.mod`) opens a window at startup, and
  its modal "Prism Autosave" dialog blocks a scripted test. It's harmless:
  closing or skipping it is fine. Add `-log <file>` to see Maya's output.
Maya 2024 and 2025 are installed locally (no 2023). Run
`mayapy tests/test_toolbox.py`, `tests/test_smart_udim.py` and
`tests/test_bevel_resolver.py` for the engines (plus `tests/test_log_noise.py`,
`tests/test_rope_lashing.py` and `tests/test_thatch_roof.py`), and
`tests/bench_scatter.py [--profile]` for speed. The Bevel Resolver GUI test
is `tests/run_gui_bevel_resolver.mel` (screenshots in
`tests/_out/bevel_resolver`). For the UI, launch GUI Maya
with `tests/run_gui_smoke.mel` (see README) and check the screenshots in
the output folder. Thatch Roof's GUI test is `tests/run_gui_thatch_roof.mel`
(pictures of every shape and style in `tests/_out/thatch_roof`). A scripted
`cmds.redo()` sends no Redo event, so GUI tests call `_rebuild_stale()`.
