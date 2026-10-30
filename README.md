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

**Scale: decimetres.** Unlok works at 1 scene unit = 10 cm. Maya has no
decimetre setting, so those scenes say "cm", and the toolbox reads a "cm"
scene as decimetres: texel density in px/m, the default thatch box, Path
Scatter's recipes. A scene set to any other unit (m, mm, in...) is taken at
its word. Smart UDIM setups saved before this change have their px/m figures
converted once when they're opened (the same layout reads 10x lower; nothing
in the scene moves).

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

### Modeling > Rope Lashing

Ties logs together with rope the way pioneering lashings are really tied,
for stilt shacks, fences and frames.

1. **Select** two logs that touch or cross. Select a whole frame instead and
   each joint gets its own lashing. Logs selected together are bound
   together: where several logs meet at one spot (a post, a beam on it and
   rafters resting there) one continuous rope binds them all, joint after
   joint, with one starting and one finishing hitch. Members are tied to
   the joint's main log (a post with two beams and a brace: each to the
   post), and to the log they rest on before tip-to-tip ties. Beams that
   cross a post close together (a frame corner) each keep to their own
   stretch of post: the lower beam's turns go round the post below it, the
   upper beam's above it, and each passes over its beam on the side the
   other doesn't cross, so nothing gets stacked or squeezed. A slanted brace
   keeps its own lashing. A knee brace whose end butts against a post gets
   its own saddle there. For separate
   lashings, select two logs at a time. For logs side by side, also select a
   vertex or edge to say where along them the lashing goes. Select an
   existing lashing to edit it.
2. **Lashing and rope:** everything here shows straight away. With logs
   selected, a preview lashing appears on them (the banner says
   **PREVIEW**) and follows every click, so you can flip between lashing
   types and rope styles to compare. The preview stays on its logs when you
   deselect them, so you can look at it shaded and keep tweaking. With
   lashings selected, the same controls edit them live (the banner says
   **EDITING**).
   - **Preset:** picking one loads it. Built in: Standard, Hero
     (close-ups), Background (light), Thin twine and Heavy rope.
     **Save...** keeps your own in Maya's preferences (an optionVar, so no
     files), ready for any scene.
   - **Lashing** (one click each). *Auto* picks from the angle:
     - **Square** (crossing near 90 degrees): clove hitch on the upright,
       3 wraps in front of the crossbar and behind the upright, 2 frapping
       turns between the logs, clove hitch on the crossbar.
     - **Diagonal** (crossing at a slant, X braces): a hitch around both
       logs, 3 wraps on each diagonal, 2 fraps, clove hitch.
     - **Round** (side by side): clove hitch around both, 7 tight wraps,
       clove hitch.
     - **Sheer** (A-frames): wraps, then fraps between the legs, with a
       hitch on each leg (when the legs touch there's no room between them,
       so the hitches go around both and there are no fraps).
     - **Bands:** plain wraps, no knots (background).
     - **Tripod** (3+ logs side by side in a row, or splayed tripod legs):
       figure-of-eight racking turns woven over and under alternate logs,
       then frapping turns cinching every gap, clove hitches on the outer
       logs.
     - **Bundle** (3+ logs packed together, e.g. 2 x 2): tight turns round
       the whole bundle. Splayed legs (a standing tripod) are bound up where
       they meet.
     - **Saddle** (picked by itself when a log ends at the other: a post
       under a beam, a rafter resting on a beam): wraps go over the top log
       on each side and half round the end log just below its end, crossing
       in an X.
     - Clove hitches are snug two-turn hitches whose cut ends are tucked
       under the turns, so no loose ends stick out.
   - **Rope:** *3 strands* is real laid rope for close-ups; *Twisted* is one
     tube shaped like laid rope (the all-rounder); *Smooth tube* is the
     light background version.
   - **Thickness** is relative to the thinner log, so a preset suits any log
     size. Wraps, Fraps (Auto follows the recipes above), clove hitches on /
     off, Tails (the cut ends), Wobble (default 0.05: a tight rope; raise it
     for a hand-tied look), **Tension** (how hard the rope is pulled tight
     as it settles), **Gravity** (lets rope that isn't on a log sag) and
     Seed (Auto: each pair of logs
     keeps its own, so the preview and the result match).
   - Advanced: Bite (how far it presses into the wood), Sides, Segment
     length, **Settle** (simulation steps; 0 = off, fastest) and Lay (how
     tight the strands twist).
3. **Preview and lash:**
   - **Lash** keeps exactly what the preview shows (one Ctrl+Z). With logs
     selected it ties those (**Lash Selected**); with nothing selected it
     ties the previewed ones (**Lash Preview**). So either select logs, set
     things up and Lash, or preview, deselect, tweak, then Lash.
   - *Selecting logs previews them straight away* is on by default, but only
     while Rope Lashing is the tool on screen: opening the toolbox or using
     another tool never makes a preview, and switching away removes it.
     Turn it off for big frames, or to click around without moving the
     preview; **Preview Selected** then puts it on the selected logs.
   - **Clear Preview** removes it. The preview isn't undoable, can't be
     selected and is never saved with the scene. For big frames it shows
     the first 12 lashings (Lash still ties them all).
4. **Finish:** **Refit to Logs** re-ties lashings to logs you've moved (each
   keeps its own settings). **Bake** turns lashings into plain meshes: the
   selected ones, or with none selected every lashing in the scene plus the
   preview, all in one Ctrl+Z. **Select Lashings** finds the ones tied to
   the selected logs.

**With Smart UDIM:** lashings carry a "UVs ready" tag, so when Smart UDIM
scans an asset that contains them they're marked **Keep UVs**: Auto UV
never re-unwraps or scores them, and layout still packs them with
everything else. Marking one Auto yourself removes the tag, so it stays
Auto.

How it stays accurate:
- The rope is pressed onto each log's real surface (ray casts), so bent,
  tapered and Log Noise logs work.
- Every later pass of rope rides over the earlier rope it crosses, which is
  what makes the hitches and fraps read as knots.
- Each lashing then settles in a small rope simulation: tension pulls out
  slack, stiffness eases kinks, gravity sags free spans, friction keeps
  turns on the logs, and the rope can't pass through the logs or itself,
  so the crossings stay as tied. About 1 s per lashing.
- The rope behaves as if under tension: it bridges short dips between the
  ropes it crosses instead of sagging back onto the wood, and hitches pick
  up the rope's direction of travel, so it spirals in and out of them
  instead of jogging sideways. Bends tighter than the rope can take are
  eased.
- Rope never cuts through a log.

UVs are straight strips (U around the rope, V along it) cut into columns
that fill 0..1 at one texel density, with no overlaps. Ropes are named
`ropeNatural_C_lashing0001_GEP` and grouped under `lashings_GRP`.

**Speed:** a square lashing on 30 cm logs takes about 0.2 s as a smooth
tube, 0.5 s twisted and 0.8 s in 3 strands. A frame of 8 joints takes about
2 to 5 s.

