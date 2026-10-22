# Log Noise - subtle "natural log" deformer for Maya 2023+
#
# Paste this whole script into the Script Editor (Python tab) and run it.
# It saves logNoise.py into your Maya plug-ins folder, loads it, and opens a
# small "Log Noise" window. Select your cylinders, click "Apply to Selected",
# then tweak the settings in the Channel Box (select several logNoise nodes
# to edit them all at once).
#
# Cylinders need some height and axis subdivisions for the noise to show,
# e.g. polyCylinder -sx 24 -sy 20.

import os
import random

import maya.cmds as cmds

PLUGIN_NAME = "logNoise"

PLUGIN_SRC = r'''
"""logNoise deformer. Written by the Log Noise script."""
import math

import maya.OpenMaya as om
import maya.OpenMayaMPx as ompx


# Gains that roughly map each control to "fraction of radius/length".
BUMP_GAIN = 2.0
BULGE_GAIN = 2.0
BEND_GAIN = 3.0
BULGE_FREQ = 0.35  # bulges per radius of length
BEND_FREQ = 1.0  # bends across the whole length


def _lcg(state):
    return (state * 1664525 + 1013904223) & 0xFFFFFFFF


def _make_perm():
    perm = list(range(256))
    s = 12345
    for i in range(255, 0, -1):
        s = _lcg(s)
        j = s % (i + 1)
        perm[i], perm[j] = perm[j], perm[i]
    return perm + perm


_P = _make_perm()


def _offsets(seed, salt, count):
    s = (seed * 2654435761 + salt * 40503 + 7) & 0xFFFFFFFF
    for _ in range(4):
        s = _lcg(s)
    out = []
    for _ in range(count):
        s = _lcg(s)
        out.append(s / 4294967296.0 * 256.0)
    return out


def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _grad(h, x, y, z):
    h &= 15
    u = x if h < 8 else y
    v = y if h < 4 else (x if h == 12 or h == 14 else z)
    return (u if h & 1 == 0 else -u) + (v if h & 2 == 0 else -v)


def noise3(x, y, z):
    """Improved Perlin noise, roughly -1..1."""
    fx, fy, fz = math.floor(x), math.floor(y), math.floor(z)
    X, Y, Z = int(fx) & 255, int(fy) & 255, int(fz) & 255
    x -= fx
    y -= fy
    z -= fz
    u, v, w = _fade(x), _fade(y), _fade(z)
    P = _P
    A = P[X] + Y
    AA = P[A] + Z
    AB = P[A + 1] + Z
    B = P[X + 1] + Y
    BA = P[B] + Z
    BB = P[B + 1] + Z

    g0 = _grad(P[AA], x, y, z)
    g1 = _grad(P[BA], x - 1, y, z)
    g2 = _grad(P[AB], x, y - 1, z)
    g3 = _grad(P[BB], x - 1, y - 1, z)
    g4 = _grad(P[AA + 1], x, y, z - 1)
    g5 = _grad(P[BA + 1], x - 1, y, z - 1)
    g6 = _grad(P[AB + 1], x, y - 1, z - 1)
    g7 = _grad(P[BB + 1], x - 1, y - 1, z - 1)

    x0 = g0 + u * (g1 - g0)
    x1 = g2 + u * (g3 - g2)
    x2 = g4 + u * (g5 - g4)
    x3 = g6 + u * (g7 - g6)
    y0 = x0 + v * (x1 - x0)
    y1 = x2 + v * (x3 - x2)
    return y0 + w * (y1 - y0)


def fbm(x, y, z, octaves):
    total, amp, norm = 0.0, 1.0, 0.0
    for _ in range(octaves):
        total += amp * noise3(x, y, z)
        norm += amp
        x *= 2.0
        y *= 2.0
        z *= 2.0
        amp *= 0.5
    return total / norm


class LogNoise(ompx.MPxDeformerNode):
    TYPE_NAME = "logNoise"
    TYPE_ID = om.MTypeId(0x0007F1A0)  # local/in-house ID range

    seed = None
    bumpAmount = None
    bumpFrequency = None
    grainStretch = None
    octaves = None
    bulge = None
    bend = None
    taper = None
    axis = None

    def __init__(self):
        ompx.MPxDeformerNode.__init__(self)

    @staticmethod
    def creator():
        return ompx.asMPxPtr(LogNoise())

    @classmethod
    def initialize(cls):
        out_geom = ompx.cvar.MPxGeometryFilter_outputGeom
        num = om.MFnNumericAttribute()

        def add(name, short, kind, default, minimum=None, maximum=None, soft_max=None):
            attr = num.create(name, short, kind, default)
            num.setKeyable(True)
            if minimum is not None:
                num.setMin(minimum)
            if maximum is not None:
                num.setMax(maximum)
            if soft_max is not None:
                num.setSoftMax(soft_max)
            cls.addAttribute(attr)
            cls.attributeAffects(attr, out_geom)
            return attr

        kInt = om.MFnNumericData.kInt
        kFloat = om.MFnNumericData.kFloat
        cls.seed = add("seed", "sd", kInt, 0, minimum=0, soft_max=9999)
        cls.bumpAmount = add("bumpAmount", "ba", kFloat, 0.04, minimum=0.0, soft_max=0.3)
        cls.bumpFrequency = add("bumpFrequency", "bf", kFloat, 2.0, minimum=0.01, soft_max=10.0)
        cls.grainStretch = add("grainStretch", "gs", kFloat, 4.0, minimum=1.0, soft_max=10.0)
        cls.octaves = add("octaves", "oct", kInt, 3, minimum=1, maximum=6)
        cls.bulge = add("bulge", "bul", kFloat, 0.06, minimum=0.0, soft_max=0.5)
        cls.bend = add("bend", "bnd", kFloat, 0.02, minimum=0.0, soft_max=0.15)
        cls.taper = add("taper", "tp", kFloat, 0.1, minimum=0.0, maximum=0.9)

        enum = om.MFnEnumAttribute()
        cls.axis = enum.create("axis", "ax", 0)
        for i, label in enumerate(("Auto", "X", "Y", "Z")):
            enum.addField(label, i)
        enum.setKeyable(True)
        cls.addAttribute(cls.axis)
        cls.attributeAffects(cls.axis, out_geom)

    def deform(self, block, geo_iter, matrix, multi_index):
        envelope = block.inputValue(ompx.cvar.MPxGeometryFilter_envelope).asFloat()
        if envelope <= 0.0:
            return

        cls = LogNoise
        seed = block.inputValue(cls.seed).asInt()
        bump = block.inputValue(cls.bumpAmount).asFloat() * BUMP_GAIN
        freq = block.inputValue(cls.bumpFrequency).asFloat()
        stretch = block.inputValue(cls.grainStretch).asFloat()
        octaves = block.inputValue(cls.octaves).asInt()
        bulge = block.inputValue(cls.bulge).asFloat() * BULGE_GAIN
        bend = block.inputValue(cls.bend).asFloat() * BEND_GAIN
        taper = block.inputValue(cls.taper).asFloat()
        axis_mode = block.inputValue(cls.axis).asShort()

        points = om.MPointArray()
        geo_iter.allPositions(points)
        count = points.length()
        if count == 0:
            return
        indices = []
        geo_iter.reset()
        while not geo_iter.isDone():
            indices.append(geo_iter.index())
            geo_iter.next()

        coords = []
        for i in range(count):
            p = points[i]
            coords.append((p.x, p.y, p.z))
        lo = [min(c[k] for c in coords) for k in range(3)]
        hi = [max(c[k] for c in coords) for k in range(3)]
        ext = [hi[k] - lo[k] for k in range(3)]

        # The log runs along the longest bounding box side unless told otherwise.
        a = ext.index(max(ext)) if axis_mode == 0 else axis_mode - 1
        b, c = (a + 1) % 3, (a + 2) % 3
        length = ext[a]
        radius = 0.25 * (ext[b] + ext[c])
        if length < 1e-6 or radius < 1e-6:
            return
        inv_r = 1.0 / radius
        base = lo[a]
        center_b = 0.5 * (lo[b] + hi[b])
        center_c = 0.5 * (lo[c] + hi[c])

        o = _offsets(seed, multi_index, 9)
        bend_scale = bend * length
        # Bend relative to the straight line between the ends, so the ends stay put.
        end0_b, end1_b = noise3(o[0], o[1], 0.37), noise3(BEND_FREQ + o[0], o[1], 0.37)
        end0_c, end1_c = noise3(o[2], o[3], 0.37), noise3(BEND_FREQ + o[2], o[3], 0.37)

        rows = {}
        for i, p in enumerate(coords):
            w = envelope * self.weightValue(block, multi_index, indices[i])
            if w == 0.0:
                continue

            h = p[a] - base
            key = round(h / length, 6)
            row = rows.get(key)
            if row is None:
                t = h / length
                off_b = noise3(t * BEND_FREQ + o[0], o[1], 0.37) - (end0_b + (end1_b - end0_b) * t)
                off_c = noise3(t * BEND_FREQ + o[2], o[3], 0.37) - (end0_c + (end1_c - end0_c) * t)
                scale = (1.0 - taper * t) * (1.0 + bulge * fbm(h * inv_r * BULGE_FREQ + o[4], o[5], 0.71, 2))
                row = rows[key] = (off_b * bend_scale, off_c * bend_scale, scale)
            off_b, off_c, scale = row

            db = p[b] - center_b
            dc = p[c] - center_c
            n = fbm(db * inv_r * freq + o[6], dc * inv_r * freq + o[7], h * inv_r * freq / stretch + o[8], octaves)
            k = scale * (1.0 + bump * n)

            q = list(p)
            q[b] += w * (center_b + db * k + off_b - p[b])
            q[c] += w * (center_c + dc * k + off_c - p[c])
            points.set(om.MPoint(q[0], q[1], q[2]), i)

        geo_iter.reset()
        geo_iter.setAllPositions(points)


def initializePlugin(mobject):
    plugin = ompx.MFnPlugin(mobject, "logNoise", "1.0", "Any")
    plugin.registerNode(LogNoise.TYPE_NAME, LogNoise.TYPE_ID, LogNoise.creator,
                        LogNoise.initialize, ompx.MPxNode.kDeformerNode)
    om.MGlobal.executeCommand("makePaintable -attrType multiFloat -sm deformer logNoise weights;")


def uninitializePlugin(mobject):
    plugin = ompx.MFnPlugin(mobject)
    try:
        om.MGlobal.executeCommand("makePaintable -remove logNoise weights;")
    except RuntimeError:
        pass
    plugin.deregisterNode(LogNoise.TYPE_ID)
'''


