"""Moss Outline detail / Breakup pictures (mayapy builds the scenes, Arnold renders them).

    mayapy tests/render_moss_breakup.py [variant ...]
    then for each scene: Render.exe -r arnold -cam camTop|camView ... (tests/render_moss_breakup.sh)

A flat roof (5 x 3.5 m) against a brick wall, moss gathering along the wall's foot
(Where it gathers: Walls) and falling off across the roof: the falloff is where
Breakup turns the carpet into cushions. Scenes and a timing log go to
tests/_out/moss_breakup.
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLBOX = os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.path.join(HERE, "_out", "moss_breakup")

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

BASE = {"style": "Mat", "coverage": 0.6, "render_as": "GED", "lumps": 0.5, "to_walls": 0.8,
        "to_walls_reach": 1.6, "detail": "Normal", "strands": 0.0, "capsules": 0.0, "seed": 3}
VARIANTS = {
    "before": {},
    "detail": {"edge_detail": 1.0, "ragged": 0.9},
    "breakup": {"edge_detail": 0.6, "ragged": 0.8, "breakup": 0.85, "breakup_width": 0.6, "breakup_size": 0.08,
                "breakup_var": 0.7, "breakup_scale": 0.5, "thickness": 0.03, "bumps": 0.7},
    "carpet": {"coverage": 0.92, "to_walls": 0.3, "thickness": 0.04, "patchiness": 0.3, "edge_detail": 0.5,
               "breakup": 0.5, "breakup_width": 0.3, "breakup_size": 0.08, "bumps": 0.6, "growths": 0.2},
}


def load_toolbox(path=TOOLBOX):
    ns = {"__name__": "unlok_test", "__file__": path}
    with open(path) as f:
        exec(compile(f.read(), path, "exec"), ns)
    return ns


def shader(name, rgb, rough=0.6):
    s = cmds.shadingNode("aiStandardSurface", asShader=True, name=name)
    cmds.setAttr(s + ".baseColor", *rgb, type="double3")
    cmds.setAttr(s + ".specularRoughness", rough)
    cmds.setAttr(s + ".specular", 0.2)
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name + "SG")
    cmds.connectAttr(s + ".outColor", sg + ".surfaceShader")
    return sg


def roof():
    """The roof (decimetres) and the wall along its back edge."""
    r = cmds.polyPlane(w=50, h=35, sx=10, sy=7, ch=False, name="roofFelt_C_test0001_GEP")[0]
    w = cmds.polyCube(w=54, h=20, d=3, ch=False, name="wallBrick_C_test0001_GEP")[0]
    cmds.move(0, 10, -19, w)
    cmds.makeIdentity(w, apply=True)
    cmds.sets(r, edit=True, forceElement=shader("roofFelt", (0.32, 0.32, 0.31), 0.8))
    cmds.sets(w, edit=True, forceElement=shader("wallBrick", (0.42, 0.17, 0.11), 0.75))
    return [cmds.ls(x, long=True)[0] for x in (r, w)]


def cameras():
    top = cmds.camera(name="camTop", focalLength=35)[0]
    cmds.move(0, 75, 2, top)
    cmds.rotate(-90, 0, 0, top)
    view = cmds.camera(name="camView", focalLength=28)[0]
    cmds.move(14, 9, 20, view)
    cmds.viewPlace(view, lookAt=(-2, 0, -10))
    sky = cmds.shadingNode("aiSkyDomeLight", asLight=True, name="sky")
    cmds.setAttr(sky + ".intensity", 0.8)
    cmds.setAttr(sky + ".color", 0.85, 0.9, 1.0, type="double3")
    sun = cmds.directionalLight(name="sun", intensity=2.2, rgb=(1.0, 0.95, 0.85))
    t = cmds.listRelatives(sun, parent=True)[0]
    cmds.rotate(-50, 35, 0, t)
    cmds.setAttr(sun + ".aiAngle", 2.0)
    import mtoa.core
    mtoa.core.createOptions()
    cmds.setAttr("defaultRenderGlobals.currentRenderer", "arnold", type="string")
    opts = "defaultArnoldRenderOptions"
    cmds.setAttr(opts + ".AASamples", 4)
    cmds.setAttr(opts + ".GIDiffuseDepth", 1)


def main():
    os.makedirs(OUT, exist_ok=True)
    cmds.loadPlugin("mtoa", quiet=True)
    tb = load_toolbox()
    names = sys.argv[1:] or list(VARIANTS)
    log = {}
    for name in names:
        cmds.file(new=True, force=True)
        cmds.currentUnit(linear="cm")
        nodes = roof()
        cameras()
        cmds.select(clear=True)
        s = dict(BASE, **VARIANTS[name])
        t0 = time.time()
        res = tb["create_scatter_group"](nodes, "Moss", s)
        dt = time.time() - t0
        root = res["root"]
        tb["sc_moss_look"]([root])
        parts = tb["sc_parts"](root)
        bed = [v for k, v in parts.items() if k.endswith("/moss")][0]
        faces = cmds.polyEvaluate(bed, face=True)
        # a second, warm build of the same layer (what a slider edit costs): Outline detail / Breakup tweaks
        lid = tb["sc_data"](root)["layers"][0]["id"]
        t1 = time.time()
        tb["sc_update"](root, lid, {"breakup_width": float(s.get("breakup_width", 0.5)) + 0.01})
        dt2 = time.time() - t1
        log[name] = {"build_s": round(dt, 2), "edit_s": round(dt2, 2), "faces": faces}
        print("VARIANT %s: build %.2f s, edit %.2f s, %d faces" % (name, dt, dt2, faces))
        sys.stdout.flush()
        cmds.file(rename=os.path.join(OUT, "moss_%s.ma" % name))
        cmds.file(save=True, type="mayaAscii", force=True)
    path = os.path.join(OUT, "timings.json")
    old = {}
    if os.path.isfile(path):
        with open(path) as f:
            old = json.load(f)
    old.update(log)
    with open(path, "w") as f:
        json.dump(old, f, indent=1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        maya.standalone.uninitialize()
        os._exit(0)
