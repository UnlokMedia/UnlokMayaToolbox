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
- **Scale: decimetres** (the user, 2026-10-30: "everything in this toolbox
  needs to work with decimeters as the default"). 1 unit = 10 cm; Maya has
  no dm, so their scenes say "cm" (prefs at Maya's default). Anything that
  turns units into real sizes goes through `scene_m_per_unit()` (0.1 for
  "cm" via `WORKING_UNIT_M`, other units taken at their word): Smart UDIM's
  px/m, the default thatch box, Path Scatter's recipes and defaults (written
  in metres; `ps_in_scene_units` scales `PS_LENGTH_KEYS` in the panel only,
  the engine's `get_settings` fallback is untouched). Sizes relative to the
  input (rope, logs, thatch settings, blockers) need nothing. Saved sessions
  and `unlokUdimLayout` are stamped `m_per_unit`; unstamped ones were read
  with `legacy_m_per_unit()` (cm as cm) and their px/m are scaled once on
  load (`largest` dropped). `test_auto_uv.load_toolbox` pins
  `WORKING_UNIT_M = 0.01` (the older suites' numbers); `test_session.py`
  checks the decimetre default and the conversion.
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
- **Roof** (Modeling tab; called Thatch Roof until corrugated metal, so the
  code still says `thatch_*` / `THATCH_*` / `ThatchRoofPanel`: kept so old
  scenes, the `unlokThatchPresets` optionVar and the other sessions' work
  keep matching; user-facing text, undo names and new node names say Roof,
  `roofBox####` / `roofBlocker####`, while roof groups keep the covering
  in their name, `thatchRoof####` / `metalRoof####`). A roof from a box. Engine `ThatchField`
  (pure maths) -> `_th_grid` -> `_th_shell_mesh` / `_th_pieces_mesh` /
  `_th_panels_mesh` / `_th_fronds_mesh`, all in
  `thatch_build`; scene side `make_thatch_roof`, `update_thatch_roofs`,
  `rebuild_stale_thatch`, `bake_thatch`; panel `ThatchRoofPanel`.
- **Bushy palapa: Shag and Cap leaf width (2026-11-11).** The user wanted a
  bushy, shaggy palapa (photos of garden / beach palapas): volume, a neat
  under layer and two layers of loose fronds, light and dry, only the odd
  frond sticking out, never "wet hair" (leaves combed flat along the roof,
  tips curled). Workshopped in the viewport with a sun and depth-map
  shadows (flat default lighting hid all of it). What did it: `shag`
  (Shag): in `leaf_line` each leaf's tip stands off the roof in a straight
  lean, `shag * stiff * L * (0.04 + 0.16 h + 0.35 h^6)` times v^1.15, h a
  hash of where the leaf starts (most a little, the odd one a lot); `stiff`
  per caller: top fronds 1, under layer and bundles 0.6, caps 0.4, cards
  and folded butts 0. `cap_width` (Cap leaf width, 0 = Leaf width): the
  ridge / hip / apex cap leaves' width (`lwc`; `cap_gap` scales with it),
  so thin cap leaves blend the hips instead of a herringbone of wide ones.
  Plus Droop 0 (curled tips read as hair), sticks and ridge pole off.
  `hip_blend` (Hip blend, hipped ends; the user, after Arnold renders: hips
  read as a defined ridge, leaves bending out from it, "in the ref they're
  just pointing straight down the ridge like the rest"): the hip fan of
  headings closes to straight down the hip line (`1 - hb`, ramped in over
  0.6 leaf from the ridge: the full fan there closes the hip / ridge joint),
  `crest(blend=)` drops the cap lift 45% and scatters each start up to
  0.3 leaf off the crest, hip step x (1 - 0.35 hb). 0 = bit-identical.
  Preset "Palm: bushy palapa (shaggy)": Lift 2.5, Volume 1.6, Top fronds 1.5
  (Lift 3 / Volume 2 / Top 1.7 let sky through where hips meet the ridge
  and took 9.5 s), Messiness 0.35 (0.25 opened that joint again), Slant 0.1,
  Bend 0.15, Softness 0.7, Cap leaf width 0.012, Hip blend 1. Its Medium
  build is ~8.5 s; the test allows 10 s for it (others 6 s). Pictures: fast
  Arnold renders with flat colour shaders (scratchpad `arnold_pics.py`)
  showed far more than the viewport. That joint (x = +-0.93 on the 6 x 4
  test box) is the preset's weak spot for gaps. Known: on a gable the thin
  saddle leaves stand up as loops along the ridge (the preset is hipped).
- **Roof panel layout (UI pass, 2026-11-11).** Step 2's Duplicate / Make
  Box Again / Link / Unlink / Select Linked are in a folded "Copies and
  links" section (`links_sec`; the link status line stays outside it). The
  preset combo is grouped under disabled bold headings: Palm, Thatch,
  Metal, Tiles, Roof shape only, Yours (`_fill_presets` never leaves it on a
  heading). Palm controls: the old "More controls" dump is split into
  "Under layer (neat rows)" (`neat_sec`: Neatness, Leaf width, Leaf overlap,
  Shingle width), "Top layer (loose fronds)" (`top_sec`: Leaf width, Slant,
  Droop, Past the edges), "Leaflet shape and ageing" (Dried variation first),
  "Edges" (Gable fringe first), "Ridge, poles and ties" (`poles_sec`: leaf
  cap, ridge / hip / hold-down poles, lashings, sticks); "More controls"
  keeps Resolution, Leaf thickness, Curl variation and the straw-piece rows.
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
  - **Contours in one pass** (`_th_contours(F, G, ts)`): every course's
    crossings from one sweep of the grid's edges (bisect into the sorted
    t list). One `_th_contour` per course cost 2.4 s on a palm roof's 70
    courses; `_th_contour` is now a one-t wrapper.
  - **Palm Fronds** (`_th_fronds_mesh`; research summary in the side-session
    notes). The user's brief (2026-10-30, second round): a real two-layer
    roof that holds up without the underlay, seen from inside too, and NO
    gaps even with thin leaves. So:
    - **Under layer = tiles** (`tile_at`): attap shingles, a stick (tube)
      along the course with wide leaflets hanging from it, spaced
      `leaf_width * (1 - overlap)`, full width over their top 45%
      (`prof_tile`). Courses `_th_frond_courses`: 0.25 leaf apart /
      density, the first 0.4 leaf above the eave so the wide part reaches
      it; every other course shifted half a tile. Course spacing < the wide
      part + lateral overlap = covered everywhere. Stacking: offset
      `2 * stick radius + rise * d / leaf` (d from its stick), so the
      higher course is on top; sticks sit on the roof surface.
    - **Top layer** (`frond_at`): half fronds between the courses, thin
      leaflets (`top_leaf_width`, narrow-base `prof_top`) on a rachis tube,
      lifted over the under layer; skipped within 0.3 leaf of the ridge.
    - **Edges:** `_th_walk(fall=)` per layer: the under layer limp
      (`0.15 + 0.7 * edge_hang` a step off the eave), the top stiff (0.03).
      Past a gable verge (leaves carried past a course's end, ox / oz)
      `verge()` turns limp leaves down more the further out, and only sags
      stiff ones. Sticks are cut at the verge (they showed as a row of
      pegs). A leaf that walks off a gable verge sideways (`_th_walk` carries
      straight on off the shell; slanted top-layer leaflets did, one stiff
      horizontal spike per course, the user 2026-11-05), or a stiff one
      carried past it, bows down: `verge_bend` turns each step from the
      first point past the verge further down, lengths kept (just lowering
      the points stretched them into long strands); limp more, both scaled
      by `edge_hang`. Limp leaves carried past keep `verge()`.
    - **Edges controls** (the user, 2026-11-11: "reduce the hang, add
      variation / messiness, length variation"): panel section "Edges"
      (palm only) holds Edge droop (`edge_hang`) plus `edge_hang_var`,
      `edge_len_var`, `edge_mess`, `edge_limp` (all 0 = the old build).
      `edge_leaf(x, z, limp)` in `_th_fronds_mesh` gives each leaf (keyed
      to its base point, `_rand12(..., 7741)`; clumped `_th_noise` at half
      a leaf) its fall per step, a hang multiplier (also `verge()`), a
      hanging-length scale and a sideways swing (`_th_walk(swing=)`, off
      the edge only). Length: walk once (`info["off"]` = last on-roof
      point), then again with only the off-roof part scaled, so rows stay
      even. Limp top fronds: that share of the top layer falls like the
      under layer. **Ragged eaves now works on palm** (it did nothing):
      clumps of the edge hang up to 2.2x further. Cards skip the per-leaf
      part (`leaf_line(edge=False)`: columns must stay together).
      `THATCH_VERSION` 12.
    - **Gable edge** (`verge_a` / `verge_b`, `THATCH_VERGES` Hanging /
      Flush; own keys, shown only on a Gable end; the user, 2026-11-02:
      gable leaves hung like curtains and clipped a brick wall). Flush
      (`F.flush`) drops that end from `gables` (no carry past the line end,
      no droop, no fringe, no shell fringe tips, no ridge-cap carry, no
      frame run-on), drops leaves starting past it, trims sticks / rachis,
      and `_th_flush_cut` moves every straw / sticks / underlay / frame
      point past the verge back onto its plane (all thatch styles).
      Overhang sets where the cut is. Metal ignores it.
    - **Cap leaves** (`crest()` on hips and the apex, `saddle()` on the
      ridge; the user 2026-11-04: on a messy roof the caps stayed neat and
      clumped, leaves clipping through each other). Laid in handfuls (2 to
      `cap_hand`, more when messy) along the crest: each leaf `cap_step`
      above the one before (a hip's fan of headings in fractions of a
      step), so neighbours always differ in height; a reset at each new
      handful. A leaf's top point moved onto the crest uses its own lift
      (with one shared `top` they all met there). The tips come down half
      their extra. Messiness: turn, length, twist, droop, width, broken
      leaves, strays laid over a handful's top; spacing `cap_gap` (closer
      with mess) keeps turned leaves covering. A hip's `pole()` sits at
      the cap's mean height, a little bedded in.
    - **Ridge poles** (`ridge_poles`, the user 2026-11-02: the poles looked
      like they floated on the cap, and turning the cap off to lose them
      opened the ridge): `pole()` checks `ridge_poles`, not `sticks` or the
      cap leaves, so off drops only the poles (the straw is identical).
      `thatch_data` and an older user preset without the key follow
      `sticks`, which used to switch them.
      `THATCH_VERSION` 6 (both changes): older roofs show Upgrade, which
      rebuilds them with the new cap and the poles following their Sticks.
    - **Cap arch** (the user 2026-11-05: the backs of the ridge cap leaves
      clipped through each other; curl them down a lot). `emit(arch=)`
      adds curl (edges down) to every cap leaf. Arched leaves are narrower
      over the roof: `cap_gap` is 0.85 of the old spacing. Less twist on
      cap leaves. `THATCH_VERSION` 7 (with the verge droop).
    - **Ridge saddle** (`saddle()`, the user 2026-11-09: the messy ridge
      got really ugly). The 2026-11-05 fold (each side's leaves ending in
      three stiff rows mirrored over the crest, the other side's tucked
      under them) made a sawtooth of little tents along the crest, its
      leaves had to pass through the far side's cap, and the pole floated:
      the mesher's crook took it sideways off the crest, over the lower
      slope. Now each ridge leaf is one leaf draped over: `leaf_line` down
      the tip's side (Lt) and down the far side (Lb, the cut base end,
      shorter), joined over the crest. Second round, same day (poles and
      frame off: "along the tops of ridges ... it becomes like too
      straight. And like, you start to see jankiness": a ruler-straight
      crest of identical staple-shaped bends; the first join was a
      quadratic lifted with sin^2, which kinked into a corner each side):
      now a cubic from B (far side) to A (tip side), tangent to both
      slopes, its reach k along them solved so its middle sits at
      `top + 0.35 * extra + hv` over the crest (clamped 0.15..0.9 of
      |AB|). Each leaf's bend reach `rf` varies (0.75..1.35x) and is lop-
      sided (`lop`, up to +-0.35 with Messiness: folded off the crest).
      The crest height wanders: `hv` = heave (rise x (0.15 + 0.45 mess))
      x two octaves of `_th_noise` along x at 0.09 span (clumps) + 0.2
      per leaf, faded out over half of each side (`layer_of`). More heave
      (0.25 + 0.75) arched leaves up with holes under them. Not scaled by
      `ridge_poles`: the leaves must be identical with poles on or off
      (the 2026-11-02 rule, tested), so the pole follows the crest. Each
      leaf's `rest` height is the bend's height where it crosses the
      crest line (a lop-sided bend's top is off to one side), and the
      bend has a row every ~0.6 rp (8..24 rows): with a fixed 8, no row
      landed under the pole and it read as bridging up to 0.9 rp. The cut base end tapers
      (0.3 -> 1 width over ~7% of the leaf), width down to -15% x mess
      (never wider: `uk_tile` maps the full width to u 0..0.85, and wider
      leaves spilled into a 4th stack tile), a small
      roll over the bend. `emit(flat=)` scales each row's curl: 0.5 over
      the bend (0.15, the first round, read as flat staples), back to
      full 2 `rf` away. Which side the tip goes, x jitter, turn (8 + 12
      mess degrees) and both lengths are random (Messiness), so neither
      edge is a ruled line; one set of leaves, no lap or interleave, so
      nothing clips. `THATCH_VERSION` 9 for this round.
      V by arc length (`vrow`, kept through a dried leaf's crumple:
      `_th_dry_leaf(coil=False)` used to reset it). Returns each leaf's
      crest height; `pole(path, rest)` lies on them (Gaussian mean pulled
      0.4 towards the local max, + 0.6 rp: pressed in a little), straight
      in the mesher (`wob` 0, true radius `rs` 1.0) with its own gentle
      crook (`frame_at`) so ties every ~0.18 span (4-6 turns of 0.12 rp,
      at 0.92 rp + rt: tight on the six-sided pole's faces, ends on down
      into the cap) stay tight. Ties go with the poles (`poles`: the
      frame's mesh, else sticks), so Ridge and hip poles off still leaves
      the sticks mesh exactly as it was. Members of kind "tie" get a ring
      at every path point and no run-on ends. `THATCH_VERSION` 8.
    - **Straight wood** (the user, 2026-11-10: sticks and poles "super
      bendy and weird", no structure, hip poles clipping through each
      other at the ridge; then: ropes only as an option, off by default,
      "more just the shape and position of the poles / frames, avoiding
      weird bent wood"). Course lines come from `_th_course_lines` (a
      drop-in for `_th_contours`, cone excepted): each course on the roof's
      planes at `_th_plane_height` (the height before sag), straight down
      each face, turning only at the hip (`_th_line_corners`); contours
      wandered ~4-12 cm in plan with lumps, warp and ridge sag and curved
      round rounded hips. Used for frond courses and battens (panels still
      use contours). Tile sticks, course poles and battens are split at the
      hip corners (`_th_split_at`, trimmed short of each other; a loop's
      first and last pieces are one member); a rachis over a corner keeps
      its longer side. Ridge / hip poles (`pole()`) are fitted by
      `_th_stiff` (a quadratic through what's under them plus a Gaussian-
      smoothed leftover over `bend` = 0.12 span, lifted straight up by 0.5 x
      the 90th-percentile residual; no crook). Hip poles start against
      the ridge pole's side (`butt`: 2.05 rp off its axis, its height
      there), and the ridge pole runs on 2.05 rp / pitch ratio + 2.5 rp past
      each hip joint. Mesher crook wavelength is now 0.3-0.6 of the span (it
      was 1.2-2 scene units: zigzag rafters in decimetre scenes).
      **Lashings** (`lashings`, default False, a look key; panel checkbox
      "Vine ties (lashings)"): ridge / hip ties (`band()`), the bands at
      the hip joints and the bundle ties; off, there are none. Old palm
      sticks bent up to 0.7 of their length round hips; now under 0.02.
      **Hip poles** (`hip_poles`, default False, a look key: real palm hips
      are mostly closed with leaves alone; the ridge pole holding the cap
      down is the common one): `ridge_poles` is now the ridge pole only.
      `thatch_data` / an older user preset without the key follow
      `ridge_poles`; a stored roof without `lashings` gets True, so old roofs
      keep their look. Palm presets (accurate defaults, the user asked):
      battens Every course, rafters 0.11-0.13 span (thatch rafters are
      30-60 cm apart), denser leaves (nipa / fale 1.4, palapa 1.3), beach
      shack Poles frame (its density stays 0.9: at 1.0 its sticks crossed
      the leaves 17.6% of edges, the test's limit is 14%). Battens skip a
      ridge course on the plane inside the rounded crest (|z| < `F.rr` +
      depth + rb): the straight lines sit nearer the crest than the old
      contours and crossed the underlay's fold at Volume 2. `THATCH_VERSION` 11.
      **Hold-down poles** (`hold_poles`, pairs along the ridge, default 0,
      a look key; the user's project, 2026-11-10: old jungle shanties in
      Brazil, palm roofs and corrugated ones, "accuracy and some
      interesting details"): `hold_down()` at the end of `_th_fronds_mesh`
      lays straight poles over the finished leaves, straight down each side
      slope (none on hip ends / a cone; a lean-to's from its top edge), the
      pair's tops crossing side by side just past the crest, over the ridge
      pole, 0.1-0.35 leaf past the eave, yawed up to 5 deg (messy). Height:
      the leaf points' tops on a plan grid (0.5 r, 3x3 cells) + (k -
      `HOLD_PRESS`) r, k = sqrt(1 + slope^2): a sloped pole's underside is
      k r straight under its axis (taken as r at first: on the steep test
      box leaves pressed "under" it stayed inside it; the press uses k too); `_th_stiff(rise=0, bend=HOLD_BEND span)` on the points away from
      the crest (within rp + 3 r of it the cap leaves arch up: on a steep
      test box they held the pole 6 r over the ridge pole), then down to the
      `HOLD_KEEP` (0.5) quantile of the leaves under it (soft leaves give;
      they are pressed flat after), the top end moved up or down onto the
      ridge pole and eased out over `HOLD_REACH` span: its target is the
      ridge pole's circle (`sqrt((rp + r)^2 - dz^2)` over its axis), so the
      axes end up rp + r apart (test: the axis distance, not the height
      over the ridge pole's top, which a sloped pole touching off-centre
      exceeds by (rp + r)(sqrt(1 + slope^2) - 1)). Then
      the leaf points under each pole are pressed down onto its underside
      (circle), eased back within a radius. Measured in 3D (test and
      scratchpad `holdtest3.py`: leaf points' distance to the pole's axis):
      none inside a pole, nearest leaf median 0.05-0.25 r off its surface,
      p90 ~1.4 r (it bridges dips), on a 6 x 4 m and a steep 6 x 4 x 3
      box (curled tips poked 6.5 r through before the press).
      Tried and worse: resting it rigidly on two supports of the upper hull
      (floated ~1-2 r between bumps), a ramp lift pivoting on the foot (the
      eave end sank 1.3-2 r). Preset "Palm: Amazon jungle shack" (riverside
      / caboclo shanty: woven panels on a pole frame, mixed fresh and old
      leaves `dried_var` 0.9, 3 pairs of hold-down poles; overhang stays 0,
      the box is the roof).
      **Wording** (the user: technical names are fine, but you shouldn't
      have to toggle things to see what they do): a collapsed "What the
      words mean" section in step 3 (ridge, eaves, gable / verge, hip,
      course, rafters, battens, purlins, ridge beam / wall plate, rachis,
      underlay, span); palm labels in plain words (Shingle width, Loose top
      fronds, Edge droop, Top fronds past edges, Butt lift, ...) and
      tooltips that say what part of the roof a setting changes and when it
      applies (Hip ends only, Gable ends only).
    - **Volume** (`_th_volume(s)`, after `_th_detail` in `thatch_build`;
      the user 2026-11-09: roofs look flimsy, "puff them out ... with an
      accurate layering", the wood too). `volume` 0.25..4 (a look key):
      thickness x v, `lift` x v (not palm: `_th_frond_rise` follows the
      thickness already), density, `rafter_size`, `batten_size` x sqrt(v),
      and `s["_wood"]` = sqrt(v) scales the fronds' stick radius `rs` and
      pole radius `rp`. The frame hangs at `1.02 F.T` under a shell, so
      it moves down with the thickness. `THATCH_VERSION` 10.
    - **Wood vs thatch** (same day: "Less clipping, more logic to it";
      `probe_wood`-style metric: share of wood mesh edges crossing the
      leaves, beach shack 18% -> ~12.7%, straw underlay 1.4% -> 0.5%):
      the top layer is laid eaves up, so `rach_lay` notes each rachis on a
      plan grid (written into the 3x3 neighbours, read as one cell) and
      later leaflets get `leaf_line(floor=rach_floor)`; `leaf_lay` notes
      each frond's leaflets (after its own rachis) and the next rachis
      lies on them (`along(extra=bed)`, bed capped at 2 rr0 and smoothed:
      uncapped it climbed frond on frond and kinked), its leaflets lifted
      with it near their roots. Leaflets over sticks: `emit(flat=)` takes
      `over_wood` (less curl near the root). Sticks have no run-on ends
      (they poked into the next tile); sticks, rachis, poles and ties no up
      crook, rafters/poles only sag (`0.5 (w2 - env)`, never up). Frame:
      `d_batten = depth + 1.1 rb`, `d_rafter = depth + 2.2 rb + 1.1 rr`
      (room for +-10% member radius), no batten points where the base
      normal's y > `0.5 (1 + 1/hypot(1, ms))` (the rounded crest; contour
      scraps of the top course lay over the rafters' tops, through the
      underlay; not for metal `_purlins`), and the underlay's batten ribs
      off when there is a real frame. Common rafters drop their top points
      over the rounded crest and past the ridge line (`zs * z < 0`: walked
      down from the crest at depth, the two sides' rafters crossed in an X
      and their tops came out through the far slope's underlay, worse at
      Volume 2); the ridge beam goes 1.1 (rr + rbeam) under the lowest
      rafter top within a rafter gap (`tops`). The shell's underside
      (`_th_shell_mesh` inner) turns more straight down over a rounded
      crest (`up` 1 -> 5 as the normal stands up past the slope's): halfway
      it folded in under the crest. Rachis radius `rr0` scales with
      `_wood` too. A slanted / bowed rachis was tried and dropped (the
      user: looked odd; keep straight sticks).
    - **Ridge slits** (dense sky-ray check, beach shack: 19 rays saw the
      sky across the crest at 121x121): cap leaves' x jitter is capped so
      two never sit more than ~0.6 lw apart (`jit`), and each handful of
      cap leaves turns one way together (`lean`, 0.7 of the turn; strays
      their own way): turned apart, neighbours opened slits. Now 1.
    - **Bundles** (the user, 2026-11-09: jungle roofs use "one stick per
      level ... bunched bits of fronds"): `frond_layout` Shingles / Bundles
      (`THATCH_FROND_LAYOUTS`), `bundle_width` (x span), preset "Palm:
      jungle hut (tied bundles)". Courses 0.42 ll apart (Shingles 0.25);
      `_th_frame_courses` returns [] (no battens), `_th_frame_members`
      drops the batten depth from `d_rafter`. In `_th_fronds_mesh`:
      `bundle_at` (a tuft: roots over 0.4 w, fanning only 0.3 w, middle
      leaves longest; stacked `neck` deep through the tie; each leaf's butt
      folded back up the slope over the pole, `layer_b`), `course_pole`
      (a pole at rb_ along the course, split at > 25 deg turns, at most
      0.06 ll past a gable verge, `run` False so the mesher doesn't run it
      on), `tie_round` (2-3 vine turns round pole + neck, kind "tie", in
      `poles`; light: 9 points a turn, `sides` 4 -> `profile`: thousands
      of them, and 3-4 turns of 15 points, 6-8 sides made 246k frame verts
      and 1.5 s of a 3.3 s build, now 77k and 2.5 s). Bundle spacing `w (0.85 - 0.45 overlap)`: wider (1.0 -)
      let 8-10 of 961 sky rays through. No rachis over bundles.
    - **Shingles' stems:** only top fronds with `r[9] < 0.33` get a rachis
      (and `sticks` for their leaflets' bed); one on every course read as
      a ladder (the user asked if real roofs have that many sticks).
    - **Sticks mesh** (the user: the horizontal tubes are wood, not leaf):
      sticks, rachis and (without a frame) poles are the roof's `sticks`
      part (`woodStick`, `THATCH_VERSION` 5), `F.stick_mesh` from
      `_th_frame_mesh(uv_strip=u_of, strip=(0, 0.8, 0.9, 0.08))`: stacked
      UVs, skin round u 0..0.8, caps at 0.9. A roof from before it (no part
      yet) gets them joined back into the straw (`_th_join`) until Upgrade.
    - **One roof, no shared UV space** (the user, 2026-11-02: "this tool
      shouldn't output under one roof any overlapping UVs, other than ...
      stacked"): `_roof_udims` (end of `thatch_build`, metal too) moves
      each part into the tiles after the previous parts', in
      `ROOF_UDIM_ORDER` (straw / sheets, sticks, underlay, trim, fixings,
      frame), from the roof's **Start UDIM** (`udim`, default 1001: an own
      key, a look key so shape presets keep it, skipped by saved presets);
      a part that won't fit before the 10th column goes up a row (above
      everything so far, from the start's column if it fits). `out["udims"]`
      = {part: [UDIM numbers]}. Only a part's own stacked variations
      overlap. The UVs section shows for every style now.
    - **Single-sided metal** (`m_single`): `_MtMesh.single` makes
      `_mt_solid` emit the top surface only (empty "bot" / "walls" UV
      ranges) for sheets and trim; All laid out skips the underside tiles,
      `_mt_pack_trim` skips empty shells. Laps keep the Thickness gap.
    - **Grouping** (the user asked): roofs and boxes are found by attribute
      / uuid, and meshes are written through the shape's inclusive matrix,
      so the roof group and the box can live in any group. The part meshes
      must stay direct children of their roof group (`thatch_parts`).
    - **Make Box Again** (`remake_thatch_boxes`, the panel button; the user
      keeps boxes out of a publish, and their sanity check deletes all
      history, which roofs survive): a roof whose box is gone keeps its
      `box_frame`; a new polyCube is placed from its 8 corners (axes from
      the averaged edges, mirrored when `flip`; a non-box mesh's frame
      gives a plain box, ridge "Z" turned) and relinked, one UndoChunk.
    - **Caps** (`crest`): leaves from a crest point down each side with a
      fixed plan heading (`_th_walk(heading=)`: round a hip's apex the
      fall line swings along the ridge and cap leaves slid off down the
      hip, leaving a hole), the first point moved onto the crest so both
      sides meet; offset from `1.15 rise` at the crest down to the courses'
      height at the tip; long and short leaves in turn; random turn kept
      under ~8 degrees (more opened gaps). Ridge: heading +-z from just off
      the crest. Hips: a fan of 5 headings from straight down the side to
      straight down the end along the hip line (plane formula). Cone: a
      radial ring at the apex, 0.9 leaf long. Poles (tubes) along ridge and
      hips. Lean-to: no cap, a last course at the top.
    - **Contours for courses** (`_th_contours`): a ridge's two slopes are
      one loop (key `along` on +z, `1e6 - along` on -z), joined only round
      a hipped end (`joins`), split at gables; a closed loop starts mid +z
      side (`_th_closed`), so course lines wrap the hips (the old z-sign
      split left an open seam down the middle of each hip end). Only
      closed loops and gable ends carry tiles past a line end.
    - Each leaflet walks the roof on its own (interpolating between a
      frond's column walks made chords across hips). Random values are
      keyed to (course, line, tile, leaflet), never segment counts.
    - **Gap test:** `tests/test_thatch_roof.py` casts 961 rays up from
      inside over the footprint (ridge line and hip-end middles included)
      per palm preset; all must hit the straw mesh.
  - **Detail** (`_th_detail` -> settings, level, underlay grid res):
    Proxy = no straw, underlay forced on, grid <= 48 (0.1 s); Rough = Cards /
    Planes, 2 segments, underlay grid x0.6; High / Hero = segments and the
    underlay's own grid x1.5 / x2 (`thatch_build` builds a second grid
    for it). It's a look key, so shape presets keep it and look presets
    don't name it.
  - **Underlay relief** (`_th_relief`, `_th_underlay_relief`, all styles):
    per grid point an outer offset `step * ((1 - f) * smooth(f / e) + bias)`
    with f the fraction through the course (`(t - t0) / dt`, matching the
    pieces' / panels' / fronds' courses) shifted by pointed tips (triangle
    wave along `PS`, staggered 0.37 a course, so it's continuous) and a
    slow wander, plus grain noise down the slope; ribs (battens) on the
    ceiling side at each course line. Palm steps sit just under the
    lowest leaf layer (`0.85 * rise * sp / leaf`, inset 0.12 rise). The
    shell also gets a fringe of tips at eaves and gable verges (outer and
    inner moved together, so it stays closed) and, under fronds, thins to
    20% within 0.6 leaf of those edges (a full-thickness slab read as a
    plank at the eave). Same topology as the plain shell; relief 0 = old.
  - **Blockers** (the user, 2026-10-30: "add a blocker cube ... the fronds
    react around it", dynamic, not heavy):
    - Stored on the roof's data: `blockers` (uuids) and `blocker_boxes`
      (world boxes {"id", "c", "u", "h"} at the last build: `_th_blocker_box`
      = a mesh's own bbox through its matrix, else the world bbox).
      `thatch_state` / `_th_same_state` compare frame + boxes, so
      `thatch_box_moved` and the panel's poll / attributeChange jobs also
      catch blockers moving, scaling or being deleted (or an undone Add).
      Linking (`link_thatch_blockers`) is a live edit (NoUndo) like the
      settings; `create_thatch_blocker` is an UndoChunk (red wireframe box
      across the + end, `THATCH_BLOCKER_ATTR`) then links outside it.
    - Engine: `thatch_build(..., blockers)` maps each world box's 8 corners
      into roof space (`_th_to_roof`: affine for a plain frame, Newton
      through the corners' trilinear lattice otherwise) and refits an
      orthonormal box (`F.blockers`). `_th_drape` walks a leaf's
      centreline: a step that would enter a box (grown by `F.block_gap`,
      half a leaf width) stops where it enters (slab test) and the rest of
      its length slides along that face (head-on: along the leaf's
      heading), normals = the face's, so the leaf lies flat; steps that
      miss are kept (free hanging). A leaf starting inside returns None
      (dropped: pushing it out of the nearest face popped leaves out of
      the far side of walls); panels and cards push instead (else whole
      panels vanished). Tubes keep their longest run outside. Shells:
      `_th_push` per point. Cap leaves' crest point is pushed too (it's
      moved after the drape). Bbox early-out per leaf.
    - Testing note: from about 13:30 that day, `mayapy` (2024 and 2025)
      crashed at startup when launched from Claude's shell (access violation
      in `TrunTimeCommandManager::load`), even on an empty script, while
      `mayabatch.exe -script` worked. Run the headless tests in mayabatch
      with a stand-in `maya.standalone` if that happens again.
  - **Frame** (the user, 2026-10-30: the sticks looked janky; "better
    logic for how it would actually be built"; standing rule: good UVs,
    optimised, a Sub-D toggle with support loops / quad caps):
    - Third roof part `frame` (`THATCH_FRAME_MATERIAL` "woodFrame", seed
      plane in `make_thatch_roof`; roofs made earlier have none and the
      panel says so via `report["no_frame"]`).
    - Layout `_th_frame_members(F, G, s, depth)`: rafters walk down the roof
      on a fixed plan heading from the crest (side faces past a hip's ridge
      end start on the hip line: jacks), hip-end jacks start on the hip line
      heading +-x, hip rafters follow the plane-formula hip line, cone
      rafters radial; ridge beam under the rafters' tops; battens on
      `_th_contours` at `_th_frame_courses` (palm: the frond courses; panels:
      panel courses; straw: 7% of the span) plus one at the eave; wall plates
      at |z| = W (and full hips' ends, a cone's ellipse). Depths below the
      roof surface: batten tops at `depth` (the underlay / shell thickness,
      else 0 for palm), rafters under battens, beam under rafters.
    - Mesher `_th_frame_mesh`: stations every ~6% of the span (bamboo nodes
      plus a holding ring either side), crookedness = low-frequency noise
      sideways (0.3x towards the roof; not on battens: crooked laths kinked
      round hips), run-on ends (rafters only at the eave: run on at the top
      they came up through the cap; run-on direction from 3 points back, a
      short last step made hooks; not into blockers). Vertices shared round
      a member, UVs split at a seam facing the thatch; skin u decreasing
      round it so UVs are upright; caps: start j-increasing, end reversed,
      UV mirror +1 / -1 (the other way round mirrored them). Sawn without
      Sub-D: a vertex strip per face (hard edges). Sub-D: 8-point profiles
      (sawn corners split by support edges), holding rings near the ends,
      caps = inset ring + 4 quads. `_th_pack` packs skins and caps.
      `sin(pi * u) ** 0.5` with u a hair over 1 gave complex numbers:
      clamp before powers.
    - **Part switches** (the user, 2026-11-11: "control for toggling
      different parts, instead of just the entire frame"): `frame_rafters`
      (rafters + jacks), `frame_hips`, `frame_beam`, `frame_battens`
      (battens / metal purlins), `wall_plates`; all default True, look
      keys, CheckFields under the Frame section (Hip rafters hidden on
      gable-gable / cone, Ridge beam only on Ridge). The layout is always
      worked out in full; `add()` drops a switched-off kind but still
      numbers it (`rid`), and `_th_frame_mesh` draws each member's
      randomness from `rid` (extras after the frame's own: palm poles,
      fascias, numbered on from `rids`), so the parts left on are exactly
      unmoved (test "frame parts"). All off and no extras: no frame mesh.
    - **Straight members** (2026-11-11 check, `straight.py`-style bow =
      worst distance off the end-to-end line / length): `add()` cuts
      rafter / jack / hip / batten ends turning > 12 deg off the line of
      the member's middle half (corner jacks bent 27% where the roof
      rounds off at an eave corner; hip-end battens turning over the hip
      crest), and a down-the-roof member that climbs at first (a short
      lean-to's two hipped ends meet below its top: hips and jacks crossed
      it) starts at its top. Plates: the constant coordinate set to the
      median (the corner normal pushed their ends out). Now <= 1.6% bow
      (the roof's own sag) except 4% on a double-hipped lean-to. Gable ends:
      battens and the ridge beam stop at the outer rafter (x0 / x1 -+ rr),
      no run-on there (they came through the hanging verge fronds: Amazon
      3% -> 0.3%). Hip rafters sit 0.35 rr deeper (1.3x thick: through a
      bundle roof's underlay, 9% of their edges). Left: bundle course poles
      and palm poles lie in / on the leaves by design; a cone's rafters
      touch its underlay at the apex (0.2%).
  - **2026-10-30, fourth round** (the user): overhang 0 by default (box =
    roof; every preset too). Frame samples `_th_sample_base` (grid P / N:
    sag, lumps, warp, ridge sag; not the lips / cap). `battens`
    (`THATCH_BATTENS`: every course / 2nd / 3rd / per level at
    `_th_level_bottoms`). Palm courses `_th_palm_courses`: restart at each
    level's step (+0.25 dt; further up a slanting view saw sky through the
    step). Wall plates sit 2.5 plate radii in from the wall line, level at
    the lowest rafter they carry (centred on the wall line they sank into
    the house with no overhang). Fronds' `tube()` hands sticks / rachis /
    poles to `_th_frame_mesh(..., uv_strip=u_of)` (now their own mesh,
    see Sticks mesh), poles to `F.frame_extra` -> the frame mesh. 3D Leaflets:
    `leaf_thickness` makes each leaflet a closed solid in `emit` (underside
    mirrored on the same UVs, side / tip / base walls on u 0.86..0.87).
    **Upgrade** (`THATCH_VERSION`, `thatch_needs_upgrade`,
    `upgrade_thatch_roofs`): adds missing parts (`THATCH_PART_MATERIALS`,
    `_th_make_part`) in an UndoChunk, stamps the version, rebuilds (old
    settings kept, new keys default via `thatch_settings_only`). Bump
    `THATCH_VERSION` whenever a roof gains a part or a setting needs a
    rebuild. Panel step 4 is built from a layout table (main / More
    controls / Underlay / Frame / UV stacks); `_update_rows` shows rows per
    style. Not done yet (the user's "desirable"): a quick roof-shape builder
    (click base points and peaks -> box, pitch, gable / hip ends).
  - **Curl** (`curl`, `curl_var`; the user: bend the reeds widthways):
    `_th_curl_points(c, h, wide)` wraps a half width round a circle (arc
    length kept, so u is unchanged; c > 0 arches, c < 0 cups), used by palm
    `emit` (columns: `s["_cross"]` from `_th_detail`, 3 / 5 at High+; per
    leaf curl from a hash of its base point) and straw planes (`r[10]`);
    leaf panels add a parabolic arch across the panel. Planes / panels
    underlays are sunk by their relief step (their courses poked through
    cupped planes). Frame mesh suffix `_GES` with Sub-D, `_GEP` without
    (`_th_suffix` in `_th_write`; tests must re-fetch the part's name).
    `git rebase` re-checks files out with CRLF here: patch scripts must
    normalise line endings (read, replace CRLF -> LF, write back).
  - **Dried** (`dried`, `dried_var`; the user: Messiness 2 still too smooth,
    wants leaflets dried, shrunk, coiled, crumpled): `_th_leaf_dry(s, r)`
    per leaflet (0..2, variation like Curl's); `_th_dry_leaf(F, Q, Nn, half,
    twist, e, r, cross, coil)` folds the centreline 1-3 times (Rodrigues
    turns up / sideways, never into the roof; smaller near the base), then
    rebuilds the tip end as a coil (mostly hooks: theta ~ r^2; extra rows at
    45 / 30 degrees), returns per-row V, extra curl (edges rolled in) and a
    crumple (amp + phases, continuous in v so Detail keeps the shape).
    `emit(..., dry=(e, randoms, coil))`; only `frond_at` (top layer) coils
    and shrinks (L x (1 - 0.18e), width x max(0.4, 1 - 0.3e), more dropped /
    torn leaflets); caps get half, crumple + twist only (`coil=False`), the
    under layer none (the no-gap guarantee). Cards ignore it. Points are
    pushed out of blockers. Its randoms come from a second `_rand12` keyed
    `key[0] * 7 + 4`, so Dried 0 builds exactly what it did before.
    Pictures: run Maya from an empty folder (`scratchpad/run_cwd`); the
    scratchpad's own .py files shadowed Maya's Python modules ("Invalid
    Python Environment").
  - **Leaflet shape** (`THATCH_LEAF_SHAPE_KEYS`: `crinkle`, `crinkle_var`,
    `leaf_twist`, `leaf_twist_var`, `width_var`, `width_wobble`,
    `bent_tips`, `bent_var`; the user, 2026-11-11: fronds too neat and
    smooth, wanted controls to dial in realism). Panel section "Leaflet
    shape" (palm, not Cards). `_th_leaf_shape_settings` is None when all
    are 0, so `emit` skips it and the roof builds exactly as before (no
    `THATCH_VERSION` bump: defaults are 0). `emit(kind=)` + `_th_leaf_shape`
    with randoms `_rand12(seed, h01 hash of the leaf's base, 7919, 61)`:
    "top" (loose fronds, gable fringe) gets everything; "cap" (crest,
    saddle) gentler, "under" (shingles, bundles, butts) no width / twist
    at all (narrowing even the taper let the sky through the beach
    shack's thin under layer, which is borderline anyway: seeds 2, 4, 5
    leak a ray with no shape at all); caps and under crinkle only upwards and
    bend tips sideways in the roof's plane (no clipping into the course
    above, no-gap rule kept). Width only narrows and is clamped to
    0.425 / uk (u 0..0.85). Crinkle resamples rows (top: + rows x crinkle
    up to 1.5x; others half) and needs columns only on the top layer. Bent
    tip = a two-row crease (half the angle at each), lengths kept. Palm
    presets carry modest values (+20-50% verts). Pictures:
    `tests/run_gui_leaf_shape_pics.mel` (`tests/_out/leaf_shape_pics`;
    `UNLOK_PIC_SET=sections` for one per cross-section).
    **Cross-section** (`leaf_section`, `THATCH_LEAF_SECTIONS` As is /
    Rolled / Creased / Mixed, `section_amount`, `section_var`; same day:
    "thinner curled tubes, or flatter with a pinch down the middle, or as
    they are now"): `_th_leaf_section` (randoms key 7919, 62). Rolled
    replaces the curl with a cup (edges up, -(0.6 + 1.3 a)), 0.3 a
    narrower, 5 columns; Creased flattens the curl and lifts the edges
    (`sec[2] * h * |x|^0.8`, a V at the midrib). Caps only cup to -0.35
    (half way opened the jungle hut's ridge at Rolled 1.5), the under
    layer to -0.25; both crease 0.35 a (edges up, nothing narrower).
    As is (the default) never touches a leaf, whatever the amount.
  - **Quick roof shape** (`thatch_shape_from_points`, pure maths;
    `create_thatch_box_from_points`, `thatch_roof_from_points` (one
    UndoChunk), `thatch_selected_points`, `ThatchPointPicker`): points split
    by height (within 20% of the range of the lowest = eaves, of the
    highest = peaks). Footprint: `_th_min_rect` (hull + calipers); ridge
    axis = the peaks' principal direction snapped to the rectangle's axes
    (one apex: the long side); lean-to when all peaks are past 0.6 W on one
    side (a is flipped so the high side is -z); cone for 5+ eave points
    within 12% of a circle. The box is a polyCube with its transform = (a,
    up, c, origin) and its 8 vertices placed in object space (index ix + 2
    iy + 4 iz, `_th_box_corners` sorts the same way): bottom = the 4 eave
    points (else the rectangle), top = above them at the ridge's height at
    each end, shifted across (and along, for two hips) so the ridge passes
    through the peaks; ridge "X". Hip pitch = W / d (lean-to 2W / d), d the
    ridge end's distance from the box end; gable when d < 8% of L. Picker:
    a draggerContext + `_ThatchPickKeys`, an app event filter (Enter, Esc;
    Ctrl+Z / Backspace / Delete = remove last, Ctrl+Y / Ctrl+Shift+Z = put
    back; queued on a timer, ignored in text fields). It also accepts
    their ShortcutOverride events, which is what keeps Maya's undo hotkey
    from running while picking (the user's Ctrl+Z undid scene work and left
    the point). Press on a marker (`marker_at`, 14 px) grabs it for
    dragging (`drag_to` re-picks), Ctrl+press removes it; removed points
    go on `undone` (index, point) for redo. Markers are numbered and
    coloured by `_th_point_roles` (the same 20% height split as
    `thatch_shape_from_points`) through an annotationShape child;
    `pick` casts against visible non-roof meshes, snaps to the hit face's
    vertices within 14 px, and on a miss `_snap_near` takes the vertex
    nearest the ray within 14 px by the camera's pixel angle (a peak
    clicked from just outside its outline); markers are NoUndo,
    doNotWrite locators.
  - **Noise speed:** `_th_noise` inlines the four `_th_hash` calls (same
    values, checked over 200k samples): the relief calls it ~1M times.
  - **Makeshift** (`warp`, `ridge_sag`, `ragged`, `gaps`): warp and ridge
    sag are in `height` (so courses and levels follow them); ragged moves
    shell points near the eave down the slope (outer and inner together,
    so the shell stays closed; the cone's jags wrap a whole number of
    times); `gap_at` is clumped noise that pieces and panels skip.
  - **Presets:** `thatch_preset` resets every shape key and sets the look
    keys a preset names, so shape presets keep the style and look presets
    (Cambodian shack, Grass hut) set it. The user's own presets live in the
    `unlokThatchPresets` optionVar (JSON, like Rope Lashing's; no file
    I/O): every key but `THATCH_PRESET_SKIP` (seed, ridge, detail); on load
    the rest get their defaults, so older saves pick up new settings.
  - **Duplicate / links / Ctrl+D copies** (the user asked how to reuse a
    roof at another size, linked): roofs store `"self"` (their own uuid,
    stamped by make and every update) and optionally `"link"` (a group
    id) in their JSON. `update_thatch_roofs` first runs
    `thatch_split_copies` on the roofs it's given (a Ctrl+D copy keeps the
    box uuid: `thatch_copies` finds roofs sharing a box, the original is
    the one whose `self` matches, else the shortest name), which gives the
    copy a box at box_world * inv(orig_world) * copy_world (or reuses an
    orphan tool box already there: Ctrl+D on box + roof), in its own
    UndoChunk; then `_th_spread_links` adds the `THATCH_LINKED_KEYS` of
    each change to the other roofs with the same link (only differing
    values, so a plain rebuild or an own-key change touches nothing else).
    `THATCH_OWN_KEYS` (shape, ridge, ends, hip_pitch, half_hip, overhang,
    seed) stay per roof. `rebuild_stale_thatch` passes split=False (no new
    nodes while redoing). The split is not run on selection: an undoable
    step there would make Ctrl+Z loop. `duplicate_thatch_roof` is one
    UndoChunk (box copy, `make_thatch_roof` nested inside, link ids), new
    seed; `_th_box_copy` duplicates a tool box, or fits a tool box to
    another mesh's bounding box. `link_thatch_roofs` / `unlink_thatch_roofs`
    write in NoUndo like live edits.
  - **`box_frame`, not `frame`:** the box's frame at the last build is
    stored as `box_frame`. It used to be `frame`, the same key as the Frame
    on/off setting, so every build overwrote Frame off with the frame dict
    (truthy: Frame came back on at the next rebuild). `thatch_data` moves an
    old dict across and reads Frame off the frame mesh (hidden at a Detail
    above Proxy = off).
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
  - **Corrugated metal** (the user, 2026-11-01: same setup as thatch,
    clean big sheets or makeshift smaller panels on top of each other, all
    fitting properly, the real frame, nice UVs with variations or all laid
    out). The panel's tool is now **Roof** (`TOOL_NAME`); `covering`
    (`ROOF_COVERINGS`) picks the engine in `make_thatch_roof` /
    `update_thatch_roofs` (`metal_build` vs `thatch_build`). Metal settings
    are `m_*` keys (`METAL_DEFAULTS`, merged into `THATCH_DEFAULTS`, all
    look keys), sizes in **metres** (not span fractions), scaled with
    `scene_m_per_unit()` in `_mt_sizes`. Parts `METAL_PART_MATERIALS`
    (sheets, trim, fixings, frame); `roof_ensure_parts({root: covering})`
    adds the missing ones in one UndoChunk ("Roof covering") before a
    rebuild; the other covering's meshes stay, hidden. Old roofs (no
    `covering` stored) are thatch and rebuild exactly as before.
    - **Faces** (`_mt_faces` -> `_MtFace`): each roof plane's footprint
      clipped by half-planes (`_mt_clip`) against its neighbours (0.01 m
      gap at hips), in plane coords a (along) / s (up the slope). A cone is
      one wrapping face with tapered sheets.
    - **Sheets** (`_mt_sheet_mesh`): profile columns (`_mt_profile`,
      Sine / Box), each column clipped to the face (`_mt_span`), closed
      solids from `_mt_solid` (top, mitred underside, edge walls whose UVs
      run as one strip per side; per-quad shells made thousands of UV
      shells).
    - **Clean** (`_mt_layout_clean`): columns of sheets from the weather end,
      laps lifted analytically by `tg` (`_mt_sizes`: 1.1 thickness x the
      profile's steepest slope factor, so a lap over a steep flank never
      touches; a flat lift collided on cone flanks).
    - **Makeshift** (`_mt_layout_makeshift`): panels per face, widened until
      the overlap is under 40% of a panel (narrow panels ratcheted up in
      stacks). `_MtRaster` (0.06 m cells: height + owner) records what is
      laid; each new panel rests on it through `_mt_rest`: a dilated
      lattice (step 0.08 k) slope-limited by two sweeps along u and v, so
      one tall spot can't tilt a whole panel up (the first version stacked
      ~3 units high). Lifts and dents only go up.
    - **Trim** (`_mt_trim`): `emit_line` samples stations along a crest and
      lifts each section over the sheets there (`_mt_lift_near`); makeshift
      runs take `stiff` (the lowest line over the station lifts), since a
      capping can't follow each panel. Ridge cap extends past hipped ends
      by 0.1 k + half a wing and the hip caps start lower, so the hip /
      ridge junction is closed; the cone cap is closed over the apex.
      `_mt_under_cap` keeps screws out from under cappings and barges.
      **Flush** (the user, 2026-11-02: flashing floated): base lift = depth
      + 2t + 2tg + `m_trim_gap` (Trim gap, metres) + 0.3 mm; laps between
      lengths and ridge-over-hip are 1.2 t. Makeshift `m_trim_drape`
      (Trim follows sheets, default 1): `draped()` bends each section
      point from the straight length onto the panel right under it
      (`_mt_lift_near(r=0.04 k)`, only the faces it's over), stations every
      0.2 k. Makeshift ridge caps went from ~14 cm to ~4 cm off the sheets
      (troughs included). Measure with rays (`scratchpad` probe idea: cast
      down from trim vertices; clean sheets only have vertex rows every
      60 cm, so casting up from sheet vertices misreads the ridge).
    - **Frame**: `_th_frame_members` with purlins (`_mt_purlins`) in place
      of battens; hip rafters are dropped along their normals (square tops
      poked through the sheets at the hip); fascia / barge boards from
      `_mt_extra_members`.
    - **UVs** (`_mt_uv_layout`): one density, `m_uv_tile` metres a tile.
      Variations: per-sheet random offset within its stack's tile / column
      (`UV_STACKED_ATTR` True). All laid out: rows of shells, long side up
      V, as many UDIM tiles as needed (not stacked). Trim is packed in
      0..1 (`_mt_pack_trim`).
    - Panel: rows carry a group ("thatch" / "metal" / "both", `self._group`)
      and `_update_rows` shows them by covering; metal hides the under /
      more / makeshift-thatch / levels / cap / blocker sections and shows
      `mmk_sec` (Makeshift panels, Makeshift only) and `trim_sec`. Picking
      a profile sets its pitch / depth (`METAL_PROFILE_SIZES`). Look
      presets with `covering` apply `METAL_DEFAULTS` first; thatch look
      presets set covering back to Thatch.
    - Not done: levels and blockers for metal (sections hidden).
    - Tests: `tests/test_corrugated_roof.py` (gap rays, closed solids, ray
      enter / leave order for interpenetration, frame under metal, UVs),
      metal block in `tests/gui_thatch_roof.py`.
  - **Clay tiles** (covering "Tiles", 2026-11-04; brief from the parent
    session: barrel / Roman / plain, courses on battens, ridge / hip /
    verge tiles, Clean and Makeshift, holes show battens and underlay,
    never sky; the user picked an Underlay setting, Felt default). Engine
    `tile_build` (pure maths, like `metal_build`); `t_*` keys
    (`TILE_DEFAULTS`, metres, look keys), `_tl_sizes` scales by
    `scene_m_per_unit()` (sizes carry `slack` 4 mm for ridge laps). Parts
    `TILE_PART_MATERIALS` (tiles `clayTile`, tile_trim `clayTrim`,
    tile_underlay named by `TILE_UNDERLAY_MATERIALS` via
    `_tl_underlay_name`, frame); groups `tileRoof####` (`_roof_stem`);
    the panel's rows are group "tiles", sections `tmk_sec` (Makeshift
    tiles) and `ttrim_sec` (Ridge, hips and verges); picking a profile sets
    `TILE_PROFILE_SIZES`. Parts exist only with geometry (`roof_ensure_parts`).
    - **Faces:** `_mt_faces` (Clean) + `_tl_face_setup` (edges as inward
      normals `tl_edges`, mids, `tl_grow`). On a cone `a` is angle x Re:
      tiles fan with the slot, so a-widths go through `qa = ring / n_cone /
      pitch` (a-units per metre across). Plain widths take `qa` once only
      (scaled twice, then an extra `/rho`, the course overlapped itself and
      the rest-solver stair-stepped to 1e36).
    - **Laying:** `_tl_layout` gives every tile in laying order (Barrel:
      pans then covers over their joints; Roman: each course from its far
      end back so every roll laps the lip laid before it; Plain: a short
      eave course then bonded courses). Per face a `_TlRaster` (top heights
      over the face plane, cells aligned to columns / courses) records
      what's laid; each tile reads its cells (`_tl_cells`) and rests on
      them through `_tl_rest(yh head, yt tail)`, then `_tl_record`s itself.
      A tile cut at its head (`tl["piv"]`, the top course) only reads cells
      below the cut, levers over its full length, and its tilt is capped at
      3 x (thickness + gap) (a short lever tipped top-course tails up 0.9 m
      and floated the ridge).
    - **Crest growth** (`_tl_crest_grow`): an edge shared over a ridge or hip
      gets `grow = tan(half the angle between the normals)`; a lean-to's
      top edge grows to the vertical wall plane. `_tl_clip_seg(grow, lift)`
      lets a tile y above its face run past the edge by y x grow, to the
      bisector plane where the other side's tiles meet it. Barrel covers sit
      high: without it the sky showed under the ridge tiles. Tiles whose
      grown columns differ are deferred until `_tl_trim` has laid the
      ridge / hip pieces (`crests` descriptors), then cut against them by
      `_tl_crest_cut` (10 samples from the old to the grown edge, stopping
      where a crest solid blocks).
    - **Ridge / hips** (`_tl_trim`): `lay_line` lays crest tiles piece by
      piece along a (sagging) crest, each lifted over what's under it
      (never below the previous less 0.8 slack, so laps stack); hips stop
      at the ridge (`_tl_stop_end`), and `cyl_clip(axes)` cuts hip tiles
      against the ridge's pieces. Verges `_tl_verges`: Verge tiles or
      Undercloak. A lean-to's top edge gets monoridge tiles: `lay_line(...,
      wall=(0, 0, -1))`, the roll from the slope over the edge onto the
      box's high face (like the metal's top barge); without them the top
      course's ends showed sky and the battens past them.
    - **Makeshift:** slipped / cracked (two solids, `_tl_emit`; the upper
      piece is key + 1, so tile keys are even) / missing / mismatched
      (slightly other sizes), uneven courses; `t_sag` feeds the
      field's warp / ridge sag so frame, battens and tiles all sag together.
      `_tl_underlay` (Felt / Boards / Reed mat) sits under the battens.
    - **Test notes** (`tests/test_tile_roof.py`): the ray enter / leave
      check uses each hit triangle's normal (a long, slightly twisted wall
      quad on a ridge tile folds along its diagonal, and a grazing ray
      crossed both halves under one polygon normal), merges coincident hits
      only when they face the same way (two tiles touching is an out and
      an in) and lets overlaps under 1 mm (0.01 units, the raster's
      resolution: courses under a cone's cap) count as touching; grazing threshold
      |n.y| < 0.002 (slanted edge walls are entered through); UV overlap
      boxes skip shells filling under half their box (the edge strips
      along tapered sides and crack lines); the eave check allows the
      normal offset.
- **Scatter** (Modeling tab; replaces the Moss and Ivy panel. The user,
  2026-11-03: "it just kind of controls everything at once, I have grass
  and leaves appearing on vertical walls ... a 'build a scatter group' and
  it showed a bounding box like the roof does ... a list of stuff in it,
  you can add / remove / undo and click things to control them"; naming:
  "everything would be under a scatteredObjects####_GRP"). Engine
  `sc_build` (each on layer by `_sc_build_layer`: moss_build / ivy_build /
  debris_build with the other items zeroed; cached per layer JSON and
  surface mesh keys in `_SC_BUILT`, so a live edit rebuilds only its
  layer; then one `_roof_udims` over every part, keys "<layer id>/<part>",
  in layer order; the layer's name is left out of that key, so a rename
  doesn't regrow it). **Per-mesh caches** (`_MI_TRIS`, `_MI_REST`,
  `_MI_MOSS_TOPO`...) are trimmed by `_mi_trim` to 3 x the meshes of every
  live group (`_mi_room`, set in `sc_build`; at least 24): a fixed 24
  thrashed on a group of 40 planks. `_mi_surface` keeps the last few
  `_MiSurface`s by mesh keys (checked with MObjectHandles, so a new scene
  with the same names builds a new one). `_mi_mesh_key` can't see a mesh
  reshaped inside its old bounding box, so the panel's Regrow runs
  `mi_clear_caches()` first. Measured 2026-11-10 (40 planks, a Coverage
  edit): the cache sizing alone was no faster; the time is the bed's own
  build. Then (2026-11-11): `_MiSurface.piece` reads the kept surface's
  `mesh_keys` (set by `_mi_surface`) instead of a `_mi_mesh_key` per
  triangle (~180 a mesh an edit); `_mi_write_colors` hands the (r, g, b)
  tuples straight to `MColorArray`; `_MossMat` keeps each dome cell's snap
  onto the surface in its layout cache (`_MI_MOSS_MATS` entry [2],
  `self.snaps`: a closest-point search over every mesh per dome, redone on
  every edit). Carpet 6.85 -> 5.9 s, Mat 2.65 -> 2.3 s, same meshes and
  colours (hashed). The panel remembers each layer's last update time
  (`ScatterPanel._took`, by group and layer), so a held slider on a layer
  known to be slow drafts from its first tick instead of after one full
  update. Test `test_scatter.many_meshes`
  (`UNLOK_ONLY=name,...` runs chosen parts of `test_scatter.py`). Scene
  side `create_scatter_group`, `sc_add_layer`,
  `sc_remove_layer`, `sc_set_layer` (on / name / area), `sc_move_layer`,
  `sc_set_surfaces`, `sc_update` (live), `sc_regrow`, `sc_sync`,
  `bake_scatter`, `sc_selection`, `sc_owner`, `sc_new_group_from`; panel
  `ScatterPanel`.
- **Scatter panel layout (UI pass, 2026-11-11).** Step 1 picks the
  "First layer" type; drawing sits in a folded "Or draw where it goes"
  section (opens itself while there are strokes); the group's surface list
  and its New Group from This / Duplicate Group buttons only show while a
  group is being edited (`group_box`). Step 2's Add Layer is a button with a
  menu of types (`add_layer(typ)`; there's no second type combo). Renaming
  a layer edits just its name (`_ScLayerNameDelegate`, the plain name in
  item data UserRole + 2). Step 3: Detail is the first row for every type;
  the old catch-all "More" sections are named for what they hold (Shoots
  and strands, Blades, How they lie, Clusters, Stems and leaves) and Height
  fade follows "Where it grows". The preset combo shows the preset the
  settings match (every key it names, seed aside; `_mark_preset`), else
  "Custom settings" (its placeholder, index -1). With no layer picked, step
  3 shows the next group's first-layer settings, kept per type in
  `ScatterPanel._next` (set by edits, presets and Randomize with no layer),
  so a new group never picks up the last layer looked at. Note the fields'
  `setValue` doesn't emit `changed`: a test emits it to act like a user.
  - **Scene:** `scatteredObjects####_GRP` (transforms free: `_rope_fill`
    writes parts through their inclusive matrix, so they sit on the
    surfaces under any parent; locked, Maya's parent couldn't compensate
    and the scatter jumped by a moved parent's offset) with `unlokScatter`
    JSON {surfaces: [uuid], udim, next,
    layers: [{id "L<n>", type (`SC_TYPES`), tag ("" / "2"...: the number
    after the material in part names), name, on, s (only the type's keys,
    `sc_defaults` under it), seeds, faces}]}; a box
    `scatteredObjects####_CTL` (`unlokScatterBox`, wireframe, no render
    flags) refit round the visible parts after each build. The box is
    beside the group at world level (the user, 2026-11-05: "move them into
    my publish thing without having to move the bounding boxes out of
    them"), linked both ways by uuid (`unlokScatterBoxId` on the group,
    `unlokScatterBoxOf` on the box; `sc_box` checks both, `sc_owner` reads
    the box's). `sc_fix_box` (NoUndo; from `sc_regrow`, the panel's
    `_alive` on a group it hasn't had, its showEvent over every group):
    unlocks old groups, parents an old box inside out to world (keeps its
    place), gives a Ctrl+D copy (link to another group's box) the copied
    box made with it if there is one, else a new `unlokScatterBoxAuto`
    box (`sc_sync` deletes those whose group is gone: an undone Ctrl+D).
    No box: grows fine; `sc_remake_boxes` (panel Make Box, one Ctrl+Z).
  - **Control group** (the user, 2026-11-09: hidden geo turned up in
    publish folders after a rebuild; "As long as it's normal geo, it can go
    in the publish group ... instance setup ... should go in the control
    group"): the scatter group holds only plain visible meshes, so it can
    be dragged into a publish hierarchy as it is. The box and any
    instanced-shoots rig live in `scatterControl####_GRP` (`SC_CTL` =
    group uuid on it, `SC_CTL_ID` = its uuid on the group; `sc_control`,
    `_sc_ctl_of`), made by `_sc_new_root` / `_sc_make_control` under the
    box's parent (world for a new group; never inside another group's
    control group: a box copied in one gets a control group beside it).
    `sc_fix_box` checks `_sc_control_ok` and runs `_sc_fix_control` when
    not: adopts a copied control (Ctrl+D on group + control), else makes
    one (`SC_CTL_AUTO` for a copy's, deleted with orphan boxes), parents
    the box in (only then: a box the user moves out later stays), moves an old
    layout's shoots node out of the group (renamed), deletes hidden tool
    parts and hidden shoots, leaves geometry where it is. So old scenes
    upgrade on regrow / panel show. Empty parts are deleted (not hidden;
    a layer turned off too, its parts come back when it's turned on);
    an empty shoots rig too. Bake deletes a control group left with only
    shoots. `sc_owner` / `sc_selection` resolve a control group and
    anything in it to the group. `tests/test_scatter_control.py`.
    `_sc_scatter_mesh` / `_sc_box_mesh` keep Draw on off boxes;
    `sc_surfaces` skips a box moved into a surface group. The panel
    follows its group by uuid when it's reparented. Parts
    `<material><tag>_C_scatteredObjects####_GEP` tagged `unlokScatterPart`
    "<layer id>/<part>", `unlokMossIvyVerts`, UV ready / stacked.
    Surfaces: a mesh, or every visible mesh under a stored group, read at
    each build (`sc_surfaces`; never inside a scatter group), minus
    `exclude` (the user, 2026-11-04: "add a group, but then click
    individual things inside to remove ... they'll override just for that
    one object"): uuids of meshes / groups inside a stored group left out
    of it. `sc_set_surfaces` goes through `_sc_exclude` (drops its own
    entry; inside a stored group (`_sc_covering`) it's excluded; excludes
    no longer under a stored group are forgotten) and `_sc_include` (out of
    `exclude`; a surface of its own only when no group covers it, or it's
    inside something still left out); drawing on a left-out mesh puts it
    back. `sc_surface_names` lists each group's left-out items after it
    (kind "left out"); the panel shows them greyed, Add Selected puts list
    picks back, Remove ignores them.
  - **New Group from This / Duplicate Group** (step 1; the user,
    2026-11-05: "selected a bunch of objects, removed some, I just need to
    be able to like duplicate that, but blank"): `sc_new_group_from(root,
    layers)` copies the whole JSON (surfaces, exclude, udim), blank
    (layers [], next 1) or with every layer, each seed + 1; one UndoChunk
    around `_sc_new_root` (group + box, shared with
    `create_scatter_group`), then the NoUndo regrow (no layers: the box
    fits the surfaces).
  - **Undo model:** structure (layers, surfaces, areas, toggles) is an
    UndoChunk on the JSON (`_sc_change`; Delete deletes the layer's parts
    inside it). Geometry and part creation are NoUndo (tool-managed,
    `_sc_write`: a part is made the first time it has faces, deleted when
    it empties, rewritten only when its mesh or UV shift changed:
    `_SC_WROTE`). After each build the group's `unlokScatterStamp` gets a
    random token (NoUndo) and `_SC_LAST[root]` = (JSON, token);
    `sc_sync` (the panel's Undo and Redo jobs) regrows any group whose
    pair differs: an undone / redone structural change, or a redone new
    group (its stamp comes back empty). A scene opened with a stamp is
    taken as built. No placeholder meshes (the user saw the old hidden
    placeholders as planes at the origin).
  - **Pause / Play** (the user: "hit pause, make a bunch of edits, then
    hit play, and it would all live update"): `_SC_HOLD` {on, base, seen,
    force}. `sc_pause()`; while on, `sc_update` and `_sc_change` save the
    JSON and return `_sc_held` reports ({"held": True}) instead of
    regrowing; `sc_sync` (undo / redo) grows nothing, it only re-bases a
    group whose JSON the undo changed. What's changed is derived, not
    tracked: `sc_pending(root)` compares the JSON with `_SC_LAST` (layer
    ids added / changed; group: surfaces, UDIM, order, removed, Regrow via
    `sc_regrow_later`). `sc_play()` regrows every group that differs (the
    `_SC_BUILT` cache means only changed layers build, once). Undo:
    `_sc_commit` sets base (NoUndo) then the JSON inside one UndoChunk, so
    Ctrl+Z restores base and `sc_sync` regrows: "Scatter play" at Play,
    "Scatter edits" before a structural change made while paused (so no
    paused live edit is lost to undo). `bake_scatter` regrows pending
    groups first. New groups still grow. Panel: `pause_btn` / `pause_label`
    under the banner, PAUSED banner, `(changed)` rows (`_layer_text`,
    `_mark_paused`), `toggle_pause`.
  - **Freeze fix** (the user changed one setting on an old scatter after
    updating and Maya seemed frozen: not old data, the first edit after a
    scene opened regrew every layer, `_SC_BUILT` being empty, with no
    window): `sc_build` reads an unchanged layer back from its parts
    (`_sc_read_layer` / `_sc_read_part`, noted in `_SC_WROTE` so nothing
    is rewritten) when `_sc_grown_layers` says the parts show it: the
    layer equals the one in what the group last grew from, the stamp
    matches (a redone new group has none) and the surfaces' mesh keys
    match (`_sc_same_surf`, 1e-4: saving rounds them). The group keeps
    `unlokScatterGrown` (JSON grown from), `unlokScatterCounts` (per
    layer) and `unlokScatterSurfaces` (mesh keys); `_sc_note` fills
    `_SC_LAST` / `_SC_SURF` from them the first time a group is touched
    (older groups: their JSON as saved). Regrow passes readback=False.
    `sc_regrow` runs in a Progress (Working window after 0.5 s; `_poll()`
    in the moss / debris / ivy loops) and with `_MI_BUDGET` on for live
    edits, so `_MossBed` raises `ScatterTooBig` past MOSS_WARN_CELLS
    (estimated cells: surface area / cell area x the share of blocks
    that can show moss); Cancelled / ScatterTooBig -> `_sc_stopped`:
    pause, box fitted, a held report with "stopped". Play, Bake and
    Regrow pass budget=False.
  - **Draft** (the user: "scattering moss is slowwwwwww, it takes ages to
    update"; pure-Python tuning only bought 10-20%): `_SC_DRAFT` {on,
    later}, a session toggle (`sc_set_draft`, `sc_drafting`). `sc_build`
    passes draft to `_sc_build_layer` for layers that grow (new / changed /
    `only`); a moss layer then calls `moss_build(draft=True)`: `_MossBed`
    with Proxy's cell and no lumps, no `_MossDetail.build()`, from the same
    field caches (same patches). Its counts get "draft": True, saved in
    `unlokScatterCounts`, so `sc_drafted(root)` (on layers with it) holds
    across undo, cache and a scene opened again; layers that don't grow
    keep what they are (a cached full build of the same JSON comes back
    full). `sc_full_detail(roots)` = `sc_regrow(only=drafted,
    draft=False)` (paused: at Play, via later). `bake_scatter` grows
    pending and drafted layers with draft=False first and skips a group
    whose growing was cancelled. Panel: `draft_btn` / `full_btn` /
    `draft_label` under Pause, `(draft)` rows (`DRAFT_RGB`), Draft off with
    drafts left = Full detail.
  - **Height fade** (the user: "moss and ivy growing up columns from the
    bottom fading out towards the top"): `MI_FADE_DEFAULTS` (fade, fade_by,
    fade_height, fade_part, fade_soft) in all three defaults and
    `SC_DEBRIS_COMMON`; `_debris_field` copies them. Objects =
    `_mi_fade_groups(nodes)`: each mesh's connected pieces
    (`_mi_pieces`, union-find on face vertices, cached by mesh key) joined
    when their XZ footprints overlap by `MI_FADE_JOIN` of the smaller one
    and neither is `MI_FADE_RATIO`x the other (so a floor stays apart).
    `_MiFade.at(p)`: the smallest object box holding p (1 cm leeway; else
    the nearest), flat ones (lower than half their narrower side) 1, else
    smoothstep from 1 at H(1 - soft) to 0 at H. `_moss_margins`: margin -=
    (1 - f) coverage + 0.6 (1 - f)^3 (patches thinning out over the whole fade), -1 at f = 0; moss (not `_up_only`) scores with
    slope >= 90 while a fade is on. `ivy_walk`: a per-vine cut (rand 55),
    the vine stops on a clinging step whose f < cut; branch chance x f;
    `vine["fade"]` per point; `ivy_leaf_mesh` skips a leaf when rand 62 >=
    f. Off = no fade object: same randoms, same meshes. Panel: section
    `_SC_FADE` before More (`fade_sec`, opened for a faded layer),
    `_style_rows` shows by/part/height/soft by Height fade and Fade by
    (`row_lbl`).
  - **Influence paint** (the user: "a brush to influence paint, to add /
    remove influence ... not 100% opacity, but like 10% ... lots of strokes
    to subtly influence parts"): a layer's `paint` = {"t": mesh uuids, "b":
    base, "m": [[cell size in the mesh's units, [i, j, k, v, ...]]]}, values
    -1 (none) .. 0 (unpainted, grows as before) .. +1 in 1/`SC_PAINT_Q`
    steps, on a sparse grid of `SC_PAINT_CELL` (10 cm) cells local to each
    mesh (follows it; not per vertex: guide meshes are a few big faces, the
    reason Artisan maps were dropped). Only touched cells are stored; Flood
    moves the base (unpainted surface) and every cell. Edit with `ScPaint`
    (`dab(p, radius, opacity, mode, nodes)`: `_sc_paint_cells` samples each
    triangle near p at half a cell inside the sphere (triangles from
    `_sc_paint_tris`, a grid cached by mesh key), falloff (1 - t^2)^2;
    Add / Remove step by opacity x falloff - between `begin_stroke` /
    `end_stroke` (the brush's press / release) capped at that past where the
    stroke found each cell, so overlapping dabs don't stack and a 10% stroke
    adds 10% like Photoshop's stroke opacity - Smooth towards the 3x3x3 average
    (cells the dab hit but nobody painted count as the base); `flood`,
    `clear`, `dump`). Stored by `sc_set_paint` through `_sc_change`, so a
    stroke / Flood / Clear is one Ctrl+Z, pending while paused, regrown at
    Play, and in the layer JSON (cache keys, readback, Duplicate copies it,
    Bake keeps it in `unlokScatterBaked` harmlessly). Build: `sc_paint_of` ->
    `_MiPaint` (world grid of cell centres; `at(p)` = weighted average within
    1.5 cells, `W0` of the base; `top` lets moss / debris grow at Coverage 0;
    its repr is the cache token) passed as `paint=` to moss / debris / ivy
    builds, which put it in `s["_paint"]` after `mi_settings_only`
    (`_debris_field` copies it). `_moss_margins` after the fade:
    `_sc_paint_margin` (k > 0: + k (1 - Coverage) + 0.3 k^3; k < 0: like the
    fade, - g Coverage - 0.6 g^3, -1 at k = -1; Coverage 0: -1 unless painted
    in), so picked faces / drawings still limit where it's sampled and paint
    works inside them. Ivy: `_MiInfluence(fade, paint)` stands in for the
    fade in `ivy_walk` (f + k (1 - f) / f (1 + k): vines stop, leaves thin);
    `_ivy_auto_seeds` drops painted-out picks by chance and puts painted-in
    ones first. Brush: `ScatterPainter` (a `SurfacePathDrawer`, context
    `unlokScatterPaintCtx`, only the group's surfaces; dabs every quarter
    radius; Ctrl swaps Add / Remove, Shift smooths; `press_at` / `drag_at` /
    `release` scriptable; reads the paint fresh at each press so undo is
    honoured) with an overlay mesh of green / red face-coloured squares
    (cells within 0.55 cell of the surface, rebuilt every 0.15 s mid-stroke
    by createInPlace, never made mid-stroke) and a ring: NoUndo,
    doNotWrite, reference display, deleted with the tool. Panel: section
    "Influence paint" in step 2 (Brush, Radius m, Opacity, Paint Influence /
    Flood / Clear, `paint_label`), `(painted)` rows, PAINTING banner,
    `_paint_states` keeps the brush on the layer being edited, `_after_undo`
    reloads it.
  - **Wall fix:** debris types set `_up_only` (`_debris_field`): Crevices
    and Creases only count where it faces up, and `_spots` hard-cuts past
    Slope limit + 15 degrees. Type defaults (`SC_TYPES` "over"): grass
    40, leaves 35, piles 30 (Creases 1.0), tufts 60 degrees.
  - **Creases** (`_mi_gather`, cached with the field): over the field's
    candidates (the first `MI_GATHER_NODES`; the rest copy the nearest),
    neighbours within 2.2 x their spacing that each can see (not behind
    either surface): concavity c = (n_p - n_q) . d / |d| (> 0: normals close
    in), averaged = crease; a 2D structure tensor of the concave
    directions gives across (towards the walls), aniso (one way) and bank
    (which side the wall is on, 0 in a channel). Water: each candidate
    drains to its steepest lower neighbour (smooth joins, or concave ones:
    into a wall's foot, never over a convex edge), accumulated top down;
    settle = level enough and (flat or the surface goes on downhill: not an
    eave); gather = 1 - (1 - crease)(1 - log(acc)/log 30 x settle), one
    smoothing pass. `_moss_margins` adds Creases x 0.5 x gather x up-facing
    (moss on a rail's side at its foot otherwise). `_spots` scales density by
    `DEBRIS_GATHER` (piles 3, leaves 1.5, tufts 1, grass 0.5).
  - **Drifts** (`_pile` / `_drift` / `_walk_crease`): a pile on a one-sided
    crease moves up to the wall; with e = 1.6 Creases gather aniso >= 0.15
    a spine is walked both ways along n x across (0.35 R steps, snapped,
    turning with the local crease, stopping where gather fades, the surface
    turns up, or it gets stuck), up to R (1 + 2.2 e) each way; leaves in an
    envelope (1 - t^2) x a banked profile (crest 0.5 e bank towards the
    wall), tilted along both slopes, half of them along the drift. Too
    short a spine: a round pile. Piles skip a spot inside one already made.
  - **Drawing** (the user: "click draw on any surface and then draw a
    curve / line over surfaces (undoable as you go), then hit 'scatter on
    drawing' ... control falloff"): `ScatterDrawer` (a `SurfacePathDrawer`
    with its own context `unlokScatterDrawCtx`; `press_at` never falls back
    to a plane, every visible mesh but scatter groups' counts, no grazed
    filter) keeps strokes [(world point, mesh shape)] shown as
    reference-display curves (NoUndo, doNotWrite) until Clear; Ctrl+Z / Y,
    Enter, Esc through `_ThatchPickKeys` (its remove_last / redo_point /
    finish / cancel). A layer's `draw` = {"t": mesh uuids, "k": [[[mesh
    index, local x, y, z]]]} (`sc_store_drawing`, `sc_drawing`: follows the
    meshes; thinned past `SC_DRAW_MAX_POINTS`); `create_scatter_group` /
    `sc_add_layer` / `sc_set_layer(drawing=)` add the meshes under it to the
    surfaces in the same Ctrl+Z. `_MiDrawing(strokes, width, falloff,
    follow, nodes)`: stroke points densified to Width / 6 in a grid; `faces`
    = faces within Width (whole meshes culled by world box; small triangles
    by centroid + radius, big ones by exact point-triangle distance), cached
    in `_MI_DRAW_MASKS`; `prof` = 1 inside Width (1 - Falloff), smoothstep
    to 0 at Width. `_moss_margins(draw=)`: margin = 0.5 + Follow (score -
    0.5) + noise - (1 - coverage) + prof - 0.5. `_MiSampler(faces=)` samples
    only masked faces (picked faces too, since this) and its `key` goes in
    the spots / field / gather cache keys. Ivy: Vines spread evenly along
    the strokes (`spread`). Settings `SC_DRAW_DEFAULTS` (draw_width metres,
    draw_falloff, draw_follow) on every type; the panel's Drawing section
    shows for a drawn layer.
  - **Strokes one by one** (the user, 2026-11-05: "I've realized one of
    the ones I painted I don't want anymore. I've already scattered, so
    how can I just remove that?"): `sc_stroke_info` (points, meshes per
    stored stroke), `_sc_drawing_rows` (every stroke in world space, in
    order, [] for one whose meshes are gone; `sc_drawing` drops those),
    `sc_delete_strokes(root, lid, indices)` (`_sc_draw_keep`: the kept
    rows, "t" pruned and re-indexed) and `sc_set_layer(add_drawing=)`
    (`_sc_draw_join`, thinned past `SC_DRAW_MAX_POINTS`), both through
    `_sc_change` (one Ctrl+Z, saved while paused, only that layer's cache
    misses). Panel: a Drawn strokes section in step 2 (list, Show Strokes,
    Delete Stroke, Add Strokes); `ScatterStrokeView` draws the stored
    strokes as curves `scatterStroke*` (NoUndo, doNotWrite, picked ones
    yellow and thicker), rebuilt when the layer's draw JSON changes;
    `_sync_from_selection` first checks `_pick_stroke_lines` (a selected
    line picks its row and keeps the group / layer open).
  - **Draw on** (the user, 2026-11-05: "if I bake a bunch of scattered
    stuff and then want to draw another one, it suddenly starts drawing on
    top of the scattered stuff ... I want to be able to sometimes just
    draw on the underlying surface"): `SC_DRAW_ON` Surfaces / Selected /
    Everything; `ScatterDrawer._candidate_meshes` by its `mode`: Surfaces
    skips meshes under any scatter group, live or baked, and any
    `_sc_scatter_mesh` (shape tagged `unlokScatterPart`, which Bake keeps,
    or a transform named `*_C_scatteredObjects####_GEP`) wherever it was
    moved; Selected = `sc_draw_targets` of the selection at activate;
    Everything = the old behaviour (all but live groups). `sc_surfaces`
    skips tagged parts found under a surface group (a baked part moved
    into it) unless one is stored itself, so moss / leaves / paint never
    use baked scatter as ground by accident.
  - **Jungle leaves** (the user, 2026-11-04: "instead of piles of small
    leaves ... large jungle leaves, like one or two or three of them at a
    time ... the size of a whole small leaf pile"): layer type "Jungle
    leaves", debris kind 5 (`DEBRIS_GATHER` 2), keys `jungle` (clusters per
    square metre; 0 in `DEBRIS_DEFAULTS`, so old Debris groups build as
    before), `jungle_size` (metres), `jungle_cluster`, `jungle_shape`
    (`JUNGLE_SHAPES`), `jungle_green`, `jungle_tear`, plus `curl`. Parts
    `green` / `dry` (`leafJungle` / `leafJungleDry`, stacked UVs);
    `SC_DEBRIS_OUT` maps a type to several (debris mesh, part) pairs.
    `_jungle`: 1 to Cluster leaves (uniform), moved up to a wall like a
    pile, spaced by `_room` (0.45 L sqrt(k)); in a crease (`_along`) one
    after another along it, else fanned. `_big_leaf` = leaf space (x across,
    f along in leaf lengths, z up) from `_blade_local` (rows follow the
    veins: f += |x| x slant, Broad's lobes reach back by a notch term; dry =
    rolled round a circle keeping the width, tears duplicate a row's outer
    vertices for the strip above, shifted a little) or `_frond_local`
    (rachis strip u 0..0.08, leaflets u 0.1..1 all on the same UVs), placed
    by the drop (below). Detail `JUNGLE_DETAIL` (rows, columns, leaflet
    rows).
  - **Dropped leaves** (the user, 2026-11-05: leaves "conform to the
    surface instead of sitting on top", "clipping through the window
    frames", big leaves sticking up "like towers" against a small step,
    "almost like it's been simulated that the leaves have just been dropped
    on top and then maybe droop a little"; then "stop leaves clipping into
    the surface or clipping into each other"): `_leaf` (lift 0) and
    `_big_leaf` go through `_DebrisBuild._drop` -> `_mi_drop_pose`, then
    `_mi_drop_settle`, then `stack.lay`. The heightfield is its own pieces,
    so it can serve other growth later:
    - `_MiDropField(surf, cell, band)`: rays straight down at nodes (i + 0.31,
      k + 0.43) * cell (off round numbers: a node on a sheet's end grazes
      its side), cast lazily, cached in `_MI_DROP_FIELDS` (4, by mesh keys,
      cell and band) across builds. A ray starts (band + 2) bands above the
      height asked, so a roof far overhead doesn't count;
      a grazing side hit is cast again a little over; an underside
      (normal y < -0.5) is `MI_DROP_INSIDE`, nothing `MI_DROP_VOID`.
      `top` = max of the 4 nodes round a point; `top_wide` = max of the 9
      round the nearest, leaving out inside ones (the settle's clamp, so a
      frame's edge between nodes can't slip over a point). Both add
      `stack.top` (laid leaves up to 2 bands above). `_DebrisBuild._field`
      picks cell L/5 in 5 mm .. 1 cm and band at least 8 cells and 1.5 L
      (powers of two: a gutter's sides under a big leaf are seen from
      above, not started inside).
    - `_MiDropStack(1 cm)`: per build, highest laid-leaf point per cell;
      `lay` samples every quad finer than a cell, so later leaves land on
      earlier ones (a layer's leaves only; layers don't see each other).
    - `_mi_drop_slope`: the slope a piece goes by along a horizontal axis:
      the normal's or that of the tops at least 15 cm either side
      (`reach`), whichever is gentler, level when they disagree (a
      corrugation flank reads as the pitch, a floor by a step as level).
    - `_mi_drop_pose(field, base, n, X, F, samples, climb, lift, reach)`:
      samples (x across, f along, `LEAF_DROP_SAMPLES` / a 3 x 6 grid over a
      big leaf) all asked from one height yq (the piece's highest expected
      point; the settle asks from it too, so both see the same tops);
      filled in to 2 cells apart (`_mi_drop_fill`, at most 24 a side, so
      a rim or a mullion can't fall between; each reads top_wide too, what
      the settle keeps points above, so nothing is lifted into a spike by
      a lip); against ref = base + slope:
      higher than climb (max(min(L, 8 cm), 0.3 L)) or inside = a wall,
      None; lower than climb = past an edge, skipped; < 3 left, None.
      Least-squares slope clamped to MI_DROP_TILT 40 degrees (or the slope
      + 8), then `_mi_drop_rest`: a rigid body's rest - on the highest
      sample, tipping its middle (of all samples, overhang too) down about
      it, then about the line to the next it meets, till it lies on three
      round its middle (the lowest plane over every sample there; a leaf
      across a gutter lies on both rims, one mostly past a rim tips over
      it), no steeper than the clamp; contacts within 0.15 climb. `_drop`
      turns it 20 / 40 / 60 degrees either way first (glancing off a wall:
      into a gutter it fits along), slides 0.15 / 0.3 of a length sideways
      (off a gutter's side), then tries half a length away in four
      directions.
    - `_mi_drop_settle`: Drape as a cantilever's arc out from the nearest
      contact (angle 1.1 droop d / L, pulled in to keep the length; droop =
      Drape x 0.5 small, 0.9 green, 0.5 dry), then clamped to top_wide +
      lift (asked from yq, or from the point's own height once it has
      drooped a band below, so a gutter under an eave counts).
    - **Contact pass** (the user, 2026-11-05: "lots of floating leaves and
      bad interaction between leaves ... no proper draping"; wanted the gaps
      to surfaces and other leaves fixed and a check that finds and fixes
      floaters). Measured first (`tests/test_leaf_contact.py --measure`):
      on a 30 degree ramp every leaf floated (up to 2 cm), on corrugated
      and glass roofs over 90%, big leaves up to 6 cm, because the nodes'
      `top` / `top_wide` read the max of the nodes round a point (a cell's
      slope high), `_MiDropStack` keeps only each cell's highest leaf
      point (a leaf rests on the curled edge of the one beside it) and the
      rest is rigid (bridges dips). Now after the settle every leaf (small,
      pile, big) goes through `_DebrisBuild._contact` ->
      `_mi_drop_contact(field, tris, pts, start, lift, kappa, reach, far,
      relief, quads, over, coarse)`. Per point, support =
      `_MiDropField.exact` (rays straight down half a cell apart, a cell
      apart for pile leaves (`coarse`), from 1-5 cm over the point, each
      kept with its hit's slope (normal, no steeper than about 3:1) and
      carried over to the point asked, so shared rays stay exact on a
      ramp / rock / corrugation flank; cached in the field's
      `nodes["exact"]` (survives rebuilds); an underside hit = the point is
      inside something: it stays put) and `_MiLeafTris.top` (laid leaves
      as triangles in 2 cm cells, barycentric rows precomputed; counts a
      leaf up to `over` = max(2 cells, 0.1 L) above the point: one put
      through it comes up on top; Rest on moss lays the moss bed in too,
      `lay_mesh`). Then (1) the whole piece comes down by its smallest
      gap; (2) it bends: D(v) = min over w (base(w) + kappa |v - w|^2) over
      the points whose gap is within reach (0.3 L in 1.5 .. 3 cm: across 4
      cm rails it bridges), base = gap minus the point's own relief (its
      curl / cup / crumple over the piece's lowest, so the sheet under the
      curl bends and a cupped leaf keeps its edges up); points already
      touching skip the loop; points past reach (over an edge, the settle's
      arc already drooped them) move with the nearest one in reach; kappa =
      bend / L, bend 0.3 + 1.5 Drape small and pile leaves (stiffer: they
      folded over rails and mullions), 0.4 + 3 Drape green, 0.3 + 2 Drape
      dry; (3) no point under its support + lift; (4) `_MiLeafTris.rims`:
      each triangle raised over any laid leaf point under it (a curled rim
      between its own points poked through the leaf laid on it; cells whose
      highest point is under the quad are skipped) - not for pile leaves
      (buried; it cost a second a pile build). Nothing under it at all:
      the leaf is taken off (`removed`). The build's `contact` dict
      (lowered / pushed / removed) is in `debris_build`'s result. After: no
      leaf over 5 mm off anything in any scene but the odd one whose face
      rests on a mullion's edge between its points (rails' grating left out
      of the measure: leaves rest across rails), the curl kept (`air` 0.1 -
      0.4). Cost: small and big leaves 5-10%, Leaf piles about 1.65x main
      (2.2 -> 3.7 s on test_scatter's yard). A small leaf leaning off a rail
      end or a sheet's edge now drapes down onto the floor below, its fit
      plane up to about 53 degrees (test_scatter's limit 52 yard / 55 roofs,
      was 48 / 52 for the stiff rest). Pile leaves come down onto the leaves
      under them too (no air pockets in the mound).
    `drape` (0.5) in `DEBRIS_DEFAULTS` and on Leaves / Leaf piles / Jungle
    leaves (More). Pile leaves (lift > 0) keep their pile placement, then
    the contact pass, and are laid in the stack. `_leaf_spine` is gone.
  - **Moss Style** (the user, 2026-11-04: the carpet "can become a bit
    heavy ... it doesn't always have to be one object ... a scattered thing
    instead of this growth. Or maybe there's a setting to toggle"): `style`
    (`MOSS_STYLES` Carpet / Clumps, default Carpet, so old groups build as
    before). `moss_build` swaps `_MossBed` for `_MossClumps`, which has the
    same interface (pts, dirs, hf, core, faces_out, R, capped, count,
    mesh()), so `_MossDetail` grows on it unchanged. Candidates with margin
    > 0, best first; radius / height from the margin (pr) and shelter;
    spacing grid (cell 4 R), cushions never overlap; each is a dome
    (`MOSS_CLUMP_GRID` rings x segments by Detail) plus up to two
    satellites, each spoke walked over the surface (`_spoke`, the user,
    2026-11-05: spots "able to grow around corners ... instead of just
    ending harshly": a flat disc laid by closest point squashed the part
    past a convex edge onto the edge, a flat wall at the edge): a step
    whose end is off the surface sideways (in the plane it walked; a
    curve's sag is along the normal; into the surface = a wall's foot, left
    alone) folds its overshoot down the far side once, the heading
    unfolding (along the edge it keeps going, across it turns down: no
    spike), and points past the fold sit along the far face's normal; a
    fold into something stops the spoke. Same number of closest-point
    queries plus one per fold. `_fit` tests rim points (x1.1) at
    full, 0.65 and 0.4 radius with `_covered` (a ray out hits within 1 cm,
    or a back face): the first clear size wins, else no cushion (moss went
    under the porch wall). Count = cushions placed. **Grouping** (the
    user: "more that are like clumped together sometimes, so it's not like
    such an even gap", with controls for the noise): `clump_group`,
    `clump_group_size` (metres), `clump_pack`. One `_moss_noise3` per
    candidate at Group size gives gg (eased, ~1 in a group); candidates are
    sorted by margin + 0.4 Grouping gg, thinned in the gaps (r[9] < Grouping
    (1 - gg) 0.9), bigger in a group's middle, and the no-overlap test's
    limit is (rad + qr) x (1 - Grouping gg (0.15 + 0.6 Packing) + Grouping
    (1 - gg) 0.4). Grouping 0 = the even scatter. The panel's "Clumps"
    section (`clump_sec`) shows only for that style (`_style_rows`, from
    `_show` and the Style field's changed signal). **Heights** (the user:
    "some that are like more mounds ... on a completely random per blob
    basis and also on a clumps basis"): `clump_hvar` (h x 1 + 1.5 hvar (r -
    0.5)), `clump_mounds` (chance 0.4 x Mounds: h x 1.8..3.5, radius x
    0.85), `clump_ghvar` (a second `_moss_noise3` at Group size, only when
    > 0: h x 1 + ghvar (1.1 noise + 0.6 Grouping (gg - 0.5))). Their
    randoms are their own `_rand12(seed, i, 7, 97)`, so changing them never
    moves the layout; the obstacle cap (0.6 x the room above) still wins.
  - **Mat style** (the user, 2026-11-06: the carpet is "quite heavy to load
    ... the topology is still weird ... nor does it handle displacement
    well ... when displacement is applied, it just lifts from whatever
    surface it's on. Maybe it needs some edges that curl down a bit?";
    wanted "quick to use and play around with, that is optimised, can have
    _GED suffix and will work well with displacement, good UVs"):
    `MOSS_STYLES[2]` "Mat", `_MossMat(_MossBed)` (same interface for
    `_MossDetail`). Keys `render_as` (`MOSS_RENDER_AS` GEP / GES / GED,
    default GED), `disp_height` (m, 0.01), `edge_roll` (0.5),
    `cage_detail` (0.5), `bumps` (0.5), `growths` (0.35); panel section
    "Mat" (`mat_sec`, Displacement only for GED); presets "Moss mat",
    "Simple mat" (Bumps / Growths 0), "Lumpy mat" (0.85 / 0.7), first in
    the list. **The default since 2026-11-09** (the user: make "the more
    optimized ones with better geo" the default preset): `MOSS_NEW_LOOK`
    adds style Mat, coverage 0.65, render_as GED, lumps 0.5 (= "Moss
    mat"), so a new layer and the panel's starting values
    (`sc_start_settings` = `sc_defaults` + the type's "new"; the panel used
    to start on `sc_defaults`, so its first layer missed the new look) are
    the Mat. `MOSS_DEFAULTS` stays Carpet: an old layer that never stored
    a style grows as before. Pipeline:
    - **Grid:** `_mi_mat_base` = the surface's faces as quads (smooth
      rest: the once subdivided mesh on its limit points; faceted: the
      faces, triangles paired, else every face split), `_mi_mat_rings`
      gives every edge ring one cell count (cell = R (1 - 0.75 Cage
      detail) x `MOSS_MAT_CELL` by Render as x 1 / 0.875 / 0.75 for
      max(Bumps, Growths) 0 / <= 0.5 / more (steps: a factor following
      the sliders changed the layout key, so every Bumps / Growths edit
      laid the cage out again), x2 for a draft), so faces
      meet point for point. Cells only in blocks the field can reach
      (`_local`, block keys carry the cell size: without it another Cage
      detail's lookups were read back), points laid on the rest surface
      by its own query (closest), each with a `_MossBed._record` (a
      context whose three corner normals are the point's normal). Per
      layout cache `_MI_MOSS_MATS`; per base quad buried / partly covered
      (`_quad_cover`).
    - **Outline:** a cell is kept where its corners' mean coverage
      (margin + ragged + 0.03, `_look`) > 0; points pressed under
      something (room < 1 cm) are -1 (no mat under a box). Notches (3
      kept neighbours) filled, spikes pruned, pinholes of <= 12 cells
      with moss all round filled, bow ties fixed (`_pinched`), bits < 3
      cells dropped. Outline points slide to the coverage's zero crossing
      along their edges (<= 0.7 of an edge), then 3 relax passes along
      the loop, snapped back to the surface.
    - **Heights:** `_value` with its own lumps off, then low cushions
      (one noise octave at max(0.7 R, 2.5 cells)); at least the rim
      height (`edge_roll x (0.35 H + 0.5 D)`), the outline at the rim, 2
      smoothing passes; then the shape (`_shape`, after the smoothing so
      it stays crisp). Both are round domes from world grids (`_dome`,
      `_domes`, `_rand12`, one per cell at most, centre snapped onto the
      surface and kept only if that lies in its own cell), profile
      (1 - x^4)^2 (full top, steep flanks, soft foot), outline radius
      x (1 + 0.25 noise). Bumps: every cell of max(0.7 R, 4 cells),
      radius 0.62..0.92 of that, height Bumps x 1.6 H x 0.55..1, the
      highest wins (creases where they meet: cushions). Growths: cells of
      2.5 x their size (size = max(4.5 cells, 1.2 R), radius 1..1.5 x),
      chance 0.9 x Growths, height H (2..4.5) x (0.6 + 0.4 Growths) but
      <= 0.75 radius, top + 0.25 x the others. Faded in from the outline
      by distance along the cage (Dijkstra over max(4 cells, R),
      smoothstep). Where 0.6 x room caps it, the cap spreads one ring and
      blends. Dead ends, each a spike or pit in the pictures: billowed
      noise (halves the feature size below 2 cells), a 2-cell octave, 3D
      dome centres off the surface (cut into narrow caps), fading by core
      (B jumps 0.1-0.5 between neighbours), a rim with infinite slope
      (sqrt / ^0.55 profiles: a one-cell cliff). The user (2026-11-06)
      asked for "more mossy bumpy noise, some more realistic bulging
      bits/ inflated growths", with control from "super simple like
      this" up, "while keeping this nice new topo". Bumps 0 + Growths 0
      is the earlier Mat (points; UVs changed, see UVs).
      Lift along the kept cells' area-weighted normals.
    - **Rolled edge:** two quad rows per outline edge: out 0.8 w and up
      0.45 rim, then back in to 0.35 w and down 1.25 D + 3 mm under the
      surface (w = max(0.5 cell, 1.5 rim)). No underside. Its open edges
      are the only ones; B (core) is 0 there.
    - **UVs:** `_mi_mat_uvs` unfolds quad by quad across shared edges at
      Tile size scale (a chart stops where a quad lands off its own
      points by > 0.45 of an edge, over another quad (point-in-quad), or
      past 0.9 of a tile; scraps of <= 4 quads then join a neighbour up to
      a whole tile), each chart moved into 0..1 (by whole tiles when it
      fits). Overlapping 0..1 like the carpet's tiles. Each quad unfolds
      at its hinge's true 3D length (direction from the UVs; a hinge
      already off by > 1.5x is a seam): scaling by the UV hinge let a
      bumpy surface's errors compound until charts shrank to nothing
      (they always passed the size test), packing the clash grid (17 s
      for 8k quads; now 0.4 s). Clash grid cell = the median quad's
      longest edge, not the first quad's.
    - **Detail:** `faces_out` is the top only; its points are lifted by
      half the displacement x core, so shoots stand on the displaced moss.
    - **Scene:** `_sc_bed_render(s)` -> (suffix, Arnold steps, height):
      Carpet as before (GES 1 from Normal up, else GEP); Mat GEP 0 / GES
      2 / GED 3 (`MOSS_MAT_ITERS`). `_sc_bed_suffix(node, s)` renames, sets
      Arnold's type and steps when the suffix changes (a hand-set step
      count stays), keeps a _GED's aiDispHeight / aiDispPadding at
      Displacement (zero value 0, autobump on when it becomes _GED).
      `_sc_bed_look` swaps a bed between `mossGreen_SG` and
      `MOSS_DISP_SG` ("mossGreenDisp_SG": the same mossGreen_MAT with
      `_ml_disp_look`: world aiNoise cushions 2.5 cm + fibres 5 mm x
      aiRange of mossData B 0..0.25) when both exist; Moss Look makes it
      when a layer is _GED and MtoA is loaded.
    - **Numbers** (rock _GES + box + floor, Normal): simple 5.2k quads,
      default 7.3k, lumpy 8.6k vs the carpet's 34.5k; 1.8 s / 2.4 s vs
      4.2 s; ~140 UV shells for ~46 tiles of area; UV scale median 1.00
      (p5 0.97, lumpy 0.90). Height spread simple 0.03 dm, default 0.16,
      lumpy 0.24; lumpy's tallest 1.3 dm (H 0.25). Cage detail 1 ~5x the
      faces; GEP ~4x.
    - **Speed pass (2026-11-09, "faster, snappier"):** a live edit
      (Coverage, Thickness, Lumps, Edge roll, Growths) ~0.85-1 s, was
      ~1.4-1.8 s (Bumps / Growths a full relayout, see Grid). `_domes`
      reads `_near_domes` (per grid cell, the domes of it and its 26
      neighbours, cached: 27 lookups a point before); `_dome` snaps with
      `closest(c, far)` (1.75 cells: `_SurfaceQuery` / `_MiRestQuery`
      take a reach, a far-off search was ~0.2 ms); `_mi_mat_uvs` checks
      clashes only in the cells the new quad spans (exact: a quad holding
      its centre, or a centre inside it, is filed there) with the bounds
      worked out once (0.9 -> 0.5 s on 12k quads). Same mesh, points and
      UVs as before, bit for bit. Left: the cold first build (~4 s, the
      field and rest surface shared with the carpet), Seed and Cage
      detail edits (a new layout, ~1.7-2.2 s).
    - Carpet / Clumps unchanged: equal to the previous toolbox exactly on
      faceted surfaces; on a smooth rest surface Maya's queries differ in
      the last bits by call order (~1e-7 dm), whichever toolbox runs first.
    - A dense triangulated scan whose triangles don't all pair is split
      whole (4x its faces): the mat then follows that density.
  - **Specks** (the user, same day: "tiny bits of moss that I could toggle
    on and off ... panels of glass ... bits of dirt or tiny bits of moss
    that have fallen down and stuck to a window"): layer type "Specks",
    debris kind 6, keys `specks` (clusters per square metre, 0 in
    `DEBRIS_DEFAULTS`), `speck_size`, `speck_dirt`, `speck_cluster`,
    `speck_spread`; type defaults Slope limit 90, Edges 0. Parts `specks` /
    `dirt` (`mossSpeck` / `dirtSpeck`, stacked). `_DebrisBuild` keeps a
    `_MossDetail(None, ms)` (no bed; strand length = speck size) and
    `_specks` calls its `_shoot` per moss speck; `_dirt` is a jagged flat
    fan (5-9 sides, slight dome, disc UVs) lifted 0.2 mm. The slope cut is
    `cos(limit) - 1e-6`, so a limit of 90 keeps upright faces.
  - `_mi_drop_repeats` cleans faces that repeat a vertex (the moss bed
    makes a few on the porch scene; Maya drops them and `assignUVs` fails).
  - Not done (phases agreed with the user): bundles / variants per layer (palm, jungle foliage, pine cones; the
    user's own meshes as a layer type) (4), group presets (5); converting
    an old mossPatch / ivy / debris group into a scatter group.
  - Tests: `tests/test_scatter.py`, `tests/gui_scatter.py` (pictures in
    `tests/_out/scatter`). Mat: `tests/test_moss_mat.py` (quads, rolled
    edge under the surface before and after a full displacement, cost vs
    the carpet, UVs, naming, Arnold when MtoA loads, Carpet / Clumps vs
    UNLOK_OLD_TOOLBOX), `tests/gui_moss_mat_pics.py` +
    `run_gui_moss_mat_pics.mel` (pictures in `tests/_out/moss_mat_pics`:
    cage wire, smooth preview, a Python-displaced copy).
- **Moss and Ivy** (Modeling tab; the user, 2026-11-03: "nice clumps of
  jungle moss ... on top of rooftops, or growing up in little crevices
  interacting with geo, or ivy growing up columns of shacks"; then "bunches
  of dry grass, scattered leaves, small piles of leaves and tiny clumps of
  moss" with a greenhouse-roof reference: the Debris kind). Engine
  `moss_build` / `ivy_build` / `debris_build` (via `mi_build`, which runs `_roof_udims(...,
  order=MI_UDIM_ORDER)`); scene side `grow_moss_ivy`, `update_moss_ivy`,
  `rebuild_stale_moss_ivy`, `bake_moss_ivy`, `mi_selection` (old groups
  still regrow through these; the panel is now Scatter, above).
  - **Scene:** one group per patch / plant, `mossPatch####_GRP` /
    `ivy####_GRP` / `debris####_GRP`, with `unlokMossIvy` JSON (kind, settings, version,
    `targets` uuids, ivy `seeds` as {"t": target uuid, "p": its local
    point, "w": world}, so Regrow follows a moved post). Parts are direct
    children tagged `unlokMossIvyPart` / `unlokMossIvyVerts`
    (`MI_PARTS`: moss `mossGreen` + `mossStrand` + `mossSpore`, ivy
    `ivyStem` + `ivyLeaf`, debris `grassDry` + `leafDry` + `mossTuft`), all with `unlokUvReady`, the stacked ones (`MI_STACKED_PARTS`)
    with `UV_STACKED_ATTR`. Grow = UndoChunk (group, JSON, seed planes),
    fill in NoUndo (`_rope_fill`); live edits NoUndo; a redo's seed planes
    are regrown by the panel's Redo job (`rebuild_stale_moss_ivy`, baked too:
    Bake renames the attr to `unlokMossIvyBaked`). An empty part gets a
    hidden 4-vertex placeholder (not stale). Sizes are metres
    (`scene_m_per_unit()`).
  - **Surfaces:** `_MiSurface` = closest point over all targets
    (`_SurfaceQuery`) + nearest ray hit (`closestIntersection` with accel
    params, flat face normal). With 6+ meshes a grid of their world boxes
    (cell = the median mesh's size; `_near`) picks the meshes a query
    looks at: Python loops over every box cost more than the queries on a
    wall of 60 stones. `_MiSampler` samples area-weighted points from
    `_mi_triangles` (world triangles, cached in `_MI_TRIS` by
    `_mi_mesh_key`: shape, counts, matrix, bbox).
  - **Rest surface** (the user, 2026-11-05: carpet moss followed the
    facets of meshes that are smooth at render time, and on corrugated
    roofs it broke up with gaps; "pre-subdividing for layout is heavy,
    find a smarter solution"). `moss_build` swaps the surface for
    `_mi_rest_surface(surf, s)`: each mesh's `_MiRest` (`_mi_rest`, cached
    in `_MI_REST` by mesh key + smooth + bridge + cap) in its place, or
    the mesh itself when nothing changes (a plain `_GEP` box builds as
    before). Its `rest_key` goes into every moss cache key
    (`_mi_surf_keys`), its `sample` feeds `_MiSampler`, its points /
    triangles / corners / curves feed `_MossBed` (`_mi_surf_topology`).
    - **Which meshes are smooth:** the per-layer **Surface** setting
      (`MOSS_SURFACES` Auto / Faceted / Smooth, `_mi_rest_smooth`); Auto
      reads the name's last token through `ur_base_suffix_of`:
      `MI_SMOOTH_SUFFIXES` (_GES, _GED, _GEV) are subdivided at render
      time, _GEP and anything else stay as modelled (`_mi_subdivided`).
    - **Smooth, no polySmooth** (`_mi_limit`, `_mi_cc`): one Catmull-Clark
      step in Python, then the limit masks on that all-quad mesh: exact
      limit points at every vertex, edge middle and face centre, limit
      normals from the subdivided quads, open edges as creases (the
      render's rule). A coarse cage (up to `MI_REST_REFINE` face corners)
      takes one more step (`_mi_cc_mesh`: 4x the exact points; the
      interpolation between them sagged 1.6 cm inside on a 1 m cube, now
      ~5 mm, polySmooth div 3 as the reference); its triangles keep the
      mesh's face ids (`parent`), so picks and masks still work. Between
      the exact points each triangle is a curved patch (`_mi_curve_at`:
      Phong tessellation, alpha `MI_REST_PHONG`, plus edge bumps 4 l_i l_j
      and a face bump through the exact face-centre / diagonal point), so
      the patches meet along shared edges (an edge's curve depends on its
      two ends only). The bed's grid points are mapped onto it
      (`_record`); `_coverage` tests points on it (`_mi_flat_bary`: flat
      points inside a curved surface read as buried). The query mesh
      (`item`, an in-memory MFnMeshData) is the patches tessellated at
      `ceil(sqrt(dev / MI_REST_TOL))` (<= 8, shared edge points).
    - **Lifted to the level-2 mesh** (`_mi_render_lift`): the exact limit
      is inside what a render or smooth preview at 2-3 levels shows on a
      convex part, and thin moss on it sank under the preview (a 1 m _GES
      cube: 25% of its top's moss showed at level 3, 3% at level 2). Each
      exact point moves along its normal to its level-2 point (the step's
      own V / E / F next to their limits; x 1/4 from level 1 on a big
      mesh): 99% shows at both levels. The rest sits ~1.5 cm over
      polySmooth div 3 on that cube (0.5 cm on the 8-sided post), never
      under it.
    - **Relief bridging** (`_mi_bridge`, a ball closing): bridge = 3 R x
      (1 - Surface detail), cap = 0.6 R x (1 - Surface detail)
      (`_mi_rest_scale`). Vertices of finely made surfaces (shortest edge
      <= bridge) near a concave spot rise along the broad normal (the
      faces' within the ball) until a ball resting on any of their faces
      (`leans`: broad, vertex and face normals) clears the surface
      (bisection); deeper than 2 cap fades out (a gutter stays a gutter);
      faces turned down are left; a vertex with its own mesh above it
      within the lift (a lap) stays. Corrugations fill to the crests,
      crests stay put. Surface detail 1 = no bridging.
    - **Panel:** Scatter's Moss layers have a "Surface" section (Surface,
      Surface detail; `SC_LAYOUT["Moss"]`) before More; both are look
      keys in `MOSS_DEFAULTS` (Auto / 0.5), so old groups get them when
      they next grow (a layer read back from its parts stays as it was
      until then; Faceted + Surface detail 1 reads every mesh as
      modelled, the seam and lap fixes still apply).
    - **Seams** (T-junctions, in `_MossBed._mesh`): faces on
      different planes cut a shared edge at different grid lines, so
      their points lifted differently and cracks opened along every fold
      of a corrugation. Each fold edge (both faces have moss, different
      plane keys) gets every grid crossing of both faces (`seams`), and
      `_seam_poly` keys points on it ("e", shape, lo, hi, s) / corners
      ("v", shape, id) and inserts the other side's crossings. Coplanar
      neighbours share one grid and are left alone (cost).
    - **Covers and pieces** (the side laps had no moss at all: a
      candidate on the lower sheet under the lap is pressed under the
      upper one (obstacle 0.5 mm, margin -1), and the upper sheet's points
      1.4 mm higher read it): `_moss_obstacle` also stores what covers a
      candidate (`memo["oc"]`, `_MiSurface.ray(piece=True)` -> the hit's
      connected piece, `_MiSurface.piece`, labels per vertex in
      `_MI_PIECE_LABELS`). A block's candidates covered by the piece its
      face is on are dropped (`_not_under_own`: the sheet lapped over, a
      rail's top over the board under it), and a point with room above it
      (its room ray, cast whenever a pressed-under candidate `hid` is in
      reach) skips pressed-under candidates (the lower sheet up to the
      lap's edge, the board beside a rail); points under the cover keep
      reading them.
    - **Numbers** (`tests/test_moss_surface.py`, same machine, other jobs
      running): corrugated Clean gaps 15.7% -> 0.9% (rays down over the
      middle), Makeshift 27.8% -> 0.7%, no cracks on fine lines across
      the corrugations and laps; build 23 s -> ~27 s Clean, 52 s -> ~63 s
      Makeshift (more moss, seams, bridging; the rest surface is cached,
      a Coverage edit ~6-8 s). _GES cages: moss within the bed's thickness
      of polySmooth (0% of points under it with the level-2 lift), 1.7 s
      vs 2.5 s for the same cage as _GEP. Clumps on a beam's top drape
      down its sides (0 before).
  - **Moss spots** (`_moss_spots`, at `_moss_reach(R)` = max(2 R, 10 cm):
    crack probes need room): per spot shelter = hemisphere rays (low first)
    that hit within 2.5 RA; six ways round, probes at 0.2 / 0.45 / 0.9 RA
    cast down: where the surface first falls away, a far probe that hits
    again = a crack (between boards: adds to shelter), else an edge.
    Without the crack test a gap between planks read as two exposed edges.
    `moss_score`: 0.5 x up-weight x (1 - edges x edge) + crevices x 0.62 x
    shelter x (0.6 + 0.4 up) + patchiness x 0.55 x noise.
  - **Field** (`_moss_field`, `_moss_margins`): candidates scattered at
    4.5 per Clump size area, each tied to the spots within 1.6 RA (weighted
    by distance, normal agreement and being on the same level: a rail's top
    must not read the board under it) plus a fine noise for a ragged edge;
    cached in `_MI_MOSS_CACHE`, so Coverage and the weights only re-score.
    `_moss_margins` gives each candidate (margin, shelter, edge): margin =
    field + 0.3 x Messiness x noise - (1 - coverage); a candidate covered
    within 5 cm above (`_moss_obstacle`, a rail on a board) keeps that
    distance (`ob`) and the bed stays 0.6 x it under. `moss_clumps` (the
    old cushion packing) is only kept for its count and the tests.
  - **Directed moss** (the user, 2026-11-03: "more controlled / directed
    clumps in certain areas instead of overall coverage"): `mi_moss_picks`
    reads the selection: vertices / edges = clump centres (stored as
    `seeds`, like ivy's, following the mesh), faces = `faces` {mesh uuid:
    [face ids]} (`mi_face_mask` on Regrow; ids, so a topology change
    breaks it). Triangles carry their face id (`_mi_triangles`), the
    sampler's `pick` says which mesh / face, candidates keep both, so
    masking is a re-score (cached field). Seeds: margin = 0.7 (1 - d /
    Spread) + 0.3 (score - 0.5) + noise - (1 - coverage) + 0.3, d to the
    nearest seed (grid); shelter still stretches a clump along a crack.
  - **Bed** (the user, 2026-11-03: "the most procedural route ... the best
    looking moss with obviously controllable tiers of detail"; reference:
    jungle moss = mats and carpets, cushions and turfs where lit, wefts and
    pendant curtains where shaded, setae with nodding capsules over it):
    `_MossBed` is one continuous shell, not cushions. Per target triangle a
    grid on its plane (axes from the normal only, `_moss_axes`: coplanar
    faces share one grid, so no seams), cell e = Tile size / k (k =
    ceil(tile / (cell x R)), `MOSS_DETAIL[0]`): every cell sits in one UV
    tile, UV = (u - tile index x tile) / tile, so the bed takes a tiling
    texture and displacement. Cells are clipped to the triangle
    (`_moss_clip`); points keyed (plane, i, j) or by quantised position on
    clip lines. Per point: kernel over the candidates within 1.3 R
    (`_record`), margin -> c / pr smoothsteps, h = H x pr x (0.5 + 0.5 c) x
    (0.75 + 0.6 shelter) x taper, x Size variation noise, x Lumps billow
    (|noise| at 0.7 R and 0.32 R, `_moss_noise3`: packed cushions with
    creases), less a tuck (the edge goes just under the surface). Faces
    with no point above the surface are dropped. pr ramps over a margin
    of 0.3 and is square-rooted: the edge slopes up and rounds over (over
    0.13 it rose within one cell: a cut-paper edge at Normal).
    - **Edges:** lift direction = corner normals (faces within 35 degrees,
      `MOSS_SMOOTH`, blend: a stone). A sharp edge within 0.6 R rolls the
      lift half way to the next face (both sides meet over it: moss rolls
      over plank edges, fills inside corners); an open edge, a masked face
      or a face facing down tapers it under.
    - **Covered faces** (fix 2026-11-03: moss went into the wall): each
      face is tested at 7 points (`_covered`: a ray out hits within 1 cm or
      hits a back face = inside another solid). All covered = buried (no
      moss, and neighbours run straight on into the corner instead of
      rolling onto it); some = partial: that face's points, and its
      neighbours', each cast a ray along their lift (`room`, stored in the
      record) and stay under 0.6 x it (a board half under the wall, a rail
      across a board). The centroid test alone missed half-covered faces.
    - **Speed:** blocks of ~0.6 rk cells are skipped unless a candidate in
      reach can show moss (exact bound on the margin), and the layout
      (points, lift directions, kernel weights, noise; block polygons) is
      cached in `_MI_MOSS_BEDS` (4 layouts, with each mesh's covered faces
      `_coverage` and each block's buckets `bks`), so Coverage, Thickness,
      Lumps and the weights redo the sums only. A new block's candidates
      are the buckets within reach of its points (`_local`, box test per
      bucket) as flat tuples (`flat`). The finished bed is kept too
      (`_MI_MOSS_BUILT`, 2, keyed on every setting but `MOSS_DETAIL_ONLY`),
      so Strands, Strand length, Droop and Capsules only redo `_MossDetail`
      (~3x faster). `_MI_MOSS_CACHE` (spots, field, creases) keeps the last
      `MOSS_CACHE_KEEP` entries, refreshed on use (`_mi_cache_get`): before,
      a hit didn't count as a use and each kind trimmed to its own size, so
      a few moss layers edited in turn pushed each other out. `MOSS_MAX_CELLS` grows the cell
      on huge areas (`capped`).
    - **Speed pass (2026-11-05, the user: "it's so laggy"):** Patch size
      no longer redoes the rays: spots and candidates are cached without
      it (`_moss_spots_base`, `_moss_field_base`; Patch size only adds its
      noise on top, `_MossCands.base` keys the bed layout), ~14 s -> ~4 s
      at High. Bed records are lists in `self.rl` looked up by int id
      (noise slots 9-11, room 12), `_value` sums in C (`sum(map(...))`),
      `_emit` / `mesh()` look up with `map` and only loop for new points;
      shoots: ribbon / star templates (`_tpl`), the vector maths written
      out, `_rand12` unrolled. Tried and dropped: reusing a triangle's
      shoots when its corners didn't move (Slope -1 s, Coverage nothing:
      its edits move nearly every point; +0.25 s and the memory on every
      other edit). `GcPaused` (Python's cycle
      collector off) round `sc_regrow`'s and Moss & Ivy's builds: the
      collector walking the cached records cost ~1 s an edit.
      `_mi_drop_repeats` checks in C. Scatter panel: once an update took
      over 0.3 s, a slider drag updates once, on release (`_dragging`).
      Check a change with `tests/bench_moss.py` (`--nogc`, `--profile`,
      `--hash`): old and new in one process, topology and UVs must match
      exactly; points match to ~1e-9 (the engine isn't bit for bit the
      same from one run to the next, ~2e-10, even old vs old).
    - **Speed pass 2 (instanced shoots, coarser bed, drag draft):**
      - **Shoots as instances** (setting `shoots`, `MOSS_SHOOT_MODES`
        Instances / Mesh; the Moss type's "over" sets Instances, an old
        layer without the key grows instances too; since 2026-11-09 a NEW
        layer gets Mesh via `MOSS_NEW_LOOK`, so its shoots are publishable
        geometry, and `sc_preset` keeps it). `_MossDetail(inst=)`
        for `MOSS_INST_KINDS` (tuft / shoot / leafy) records each shoot
        (root, axes x = the turned perpendicular, y = up the shoot, z,
        length, index = stack x `MOSS_INST_TURNS` + turn bucket) in
        `self.I` instead of meshing it; `shapes()` builds the unit-length
        protos (8 turns of the bend per stack). Scene (in the control
        group, `_sc_shoot_names`): a `<mat><tag>Shoots####_GRP` transform
        (`SC_SHOOTS`, key "<layer>/shoots", `sc_shoots`, `_sc_shoot_nodes`)
        holding a hidden `...ShootsShapes####_GRP` of
        `<mat>_C_shoot<A..>####_GEP` protos (`SC_SHOOT_SHAPE`
        order, strands UVs: they share the strands part's tiles, or take
        its key when there's no strands part), a hidden particle shape
        (API1 `MFnParticleSystem.emit`, rotationPP / scalePP / indexPP and
        their "0" copies, `saveInitialState`, not dynamic: the data is
        saved with the scene and survives frame changes;
        `...ShootsPoints####Shape`, made as `unlokShootPointsTmp#` and
        renamed after the emit and instancer: `MFnParticleSystem.emit` goes
        by name, and a Ctrl+D copy's rig has the original's names, so its
        instances went into the original's; new nodes' paths come from
        `_sc_under`, not `long_name`) and a `particleInstancer`
        `...Shoots####_INS` (first child: the crash fix). Rotation: XYZ Euler from
        the axes (`_mi_euler_xyz` / `_mi_axes_xyz`, row-vector: matrix
        rows = axes). Read back by `_sc_read_shoots` (the freeze fix's
        readback, `_sc_shoots_sig` in `_SC_WROTE`). `sc_owner` walks up
        to the shoots node; `sc_remove_layer` deletes it; Bake
        (`_sc_bake_shoots`) makes a new strands mesh with the shoots as
        real geometry (`moss_instances_mesh`) in the old part's name and
        shading, in the undo queue (one Ctrl+Z brings the instancer back).
        `MOSS_MAX_INSTANCES` thins like `MI_MAX_VERTS`.
      - **Coarser bed:** High 0.2 R (was 0.14), Hero 0.13 R (0.09); at
        `MOSS_BED_SMOOTH` (Normal / High / Hero) the bed part is named
        `_GES` (`_sc_bed_suffix`; Arnold's Catmull-Clark 1 step set when
        MtoA's attrs exist), Proxy stays `_GEP`. Tests must fetch the
        bed part's name from `sc_parts`.
      - **Drag draft:** on a slow layer (`_slow`) a held slider grows the
        moss layer as a draft (`sc_update(..., draft=True)`, "Draft (let
        go for full detail)") and `_drag_draft` makes the release regrow
        it in full (`sc_regrow(only={lid}, draft=False)`); other types
        still wait for the release. Skipped while global Draft is on.
      - Numbers (`tests/bench_moss_scene.py --detail High`, the bench
        boulder): first grow 17.9 s -> 13.0 s, Coverage 4.2 -> 2.7 s,
        Patch size 5.2 -> 3.1 s, Strands 2.6 -> 1.5 s; bed 87.8k -> 58.1k
        faces; strands 467k faces -> 11.6k hanging-strand faces + 45k
        instances; .mb 47.8 -> 14.4 MB, .ma 95.6 -> 23.1 MB.
        `tests/test_moss_instances.py` checks the convention, every
        instance's matrix, tiles, Mesh mode, file size, reopen, Bake and
        undo, old layers and removal.
  - **Realism pass (2026-11-05):** new keys in `MOSS_DEFAULTS` default to
    what moss did before (exposure / feather / strays / ragged /
    clump_merge 0, shoot_form Star, spill 0), so old groups and Moss & Ivy
    regrow exactly as before (`test_moss_realism` compares against an
    older toolbox with `UNLOK_OLD_TOOLBOX`). A NEW Scatter Moss layer gets
    `MOSS_NEW_LOOK` through `SC_TYPES[...]["new"]` (applied by
    `sc_start_settings`: new layers and the panel's start values); Leaves / Leaf piles / Jungle leaves get
    `on_moss` True the same way (`DEBRIS_DEFAULTS` False). Panel: Bare
    ridges + Floor spill in "Where it grows", an "Edges" section (Soft
    edges, Ragged outline, Stray tufts), Merge in Clumps, Shoot shape in
    More, Rest on moss in the leaf types' More.
    - **Bare ridges** (`exposure`, `_moss_exposure`, cached per spots):
      per spot the weighted convexity over `RX = max(3 RA, 30 cm)`
      (`sum w (n_q - n_p).(q - p)/d`, a sphere gives RX / 2r), plus
      0.3 x up x min(1, conv / 0.3) for rounded tops, compared with the
      average of the spot's object (the smallest bbox it's in): only
      what's more convex than its object goes bare, so a smooth pebble
      keeps its moss and a block's edges don't. Subtracted from the
      scores in `_moss_margins` (x 0.9, patchy with the spot noise).
    - **Ragged outline** (`ragged`): a domain warp on the spots' patch
      noise and the candidates' fine noise (plus a 38x fray), more edge
      noise in `_MossBed` (`self.rn`) and in `rag`. It's part of the
      spots / field cache keys (patch entry is a (patch, ragged) tuple).
    - **Soft edges** (`feather`): `_MossBed._value` widens the c / pr
      ramps and blends sqrt toward pr^1.2; `_MossDetail.build` thins the
      shoots by (1 - 0.8 fe (1 - core)^2).
    - **Stray tufts** (`strays`, `MOSS_DETAIL_ONLY`): `_MossDetail.strays`
      after build: out from the bed mesh's open edges (chance 0.35 st
      per edge) 0.35-2 R, a tuft of 2-12 shoots via `surf.closest`.
    - **Merge** (`clump_merge`, Clumps): wider (x1.3), packed closer,
      lower (x0.55 at 1), mounds flattened, domes blend to a low bell.
    - **Shoot shape** (`shoot_form`, `MOSS_SHOOT_FORMS` Star / Leafy,
      `MOSS_DETAIL_ONLY`): Leafy = `_leafy_shape` (thin stem, 7 pairs of
      cupped leaves, open low down, a bud at the tip, star UVs), 1.5x
      the shoots. Always laid out like instances; Shoots Mesh makes them
      real at the end (`mesh_leafy`, the geometry Bake makes).
    - **Floor spill** (`spill`, metres): `_moss_floor_nodes` (bbox under
      0.16 of its width) only when there are other surfaces too;
      `_moss_spill` gives each floor candidate its distance to the
      nearest non-floor candidate; past Spill no moss, inside it a bonus
      tapering off.
    - **Rest on moss** (`on_moss`, leaf debris): `sc_build` collects the
      group's moss beds grown so far (`rest`, lifted 0.4 x strand
      length when tall); an on_moss layer gets them as `rest_on`
      (`debris_build` -> `s["_rest_on"]`) and `_DebrisBuild._field` lays
      them into the drop stack (`_MiDropStack.lay_mesh`: points, face
      and edge middles). Its cache key includes the beds; read back is
      skipped when a moss layer was just grown.
    - **Shading data:** moss meshes' points are `_MiPts` (a list with
      `.col`) and `_sc_write` writes them to the colour set
      `MOSS_COLOR_SET` "mossData" (`_mi_write_colors`, `aiExportColors`
      on), read back by `_sc_read_part`. R: carpet a patch-sized noise,
      Clumps a random per cushion, strands / capsules a random per item;
      G: height in the bed (hf / H); B: core (0 at a patch edge).
      Instanced shoots have none: the look uses aiUtility "obj" (a
      random per instance) as the aiUserDataColor default.
    - **Moss Look** (`sc_moss_look`, panel button by Bake): one Ctrl+Z;
      mossGreen_MAT / mossStrand_MAT / mossSpore_MAT (+ `_SG`) made once
      per scene (aiStandardSurface networks `_ml_arnold_look` with MtoA,
      plain standardSurface without), on the Moss layers' bed, strands,
      shoot shapes and capsules. Noise sizes in metres (`_ml_noise`).
    - **Instancer first** (`_sc_shoots_order`): Maya crashed (fatal) freeing
      an undone shoots node whose particle shape came before its
      instancer; the instancer is reordered to the front when made and
      when an older node is rewritten. `test_moss_instances` checks it.
    - **Bed budget** (`_MossBed`): `MOSS_MAX_CELLS` / the estimate use the
      area of the faces the layer may grow on (`_moss_area(nodes, faces)`),
      not the whole meshes: a rock plus a ring of a huge floor got a capped,
      coarse bed.
  - **Detail** (`MOSS_DETAIL`: cell x R, detail on, rate, kind, capsule
    sides, hanging segments): Proxy = bed only at 1 R cells; Normal 0.3 R,
    tufts (5-point leaf stars on the bed); High 0.2 R, shoots (2-segment
    stem + 4-leaf star); Hero 0.13 R, leafy shoots (3 segments, two
    whorls). `_MossDetail` samples the bed's exposed faces area-weighted,
    keyed by (plane, cell, triangle) so a tier's shoots keep their place
    through edits. Hanging strands (ribbons bent down by gravity) where the
    bed faces sideways or down (normal y < 0.35), Hanging x their length,
    gathered into curtains (noise at 4 R, longer mid-curtain, a sine
    wave down each; an even fringe read as grass);
    capsules (seta ribbon + spindle capsule nodding 0.5 - 1.6 rad) in
    noise clusters where the bed is full and up-facing. Parts: `strands`
    (`mossStrand`: stems u 0..0.1, hanging u 0.12..0.22, stars round
    (0.625, 0.625)) and `capsules` (`mossSpore`: setae u 0..0.1, capsules
    0.2..1), both stacked. Thinned to `MI_MAX_VERTS`.
  - **Ivy walk** (`ivy_walk`): step = leaf x `IVY_STEP` (Detail); steer
    towards "up the surface" swung by a slow noise (Wander) with weight
    Climb x 0.6 (a per-step turn made vines spiral round posts), plus a
    small fast meander, plus a push from other vines' points (grid, cell
    1.4 leaf); a forward ray that hits a front face climbs onto it, else
    snap by closest point; a snap farther than 0.35 step = rounding a
    convex edge (normal = from the surface to the stepped point). Gravity:
    within 5 steps of an edge heading down, or under an overhang, a vine
    may let go and hang (free points, swaying, re-cling on a hit). Branches
    two levels deep, thinner (0.7) and shorter. Climb variation
    (`climb_var`): each main vine's Climb x cf, cf = 1 + var (2 r - 1)
    (`_rand12(seed, si, k, 56)`), the 9th queue element, inherited by its
    branches; cf < 1 also turns its start (1 - cf) x 1.4 rad off up (vines
    start up the surface, so a weaker pull alone changed nothing).
  - **Ivy auto seeds** (`_ivy_auto_seeds`; the user, 2026-11-05: "it's
    only scattering them on a few of the columns I've got selected" /
    "they seem to all clump together on one or two columns"; it used to
    take the globally lowest 12%, so the lowest-standing columns got them
    all): per sampler part (mesh), side-facing samples (area-weighted
    count; Per mesh: count x 30 each), a ray down from each: grounded =
    an upward-facing hit (n.y > 0.3) within 30 cm (inside or under a slab
    doesn't count); a mesh with none grounded takes its lowest 12% of
    those with no hit below; none at all (tops only) = anywhere.
    `vines_by` (`IVY_VINES_BY`): In all = `_ivy_spaced` over every pool
    together; Per mesh = Vines each (fewer past `IVY_MAX_AUTO_VINES` in
    all). `_ivy_spaced`: best candidate, each the farthest from those
    picked among 1 + 12 x `vine_spacing` random candidates (>= 0.999: all
    of them, farthest first); painted in (rank < 0) first when enough.
  - **Ivy mesh:** `_ivy_finish` smooths and lifts centres a radius off the
    surface (pushed out when closer). Stems `ivy_stem_mesh`: tapered tubes,
    seam towards the wall, tip cone; UVs via `_ivy_columns` (pieces no
    taller than a tile in columns, short ones stacked, one density
    bisected to fit Stem tiles). Leaves `ivy_leaf_mesh`: a narrow stalk row
    at the stem (v 0..0.2) then the blade rows; above Proxy the blade is cut
    to `IVY_OUTLINE` (heart-shaped base whose lobes reach back, pointed
    tip; no alpha needed), 5 columns from Normal, UVs following the outline
    undistorted (u 0.14..0.86); cupped (mostly x^2, a soft midrib), tip
    curled back, a little wave. Blades lie over the surface like shingles
    (small outward component), petioles 0.18..0.58 leaf long, leaves 0.7..1.3x
    from tip to old growth. The blade tilts out if a ray along it hits the
    wall; quads wound so the blade faces out.
  - **Debris** (`_DebrisBuild`; kind "Debris", `DEBRIS_DEFAULTS`): the
    moss's field (`_debris_field` = moss settings with clump size
    `DEBRIS_FIELD_R`, so picks and faces work the same; mi_build output
    counts are `leaves_n` / `tufts_n`: `_roof_udims` takes any key named
    like a part for a mesh). `_spots(density, kind)`: per candidate,
    density x its area share x a ramp on the margin, jittered and snapped,
    never under something (`_moss_obstacle`) or onto a face turned away (a
    rail's underside lies flush on the board: blades lifted into it).
    - Grass `_bunch` / `_blade`: blades per 10 cm square by Detail
      (`DEBRIS_DETAIL`, x Fullness; fewer, wider blades below Hero), each
      started half its length back so its middle is in the bunch, walked
      over the surface by closest point (curl per step), lifted onto the
      mound (layer; 0.2 x bunch radius high: higher read as separate bales)
      plus an arch; off an edge (closest point to the side,
      or a face turned away) it steps level past it, then droops; every
      free step casts a ray and the blade ends against what it hits (they
      cut through the wall's corner before). Ribbons narrow to the tip.
    - **Loose piles** (`grass_pile`, Pile height; the user, 2026-11-06:
      "trying to scatter some loose piles of dry grass but its just flat
      clumps"; the flat mound above tops out at 0.3 x the radius):
      `_grass_pile` when > 0. A lumpy dome (2nd / 3rd harmonics on outline
      and height, by Messiness) Pile height x radius high; blades =
      Detail's rate x Fullness x 1.2 over the dome's outside area; each
      blade's middle at a random point in it (height fraction 1 - 0.85 r^2:
      most near the top), found by a ray out from the bunch's centre (a
      wall in the way: the heap banks up against it), heading as the flat
      bunch's (`_grass_heading`: crease / downhill / Combed), laid along
      the dome there and tipped by +-(0.2 + 0.3 Messiness) rad; then
      `_grass_walk` both ways from the middle: curl and sag
      (0.04 + 0.1 Droop rad a step) in the air, a ray per step (and per
      slide), meeting a surface it lies along it, `_grass_out` keeps every
      point over the surface (closest point). 0 = the flat bunch exactly
      (`DEBRIS_DEFAULTS` 0, so old groups and Moss & Ivy Debris build as
      before); a NEW Grass layer gets 0.6 (`SC_TYPES` "new"), presets Dry
      grass 0.6, Loose piles 0.9, Grass mat 0. Cost about 2x the flat
      bunches (yard: 1.9 vs 0.9 s).
    - **Grass inside boxes** (the user asked, 2026-11-06): the floor under a
      box standing on it is sampled like any other, so bunches grew inside
      the box (test_grass_pile's yard: ~2k points in the step), and blades
      of bunches beside a wall / step / brick started or walked under it.
      `_in_solid(c, n, R)`: a ray out along n leaves through a back face
      AND three of four sideways rays do too (the up ray alone would also
      skip grass under a single-sided roof plane, whose back it hits):
      such a bunch (flat or pile) isn't grown. `_blocked(a, b, up)`: the
      front of a face standing up from the surface (normal within 60
      degrees of up's plane; ground-like faces, a chord cutting a rounded
      crest, don't count) between a and b. A flat blade whose start is
      blocked from the bunch's centre is dropped; a walking step that is
      blocked ends the blade there. Yard: 2,167 -> 7 points inside, 437
      -> 0 blades through; blades in the open are unchanged (open ground
      builds exactly as before); flat grass costs ~40-60% more (a ray per
      step: ramp 0.22 -> 0.35 s). Other debris kinds (tufts, specks) don't
      have the check.
      Like every debris kind, piles only see the group's surfaces: a mesh
      left out of them (or not added) is passed through, and a tall pile
      beside it shows that more than a flat bunch did (test_scatter's
      left-out beam check uses Pile height 0 for that reason).
    - Leaves `_leaf`: rows x columns over a cut outline: a stalk row
      (`DEBRIS_STALK`), then an ovate blade (half width 0.19 - 0.31 x
      length; the first version, near round and cupped, read as crisps),
      even columns for a midrib line, cup / ends / fold / crumple by Leaf curl, rests on its lowest
      point (a quarter flipped), pushed out of curved surfaces. Piles
      `_pile`: mound 0.3 R high, leaves sorted bottom first, tilted along
      the mound, plus strays. Tufts `_tuft`: 2-5 `_dome`s run together (one at Proxy),
      each dome rings with sqrt profile,
      jittered rim tucked under, every point laid onto the surface by
      closest point.
  - **Panel:** steps Select surfaces / Grow (Moss | Ivy segment, presets,
    Grow button) / Look (one box of fields per kind) / Finish (Select All,
    Regrow, Bake). Selecting a group shows its settings and switches the
    kind; `_editing()` = selected live groups of the kind on show.
    Presets: `MI_PRESETS` + `unlokMossPresets` / `unlokIvyPresets`
    optionVars (seed and Start UDIM skipped).
  - Speed (GUI test): a whole shack roof (44 planks) at Normal ~13 s to
    grow (230k faces), a live Coverage edit ~5 s (cached layout). Three
    planks of Fruiting cushions: Proxy ~2k verts, Normal ~30k, High ~320k,
    Hero ~1M. Ivy 0.25 s.
  - Not done (ideas): following the meshes live (Regrow is manual), a
    click-to-plant picker (or changing a grown patch's picks: today picks
    are set at Grow), rootlets on the stems, moss on the ivy, caching the
    detail layer (High / Hero edits rebuild it), High / Hero speed on big
    areas.
  - Tests: `tests/test_moss_surface.py` (rest surface: suffixes, _GES
    cages vs polySmooth, corrugated roofs' gaps and cracks),
    `tests/test_moss_ivy.py` (the engine; its old panel's GUI test
    went with the panel).
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
    squares layout (`_mesh_bundles`, `_similar_blocks`, `_smallest_rect`,
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
    **Lay Out Selected** (`lay_out_selected`) is the same `_lay_out`
    without the unwrap, for the user's spot-fix loop (Auto UV + Lay Out,
    hand clean-up, Lay Out again, Keep UVs, next). Selections outside the
    asset's root (`_lay_out` checks the root, not just "an asset is
    loaded") stay in their majority tile (`_uv_tile`), one block.
    Component picks: `selection_items` gives faces, `shell_faces` grows
    them to whole UV shells (moving part of a shell would tear it), and
    `lay_out_together` takes {mesh: faces or None}. The tile comes from
    `face_tiles` of the picked shells (`free_tile_for(mine=)`), and the
    mesh's other shells' tiles count as taken (`also_used=`).
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
    - **The hierarchy decides** (simplified 2026-10-27 after the user
      found Check & Fix always reported moves that Fix never made, and
      Outliner moves that didn't follow): `follow_links` puts every mesh
      under a followed group where its closest followed group says, every
      time. Live, Check (`dry=True`) and Fix all call it, so a Check after a
      Fix finds nothing. (`changed` / `everything` are kept for callers.)
      - Material link: the whole mesh goes in.
      - Section link: into that section keeping its material; new meshes,
        and meshes that have left a followed material group (they only had
        that material because of the group), are sorted in by name /
        shader. Which material group inside the section is the user's call.
      - Under no followed group: left alone.
    - **Pins:** `unlokUdimPins` on a material set holds meshes put there
      by hand against a link (`assign`, the panel's New Group / New Section
      / Move to Section call `pin_overrides`). Each pin remembers the
      followed group the mesh was under (`unlokUdimPinVia`, uuid); dragged
      under another followed group, the pin is dropped and it follows. An
      old pin without it adopts the group it's under now. `link_groups`
      unpins what's under the groups (explicit wins).
    - **Retired:** the `unlokUdimFollowed` "where it came from" tag and its
      restore. Check listed every tagged mesh as a move while Fix left the
      tag alone (the stuck count), and a tagged mesh dragged to another
      group was sent back to its old set. Old tags are deleted on the next
      follow. After Ctrl+Z of a reparent a mesh follows whatever group it's
      back under.
    - **Sections survive emptying:** Maya deletes a set whose last member
      is deleted, so `prune_empty_groups` takes each material set out of
      its section before deleting it. Otherwise emptying a section deleted
      it and its group link, and meshes dragged back into that group were
      followed nowhere.
    - **Live:** `MDagMessage.addParentAddedCallback` notes the child path
      (`_reparented`, `_links_dirty`) and starts the refresh timer.
      `refresh` then runs `_follow_groups` in **NoUndo**. An undoable sync
      step would be redone the moment Ctrl+Z undid it.
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
      - The moves come from `follow_links(dry=True)`, the same rules Fix applies.
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
    - **Rigid, strictly** (the user's rule, 2026-10-28: "the only edits
      ... transforming it as a whole"): `_apply_layout` and
      `lay_out_together` write a Keep Layout mesh with `_move_whole`: the
      transform read off its biggest placed shell, applied to every UV of
      the mesh. Before, only the shells `_read_shells` kept were placed,
      so a collapsed / zero-area face (skipped as degenerate) stayed at
      the old UVs, rows away. `_read_shells` now keeps skipped shells as
      `_Dead(uv_ids)` markers, gathered per mesh in `caches["_dead"]` /
      `collected["dead_uvs"]`; on other meshes `_take_dead_along` tucks
      them into the middle of the mesh's biggest placed shell (only those
      UVs: a locked group's faces on the same mesh are never touched). A
      Keep Layout mesh split across two material groups takes its biggest
      group's transform for every UV. Lay Out Selected moves Keep Layout
      meshes as `_layout_unit` blocks instead of skipping them.
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
    - **Squares, now rectangles** (`squares`, the panel's default; engine
      default off). The user's correction (2026-10-27): "squared" meant
      tidy axis-aligned blocks, not squares; forced squares left long
      strips at the bottom of empty squares. `_group_squares` now returns
      rectangles via `_smallest_rect` (row widths from the widest piece /
      area bound up to a tile, `RECT_STEP` 1.08 apart, smallest area wins;
      `hints[key]` keeps the winning width as a multiple of sqrt(area) and
      later Fit attempts only try 7 widths near it). Blocks are
      `(udim, x, y, w, h, set, key)`; `_rect_of` replaces `_square_of`
      (`_smallest_square` / `_pack_square` are gone). Test building:
      Fixed density 18 -> 15 tiles, Fit rows 152 -> 160 px/m, wall blocks
      66% -> 88% full; Plan 0.36 s on 1,800 shells.
      `plan_layout` turns each group's pieces (after bundles / similar
      blocks / Keep Layout units) into compounds with
      `_group_squares`: the smallest block they pack into in rows
      (`_Shelves`: first fit by height over `_by_height`-sorted cells,
      PolyRaven-style; it replaced the skyline-with-gaps packer inside
      squares on 2026-10-27, same density and tiles on the test building,
      much tidier)
      (hints in `collected["_square_hints"]`), or whole-tile blocks filled
      first-fit plus a smallest block for the rest. A section's blocks are
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
      **Row order** (the user's first rule, restored 2026-10-28):
      `run_section` lays a section's blocks with a cursor that only moves
      right: materials in `_material_rank` order (`first_materials`
      bucket, then `material_order` patterns, then A-Z, then
      `last_materials`; fnmatch, comma separated, case-insensitive), each
      material's blocks biggest first into the open tile, then the next.
      Never back into an earlier tile (blocks used to go biggest first into
      any open tile, scattering materials; it costs ~2 tiles of 15 at fixed
      density). Own-UDIM buckets start a fresh tile at the bucket change.
      `align_columns`: a dry run (`dry_open` / `dry_place`, plain packers)
      lays every section; the one using most tiles gives `{key: start
      index}`, recorded where each material's first block LANDS (the
      cursor's spot was one off when the block didn't fit), and the real
      pass skips ahead (`skip_tile`, not counted as used) so each material
      starts no earlier than that column. Pinned / prefer / Hands-off
      groups keep their own tiles and don't move the cursor. Groups'
      blocks are computed once (`prepared`) for both passes.
      Reordering by drag: `UVCanvas._reorder_target` (plan view, over
      another material's shell: (key, after?) by which half of its box)
      -> `UVViewer.drop_material` -> panel `reorder_material`, which writes
      the full current order (`_material_rank`) with the move into
      `lay_order` and re-plans once (timer stopped, `_replan`). Own-UDIM
      materials keep their bucket; the status says so.
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
      good. **Remembered** (`_remember_largest` / `_recall_largest`, at
      Apply and after every Find; in the session JSON as `largest`): the
      top 6 with the uv set, `_largest_settings` (map size, padding,
      growth, orientation, defaults filled in: the plan's settings carry
      growth, the panel's don't), the material set names (TD % lives in
      them) and `mesh_fingerprint` of every mesh. A Find whose check
      passes answers straight away; otherwise it reads shells afresh
      (never `self._collected`, which a UV edit doesn't invalidate; the
      shell cache keeps unchanged meshes cheap).
      **Viewer after Apply:** `refresh` drops `_collected`, so Apply keeps
      `self._applied = (collected, plan, time)` and `open_viewer` shows it
      while `_plan` is that plan; with no plan in memory (a reopened
      scene) and a layout applied, it reads the scene itself up to
      `VIEWER_AUTO_READ` (400) meshes.
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

- **Quad Fill** (Modeling tab; the user, 2026-11-03: "an actually good quad
  fill hole tool ... bridge everything together with the right edge loops
  ... it should follow the surface", and "this doesn't make a new mesh ...
  like a super advanced bridge tool"). Engine `qf_plan` (pure maths on
  `qf_read`'s data), scene side `qf_selection`, `quad_fill`, `_qf_build`;
  panel `QuadFillPanel`, preview `QuadFillPreview`.
  - **Layout:** `qf_corners` scores every (start, side split) of an even
    loop: capped turns at the 4 corners, minus opposite-side length
    mismatch, minus 0.5 x |log cell aspect| (side-middle distances over edge
    counts; without it a circle got 1 x 7). Even holes are always a pure
    grid; odd ones lose one triangle at the sharpest corner first (all quads
    is impossible). Rings Auto = 1 for round holes (12+ edges, no corner
    over 50 degrees) and concave ones (a border turn under -26 degrees: a
    grid corner at a reflex vertex is a folded quad).
  - **Shape:** linear Coons (Follow 0) plus Follow x the normal part of two
    blended cubic lofts. Each loft leaves along its own chord laid into the
    tangent plane at that end (the border's inward direction over-bulged
    round holes' corners). Normals come from a quadric fitted to each border
    vertex's 2-ring (face normals sit half an edge out: too much bulge). The
    tilt out of the hole's plane is capped at 1.3 x what the curvature
    across the hole gives, less 0.15 x the larger principal curvature (the
    fit leaks), so tube ends close flat and spheres stay round (0.2% of r).
    In the plane the way in is the surface's own, but straight in from the
    border where the surface stands up: normalising that sliver flipped
    border normals and folded a 96-edge cap.
  - **Untangle** (`_qf_untangle`): gradient steps along the surface on
    corners under ~15 degrees, keeping the best state; corners with all
    three nodes on the border are skipped (nothing can move them, and they
    cost 2 s on a 128-edge cap).
  - **Writes:** polyCloseBorder, polySplit (vertex-to-vertex lines, then one
    split per row crossing them), polyExtrudeFacet(divisions=rings,
    thickness 0), one `pnts` tweak, polySoftEdge (new edges 180, the old
    border 60: a tube's rim stays hard), all with `ch` = the mesh already
    has history. New ids are found by topology after each step and the
    result is checked face by face against the plan (else the chunk is
    undone). Maya puts the new faces of a per-face shaded mesh in
    initialShadingGroup; `_qf_shade` moves them to the material round the
    hole.
  - **Grid: Straight** (the user, 2026-11-04: even at Smooth 0 / Follow 0
    the lines curved; wanted "a really neat hard grid"): a linear Coons
    patch's iso-lines blend the side curves, so they bend. Straight puts
    each inner grid node where its two chords (border node to opposite
    border node, rings first since nodes go in id order) pass closest
    (`_qf_chords`), then lifts only along the patch normal by Follow (lines
    stay straight seen along the normal; a sphere hole still fills round).
    Smooth is skipped (greyed out); untangle still runs on folds.
  - **Triangles** (same day: "warn the user ... how they can get rid of
    the tri"): `qf_triangle_advice(plans)` says how many, the odd edge
    count and the fix (split one border edge, fill again; Offset moves
    it). The panel shows it in step 3 (amber label, card tone warn), the
    NEXT banner mentions it, and the status after Fill repeats the fix.

- **Lazy tabs** (launch speed, 2026-11-04; the user: "make the toolbox
  launch faster"): `CategoryPage` builds a tool's panel the first time it's
  shown (`panel(i)` / `show_tool(i)`; until then its stack slot is an empty
  placeholder, replaced in place so `stack.setCurrentWidget(panel)` still
  works). The window builds only the first tab's first tool before showing;
  `tabs.currentChanged` builds the rest on demand. A panel whose build raises
  becomes `_ToolFailed` (the toolbox still opens). `window.panels()` builds
  everything (the GUI tests use it); the window itself uses
  `built_panels()` (shutdown on close). Build times land in
  `_registry()["build_times"]`. **Scene upkeep for unbuilt panels:**
  `TOOL_UPKEEP` lists what a panel does on Undo / Redo
  (`rebuild_stale_ropes`, `rebuild_stale_thatch`, `sc_sync`); the window's
  own Undo / Redo jobs run those for panels not built yet, so a redo still
  re-ties a rope with the Rope tab never opened. Add a row when a new panel
  gains scene upkeep. Smart UDIM starts with `_links_dirty = True` (it may be
  built long after the scene loaded, so it catches up on followed groups at
  its first refresh). `tests/gui_launch_time.py` (`run_gui_launch_time.mel`)
  measures read / compile / module / show / first paint and a real Script
  Editor paste, and opens every tool once.
- **Selection callbacks only for the tab on screen** (the user, 2026-11-05:
  Maya froze selecting meshes with the toolbox open, fine with it closed).
  Every built panel keeps its SelectionChanged job, so a tab opened once
  that session worked on every click: Quad Fill walked every edge of every
  mesh picked whole (0.54 s for 200 small spheres, seconds on real
  meshes). Rules: a panel's selection (and scene / undo) jobs go through
  `_on_screen_job(self, timer)`, which starts the timer only while the
  panel `isVisible()`; the panel's `showEvent` restarts it to catch up
  once (Path Scatter's direct job checks `isVisible()` and skips when the
  scene has no system). Quad Fill hunts a hole on a mesh picked whole only
  when it's the only mesh picked (several: a note, pick an edge) and stops
  at the second open border. `sc_selection` finds the scatter / moss
  groups once (`_tagged_roots`) and only asks `sc_owner` / `_mi_part_of`
  about nodes under one (`_under_any`); Scatter's `_update_states` reuses
  the selection `_sync_from_selection` read (`_sel_now`). Measured with
  `tests/gui_selection_speed.py` (200 spheres 64 x 64, every panel built,
  Scatter tab): 0.66 s -> 0.02 s of toolbox work per selection change,
  0.58 s -> 0.0002 s with the toolbox hidden. New panels: use
  `_on_screen_job` and a catching-up `showEvent`.
- **Renamer** (Naming tab; UnlokRenamer ported in, 2026-11-04, the user:
  "incorporate unlok renamer too"). Module-level engine: `ur_parse_name`,
  `ur_family_key`, `ur_compose_name`, `ur_generate_name(opts, index)` (opts =
  the panel's fields, `UR_RENAME_DEFAULTS`), `ur_fields_from_name` (Set From
  Selection; returns explicit fields plus `group`, and the panel applies
  `UR_GROUP_MODE` / `UR_GEOMETRY_MODE` first when the mode flips, as the
  standalone checkbox did), `ur_rename`, `ur_transforms`, the four
  `ur_scan_*`, `ur_family_targets` (pure: the family-renumber engine) and
  `ur_fix_families`; panel `RenamerPanel`, results `RenamerIssueDialog`
  (re-scans after each fix). Kept from the standalone: names, parsing,
  numbering, UUID two-pass renames (`_ur_rename_pairs`), checks and their
  wording. Changed for the toolbox: renames and fixes are one UndoChunk each
  (the standalone had no undo chunk), errors go to the status line, one
  narrow column. Shares `UR_MATERIALS` / `UR_COLORS` / `UR_SUFFIXES` and the
  split helpers with Smart UDIM. `tests/test_renamer.py` compares the maths
  with the standalone `unlok_renamer.py` (loaded from the UnlokRenamer repo
  when it's there). **Both stay maintained** (the user, 2026-11-05: "Keep
  both maintained"): a naming-rule change goes into both this panel and
  UnlokRenamer's `unlok_renamer.py`, and the parity test must still pass.
  Smart UDIM's
  **Open Renamer** selects the listed meshes and calls
  `open_toolbox_tool("Renamer")` (the old "is unlok_renamer loaded" lookup is
  gone).
- **Reframe** (Camera tab; the user's MayaReframeTool, embedded 2026-11-04).
  It stays its own project (`../../MayaReframeTool`, `Build/scripts/reframe`,
  its own tests and paste build). `tools/embed_reframe.py` copies its
  package into `_REFRAME_SOURCES` between the BEGIN / END REFRAME SOURCES
  markers as string literals (non-ASCII as `\uXXXX` escapes, decoding back
  exactly); `--check` says whether it's current. Edit Reframe there, then
  re-run the script; never edit the embedded block by hand.
  `reframe_package()` installs an in-memory importer (flag `_reframe_bundle`,
  the same one the standalone bundle uses, so either paste cleans up the
  other) and imports it, once per paste (`_REFRAME_STAMP`); nothing of it is
  compiled at paste time. `ReframeToolPanel` hosts Reframe's own
  `sidebar.ReframePanel` (a `MayaQWidgetDockableMixin` widget; parented into
  the panel it behaves as a plain widget) and calls its `shutdown()`. The
  Match window still opens as Reframe's own floating workspaceControl.
  Exceptions to the toolbox rules, kept as Reframe's behaviour: Export Match
  Data writes a JSON file the user picks, the strip's "Show in Explorer"
  starts explorer, and its UI callbacks don't go through `ui_safe`.
  `tests/test_reframe_embed.py`.
- **Shelf button** (the user, 2026-11-04: an icon "so it can be installed
  as part of the AM_custom shelf"). `shelf/install_shelf_button.py` (run in
  Maya, not part of the paste) copies `shelf/TAB_UnlokToolbox_icon_128px.png`
  into prefs `icons/tabIcons`, backs the shelf file up to `.bak`, replaces
  our button or an old pasted-toolbox button in place and saves shelves;
  the button execs `UnlokToolbox.py` from the main clone into `__main__`
  (like a paste). `tools/make_shelf_icon.py` draws the icons (the AM_Custom
  tab style: 403 x 128 pill, coloured block + white symbol, Poppins Bold).
  Never edit `shelf_AM_Custom.mel` while the user's Maya is open: Maya
  rewrites shelves on exit.

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
the output folder. The Roof tool's GUI test is `tests/run_gui_thatch_roof.mel`
(pictures of every shape and style in `tests/_out/thatch_roof`). A scripted
`cmds.redo()` sends no Redo event, so GUI tests call `_rebuild_stale()`.
Corrugated metal: `tests/test_corrugated_roof.py`. Clay tiles: `tests/test_tile_roof.py`.
Moss and Ivy: `tests/test_moss_ivy.py`. Scatter: `tests/test_scatter.py`, GUI `tests/run_gui_scatter.mel`.
Scatter influence paint: `tests/test_scatter_paint.py`, GUI `tests/run_gui_scatter_paint.mel` (its
pictures read the viewport back instead of playblasting, which empties the undo queue its Ctrl+Z checks need).
Dropped leaves touching what they lie on: `tests/test_leaf_contact.py` (`--measure` prints the gaps per scene
and layer); low close-up pictures from GUI `tests/run_gui_leaf_pics.mel` (`UNLOK_TOOLBOX` an older copy for
"before", `UNLOK_PIC_TAG` a file name prefix; `tests/_out/leaf_pics`).
Loose grass piles: `tests/test_grass_pile.py` (`UNLOK_OLD_TOOLBOX` an older copy: Pile height 0 must build
exactly what it built on open ground; grass under a single-sided roof plane), pictures from GUI `tests/run_gui_grass_pics.mel` (flat / new layer / Loose piles,
`tests/_out/grass_pics`). Both GUI picture scripts sometimes leave Maya open after `cmds.quit` once the
pictures are written: check the command line before stopping it.
Quad Fill: `tests/test_quad_fill.py`, GUI `tests/run_gui_quad_fill.mel`.
Renamer: `tests/test_renamer.py`. Reframe: `tests/test_reframe_embed.py`
(and `python tools/embed_reframe.py --check`). Launch time and every tool
opening: GUI `tests/run_gui_launch_time.mel`. Selection speed with the
toolbox open: GUI `tests/run_gui_selection_speed.mel` (`UNLOK_TOOLBOX` times
another copy, `UNLOK_TEST_TAG` names the results file).
- **Claude's shell here:** `python -` reading a heredoc or empty stdin, and
  `cat > file` without a heredoc, hang. Write patch scripts to files and
  run `python script.py`.
