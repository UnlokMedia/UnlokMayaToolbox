# Scatter responsiveness: where the time goes, and what to change

2026-11-19. The question: "is there some innovative out of the box method ... Blender geo nodes achieve
similar things with almost instant feedback, this has a lot of loading and feels very heavy when you
start getting like 3 or 4 layers."

Constraints: one pasteable file, Maya 2023 / Python 3.9, no numpy / plugins / runtime file I/O,
stability first.

## 1. Measured (headless, `tests/bench_scatter_layers.py`)

The user's yard (40 x 40 dm floor, wall ring, crate). One group, four layers in the panel's default
order and with their default settings: Moss mat, Scattered blades (grass), Dead leaves, Young shoots
(ivy). That is about 119k vertices in parts. Each line is one live edit through `sc_update`, as a
slider makes it. Mayapy 2024; times are wall clock, best of 2 where shown.

| Edit | Total | The edited layer's build | Other layers built again | Write to scene | UDIM pack + overhead |
|---|---|---|---|---|---|
| Add / create Moss mat (cold) | 5.7-6.2 s | 5.3-5.8 s | - | 0.24 s | 0.02 s |
| Moss coverage | 2.2-2.4 s | ~1.2 s | ~0.8 s (leaves resting on moss) | 0.27 s | 0.03 s |
| Leaves coverage | 0.8 s | ~0.4 s | ~0.4 s (grass resting on leaves) | 0.02 s | 0.03 s |
| Grass coverage | 0.4 s | 0.37 s | - | 0.02 s | 0.03 s |
| Ivy seed | 0.03-0.07 s | 0.02 s | - | 0.01 s | 0.02 s |
| Nothing changed (all cached) | 0.03 s | - | - | - | 0.03 s |
| Moss, Draft on | 1.5 s | ~0.7 s | ~0.8 s | 0.04 s | - |

What this shows:

- **The fixed cost of an edit is tiny.** It is 30 ms with every layer cached. `_sc_place_udims`,
  `_sc_write`'s checks, the JSON round trip and the box fit don't grow with the layer count. The
  per-layer cache (`_SC_BUILT`) works: unrelated layers cost nothing.
- **What does grow with layers is dependency.** New leaves, leaf piles and jungle layers start with
  *Rest on moss* and *On layers below* on, and grass with *On layers below* (the `SC_TYPES` "new"
  defaults). So every stack is a chain. A live edit low in the chain built every layer resting on it
  again, inside the same edit, before the viewport could update:
  - moss -> leaves rebuilt (+0.8 s, about 35% of the edit);
  - leaves -> grass rebuilt (+0.4 s, about 50% of the edit).

  With 3-4 layers each added layer adds its whole build time to every edit below it. This is the
  "heavy with 3 or 4 layers" feeling.
- **Moss mat is the single heaviest layer.** In a coverage edit's ~1.2 s, `_MossMat._finish`
  (heights, domes, shape) is ~55%, `_mi_mat_uvs` ~17%, shoots (`_MossDetail`) ~20% and the margins
  ~12% (profiled shares). A cold build is 5-6 s, nearly all of it the field / rest-surface analysis,
  which is cached afterwards.
- **Writing to the scene is minor headless** (0.24 s for the ~100k-vertex moss parts, nothing for
  the rest). This bench cannot see the viewport. Viewport 2.0 re-uploading a rewritten 100k mesh, and
  the Outliner / Attribute Editor refreshes, cost GUI time. That needs a GUI bench (see 4).
- **Draft moss still paid for the chain.** With Draft on, a moss edit was still 1.5 s, half of it the
  leaves on top.

## 2. Ideas, ranked

Expected gains are for the 4-layer yard above.

### 1. Settle later: never rebuild resting layers mid-edit (BUILT, see 3)

This is what geometry nodes effectively does. Only the node you touch re-evaluates at interactive
rate; downstream, expensive work is deferred. Here: a live edit grows only the edited layer. Layers
that would grow again only because what they rest on changed keep their last parts for now. They grow
("settle") once the slider is let go and no edit is queued.

- Gain: moss edits 2.4 -> 1.6 s, leaves edits 0.8 -> 0.4 s. Each extra resting layer would have added
  its full build; now it adds nothing until release. The gain grows with stack height, and that is the
  complaint.
- Risk: low. While dragging, resting leaves can float or sink a few mm over the changed moss, for
  under half a second after release. Play, Bake, Regrow and any non-live regrow always settle. A scene
  saved mid-wait regrows those layers instead of reading them back (they're left out of
  `unlokScatterGrown`).

### 2. Points-only updates for "height" sliders (next, recommended)