def ensure_plugin():
    if cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
        return
    folder = os.path.join(cmds.internalVar(userAppDir=True), cmds.about(version=True), "plug-ins")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    path = os.path.join(folder, PLUGIN_NAME + ".py")
    with open(path, "w") as f:
        f.write(PLUGIN_SRC)
    cmds.loadPlugin(path)
    print("Log Noise: loaded plug-in from " + path)


def _selected_logs():
    logs = []
    for node in cmds.ls(selection=True, objectsOnly=True, long=True) or []:
        if cmds.nodeType(node) == "mesh":
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        if node not in logs and cmds.listRelatives(node, shapes=True, type="mesh", noIntermediate=True):
            logs.append(node)
    return logs


def _noise_nodes(objs):
    return cmds.ls(cmds.listHistory(objs) or [], type=PLUGIN_NAME) if objs else []


def apply_to_selection(*_):
    logs = _selected_logs()
    if not logs:
        cmds.warning("Log Noise: select some mesh logs first.")
        return []
    created = []
    for obj in logs:
        short = obj.split("|")[-1]
        if _noise_nodes([obj]):
            print("Log Noise: %s already has one, skipping." % short)
            continue
        verts = cmds.polyEvaluate(obj, vertex=True)
        if verts < 200:
            cmds.warning("Log Noise: %s only has %d verts, add height/axis subdivisions for the noise to show." % (short, verts))
        node = cmds.deformer(obj, type=PLUGIN_NAME, name=short + "_logNoise")[0]
        cmds.setAttr(node + ".seed", random.randint(0, 9999))
        created.append(node)
    if created:
        cmds.select(created)
        print("Log Noise: added %d deformer(s). They're selected, so the Channel Box edits them together." % len(created))
    return created


