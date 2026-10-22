"""Headless tests for Log Noise (mayapy).

    mayapy tests/test_log_noise.py

Checks the plugin-free port against the original logNoise deformer
(contrib/log_noise/log_noise.py), plus undo, live edits, masks, reset, bake,
topology changes, save/reopen and speed.
"""

import math
import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
CONTRIB = os.path.join(os.path.dirname(HERE), "contrib", "log_noise", "log_noise.py")

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    sys.stdout.flush()


def load_toolbox():
    ns = {"__name__": "unlok_test", "__file__": TOOLBOX}
    with open(TOOLBOX) as f:
        exec(compile(f.read(), TOOLBOX, "exec"), ns)
    return ns


def log(name, history=True, scale=1.0, **kw):
    args = dict(r=0.15 * scale, h=2.0 * scale, sx=24, sy=20, name=name, constructionHistory=history)
    args.update(kw)
    return cmds.ls(cmds.polyCylinder(**args)[0], long=True)[0]


def run():
    tb = load_toolbox()
    pts = lambda x: tb["_ln_points"](tb["_log_shape"](x))  # noqa: E731

    def maxdiff(a, b):
        return max(max(abs(p[k] - q[k]) for k in range(3)) for p, q in zip(a, b))

    # --- parity with the original deformer (its plugin file goes to a temp folder: test only)
    src = open(CONTRIB).read()
    plugin_src = src.split("PLUGIN_SRC = r'''", 1)[1].split("'''", 1)[0]
    folder = tempfile.mkdtemp(prefix="lognoise")
    path = os.path.join(folder, "logNoise.py")
    with open(path, "w") as fh:
        fh.write(plugin_src)
    cmds.loadPlugin(path)
    worst = 0.0
    for seed in (0, 1234, 9876):
        a = log("defA")
        b = log("portB")
        node = cmds.deformer(a, type="logNoise")[0]
        cmds.setAttr(node + ".seed", seed)
        tb["add_log_noise"]([b], seeds={b: seed})
        worst = max(worst, maxdiff(pts(a), pts(b)))
        cmds.delete(a, b)
    check("same shapes as the original deformer (3 seeds, default settings)", worst < 1e-5,
          "worst %.2g" % worst)
    a, b = log("defA"), log("portB")
    node = cmds.deformer(a, type="logNoise")[0]
    custom = {"bump": 0.12, "frequency": 3.5, "grain": 2.0, "octaves": 4, "bulge": 0.2, "bend": 0.08,
              "taper": 0.3}
    plug = {"bump": "bumpAmount", "frequency": "bumpFrequency", "grain": "grainStretch", "octaves": "octaves",
            "bulge": "bulge", "bend": "bend", "taper": "taper"}
    for k, v in custom.items():
        cmds.setAttr("%s.%s" % (node, plug[k]), v)
    cmds.setAttr(node + ".seed", 42)
    tb["add_log_noise"]([b], custom, seeds={b: 42})
    d = maxdiff(pts(a), pts(b))
    check("same shapes with every setting changed", d < 1e-5, "worst %.2g" % d)
    cmds.file(new=True, force=True)
    cmds.unloadPlugin("logNoise")

    # --- apply: history and history-free meshes, one Ctrl+Z
    for hist in (True, False):
        x = log("log_%s" % hist, history=hist)
        rest = pts(x)
        rep = tb["add_log_noise"]([x])
        moved = maxdiff(rest, pts(x))
        check("apply shapes the log (history=%s)" % hist, rep["added"] == [x] and moved > 0.003,
              "moved up to %.4f" % moved)
        cmds.undo()
        check("one Ctrl+Z undoes apply (history=%s)" % hist,
              maxdiff(rest, pts(x)) < 1e-6 and not tb["has_log_noise"](x))
    cmds.file(new=True, force=True)

    # --- live edits, seeds, skip, low-vertex warning
    x, y = log("logX"), log("logY")
    rest = pts(x)
    tb["add_log_noise"]([x, y], seeds={x: 10, y: 11})
    again = tb["add_log_noise"]([x])
    check("applying twice skips logs that already have noise", again["skipped"] == [x])
    before = pts(x)
    tb["update_log_noise"]({x: {"bend": 0.12}, y: {"bend": 0.12}}, live=True)
    check("live edit re-shapes and remembers the setting", maxdiff(before, pts(x)) > 1e-3 and
          tb["log_settings"](x)["bend"] == 0.12 and tb["log_settings"](x)["seed"] == 10)
    fresh = log("logZ")
    tb["add_log_noise"]([fresh], {"bend": 0.12}, seeds={fresh: 10})
    check("live edit gives the same shape as applying with that setting", maxdiff(pts(fresh), pts(x)) < 1e-5)
    small = cmds.ls(cmds.polyCylinder(sx=8, sy=1)[0], long=True)[0]
    check("warns about logs with too few vertices", tb["add_log_noise"]([small])["low"] == [small])

    # --- scale independence
    big = log("logBig", scale=10.0)
    tb["add_log_noise"]([big], seeds={big: 10})
    ratio = maxdiff(pts(big), [(p[0] * 10, p[1] * 10, p[2] * 10) for p in tb["log_noise_points"](
        rest, dict(tb["LOG_DEFAULTS"], seed=10))])
    check("scale-independent: a 10x log gets the same shape, 10x bigger", ratio < 1e-4, "off by %.2g" % ratio)

    # --- vertex selection limits it
    m = log("logMask")
    rest_m = pts(m)
    cmds.select(["%s.vtx[0:239]" % m])  # bottom rows
    logs, weights = tb["log_selection"]()
    tb["add_log_noise"](logs, weights=weights)
    after = pts(m)
    untouched = all(abs(after[i][k] - rest_m[i][k]) < 1e-9 for i in range(240, len(rest_m)) for k in range(3))
    check("a vertex selection limits the noise to those vertices", logs == [m] and untouched and
          maxdiff(rest_m[:240], after[:240]) > 1e-3)
    cmds.select(clear=True)

    # --- reset and bake
    done, _ = tb["reset_log_noise"]([y])
    check("reset puts the cylinder back and forgets the noise", done == [y] and not tb["has_log_noise"](y))
    cmds.undo()
    check("reset is one Ctrl+Z", tb["has_log_noise"](y))
    shaped = pts(x)
    tb["bake_log_noise"]([x])
    check("bake keeps the shape and drops the stored data", maxdiff(shaped, pts(x)) < 1e-9 and
          not tb["has_log_noise"](x) and not cmds.attributeQuery(tb["LOG_REST"], node=tb["_log_shape"](x),
                                                                exists=True))
    check("finds logs with noise", set(tb["logs_with_noise"]()) >= {y, fresh, big, m} and
          x not in tb["logs_with_noise"]())

    # --- topology change: left alone and reported
    cmds.polySmooth(y, divisions=1)
    stale = tb["update_log_noise"]({y: {"bend": 0.0}}, live=False)
    check("changed topology is reported, not mangled", stale == [y])

    # --- save, reopen, keep tweaking (no plugin needed)
    scene = os.path.join(tempfile.mkdtemp(prefix="lognoise"), "logs.ma")
    cmds.file(rename=scene)
    cmds.file(save=True, type="mayaAscii")
    shaped = pts(fresh)
    cmds.file(new=True, force=True)
    cmds.file(scene, open=True, force=True)
    z = cmds.ls("logZ", long=True)[0]
    reopened = pts(z)
    plugins = cmds.ls(type="unknown") or []
    tb["update_log_noise"]({z: {"bend": 0.0}}, live=True)
    check("saved scenes keep the shape and settings, and need no plugin",
          maxdiff(shaped, reopened) < 1e-5 and not plugins and tb["log_settings"](z)["seed"] == 10 and
          maxdiff(reopened, pts(z)) > 1e-4)

    # --- speed
    cmds.file(new=True, force=True)
    heavy = log("heavy", sx=36, sy=107)
    n = cmds.polyEvaluate(heavy, vertex=True)
    t0 = time.time()
    tb["add_log_noise"]([heavy])
    t_add = time.time() - t0
    t0 = time.time()
    tb["update_log_noise"]({heavy: {"bump": 0.08}}, live=True)
    t_edit = time.time() - t0
    check("fast enough for live sliders", t_edit < 0.5, "%d verts: apply %.2fs, edit %.2fs" % (n, t_add, t_edit))


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
