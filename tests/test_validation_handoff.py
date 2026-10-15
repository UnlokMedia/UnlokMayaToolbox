"""Headless tests for Smart UDIM validation (M6) and the hand-off sheet (M7).

    mayapy tests/test_validation_handoff.py [--sheet PATH]

Real-scale test building -> scan -> Auto UV -> smart layout -> validate (must
be clean); then break specific shells on purpose and check each problem is
reported under the right heading; finally render the hand-off sheet.
"""

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_auto_uv.py")).read()
src = src[:src.index("try:\n    run()")]
ns = {"__name__": "validation_test", "__file__": os.path.join(HERE, "test_auto_uv.py")}
exec(compile(src, "test_auto_uv.py", "exec"), ns)
cmds = ns["cmds"]
maya = ns["maya"]

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def uvs_of(tb, shell):
    faces = ["%s.%s" % (shell["mesh"], r) for r in tb["face_ranges"](shell["faces"])]
    return cmds.polyListComponentConversion(faces, toUV=True)


def run():
    tb = ns["load_toolbox"]()
    cmds.loadPlugin("Unfold3D", quiet=True)
    root, kinds = ns["build_building"]()
    cmds.scale(100, 100, 100, root)
    cmds.makeIdentity(root, apply=True, scale=True)
    asset = tb["SmartUdimAsset"].for_group(root)
    asset.scan(sections_from_groups=True)
    tb["run_auto_uv"](asset)
    col = tb["collect_shells"](asset)
    plan = tb["make_plan"](col, dict(tb["LAYOUT_DEFAULTS"], texel_density=128.0, map_size="2048"))
    tb["apply_layout"](asset, col, plan)
    check("layout settings stored for validation", tb["layout_settings_of"](asset).get("density") == 128.0,
          str(tb["layout_settings_of"](asset)))

    t0 = time.time()
    res = tb["validate_layout"](asset)
    t_val = time.time() - t0
    counts = {k: len(v) for k, v in res["items"].items() if v}
    check("validation is quick", t_val < 5.0, "%.2fs for %d shells" % (t_val, res["shells"]))
    check("a fresh layout has no problems (range / crossing / overlap)",
          not any(counts.get(k) for k in ("out_of_range", "crossing", "overlap")), str(counts))
    check("a fresh layout is on target density with proper padding",
          not counts.get("density") and not counts.get("padding") and not counts.get("tiny"), str(counts))

    # --- break things on purpose, one shell each, on different meshes
    unit = 0.01 ** 2
    picks = {}
    used = set()
    shells_by_mesh = {}
    for m in asset.meshes()[0]:
        shells_by_mesh[m] = tb["_mesh_shells"](m, "map1", unit)
    for cat in ("crossing", "out_of_range", "overlap", "flipped", "tiny", "density"):
        for m, shells in sorted(shells_by_mesh.items()):
            if m in used or not shells:
                continue
            big = max(shells, key=lambda s: s["auv"])
            picks[cat] = big
            used.add(m)
            break
    sh = picks["crossing"]
    u0, v0, u1, v1 = sh["box"]
    cmds.polyEditUV(uvs_of(tb, sh), u=(int(u0) + 1) - (u0 + u1) / 2.0, v=0.0, relative=True)
    sh = picks["out_of_range"]
    cmds.polyEditUV(uvs_of(tb, sh), u=-0.5 - sh["box"][0], v=0.0, relative=True)
    sh, target = picks["overlap"], picks["density"]
    # overlap: put this shell right on top of another one in its tile
    others = [s for m, ss in shells_by_mesh.items() if m not in used for s in ss
              if int(s["box"][0]) == int(sh["box"][0]) and int(s["box"][1]) == int(sh["box"][1])]
    other = others[0] if others else [s for m, ss in shells_by_mesh.items() if m not in used for s in ss][0]
    cmds.polyEditUV(uvs_of(tb, sh), u=other["box"][0] - sh["box"][0], v=other["box"][1] - sh["box"][1],
                    relative=True)
    sh = picks["flipped"]
    cu, cv = (sh["box"][0] + sh["box"][2]) / 2.0, (sh["box"][1] + sh["box"][3]) / 2.0
    cmds.polyEditUV(uvs_of(tb, sh), scaleU=-1.0, scaleV=1.0, pivotU=cu, pivotV=cv)
    sh = picks["tiny"]
    cu, cv = (sh["box"][0] + sh["box"][2]) / 2.0, (sh["box"][1] + sh["box"][3]) / 2.0
    cmds.polyEditUV(uvs_of(tb, sh), scaleU=0.0004, scaleV=0.0004, pivotU=cu, pivotV=cv)
    sh = picks["density"]
    cu, cv = (sh["box"][0] + sh["box"][2]) / 2.0, (sh["box"][1] + sh["box"][3]) / 2.0
    cmds.polyEditUV(uvs_of(tb, sh), scaleU=0.6, scaleV=0.6, pivotU=cu, pivotV=cv)

    res = tb["validate_layout"](asset)
    found = {k: set(it["mesh"] for it in v) for k, v in res["items"].items()}
    for cat, sh in sorted(picks.items()):
        check("detects %s" % cat, sh["mesh"] in found.get(cat, set()),
              "%s -> %s" % (sh["mesh"].split("|")[-1], {k: len(v) for k, v in found.items() if v}))
    check("overlap reports both shells", other["mesh"] in found.get("overlap", set()),
          other["mesh"].split("|")[-1])

    # --- hand-off sheet
    t0 = time.time()
    img = tb["render_handoff_sheet"](asset, px_per_tile=256)
    t_sheet = time.time() - t0
    check("hand-off sheet renders", img.width() > 256 and img.height() > 256, "%dx%d in %.2fs" % (
        img.width(), img.height(), t_sheet))
    colors = set()
    for y in range(0, img.height(), 7):
        for x in range(0, img.width(), 7):
            colors.add(img.pixel(x, y))
    check("sheet has real content (many colours)", len(colors) > 40, "%d distinct colours" % len(colors))
    path = sys.argv[sys.argv.index("--sheet") + 1] if "--sheet" in sys.argv else os.path.join(
        os.environ.get("TEMP", HERE), "unlok_handoff_test.png")
    ok = img.save(path, "PNG")
    check("sheet saves as PNG", ok and os.path.getsize(path) > 10000, "%s (%d KB)" % (
        path, os.path.getsize(path) // 1024 if os.path.exists(path) else 0))


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
