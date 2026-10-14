"""Headless Path Scatter benchmark (mayapy).

    mayapy tests/bench_scatter.py [--profile]

Times rebuilds and bakes for heavy, realistic setups and prints a table.
With --profile, also prints the top functions for the thatch rebuild.
"""

import cProfile
import io
import os
import pstats
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402


def load():
    ns = {"__name__": "bench", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    return ns


def roof():
    left = cmds.polyPlane(w=8.6, h=4.6, sx=40, sy=20, name="roofLeft")[0]
    cmds.rotate(-35, 0, 0, left)
    cmds.move(0, 5.3, -1.85, left)
    right = cmds.polyPlane(w=8.6, h=4.6, sx=40, sy=20, name="roofRight")[0]
    cmds.rotate(35, 0, 0, right)
    cmds.move(0, 5.3, 1.85, right)
    for n in (left, right):
        cmds.makeIdentity(n, apply=True)
    a = cmds.curve(degree=3, point=[(-4.2, 3.98, 3.73), (-1.4, 3.98, 3.73), (1.4, 3.98, 3.73), (4.2, 3.98, 3.73)])
    b = cmds.curve(degree=3, point=[(4.2, 3.98, -3.73), (1.4, 3.98, -3.73), (-1.4, 3.98, -3.73), (-4.2, 3.98, -3.73)])
    return [left, right], [a, b]


def timed(fn, repeat=3):
    best = None
    out = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = fn()
        dt = (time.perf_counter() - t0) * 1000.0
        best = dt if best is None else min(best, dt)
    return best, out


def main():
    tb = load()
    PSS = tb["PathScatterSystem"]
    D = dict(tb["PS_DEFAULTS"])
    thatch = dict(D)
    thatch.update({k: v for k, v in tb["RECIPES"]["Messy Thatch"].items() if not k.startswith("_")})
    rows = []

    # --- thatch: dense, two surfaces, snapping + normals
    cmds.file(new=True, force=True)
    surfaces, curves = roof()
    sysm = PSS.create(thatch)
    sysm.set_paths(curves)
    sysm.set_surfaces(surfaces)
    sysm.rebuild(thatch)
    def cold(settings):
        sysm.invalidate()
        return sysm.rebuild(settings)
    ms, res = timed(lambda: cold(thatch))
    rows.append(("thatch rebuild (cold)", res[0], ms))
    ms, res = timed(lambda: sysm.rebuild(thatch))
    rows.append(("thatch rebuild (nothing changed)", res[0], ms))
    angles = iter(range(10, 1000, 7))  # a different rotation every repeat (no cache hit)
    ms, res = timed(lambda: sysm.rebuild(dict(thatch, rot_x=float(next(angles)))))
    rows.append(("thatch: rotate offset changed", res[0], ms))
    ms, res = timed(lambda: cold(dict(thatch, seed=7)))
    rows.append(("thatch: new seed (cold)", res[0], ms))
    profile_text = ""
    if "--profile" in sys.argv:
        prof = cProfile.Profile()
        sysm.invalidate()
        prof.enable()
        sysm.rebuild(dict(thatch, seed=11))
        prof.disable()
        buf = io.StringIO()
        pstats.Stats(prof, stream=buf).sort_stats("tottime").print_stats(18)
        profile_text = buf.getvalue()
    for mode in ("Copies", "Combined Mesh", "Instances"):
        if mode == "Instances" and "--quick" in sys.argv:
            continue
        s = dict(thatch, bake_mode=mode, keep_system=True)
        t0 = time.perf_counter()
        if mode == "Copies" and "--profile" in sys.argv:
            bprof = cProfile.Profile()
            bprof.enable()
        out = sysm.bake(s)
        if mode == "Copies" and "--profile" in sys.argv:
            bprof.disable()
            buf = io.StringIO()
            pstats.Stats(bprof, stream=buf).sort_stats("tottime").print_stats(12)
            profile_text += "\n--- bake copies ---\n" + buf.getvalue()
        rows.append(("thatch bake: " + mode, res[0], (time.perf_counter() - t0) * 1000.0))
        cmds.delete(out)

    # --- big flat array, no surface
    cmds.file(new=True, force=True)
    c = cmds.curve(degree=1, point=[(0, 0, 0), (200, 0, 0)])
    big = dict(D, dist_mode="Spacing", spacing=0.1, rows=10, row_spacing=0.2, max_items=50000)
    sysm = PSS.create(big)
    sysm.set_paths([c])
    sysm.rebuild(big)
    ms, res = timed(lambda: (sysm.invalidate(), sysm.rebuild(big))[1])
    rows.append(("20k array rebuild (cold)", res[0], ms))

    # --- rocks: heavy mesh variants, random everything
    cmds.file(new=True, force=True)
    rocks = [cmds.polySphere(r=0.3, sx=120, sy=80, name="rock%d" % i)[0] for i in range(3)]
    c = cmds.curve(degree=3, point=[(0, 0, 0), (10, 0, 5), (20, 0, -5), (30, 0, 0)])
    rk = dict(D, source_type="Mesh", dist_mode="Spacing", spacing=0.05, rows=4, row_spacing=0.3,
              rand_rot_x=180, rand_rot_y=180, rand_rot_z=180, rand_scale_min=0.5, rand_scale_max=1.5)
    sysm = PSS.create(rk)
    sysm.set_paths([c])
    sysm.set_sources(rocks)
    sysm.rebuild(rk)
    ms, res = timed(lambda: (sysm.invalidate(), sysm.rebuild(rk))[1])
    rows.append(("rocks (heavy sources) rebuild (cold)", res[0], ms))

    print("\n%-34s %8s %10s" % ("case", "items", "ms"))
    for name, n, ms in rows:
        print("%-34s %8d %10.1f" % (name, n, ms))
    if "--profile" in sys.argv:
        print("\n" + profile_text)
    try:
        import numpy
        print("numpy", numpy.__version__, numpy.__file__)
    except ImportError:
        print("numpy: not available")


try:
    main()
except Exception:
    traceback.print_exc()
finally:
    sys.stdout.flush()
    maya.standalone.uninitialize()
    os._exit(0)
