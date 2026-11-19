# Other tools

[Back to Home](Home.md). Each tool has a full section in the [README](../../README.md).

| Tool | Tab | What it's for |
| --- | --- | --- |
| **Path Scatter** | Modeling | Draw a path on a surface and lay objects along it: shingles, fences, kerbs, rocks. **Bake** as instances, copies or one mesh when done. |
| **Bevel Resolver** | Modeling | Cleans up hard-surface bevels for SubD: fixes the 5-, 6- and 7-sided faces left where a bevelled edge chain ends. |
| **Log Noise** | Modeling | Turns cylinders into natural-looking logs for shack supports, posts and fences. |
| **Rope Lashing** | Modeling | Ties logs together with rope the way real lashings are tied, for stilt shacks, fences and frames. |
| **Quad Fill** | Modeling | Fills a hole with clean quads that follow the surface, instead of one n-gon. |
| **Smart UDIM** | UV | Lays out UDIMs at a set texel density (px/m, decimetre scenes). Still in progress. |
| **Renamer** | Naming | Names geometry and groups to the Unlok convention and checks a whole hierarchy. |
| **Reframe** | Camera | Matches a Maya camera to concept art or a photo by clicking matching points: position, rotation, focal length. |

## Path Scatter in four steps

1. Pick a source: Cube / Cylinder / Plane / Sphere, or select your meshes and press **Use Selected Meshes**. Pick several for random variants.
2. Press **Draw Path** and drag across a mesh. **Shift** draws a straight line, **Ctrl** adds another path, **Q** finishes. Or use a curve or polygon edges with **Use Selection as Path**.
3. Adjust Distribution, Rows, Orientation and randomness. It updates live.
4. **Bake**.
