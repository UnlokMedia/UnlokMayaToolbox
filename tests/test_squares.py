"""Headless tests for square-per-material layout, Quick Plan and the shell
cache (mayapy).

    mayapy tests/test_squares.py

- blocks: every material group's shells sit inside its own rectangle(s);
  blocks are inside their tile and never overlap; a group bigger
  than a tile is split into several squares
- Fit sections to rows still gives each section one row
- stacked groups and pins work in squares mode
- Quick Plan: one area call per set (no mesh loops), estimated squares, a
  row per section in order, rows even when out of time
- planning again re-uses the shells read before; a changed mesh is re-read
"""

import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "squares_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def square_problems(tb, col, plan):
    """Shells outside their group's blocks, blocks overlapping, off-tile."""
    out = []
    by_set = {}
    for udim, x, y, bw, bh, node, key in plan["blocks"]:
        by_set.setdefault(node, []).append((udim, x, y, bw, bh))
        if x < -1e-9 or y < -1e-9 or x + bw > 1.0 + 1e-9 or y + bh > 1.0 + 1e-9:
            out.append("block of %s off tile %d" % (key, udim))
    bl = plan["blocks"]
    for i in range(len(bl)):
        for j in range(i + 1, len(bl)):
            a, b = bl[i], bl[j]
            if a[0] != b[0]:
                continue
            if a[1] < b[1] + b[3] - 1e-9 and b[1] < a[1] + a[3] - 1e-9 and \
                    a[2] < b[2] + b[4] - 1e-9 and b[2] < a[2] + a[4] - 1e-9:
                out.append("blocks of %s and %s overlap in %d" % (a[6], b[6], a[0]))
    for g in col["groups"]:
        sq = by_set.get(g["set"], [])
        for sh in g["shells"]:
            pl = plan["placements"].get(id(sh))
            if not pl:
                continue
            udim = 1001 + pl[0] + 10 * pl[1]
            x0, y0, x1, y1 = pl[2], pl[3], pl[2] + pl[6], pl[3] + pl[7]
            if not any(u == udim and x0 >= x - 1e-6 and y0 >= y - 1e-6 and x1 <= x + bw + 1e-6 and
                       y1 <= y + bh + 1e-6 for u, x, y, bw, bh in sq):
                out.append("a shell of %s outside its blocks" % g["key"])
                break
    return out


