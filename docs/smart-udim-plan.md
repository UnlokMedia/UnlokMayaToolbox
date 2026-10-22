# Smart UDIM: plan

A UV > Smart UDIM tool for the Unlok Toolbox. It lays out UDIMs for **film**
assets (buildings, sets, props) by section and material, at a consistent texel
density, with stable re-layouts and a hand-off sheet for texture artists.

It follows the same rules as the rest of the toolbox: one pasteable file,
Maya 2023, no crashes, fast and iterative.

## Decisions so far

| Topic | Decision |
| --- | --- |
| Naming source | UnlokRenamer convention: `<materialColor>_<Pos>_<desc><####>_<suffix>`. The material key is the first token (`woodGreen`). Parsing helpers are copied in (keep in sync with UnlokRenamer); UnlokRenamer itself is never edited. |
| Material sets | `td100_woodGreen_c085` plus optional flags, e.g. `td100_woodGreen_c085_stack`. `td` = texel density %, `c` = coverage in % of one tile. Values are mirrored in attributes; the tool keeps names in sync and parses hand-typed names like `td150_woodGreen`. |
| Freeform materials | The name convention first, then the assigned shader (per face). |
| Pre-process | Auto-fix lamina faces, non-manifold geometry and zero-area faces. **Warn only** on n-gons. One undo step. |
| Bad or missing UVs | Warn and skip those meshes. The tool lays out existing unwraps; it never invents seams. |
| Stacking | Per group, opt in with a `_stack` flag on the set name. **Off by default.** |
| Tiling / trim sheets / lightmaps | Not needed (film pipeline). |
| Output | Written to a **new UV set** (default `map1_udim`), so original UVs are always kept. |

## Data model: plain Maya selection sets

Users can build or edit these outside the tool.

```
smartUDIM_SET                              root, one per asset
├─ buildingOne_UDS                         section: a row band of UDIMs, laid out in order
│   ├─ td100_glassClear_c012               material set (meshes or faces)
│   ├─ td100_woodGreen_c085_stack          repeated shells stack on top of each other
│   └─ td80_brickRed_c140                  80% texel density
└─ buildingTwo_UDS
    └─ ...
```

- **Section order:** set by an order attribute (drag-and-drop in the tool).
- **Locks:** lock state, growth margin and an input fingerprint are also
  stored as attributes on each set.
- **No sets at all:** the root becomes one section, and materials are
  detected automatically.

## Pipeline

**Scan → Pre-process → Texel density → Measure → Plan → Apply → Validate → Hand off**

Every stage is a button, and there's also one-click **Run All**. *Plan*
is pure math, so it updates live. *Apply* is one undo step, with progress and
Cancel.

