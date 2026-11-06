"""Headless tests for the moss Mat style (mayapy).

    mayapy tests/test_moss_mat.py
    (UNLOK_OLD_TOOLBOX=<an older UnlokToolbox.py> also checks that Carpet and
    Clumps moss grow exactly as that one did)

The Mat is a light all-quad cage for render-time subdivision and
displacement: every face a quad, no non-manifold edges, its only open
edges the bottom of the rolled edge, tucked under the surface deeper than
Displacement (still under after the whole mat is pushed out by it), far
fewer faces than the Carpet, UVs at one world-scale density in 0..1, and a
Scatter bed named _GED / _GES / _GEP by Render as with Arnold set to match.
"""

import math
import os
import sys
import time
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


def load_toolbox(path=TOOLBOX):
    ns = {"__name__": "unlok_test", "__file__": path}
    with open(path) as f:
        exec(compile(f.read(), path, "exec"), ns)
    return ns


def scene():
    """A rock rendered subdivided (_GES), a box and a floor (decimetres)."""
    r = cmds.polySphere(r=3.0, sx=24, sy=16, ch=False, name="rockGrey_C_test0001_GES")[0]
    cmds.scale(1.0, 0.7, 0.85, r)
    cmds.move(0, 1.6, 0, r)
    cmds.makeIdentity(r, apply=True)
    b = cmds.polyCube(w=6.0, h=4.0, d=6.0, sx=3, sy=2, sz=3, ch=False, name="woodPlank_C_test0001_GEP")[0]
    cmds.move(9, 2.0, 0, b)
    cmds.makeIdentity(b, apply=True)
    f = cmds.polyPlane(w=40, h=30, sx=8, sy=6, ch=False, name="groundSoil_C_test0001_GEP")[0]
    cmds.move(4, 0, 0, f)
    cmds.makeIdentity(f, apply=True)
    return [cmds.ls(x, long=True)[0] for x in (r, b, f)]


def edges(mesh):
    seen, k = {}, 0
    for n in mesh[1]:
        ids = mesh[2][k:k + n]
        k += n
        for a in range(n):
            e = (min(ids[a], ids[(a + 1) % n]), max(ids[a], ids[(a + 1) % n]))
            seen[e] = seen.get(e, 0) + 1
    return seen


def normals(mesh):
    """Area-weighted vertex normals of a quad mesh tuple."""
    P = mesh[0]
    acc = [[0.0, 0.0, 0.0] for _ in P]
    k = 0
    for n in mesh[1]:
        ids = mesh[2][k:k + n]
        k += n
        a, b, c, d = (P[i] for i in ids[:4])
        u = [c[j] - a[j] for j in range(3)]
        v = [d[j] - b[j] for j in range(3)]
        cr = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        for i in ids:
            for j in range(3):
                acc[i][j] += cr[j]
    out = []
    for a in acc:
        ln = math.sqrt(sum(x * x for x in a)) or 1.0
        out.append(tuple(x / ln for x in a))
    return out


def own_offsets(tb, surf, nodes, mesh, verts, shift=None):
    """Signed distance of points above the surface they belong to (the
    nearest of the meshes, along its normal); shift: points moved first."""
    out = []
    items = surf.items
    import maya.api.OpenMaya as om
    for i in verts:
        p = mesh[0][i] if shift is None else shift[i]
        hits = [r for r in (it[0].closest(om.MPoint(p[0], p[1], p[2])) for it in items) if r]
        near = min(r[0] for r in hits)
        # the nearest surface; where two are as near (a box's bottom on the floor), the one it is deeper under
        out.append(min((p[0] - r[1].x) * r[2].x + (p[1] - r[1].y) * r[2].y + (p[2] - r[1].z) * r[2].z
                       for r in hits if r[0] <= near + 1e-4))
    return out