def randomize_seeds(*_):
    nodes = cmds.ls(selection=True, type=PLUGIN_NAME) + _noise_nodes(_selected_logs())
    for node in set(nodes or cmds.ls(type=PLUGIN_NAME)):
        cmds.setAttr(node + ".seed", random.randint(0, 9999))


def select_noise_nodes(*_):
    nodes = _noise_nodes(_selected_logs()) or cmds.ls(type=PLUGIN_NAME)
    if nodes:
        cmds.select(nodes)


def bake_selected(*_):
    logs = _selected_logs()
    if not logs:
        cmds.warning("Log Noise: select the logs to bake.")
        return
    cmds.delete(logs, constructionHistory=True)
    print("Log Noise: baked %d log(s)." % len(logs))


def show_window():
    win = "logNoiseWin"
    if cmds.window(win, exists=True):
        cmds.deleteUI(win)
    cmds.window(win, title="Log Noise", sizeable=False)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=4, columnAttach=("both", 8))
    cmds.separator(style="none", height=4)
    cmds.button(label="Apply to Selected", height=30, command=apply_to_selection)
    cmds.button(label="Randomize Seeds", command=randomize_seeds)
    cmds.button(label="Select Noise Nodes", command=select_noise_nodes)
    cmds.button(label="Bake Selected (delete history)", command=bake_selected)
    cmds.text(label="Tweak settings in the Channel Box.\nRandomize/Select work on the selection,\nor every log if nothing is selected.", align="left")
    cmds.separator(style="none", height=4)
    cmds.showWindow(win)


ensure_plugin()
if not cmds.about(batch=True):
    show_window()