def run():
    tb = ns["load_toolbox"]()
    root, kinds = ns["build_building"]()
    cmds.scale(100, 100, 100, root)
    cmds.makeIdentity(root, apply=True, scale=True)
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    tb["run_auto_uv"](asset, score=False, unwrapper=tb["UNWRAP_METHODS"][0], pack="fit")
    base = dict(tb["LAYOUT_DEFAULTS"], texel_density=128.0, map_size="2048", orientation="Upright",
                group_similar=True, keep_meshes=True, squares=True)

    # --- shell cache
    tb["_SHELL_CACHE"].clear()
    t = time.time()
    col = tb["collect_shells"](asset)
    first = time.time() - t
    t = time.time()
    col2 = tb["collect_shells"](asset)
    second = time.time() - t
    n = sum(len(g["shells"]) for g in col["groups"])
    check("planning again re-uses the shells already read", second < first * 0.7,
          "%.2fs then %.2fs (%d shells)" % (first, second, n))
    same = set(id(sh) for g in col["groups"] for sh in g["shells"]) == set(
        id(sh) for g in col2["groups"] for sh in g["shells"])
    check("...the very same shells", same)
    mesh = col["groups"][0]["shells"][0].mesh
    cmds.polyEditUV(mesh + ".map[*]", u=0.01, v=0.0)
    col3 = tb["collect_shells"](asset)
    moved = [sh for g in col3["groups"] for sh in g["shells"] if sh.mesh == mesh]
    check("a mesh whose UVs changed is read again", moved and all(
        id(sh) not in set(id(s) for g in col["groups"] for s in g["shells"]) for sh in moved))
    col = col3

    # --- squares, fixed density
    plan = tb["make_plan"](col, dict(base, mode="Fixed density"))
    probs = square_problems(tb, col, plan)
    check("Fixed density: each group's shells inside its own squares, no overlaps", not probs,
          "; ".join(probs[:4]))
    placed = sum(1 for g in col["groups"] for sh in g["shells"] if id(sh) in plan["placements"])
    check("...every shell placed", placed == n, "%d of %d" % (placed, n))
    per = {}
    for b in plan["blocks"]:
        per[b[5]] = per.get(b[5], 0) + 1
    check("a small group is one square", min(per.values()) == 1, str(sorted(per.values())[:6]))
    fills = {}
    for g in col["groups"]:
        if g["key"].startswith("glassClear"):
            area = sum(sh.area_uv * plan["placements"][id(sh)][4] ** 2 for sh in g["shells"])
            fills[g["set"]] = area / sum(b[3] * b[4] for b in plan["blocks"] if b[5] == g["set"])
    check("identical pieces grid into a square block (two 2:1 panes stack, they don't make a strip)",
          tb["_square_grid"](2, 0.29, 0.15, 10, 10) == (1, 2) and fills and min(fills.values()) > 0.85,
          "grid %s, glass fill %s" % (tb["_square_grid"](2, 0.29, 0.15, 10, 10),
                                      ["%.2f" % v for v in fills.values()]))
    LS = tb["LayoutShell"]
    rect = [(0, 0), (1, 0), (1, 4), (0, 4)]  # a 1 x 4 plank in UV
    logs = [LS("|log%d" % i, [i], 4.0, 4.0, rect, up_dir=d)
            for i, d in enumerate([(0, 1), (0, 1), (0.6, 0.8), (1, 0)])]  # the last one's slope tipped it
    dims = tb["_group_dims"](logs, "up")
    own = [sh.dims["up"] for sh in logs]
    check("long pieces of one material all lie the same way (the majority's), whatever their slope",
          all(h > w for _, w, h in dims) and not all(h > w for _, w, h in own),
          "own %s -> %s" % (["up" if h > w else "across" for _, w, h in own],
                            ["up" if h > w else "across" for _, w, h in dims]))
    # a slab's edges turn with its main face: a wall's ends stay upright like the wall
    wall = [LS("|wall", [0], 18.0, 18.0, [(0, 0), (6, 0), (6, 3), (0, 3)], up_dir=(0, 1))]
    wall += [LS("|wall", [i], 0.9, 0.9, [(0, 0), (0.3, 0), (0.3, 3), (0, 3)], up_dir=(0, 1)) for i in (1, 2)]
    wall += [LS("|wall", [3], 1.8, 1.8, [(0, 0), (6, 0), (6, 0.3), (0, 0.3)])]  # its top: flat
    dims = tb["_group_dims"](wall + logs, "up")[:4]
    check("a wall's thin ends stay upright (they turn with the wall, they don't vote)",
          dims[0][1] > dims[0][2] and all(h > w for _, w, h in dims[1:3]), str([d[1:] for d in dims]))
    board = [LS("|board", [0], 0.4, 0.4, [(0, 0), (0.2, 0), (0.2, 2), (0, 2)], up_dir=(0, 1))]
    board += [LS("|board", [i], 0.04, 0.04, [(0, 0), (0.02, 0), (0.02, 2), (0, 2)], up_dir=(0, 1)) for i in (1, 2)]
    flat = [LS("|beam%d" % i, [i], 4.0, 4.0, [(0, 0), (4, 0), (4, 1), (0, 1)], up_dir=(0, 1)) for i in range(3)]
    dims = tb["_group_dims"](board + flat, "up")[:3]
    check("...and a board outvoted by the beams turns whole, its edges with it",
          all(w > h for _, w, h in dims), str([d[1:] for d in dims]))
    mixed = []
    for g in col["groups"]:
        ways = set()
        edges = tb["_slab_edges"](g["shells"], [sh.dims["up"] for sh in g["shells"]])
        for i, sh in enumerate(g["shells"]):
            if i in edges:
                continue
            pl = plan["placements"].get(id(sh))
            if pl and min(pl[6], pl[7]) > 0 and max(pl[6], pl[7]) >= 1.5 * min(pl[6], pl[7]):
                ways.add(pl[7] > pl[6])
        if len(ways) > 1:
            mixed.append(g["key"])
    check("...and in a real Upright plan no material mixes up and across long pieces (a slab's edges aside)", not mixed, str(mixed))

    # --- left to right by material, and the row options
    sec_of_set = dict((g["set"], g["section"]) for g in col["groups"])

    def spans(pl):
        """{section: {key: (first tile, last tile)}} from a plan's blocks."""
        out = {}
        for udim, x, y, bw, bh, node, key in pl["blocks"]:
            lo, hi = out.setdefault(sec_of_set[node], {}).get(key, (udim, udim))
            out[sec_of_set[node]][key] = (min(lo, udim), max(hi, udim))
        return out

    order_bad = []
    for sec, by_key in spans(plan).items():
        keys = sorted(by_key, key=str.lower)
        for a, b in zip(keys, keys[1:]):
            if by_key[a][1] > by_key[b][0]:
                order_bad.append("%s: %s ends at %d after %s starts at %d" % (sec, a, by_key[a][1], b, by_key[b][0]))
    check("each row goes left to right by material (A-Z); no material fills an earlier one's gaps", not order_bad,
          "; ".join(order_bad[:3]))
    ordered_plan = tb["make_plan"](col, dict(base, mode="Fixed density", material_order="wood*"))
    wood_first = all(by_key.get("woodBrown", (0, 0))[0] == min(v[0] for v in by_key.values())
                     for by_key in spans(ordered_plan).values() if "woodBrown" in by_key)
    check("Material order: 'wood*' puts wood at the start of every row", wood_first,
          str(dict((k, v.get("woodBrown")) for k, v in spans(ordered_plan).items())))
    own = tb["make_plan"](col, dict(base, mode="Fixed density", first_materials="glass*"))
    glass_tiles = set(b[0] for b in own["blocks"] if b[6].startswith("glass"))
    others_there = [b[6] for b in own["blocks"] if b[0] in glass_tiles and not b[6].startswith("glass")]
    firsts = [min(v[0] for v in by_key.values()) for by_key in spans(own).values() if any(
        k.startswith("glass") for k in by_key)]
    check("Own UDIM first: glass gets the first UDIM of its row, shared with nothing else",
          glass_tiles and not others_there and all(t in glass_tiles for t in firsts),
          "glass in %s, others there %s" % (sorted(glass_tiles), others_there))
    lined = tb["make_plan"](col, dict(base, mode="Fixed density", align_columns=True, first_materials="glass*"))
    cols = {}
    for sec, by_key in spans(lined).items():
        for key, (lo, hi) in by_key.items():
            cols.setdefault(key, set()).add((lo - 1001) % 10)
    shared = dict((k, v) for k, v in cols.items() if len([s for s in spans(lined).values() if k in s]) > 1)
    check("Line up materials in columns: every shared material starts in the same column in each section",
          shared and all(len(v) == 1 for v in shared.values()), str(shared))

    big = tb["make_plan"](col, dict(base, mode="Fixed density", texel_density=900.0))
    per = {}
    for b in big["blocks"]:
        per[b[5]] = per.get(b[5], 0) + 1
    probs = square_problems(tb, col, big)
    check("a group bigger than a tile is split into several squares", max(per.values()) > 1 and not probs,
          "most squares for one group: %d; %s" % (max(per.values()), "; ".join(probs[:3])))

    # --- fit rows
    t = time.time()
    rows = tb["make_plan"](col, dict(base, mode=tb["FIT_ROWS"]))
    secs = time.time() - t
    sr = tb["section_rows"](col, rows)
    probs = square_problems(tb, col, rows)
    check("Fit rows with squares: one row per section, squares clean",
          all(len(r) <= 1 for r in sr.values()) and not probs,
          "%.2fs, %d px/m, %s" % (secs, rows["density"], "; ".join(probs[:3])))

    # --- freeform still works (squares off)
    free = tb["make_plan"](col, dict(base, mode="Fixed density", squares=False))
    check("squares off: the freeform layout still places every shell", len(free["placements"]) >= placed and
          not free["blocks"])

    # --- pins
    one = [b[5] for b in plan["blocks"] if sum(1 for c in plan["blocks"] if c[5] == b[5]) == 1]
    g0 = [g for g in col["groups"] if g["set"] in one][0]
    g0["pin"] = [1095]
    pinned = tb["make_plan"](col, dict(base, mode="Fixed density"))
    g0["pin"] = []
    tiles = pinned["stats"][g0["set"]]["tiles"]
    check("a pinned group's square goes in its pinned tile", tiles == [1095], str(tiles))

    # --- stacked group
    g1 = [g for g in col["groups"] if len(g["shells"]) > 3][0]
    g1["stack"] = True
    st = tb["make_plan"](col, dict(base, mode="Fixed density"))
    g1["stack"] = False
    got = sum(1 for sh in g1["shells"] if id(sh) in st["placements"])
    check("stacked groups place every copy in squares mode", got == len(g1["shells"]),
          "%d of %d" % (got, len(g1["shells"])))

    # --- the largest shell caps the density; Fit largest shell lays out at it
    top = tb["largest_shells"](col, base, 5)
    fixed_s = dict(base, mode="Fixed density")
    usable = 1.0 - 2.0 * float(base["padding_px"]) / float(base["map_size"])

    def lowered(pl):
        return [w for w in pl["warnings"] if "didn't fit a tile" in w]

    def size_of(pl, r):
        for g in col["groups"]:
            for sh in g["shells"]:
                if sh.mesh == r["mesh"] and sh.uv_ids == r["uv_ids"] and id(sh) in pl["placements"]:
                    q = pl["placements"][id(sh)]
                    return max(q[6], q[7])
        return 0.0
    at = tb["plan_layout"](col, dict(fixed_s, texel_density=top[0]["density"] * 0.999))
    over = tb["plan_layout"](col, dict(fixed_s, texel_density=top[0]["density"] * 1.05))
    got = size_of(at, top[0])
    check("the largest shell's density makes it just fill a UDIM (inside the padding)",
          top and abs(got - usable) < 0.01 and not lowered(at) and lowered(over) and
          all(a["density"] <= b["density"] for a, b in zip(top, top[1:])),
          "%d px/m -> %.4f of %.4f; over: %s" % (top[0]["density"], got, usable, lowered(over)[:1]))
    fit = tb["make_plan"](col, dict(base, mode=tb["FIT_LARGEST"]))
    check("Fit largest shell: that density for everything, nothing shrunk, squares clean",
          abs(fit["density"] - top[0]["density"]) < 0.01 * top[0]["density"] and not lowered(fit) and
          fit["largest"]["mesh"] == top[0]["mesh"] and not square_problems(tb, col, fit) and
          len(fit["placements"]) == len(at["placements"]),
          "%d px/m, %d tiles, %s" % (fit["density"], len(fit["new_tiles"]), lowered(fit)[:1]))
    cmds.polyAutoProjection(top[0]["mesh"])  # cut the largest shell up: the cap goes up
    after = tb["largest_shells"](tb["collect_shells"](asset), base, 1)
    check("cutting the largest shell up raises the cap (planning again re-reads just that mesh)",
          after and (after[0]["density"] > top[0]["density"] or after[0]["mesh"] != top[0]["mesh"]),
          "%d -> %d px/m (%s)" % (top[0]["density"], after[0]["density"] if after else 0,
                                  after and tb["short_name"](after[0]["mesh"])))
    cmds.undo()

    # --- Quick Plan: from the set names only
    def no_meshes(*a, **k):
        raise RuntimeError("Quick Plan touched a mesh")
    saved = dict((n, tb[n]) for n in ("_mesh_fn", "_group_print", "uv_footprints"))  # set reads are fine
    tb.update(dict((n, no_meshes) for n in saved))
    try:
        t = time.time()
        q = tb["quick_groups"](asset)
        qp = tb["plan_layout"](q, dict(base, mode="Fixed density"))
        secs = time.time() - t
        ok = True
    except RuntimeError as e:
        ok, secs, q, qp = str(e), 0.0, None, None
    tb.update(saved)
    check("Quick Plan never loops over meshes (one C++ area call per set), quickly", ok is True and secs < 1.0,
          "%s, %.3fs" % (ok, secs))
    if q:
        have = set(b[5] for b in qp["blocks"])
        sized = set(g["set"] for g in q["groups"] if g["area"])
        check("Quick Plan: every measured group gets an estimated square", sized and sized <= have and
              not square_problems(tb, q, qp), "%d of %d" % (len(have & sized), len(q["groups"])))
        fit = tb["make_plan"](q, dict(base, mode=tb["FIT_ROWS"]))
        ratio = fit["density"] / rows["density"]
        check("Quick Plan's Fit rows density is in the ballpark of the real one", 0.6 < ratio < 1.6,
              "%d vs %d px/m (%.2f)" % (fit["density"], rows["density"], ratio))
        none = tb["quick_groups"](asset, budget=0.0)
        np_ = tb["plan_layout"](none, dict(base, mode="Fixed density"))
        sr = tb["section_rows"](none, np_)
        check("out of time: no squares, but every section still gets its own row", not np_["blocks"] and
              len(sr) == len(set(g["section_index"] for g in none["groups"])) and
              len(set(min(r) for r in sr.values())) == len(sr), str(sr))
        sr = tb["section_rows"](q, qp)
        order = [min(sr[si]) for si in sorted(sr)]
        check("Quick Plan: a row per section, in section order",
              all(len(r) == 1 for r in sr.values()) and order == sorted(order) and len(set(order)) == len(order),
              str(order))
        secs_before = asset.sections()
        asset.move_section(secs_before[0], len(secs_before) - 1)
        q2 = tb["quick_groups"](asset)
        qp2 = tb["plan_layout"](q2, dict(base, mode="Fixed density"))
        top = max(tb["section_rows"](q2, qp2).items(), key=lambda kv: max(kv[1]))[0]
        moved = [g["section"] for g in q2["groups"] if g["section_index"] == top]
        check("moving a section to the end puts its row on top", moved and moved[0] == secs_before[0],
              "%s vs %s" % (moved[:1], secs_before[0]))
        cmds.undo()

        # hands off: the piece stays where it is, squares go around it, its area isn't in its square
        g = max(q["groups"], key=lambda g: g["area"] or 0)
        mesh = sorted(tb["expand_members"](g["set"])[0])[0]
        before = g["area"]
        asset.set_uv_status([mesh], "handsoff")
        q3 = tb["quick_groups"](asset)
        qp3 = tb["plan_layout"](q3, dict(base, mode="Fixed density"))
        g3 = [x for x in q3["groups"] if x["set"] == g["set"]][0]
        boxes = [(fx["udim"], fx["box"]) for fx in q3["fixed"]]
        hit = []
        for udim, x, y, bw, bh, node, key in qp3["blocks"]:
            for u, b in boxes:
                if u == udim and b[0] < x + bw and x < b[2] and b[1] < y + bh and y < b[3]:
                    hit.append((key, udim))
        check("Quick Plan: hands-off pieces stay put and squares pack around them",
              boxes and not hit and g3["area"] < before and set(u for u, _ in boxes) <= set(qp3["tiles"]),
              "%d fixed boxes, overlaps %s, area %.2f -> %.2f" % (len(boxes), hit[:3], before, g3["area"] or 0))

        # ...and it's never read: every per-UV reader is a trap for that mesh
        touched = []
        real = dict((n, tb[n]) for n in ("_mesh_fn", "uv_footprints", "mesh_fingerprint", "uv_quality",
                                         "oversplit", "_mesh_cache"))

        def trap(name):
            def fn(xform, *a, **k):
                if xform == mesh:
                    touched.append(name)
                    raise RuntimeError("read a Hands off mesh with %s" % name)
                return real[name](xform, *a, **k)
            return fn
        tb.update(dict((n, trap(n)) for n in real))
        errors = []
        for label, call in (("Quick Plan", lambda: tb["quick_groups"](asset)),
                            ("Plan", lambda: tb["collect_shells"](asset)),
                            ("Validate", lambda: tb["validate_layout"](asset)),
                            ("hand-off sheet", lambda: tb["render_handoff_sheet"](asset, px_per_tile=64))):
            try:
                call()
            except Exception as e:
                errors.append("%s: %s" % (label, e))
        tb.update(real)
        col_ho = tb["collect_shells"](asset)
        spots = [fx for fx in col_ho["fixed"] if fx["mesh"] == mesh]
        check("a Hands off mesh is never read (one UV-box query), in Quick Plan, Plan, Validate and the sheet",
              not touched and not errors and spots, "%s %s, %d spot(s)" % (touched[:3], errors[:2], len(spots)))
        # out of time: its group's tiles from the last layout are blocked whole
        cmds.addAttr(g["set"], longName=tb["LAYOUT_TILES"], dataType="string") if not cmds.attributeQuery(
            tb["LAYOUT_TILES"], node=g["set"], exists=True) else None
        cmds.setAttr(g["set"] + "." + tb["LAYOUT_TILES"], "1005,1006", type="string")
        real_finder = tb["HandsOffFinder"]
        tb["HandsOffFinder"] = lambda uv_set="map1": real_finder(uv_set, budget=0.0)
        try:
            late = tb["collect_shells"](asset)
            q_late = tb["quick_groups"](asset)
        finally:
            tb["HandsOffFinder"] = real_finder
        whole = sorted(fx["udim"] for fx in late["fixed"] if fx["mesh"] == mesh and fx["box"] == (0.0, 0.0, 1.0, 1.0))
        plan_late = tb["plan_layout"](late, dict(base, mode="Fixed density"))
        landed = [b for b in plan_late["blocks"] if b[0] in (1005, 1006)]
        check("past the time limit, its group's tiles are blocked whole and nothing else lands there",
              late["handsoff_late"] == [mesh] and q_late["handsoff_late"] == [mesh] and whole == [1005, 1006] and
              not [b for b in landed if b[5] != g["set"]], "late %s, blocked %s, landed %s" % (
                  late["handsoff_late"], whole, [(b[0], b[6]) for b in landed][:3]))
        cmds.undo()

    # --- quick look: a selection laid out together in a free UDIM of its own
    every = asset.meshes()[0]
    picked = [m for m in every if "wall" in m or "column" in m][:8]
    others = [m for m in every if m not in picked]
    udim = tb["free_tile_for"](picked, others)
    used_by_others = set()
    for t in tb["mesh_tiles"](others).values():
        used_by_others |= t
    with tb["UndoChunk"]("Lay Out Selected"):
        assigned = asset.assignments()
        keys = dict((m, tb["_get"](assigned[m][0][0], tb["UDIM_KEY"]) or
                     tb["parse_group_name"](assigned[m][0][0])["key"]) for m in picked if assigned.get(m))
        n = tb["lay_out_together"](picked, udim=udim, keys=keys)
    tu, tv = (udim - 1001) % 10, (udim - 1001) // 10
    inside = all(tb["mesh_tiles"]([m])[m] == {udim} for m in picked)
    boxes, ratios = [], []
    unit = tb["scene_m_per_unit"]() ** 2
    for m in picked:
        shells_, _ = tb["_read_shells"](m, None, "map1", unit, {}, set())
        for sh in shells_:
            xs = [sh.cx + q[0] for q in sh.hull]
            ys = [sh.cy + q[1] for q in sh.hull]
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
            ratios.append(sh.area_uv / sh.area3d)
    clash = [1 for i, a in enumerate(boxes) for b in boxes[i + 1:]
             if a[0] < b[2] - 1e-6 and b[0] < a[2] - 1e-6 and a[1] < b[3] - 1e-6 and b[1] < a[3] - 1e-6]
    even = max(ratios) / min(ratios) < 1.05
    cmds.undo()
    # a mesh whose UVs are scattered over 30 tiles doesn't push the pick up the grid
    spread = cmds.polyPlane(w=10, h=10, sx=4, sy=4, name="spreadUVs")[0]
    cmds.polyEditUV(spread + ".map[*]", scaleU=30, scaleV=3, pivotU=0, pivotV=0)
    low = tb["free_tile_for"](picked, others + [cmds.ls(spread, long=True)[0]])
    cmds.delete(spread)
    check("a mesh with scattered UVs only counts its main tile when picking the quick look's UDIM",
          low <= udim + 1, "picked %d (without it %d)" % (low, udim))
    check("Lay Out Selected: the selection together in a UDIM nothing else uses, even density, nothing overlapping",
          n > 0 and udim not in used_by_others and inside and not clash and even,
          "udim %d, %d shells, inside %s, %d box overlaps, density spread %.3f" % (
              udim, n, inside, len(clash), max(ratios) / min(ratios)))

    # --- just some shells: a picked face takes its whole shell; the rest stays put
    halves = cmds.polyPlane(w=100, h=50, sx=4, sy=2, name="twoHalves")[0]
    cmds.polyMapCut(["%s.e[%d]" % (halves, e) for e in range(cmds.polyEvaluate(halves, edge=True))
                     if abs(cmds.xform("%s.e[%d]" % (halves, e), q=True, bb=True, ws=True)[0]) < 1e-6 and
                     abs(cmds.xform("%s.e[%d]" % (halves, e), q=True, bb=True, ws=True)[3]) < 1e-6],
                    constructionHistory=False)
    halves = cmds.ls(halves, long=True)[0]
    left = [f for f in range(cmds.polyEvaluate(halves, face=True))
            if cmds.xform("%s.f[%d]" % (halves, f), q=True, bb=True, ws=True)[3] <= 1e-6]
    grown = tb["shell_faces"](halves, [left[0]])
    right_uvs = cmds.polyEditUV(cmds.polyListComponentConversion(
        ["%s.f[%d]" % (halves, f) for f in range(cmds.polyEvaluate(halves, face=True)) if f not in left],
        toUV=True), q=True)
    with tb["UndoChunk"]("Lay Out Selected"):
        n2 = tb["lay_out_together"]({halves: grown}, udim=1007)
    left_tiles = tb["face_tiles"](halves, grown)
    right_after = cmds.polyEditUV(cmds.polyListComponentConversion(
        ["%s.f[%d]" % (halves, f) for f in range(cmds.polyEvaluate(halves, face=True)) if f not in left],
        toUV=True), q=True)
    cmds.undo()
    cmds.delete(halves)
    check("Lay Out Selected on part of a mesh: a picked face takes its whole shell, the rest stays put",
          grown == set(left) and n2 == 1 and left_tiles == {1007} and right_after == right_uvs,
          "grown %s vs half %s, %d shell(s), tiles %s, rest unchanged %s" % (
              sorted(grown or []), sorted(left), n2, sorted(left_tiles), right_after == right_uvs))

    # --- Keep Layout is one rigid block; faces too small to count go along
    kit = cmds.group(empty=True, name="kit_GRP")
    kgrp = cmds.group(empty=True, name="crateA_GRP", parent=kit)
    kl = cmds.polyCube(w=100, h=60, d=40, name="woodBrown_C_crate0001_GEP")[0]
    kl = cmds.ls(cmds.parent(kl, kgrp)[0], long=True)[0]
    cmds.polyAutoProjection(kl, constructionHistory=False)
    cmds.polyMapCut(cmds.polyListComponentConversion(kl + ".f[2]", toEdge=True), constructionHistory=False)
    cmds.polyEditUV(cmds.polyListComponentConversion(kl + ".f[2]", toUV=True), scaleU=0, scaleV=0)  # collapsed
    board = cmds.polyPlane(w=100, h=100, sx=3, sy=3, name="woodBrown_C_board0001_GEP")[0]
    board = cmds.ls(cmds.parent(board, kgrp)[0], long=True)[0]
    cmds.polyMapCut(cmds.polyListComponentConversion(board + ".f[4]", toEdge=True), constructionHistory=False)
    sliver = cmds.ls(cmds.polyListComponentConversion(board + ".f[4]", toVertex=True), flatten=True)
    for v in sliver[1:]:
        cmds.xform(v, t=cmds.pointPosition(sliver[0], world=True), ws=True)  # a zero-area face, own shell
    for m in (kl, board):
        cmds.polyEditUV(m + ".map[*]", u=5.0, v=0.0)
    kasset = tb["SmartUdimAsset"].for_group(kit)
    kasset.scan(sections_from_groups=True)
    kasset.set_uv_status([kl], "keeplayout")

    def uvs_of(m):
        q = cmds.polyEditUV(m + ".map[*]", q=True)
        return list(zip(q[0::2], q[1::2]))

    def rigid(old, new):
        """new = k * old + offset for every UV (one scale, one move)?"""
        i = max(range(len(old)), key=lambda j: abs(old[j][0] - old[0][0]) + abs(old[j][1] - old[0][1]))
        d_old = math.hypot(old[i][0] - old[0][0], old[i][1] - old[0][1])
        k = math.hypot(new[i][0] - new[0][0], new[i][1] - new[0][1]) / d_old
        ou, ov = new[0][0] - k * old[0][0], new[0][1] - k * old[0][1]
        return max(abs(k * a + ou - c) + abs(k * b + ov - d) for (a, b), (c, d) in zip(old, new)) < 1e-4

    def tiles(m):
        return sorted(set(1001 + int(u) + 10 * int(v) for u, v in uvs_of(m)))

    before = uvs_of(kl)
    kcol = tb["collect_shells"](kasset)
    tb["apply_layout"](kasset, kcol, tb["make_plan"](kcol, dict(base, mode="Fixed density")))
    check("Apply: a Keep Layout mesh moves as one rigid block (one scale, one move, every UV), and a "
          "collapsed face or a zero-area face goes along with its mesh",
          rigid(before, uvs_of(kl)) and len(tiles(kl)) == 1 and len(tiles(board)) == 1,
          "keep layout rigid %s, tiles %s / %s" % (rigid(before, uvs_of(kl)), tiles(kl), tiles(board)))
    for m in (kl, board):
        cmds.polyEditUV(m + ".map[*]", u=3.0, v=1.0)
    before = uvs_of(kl)
    with tb["UndoChunk"]("Lay Out Selected"):
        tb["lay_out_together"]([kl, board], udim=1009, keep_layout=[kl])
    check("Lay Out Selected: the Keep Layout mesh moves as one rigid block too, nothing left behind",
          rigid(before, uvs_of(kl)) and tiles(kl) == [1009] and tiles(board) == [1009],
          "rigid %s, tiles %s / %s" % (rigid(before, uvs_of(kl)), tiles(kl), tiles(board)))
    cmds.delete(kit)

    # --- a Hands off mesh with broken (infinite) UVs never stops anything
    # ('cannot convert float infinity to integer' in Lay Out Selected,
    # Auto UV's packing and the sheet)
    import maya.api.OpenMaya as om2
    junk = cmds.polyCube(w=100, h=100, d=100, name="metalGrey_C_junk0001_GEP")[0]
    junk = cmds.ls(cmds.parent(junk, cmds.listRelatives(picked[0], parent=True, fullPath=True)[0])[0], long=True)[0]
    sel_ = om2.MSelectionList()
    sel_.add(cmds.listRelatives(junk, shapes=True, fullPath=True)[0])
    fn_ = om2.MFnMesh(sel_.getDagPath(0))
    us_, vs_ = fn_.getUVs()
    us_, vs_ = list(us_), list(vs_)
    vs_[2] = float("inf")
    fn_.setUVs(us_, vs_)
    asset.scan(sections_from_groups=True)
    asset.set_uv_status([junk], "handsoff")
    errors = []
    for label, fn in (("free tile", lambda: tb["free_tile_for"](picked, [junk] + others)),
                      ("plan", lambda: tb["oversize_shells"](tb["collect_shells"](asset), tb["make_plan"](
                          tb["collect_shells"](asset), dict(base, mode=tb["FIT_ROWS"])), asset.uv_status())),
                      ("quick plan", lambda: tb["make_plan"](tb["quick_groups"](asset), dict(base, mode=tb["FIT_ROWS"]))),
                      ("sheet", lambda: tb["render_handoff_sheet"](asset, px_per_tile=32))):
        try:
            fn()
        except Exception as e:
            errors.append("%s: %s" % (label, e))
    check("a Hands off mesh with infinite UVs doesn't stop the free-tile pick, Plan, Quick Plan or the sheet",
          not errors and tb["handsoff_box"](junk) is None, "; ".join(errors))
    cmds.delete(junk)

    # --- a floor too big for a UDIM: split at its thirds (40 m at 128 px/m on
    # 2048 maps: a tile holds 16 m), one Ctrl+Z, and then it fits whole parts
    yard = cmds.group(empty=True, name="yard_GRP", parent=root)
    floor = cmds.polyPlane(w=4000, h=4000, sx=24, sy=24, name="stoneGrey_C_yard0001_GEP")[0]
    floor = cmds.parent(floor, yard)[0]
    asset.scan(sections_from_groups=True)
    col = tb["collect_shells"](asset)
    plan = tb["plan_layout"](col, dict(base, mode="Fixed density"))
    status = asset.uv_status()
    big = [it for it in tb["oversize_shells"](col, plan, status) if it["mesh"].endswith("yard0001_GEP")]
    with tb["UndoChunk"]("Split Big Shells"):
        tb["split_shells"](big)
    parts = tb["_mesh_fn"](cmds.ls(floor, long=True)[0]).getUvShellsIds("map1")[0]
    col2 = tb["collect_shells"](asset)
    plan2 = tb["plan_layout"](col2, dict(base, mode="Fixed density"))
    still = [it for it in tb["oversize_shells"](col2, plan2, status) if it["mesh"].endswith("yard0001_GEP")]
    cmds.undo()
    back = tb["_mesh_fn"](cmds.ls(floor, long=True)[0]).getUvShellsIds("map1")[0]
    check("a floor too big for a UDIM is cut at its thirds, then fits; one Ctrl+Z puts it back",
          len(big) == 1 and (big[0]["cols"], big[0]["rows"]) == (3, 3) and parts == 9 and not still and back == 1,
          "found %s, %d parts, still too big %d, after undo %d shell(s)" % (
              [(it["cols"], it["rows"]) for it in big], parts, len(still), back))

try:
    run()
except Exception:
    traceback.print_exc()
    RESULTS.append(("exception", False, ""))
finally:
    failed = [r for r in RESULTS if not r[1]]
    print("\n%d passed, %d failed" % (len(RESULTS) - len(failed), len(failed)))
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(1 if failed else 0)
