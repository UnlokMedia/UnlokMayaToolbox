"""Close-up pictures of palm leaflet shape (Crinkle, Twist, Width variation,
Uneven edges, Bent tips, Cross-section): each palm preset with the controls off, at the
preset's values and strong, from an eave corner and from above the ridge.

Launch (GUI Maya), with UNLOK_TEST_DIR set to this folder:

    maya.exe -script tests/run_gui_leaf_shape_pics.mel

UNLOK_PIC_SET=sections: the palapa preset with each cross-section instead.

Pictures go to $UNLOK_TEST_OUT (default: tests/_out/leaf_shape_pics).
"""

import os
import traceback

import maya.cmds as cmds

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ["UNLOK_TEST_DIR"]
TOOLBOX = os.environ.get("UNLOK_TOOLBOX") or os.path.join(os.path.dirname(HERE), "UnlokToolbox.py")
OUT = os.environ.get("UNLOK_TEST_OUT") or os.path.join(HERE, "_out", "leaf_shape_pics")

STRONG = dict(crinkle=1.0, leaf_twist=1.0, width_var=0.8, width_wobble=0.8, bent_tips=0.5)


def snap(name, eye, aim, width=1400, height=900):
    cmds.setAttr("persp.translate", *eye)
    cmds.viewLookAt("persp", position=aim)
    cmds.setAttr("perspShape.focalLength", 45.0)
    cmds.refresh(force=True)
    cmds.playblast(frame=[cmds.currentTime(q=True)], format="image", compression="png",
                   completeFilename=os.path.join(OUT, name), viewer=False, showOrnaments=False, percent=100,
                   widthHeight=(width, height), offScreen=True)


def sections(ns):
    """The palapa preset with each leaflet cross-section (As is, Rolled, Creased, Mixed), close up."""
    for form in ns["THATCH_LEAF_SECTIONS"]:
        cmds.file(new=True, force=True)
        house = cmds.polyCube(w=6, h=3, d=4, ch=False, name="house")[0]
        cmds.move(0, 1.5, 0, house)
        box = cmds.polyCube(w=6, h=2, d=4, ch=False, name="roofBox")[0]
        cmds.move(0, 4, 0, box)
        s = dict(ns["thatch_preset"]("Palm: palapa (hipped, messy top)"), detail="High", frame=True,
                 leaf_section=form, section_amount=1.0, section_var=0.3)
        ns["make_thatch_roof"](box, s)
        cmds.setAttr(box + ".visibility", 0)
        cmds.select(clear=True)
        tag = form.replace(" ", "_")
        snap("section_%s_close.png" % tag, (1.2, 5.2, 2.2), (0.7, 4.45, 1.0))
        snap("section_%s_eave.png" % tag, (3.2, 3.0, 2.9), (2.3, 3.0, 1.75))
        print("pictures: section %s" % form)


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    ns = {"__name__": "unlok_pics", "__file__": TOOLBOX}
    exec(compile(open(TOOLBOX).read(), TOOLBOX, "exec"), ns)
    keys = ns["THATCH_LEAF_SHAPE_KEYS"]
    for panel in cmds.getPanel(type="modelPanel") or []:
        cmds.modelEditor(panel, edit=True, displayAppearance="smoothShaded", wireframeOnShaded=False,
                         grid=False, displayLights="default")
    if os.environ.get("UNLOK_PIC_SET") == "sections":
        sections(ns)
        return
    for name in [k for k in ns["THATCH_PRESETS"] if k.startswith("Palm")]:
        tag = name.split(":")[1].split("(")[0].strip().replace(" ", "_")
        for look, over in (("off", dict((k, ns["THATCH_DEFAULTS"][k]) for k in keys)), ("preset", {}),
                           ("strong", STRONG)):
            cmds.file(new=True, force=True)
            house = cmds.polyCube(w=6, h=3, d=4, ch=False, name="house")[0]
            cmds.move(0, 1.5, 0, house)
            box = cmds.polyCube(w=6, h=2, d=4, ch=False, name="roofBox")[0]
            cmds.move(0, 4, 0, box)
            s = dict(ns["thatch_preset"](name), detail="High", frame=True)
            s.update(over)
            ns["make_thatch_roof"](box, s)
            cmds.setAttr(box + ".visibility", 0)
            cmds.select(clear=True)
            snap("%s_%s_eave.png" % (tag, look), (4.6, 3.3, 3.9), (2.4, 3.2, 1.7))
            snap("%s_%s_top.png" % (tag, look), (1.5, 6.6, 3.2), (0.6, 4.4, 0.6))
            print("pictures: %s %s" % (name, look))


try:
    main()
except Exception:
    traceback.print_exc()
cmds.quit(force=True)
