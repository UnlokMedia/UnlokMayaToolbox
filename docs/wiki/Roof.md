# Roof (Modeling > Roof)

[Back to Home](Home.md) | Full reference: [README, Roof](../../README.md#modeling--roof)

Builds a whole roof (palm thatch, straw, corrugated metal, tiles) from a simple
box. You shape the box; the tool covers it.

![Palapa roof](images/roof_palapa_close.png)

## Basic flow

1. **Create a roof box** in the panel, or select an existing roof box. Move, scale or reshape its vertices to match your building: the roof follows the box, including boxes reshaped with modelling tools.
2. Pick a **preset** from the Preset list, e.g. `beach_dock_hut_001` (palm palapa, hipped, dried fronds).
3. Set the **Detail** level. Work in **Low** or **Medium**; switch to **High** only for final renders. High is heavy, and if it would go over the vertex limit the tool eases the detail itself and says so in the status bar.
4. Adjust settings. The roof rebuilds as you go. Use **Pause** to make several changes at once.

## Presets

- A **look preset** (palm, straw, etc.) sets every look setting. Anything it doesn't name goes back to default, so leftover tweaks from earlier don't carry over. Your Detail, seed and UV settings stay as they are.
- **Reset** (next to Save and Delete) puts every setting back to default.
- **Save** stores the current settings as your own preset.

## Settings artists use most

| Want | Use |
| --- | --- |
| Longer or shorter eave fringe | Edges: **Fringe length**, **Edge hang** |
| Wind-swept fringe | **Wind** (-1 to 1) |
| Packed down, less fluffy | **Max angle** (lower = flatter), **Neat** |
| Messier overall | **Messiness** |
| Ridge sits too low or looks sunken | Ridge: **Ridge height** (1.0 works for shallow roofs) |
| Fuller ridge | Ridge: **Ridge layers** (1 to 4) |
| Tufts and flyaways | Look: **Odd ones poking out**, **... lift**, **... in clumps**, **... variation** |

Tip: for tufts, try Pokes 20 to 30, lift 1.3, clump 0.5 and variation 1.0. This gives lone flyaways, tiny and small tufts, and one wide, low tuft.