### Modeling > Thatch Roof

Thatched roofs from a box: the right shape for a cottage, barn, shed,
roundhouse or palm hut, built the way thatch is laid, with stacked UVs for
straw and leaf textures. Work rough to fine: block the roof in on **Proxy**
detail (just its shell, instant), get the shape right, then raise
**Detail** a step at a time; the layout stays put while detail is added.

1. **Box:** press **Create Box**. With the building selected, the box sits
   on top of it (footprint = the building, bottom on its top); otherwise
   it's a 6 x 3 x 4 m box at the origin, eaves 2.5 m up (60 x 30 x 40
   units in decimetres). Move, rotate and scale it to the
   roof: the footprint is the wall tops, the bottom is the eave line and
   the top is the ridge. It's a wireframe that never renders. Any mesh works
   as a box (its bounding box).
   - **Deform the box** for roofs that aren't rectangular: move its
     vertices and the roof warps with them. Pull one end's corners in for
     a tapered footprint, raise one end's top for a ridge that climbs, slide
     the top sideways for an off-centre ridge, drop corners for a sloping
     eave line. The roof is laid out on the box as if it were square, then
     bent through its 8 corners like a lattice, so hips, levels and pieces
     all follow (pieces stretch a little where the box is stretched). A
     plain box gives exactly the same roof as before. Don't add vertices:
     a box with more than 8 is used by its bounding box.
2. **Make Roof** (one Ctrl+Z) thatches the selected box. From then on the
   roof **follows its box**: move, scale or deform the box and the roof
   rebuilds a moment after you stop (undoing it puts it back). Vertex edits
   are picked up while the Thatch Roof panel is on screen; otherwise press
   **Rebuild** (or select the roof: a box that changed is caught then). Selecting the
   roof or its box puts the roof on the panel (the banner says
   **EDITING**); it stays there when you deselect it, so you can look at it
   and keep tweaking.
3. **Roof shape** (live):
   - **Preset:** shape presets (Cottage (hipped), Gabled cottage,
     Half-hipped, Tiered, Roundhouse, Lean-to shed) set the shape and keep
     how the straw is made (step 4). Look presets set the whole look, step 4
     included:
     - **Cambodian shack (leaf panels):** a thin roof of folded palm-leaf
       panels in ragged rows, sagging ridge, warped slopes, gaps, no
       underlay (you see the panels from inside).
     - **Cambodian shack (straw):** a thin, scruffy layer of long straw
       planes, ragged hanging eaves, patchy.
     - **Grass hut (messy):** a hipped hut of loose 3D grass bundles.
     - **Palm: nipa shingles (neat):** gabled, thin, very even courses of
       narrow leaflets (Philippine / Malay nipa or attap shingles), a light
       top layer, a short fringe at the gables.
     - **Palm: palapa (hipped, messy top):** a hipped, thicker roof of long,
       wide leaves under a heavy, scruffy top layer that reaches further at
       the eaves; the hips get their own leaves.
     - **Palm: beach shack (makeshift):** gabled, sagging and warped, a
       loose under layer, lots of messy top fronds, gaps, long fronds
       hanging off the gable ends.
     - **Palm: Pacific fale (rounded):** very round hips, a thick, tidy roof
       with a light top layer.
   - **Ridge** (two slopes), **Lean-to** (one slope, high along the box's -
     side) or **Cone** (round, elliptical in a long box: use a square box
     over a round wall).
   - **+ end / - end:** **Gable** (flat, upright), **Hip** (slopes in) or
     **Half-hip** (upright below, hipped near the top). *Hip pitch* makes
     hips steeper or shallower than the sides; *Half-hip at* sets where the
     half-hip starts. *Ridge along* picks the ridge's direction (Auto: the
     box's longer side).
   - **Overhang** is 0 by default (every preset too): the roof is exactly
     the box, so make the box bigger for eaves; the slider adds a little on
     top if you want it.
   - **Thickness, Softness** (how round the ridge and hips are),
     **Sag** (old thatch dips; below 0 it bellies out) and **Lumps**.
   - **Makeshift** (for shacks rather than clean cottages): **Warp**
     (crooked rafters, a wavy eave line), **Ridge sag** (the ridge pole dips
     in the middle and drags the slopes down), **Ragged eaves** (an uneven,
     hacked-off edge; planes and pieces hang further in places, panels
     fray more) and **Gaps** (pieces or panels left out in clumps).
   - **Blockers** (for roofs that meet other geometry): boxes the thatch
     bends round. **Add Blocker** stands a red wireframe box (never
     renders) across the roof's + end, already blocking: move, rotate and
     scale it to the wall the roof butts up against, a lower roof under an
     eave, a beam. **Use Selected** makes your own meshes or groups blockers
     (their bounding boxes, rotated with them); **Remove** / **Select**.
     Every leaf, plane, piece and panel is walked from its top: a step that
     would go into a blocker stops at the face it hits and carries on along
     it, so leaves butt up flat against a wall and lie down on a lower roof,
     and off the face's edge they fall on as before; leaves that miss it
     hang free (a wall over half a verge leaves the other half hanging). A
     leaf that would grow out of a blocker is left out, sticks and poles are
     cut where they go in, and the surface / underlay are pushed flat
     against it. Move, scale or delete a blocker and the roof follows, like
     its box; selecting a blocker puts its roof on the panel; Bake removes
     the blockers the tool made (your own meshes stay). Exact on a plain
     box; through a deformed box blockers are fitted approximately.
   - **Levels:** tiers from the eaves to the ridge cap; each level's bottom
     edge stands proud of the one below by *Level lip*. One level is a plain
     roof with a rounded eave lip.
   - **Ridge cap:** *Top depth* (how far down it reaches; 0 = none), *Cap
     thickness*, and the cut of its lower edge: **Straight**, **Scallops**
     or **Points**, with their size and depth.
   - Sizes are fractions of the roof's span (its width across the ridge), so
     settings and presets suit any roof size; tooltips give real-world
     figures for a 5 m span.
