"""Headless test: moss Slope limit is a hard limit (mayapy).

    mayapy tests/test_moss_slope.py

The user (2026-11-18): "when I make moss on walls, even if I turn slope
limit all the way to 0, which it says is flat only. It still grows up the
side of walls." Moss on a floor with a wall block standing on it (so the
wall foot is sheltered, where moss used to creep up): Slope limit 0 and 45
keep it off the wall's sides (the wall top is flat: moss there is fine),
90 lets it climb. Side-view pictures (looking at the wall's face) go to
tests/_out/moss_slope (UNLOK_TOOLBOX: an older copy, to see "before").
"""

import os
import struct
import sys
import traceback
import zlib

import maya.standalone
maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402
import maya.api.OpenMaya as om  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.path.join(HERE, "_out", "moss_slope")
TAG = os.environ.get("UNLOK_PIC_TAG", "")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def points(node):
    sel = om.MSelectionList()
    sel.add(node)
    return [(p.x, p.y, p.z) for p in om.MFnMesh(sel.getDagPath(0)).getPoints(om.MSpace.kWorld)]


def png(path, panels, W=300, H=170):
    """Side views (x, y) of each panel's points, the wall's face outlined."""
    IW = W * len(panels)
    img = bytearray(b"\x26\x24\x22" * IW * H)
    for k, (title, pts) in enumerate(panels):
        x0 = k * W
        for x in range(W):  # wall outline: x -20..20, y 0..20 -> the panel
            for y in range(H):
                wx, wy = (x - 10) / (W - 20.0) * 44.0 - 22.0, (H - 10 - y) / (H - 20.0) * 24.0
                on = (abs(abs(wx) - 20.0) < 0.12 and 0 <= wy <= 20) or (abs(wy - 20.0) < 0.12 and abs(wx) <= 20) \
                    or abs(wy) < 0.1
                if on:
                    i = 3 * (y * IW + x0 + x)
                    img[i:i + 3] = b"\x70\x70\x78"
            if x0 and x == 0:
                for y in range(H):
                    i = 3 * (y * IW + x0)
                    img[i:i + 3] = b"\x10\x10\x10"
        for p in pts:
            x = int(10 + (p[0] + 22.0) / 44.0 * (W - 20))
            y = int(H - 10 - p[1] / 24.0 * (H - 20))
            if 0 <= x < W and 0 <= y < H:
                i = 3 * (y * IW + x0 + x)
                img[i:i + 3] = b"\x9c\xd0\x5a"
    raw = b"".join(b"\x00" + bytes(img[3 * IW * y:3 * IW * (y + 1)]) for y in range(H))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", IW, H, 8, 2, 0, 0, 0)) +
                chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    print("picture: %s  (%s)" % (path, ", ".join(t for t, _ in panels)))


def run():
    tb = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), tb)
    cmds.file(new=True, force=True)
    floor = cmds.polyPlane(w=60, h=60, sx=6, sy=6, name="floor", constructionHistory=False)[0]
    wall = cmds.polyCube(w=40, h=20, d=4, sx=8, sy=4, sz=1, name="wall", constructionHistory=False)[0]
    cmds.move(0, 10, 0, wall)
    grp = cmds.group(floor, wall, name="yard_GRP")
    rep = tb["create_scatter_group"]([grp], "Moss", {"detail": "Normal", "coverage": 0.7, "crevices": 1.0,
                                                     "slope": 0.0, "seed": 4}, select=False)
    root = rep["root"]
    lid = tb["sc_data"](root)["layers"][0]["id"]

    def sides():
        node = tb["sc_parts"](root).get(lid + "/moss")
        pts = points(node) if node and cmds.getAttr(node + ".visibility") else []
        # on the wall's sides: up off the floor, below its top, at its faces (z = +-2)
        side = [p for p in pts if 1.0 < p[1] < 19.0 and abs(abs(p[2]) - 2.0) < 1.5 and abs(p[0]) < 21.0]
        front = [p for p in pts if p[2] > 0.0 and (p[1] < 0.6 or p[2] < 3.6)]  # the near side, for the picture
        return pts, side, front

    got = {}
    for lim in (0.0, 45.0, 90.0):
        tb["sc_update"](root, lid, {"slope": lim})
        got[lim] = sides()
        print("slope %g: %d bed points, %d up the wall's sides" % (lim, len(got[lim][0]), len(got[lim][1])))
    check("Slope limit 0: nothing up the wall's sides (flat ground only)", got[0.0][0] and not got[0.0][1],
          "%d bed points, %d up the wall" % (len(got[0.0][0]), len(got[0.0][1])))
    check("Slope limit 45: nothing up the (vertical) wall either", not got[45.0][1], "%d up the wall" % len(
        got[45.0][1]))
    check("Slope limit 90: it climbs the sheltered wall", len(got[90.0][1]) > 50, "%d up the wall" % len(
        got[90.0][1]))
    check("... and the floor still grows the same way at 0 as at 45",
          abs(len(got[0.0][0]) - len(got[45.0][0])) <= 0.2 * max(1, len(got[45.0][0])))
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    png(os.path.join(OUT, TAG + "wall_side.png"), [("Slope limit %g" % k, got[k][2]) for k in (0.0, 45.0, 90.0)])

    # a Height fade still takes moss up (it decides how high, not Slope limit)
    tb["sc_update"](root, lid, {"slope": 0.0, "fade": "From base", "fade_by": "Metres", "fade_height": 1.0})
    base_f = sides()
    faded = base_f[1]
    check("with a Height fade on, the fade decides: it still climbs (to the fade)", len(faded) > 20,
          "%d up the wall" % len(faded))

    # the user: rain collecting on a wall's top, moss growing there and edging down; "both. Or either"
    def bands(side):
        return (sum(1 for p in side if p[1] < 6.5), sum(1 for p in side if 7.5 < p[1] < 12.5),
                sum(1 for p in side if p[1] > 13.5))

    tb["sc_update"](root, lid, {"fade": "From base", "fade_height": 0.6})
    fb = sides()
    tb["sc_update"](root, lid, {"fade": "From top"})
    ft = sides()
    tb["sc_update"](root, lid, {"fade": "Both ends"})
    fe = sides()
    b, t, e = bands(fb[1]), bands(ft[1]), bands(fe[1])
    check("From base: up from the wall's foot, nothing near its top", b[0] > 50 and b[1] == 0 and b[2] == 0,
          "low / middle / high %s" % (b,))
    check("From top: along the top and down from it, nothing near the foot", t[2] > 50 and t[1] == 0 and
          t[0] == 0 and fe[0] and any(p[1] > 19.5 for p in ft[0]), "low / middle / high %s" % (t,))
    check("Both ends: down from the top and up from the foot, bare in the middle", e[0] > 50 and e[2] > 50 and
          e[1] == 0, "low / middle / high %s" % (e,))
    png(os.path.join(OUT, TAG + "wall_fades.png"), [("From base", fb[2]), ("From top", ft[2]),
                                                     ("Both ends", fe[2])])


try:
    run()
except Exception:
    traceback.print_exc()
    RESULTS.append(("crashed", False, ""))
failed = [r for r in RESULTS if not r[1]]
print("\n%d checks, %d failed" % (len(RESULTS), len(failed)))
for name, _, detail in failed:
    print("FAILED: %s  %s" % (name, detail))
sys.stdout.flush()
maya.standalone.uninitialize()
os._exit(1 if failed else 0)