Thickness, Cushion height, Displacement, Breakup height and Edge roll on Moss mat change only how far
each top point is lifted. They don't change topology, outline or UVs. Keep each top point's base and
lift direction with the built layer. Then such a slider is one `MFnMesh.setPoints` on the existing
part, with no layout, no UVs and no new mesh. The user already asked for this ("Thickness / Cushion
height previewing live while dragging", in CLAUDE.md under Mat style).

- Gain: these sliders go from ~1.2-2 s to well under 0.1 s, a true real-time drag.
- Risk: medium. Each key needs a correct "only moves points" classification, and an exact-equality
  test against a full build per key. Shoots standing on the bed must move with it (instanced shoots:
  update their positions array).

### 3. A drag draft for leaves / grass (cheap, low risk)

Today a slow non-moss layer doesn't update at all while a slider is held (`_apply_pending` waits for
release). Give debris the same drag draft moss has: skip `_drop` / `_contact` / `_strays` (0.5 of a
leaves build) and lay pieces flat on the surface. Then do the full build on release, as the moss drag
draft already does.

- Gain: leaves drags at ~0.2 s a tick instead of no feedback.
- Risk: low; it reuses the Draft plumbing.

### 4. Measure the GUI side before tuning it

A GUI bench (pattern: `tests/gui_draw_bench.py` + a `.mel` runner) timing an edit end to end:
`sc_update` plus the next viewport refresh, with the panel open and Outliner / Attribute Editor
visible. If VP2 re-upload of big parts dominates, two options:
- show the part as bounding box / reduced display while dragging (`overrideLevelOfDetail`, NoUndo);
- split moss parts per surface mesh so an edit rewrites only the pieces that changed (dirty regions).

This needs a GUI Maya run on the user's machine (windows pop up), so it is for them to say when.

### 5. Moss mat: cache heights per point across coverage edits (moderate)

Domes and bumps come from world grids that don't depend on Coverage. Cache `_shape` / `_domes` per
grid point keyed by the layout. A coverage edit then only redoes the outline and the band near it
(~30-40% of a mat edit).

- Risk: medium (bit-exactness against the current build).

### 6. Interruptible builds (latest value wins), not recommended now

The build loops already call `_poll()`. Cancelling when a newer slider value arrives would need Qt
events processed mid-build (re-entrancy into the panel and scene mid-write). That is the kind of
instability the toolbox is replacing MASH to avoid. Settle later (1) and the drafts get most of the
feel without it.

### Rejected

- **Background threads / processes:** pure-Python work holds the GIL, and the Maya API isn't
  thread-safe. Separate processes need file or socket I/O, which is not allowed.
- **numpy / compiled plugins:** ruled out by the constraints.
- **Instancer previews for moss / grass / leaves:** these layers are continuous or draped meshes, not
  rigid copies, so a point-instancer preview would look nothing like the result. The instancer stays
  right for moss shoots (already done) and Path Scatter.
- **More pure-Python micro-tuning:** already tried, 10-20%.

## 3. Prototype: settle later (built, on main)

Engine (`UnlokToolbox.py`):
- `sc_build(..., settle=True)`. With `settle=False`, a layer whose cache key missed only because its
  ground changed (same layer JSON and surfaces as its last build, `_SC_PREV`) keeps its last parts,
  and its id goes in `report["stale"]`. Held parts never go into `_SC_BUILT` under the new ground's
  key.
- `sc_regrow` / `sc_update` take `settle`. `_SC_STALE[root]` keeps the stale ids, which are never
  read back (filtered from `_sc_grown_layers` and left out of `unlokScatterGrown`).
- `sc_stale(root)`, `sc_settle(root)` (regrow when something is stale and it isn't paused). Play and
  Bake settle stale groups first.

Panel (`ScatterPanel`):
- Live slider edits (normal and drag-draft) call `sc_update(..., settle=False)`.
- `_settle_later` starts `_settle_timer` (350 ms). `_settle` waits while a slider is held or an edit
  is queued, then calls `sc_settle` and reports "Settled the resting layers of ...". Paused groups
  wait for Play.

Tests:
- `tests/test_scatter_settle.py`: 14 checks. One layer built per live edit; stale ids reported and
  kept; the grown JSON leaves stale layers out; settle equals a full regrow from nothing; no readback
  of stale layers; pause / Play; Bake.
- `tests/bench_scatter_layers.py`: per-stage timings of the 4-layer stack, old way and live + settle.

Live + settle numbers from the bench:

| Edit | Before (one blocking edit) | Live edit now | Settle after release |
|---|---|---|---|
| Moss coverage | 2.38 s | 1.60 s | 0.84 s |
| Leaves coverage | 0.81 s | 0.37 s | 0.41 s |
| Grass / ivy | unchanged (nothing rests on them here) | | |

Not verified: the panel's timer path in GUI Maya (`tests/run_gui_scatter.mel` was not run, since GUI
runs pop windows on the user's screen).