4. **Thatch:**
   - **Surface:** one closed, displaced mesh with straw grooves running down
     every face (fanning round the hips), lightest to render. *Strands* and
     *Strand width* set the grooves; *Resolution* (grid points across the
     span) sets the detail.
   - **Planes:** straw cards for an alpha-mapped straw texture, laid up the
     slope over an **underlay** (a plain thatch shell, its own mesh for its
     own material), each lifted at its butt and tucked in at its top so the
     course above covers it. The bottom course hangs over the eaves.
   - **3D Pieces:** little tapered bundles with a cut butt end, for
     close-ups.
   - **Leaf Panels:** folded palm-leaf (sla / attap) panels tied in courses
     along the roof from the eaves up, each course overlapping the one
     below with its bottom edge standing off and frayed; the top course
     folds over the ridge. *Panel width* / *Panel length* size them,
     *Density* packs the courses closer. Each panel fills 0..1 (U along the
     roof, V up), on the same stacks as planes: one leaf-panel texture with
     alpha per stack.
   - **Palm Fronds:** palm thatch the way it's built (nipa / attap
     shingles, palapa, Pacific and beach huts), a whole roof on its own: no
     underlay needed (the palm presets switch it off), no gaps from outside
     or from inside, where you see the sticks and the backs of the leaves.
     - **Under layer, neat:** **tiles** (shingles, ~1 m patches), each a
       stick with wide leaflets folded over it hanging down the slope, side
       by side and overlapping their neighbours (*Overlap*), tied in courses
       a quarter leaf apart from the eaves up, every other course shifted
       half a tile. A leaflet keeps its full width over its top half, so
       with the overlap and the courses there's always a leaf over every
       point. Each course's tips stand off the roof a little more than its
       top, so the course above lies over it. *Under leaf width* (wide: 11
       cm on a 5 m span), *Tile width*, *Neat under layer*.
     - **Top layer, messy:** loose half fronds between the courses, with
       thinner leaflets (*Top leaf width*) on a rachis, turned, lifted,
       twisted, curling, some broken or missing (*Top layer*, *Slant*,
       *Messiness*, *Droop*).
     - **Edges, two layers:** the under layer is limp, so past the eaves
       and gable verges its leaves hang down (*Edge hang*); the top layer
       is stiff and sticks out further (*Reach at ends*). *Gable fringe*
       adds leaves tied along each verge.
     - **Caps:** leaves laid over the ridge, down each hip and round a
       cone's apex from the crest down both sides, ending at the courses'
       height so they blend in, under a pole along the crest (*Cap the
       ridge, hips and apex*). Courses wrap continuously round hipped ends.
     - **Form:** **Cards** (one card per tile / frond for an alpha-mapped
       texture; each fills 0..1; caps stay leaflets), **Leaflets** (each
       leaflet a flat tapered strip) or **3D Leaflets** (creased down the
       midrib, rounder sticks). Leaflets share one UV layout: the leaflet in
       true proportions in the left 85% of 0..1 (so a leaf texture with
       alpha fits its outline), sticks, rachis and poles in the strip on the
       right (*Sticks, rachis and ridge poles*); stacks and mirroring as
       below.
     - **Curl** bends every leaflet across its width (not along it): above
       0 it arches (edges down to the roof), below 0 it cups (edges up), 1 is
       a half tube, 2 rolled round; the width and UVs are kept. *Curl
       variation* gives each leaf its own. Curled leaves get 3 columns across
       (High / Hero: 5); at 0 they stay flat and lightest. Straw **Planes**
       curl the same way, and **Leaf Panels** get a gentle arch across each
       panel. The palm presets use a little (0.25-0.5).
     - **Levels** (step 3) work with palm too: every level starts a fresh
       course right at its step, its leaves hanging down over the level
       below.
     - **3D Leaflets** have a real *Leaf thickness* (3 mm on a 5 m span by
       default): every leaflet is a closed, thin solid (underside on the same
       UVs, its edges and tip on a sliver of the strip).
     - **Sticks, rachis and poles** are built like the frame's members:
       capped ends, a little natural variation, Sub-D topology with the
       frame's toggle; the tile sticks and the top fronds' rachis stay on
       the stacked leaf UVs (the strip on the right), the ridge and hip
       poles go in the frame's mesh (in the straw without a frame).
     - *Leaf length*, *Density* (1 is about four leaves deep), *Lift* (how
       far the courses stand off), *Bend*, *Segments*.
   - Pieces: *Density* (1 covers the roof about three deep), *Width*,
     *Length*, *Messiness* (random turn, roll and size), *Lift*, *Bend*,
     *Segments*; 3D pieces also *Sides* and *Flatness*.
   - **Underlay:** a closed shell under the planes / pieces / panels /
     fronds (its own mesh, for its own material; palm roofs don't need it,
     but it's there if you want one) that holds up close: it's
     coursed like the thatch on it (each course's lower edge stands proud,
     cut into leaf or straw tips staggered course to course, with grain
     running down the slope), its eaves and gable verges end in a fringe of
     tips, under palm fronds it thins towards the edges so only the leaves
     show there, and the ceiling side has a neat batten along every course
     (what you see from inside). *Underlay relief* scales all of it (0: the
     old plain shell). Fine relief needs grid points: raise *Resolution* or
     use High / Hero.
   - **Frame** (built the way a thatched roof is): **rafters** down the
     slope from a **ridge beam** to the eaves (a **hip rafter** down each
     hip and **jack rafters** off it; radial rafters to a cone's apex), a
     **batten** across them under every course (the tiles' sticks rest on
     them; round a hip or a cone they follow the courses), **wall plates**
     along the wall tops under the rafters. It sits under the thatch (under
     the underlay or the surface's shell when there is one), so it's what
     you see from inside, in its own mesh (`woodFrame_C_...`) for a wood
     material. *Style*: **Bamboo** (a node ring every ~35 cm), **Poles**
     (round timber, tapering, a little out of round) or **Sawn**
     (rectangular: rafters deeper than wide, battens flat).
     *Battens*: **Every course**, **Every 2nd**, **Every 3rd** (fewer
     horizontal lines, the tiles in between tied to the rafters) or **Per
     level** (a purlin where each of step 3's *Levels* starts, the way tiered
     roofs are built). The frame follows the roof's shape (sag, lumps, warp,
     ridge sag) but not the levels' lips or the cap (thatch, not timber);
     wall plates sit on the wall tops under the rafters. *Rafter
     spacing*, *Rafter size* (ridge beam 1.4x, hips 1.3x), *Batten size*,
     *Crookedness* (gently crooked members, ends cut unevenly; rafter tops
     always meet the ridge beam). Light topology: a ring every ~25 cm, 6
     sides, hard edges on sawn timber, one-face caps. **Sub-D topology**:
     8 sides (the frame mesh is then named `..._GES` instead of `_GEP`),
     support loops near the cut ends and along sawn corners,
     quad-filled caps, every member closed and all quads, so it smooths
     with crisp rounded edges and no chamfers. UVs: each member's skin one
     shell (seam on the side facing the thatch; sawn faces unfolded side by
     side), each cap a disc, all packed into 0..1 at one texel density.
     Blockers cut members where they go in. Not built on Proxy.
   - **Detail:** **Proxy** (no thatch, just the shell on a coarse grid:
     about 0.1 s, for placing and shaping), **Rough** (cards / planes, 2
     segments), **Medium** (as set), **High** and **Hero** (1.5x / 2x the
     segments and a finer underlay, for close-ups). Every random value is
     tied to its course and frond, so raising Detail keeps the layout.
   - **UV stacks:** every plane / piece has the same UVs (planes fill 0..1;
     3D pieces have the body in the left 78% and the butt in the corner).
     With 2+ *Stacks* each piece picks one at random, in **UDIM tiles**
     (stack 1 in 1001, stack 2 in 1002...) or **Atlas columns** (side by
     side in 0..1), so two or three straw textures mix across the roof.
     *Mirror half the pieces* flips the texture on about half of them (the
     UVs are mirrored: fine for colour, careful with normal maps).
   - *Seed* / **Randomize** for the lumps, straw and pieces.
5. **Finish:** **Select Box**, **Rebuild** (from the box as it is now: handy
   after editing the box's vertices) and **Bake** (one Ctrl+Z): the roof
   stays as plain meshes and the box goes. **Upgrade** brings roofs made
   by an older version of the toolbox up to date in place (the selected
   ones, or every roof): it adds the meshes they lack (the frame), keeps
   their settings, gives settings added since their defaults and rebuilds
   (one Ctrl+Z for the added meshes). Selecting an old roof says so; no
   need to remake roofs after updating the toolbox.

**Panel:** step 4 shows the main controls for the chosen style (Detail,
form, leaf sizes, top layer, neatness, density...); the rest is folded into
*More controls*, *Underlay*, *Frame* and *UV stacks*. In step 3, Makeshift,
Blockers, Levels and Ridge cap start folded.

Roofs are `thatchRoof0001_GRP` holding `strawThatch_C_thatchRoof0001_GEP`
(the surface, or the planes / pieces) and `strawUnderlay_C_thatchRoof0001_GEP`
(hidden for a surface), next to the box. **With Smart UDIM:** the surface and
the underlay are marked **Keep UVs** when scanned; stacked planes and pieces
are marked **Hands off**, since laying them out would unstack them (their
stack tiles are kept free). Marking one Auto yourself sticks.

**Speed:** on a 6 x 4 m roof at the defaults, a surface takes about 0.6 s
(56,000 faces), planes 1 s (3,500 planes) and 3D pieces 1.4 s (92,000
faces); the leaf-panel shack about 0.7 s (250 panels). The palm presets take
about 0.1 s on Proxy, 0.7 s on Rough, 1.3-1.6 s on Medium (65,000-100,000
faces), about 2 s on High and 2.3 s on Hero. Shape the roof on
Proxy (or lower *Resolution*) if edits feel slow.

### UV > Smart UDIM (in progress)

**Finding your way:** only the step you're on stays open (plus any step
that needs a look, marked amber). Finished steps fold to a one-line
summary. The strip of numbers under the NEXT banner jumps to any step:
green ticks are done, teal is now. Click any step's title to open or fold
it. Each step's settings sit under **Options**, and the UV-status legend
appears when you tick *Colour meshes by UV status*.

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
   - **Follow Maya groups** (step 3): a section or material group can
     follow groups in your hierarchy, so you don't have to re-assign new
     geometry.
     - **Setting it up:** select e.g. `shackA_GRP` in the Outliner, highlight
       a material group in the list and press **Follow Selected Groups**.
       Pressing **Move to Group** or **New Material Group** with a group
       selected does the same.
     - **What it does:** every mesh in the group moves into that set, and
       so does anything you add to the group later. It happens straight
       away: no Scan, no button. A linked set has a link icon in the list,
       and its tooltip names the groups.
     - **The closest followed group wins**, so a sub-group can follow a
       different set.
     - **The Outliner decides.** Every mesh under a followed group belongs
       where its closest followed group says, always: drag a mesh to
       another group in the Outliner and its sets follow. Check & Fix
       Groups uses the same rule, so after a Fix it finds nothing left to
       move.
     - **Followed sections** (Section from Group, or the top-level groups
       of the first Scan) sort new meshes in by name or shader. A mesh you
       move into their group goes along, keeping its material. One that
       leaves a followed material group is sorted by its own name or
       shader again.
     - **A mesh you assign elsewhere by hand stays there** while it stays in
       its Maya group: it's pinned. Drag it to another group in the
       Outliner and the pin is dropped, so it follows. Following another
       group explicitly also takes it back.
     - **A section that runs empty stays**, still following its group, so
       meshes you drag back into the group join it again.
     - **Renaming or moving** the group keeps the link. **Stop Following**
       ends it; the meshes stay where they are.
     - **Speed:** the check only runs after something was reparented or
       created, and takes about 7 ms when nothing needs to move (400
       meshes).
     - **Check & Fix Groups...** looks over the whole asset first and shows
       what it found before changing anything:
       - **Broken links:** a group that followed a Maya group which is now
         gone. Pick the group it should follow now (a group with the same
         name is offered first), leave it, or forget the link.
       - **Not following a group yet:** material groups that look like they
         were made from a Maya group (all its meshes, nearly nothing else).
         It suggests following that group, so meshes added there later join.
       - **Meshes not where their followed groups say:** moved, unless you
         pinned them there by hand (and haven't moved them since).
       - **Meshes in no group:** sorted in by name or shader.
       - **Empty material groups:** removed.

       Fix applies it all as one Ctrl+Z.
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
     inside a section. Every action accepts groups as well as meshes, and
     empty material groups are tidied away. Each action is one Ctrl+Z.
   - **Buttons vs right-click:** the step shows the everyday buttons
     (Select, Move to Group, New Material Group, Section from Group, Check
     & Fix Groups). Right-click a section or group for the rest: move
     sections up / down (or drag them in Quick Plan), move to section,
     delete section, pin / unpin, follow Maya groups, stack, orientation,
     rename. The Stack, Orient and Pin columns only show once a group uses
     them.
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
   - **In the tree:** double-click **TD %** to edit it; right-click for
     stacking, orientation, pins and section order.
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
   - **Do It All** (top of the panel): one click to Auto UV everything that
     needs it, lay it all out and validate.
     - It respects your sections, groups, Keep UVs / Hands off marks, locks
       and every setting in steps 6 and 7.
     - It scans first if there are new, ungrouped meshes.
     - It asks once with a summary of what it'll do, then you can leave it
       running.
     - Esc stops it. Finished steps stay, each its own Ctrl+Z (layout, then
       Auto UV).
     - At the end it says how many meshes were unwrapped and laid out, how
       many need a look, and what validation found. From there you can
       re-lay out, add sections, or re-UV things as you go.
   - **UV status colours** (the strip at the top of the panel): tick
     *Colour meshes by UV status* to see where you are in the viewport.
     - **Yellow:** needs UVs.
     - **Red:** a problem, for example Auto UV failed, or the mesh is
       instanced.
     - **Greens:** Good UVs, Keep UVs (your marks) and Auto UV'd.
     - **Light blue:** UVs the tool made (Auto UV'd or found good) that
       Smart Layout has placed.
     - **Your marks always keep their own colour**, laid out or not, so
       after a full run you can still tell your own UVs from the tool's.
       The Auto UV list's Status column adds "laid out" (e.g. "Keep UVs
       · laid out"), and the inspector says both who made a mesh's
       UVs and whether it's laid out. Nothing the tool does ever removes
       your marks.
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
   - **Why is it red? (the inspector):** click a mesh in the viewport, or a
     row in the list.
     - The box under the list shows its state, its UV score now, what Auto
       UV last did to it, and for red meshes why it's red and what to do.
       Its row is highlighted too.
     - **Fix** does the right thing for the reason:
       - re-unwraps it, forced even if an old Check UVs called it good;
       - or, when its UVs already score fine and the red flag is just out
         of date, clears the flag.
     - **Select bad faces** selects the stretched, folded, overlapping or
       UV-less faces that pull the score down.
     - **Show only problems** filters the list down to the red meshes.
     - The scores' reasons now say what's wrong and how much, e.g. "12%
       stretched (over 4x off its shell), 3% overlapping".
     - A mesh goes red when:
       - Auto UV failed on it;
       - its UVs score under *Keep above* after unwrapping;
       - or it's instanced: it shares its shape with another transform,
         so it can't get its own UVs. Make it unique, or mark it Hands off.
     - Marking a red mesh Keep UVs or Hands off takes the red flag off. It
       used to stay red, because the flag outranked your mark.
   - **Auto UV Selected:** only the selected meshes or groups, so you can
     work through an asset bit by bit. Each one is fitted into its own tile
     (see step 4 below); nothing else moves, and Hands off meshes are never
     touched.
   - **Auto UV + Lay Out Selected:** a quick look as you go. Select some
     meshes or groups, press it, and they're unwrapped and then laid out
     together in one UDIM of their own: the one they already share if
     nothing else uses it (press again to redo them in place), else the
     first free one. Each material gets its own block, with neat rows and
     grids at one even density, upright. It isn't the plan: nothing is
     stored, and Apply Layout later lays everything out properly. Hands off
     meshes aren't moved; Keep Layout ones move as one rigid block. Two
     Ctrl+Z steps (Auto UV, then
     the lay-out). It lands in the first UDIM the tool hasn't filled
     (meshes nobody has unwrapped yet don't count).
   - **Lay Out Selected:** the same lay-out on the selection's UVs as they
     are, with no unwrap, like PolyRaven's size-based distribute and
     layout. It's for spot fixes:
     1. Auto UV + Lay Out Selected.
     2. Clean the UVs up by hand.
     3. Lay Out Selected again (it re-lays them in their own UDIM).
     4. Keep UVs, and move on to the next piece.

     It also works on parts of meshes: pick UVs, faces or edges (in the
     viewport or the UV Editor) and each takes its whole UV shell, like
     PolyRaven's convert-to-shell. Just those shells are laid out; the
     mesh's other shells stay where they are, and the laid-out ones never
     land on their tile. Meshes outside the asset are laid out in the UDIM
     they're in. One Ctrl+Z.
   - **Speed on big assets:**
     - Meshes whose projection is already clean (every edge's UV length
       the same multiple of its 3D length: walls, planks, boxes) skip
       Unfold3D. On the test building that's 99 of 102 meshes.
     - Check UVs remembers its scores with the scene and only re-scores
       meshes that changed (47 meshes: 0.11 s, then 0.01 s).
     - At 3,000 meshes the panel refreshes about 10x faster. It only
       refreshes when the asset's sets or meshes actually change, so
       undoing unrelated work doesn't touch it.
     - Scan shows progress, and Esc rolls it back.
   - **Auto UV doesn't score.** It unwraps every mesh that isn't marked
     Keep UVs or Hands off.
     - **Check UVs** is optional. Run it when some meshes may already have
       decent UVs you forgot to mark: Auto UV then keeps the ones it found
       good (green), as long as you don't edit them afterwards.
     - Hands off meshes are never scored or traced shell by shell, however
       heavy. Colours, Plan, packing and Validate stay quick: a
       160,000-face Hands off mesh costs 0.01 to 0.2 s.
   - **Check UVs** (was Analyse) scores every mesh's UVs from 0 (none or garbage) to 1
     (clean) and lists them worst first. A face counts as bad if it has no
     UVs, is collapsed, folded or overlapping, or is stretched more than 4x
     compared with the rest of its own shell. Rectangulated or straightened
     shells and shells at different densities aren't penalised.
   - **Auto UV** works through these steps:
     1. backs up the current UVs into `map1_backup` (only if that set doesn't
        exist yet, so re-runs keep your originals)
     2. cleans bad geometry
     3. re-unwraps every mesh scoring below *Keep above* (0.85) with the
        chosen *Unwrapper* (below)
     4. fits each unwrapped mesh into one UDIM tile, as big as it fits
        and at one density for the mesh, without laying meshes out against
        each other. That's Smart Layout's job, later. Meshes sharing a tile
        overlap until then. The tile is:
        - the one the current layout plan puts the mesh in, if there's a
          plan;
        - else one its group was laid out in by Apply Layout (the one it's
          in now, if it's one of them);
        - else the tile its old UVs were in;
        - else 1001, for a mesh with no UVs yet.

        (Engine scripts can still pack each material group into its own
        tile with `run_auto_uv(pack=True)`.)
   - **Progress:** Maya's progress bar at the bottom of the window, and the
     Auto UV step itself, show each stage, the mesh or batch it's on, a
     percentage and the time left. Press **Esc** to stop at the next mesh;
     one Ctrl+Z then undoes what was done. A long pause only happens inside
     one Unfold3D call on a big mesh, and the bar names it first.
   - **Unwrapper: Unlok (fast)**, the default, is the toolbox's own
     unwrapper. It runs in the background, so Maya stays responsive and
     Cancel works at once.
     - **Repeats are unwrapped once.** Pieces with the same topology and
       edge lengths are recognised, whether they're duplicated and combined
       into one mesh or kept as separate meshes. One gets unwrapped; the
       rest copy its UVs (scaled if the copy is scaled). A combined grid of
       36 pegs costs about the same as one peg.
     - **Hard surface or organic:** each piece is sorted by its edges.
       - **Hard surface** (flat areas and folds) is unwrapped like this:
         1. The mesh's own hard edges are ignored, as if every edge were
            softened. Imports leave stray hard edges across flat walls and
            floors, and those used to chop them up.
         2. Only real folds are cut: edges sharper than *Seam angle*. A
            flat or gently bent surface is never cut through, however
            messy its topology. Boolean slivers can't fake a fold.
         3. The parts are sewn back into box unfolds: only round outside
            corners (an inside corner is where a leg meets a rail, or a
            wall a floor, so those parts stay apart), only while the shell
            stays compact, with nothing lying on itself. Joins are rigid,
            so nothing stretches. A box, a crate or a plank comes out as
            one shell; a railing comes out as its rail plus one shell per
            leg.
         4. Whatever doesn't make a nice unfold stays cut at its folds.
         5. Every shell is turned square to the grid (its tightest box
            along U and V), the mesh's up pointing up the tile, so a house
            turned off the world grid still gives square walls.
       - **Organic** (smoothly curved everywhere) only cuts very sharp
         edges. A closed shape gets one pelt cut between its two farthest
         points, and the result is relaxed.
     - **Flattening:**
       - Flat parts are projected.
       - Developable ones (planks, boxes, cylinders, cones, tubes) are
         unfolded triangle by triangle, which is exact. A ring (a
         cylinder's side) gets one cut between its rims and unrolls with
         no stretch.
       - Curved parts are relaxed (as-rigid-as-possible). Bent, tapered,
         wobbly or triangulated tubes start from a rectangle (rim length by
         tube length), and closed shapes cut by a pelt start from an
         ellipse. The relax then only has to take out the bend, so such a
         tube comes out as one shell.
       - A part that would fold over or stretch badly is split and tried
         again.
     - **Tubes, planks and boxes** (posts, pipes, beams, planks, crates,
       bolts, bevelled or not) come out as one straight strip plus their
       caps, but only when what's left after cutting the caps really is a
       tube (a railing or a wall with n-gons used to come out as one
       windy, stretched shell).
       - The caps are found by shape: n-gon caps, or faces looking along
         the piece's axis. So a bevel or soft shading can't merge a cap into
         the side, which used to bend the side into a banana or a star.
       - The side unrolls straight onto a rectangle, even when the pipe
         bends, and the caps are sewn on at the ends.
     - **Tiny bits** (bevel corners, slivers) are merged into a neighbour
       before flattening. A small leftover shell is sewn on as a flap only
       where it shares a good stretch of edge (30% of its outline), so round
       caps and bolt heads are their own shells instead of hanging off a
       corner. Tiny few-sided bevel corners still go on.
     - **Join shells:**
       - *As few shells as possible* (default): sew into box unfolds as
         above. Two matching end caps go on the same side (symmetric).
       - *Compact shells*: sew only near-rectangles, which packs tighter.
       - *Keep every cut*: leave a seam on every hard and sharp edge.
     - **Big curved parts** (over 6,000 triangles, e.g. a dense dome or
       rock) are relaxed coarse-to-fine, still without Unfold3D:
       1. a ~1,000-triangle version is relaxed fully
       2. the rest is filled in between it
       3. two full-detail passes finish it

       Unfold3D is never called. Anything still too stretched is split and
       relaxed again.
     - **Speed** on the 47-mesh test building, all in the background:
       - 46 meshes (walls, planks, posts, columns, rings, curved panels)
         take 0.04 s together.
       - The 19,200-face closed dome takes about 8 s: relaxing big smooth
         shapes in plain Python costs time.
       - The whole Auto UV run takes 9.6 s with Unlok vs 5.2 s with
         Unfold3D, at the same quality score. Unfold3D blocks Maya for its
         whole run, while Unlok keeps Maya usable and Cancel instant.
   - **Unwrapper: Unfold3D (Maya)** is the old route:
     - normal-based projection
     - soft edges sewn; hard edges and edges sharper than *Seam angle* cut
     - Unfold3D auto-seams for closed shapes, then relax
     - extra cuts where shells are still stretched

     A shell whose projection is already clean skips Unfold3D, and only
     curved shells are unfolded. A single Unfold3D call on a big mesh still
     blocks Maya until it's done.
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
     - **Keep Layout:** UV'd *and* laid out the way you want, e.g. you
       unwrapped a mesh and arranged its shells yourself. They're never
       re-unwrapped. The layout scales each mesh to texel density as a
       whole (one scale for all its shells) and moves it as one block, so
       every shell stays where it is relative to the others. The block is
       never turned, and is shrunk only if it can't fit in a tile (with a
       warning). Strictly rigid: one scale and one move for every UV the
       mesh has, in Apply Layout and Lay Out Selected alike, so even a face
       too small or broken to count as a shell moves with it. No shell is
       ever moved on its own.
     - **Tiny or broken faces** (a collapsed face, a zero-area sliver) on
       other meshes go along with their mesh too. They used to stay where
       the mesh's UVs had been, sometimes rows away.
     - **Hands off:** finished and already in their UDIM, or too heavy or
       fragile to be checked. Nothing reads them: no unwrap, no score, no
       Pre-process, no backup copy, no moving. Plans, Validate, the sheet
       and the UV Viewer only ask Maya for the box around their UVs (one
       quick query per mesh, worked out inside Maya). Plans keep other
       squares out of that box, so a hands-off piece that uses only a corner
       of a tile still lets others share it. If finding them all takes over
       20 seconds, the rest block their group's whole tiles from the last
       layout instead. Validate only checks that the box is inside the UDIM
       range.
     - **Auto:** back to normal, where the score decides.
   - About 7 s for a 47-mesh test building that includes a 19,000-face dome.
     The whole run is one Ctrl+Z.

7. **Smart layout**: the even-density UDIM layout.
   - **One block per material group.** Each material group gets its own
     rectangle: the smallest-area one its shells fit at the texel density
     (row widths are tried from the widest piece up to a whole tile). Long,
     flat pieces make a wide, low strip, so other blocks can use the rest
     of the tile. A group bigger than a tile gets whole-tile blocks plus
     one smaller block for the rest. Blocks never overlap, so no material
     lands in another's gaps or corners. A tile can hold several blocks.
     (They used to be squares, which left long strips sitting at the
     bottom of mostly empty squares: on the test building the blocks went
     from 66% to 88% full for walls, and 18 tiles to 15.)
   - **Left to right by material.** Each section gets its own row, and
     along it the materials go left to right in order (alphabetical, or
     your own order). Each material's blocks stay together and never fill
     an earlier material's gaps, so every row reads the same way: woods in
     one place, concretes in another. Inside a material, each mesh's shells
     stay together and similar pieces sit side by side.
   - **Row options** (More options):
     - *Material order:* names or patterns in the order you want them
       (`wood*, concrete*`); the rest follow alphabetically. Or, in the UV
       Viewer, drag a material's shells onto another material: dropped on
       its left half it goes just before it, on the right half just after,
       in every row. The field fills in with the new order and the plan
       runs again. Dropping on empty tile space still pins it there.
     - *Own UDIM first / last:* materials that get their own UDIM(s) at
       the start or end of every section's row (`glass*` first: all the
       windows in each row's first UDIM).
     - *Line up materials in columns:* the section that uses the most UDIMs
       sets the columns, and every other section starts each material in
       the same column (wood from 1003 in the big building puts wood at
       1013 in the next). Smaller sections get gaps, and each column of
       UDIMs holds the same materials. It needs more room, so *Fit
       sections to rows* may settle on a lower density.
   - **Rows by size inside each block**, like PolyRaven's size-based
     distribution. Pieces go in tallest first, left to right, on one
     baseline per row; each piece takes the first row tall enough with
     room. Rows hold pieces of about one height, similar shapes sit side by
     side, and nothing is wedged into another piece's gap. Neat beats
     tight: a free-form packer that tucked pieces into gaps filled squares
     about 10% better and was left out on purpose.
   - **Options:** Density, Map size and Mode up front; More options has
     Padding, Orientation and Tidy blocks. Each section always starts a
     new row, a piece bigger than a tile always lowers just its own group
     (with a warning), and hands-off pieces are always packed around.
   - **Two stages:**
     - **Quick Plan** (a second or less): an overview to arrange and check
       before anything heavy runs. Each section gets a row, with its
       materials listed under its name (why is there glass in shackD?).
       Each material gets an estimated square, sized from its 3D area. Maya
       measures each set in one call, so no UVs are read and nothing loops
       over meshes. Measuring stops after 2 seconds; any material not
       measured by then is still listed on its row (marked `?`), just
       without a square. The estimate lands close to the real Plan (145 vs
       146 px/m on the test building).
       - Hands off pieces show where they sit (hatched), like in Plan, and
         the squares pack around them; their area isn't counted in their
         group's square.
       - Drag a section's name up or down to reorder sections (one Ctrl+Z).
       - Click a square to select that group's meshes.
       - Drag a square onto a tile to pin the group there.
     - **Plan**: packs the real shells into each group's square(s),
       honouring pins. Changing a setting re-plans. **Apply Layout** writes
       it.
   - **What Plan does, and why the first one takes a moment.** Groups and
     names only say which shells go together and at what density. To pack
     them, Plan needs every shell's 3D area, UV area and outline, so the
     first Plan reads every mesh's UV shells. That reading is remembered per
     mesh, so later Plans only re-read meshes that changed (0.2 s instead
     of 1.3 s for 4,800 shells). *Fit sections to rows* and *Fit to tiles*
     then try about 20 densities, each a full packing (about 0.6 s for
     4,800 shells).
   - **Plan runs in the background.** Once the shells are read, the search
     runs on its own thread: Maya stays usable, and changing a setting
     starts a fresh search (the old one stops). Apply and Do It All still
     plan on the spot.
   - **UV Viewer** (button next to Plan): a big window with the layout on
     the UDIM grid, each material's square framed and named. It only opens
     when you press the button (or Quick Plan). While Plan searches it
     animates through the densities it tries. *Read Scene UVs* shows the UVs as they are in the scene now
     (each mesh is read once, then remembered until it changes).
     - Colour by material group, UV status (the panel's colours) or texel
       density (blue under target, green on it, red over).
     - Overlays you can toggle: section names down the side of their rows,
       UDIM numbers, and hatched reserved tiles.
     - Wheel zooms, middle-drag or Alt+drag pans, F frames. Hover a shell
       to see its mesh, group, section and density; click it to select the
       mesh.
   - **Labels in UV Editor** (a UV Viewer button): tile borders, UDIM numbers and
     section names inside Maya's own UV Editor. They're drawn by a helper
     mesh, `unlokUdimLabels`, which doesn't render and is added to the
     selection (the UV Editor only shows selected meshes). It updates with
     each plan. Untick it to delete the mesh; closing the toolbox deletes it
     too.
   - **Plan only lays out meshes that are ready:** Keep UVs, Auto UV'd,
     already laid out, or scoring well. Meshes that still need UVs, and
     meshes with junk UVs (thousands of shells, or most faces their own
     shell), are left out and listed. The banner then says to run Auto UV
     first.
   - **Every heavy step shows progress and stops on Esc:** Check UVs, Auto
     UV, Plan, Apply, Validate, Pre-process, Bevel Resolver and Log Noise.
     After half a second a **Working** window appears with what's
     happening and a **Cancel** button. Maya keeps redrawing, so Windows
     never marks it "Not responding", and Cancel or Esc stops within a
     moment (long loops check it as they go, not just between meshes).
     A cancelled Apply, Bevel Resolve or Log Noise apply rolls back
     completely, and never undoes your previous action. Validate and the
     hand-off sheet report junk-UV meshes instead of grinding through
     every shell.
   - **Mode: Fit sections to rows (the default).** It finds the highest
     texel density at which every section still fits on its own single row
     of UDIMs (the biggest section decides), and gives every shell that one
     density. Groups or sections set to + / - TD % keep their offset, and
     Hands off pieces stay as they are. The summary says which section is
     widest and how many tiles it uses. *Fixed density* (your own px/m) and
     *Fit to tiles* (a tile budget) are still there.
     - A very low density here means a section has too much UV area for
       one row of 10 tiles. One big shell doesn't cause it: a shell too big
       for a tile only lowers its own group, with a warning.
   - **Mode: Fit largest shell.** Every shell gets the density at which the
     largest shell just fills one UDIM (inside the padding). Everything else
     is smaller, so nothing gets shrunk, groups keep their TD %, and the
     layout takes as many tiles as that needs (still a row per section). The
     summary names the shell that set it.
   - **Split shells too big for a UDIM** (step 7, More options, on by
     default): when the plan has a shell bigger than one UDIM (a big floor
     or wall), the summary says so, and Apply first cuts it along its faces
     at its 50% line along its laid-out length (thirds, or a grid, if it
     needs more), then plans again at the higher density that allows. Flat
     planes are otherwise never cut. The split is its own Ctrl+Z, before
     the layout's. Keep UVs, Keep Layout and Hands off meshes are never
     cut; a shell that's one big face can't be, and is fitted whole by
     lowering its group's density as before. Off: every big shell is
     fitted whole that way.
   - **After Apply Layout:** the UV Viewer opens on the layout you just
     applied (Read Scene UVs shows edits made since). After reopening the
     scene it reads the laid-out scene's UVs by itself for assets up to
     400 meshes; bigger ones wait for Read Scene UVs.
   - **Find Largest Shell** is instant after a layout (or an earlier Find)
     while nothing has changed: the answer is kept with a fingerprint of
     every mesh, saved with the scene. Change a mesh (cut the largest
     shell, say) and the next press measures again.
   - **Find Largest Shell** (step 7): selects the largest shell's faces and
     lists the next few, each with the most density it allows. It changes
     nothing. To raise the density:
     1. Cut that shell into smaller ones (or lower its group's TD %).
     2. Press Find Largest Shell again.
     3. Repeat until the density is good, then Plan.
   - **Re-laying out after editing UVs is safe:** Plan re-reads every mesh
     whose UVs changed and works out all sizes again. Locked groups keep
     their tiles (unlock to re-lay them), and Keep Layout meshes move as
     one block.
   - **Density:** every shell is scaled to exactly the target texel density,
     times its group's and section's TD %. A group renamed `td150_...` gets
     1.5x.
   - **Orientation:** every shell is first straightened to its tightest
     bounding box (edges square to U and V). *Upright*, the panel's default,
     then picks the quarter turn that points world Y up the tile, so planks,
     posts and pipes read the right way up for texturing. (Auto UV's
     per-mesh fit does the same.)
   - **One direction per material:** in Upright, a material's long pieces
     (beams, logs, planks: 1.4x longer than wide) all lie the same way,
     either across or up, whichever most of them (by area) already do. A
     diagonal beam no longer goes whichever way its slope tipped it, so one
     texture wraps along every woodBrown log. It's maths on numbers Plan
     already has, so it costs nothing.
   - **Tidy blocks** (More options, on by default): a mesh's shells are
     packed close together, so shells near each other in UV belong to the
     same mesh (a rope binding's strands, a lamp's parts), in rows. Shells
     of nearly the same size (planks, bolts, brackets: within 4%, or 15% for
     small pieces under 8% of a tile) are laid out in a grid of equal cells
     and packed as one block, like PolyRaven's size-based distribute. The
     grid is as close to a square as it can be (two 2:1 panes stack).
   - **Managing a finished layout:**
     - **Fix one mesh:** click it; the inspector says what's wrong. **Fix**
       or **Auto UV Selected** re-unwraps just it. If you've edited it by
       hand in the UV Editor, mark it **Keep UVs** so Auto UV leaves it
       (the layout still scales and packs it), or **Hands off** if it's
       final where it is.
     - **Re-layout Selected** (step 7): lays out again just the material
       groups highlighted in step 3, or the groups of the meshes selected
       in the scene, at the last layout's density.
       - Everything else stays exactly where it is, and its shells are
         worked around.
       - The re-laid groups go back into their own tiles first, filling the
         gaps left around other groups.
       - One Ctrl+Z.
     - **Pin to Tiles** (step 3: a button, the right-click menu, or
       double-click the *Pin* column): a group always goes to those tiles
       (e.g. `1012` or `1012-1014`), and no other group goes there. If it
       doesn't fit at that density, the rest spills into the next free tile,
       with a warning. Auto UV fits the group's meshes into its pinned tile.
       *Unpin* gives the group back to the layout.
     - **Drag in the UV Viewer:** drag any shell (or a Quick Plan tile)
       onto another tile, and its whole group is pinned there (a group of
       several squares gets that many tiles from there).
       - **On a plan:** it re-plans straight away (a Quick Plan stays
         quick).
       - **On the scene's UVs:** that group is re-laid out on the spot
         (Re-layout Selected).
       - A plain click still selects the mesh.
     - **Lock** (step 3) still keeps a finished group's UVs and tiles
       through every re-layout. Fit sections to rows leaves pinned groups
       out of its row check.
   - **Orientation modes:**
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
   - **Hands-off pieces** stay exactly where they are, and their tiles are
     never handed out as fresh tiles. Other squares fill the free space
     around them, keeping the padding; their own group gets first go.
   - **Fit to tiles:** finds the highest density that fits your tile budget.
   - **Locks (Lock column):** a locked group keeps its UVs and its tiles stay
     reserved, so you can re-lay everything else around finished work.
     Groups whose geometry changed since they were laid out get flagged.
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
- `tests/test_speedups.py`: clean projections skip Unfold3D (same
  quality), remembered scores and their invalidation, Scan progress and
  Esc.
- `tests/test_fast_reads.py`: the API readers (`expand_members`,
  `meshes()`) match the old cmds versions, and refresh reads are fast at
  3,000 meshes.
- `tests/test_guards.py`: junk UVs flagged fast, Plan leaves unready
  meshes out, Esc stops every heavy step, cancelled steps roll back without
  touching the previous undo step.
- `tests/test_uv_states.py`: UV states, status colours (and the real
  shading coming back), tracking sets, Auto UV Selected.
- `tests/test_follow_groups.py`: sets that follow Maya groups (new
  meshes, moved meshes, Ctrl+Z, pins, sections, renames, speed).
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
- `tests/test_unlok_unwrap.py`: the Unlok unwrapper. Covers a box and a
  plank (one shell, no stretch), a cylinder, a sphere pelt, a torus, a
  combined grid of copies, cancel, undo, and Unlok vs Unfold3D on the test
  building. `tests/bench_unwrap.py [--profile]` times it per mesh.
- `tests/bench_uv_quality.py [OUT] [-v]`: builds a messy shack and runs
  Auto UV and a layout on it. It saves pictures of every mesh's UVs and the
  sheet, and scores tiny shells, stars, straight and upright shells.
- `tests/test_squares.py`: one square per material group (shells inside
  their own squares, no overlaps, big groups split, pins, stacks, Fit
  rows), Quick Plan (one area call per set, estimated squares, rows in
  section order even when out of time), and the shell cache. `tests/bench_plan.py` times
  Plan on a bigger asset.
- `tests/test_manage_layout.py`: tile parsing, pins (own tile, others kept
  out, spill-over warning, Fit to rows), Re-layout Selected (others
  untouched, own tiles, no overlaps), Auto UV honouring a pin, mesh shells
  kept together.
- `tests/test_live_view.py`: shell outlines match their placements, the
  live-view hook, the background planner (same result, stops promptly),
  scene outlines and their density, the UV Editor label mesh.
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
- `tests/test_rope_lashing.py`: headless Rope Lashing tests. Every lashing
  and rope style is checked for clearance from itself and the logs, UVs in
  0..1 without overlaps, undo / redo (with the re-tie), save / reopen, live
  edits, refit, a whole frame, Log Noise logs, presets and speed.
- `tests/gui_rope_lashing.py`: drives the Rope Lashing panel in a real Maya
  session and saves close-ups to `tests/_out/rope_lashing`. Launch it like
  the smoke test below, with `tests/run_gui_rope_lashing.mel`.
- `tests/test_thatch_roof.py`: headless Thatch Roof tests. Every roof shape
  and end type in each style: closed shells facing out, the roof on its box,
  UVs (0..1 for the surface, stacks in their tiles / columns), undo / redo
  (with the rebuild), save / reopen, live edits, following the box, bake,
  the Smart UDIM marks and speed. Palm fronds: the presets (no underlay, and
  no gaps: rays cast up from inside over the whole footprint, the ridge line
  and hip ends included, must all hit a leaf), tapered leaflets and their
  UVs, the three forms, a neat under layer against a messy one, the top
  layer, the ridge cap, the gable fringe (none on a hip), the limp under
  layer against the stiff top layer at the eaves, the Detail levels (Proxy
  shell only, the same tiles and fronds at every level) and the underlay's
  relief (still a closed shell, same topology). Blockers: Add Blocker, a wall
  across the gable, one over half the verge (the open half still hangs), a
  lower roof the eave leaves lie on, nothing inside a blocker in any style,
  following a moved / deleted blocker, undo, bake, and the inverse of a
  deformed box's lattice. Frame: its own mesh, every style with and without
  Sub-D (UVs packed in 0..1 and the right way round, closed members, Sub-D
  all quads), under the thatch, rafter spacing, off on Proxy, cones and
  hipped surface roofs.
- `tests/gui_thatch_roof.py`: drives the Thatch Roof panel in a real Maya
  session (box on a house, Make Roof, live edits, following the box, presets,
  the palm presets and Detail levels, the frame, blockers, undo / redo, bake) and saves pictures
  of every shape and style (palm close-ups, eaves, gables, hips, the roof
  seen from inside and each Detail level) to `tests/_out/thatch_roof`. Launch it like
  the smoke test below, with
  `tests/run_gui_thatch_roof.mel`.
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