def run():
    tb = load_toolbox()
    cmds.file(new=True, force=True)
    M = tb["scene_m_per_unit"]()
    nodes = scene()

    md = tb["MOSS_DEFAULTS"]
    check("Mat is a third style; old layers stay Carpet", tb["MOSS_STYLES"][2] == "Mat" and md["style"] == "Carpet")
    laid = set(k for _, _, keys in tb["SC_LAYOUT"]["Moss"] for k in keys)
    check("its settings have fields in the panel",
          all(k in laid and k in tb["SC_FIELDS"] for k in ("render_as", "disp_height", "edge_roll", "cage_detail",
                                                            "bumps", "growths")))
    pre = tb["MI_PRESETS"]["Moss"]
    check("Displaced, Simple and Lumpy mat presets",
          all(pre.get(n, {}).get("style") == "Mat" for n in ("Displaced mat", "Simple mat", "Lumpy mat")))

    s = dict(md, style="Mat", coverage=0.6, detail="Normal", seed=1)
    sc = dict(md, style="Carpet", coverage=0.6, detail="Normal", seed=1)
    t0 = time.time()
    carpet = tb["moss_build"](nodes, sc)
    tc = time.time() - t0
    t0 = time.time()
    got = tb["moss_build"](nodes, s)
    tm = time.time() - t0
    mat = got["moss"]
    nf, nfc = len(mat[1]), len(carpet["moss"][1])
    check("the mat grew", nf > 500, "%d faces" % nf)
    check("every face is a quad", all(c == 4 for c in mat[1]))
    seen = edges(mat)
    check("no non-manifold edges", not any(v > 2 for v in seen.values()))
    check("far fewer faces than the carpet (a third or less)", nf * 3 <= nfc, "%d vs %d" % (nf, nfc))
    check("quicker to build than the carpet", tm < tc, "%.2f s vs %.2f s" % (tm, tc))
    check("shoots and strands still grow on it", got["strands"] and len(got["strands"][0]) > 1000)

    # the rolled edge: the open edges are its bottom, under the surface deeper than Displacement
    surf = tb["_mi_rest_surface"](tb["_MiSurface"](nodes), tb["mi_settings_only"]("Moss", s))
    D = float(s["disp_height"]) / M
    opn = sorted(set(i for e, v in seen.items() if v == 1 for i in e))
    off = own_offsets(tb, surf, nodes, mat, opn)
    check("every open edge is tucked under the surface, deeper than Displacement",
          off and max(off) < -D, "deepest %.4f shallowest %.4f (D %.3f)" % (min(off), max(off), D))
    # the worst displacement: every point pushed out along its normal by the whole height
    nv = normals(mat)
    moved = [tuple(p[j] + n[j] * D for j in range(3)) for p, n in zip(mat[0], nv)]
    off2 = own_offsets(tb, surf, nodes, mat, opn, moved)
    check("pushed out by the whole Displacement, its edge still stays under the surface", max(off2) < 0.0,
          "shallowest %.4f" % max(off2))
    col = mat[0].col
    rim = [col[i][2] for i in opn]
    check("the edge's shading data B is 0 (Moss Look fades displacement out there)", max(rim) == 0.0)
    # the top sits on the surface (on the smooth rock too), at least the rim's height up
    top = [i for i in range(len(mat[0])) if col[i][1] > 0.0]
    offt = own_offsets(tb, surf, nodes, mat, top[::7])
    low = min(range(len(offt)), key=lambda i: offt[i])
    check("the top lies over the surface", offt[low] > -1e-3 * D,
          "lowest %.5f at %s" % (offt[low], tuple(round(x, 2) for x in mat[0][top[::7][low]])))

    # UVs: one world-scale density, in 0..1, every corner has one
    us, vs, uvi = mat[3], mat[4], mat[5]
    check("UVs in 0..1, one per face corner", us and min(us) >= 0 and max(us) <= 1 and min(vs) >= 0 and max(vs) <= 1
          and len(uvi) == len(mat[2]))
    tile = float(s["uv_tile"]) / M
    rs = []
    for q in range(len(mat[1])):
        for i in range(4):
            a, b = q * 4 + i, q * 4 + (i + 1) % 4
            pa, pb = mat[0][mat[2][a]], mat[0][mat[2][b]]
            l3 = math.sqrt(sum((pa[j] - pb[j]) ** 2 for j in range(3)))
            l2 = math.hypot(us[uvi[a]] - us[uvi[b]], vs[uvi[a]] - vs[uvi[b]])
            if l3 > 1e-6:
                rs.append(l2 * tile / l3)
    rs.sort()
    check("UV density is the world scale (Tile size), unstretched",
          abs(rs[len(rs) // 2] - 1.0) < 0.02 and rs[len(rs) // 20] > 0.85 and rs[-len(rs) // 20] < 1.15,
          "p5 %.3f med %.3f p95 %.3f" % (rs[len(rs) // 20], rs[len(rs) // 2], rs[-len(rs) // 20]))
    lab = {}

    def find(i):
        while lab.setdefault(i, i) != i:
            i = lab[i]
        return i

    for q in range(len(mat[1])):
        ids = uvi[q * 4:q * 4 + 4]
        for i in ids[1:]:
            a, b = find(ids[0]), find(i)
            if a != b:
                lab[a] = b
    shells = len(set(find(i) for i in uvi))
    area = 0.0
    k = 0
    for n in mat[1]:
        a, b, c, d = (mat[0][i] for i in mat[2][k:k + 4])
        k += 4
        u = [c[j] - a[j] for j in range(3)]
        v = [d[j] - b[j] for j in range(3)]
        area += 0.5 * math.sqrt((u[1] * v[2] - u[2] * v[1]) ** 2 + (u[2] * v[0] - u[0] * v[2]) ** 2 +
                                (u[0] * v[1] - u[1] * v[0]) ** 2)
    check("few UV shells (charts a tile or so across)", shells < 4.0 * area / (tile * tile) + 20,
          "%d shells, %.0f tiles of area" % (shells, area / (tile * tile)))

    # the settings
    fine = tb["moss_build"](nodes, dict(s, cage_detail=1.0))["moss"]
    check("Cage detail 1 makes it finer", len(fine[1]) > 2 * nf, "%d vs %d" % (len(fine[1]), nf))
    gep = tb["moss_build"](nodes, dict(s, render_as="GEP"))["moss"]
    check("as GEP (not subdivided) its cells are finer than GED's", len(gep[1]) > 2 * nf, "%d" % len(gep[1]))
    flat = tb["moss_build"](nodes, dict(s, edge_roll=0.0, bumps=0.0, growths=0.0))["moss"]  # (the edge alone)
    thick = tb["moss_build"](nodes, dict(s, edge_roll=1.0, bumps=0.0, growths=0.0))["moss"]

    def rim_h(m):
        c = m[0].col
        return max(c[i][1] for i in range(len(m[0])) if c[i][2] == 0.0)

    check("Edge roll sets how thick the edge stays", rim_h(thick) > rim_h(flat), "%.3f vs %.3f" % (rim_h(thick), rim_h(flat)))
    deeper = tb["moss_build"](nodes, dict(s, disp_height=0.03))["moss"]
    sd = edges(deeper)
    od = own_offsets(tb, surf, nodes, deeper, sorted(set(i for e, v in sd.items() if v == 1 for i in e))[::5])
    check("a higher Displacement tucks the edge deeper", max(od) < -0.03 / M, "shallowest %.4f" % max(od))
    t0 = time.time()
    dr = tb["moss_build"](nodes, dict(s, seed=5), draft=True)["moss"]
    check("a draft is a coarser mat", 0 < len(dr[1]) < nf, "%d faces" % len(dr[1]))
    again = tb["moss_build"](nodes, dict(s))["moss"]
    check("the same settings grow the same mat", again[0] == mat[0] and again[2] == mat[2])

    # shape: Bumps and Growths (0 and 0: the simplest mat)
    H = float(s["thickness"]) / M

    def heights(m):
        c = m[0].col
        top = [i for i in range(len(m[0])) if c[i][2] > 0.5][::4]
        return sorted(own_offsets(tb, surf, nodes, m, top))

    def spread(h):
        mu = sum(h) / len(h)
        return math.sqrt(sum((x - mu) ** 2 for x in h) / len(h))

    simple = tb["moss_build"](nodes, dict(s, bumps=0.0, growths=0.0))["moss"]
    t0 = time.time()
    lumpy = tb["moss_build"](nodes, dict(s, bumps=0.85, growths=0.7))["moss"]
    tl = time.time() - t0
    hs, hd, hl = heights(simple), heights(mat), heights(lumpy)
    check("Bumps 0, Growths 0: the simplest mat, fewest cells", len(simple[1]) < nf <= len(lumpy[1]),
          "%d / %d / %d faces" % (len(simple[1]), nf, len(lumpy[1])))
    check("more Bumps and Growths: more relief", spread(hs) < spread(hd) < spread(hl),
          "height spread %.3f / %.3f / %.3f (H %.3f)" % (spread(hs), spread(hd), spread(hl), H))
    check("growths rise well above the mat", hl[-1] > 2.0 * H and hl[-1] > hs[-1] + H,
          "tallest %.3f vs simple %.3f (H %.3f)" % (hl[-1], hs[-1], H))
    sl = edges(lumpy)
    check("lumpy: still all quads, manifold, a third of the carpet's faces or less",
          all(c == 4 for c in lumpy[1]) and not any(v > 2 for v in sl.values()) and len(lumpy[1]) * 3 <= nfc,
          "%d faces" % len(lumpy[1]))
    check("lumpy: still quicker than the carpet", tl < tc, "%.2f s vs %.2f s" % (tl, tc))
    ol = own_offsets(tb, surf, nodes, lumpy, sorted(set(i for e, v in sl.items() if v == 1 for i in e)))
    check("lumpy: the edge still tucks under deeper than Displacement", max(ol) < -D, "shallowest %.4f" % max(ol))
    rl = []
    for q in range(len(lumpy[1])):
        for i in range(4):
            a, b = q * 4 + i, q * 4 + (i + 1) % 4
            pa, pb = lumpy[0][lumpy[2][a]], lumpy[0][lumpy[2][b]]
            l3 = math.sqrt(sum((pa[j] - pb[j]) ** 2 for j in range(3)))
            l2 = math.hypot(lumpy[3][lumpy[5][a]] - lumpy[3][lumpy[5][b]], lumpy[4][lumpy[5][a]] - lumpy[4][lumpy[5][b]])
            if l3 > 1e-6:
                rl.append(l2 * tile / l3)
    rl.sort()
    check("lumpy: UVs keep the world scale over the growths",
          abs(rl[len(rl) // 2] - 1.0) < 0.03 and rl[len(rl) // 20] > 0.8 and rl[-len(rl) // 20] < 1.2,
          "p5 %.3f med %.3f p95 %.3f" % (rl[len(rl) // 20], rl[len(rl) // 2], rl[-len(rl) // 20]))

    # Scatter: named by Render as, Arnold set to match
    cmds.select(clear=True)
    res = tb["create_scatter_group"](nodes, "Moss", {"style": "Mat", "coverage": 0.6})
    root = res["root"]
    lid = tb["sc_data"](root)["layers"][0]["id"]
    bed = tb["sc_parts"](root)[lid + "/moss"]
    check("a Mat bed is named _GED", bed.endswith("_GED"), bed.split("|")[-1])
    tb["sc_update"](root, lid, {"render_as": "GES"})
    bed = tb["sc_parts"](root)[lid + "/moss"]
    check("Render as GES renames it _GES", bed.endswith("_GES"), bed.split("|")[-1])
    tb["sc_update"](root, lid, {"style": "Carpet", "detail": "Proxy"})
    bed = tb["sc_parts"](root)[lid + "/moss"]
    check("back to a Proxy Carpet: _GEP as before", bed.endswith("_GEP"), bed.split("|")[-1])
    try:
        cmds.loadPlugin("mtoa", quiet=True)
        arnold = bool(cmds.pluginInfo("mtoa", query=True, loaded=True))
    except Exception:
        arnold = False
    if arnold:
        tb["sc_update"](root, lid, {"style": "Mat", "render_as": "GED", "disp_height": 0.02})
        bed = tb["sc_parts"](root)[lid + "/moss"]
        shape = tb["_log_shape"](bed)
        check("Arnold: a _GED bed is Catmull-Clark, 3 steps, displaced 2 cm with that padding",
              cmds.getAttr(shape + ".aiSubdivType") == 1 and cmds.getAttr(shape + ".aiSubdivIterations") == 3
              and abs(cmds.getAttr(shape + ".aiDispHeight") - 0.02 / M) < 1e-6
              and abs(cmds.getAttr(shape + ".aiDispPadding") - 0.02 / M) < 1e-6)
        look = tb["sc_moss_look"]([root])
        sgs = cmds.listConnections(shape, type="shadingEngine") or []
        check("Moss Look gives a _GED bed the displaced shader",
              tb["MOSS_DISP_SG"] in sgs and cmds.listConnections(tb["MOSS_DISP_SG"] + ".displacementShader"),
              str(sgs))
        tb["sc_update"](root, lid, {"render_as": "GES"})
        bed = tb["sc_parts"](root)[lid + "/moss"]
        shape = tb["_log_shape"](bed)
        sgs = cmds.listConnections(shape, type="shadingEngine") or []
        check("as _GES again it goes back to the plain moss shader, 2 steps",
              "mossGreen_SG" in sgs and cmds.getAttr(shape + ".aiSubdivIterations") == 2, str(sgs))
    else:
        print("SKIP  Arnold checks (MtoA would not load)")

    # an older toolbox: Carpet and Clumps grow exactly as before
    old_path = os.environ.get("UNLOK_OLD_TOOLBOX")
    if old_path and os.path.isfile(old_path):
        tbo = load_toolbox(old_path)
        # (on a smooth rest surface Maya's queries differ in the last bits by call order: compared closely there,
        # exactly on faceted ones)
        for style in ("Carpet", "Clumps"):
            for detail in ("Normal", "High"):
                for surface in ("Faceted", "Auto"):
                    s2 = dict(md, style=style, coverage=0.6, detail=detail, seed=2, surface=surface)
                    so = {k: v for k, v in s2.items() if k in tbo["MOSS_DEFAULTS"]}
                    a = tb["moss_build"](nodes, s2)
                    b = tbo["moss_build"](nodes, so)
                    same = a["moss"][2] == b["moss"][2] and len(a["moss"][3]) == len(b["moss"][3]) and \
                        len(a["moss"][0]) == len(b["moss"][0]) and len(a["strands"][0]) == len(b["strands"][0])
                    gap = max([abs(p[j] - q[j]) for p, q in zip(a["moss"][0], b["moss"][0]) for j in range(3)] +
                              [abs(p[j] - q[j]) for p, q in zip(a["strands"][0], b["strands"][0]) for j in range(3)] +
                              [abs(p - q) for k in (3, 4) for p, q in zip(a["moss"][k], b["moss"][k])])
                    same = same and (gap == 0.0 if surface == "Faceted" else gap < 1e-6)
                    check("%s %s moss (%s) is the same as before" % (style, detail, surface), same,
                          "%d / %d pts, off by %.2g" % (len(a["moss"][0]), len(b["moss"][0]), gap))
        if "Mat" in tbo["MOSS_STYLES"]:  # Bumps 0 and Growths 0 lay the mat the earlier Mat laid (UVs aside)
            s2 = dict(md, style="Mat", coverage=0.6, detail="Normal", seed=2, bumps=0.0, growths=0.0)
            so = {k: v for k, v in s2.items() if k in tbo["MOSS_DEFAULTS"]}
            a = tb["moss_build"](nodes, s2)["moss"]
            b = tbo["moss_build"](nodes, so)["moss"]
            gap = max([abs(p[j] - q[j]) for p, q in zip(a[0], b[0]) for j in range(3)] +
                      [abs(p[j] - q[j]) for p, q in zip(a[0].col, b[0].col) for j in range(3)])
            check("Mat with Bumps 0 and Growths 0 is the earlier Mat (smooth rock: closely)",
                  len(a[0]) == len(b[0]) and a[2] == b[2] and gap < 1e-6,
                  "%d / %d pts, off by %.2g" % (len(a[0]), len(b[0]), gap))
        del tbo
    else:
        print("SKIP  old toolbox comparison (set UNLOK_OLD_TOOLBOX)")


try:
    run()
except Exception:
    traceback.print_exc()
    check("ran without errors", False)
fails = [r for r in RESULTS if not r[1]]
print("%d checks, %d failed" % (len(RESULTS), len(fails)))
sys.stdout.flush()
try:
    maya.standalone.uninitialize()
except Exception:
    pass
os._exit(1 if fails else 0)
