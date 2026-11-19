# Getting started

[Back to Home](Home.md)

## Run it (any machine)

1. Open `UnlokToolbox.py`, select all, copy.
2. In Maya: **Windows > General Editors > Script Editor**, open a **Python** tab, paste.
3. Run it (Ctrl+Enter or the run button).

Running it again just replaces the window. To get the latest version, copy the
newest `UnlokToolbox.py` from this repo and run it again.

## Make a shelf button

The quick way: select the pasted code in the Script Editor and middle-mouse-drag it onto a shelf.

**AM_Custom shelf** (if you have this repo on your machine): run
`shelf/install_shelf_button.py` once in the Script Editor. It adds a toolbox
button with an icon that always runs the repo's current `UnlokToolbox.py`.

**Whole AM_Custom shelf on another PC:** ask for the latest
`PREFS - Andy - <month year>` folder. With Maya closed, copy its `prefs` and
`scripts` folders into `Documents/maya/<version>/` (merge and replace).

## The window

- Tabs along the top: **Modeling**, **UV**, **Naming**, **Camera**. Each has a row of tool buttons.
- Panels are numbered steps from top to bottom: pick or create the thing, then adjust settings.
- Most tools update **live** as you drag a slider. The heavy ones (Roof, Scatter) have a **Pause** button for making several changes before a rebuild.
- Hover over any setting for a tooltip saying what it does.
- The bar at the bottom shows what just happened (build time, face count, warnings).

## Scale: decimetres

Unlok scenes use 1 scene unit = 10 cm. Maya has no decimetre setting, so the
scenes say "cm" and the toolbox reads a "cm" scene as decimetres. Sizes in the
tools are shown in metres where it matters (patch sizes, leaf lengths, fade
heights). A scene in any other unit (m, mm, in) is taken at its word.