1. **Scan.** Pick a root group, then build or refresh the sets.
   **UnlokRenamer hand-off:** list meshes whose names don't parse, with
   select buttons (and open UnlokRenamer if it's loaded), so they can be
   fixed before layout.
2. **Pre-process.** Run Maya's cleanup (`polyCleanupArgList`) for the agreed
   fixes, and report n-gons and skipped meshes (no or broken UVs). Click a
   report entry to select it.
3. **Texel density.**
   - Each material group is evened out internally (Unfold3D can rescale
     every shell to match its 3D size).
   - Then the group is scaled to target px/m at the chosen map size, times
     its section % and material %.
   - Areas come from `polyEvaluate`, which is C++ and fast.
4. **Measure.**
   - For `_stack` groups, identical shells are found first (shape signature
     plus Maya's `polyUVStackSimilarShells`), and only one copy counts.
   - A trial pack gives each group's real footprint, which becomes `c###`.
5. **Plan.**
   - **Rows:** sections fill rows of 10 tiles (each section starts on a new
     row by default; *Continuous* packs them back to back).
   - **Within a section:** groups over a tile get whole tiles. Smaller
     groups share tiles, packed from the bottom-left.
   - **Same material, same spot:** one global material order is used by every
     section. A setting picks *Strict*, *Prefer* (default) or *Off*.
   - **Modes:** *Fixed texel density*, or *Fit to N tiles* (the tool finds the
     highest density that fits).
   - **Fail-safe:** for a shell bigger than a tile, either warn and select
     it, or auto-compensate by lowering density for that material, its
     section or everything.
6. **Apply.**
   - **Own shelf packer, PolyRaven-style:** shells are grouped by size and
     shape (area, aspect, outline signature), so similar pieces sit together
     in neat rows instead of being scattered like a generic packer would.
   - **Rotation per set:** *Keep* (never rotate, for pre-aligned unwraps),
     *Align grain* (line the shell's main direction up with U or V),
     *90° steps*, or *Free*.
   - **Padding:** in pixels at the map size.
   - **Speed:** UVs are written in bulk through the API, and everything goes
     into the new UV set.
   - **Checking:** the result is checked against each rectangle, and any
     overshoot is squeezed back in.
7. **Validate.** One report, click-to-select:
   - shells crossing tile borders
   - overlaps that aren't intentional stacks
   - flipped (mirrored) shells
   - shells under about 2 px at the target resolution
   - density outliers
   - padding too small for lower texture resolutions (mip levels)
8. **Hand-off sheet.** A rendered image of the full layout:
   - real shell outlines, coloured by material, on the tile grid
   - section bands, tile numbers, labels and a legend
   - **export as PNG** through a save dialog the user chooses, or **copy to
     the clipboard** when saving files is locked down

## Stable re-layouts (essential, and must be intuitive)

The model will change after texturing starts. Re-running must not reshuffle
finished work.

- **Locks:** a padlock on every section and material block in the UDIM Map.
  A locked block keeps its tile and its spot.
- **Growth margin:** spare room per block (default +10%) so small model
  changes still fit in place.
- **Change detection:** each set's input fingerprint (members, face count,
  3D area) is saved when layout is applied. Changed blocks get a badge.
  **Re-lay changed only** moves just those.
- **When a locked block no longer fits,** the tool says so plainly and
  offers three choices: *let it overflow into a new tile*, *lower density for
  this block only* or *unlock and re-lay*. It never silently moves other
  locked work.

## Visual feedback

- **UDIM Map** (guaranteed): a Qt-painted map in the panel showing tiles,
  section bands, coloured material blocks, coverage and effective density.
  - **Interaction:** hover shows details, clicking selects faces, and the
    padlocks toggle locks.
  - **Speed and placement:** it re-plans live and can pop out as a small
    floating window.
- **UV Editor overlay** (spike): the UV Editor can't report its pan and zoom,
  so this is a prototype first, either tracking the view ourselves or
  showing guide-mesh outlines. It only ships if it's solid. The toggle is
  instant either way.

## Progress

- **M1 + M2 done:** sets and naming, scan, the tree UI, the UnlokRenamer
  hand-off list, and pre-process.
- **Unique names:** Maya set names are global, so the same material in two
  sections becomes `td100_woodGreen` and `td100_woodGreen_2`. Parsing
  ignores the `_2`.

- **Auto UV added** (user request): a scorched-earth first pass for
  un-UV'd assets.
  - It scores UV quality, re-unwraps the worst meshes (projection, then
    hard-edge seams, then Unfold3D, then extra stretch cuts), backs up the
    old UVs and packs one tile per material group.
  - This replaces the earlier "warn and skip meshes with bad UVs" decision
    for assets that have no usable UVs. Pre-process still reports them.
  - Smart layout (M3-M5) builds on this: even density across groups,
    multi-tile groups and locks.

- **Smart layout v1 done (M3-M5 core):**
  - exact texel density per shell (group and section TD %)
  - PCA rotation, with a keep-orientation option
  - shelf packing tile by tile (tallest first, similar shapes together)
  - groups spanning tiles, without crossing borders
  - sections on rows
  - fit to N tiles
  - auto-compensate for oversized pieces
  - locks with reserved tiles, change fingerprints, spare room
  - coverage written to names
  - the UDIM Map widget
  - Apply is one Ctrl+Z
- **M6 + M7 done:**
  - validation report (range, crossing, overlap, flipped, tiny, density,
    padding; click to select)
  - PNG / clipboard hand-off sheet (shells in material colours, tiles,
    sections, legend)
- **Done:**
  - orientation modes (Main axis / Upright / Keep) with a per-group
    override
  - `_stack` stacking of identical pieces
  - 2D skyline packing with gap reuse and 90-degree turns: 83% fill and
    7 tiles on the test building (the shelf packer managed 65% and 9)
  - per-mesh UV status: Keep UVs (laid out, never unwrapped) and Hands off
    (never touched; the layout packs around them or reserves their tiles)
- **Still open:**
  - the UV Editor overlay (M8)
  - the UnlokRenamer sanity-check hookup (beyond the naming list)

## Build order

1. **M1:** sets, name parsing (`td`, `c`, `_stack`, sections), scan, the
   section/material tree UI, creating sets from naming, and the UnlokRenamer
   hand-off list.
2. **M2:** pre-process, plus reporting on incoming UVs.
3. **M3:** first a quick test of the remaining Unfold3D details (packing box,
   overshoot, scale flags). Then texel density, stack detection and coverage.
4. **M4:** the planner (pure Python, tested headless), the UDIM Map, locks,
   growth margin and fingerprints.
5. **M5:** the similarity shelf packer, rotation modes, and apply into the
   new UV set with verification.
6. **M6:** the validation report.
7. **M7:** the hand-off sheet (PNG and clipboard).
8. **M8:** the UV Editor overlay spike.
9. **M9:** tests and a benchmark. A generated scene (3 sections × 6
   materials, with stacked windows) is checked for:
   - no UVs outside their assigned tile
   - density within ±2%
   - consistent material spots across sections
   - locked blocks staying put after a model change
   - undo working
   - speed targets: re-plan under 50 ms, apply on about 200k faces in
     seconds

## Defaults (unless changed)

- **Texel density:** px/m at 4096.
- **UV sets:** from `map1`, into `map1_udim`.
- **Rows:** 10 tiles per row, starting at 1001.
- **Rotation:** *90° steps*.
- **Growth margin:** 10%.
- **Instanced meshes:** skipped.

## Future scope

- **Lower density for hidden faces:** undersides, faces against walls, and
  anything that never faces camera automatically get less density (e.g.
  25%). Agreed as a good idea, parked for later.
