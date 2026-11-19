# Unlok Toolbox: quickstart

For artists picking up any scenes using scatters, roofs or other procedurals
from the Unlok Toolbox plugin for Maya.

![Palapa roof built with the Roof tool](images/roof_palapa.png)

## 1. Open the toolbox

1. Get [`UnlokToolbox.py`](https://github.com/UnlokMedia/UnlokMayaToolbox/blob/main/UnlokToolbox.py).
2. In Maya, open **Windows > General Editors > Script Editor** and a **Python** tab.
3. Paste the whole file and run it with Ctrl+Enter. The **Unlok Toolbox** window opens.

More detail, including shelf buttons and scene scale, is in [Getting started](Getting-Started.md).

## 2. What you'll see in the scene

**`scatteredObjects####_GRP` and `scatterControl####_GRP`**

You'll probably see a lot of these. They come in matching pairs: `scatteredObjects0003_GRP` goes with `scatterControl0003_GRP`.

- **`scatteredObjects####_GRP`** holds the output geometry: the moss, grass, leaves and so on.
- **`scatterControl####_GRP`** holds what drives it.

The two are connected, but they can sit in different places in the Outliner. The scattered objects can go inside a published group while the controls stay outside it. Moving either one doesn't break the link.

**`_CTL` bounding boxes**

There will probably also be quite a few wireframe `_CTL` boxes (`scatteredObjects####_CTL`). Each one belongs to the scatter group with the same number. Select a `_CTL` box to select and control its scatter group without having to pick the output geometry.

## 3. Editing a scatter

1. Select a `_CTL` box, or the scatter group itself.
2. In the toolbox, go to **Modeling > Scatter**. You'll see that group's **layers**, e.g. Moss, Grass, Leaves.
3. Click between the layers to edit each one on its own. Changes show straight away.
   - Tick a layer to turn it on or off.
   - Use **Pause** to make several changes before it regrows.
   - **Regrow** grows it again on the meshes as they are now, e.g. after the ground was edited.

**If a scatter doesn't respond**, check that it hasn't been **baked**. Baking turns a scatter group into plain meshes. That is sometimes needed for more manual edits, and once baked it no longer has layers to edit.

## 4. Guides for each tool

- [Getting started](Getting-Started.md)
  - [Run it](Getting-Started.md#run-it-any-machine)
  - [Shelf buttons](Getting-Started.md#make-a-shelf-button)
  - [The window](Getting-Started.md#the-window)
  - [Scale: decimetres](Getting-Started.md#scale-decimetres)
- [Scatter](Scatter.md): moss, grass, leaves, debris, ivy
  - [Basic flow](Scatter.md#basic-flow)
  - [Work light, then add detail](Scatter.md#work-light-then-add-detail)
  - [Controlling where it grows](Scatter.md#controlling-where-it-grows): blockers, slope limit, wall tops, patches
- [Roof](Roof.md): palm, thatch and other roofs
  - [Basic flow](Roof.md#basic-flow)
  - [Presets and Reset](Roof.md#presets)
  - [Settings artists use most](Roof.md#settings-artists-use-most): fringe, wind, ridge, tufts
- [Other tools](Other-Tools.md): Path Scatter, Bevel Resolver, Log Noise, Rope Lashing, Quad Fill, Smart UDIM, Renamer, Reframe
- [Tips and troubleshooting](Tips.md)
- [Full reference for every setting (README)](../../README.md)

**Scale:** scenes are in decimetres. They're set to "cm" in Maya, but the toolbox reads them as 1 unit = 10 cm. Don't change the scene unit.
