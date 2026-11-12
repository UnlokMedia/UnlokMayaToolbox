"""Headless tests: scatter layers on top of each other (mayapy).

    mayapy tests/test_layer_stack.py

The user (2026-11-12): "fallen jungle leaves underneath grass, or if I move
a layer above grass ... things higher up in the layer stack will appear on
top of the other ones ... fallen leaves will sort of interact with
scattered grass and like sit on top of piles sometimes, or up against them".

A group grows moss first, then its other layers from the bottom of the list
up; a debris layer with On layers below (`on_layers`, new layers) lies on
the grass / leaves of the layers under it in the list. Checked on a floor
in decimetres: the setting is off for old layers (a layer then grows the
same with or without the others), Jungle leaves above grass piles sit up
on them, grass above jungle leaves lies over them (not under), Move Up /
Down swaps who is on top, and editing the lower layer regrows the one on
top.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def load_toolbox(path):
    ns = {"__name__": "unlok_test", "__file__": path}
    with open(path) as f:
        exec(compile(f.read(), path, "exec"), ns)
    return ns


GRASS = {"grass": 3.0, "bunch_size": 0.5, "grass_pile": 0.8, "coverage": 0.9, "patchiness": 0.2, "seed": 4}
JUNGLE = {"jungle": 2.5, "jungle_size": 0.45, "coverage": 0.9, "patchiness": 0.2, "seed": 9}


def main():
    tb = load_toolbox(TOOLBOX)
    cmds.file(new=True, force=True)
    floor = cmds.polyCube(w=40, h=1, d=40, sx=10, sy=1, sz=10, name="floor", constructionHistory=False)[0]
    cmds.move(0, -0.5, 0, floor)
    floor = cmds.ls(floor, long=True)[0]
    m = tb["scene_m_per_unit"]()
    D = tb["DEBRIS_DEFAULTS"]
    types = dict(tb["SC_TYPES"])
    check("On layers below is a debris setting, off by default (old groups grow as before)",
          D.get("on_layers") is False)
    check("... on for a new Grass, Leaves, Leaf piles and Jungle leaves layer, with a field and a place in the panel",
          all(types[t].get("new", {}).get("on_layers") is True and "on_layers" in types[t]["keys"] and
              any("on_layers" in sec[2] for sec in tb["SC_LAYOUT"][t])
              for t in ("Grass", "Leaves", "Leaf piles", "Jungle leaves")) and "on_layers" in tb["SC_FIELDS"])

    def group(first, second, on):
        """A group: first layer at the top of the list, second under it."""
        typ1, s1 = first
        typ2, s2 = second
        root = tb["create_scatter_group"]([floor], typ2, dict(s2, on_layers=on), select=False)["root"]
        tb["sc_add_layer"](root, typ1, dict(s1, on_layers=on))
        ls = tb["sc_data"](root)["layers"]
        lid2, lid1 = ls[0]["id"], ls[1]["id"]
        tb["sc_move_layer"](root, lid1, -1)  # the second added goes to the top
        return root, lid1, lid2

    def meshes(root):
        placed, _, _ = tb["sc_build"](root, tb["sc_data"](root), readback=False)
        return placed

    def heights(ms):
        return [p[1] for mm in ms for p in mm[0]]

    def under(top_meshes, low_meshes):
        """Points of top_meshes more than 3 mm under low_meshes' faces (seen from above)."""
        st = tb["_MiDropStack"](0.01 / m)
        for mm in low_meshes:
            st.lay_faces(mm)
        n = 0
        for p in [p for mm in top_meshes for p in mm[0]]:
            h = st.top(p[0], p[2], p[1] + 0.3 / m)
            if h > tb["MI_DROP_VOID"] and h > p[1] + 0.003 / m:
                n += 1
        return n

    def jungle_of(placed, lid):
        return [placed[k] for k in sorted(placed) if k.startswith(lid + "/")]

    # --- off: each layer grows as it would alone
    root, lj, lg = group(("Jungle leaves", JUNGLE), ("Grass", GRASS), False)
    both = meshes(root)
    alone = tb["create_scatter_group"]([floor], "Jungle leaves", dict(JUNGLE, on_layers=False), select=False)["root"]
    la = tb["sc_data"](alone)["layers"][0]["id"]
    one = meshes(alone)
    a, b = jungle_of(both, lj), jungle_of(one, la)
    check("off: jungle leaves above grass grow exactly as alone",
          [x[0] for x in a] == [x[0] for x in b], "%d vs %d points" % (len(heights(a)), len(heights(b))))
    grass_off = both[lg + "/grass"]
    jung_off = a
    cmds.delete(root, alone)

    # --- leaves on top of grass piles
    root, lj, lg = group(("Jungle leaves", JUNGLE), ("Grass", GRASS), True)
    got = meshes(root)
    jung_on = jungle_of(got, lj)
    grass = got[lg + "/grass"]
    check("the grass under them is unchanged by the leaves on top", grass[0] == grass_off[0],
          "%d vs %d points" % (len(grass[0]), len(grass_off[0])))
    lo, hi = sorted(heights(jung_off)), sorted(heights(jung_on))
    q = lambda xs, f: xs[int(f * (len(xs) - 1))] if xs else 0.0  # noqa: E731
    check("jungle leaves above grass piles sit up on them (higher than without)",
          q(hi, 0.75) > q(lo, 0.75) + 0.01 / m and q(hi, 0.9) > q(lo, 0.9),
          "75th percentile %.3f vs %.3f dm, 90th %.3f vs %.3f" % (q(hi, 0.75), q(lo, 0.75), q(hi, 0.9), q(lo, 0.9)))
    buried_on, buried_off = under(jung_on, [grass]), under(jung_off, [grass])
    check("... instead of in among the piles' blades", buried_on < 0.5 * buried_off,
          "%d leaf points under blades vs %d without" % (buried_on, buried_off))

    # --- Move Up: the grass on top now lies over the leaves
    tb["sc_move_layer"](root, lg, -1)
    got = meshes(root)
    jung = jungle_of(got, lj)
    grass = got[lg + "/grass"]
    off_root, og, _ = group(("Grass", GRASS), ("Jungle leaves", JUNGLE), False)
    goff = meshes(off_root)[og + "/grass"]
    n_on, n_off = under([grass], jung), under([goff], jung)
    check("Move Up: grass on top lies over the jungle leaves (no blade point under one)",
          n_on <= max(5, len(grass[0]) // 2000) and n_off > 20 * max(1, n_on),
          "%d grass points under a leaf vs %d with it off, of %d" % (n_on, n_off, len(grass[0])))
    check("... and the leaves, now under, grow as they would alone", [x[0] for x in jung] == [x[0] for x in jung_off])
    cmds.delete(off_root)

    # --- editing the lower layer regrows the one on top
    before = list(grass[0])
    tb["sc_update"](root, lj, {"seed": 21})
    got = meshes(root)
    check("a new seed on the leaves under it moves the grass on top too", got[lg + "/grass"][0] != before)


try:
    main()
except Exception:
    traceback.print_exc()
    check("ran without errors", False, "exception")
failed = [r for r in RESULTS if not r[1]]
print("%d checks, %d failed" % (len(RESULTS), len(failed)))
for name, ok, detail in failed:
    print("FAILED: %s  %s" % (name, detail))
sys.stdout.flush()
maya.standalone.uninitialize()
os._exit(1 if failed else 0)
