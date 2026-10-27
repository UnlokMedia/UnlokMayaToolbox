"""Headless tests for square-per-material layout, Quick Plan and the shell
cache (mayapy).

    mayapy tests/test_squares.py

- squares: every material group's shells sit inside its own square(s);
  squares are square, inside their tile and never overlap; a group bigger
  than a tile is split into several squares
- Fit sections to rows still gives each section one row
- stacked groups and pins work in squares mode
- Quick Plan: one area call per set (no mesh loops), estimated squares, a
  row per section in order, rows even when out of time
- planning again re-uses the shells read before; a changed mesh is re-read
"""

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
    """Shells outside their group's squares, squares overlapping, off-tile."""
    out = []
    by_set = {}
    for udim, x, y, side, node, key in plan["blocks"]:
        by_set.setdefault(node, []).append((udim, x, y, side))
        if x < -1e-9 or y < -1e-9 or x + side > 1.0 + 1e-9 or y + side > 1.0 + 1e-9:
            out.append("square of %s off tile %d" % (key, udim))
    bl = plan["blocks"]
    for i in range(len(bl)):
        for j in range(i + 1, len(bl)):
            a, b = bl[i], bl[j]
            if a[0] != b[0]:
                continue
            if a[1] < b[1] + b[3] - 1e-9 and b[1] < a[1] + a[3] - 1e-9 and \
                    a[2] < b[2] + b[3] - 1e-9 and b[2] < a[2] + a[3] - 1e-9:
                out.append("squares of %s and %s overlap in %d" % (a[5], b[5], a[0]))
    for g in col["groups"]:
        sq = by_set.get(g["set"], [])
        for sh in g["shells"]:
            pl = plan["placements"].get(id(sh))
            if not pl:
                continue
            udim = 1001 + pl[0] + 10 * pl[1]
            x0, y0, x1, y1 = pl[2], pl[3], pl[2] + pl[6], pl[3] + pl[7]
            if not any(u == udim and x0 >= x - 1e-6 and y0 >= y - 1e-6 and x1 <= x + s + 1e-6 and y1 <= y + s + 1e-6
                       for u, x, y, s in sq):
                out.append("a shell of %s outside its squares" % g["key"])
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
        per[b[4]] = per.get(b[4], 0) + 1
    check("a small group is one square", min(per.values()) == 1, str(sorted(per.values())[:6]))

    big = tb["make_plan"](col, dict(base, mode="Fixed density", texel_density=900.0))
    per = {}
    for b in big["blocks"]:
        per[b[4]] = per.get(b[4], 0) + 1
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
    one = [b[4] for b in plan["blocks"] if sum(1 for c in plan["blocks"] if c[4] == b[4]) == 1]
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
        have = set(b[4] for b in qp["blocks"])
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
        for udim, x, y, side, node, key in qp3["blocks"]:
            for u, b in boxes:
                if u == udim and b[0] < x + side and x < b[2] and b[1] < y + side and y < b[3]:
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
              not [b for b in landed if b[4] != g["set"]], "late %s, blocked %s, landed %s" % (
                  late["handsoff_late"], whole, [(b[0], b[5]) for b in landed][:3]))
        cmds.undo()

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
