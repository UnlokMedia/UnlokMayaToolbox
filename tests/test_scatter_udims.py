"""Headless tests: a scatter layer on its own UDIM tiles (mayapy).

    mayapy tests/test_scatter_udims.py

The user (2026-11-12): "control UDIMs individually on layers ... move one
layer to a different UDIM than the rest of the group". A layer's "udim"
(Layer has own UDIM) starts its parts there; the rest follow the group's
Start UDIM in list order and skip the tiles it takes. Checked: the layer's
parts move to their tiles, two given the same UDIM overlap there, the
others never share a tile, nothing grows again (UVs
only), switching it off puts every part back where it was, and pinning a
layer onto the group's own start pushes the others along.
"""

import math
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


def main():
    tb = load_toolbox(TOOLBOX)
    cmds.file(new=True, force=True)
    floor = cmds.polyCube(w=30, h=1, d=30, sx=6, sy=1, sz=6, name="floor", constructionHistory=False)[0]
    cmds.move(0, -0.5, 0, floor)
    root = tb["create_scatter_group"]([floor], "Leaves", {"leaves": 10.0, "coverage": 0.8}, select=False)["root"]
    tb["sc_add_layer"](root, "Grass", {"grass": 2.0, "coverage": 0.8})
    tb["sc_add_layer"](root, "Jungle leaves", {"jungle": 1.0, "coverage": 0.8})
    lids = [l["id"] for l in tb["sc_data"](root)["layers"]]

    def state():
        """{part key: (sorted UDIMs its UVs cover, point count, first point)}."""
        out = {}
        for key, node in tb["sc_parts"](root).items():
            (u0, u1), (v0, v1) = cmds.polyEvaluate(node, boundingBox2d=True)
            cu = range(int(math.floor(u0 + 1e-6)), max(int(math.floor(u0 + 1e-6)) + 1, int(math.ceil(u1 - 1e-6))))
            cv = range(int(math.floor(v0 + 1e-6)), max(int(math.floor(v0 + 1e-6)) + 1, int(math.ceil(v1 - 1e-6))))
            tiles = sorted(1001 + i + 10 * j for i in cu for j in cv)
            pts = cmds.xform(node + ".vtx[0]", query=True, worldSpace=True, translation=True)
            out[key] = (tiles, cmds.polyEvaluate(node, vertex=True), tuple(round(p, 6) for p in pts))
        return out

    def clash(st):
        seen = {}
        for key, (tiles, _, _) in st.items():
            for t in tiles:
                if t in seen:
                    return "%s and %s on %d" % (key, seen[t], t)
                seen[t] = key
        return ""

    base = state()
    check("three layers, no two parts on one tile", len(base) >= 3 and not clash(base), str(base and clash(base)))
    builds = []
    real = tb["_sc_build_layer"]

    def counted(layer, *a, **k):
        builds.append(layer["id"])
        return real(layer, *a, **k)
    tb["_sc_build_layer"] = counted

    mid = lids[1]
    tb["sc_update"](root, mid, layer_change={"udim": 1021})
    st = state()
    own = dict((k, v) for k, v in st.items() if k.startswith(mid + "/"))
    check("Layer's UDIM 1021: its parts start there",
          own and min(t for v in own.values() for t in v[0]) == 1021, str(sorted(own.items())))
    check("... no two parts share a tile", not clash(st), clash(st))
    check("... nothing grew again (UVs only)", not builds and all(st[k][1:] == base[k][1:] for k in base),
          str(builds))
    check("... stored on the layer, not its settings",
          tb["sc_layer"](tb["sc_data"](root), mid).get("udim") == 1021 and
          "udim" not in tb["sc_layer"](tb["sc_data"](root), mid).get("s", {}))
    tb["sc_update"](root, mid, layer_change={"udim": 1001})
    st = state()
    own = dict((k, v) for k, v in st.items() if k.startswith(mid + "/"))
    check("pinned onto the group's start: it takes 1001, the others move past it",
          min(t for v in own.values() for t in v[0]) == 1001 and not clash(st), str(sorted(st.items())))
    # two layers given the same UDIM overlap there (the user: "I should just be able to overlap two of them")
    last = lids[2]
    tb["sc_update"](root, mid, layer_change={"udim": 1021})
    tb["sc_update"](root, last, layer_change={"udim": 1021})
    st = state()
    a = [t for k, v in st.items() if k.startswith(mid + "/") for t in v[0]]
    b = [t for k, v in st.items() if k.startswith(last + "/") for t in v[0]]
    first = [t for k, v in st.items() if k.startswith(lids[0] + "/") for t in v[0]]
    check("two layers on the same UDIM overlap there", min(a) == 1021 and min(b) == 1021 and set(a) & set(b),
          "%s / %s" % (a, b))
    check("... while the layer following the group stays clear of them", first and not set(first) & set(a + b),
          str(first))
    tb["sc_update"](root, last, layer_change={"udim": 0})
    tb["sc_update"](root, mid, layer_change={"udim": 0})
    st = state()
    check("off again: every part back on its old tiles",
          dict((k, v[0]) for k, v in st.items()) == dict((k, v[0]) for k, v in base.items()) and not builds,
          str(builds))
    tb["_sc_build_layer"] = real
    tb["sc_update"](root, mid, layer_change={"udim": 1031})
    tb["sc_set_layer"](root, mid, name="renamed")
    data = tb["sc_data"](root)
    tb["_SC_BUILT"].clear()
    placed, _, _ = tb["sc_build"](root, data)  # a scene just opened: read back from the parts

    lo = min(int(math.floor(min(placed[k][3]) + 1e-6)) for k in placed if k.startswith(mid + "/"))
    check("read back from its parts (scene opened again) it keeps its tiles", lo == 0 and
          min(int(math.floor(min(placed[k][4]) + 1e-6)) for k in placed if k.startswith(mid + "/")) == 3)


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
