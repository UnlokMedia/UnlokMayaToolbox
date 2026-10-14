"""
Unlok Maya Toolbox
==================

Paste this whole file into the Maya Script Editor (Python tab) and run it.
It is fully self-contained: no other files, folders or third-party packages.

Target: Maya 2023 (Python 3.9, PySide2). Also runs on 2024/2025.

Tools
-----
Modeling
    Path Scatter  - draw a path on any surface and scatter / array objects
                    along it (presets or your own meshes), with rows, stagger,
                    randomness and bake to instances, copies or one mesh.
UV
    Smart UDIM    - sort an asset into UDIM sections and material groups
                    (plain Maya sets, UnlokRenamer naming), clean geometry
                    and report UV problems before layout.
"""

import functools
import json
import math
import random
import re
import time
import traceback

import maya.cmds as cmds
import maya.mel as mel
import maya.api.OpenMaya as om
import maya.api.OpenMayaUI as omui
import maya.OpenMaya as om1
import maya.OpenMayaUI as omui1

try:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance
except ImportError:  # Maya 2025+
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance


TOOLBOX_VERSION = "0.1.0"
WINDOW_OBJECT_NAME = "UnlokToolboxWindow"
REGISTRY_KEY = "_unlok_toolbox_registry"


# =============================================================================
# Generic helpers
# =============================================================================

def _registry():
    """Process-wide state that survives re-pasting the script.

    Holds callback ids / script jobs so a fresh paste can clean up the
    previous run before building a new window.
    """
    import __main__
    reg = getattr(__main__, REGISTRY_KEY, None)
    if not isinstance(reg, dict):
        reg = {"callbacks": [], "jobs": []}
        setattr(__main__, REGISTRY_KEY, reg)
    return reg


class NoUndo(object):
    """Suspend undo recording for tool-managed scene edits.

    Live preview edits happen many times a second; recording them would flood
    the undo queue and make Ctrl+Z step through slider ticks.
    """

    def __enter__(self):
        self._was_on = cmds.undoInfo(q=True, stateWithoutFlush=True)
        if self._was_on:
            cmds.undoInfo(stateWithoutFlush=False)
        return self

    def __exit__(self, *exc):
        if self._was_on:
            cmds.undoInfo(stateWithoutFlush=True)
        return False


class PreserveSelection(object):
    """Restore the user's selection after commands that change it."""

    def __enter__(self):
        self._sel = cmds.ls(selection=True, long=True) or []
        return self

    def __exit__(self, *exc):
        keep = [n for n in self._sel if cmds.objExists(n)]
        if keep:
            cmds.select(keep, replace=True)
        else:
            cmds.select(clear=True)
        return False


def get_mobject(name):
    sel = om.MSelectionList()
    try:
        sel.add(name)
        return sel.getDependNode(0)
    except (RuntimeError, TypeError):
        return None


def get_dag_path(name):
    sel = om.MSelectionList()
    try:
        sel.add(name)
        return sel.getDagPath(0)
    except (RuntimeError, TypeError):
        return None


def long_name(name):
    found = cmds.ls(name, long=True) or []
    return found[0] if found else None


def short_name(name):
    return name.split("|")[-1]


def mat_translate(x, y, z):
    return om.MMatrix([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1])


def mat_scale(x, y, z):
    return om.MMatrix([x, 0, 0, 0, 0, y, 0, 0, 0, 0, z, 0, 0, 0, 0, 1])


def mat_euler_deg(x, y, z):
    return om.MEulerRotation(math.radians(x), math.radians(y), math.radians(z)).asMatrix()


def mat_from_frame(x_axis, y_axis, z_axis, pos):
    return om.MMatrix([
        x_axis.x, x_axis.y, x_axis.z, 0,
        y_axis.x, y_axis.y, y_axis.z, 0,
        z_axis.x, z_axis.y, z_axis.z, 0,
        pos.x, pos.y, pos.z, 1,
    ])


AXES = {"X": (0, 1.0), "-X": (0, -1.0), "Y": (1, 1.0), "-Y": (1, -1.0), "Z": (2, 1.0), "-Z": (2, -1.0)}


def axis_remap_matrix(forward, up):
    """Matrix taking the source's forward axis to +X and up axis to +Y.

    Returns (matrix, ok). ok is False when forward and up share an axis.
    """
    fi, fs = AXES.get(forward, (0, 1.0))
    ui, us = AXES.get(up, (1, 1.0))
    if fi == ui:
        return om.MMatrix(), False
    rows = [[0.0, 0.0, 0.0] for _ in range(3)]
    rows[fi][0] = fs
    rows[ui][1] = us
    k = 3 - fi - ui
    rows[k][2] = 1.0
    det = (rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
           - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
           + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0]))
    if det < 0:
        rows[k][2] = -1.0
    flat = rows[0] + [0] + rows[1] + [0] + rows[2] + [0] + [0, 0, 0, 1]
    return om.MMatrix(flat), True


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


# =============================================================================
# Path Scatter - engine
# =============================================================================

PRESET_TYPES = ("Cube", "Cylinder", "Plane", "Sphere")
SOURCE_TYPES = PRESET_TYPES + ("Mesh",)
DIST_MODES = ("Fit to Size", "Spacing", "Count")
PIVOT_MODES = ("Bottom", "Center", "Source Origin")
UP_MODES = ("Surface Normal", "World Up")
VARIANT_MODES = ("Random", "Cycle")
BAKE_MODES = ("Instances", "Copies", "Combined Mesh")
AXIS_NAMES = ("X", "-X", "Y", "-Y", "Z", "-Z")

PS_DEFAULTS = {
    # source
    "source_type": "Cube",
    "size_x": 1.0, "size_y": 0.1, "size_z": 0.5, "preset_sides": 12,
    "forward_axis": "X", "up_axis": "Y", "pivot": "Bottom",
    # distribution
    "dist_mode": "Fit to Size", "gap": 0.0, "spacing": 1.0, "count": 10,
    "start_offset": 0.0, "end_offset": 0.0,
    # rows / grid
    "rows": 1, "row_spacing": 0.5, "row_stagger": 0.0, "row_lift": 0.0, "rows_centered": False,
    # orientation
    "follow_path": True, "up_mode": "Surface Normal", "snap_surface": True, "surface_offset": 0.0,
    "rot_x": 0.0, "rot_y": 0.0, "rot_z": 0.0,
    # scale
    "scale": 1.0, "scale_x": 1.0, "scale_y": 1.0, "scale_z": 1.0,
    # randomness
    "seed": 1, "rand_scale_min": 1.0, "rand_scale_max": 1.0, "rand_scale_axis": 0.0,
    "rand_rot_x": 0.0, "rand_rot_y": 0.0, "rand_rot_z": 0.0,
    "rand_along": 0.0, "rand_side": 0.0, "rand_up": 0.0,
    "skip_chance": 0.0, "variant_mode": "Random",
    # drawing / output
    "smoothing": 3, "bake_mode": "Instances", "keep_system": False,
    "max_items": 20000, "preview_boxes": False,
}

# One-click starting points. Each resets to defaults, then applies these.
RECIPES = {
    "Neat Array": {
        "source_type": "Cube", "size_x": 0.5, "size_y": 0.5, "size_z": 0.5, "gap": 0.1,
    },
    "Roof Shingles": {
        "source_type": "Cube", "size_x": 0.6, "size_y": 0.04, "size_z": 0.45, "gap": 0.02,
        "rows": 10, "row_spacing": -0.35, "row_stagger": 0.5, "row_lift": 0.012, "rot_x": 3.0,
        "rand_rot_x": 1.5, "rand_rot_y": 2.0, "rand_scale_axis": 0.05, "rand_along": 0.01,
    },
    "Messy Thatch": {
        # Width is the strand length, so strands run across the path (down the slope).
        "source_type": "Cube", "size_x": 0.025, "size_y": 0.025, "size_z": 1.2, "pivot": "Center",
        "dist_mode": "Spacing", "spacing": 0.03, "rows": 12, "row_spacing": -0.3, "row_stagger": 0.5,
        "row_lift": 0.02, "surface_offset": 0.02, "rot_x": 6.0,
        "rand_rot_x": 6.0, "rand_rot_y": 14.0, "rand_rot_z": 4.0, "rand_scale_min": 0.75, "rand_scale_max": 1.15,
        "rand_scale_axis": 0.35, "rand_along": 0.03, "rand_side": 0.18, "rand_up": 0.015, "skip_chance": 12.0,
        "max_items": 60000,
    },
    "Rocks / Debris": {
        "source_type": "Sphere", "size_x": 0.4, "size_y": 0.3, "size_z": 0.35, "preset_sides": 8,
        "pivot": "Center", "dist_mode": "Spacing", "spacing": 0.35, "up_mode": "World Up", "surface_offset": -0.05,
        "rand_scale_min": 0.4, "rand_scale_max": 1.5, "rand_scale_axis": 0.3,
        "rand_rot_x": 180.0, "rand_rot_y": 180.0, "rand_rot_z": 180.0,
        "rand_along": 0.15, "rand_side": 0.5, "skip_chance": 15.0, "_keep_mesh": True,
    },
    "Fence Posts": {
        "source_type": "Cylinder", "size_x": 0.12, "size_y": 1.2, "size_z": 0.12, "preset_sides": 10,
        "dist_mode": "Spacing", "spacing": 1.5, "up_mode": "World Up",
        "rand_rot_x": 2.0, "rand_rot_z": 2.0, "rand_scale_axis": 0.05,
    },
}
RECIPE_KEEP = ("seed", "smoothing", "bake_mode", "keep_system", "preview_boxes")

WORLD_UP = om.MVector(0, 1, 0)
WORLD_X = om.MVector(1, 0, 0)
WORLD_Z = om.MVector(0, 0, 1)


class PathScatterSystem(object):
    """A live scatter setup in the scene.

    Scene layout (everything hangs off one root so it is easy to find,
    select and delete)::

        pathScatter1                 root, stores settings + links
          pathScatter1_paths         curves drawn with the tool
          pathScatter1_sources       hidden; one proxy per source variant
          pathScatter1_instancer     instancer node fed with static arrays

    The preview is a single ``instancer`` node whose inputPoints are set
    directly from Python (no MASH network, no per-item nodes), so updates
    cost milliseconds even for tens of thousands of items. Real geometry is
    only created on bake.
    """

    TAG = "unlokPathScatter"

    def __init__(self, uuid):
        self.uuid = uuid
        self.last_count = 0
        self._cache = {}
        self._preset_state = None
        self._pushed = None
        self._pushed_boxes = None

    # ------------------------------------------------------------------ lookup
    @classmethod
    def create(cls, settings):
        with NoUndo(), PreserveSelection():
            root = long_name(cmds.group(empty=True, world=True, name="pathScatter1"))
            short = short_name(root)
            cmds.addAttr(root, longName=cls.TAG, attributeType="bool", defaultValue=True)
            cmds.addAttr(root, longName="unlokSettings", dataType="string")
            cmds.addAttr(root, longName="unlokProxySig", dataType="string")
            for ln in ("unlokPaths", "unlokSurfaces", "unlokSources"):
                cmds.addAttr(root, longName=ln, attributeType="message", multi=True, indexMatters=False)
            for ln in ("unlokPathGrp", "unlokSourceGrp", "unlokInstancer"):
                cmds.addAttr(root, longName=ln, attributeType="message")

            paths = cmds.group(empty=True, name=short + "_paths", parent=root)
            sources = cmds.group(empty=True, name=short + "_sources", parent=root)
            cmds.setAttr(sources + ".visibility", 0)
            inst = cmds.createNode("instancer", name=short + "_instancer", parent=root, skipSelect=True)
            cmds.setAttr(inst + ".rotationAngleUnits", 0)  # degrees
            cmds.setAttr(inst + ".rotationOrder", 0)  # XYZ
            cmds.connectAttr(paths + ".message", root + ".unlokPathGrp")
            cmds.connectAttr(sources + ".message", root + ".unlokSourceGrp")
            cmds.connectAttr(inst + ".message", root + ".unlokInstancer")
            # The instancer lives under the root, so keep the root at identity.
            for attr in ("t", "r", "s"):
                for ax in "xyz":
                    cmds.setAttr(root + "." + attr + ax, lock=True)
            uuid = cmds.ls(root, uuid=True)[0]
        system = cls(uuid)
        system.set_settings(settings)
        return system

    @classmethod
    def from_node(cls, node):
        """Return the system that owns ``node`` (any descendant), or None."""
        if not node:
            return None
        node = node.split(".")[0]
        path = long_name(node)
        if not path:
            return None
        parts = path.split("|")
        for i in range(len(parts), 1, -1):
            cand = "|".join(parts[:i])
            if cand and cmds.attributeQuery(cls.TAG, node=cand, exists=True):
                return cls(cmds.ls(cand, uuid=True)[0])
        return None

    @classmethod
    def all_roots(cls):
        return cmds.ls("*." + cls.TAG, objectsOnly=True, long=True, recursive=True) or []

    def root(self):
        found = cmds.ls(self.uuid, long=True) or []
        return found[0] if found else None

    def exists(self):
        return self.root() is not None

    def name(self):
        root = self.root()
        return short_name(root) if root else ""

    def _msg_one(self, attr):
        root = self.root()
        if not root:
            return None
        conns = cmds.listConnections(root + "." + attr, source=True, destination=False) or []
        return long_name(conns[0]) if conns else None

    def _msg_list(self, attr):
        root = self.root()
        if not root:
            return []
        out = []
        for idx in cmds.getAttr(root + "." + attr, multiIndices=True) or []:
            conns = cmds.listConnections("%s.%s[%d]" % (root, attr, idx), source=True, destination=False) or []
            for c in conns:
                ln = long_name(c)
                if ln and ln not in out:
                    out.append(ln)
        return out

    def _msg_set(self, attr, nodes, add=False):
        root = self.root()
        if not root:
            return
        with NoUndo():
            existing = self._msg_list(attr)
            if not add:
                for idx in cmds.getAttr(root + "." + attr, multiIndices=True) or []:
                    cmds.removeMultiInstance("%s.%s[%d]" % (root, attr, idx), b=True)
                existing = []
            for node in nodes:
                ln = long_name(node)
                if ln and ln not in existing:
                    cmds.connectAttr(ln + ".message", root + "." + attr, nextAvailable=True)
                    existing.append(ln)

    def path_group(self):
        return self._msg_one("unlokPathGrp")

    def source_group(self):
        return self._msg_one("unlokSourceGrp")

    def instancer(self):
        return self._msg_one("unlokInstancer")

    def paths(self):
        return self._msg_list("unlokPaths")

    def surfaces(self):
        return self._msg_list("unlokSurfaces")

    def sources(self):
        return self._msg_list("unlokSources")

    # --------------------------------------------------------------- settings
    def get_settings(self):
        out = dict(PS_DEFAULTS)
        root = self.root()
        if root:
            try:
                out.update(json.loads(cmds.getAttr(root + ".unlokSettings") or "{}"))
            except ValueError:
                pass
        return out

    def set_settings(self, settings):
        root = self.root()
        if root:
            with NoUndo():
                cmds.setAttr(root + ".unlokSettings", json.dumps(settings, sort_keys=True), type="string")

    # ---------------------------------------------------------------- inputs
    def set_paths(self, curves, add=False):
        """Assign path curves. Replaced curves that the tool drew are deleted."""
        self.invalidate()
        with NoUndo():
            grp = self.path_group()
            old = self.paths()
            self._msg_set("unlokPaths", curves, add=add)
            if not add and grp:
                keep = set(self.paths())
                for c in old:
                    if c not in keep and c.startswith(grp + "|") and cmds.objExists(c):
                        cmds.delete(c)

    def set_surfaces(self, meshes, add=False):
        self.invalidate()
        self._msg_set("unlokSurfaces", meshes, add=add)

    def set_sources(self, nodes):
        self.invalidate()
        self._msg_set("unlokSources", nodes)

    def adopt_curve(self, curve):
        """Move a tool-created curve under this system's path group."""
        grp = self.path_group()
        if not grp:
            return curve
        with NoUndo():
            return long_name(cmds.parent(curve, grp)[0])

    # --------------------------------------------------------------- sources
    def proxies(self):
        inst = self.instancer()
        if not inst:
            return []
        out = []
        for idx in cmds.getAttr(inst + ".inputHierarchy", multiIndices=True) or []:
            conns = cmds.listConnections("%s.inputHierarchy[%d]" % (inst, idx), source=True, destination=False) or []
            if conns:
                out.append(long_name(conns[0]))
        return [p for p in out if p]

    def _clear_proxies(self):
        inst = self.instancer()
        proxies = self.proxies()
        if inst:
            for idx in cmds.getAttr(inst + ".inputHierarchy", multiIndices=True) or []:
                cmds.removeMultiInstance("%s.inputHierarchy[%d]" % (inst, idx), b=True)
        existing = [p for p in proxies if cmds.objExists(p)]
        if existing:
            # Proxies only hold *instances* of user meshes, so deleting them
            # never touches the user's originals.
            cmds.delete(existing)

    def _wire_proxy(self, proxy, index):
        cmds.connectAttr(proxy + ".matrix", "%s.inputHierarchy[%d]" % (self.instancer(), index), force=True)

    def _ensure_proxies(self, s):
        root = self.root()
        kind = s.get("source_type", "Cube")
        if kind == "Mesh":
            srcs = [n for n in self.sources() if cmds.objExists(n)]
            sig = "mesh:" + ",".join(cmds.ls(srcs, uuid=True) or [])
        else:
            srcs = []
            sig = "preset:" + kind
        current = cmds.getAttr(root + ".unlokProxySig") or ""
        if sig == current and self.proxies():
            return
        self.invalidate()
        self._preset_state = None
        with NoUndo(), PreserveSelection():
            self._clear_proxies()
            group = self.source_group()
            short = self.name()
            if kind == "Mesh":
                index = 0
                for src in srcs:
                    proxy = self._make_mesh_proxy(src, group, short)
                    if proxy:
                        self._wire_proxy(proxy, index)
                        index += 1
            elif kind in PRESET_TYPES:
                proxy = self._make_preset_proxy(kind, s, group, short)
                self._wire_proxy(proxy, 0)
            cmds.setAttr(root + ".unlokProxySig", sig, type="string")

    @staticmethod
    def _make_preset_proxy(kind, s, group, short):
        proxy = cmds.createNode("transform", name=short + "_src", parent=group, skipSelect=True)
        sides = int(max(3, s.get("preset_sides", 12)))
        if kind == "Cube":
            geo = cmds.polyCube(w=1, h=1, d=1, sx=1, sy=1, sz=1, ch=True, name=short + "_cube")[0]
        elif kind == "Cylinder":
            geo = cmds.polyCylinder(r=0.5, h=1, sx=sides, sy=1, sz=1, ax=(0, 1, 0), ch=True, name=short + "_cylinder")[0]
        elif kind == "Plane":
            geo = cmds.polyPlane(w=1, h=1, sx=1, sy=1, ax=(0, 1, 0), ch=True, name=short + "_plane")[0]
        else:
            geo = cmds.polySphere(r=0.5, sx=sides, sy=max(4, sides // 2), ax=(0, 1, 0), ch=True, name=short + "_sphere")[0]
        cmds.parent(geo, proxy, relative=True)
        return long_name(proxy)

    @staticmethod
    def _make_mesh_proxy(src, group, short):
        """Proxy transform at identity that *instances* the source's contents.

        Edits to the user's mesh show up in the scatter immediately, and the
        source's own position in the scene is ignored (object space is used).
        """
        if cmds.objectType(src, isAType="shape"):
            src = long_name(cmds.listRelatives(src, parent=True, fullPath=True)[0])
        children = []
        for child in cmds.listRelatives(src, children=True, fullPath=True) or []:
            if cmds.objectType(child, isAType="shape"):
                if cmds.getAttr(child + ".intermediateObject"):
                    continue
            elif not cmds.objectType(child, isAType="transform"):
                continue
            children.append(child)
        if not children:
            return None
        proxy = long_name(cmds.createNode("transform", name=short + "_src_" + short_name(src), parent=group, skipSelect=True))
        fn = om.MFnDagNode(get_mobject(proxy))
        for child in children:
            obj = get_mobject(child)
            if obj is not None:
                fn.addChild(obj, om.MFnDagNode.kNextPos, True)
        return proxy

    def _update_presets(self, s):
        if s.get("source_type") not in PRESET_TYPES:
            return
        size = [max(1e-4, float(s.get(k, 1.0))) for k in ("size_x", "size_y", "size_z")]
        sides = int(max(3, s.get("preset_sides", 12)))
        state = (s.get("source_type"), tuple(size), sides)
        if state == self._preset_state:
            return  # nothing changed: skip the scene queries entirely
        self._preset_state = state
        self.invalidate()  # item sizes changed
        for proxy in self.proxies():
            for geo in cmds.listRelatives(proxy, children=True, type="transform", fullPath=True) or []:
                cur = cmds.getAttr(geo + ".scale")[0]
                if any(abs(a - b) > 1e-9 for a, b in zip(cur, size)):
                    cmds.setAttr(geo + ".scale", *size)
                for shape in cmds.listRelatives(geo, shapes=True, fullPath=True) or []:
                    for node in cmds.listConnections(shape + ".inMesh", source=True, destination=False) or []:
                        ntype = cmds.nodeType(node)
                        if ntype in ("polyCylinder", "polySphere") and cmds.getAttr(node + ".subdivisionsAxis") != sides:
                            cmds.setAttr(node + ".subdivisionsAxis", sides)
                        if ntype == "polySphere":
                            h = max(4, sides // 2)
                            if cmds.getAttr(node + ".subdivisionsHeight") != h:
                                cmds.setAttr(node + ".subdivisionsHeight", h)

    @staticmethod
    def _proxy_corners(proxy):
        """Bounding box corners of a proxy, in the proxy's own space."""
        try:
            bb = cmds.exactWorldBoundingBox(proxy)
        except RuntimeError:
            return None
        if not bb or (bb[3] - bb[0]) + (bb[4] - bb[1]) + (bb[5] - bb[2]) <= 0:
            return None
        inv = om.MMatrix(cmds.xform(proxy, q=True, worldSpace=True, matrix=True)).inverse()
        corners = []
        for x in (bb[0], bb[3]):
            for y in (bb[1], bb[4]):
                for z in (bb[2], bb[5]):
                    corners.append(om.MPoint(x, y, z) * inv)
        return corners

    # ---------------------------------------------------------------- inputs
    def _curve_samplers(self):
        out = []
        for node in self.paths():
            if cmds.nodeType(node) == "nurbsCurve":
                shapes = [node]
            else:
                shapes = cmds.listRelatives(node, shapes=True, type="nurbsCurve", fullPath=True, noIntermediate=True) or []
            for shape in shapes:
                dag = get_dag_path(shape)
                if dag is None:
                    continue
                fn = om.MFnNurbsCurve(dag)
                obj_len = fn.length()
                if obj_len < 1e-6:
                    continue
                m = dag.inclusiveMatrix()
                axis_scale = sum(om.MVector(m.getElement(r, 0), m.getElement(r, 1), m.getElement(r, 2)).length()
                                 for r in range(3)) / 3.0
                closed = fn.form != om.MFnNurbsCurve.kOpen
                out.append(_CurveSampler(fn, obj_len, obj_len * axis_scale, closed))
        return out

    def _surface_queries(self):
        out = []
        for node in self.surfaces():
            if cmds.nodeType(node) == "mesh":
                shapes = [node]
            else:
                shapes = cmds.listRelatives(node, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or []
            for shape in shapes:
                dag = get_dag_path(shape)
                if dag is not None:
                    try:
                        out.append(_SurfaceQuery(dag))
                    except RuntimeError:
                        pass
        return out

    # --------------------------------------------------------------- compute
    # Compute runs in two cached stages so the common tweaks stay instant:
    #   placement : sample the path, snap to surfaces, build each item's frame
    #               (the expensive part: curve + surface queries)
    #   finish    : per-item scale / rotation on top of those frames
    # Changing rotation or (outside Fit to Size) scale only re-runs "finish".
    # invalidate() drops the cache when paths, surfaces or sources change.

    # Settings that only affect the finish stage. In Fit to Size, scale and
    # the rotation offset change item lengths (spacing), so they count as
    # placement there.
    _FINISH_ONLY = ("rand_rot_x", "rand_rot_y", "rand_rot_z", "preview_boxes", "bake_mode", "keep_system",
                    "smoothing")
    _FINISH_ONLY_UNLESS_FIT = ("rot_x", "rot_y", "rot_z", "scale", "scale_x", "scale_y", "scale_z",
                               "rand_scale_min", "rand_scale_max", "rand_scale_axis")

    def invalidate(self):
        """Inputs changed (curve edited, surface moved, source modelled...)."""
        self._cache.clear()
        self._pushed = None

    def _placement_key(self, s):
        skip = set(self._FINISH_ONLY)
        if s.get("dist_mode") != "Fit to Size":
            skip.update(self._FINISH_ONLY_UNLESS_FIT)
        return tuple(sorted((k, v) for k, v in s.items() if k not in skip))

    def _variants(self, s, proxies):
        """Per source variant: (pre-matrix, bounding corners after pre)."""
        remap, axes_ok = axis_remap_matrix(s["forward_axis"], s["up_axis"])
        key = ("variants", tuple(proxies), s["forward_axis"], s["up_axis"], s["pivot"])
        hit = self._cache.get(key)
        if hit is not None:
            return hit, axes_ok
        variants = []
        for proxy in proxies:
            corners = self._proxy_corners(proxy) or [om.MPoint(x, y, z) for x in (-0.5, 0.5)
                                                     for y in (-0.5, 0.5) for z in (-0.5, 0.5)]
            rc = [c * remap for c in corners]
            xs, ys, zs = [c.x for c in rc], [c.y for c in rc], [c.z for c in rc]
            cx, cz = (min(xs) + max(xs)) * 0.5, (min(zs) + max(zs)) * 0.5
            if s["pivot"] == "Center":
                pivot = (cx, (min(ys) + max(ys)) * 0.5, cz)
            elif s["pivot"] == "Bottom":
                pivot = (cx, min(ys), cz)
            else:
                pivot = (0.0, 0.0, 0.0)
            pre = remap * mat_translate(-pivot[0], -pivot[1], -pivot[2])
            variants.append((pre, [c * pre for c in corners]))
        self._cache[key] = variants
        return variants, axes_ok

    def compute(self, s, use_cache=True):
        """Return (items, warning). items = [(variant_index, MMatrix), ...]."""
        if not use_cache:
            self.invalidate()
        proxies = self.proxies()
        if not proxies:
            if s.get("source_type") == "Mesh":
                return [], "Pick source meshes: select them and press 'Use Selected Meshes'."
            return [], "No source."
        variants, axes_ok = self._variants(s, proxies)
        warning = None if axes_ok else "Forward and Up axis can't be the same axis."

        pkey = ("placement", self._placement_key(s), len(variants))
        placed = self._cache.get(pkey)
        if placed is None:
            curves = self._curve_samplers()
            if not curves:
                return [], "No path yet. Draw one, or select a curve / edges and press 'Use Selection'."
            for k in [k for k in self._cache if k[0] == "placement"]:
                del self._cache[k]  # keep one placement in memory
            placed = self._place(s, variants, curves, self._surface_queries())
            self._cache[pkey] = placed
        placements, truncated = placed
        if truncated:
            warning = "Capped at %d items (raise 'Max items' in Output if you really need more)." % int(s["max_items"])
        fkey = ("finish", pkey, tuple(sorted(s.items())))
        items = self._cache.get(fkey)
        if items is None:
            for k in [k for k in self._cache if k[0] == "finish"]:
                del self._cache[k]
            items = self._cache[fkey] = self._finish(s, variants, placements)
        return items, warning

    @staticmethod
    def _scale_fn(s):
        base = (s["scale"] * s["scale_x"], s["scale"] * s["scale_y"], s["scale"] * s["scale_z"])
        smin, smax, axis_j = s["rand_scale_min"], s["rand_scale_max"], s["rand_scale_axis"]
        if abs(smax - smin) < 1e-12 and axis_j == 0:
            const = tuple(max(1e-4, b * smin) for b in base)
            return lambda u: const
        span = smax - smin

        def scale_of(u):
            mult = smin + span * u[2]
            return (max(1e-4, base[0] * mult * (1.0 + (u[3] * 2.0 - 1.0) * axis_j)),
                    max(1e-4, base[1] * mult * (1.0 + (u[4] * 2.0 - 1.0) * axis_j)),
                    max(1e-4, base[2] * mult * (1.0 + (u[5] * 2.0 - 1.0) * axis_j)))
        return scale_of

    def _place(self, s, variants, curves, surfaces):
        """The expensive stage: [(variant, randoms, frame MMatrix)], truncated."""
        n_var = len(variants)
        rot_offset = mat_euler_deg(s["rot_x"], s["rot_y"], s["rot_z"])
        scale_of = self._scale_fn(s)
        extent_cache = {}

        def extent(vi, sc):
            key = (vi, sc)
            hit = extent_cache.get(key)
            if hit is None:
                m = mat_scale(*sc) * rot_offset
                xs = [(c * m).x for c in variants[vi][1]]
                hit = extent_cache[key] = (min(xs), max(xs))
            return hit

        seed = int(s["seed"])
        jit = (s["rand_along"], s["rand_side"], s["rand_up"])
        skip = s["skip_chance"] / 100.0
        cycle = s["variant_mode"] == "Cycle"
        mode = s["dist_mode"]
        gap = s["gap"]
        rows = max(1, int(s["rows"]))
        max_items = max(1, int(s["max_items"]))
        use_normal = s["up_mode"] == "Surface Normal" and bool(surfaces)
        snap = s["snap_surface"] and bool(surfaces)
        follow = s["follow_path"]
        surface_offset = s["surface_offset"]
        row_lift = s["row_lift"]

        def variant_of(u, row, i):
            return (i + row) % n_var if cycle else min(n_var - 1, int(u[0] * n_var))

        def closest(point):
            best = None
            for q in surfaces:
                hit = q.closest(point)
                if hit is not None and (best is None or hit[0] < best[0]):
                    best = hit
            return best

        placements = []
        truncated = False
        base_cache = {}  # rows share path samples: (path, distance) -> frame data
        for pi, curve in enumerate(curves):
            start = s["start_offset"]
            end = curve.length - s["end_offset"]
            usable = end - start
            if usable <= 1e-6:
                continue
            if mode == "Fit to Size":
                base_sc = tuple(max(1e-4, v) for v in (s["scale"] * s["scale_x"], s["scale"] * s["scale_y"],
                                                       s["scale"] * s["scale_z"]))
                mn, mx = extent(0, base_sc)
                pitch = max(1e-4, (mx - mn) + gap)
            elif mode == "Spacing":
                pitch = max(1e-4, s["spacing"])
            else:
                n = max(1, int(s["count"]))
                pitch = usable / n if curve.closed else (usable / (n - 1) if n > 1 else usable)

            for row in range(rows):
                row_off = ((row - (rows - 1) * 0.5) if s["rows_centered"] else row) * s["row_spacing"]
                stagger = (row % 2) * s["row_stagger"] * pitch

                slots = []  # (distance, randoms, variant)
                if mode == "Fit to Size":
                    d = start + stagger
                    i = 0
                    while len(placements) + len(slots) < max_items:
                        u = _rand12(seed, pi, row, i)
                        vi = variant_of(u, row, i)
                        mn, mx = extent(vi, scale_of(u))
                        pos = d - mn
                        if pos + mx > end + 1e-6:
                            break
                        slots.append((pos, u, vi))
                        d = pos + max(1e-4, mx + gap)
                        i += 1
                    else:
                        truncated = True
                elif mode == "Spacing":
                    d = start + stagger
                    i = 0
                    while d <= end + 1e-6:
                        if len(placements) + len(slots) >= max_items:
                            truncated = True
                            break
                        u = _rand12(seed, pi, row, i)
                        slots.append((d, u, variant_of(u, row, i)))
                        d += pitch
                        i += 1
                else:
                    n = max(1, int(s["count"]))
                    for i in range(n):
                        if len(placements) + len(slots) >= max_items:
                            truncated = True
                            break
                        if n == 1 and not curve.closed:
                            d = start + usable * 0.5 + stagger
                        else:
                            d = start + i * pitch + stagger
                        if not curve.closed and d > end + 1e-6:
                            continue
                        u = _rand12(seed, pi, row, i)
                        slots.append((d, u, variant_of(u, row, i)))

                for dist, u, vi in slots:
                    if u[1] < skip:
                        continue
                    key = (pi, round(dist, 6))
                    base = base_cache.get(key)
                    if base is None:
                        point, tangent = curve.sample(dist)
                        up = WORLD_UP
                        if use_normal:
                            hit = closest(point)
                            if hit:
                                up = hit[2]
                        x0 = tangent - up * (tangent * up)
                        if x0.length() < 1e-6:
                            x0 = WORLD_X - up * (WORLD_X * up)
                            if x0.length() < 1e-6:
                                x0 = WORLD_Z
                        x0.normalize()
                        z0 = (x0 ^ up).normal()
                        base = base_cache[key] = (point, tangent, up, x0, z0)
                    point, tangent, up, x0, z0 = base
                    p = om.MPoint(point) + z0 * (row_off + (u[10] * 2.0 - 1.0) * jit[1]) \
                        + x0 * ((u[9] * 2.0 - 1.0) * jit[0])
                    if snap:
                        hit = closest(p)
                        if hit:
                            p = hit[1] + hit[2] * surface_offset
                            if use_normal:
                                up = hit[2]
                    p = p + up * (row_lift * row + (u[11] * 2.0 - 1.0) * jit[2])

                    ref = tangent if follow else WORLD_X
                    xf = ref - up * (ref * up)
                    if xf.length() < 1e-6:
                        xf = x0
                    xf.normalize()
                    zf = (xf ^ up).normal()
                    yf = (zf ^ xf).normal()
                    placements.append((vi, u, mat_from_frame(xf, yf, zf, p)))
            if truncated:
                break
        return placements, truncated

    def _finish(self, s, variants, placements):
        """The cheap stage: put each source on its frame with scale/rotation."""
        rot_offset = mat_euler_deg(s["rot_x"], s["rot_y"], s["rot_z"])
        scale_of = self._scale_fn(s)
        rr = (s["rand_rot_x"], s["rand_rot_y"], s["rand_rot_z"])
        has_rand_rot = any(abs(v) > 1e-9 for v in rr)
        constant_scale = scale_of((0.0,) * 12) == scale_of((1.0,) * 12)
        if constant_scale and not has_rand_rot:
            sc = scale_of((0.0,) * 12)
            locals_ = [pre * mat_scale(*sc) * rot_offset for pre, _ in variants]
            return [(vi, locals_[vi] * frame) for vi, u, frame in placements]
        items = []
        for vi, u, frame in placements:
            local = variants[vi][0] * mat_scale(*scale_of(u)) * rot_offset
            if has_rand_rot:
                local = local * mat_euler_deg((u[6] * 2.0 - 1.0) * rr[0], (u[7] * 2.0 - 1.0) * rr[1],
                                              (u[8] * 2.0 - 1.0) * rr[2])
            items.append((vi, local * frame))
        return items

    # ------------------------------------------------------------- preview
    def _push(self, items, boxes=False):
        inst = self.instancer()
        if not inst:
            return
        sel = om1.MSelectionList()
        sel.add(inst)
        obj = om1.MObject()
        sel.getDependNode(0, obj)
        plug = om1.MFnDependencyNode(obj).findPlug("inputPoints")
        fn = om1.MFnArrayAttrsData()
        data = fn.create()
        pos = fn.vectorArray("position")
        rot = fn.vectorArray("rotation")
        scl = fn.vectorArray("scale")
        idx = fn.doubleArray("objectIndex")
        n = len(items)
        for arr in (pos, rot, scl, idx):
            arr.setLength(n)
        vec = om1.MVector
        deg = math.degrees
        world = om.MSpace.kWorld
        for k, (vi, m) in enumerate(items):
            tm = om.MTransformationMatrix(m)
            t = tm.translation(world)
            r = tm.rotation()
            sc = tm.scale(world)
            pos.set(vec(t.x, t.y, t.z), k)
            rot.set(vec(deg(r.x), deg(r.y), deg(r.z)), k)
            scl.set(vec(sc[0], sc[1], sc[2]), k)
            idx.set(float(vi), k)
        plug.setMObject(data)
        lod = 1 if boxes else 0
        if cmds.getAttr(inst + ".levelOfDetail") != lod:
            cmds.setAttr(inst + ".levelOfDetail", lod)

    def rebuild(self, s):
        """Apply settings and refresh the preview. Returns (count, ms, warning)."""
        t0 = time.time()
        with NoUndo():
            root = self.root()
            if not root:
                return 0, 0.0, "Scatter system no longer exists."
            if not cmds.getAttr(root + ".visibility"):
                cmds.setAttr(root + ".visibility", 1)
            self.set_settings(s)
            self._ensure_proxies(s)
            self._update_presets(s)
            items, warning = self.compute(s)
            # Same list object = cache hit = nothing moved; skip the upload.
            if items is not self._pushed or s.get("preview_boxes", False) != self._pushed_boxes:
                self._push(items, s.get("preview_boxes", False))
                self._pushed = items
                self._pushed_boxes = s.get("preview_boxes", False)
        self.last_count = len(items)
        return len(items), (time.time() - t0) * 1000.0, warning

    # ------------------------------------------------------------------ bake
    def _variant_meshes(self, proxy):
        """[(mesh shape MObject, mesh path, matrix relative to proxy)]."""
        out = []
        proxy_dag = get_dag_path(proxy)
        if proxy_dag is None:
            return out
        inv = proxy_dag.inclusiveMatrixInverse()
        for shape in cmds.listRelatives(proxy, allDescendents=True, type="mesh", fullPath=True) or []:
            if cmds.getAttr(shape + ".intermediateObject"):
                continue
            dag = get_dag_path(shape)
            if dag is None:
                continue
            out.append((dag.node(), shape, dag.inclusiveMatrix() * inv))
        return out

    def bake(self, s):
        """Turn the preview into real scene objects. Returns the result node."""
        items, _ = self.compute(s, use_cache=False)
        if not items:
            raise RuntimeError("Nothing to bake.")
        proxies = self.proxies()
        mode = s.get("bake_mode", "Instances")
        short = self.name()
        with NoUndo(), PreserveSelection():
            out = long_name(cmds.group(empty=True, world=True, name=short + "_baked1"))
            out_obj = get_mobject(out)
            if mode == "Instances":
                self._bake_instances(items, proxies, out_obj, short)
                result = out
            elif mode == "Combined Mesh":
                result = self._combine_direct(items, proxies, short)
                if result is None:  # too heavy for the direct build: copies + polyUnite
                    self._bake_copies(items, proxies, out_obj, short)
                    result = self._combine(out, short)
                else:
                    cmds.delete(out)
            else:
                self._bake_copies(items, proxies, out_obj, short)
                result = out
            root = self.root()
            if s.get("keep_system"):
                cmds.setAttr(root + ".visibility", 0)
            else:
                cmds.delete(root)
        return result

    @staticmethod
    def _new_transforms(parent_obj, names):
        mod = om.MDagModifier()
        objs = []
        for name in names:
            obj = mod.createNode("transform", parent_obj)
            mod.renameNode(obj, name)
            objs.append(obj)
        mod.doIt()
        return objs

    def _bake_instances(self, items, proxies, out_obj, short):
        children = []
        for proxy in proxies:
            kids = []
            for child in cmds.listRelatives(proxy, children=True, fullPath=True) or []:
                obj = get_mobject(child)
                if obj is not None:
                    kids.append(obj)
            children.append(kids)
        objs = self._new_transforms(out_obj, ["%s_%04d" % (short, i + 1) for i in range(len(items))])
        for obj, (vi, m) in zip(objs, items):
            om.MFnTransform(obj).setTransformation(om.MTransformationMatrix(m))
            fn = om.MFnDagNode(obj)
            for kid in children[vi]:
                fn.addChild(kid, om.MFnDagNode.kNextPos, True)

    def _bake_copies(self, items, proxies, out_obj, short):
        meshes = [self._variant_meshes(p) for p in proxies]
        objs = self._new_transforms(out_obj, ["%s_%04d" % (short, i + 1) for i in range(len(items))])
        copied = [[[] for _ in v] for v in meshes]  # per variant, per mesh: new shape paths
        fn_mesh = om.MFnMesh()
        for obj, (vi, m) in zip(objs, items):
            variant = meshes[vi]
            if len(variant) == 1:
                src_obj, _, rel = variant[0]
                om.MFnTransform(obj).setTransformation(om.MTransformationMatrix(rel * m))
                new_shape = fn_mesh.copy(src_obj, obj)
                copied[vi][0].append(new_shape)
                continue
            om.MFnTransform(obj).setTransformation(om.MTransformationMatrix(m))
            parts = self._new_transforms(obj, ["part%d" % (k + 1) for k in range(len(variant))])
            for k, (part, (src_obj, _, rel)) in enumerate(zip(parts, variant)):
                om.MFnTransform(part).setTransformation(om.MTransformationMatrix(rel))
                copied[vi][k].append(fn_mesh.copy(src_obj, part))
        for vi, variant in enumerate(meshes):
            for k, (_, src_path, _) in enumerate(variant):
                dst = []
                for o in copied[vi][k]:
                    if o.hasFn(om.MFn.kMesh):
                        dst.append(om.MDagPath.getAPathTo(o).fullPathName())
                    else:
                        dst.extend(cmds.listRelatives(om.MDagPath.getAPathTo(o).fullPathName(),
                                                      shapes=True, fullPath=True) or [])
                copy_shading(src_path, dst)

    COMBINE_DIRECT_MAX_POINTS = 3000000

    @staticmethod
    def _mesh_data(path, rel):
        """Everything needed to rebuild a mesh: points, faces, UVs, shading
        per face and which edges are hard (as face + edge-in-face slots,
        since edge ids aren't stable between meshes)."""
        dag = get_dag_path(path)
        fn = om.MFnMesh(dag)
        counts, connects = fn.getVertices()
        uv_set = fn.currentUVSetName()
        if uv_set and fn.numUVs(uv_set):
            us, vs = fn.getUVs(uv_set)
            uvc, uvi = fn.getAssignedUVs(uv_set)
        else:
            us = vs = uvc = uvi = []
        try:
            shaders, face_sg = fn.getConnectedShaders(dag.instanceNumber())
            sgs = [om.MFnDependencyNode(o).name() for o in shaders]
        except RuntimeError:
            sgs, face_sg = [], []
        hard = []
        seen = set()
        it = om.MItMeshPolygon(dag)
        while not it.isDone():
            f = it.index()
            for k, e in enumerate(it.getEdges()):
                if e not in seen:
                    seen.add(e)
                    if not fn.isEdgeSmooth(e):
                        hard.append((f, k))
            it.next()
        return {
            "pts": [(q.x, q.y, q.z) for q in fn.getPoints(om.MSpace.kObject)],
            "counts": list(counts), "connects": list(connects),
            "us": list(us), "vs": list(vs), "uvc": list(uvc), "uvi": list(uvi),
            "sgs": sgs, "face_sg": list(face_sg), "hard": hard, "rel": rel,
            "nfaces": len(counts), "nuvs": len(us),
        }

    def _combine_direct(self, items, proxies, short):
        """Build the combined mesh in one MFnMesh.create call.

        O(n) and ~100x faster than polyUnite on thousands of pieces. Keeps
        UVs (current set), hard/soft edges and per-face materials. Returns
        None when the result would be too heavy for a Python build.
        """
        data = [[self._mesh_data(path, rel) for _, path, rel in self._variant_meshes(p)] for p in proxies]
        total = sum(len(md["pts"]) for vi, _ in items for md in data[vi])
        if total > self.COMBINE_DIRECT_MAX_POINTS or total == 0:
            return None
        points, counts, connects = [], [], []
        us, vs, uvc, uvi = [], [], [], []
        by_sg = {}
        hard = []
        vbase = fbase = uvbase = 0
        has_uvs = all(md["uvc"] for v in data for md in v)
        for vi, m in items:
            for md in data[vi]:
                mm = md["rel"] * m
                a00, a01, a02 = mm.getElement(0, 0), mm.getElement(0, 1), mm.getElement(0, 2)
                a10, a11, a12 = mm.getElement(1, 0), mm.getElement(1, 1), mm.getElement(1, 2)
                a20, a21, a22 = mm.getElement(2, 0), mm.getElement(2, 1), mm.getElement(2, 2)
                a30, a31, a32 = mm.getElement(3, 0), mm.getElement(3, 1), mm.getElement(3, 2)
                points.extend((x * a00 + y * a10 + z * a20 + a30,
                               x * a01 + y * a11 + z * a21 + a31,
                               x * a02 + y * a12 + z * a22 + a32) for x, y, z in md["pts"])
                counts.extend(md["counts"])
                connects.extend([c + vbase for c in md["connects"]])
                if has_uvs:
                    us.extend(md["us"])
                    vs.extend(md["vs"])
                    uvc.extend(md["uvc"])
                    uvi.extend([c + uvbase for c in md["uvi"]])
                face_sg, sgs = md["face_sg"], md["sgs"]
                if face_sg and len(set(face_sg)) == 1:
                    sid = face_sg[0]
                    by_sg.setdefault(sgs[sid] if 0 <= sid < len(sgs) else None, []).append(
                        (fbase, fbase + md["nfaces"] - 1))
                else:
                    for f, sid in enumerate(face_sg or [-1] * md["nfaces"]):
                        by_sg.setdefault(sgs[sid] if 0 <= sid < len(sgs) else None, []).append(
                            (fbase + f, fbase + f))
                hard.extend((fbase + f, k) for f, k in md["hard"])
                vbase += len(md["pts"])
                fbase += md["nfaces"]
                uvbase += md["nuvs"]

        mod = om.MDagModifier()
        xform = mod.createNode("transform")
        mod.renameNode(xform, short + "_combined1")
        mod.doIt()
        fn = om.MFnMesh()
        if has_uvs:
            mesh = fn.create(om.MPointArray(points), counts, connects, us, vs, xform)
            fn.assignUVs(uvc, uvi)
        else:
            mesh = fn.create(om.MPointArray(points), counts, connects, parent=xform)
        if hard:
            it = om.MItMeshPolygon(mesh)
            ids = []
            for f, k in hard:
                it.setIndex(f)
                ids.append(it.getEdges()[k])
            fn.setEdgeSmoothings(ids, [False] * len(ids))
            fn.cleanupEdgeSmoothing()
            fn.updateSurface()
        shape = om.MDagPath.getAPathTo(mesh).fullPathName()
        for sg, spans in by_sg.items():
            sg = sg or "initialShadingGroup"
            if len(by_sg) == 1:
                cmds.sets(shape, edit=True, forceElement=sg)
                break
            merged = []
            for a, b in sorted(spans):
                if merged and a <= merged[-1][1] + 1:
                    merged[-1][1] = max(merged[-1][1], b)
                else:
                    merged.append([a, b])
            comps = ["%s.f[%d:%d]" % (shape, a, b) if a != b else "%s.f[%d]" % (shape, a) for a, b in merged]
            for i in range(0, len(comps), 5000):
                cmds.sets(comps[i:i + 5000], edit=True, forceElement=sg)
        return long_name(om.MDagPath.getAPathTo(xform).fullPathName())

    @staticmethod
    def _combine(group, short):
        shapes = cmds.listRelatives(group, allDescendents=True, type="mesh", fullPath=True) or []
        xforms = []
        for sh in shapes:
            p = cmds.listRelatives(sh, parent=True, fullPath=True)[0]
            if p not in xforms:
                xforms.append(p)
        if len(xforms) < 2:
            if xforms:
                result = long_name(cmds.parent(xforms[0], world=True)[0])
                cmds.delete(group)
                return long_name(cmds.rename(result, short + "_combined1"))
            return group
        merged = cmds.polyUnite(xforms, constructionHistory=False, mergeUVSets=1, name=short + "_combined1")[0]
        if cmds.objExists(group):
            cmds.delete(group)
        return long_name(merged)

    def delete(self):
        root = self.root()
        if root:
            with NoUndo():
                cmds.delete(root)


_MASK64 = (1 << 64) - 1


def _rand12(seed, a, b, c):
    """12 deterministic uniforms in [0, 1) for one item (splitmix64).

    Several times cheaper than a random.Random per item, and stable: an
    item keeps its random values when the count or other items change.
    """
    x = (seed * 0x9E3779B97F4A7C15 ^ a * 0xBF58476D1CE4E5B9 ^ b * 0x94D049BB133111EB
         ^ c * 0xD6E8FEB86659FD93) & _MASK64
    out = []
    for _ in range(3):
        x = (x + 0x9E3779B97F4A7C15) & _MASK64
        z = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
        z ^= z >> 31
        out.extend(((z >> 48) & 0xFFFF, (z >> 32) & 0xFFFF, (z >> 16) & 0xFFFF, z & 0xFFFF))
    return tuple(v * (1.0 / 65536.0) for v in out)


class _SurfaceQuery(object):
    """Accelerated closest point + normal on a mesh, in world space.

    MMeshIntersector answers in ~3 us vs ~200 us for MFnMesh's brute-force
    getClosestPointAndNormal. It takes world points but answers in the
    mesh's object space, so results are mapped back here.
    """
    __slots__ = ("inter", "matrix", "normal_matrix")

    def __init__(self, dag):
        self.matrix = dag.inclusiveMatrix()
        self.normal_matrix = self.matrix.inverse().transpose()
        self.inter = om.MMeshIntersector()
        self.inter.create(dag.node(), self.matrix)

    def closest(self, point):
        """(distance, world point, world unit normal) or None."""
        try:
            pom = self.inter.getClosestPoint(point)
        except RuntimeError:
            return None
        p = om.MPoint(pom.point) * self.matrix
        n = om.MVector(pom.normal) * self.normal_matrix
        if n.length() < 1e-12:
            return None
        return (p - point).length(), p, n.normal()


def restore_scatter_previews():
    """The instancer's point data isn't saved with the scene, so live scatters
    come back empty after reopening a file. Rebuild them from their stored
    settings (called when the toolbox opens and whenever a scene opens)."""
    restored = 0
    for root in PathScatterSystem.all_roots():
        try:
            uuid = cmds.ls(root, uuid=True)[0]
            system = PathScatterSystem(uuid)
            if not cmds.getAttr(root + ".visibility"):
                continue  # hidden after a bake with "keep live system"
            with NoUndo():
                system.rebuild(system.get_settings())
            restored += 1
        except Exception:
            traceback.print_exc()
    return restored


class _CurveSampler(object):
    __slots__ = ("fn", "obj_length", "length", "closed")

    def __init__(self, fn, obj_length, world_length, closed):
        self.fn = fn
        self.obj_length = obj_length
        self.length = world_length
        self.closed = closed

    def sample(self, dist):
        if self.closed:
            dist = dist % self.length
        else:
            dist = clamp(dist, 0.0, self.length)
        obj_d = clamp(dist * self.obj_length / self.length, 0.0, self.obj_length * (1.0 - 1e-9))
        u = self.fn.findParamFromLength(obj_d)
        point = self.fn.getPointAtParam(u, om.MSpace.kWorld)
        tangent = self.fn.tangent(u, om.MSpace.kWorld)
        if tangent.length() < 1e-9:
            tangent = om.MVector(WORLD_X)
        return point, tangent.normal()


def _connect_whole_object_shading(sg, shapes):
    """Assign whole shapes to a shading group with one batched DG edit
    (what `sets -forceElement` does, minus its per-object overhead)."""
    sel = om.MSelectionList()
    sel.add(sg)
    sg_fn = om.MFnDependencyNode(sel.getDependNode(0))
    members = sg_fn.findPlug("dagSetMembers", False)
    used = members.getExistingArrayAttributeIndices()
    index = (max(used) + 1) if used else 0
    mod = om.MDGModifier()
    for shape in shapes:
        dag = get_dag_path(shape)
        if dag is None:
            continue
        iog = om.MFnDependencyNode(dag.node()).findPlug("instObjGroups", False)
        src = iog.elementByLogicalIndex(dag.instanceNumber())
        mod.connect(src, members.elementByLogicalIndex(index))
        index += 1
    mod.doIt()


def copy_shading(src_shape, dst_shapes):
    """Give dst_shapes the same shading engine assignments as src_shape,
    including per-face assignments."""
    if not dst_shapes:
        return
    src_obj = get_mobject(src_shape)
    assigns = []
    for sg in sorted(set(cmds.listConnections(src_shape, type="shadingEngine") or [])):
        for member in cmds.sets(sg, q=True) or []:
            node, _, comp = member.partition(".")
            node_shapes = [node] if cmds.objectType(node, isAType="shape") else (
                cmds.listRelatives(node, shapes=True, fullPath=True) or [])
            if any(get_mobject(n) == src_obj for n in node_shapes):
                entry = (sg, "." + comp if comp else "")
                if entry not in assigns:
                    assigns.append(entry)
    if not assigns:
        assigns = [("initialShadingGroup", "")]
    if len(assigns) == 1 and not assigns[0][1]:
        try:
            _connect_whole_object_shading(assigns[0][0], dst_shapes)
            return
        except RuntimeError:
            pass  # fall back to the command
    for sg, comp in assigns:
        targets = [d + comp for d in dst_shapes] if comp else list(dst_shapes)
        for i in range(0, len(targets), 2000):
            cmds.sets(targets[i:i + 2000], edit=True, forceElement=sg)


# =============================================================================
# Surface path drawing tool
# =============================================================================

DRAW_CTX = "unlokPathDrawCtx"


class SurfacePathDrawer(object):
    """Viewport tool: drag to draw a curve that sticks to whatever mesh is
    under the cursor (or the ground plane when there is nothing).

    Shift = straight line (still follows the surface).
    Ctrl  = add another path instead of replacing.
    """

    def __init__(self, on_stroke, get_smoothing, exclude_roots=None):
        self.on_stroke = on_stroke
        self.get_smoothing = get_smoothing
        self.exclude_roots = exclude_roots or (lambda: [])
        self.on_miss = None
        self.forced_surfaces = []
        self.preview = None  # (transform MObjectHandle, shape MDagPath, cv capacity)
        self._reset()

    def _reset(self):
        self.points = []  # [(MPoint, mesh path or None for the plane)]
        self.candidates = []  # [(dag, fn, accel, world bbox or None, path)] for this stroke
        self.last_mesh = None  # candidate the stroke is currently on (tried first)
        self.plane = None
        self.anchor = None
        self.last_screen = None
        self.last_drag = None
        self.straight = False
        self.add = False
        self._last_refresh = 0.0

    # -------------------------------------------------------------- activate
    def activate(self, surfaces=None):
        self.forced_surfaces = list(surfaces or [])
        if cmds.draggerContext(DRAW_CTX, exists=True):
            cmds.deleteUI(DRAW_CTX)
        cmds.draggerContext(
            DRAW_CTX,
            pressCommand=self._press,
            dragCommand=self._drag,
            releaseCommand=self._release,
            finalize=self._finalize,
            space="screen",
            cursor="crossHair",
            undoMode="step",
        )
        cmds.setToolTo(DRAW_CTX)
        # Make the stroke preview now, so no node is created mid-stroke.
        self._ensure_preview()

    @staticmethod
    def is_active():
        try:
            return cmds.currentCtx() == DRAW_CTX
        except RuntimeError:
            return False

    @staticmethod
    def deactivate():
        if SurfacePathDrawer.is_active():
            cmds.setToolTo("selectSuperContext")

    @staticmethod
    def delete_context():
        SurfacePathDrawer.deactivate()
        if cmds.draggerContext(DRAW_CTX, exists=True):
            cmds.deleteUI(DRAW_CTX)

    # ---------------------------------------------------------------- rays
    @staticmethod
    def _ray(x, y):
        view = omui.M3dView.active3dView()
        src, direction = om.MPoint(), om.MVector()
        view.viewToWorld(int(x), int(y), src, direction)
        return src, direction.normal()

    def _candidate_meshes(self, use_forced=True):
        """Meshes a stroke can land on: the chosen surfaces, or every visible
        mesh in the scene (excluding scatter systems)."""
        if use_forced and self.forced_surfaces:
            out = []
            for node in self.forced_surfaces:
                shapes = [node] if cmds.nodeType(node) == "mesh" else (
                    cmds.listRelatives(node, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or [])
                for sh in shapes:
                    dag = get_dag_path(sh)
                    if dag is not None:
                        out.append(dag)
            return out
        excluded = tuple(r + "|" for r in self.exclude_roots())
        out = []
        it = om.MItDag(om.MItDag.kDepthFirst, om.MFn.kMesh)
        while not it.isDone():
            dag = it.getPath()
            it.next()
            try:
                if om.MFnDagNode(dag).isIntermediateObject or not dag.isVisible():
                    continue
            except RuntimeError:
                continue
            if excluded and dag.fullPathName().startswith(excluded):
                continue
            out.append(dag)
        return out

    @staticmethod
    def _world_box(dag):
        try:
            bb = om.MFnDagNode(dag).boundingBox
            bb.transformUsing(dag.inclusiveMatrix())
            return bb
        except RuntimeError:
            return None

    @staticmethod
    def _ray_hits_box(src, direction, dag):
        return SurfacePathDrawer._ray_hits_bbox(src, direction, SurfacePathDrawer._world_box(dag))

    @staticmethod
    def _ray_hits_bbox(src, direction, bb):
        return SurfacePathDrawer._ray_box_entry(src, direction, bb) is not None

    @staticmethod
    def _ray_box_entry(src, direction, bb):
        """Distance along the ray where it enters the box (0 if it starts
        inside), or None if it misses. No box = always worth testing."""
        if bb is None:
            return 0.0
        tmin, tmax = -1e30, 1e30
        mn, mx = bb.min, bb.max
        for o, d, lo, hi in ((src.x, direction.x, mn.x, mx.x),
                             (src.y, direction.y, mn.y, mx.y),
                             (src.z, direction.z, mn.z, mx.z)):
            if abs(d) < 1e-12:
                if o < lo or o > hi:
                    return None
                continue
            t1, t2 = (lo - o) / d, (hi - o) / d
            if t1 > t2:
                t1, t2 = t2, t1
            tmin, tmax = max(tmin, t1), min(tmax, t2)
            if tmin > tmax:
                return None
        if tmax < 0:
            return None
        return max(tmin, 0.0)

    @staticmethod
    def _intersect(entry, src, direction):
        fn, accel = entry
        try:
            hit = fn.closestIntersection(om.MFloatPoint(src), om.MFloatVector(direction), om.MSpace.kWorld,
                                         1e7, False, accelParams=accel)
        except RuntimeError:
            return None
        if not hit:
            return None
        return om.MPoint(hit[0]), hit[1]

    def _cast(self, x, y):
        """World point under the screen position for the current stroke.

        Each point lands on whichever candidate mesh is under the cursor, so a
        stroke can cross several pieces and starting near an edge is fine.
        A stroke that starts on empty space draws on a plane instead.
        """
        src, direction = self._ray(x, y)
        if self.plane is None:
            # Nearest visible hit wins. Testing the mesh we're already on first
            # gives a hit distance that rules out (by bounding box) nearly
            # every other mesh without a full intersection test.
            best = None
            if self.last_mesh is not None:
                hit = self._intersect((self.last_mesh[1], self.last_mesh[2]), src, direction)
                if hit:
                    best = (hit[0], hit[1], self.last_mesh)
            for cand in self.candidates:
                if cand is self.last_mesh:
                    continue
                entry = self._ray_box_entry(src, direction, cand[3])
                if entry is None or (best is not None and entry >= best[1]):
                    continue
                hit = self._intersect((cand[1], cand[2]), src, direction)
                if hit and (best is None or hit[1] < best[1]):
                    best = (hit[0], hit[1], cand)
            if best is None:
                return None
            self.last_mesh = best[2]
            return best[0], best[2][4]
        origin, normal = self.plane
        denom = direction * normal
        if abs(denom) > 1e-9:
            t = ((origin - src) * normal) / denom
            if t > 0:
                return src + direction * t, None
        return None

    # -------------------------------------------------------------- events
    # Context callbacks read the mouse state, then hand off to the *_at
    # methods (which can also be driven from scripts / tests).
    def _press(self):
        try:
            x, y, _ = cmds.draggerContext(DRAW_CTX, q=True, anchorPoint=True)
            self.press_at(x, y, cmds.draggerContext(DRAW_CTX, q=True, modifier=True))
        except Exception:
            traceback.print_exc()

    def _drag(self):
        try:
            x, y, _ = cmds.draggerContext(DRAW_CTX, q=True, dragPoint=True)
            self.drag_at(x, y)
        except Exception:
            traceback.print_exc()

    def _release(self):
        try:
            self.release()
        except Exception:
            traceback.print_exc()

    def press_at(self, x, y, mod="none"):
        self._reset()
        self.anchor = (x, y)  # stroke in progress from here on
        self._ensure_preview()
        self.straight = mod == "shift"
        self.add = mod == "ctrl"
        src, direction = self._ray(x, y)

        self.candidates = self._make_candidates(self._candidate_meshes())
        self.anchor = (x, y)
        self.last_screen = (x, y)
        p = self._cast(x, y)
        if p is None and self.forced_surfaces:
            # Didn't start on the selected surface: use whatever is under the cursor.
            self.candidates = self._make_candidates(self._candidate_meshes(use_forced=False))
            self.last_mesh = None
            p = self._cast(x, y)
        if p is None:
            # Started on empty space: draw on the ground (or a camera-facing plane).
            if abs(direction.y) > 0.05:
                self.plane = (om.MPoint(0, 0, 0), om.MVector(0, 1, 0))
            else:
                self.plane = (om.MPoint(0, 0, 0), -direction)
            p = self._cast(x, y)
        if p is not None:
            self.points.append(p)

    @staticmethod
    def _make_candidates(dags):
        out = []
        for dag in dags:
            fn = om.MFnMesh(dag)
            out.append((dag, fn, fn.autoUniformGridParams(), SurfacePathDrawer._world_box(dag), dag.fullPathName()))
        return out

    def drag_at(self, x, y):
        if self.anchor is None:
            return
        self.last_drag = (x, y)
        if self.straight:
            # Coarse while dragging; release() resamples finely.
            self.points = self._line_points(x, y, 24.0)
        else:
            lx, ly = self.last_screen
            if math.hypot(x - lx, y - ly) < 3.0:
                return
            p = self._cast(x, y)
            if p is None:
                return
            self.points.append(p)
            self.last_screen = (x, y)
        self._update_preview()

    def _line_points(self, x, y, step_px):
        ax, ay = self.anchor
        steps = max(2, int(math.hypot(x - ax, y - ay) / step_px))
        pts = []
        for i in range(steps + 1):
            t = float(i) / steps
            p = self._cast(ax + (x - ax) * t, ay + (y - ay) * t)
            if p is not None:
                pts.append(p)
        return pts

    def release(self):
        try:
            if self.straight and self.last_drag is not None and self.anchor is not None:
                self.points = self._line_points(self.last_drag[0], self.last_drag[1], 6.0)
            # Meshes the stroke only grazed (e.g. the wall under an eave) don't
            # become snap surfaces, and points on them are dropped so the path
            # doesn't dip off the edge.
            counts = {}
            for _, mesh in self.points:
                if mesh is not None:
                    counts[mesh] = counts.get(mesh, 0) + 1
            total = float(sum(counts.values()) or 1)
            surfaces = [m for m, n in sorted(counts.items(), key=lambda kv: -kv[1]) if n / total >= 0.15]
            pts = self._clean_points([pt for pt, mesh in self.points if mesh is None or mesh in surfaces])
            self._set_preview_visible(False)
            if len(pts) < 2:
                if self.on_miss is not None:
                    self.on_miss()
                return
            with NoUndo(), PreserveSelection():
                curve = cmds.curve(degree=1, point=[(p.x, p.y, p.z) for p in pts], name="unlokPath1")
                smoothing = int(self.get_smoothing())
                spans = max(1, int(round((len(pts) - 1) / (1.0 + smoothing * 1.5))))
                if len(pts) > 2:
                    cmds.rebuildCurve(curve, constructionHistory=False, replaceOriginal=True, rebuildType=0,
                                      endKnots=1, keepRange=0, keepControlPoints=False, keepEndPoints=True,
                                      keepTangents=False, spans=spans, degree=3 if spans >= 3 else 1)
                curve = long_name(curve)
            self.on_stroke(curve, surfaces, self.add)
        finally:
            self.points = []
            self.anchor = None

    def _finalize(self):
        try:
            self._delete_preview()
        except Exception:
            pass

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _clean_points(points):
        out = []
        for p in points:
            if not out or (p - out[-1]).length() > 1e-4:
                out.append(p)
        return out

    PREVIEW_CAPACITY = 1024

    def _update_preview(self):
        """Show the stroke while drawing.

        Runs on every mouse move, so it stays off the command layer: one
        preview curve is made when the tool starts and then only has its CVs
        moved through the API (no node creation, selection changes or undo
        entries mid-stroke), with redraws capped at ~60 fps.
        """
        pts = self._clean_points([pt for pt, _ in self.points])
        if len(pts) < 2:
            return
        self._ensure_preview()
        handle, shape, cap = self.preview
        if len(pts) > cap:  # very long stroke: thin it out for display only
            step = int(math.ceil(len(pts) / float(cap - 1)))
            pts = pts[::step][:cap - 1] + [pts[-1]]
        cvs = om.MPointArray(pts)
        for _ in range(cap - len(pts)):
            cvs.append(pts[-1])  # spare CVs sit on the last point
        fn = om.MFnNurbsCurve(shape)
        fn.setCVPositions(cvs, om.MSpace.kObject)
        fn.updateCurve()
        self._set_preview_visible(True)
        now = time.time()
        if now - self._last_refresh > 1.0 / 60.0:
            self._last_refresh = now
            cmds.refresh(currentView=True)

    def _preview_valid(self):
        return self.preview is not None and self.preview[0].isValid() and self.preview[0].isAlive()

    def _ensure_preview(self):
        if not self._preview_valid():
            self._create_preview(self.PREVIEW_CAPACITY)

    def _create_preview(self, capacity):
        mod = om.MDagModifier()
        xform = mod.createNode("transform")
        mod.renameNode(xform, "unlokPathPreview")
        mod.doIt()
        knots = om.MDoubleArray([float(i) for i in range(capacity)])
        cvs = om.MPointArray([om.MPoint()] * capacity)
        shape_obj = om.MFnNurbsCurve().create(cvs, knots, 1, om.MFnNurbsCurve.kOpen, False, False, xform)
        for obj in (xform, shape_obj):
            om.MFnDependencyNode(obj).setDoNotWrite(True)  # never saved with the scene
        shape = om.MDagPath.getAPathTo(shape_obj)
        name = shape.fullPathName()
        with NoUndo():
            cmds.setAttr(om.MDagPath.getAPathTo(xform).fullPathName() + ".hiddenInOutliner", 1)
            cmds.setAttr(name + ".overrideEnabled", 1)
            cmds.setAttr(name + ".overrideRGBColors", 1)
            cmds.setAttr(name + ".overrideColorRGB", 1.0, 0.75, 0.2)
            cmds.setAttr(name + ".lineWidth", 2.5)
            if cmds.attributeQuery("alwaysDrawOnTop", node=name, exists=True):
                cmds.setAttr(name + ".alwaysDrawOnTop", 1)
        self.preview = (om.MObjectHandle(xform), shape, capacity)
        self._set_preview_visible(False)

    def _set_preview_visible(self, on):
        if self._preview_valid():
            plug = om.MFnDependencyNode(self.preview[0].object()).findPlug("visibility", False)
            if plug.asBool() != on:
                plug.setBool(on)

    def _delete_preview(self):
        if self._preview_valid():
            mod = om.MDagModifier()
            mod.deleteNode(self.preview[0].object())
            mod.doIt()
        self.preview = None


# =============================================================================
# UI building blocks
# =============================================================================

ACCENT = "#2f8f83"
ACCENT_HOVER = "#37a596"
ACTIVE = "#c9772a"

STYLE = """
#UnlokToolboxWindow QLabel[unlokTitle="true"] { font-size: 11px; font-weight: 700; letter-spacing: 2px; color: #9a9a9a; }
#UnlokToolboxWindow QLabel[unlokToolTitle="true"] { font-size: 15px; font-weight: 700; color: #f2f2f2; }
#UnlokToolboxWindow QLabel[unlokHint="true"] { color: #9a9a9a; }

#UnlokToolboxWindow QTabWidget::pane { border: none; }
#UnlokToolboxWindow QTabBar::tab {
    background: transparent; color: #9a9a9a; padding: 6px 16px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600; }
#UnlokToolboxWindow QTabBar::tab:selected { color: #f2f2f2; border-bottom: 2px solid %(accent)s; }
#UnlokToolboxWindow QTabBar::tab:hover { color: #dcdcdc; }

#UnlokToolboxWindow QFrame[unlokNext="true"] {
    background: rgba(47, 143, 131, 55); border: none; border-left: 3px solid %(accent)s; border-radius: 4px; }
#UnlokToolboxWindow QFrame[unlokNext="true"][unlokTone="warn"] {
    background: rgba(224, 176, 80, 45); border-left: 3px solid #e0b050; }
#UnlokToolboxWindow QFrame[unlokNext="true"][unlokTone="done"] {
    background: rgba(111, 191, 115, 45); border-left: 3px solid #6fbf73; }
#UnlokToolboxWindow QFrame[unlokNext="true"][unlokTone="active"] {
    background: rgba(201, 119, 42, 55); border-left: 3px solid %(active)s; }
#UnlokToolboxWindow QLabel[unlokNextTag="true"] { color: #7fd6c9; font-size: 10px; font-weight: 800; letter-spacing: 1px; }
#UnlokToolboxWindow QLabel[unlokNextTag="true"][unlokTone="warn"] { color: #f0c870; }
#UnlokToolboxWindow QLabel[unlokNextTag="true"][unlokTone="done"] { color: #9ad89d; }
#UnlokToolboxWindow QLabel[unlokNextTag="true"][unlokTone="active"] { color: #f0a560; }

#UnlokToolboxWindow QFrame[unlokStep="true"] {
    background: #4b4b4b; border: 1px solid #3a3a3a; border-radius: 6px; }
#UnlokToolboxWindow QFrame[unlokStep="true"][unlokState="current"] { border: 1px solid %(accent)s; }
#UnlokToolboxWindow QLabel[unlokBadge="true"] {
    background: #5f5f5f; color: #dddddd; border-radius: 11px; font-weight: 700; }
#UnlokToolboxWindow QLabel[unlokBadge="true"][unlokState="current"] { background: %(accent)s; color: white; }
#UnlokToolboxWindow QLabel[unlokBadge="true"][unlokState="done"] { background: #3f6b45; color: #c8f0cb; }
#UnlokToolboxWindow QLabel[unlokStepTitle="true"] { font-size: 12px; font-weight: 700; color: #e6e6e6; }
#UnlokToolboxWindow QLabel[unlokStepTitle="true"][unlokState="done"] { color: #b8b8b8; }

#UnlokToolboxWindow QToolButton[unlokSection="true"] {
    border: none; border-top: 1px solid #5a5a5a; color: #d0d0d0; font-weight: 600; padding: 6px 0px 4px 0px; }
#UnlokToolboxWindow QPushButton[unlokPrimary="true"] {
    background: %(accent)s; color: white; font-weight: 700; padding: 6px 12px; border-radius: 4px; border: none; }
#UnlokToolboxWindow QPushButton[unlokPrimary="true"]:hover { background: %(hover)s; }
#UnlokToolboxWindow QPushButton[unlokPrimary="true"]:checked { background: %(active)s; }
#UnlokToolboxWindow QPushButton[unlokPrimary="true"]:disabled { background: #5a5a5a; color: #9a9a9a; }
#UnlokToolboxWindow QPushButton[unlokSegment="true"] {
    padding: 4px 6px; border: 1px solid #333333; border-radius: 3px; background: #5d5d5d; }
#UnlokToolboxWindow QPushButton[unlokSegment="true"]:hover { background: #686868; }
#UnlokToolboxWindow QPushButton[unlokSegment="true"]:checked { background: %(accent)s; color: white; }
""" % {"accent": ACCENT, "hover": ACCENT_HOVER, "active": ACTIVE}


def maya_main_window():
    try:
        ptr = omui1.MQtUtil.mainWindow()
        if ptr:
            return wrapInstance(int(ptr), QtWidgets.QWidget)
    except Exception:
        pass
    return None


def ui_safe(fn):
    """Never let a UI callback throw into Qt; report it in the panel instead."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as exc:
            traceback.print_exc()
            try:
                self.set_status("Error: %s" % exc, level="error")
            except Exception:
                pass
    return wrapper


class _WheelGuard(object):
    """Ignore mouse-wheel on unfocused inputs so scrolling the panel never
    changes values by accident."""

    def wheelEvent(self, event):
        if self.hasFocus():
            super(_WheelGuard, self).wheelEvent(event)
        else:
            event.ignore()


class _DoubleSpin(_WheelGuard, QtWidgets.QDoubleSpinBox):
    pass


class _Spin(_WheelGuard, QtWidgets.QSpinBox):
    pass


class _Slider(_WheelGuard, QtWidgets.QSlider):
    pass


class _Combo(_WheelGuard, QtWidgets.QComboBox):
    pass


def _guard_focus(widget):
    widget.setFocusPolicy(QtCore.Qt.StrongFocus)
    return widget


class FloatField(QtWidgets.QWidget):
    """Spin box + slider. The slider covers a soft range; typing can go
    beyond it up to the hard range."""

    changed = QtCore.Signal()
    STEPS = 1000

    def __init__(self, lo, hi, soft_lo=None, soft_hi=None, decimals=3, step=0.1, parent=None):
        super(FloatField, self).__init__(parent)
        self.soft = (lo if soft_lo is None else soft_lo, hi if soft_hi is None else soft_hi)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.spin = _guard_focus(_DoubleSpin())
        self.spin.setRange(lo, hi)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setKeyboardTracking(False)
        self.spin.setFixedWidth(72)
        self.slider = _guard_focus(_Slider(QtCore.Qt.Horizontal))
        self.slider.setRange(0, self.STEPS)
        lay.addWidget(self.spin)
        lay.addWidget(self.slider, 1)
        self.spin.valueChanged.connect(self._spin_changed)
        self.slider.valueChanged.connect(self._slider_changed)

    def _to_slider(self, v):
        lo, hi = self.soft
        return int(round(clamp((v - lo) / float(hi - lo), 0.0, 1.0) * self.STEPS)) if hi > lo else 0

    def _spin_changed(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(self._to_slider(v))
        self.slider.blockSignals(False)
        self.changed.emit()

    def _slider_changed(self, i):
        lo, hi = self.soft
        self.spin.setValue(lo + (hi - lo) * i / float(self.STEPS))

    def value(self):
        return float(self.spin.value())

    def setValue(self, v):
        self.spin.blockSignals(True)
        self.slider.blockSignals(True)
        self.spin.setValue(float(v))
        self.slider.setValue(self._to_slider(float(v)))
        self.spin.blockSignals(False)
        self.slider.blockSignals(False)


class IntField(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, lo, hi, soft_lo=None, soft_hi=None, parent=None):
        super(IntField, self).__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.spin = _guard_focus(_Spin())
        self.spin.setRange(lo, hi)
        self.spin.setKeyboardTracking(False)
        self.spin.setFixedWidth(72)
        self.slider = _guard_focus(_Slider(QtCore.Qt.Horizontal))
        self.slider.setRange(lo if soft_lo is None else soft_lo, hi if soft_hi is None else soft_hi)
        lay.addWidget(self.spin)
        lay.addWidget(self.slider, 1)
        self.spin.valueChanged.connect(self._spin_changed)
        self.slider.valueChanged.connect(self.spin.setValue)

    def _spin_changed(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self.changed.emit()

    def value(self):
        return int(self.spin.value())

    def setValue(self, v):
        self.spin.blockSignals(True)
        self.slider.blockSignals(True)
        self.spin.setValue(int(v))
        self.slider.setValue(int(v))
        self.spin.blockSignals(False)
        self.slider.blockSignals(False)


class ComboField(_Combo):
    changed = QtCore.Signal()

    def __init__(self, items, parent=None):
        super(ComboField, self).__init__(parent)
        _guard_focus(self)
        self.addItems(list(items))
        self.currentIndexChanged.connect(lambda *_: self.changed.emit())

    def value(self):
        return self.currentText()

    def setValue(self, v):
        i = self.findText(str(v))
        if i >= 0:
            self.blockSignals(True)
            self.setCurrentIndex(i)
            self.blockSignals(False)


class CheckField(QtWidgets.QCheckBox):
    changed = QtCore.Signal()

    def __init__(self, text="", parent=None):
        super(CheckField, self).__init__(text, parent)
        self.toggled.connect(lambda *_: self.changed.emit())

    def value(self):
        return self.isChecked()

    def setValue(self, v):
        self.blockSignals(True)
        self.setChecked(bool(v))
        self.blockSignals(False)


class SegmentField(QtWidgets.QWidget):
    """Row of exclusive toggle buttons."""

    changed = QtCore.Signal()

    def __init__(self, items, parent=None):
        super(SegmentField, self).__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.group = QtWidgets.QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for item in items:
            btn = QtWidgets.QPushButton(item)
            btn.setCheckable(True)
            btn.setProperty("unlokSegment", True)
            self.group.addButton(btn)
            lay.addWidget(btn)
            self.buttons[item] = btn
        self.buttons[items[0]].setChecked(True)
        self.group.buttonClicked.connect(lambda *_: self.changed.emit())

    def value(self):
        btn = self.group.checkedButton()
        return btn.text() if btn else ""

    def setValue(self, v):
        btn = self.buttons.get(v)
        if btn:
            btn.setChecked(True)


class Section(QtWidgets.QWidget):
    """Collapsible block with a two-column grid (label | field)."""

    def __init__(self, title, expanded=True, parent=None, header=True):
        super(Section, self).__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = QtWidgets.QToolButton()
        self.header.setText(title)
        self.header.setProperty("unlokSection", True)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.body = QtWidgets.QWidget()
        self.grid = QtWidgets.QGridLayout(self.body)
        self.grid.setContentsMargins(4, 6, 2, 8)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(4)
        self.grid.setColumnStretch(1, 1)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self.header.toggled.connect(self._toggled)
        self._toggled(expanded)
        self._row = 0
        if not header:  # plain label | field grid inside a step card
            self.header.setVisible(False)
            self.grid.setContentsMargins(0, 0, 0, 0)

    def _toggled(self, on):
        self.header.setArrowType(QtCore.Qt.DownArrow if on else QtCore.Qt.RightArrow)
        self.body.setVisible(on)

    def add_row(self, label, widget, tip=None):
        lbl = QtWidgets.QLabel(label)
        lbl.setMinimumWidth(92)
        if tip:
            lbl.setToolTip(tip)
            widget.setToolTip(tip)
        self.grid.addWidget(lbl, self._row, 0)
        self.grid.addWidget(widget, self._row, 1)
        self._row += 1
        return lbl

    def add_full(self, widget):
        self.grid.addWidget(widget, self._row, 0, 1, 2)
        self._row += 1


def hint_label(text):
    lbl = QtWidgets.QLabel(text)
    lbl.setWordWrap(True)
    lbl.setProperty("unlokHint", True)
    return lbl


def primary_button(text, checkable=False):
    btn = QtWidgets.QPushButton(text)
    btn.setProperty("unlokPrimary", True)
    btn.setCheckable(checkable)
    return btn


def repolish(*widgets):
    """Re-apply the stylesheet after a dynamic property change."""
    for w in widgets:
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()


class ToolHeader(QtWidgets.QWidget):
    """Tool name + one line on what it's for."""

    def __init__(self, title, description, parent=None):
        super(ToolHeader, self).__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(1)
        t = QtWidgets.QLabel(title)
        t.setProperty("unlokToolTitle", True)
        d = QtWidgets.QLabel(description)
        d.setWordWrap(True)
        d.setProperty("unlokHint", True)
        lay.addWidget(t)
        lay.addWidget(d)


class NextBanner(QtWidgets.QFrame):
    """'NEXT: ...' strip that always says the one thing to do now."""

    def __init__(self, parent=None):
        super(NextBanner, self).__init__(parent)
        self.setProperty("unlokNext", True)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(8)
        self.tag = QtWidgets.QLabel("NEXT")
        self.tag.setProperty("unlokNextTag", True)
        self.tag.setMinimumWidth(64)  # bold + letter-spaced text is wider than its first size hint
        self.tag.setAlignment(QtCore.Qt.AlignTop)
        self.text = QtWidgets.QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(QtCore.Qt.RichText)
        lay.addWidget(self.tag, 0, QtCore.Qt.AlignTop)
        lay.addWidget(self.text, 1)

    def set_text(self, text, tag="NEXT", tone="next"):
        self.tag.setText(tag)
        self.text.setText(text)
        if self.property("unlokTone") != tone:
            self.setProperty("unlokTone", tone)
            self.tag.setProperty("unlokTone", tone)
            repolish(self, self.tag)


class StepCard(QtWidgets.QFrame):
    """A numbered workflow step: badge, title, one-line explanation, body.

    State: 'todo' (grey badge), 'current' (accent badge + outline) or
    'done' (tick).
    """

    def __init__(self, number, title, subtitle="", parent=None):
        super(StepCard, self).__init__(parent)
        self.number = number
        self.setProperty("unlokStep", True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 9, 10, 10)
        lay.setSpacing(7)
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(9)
        self.badge = QtWidgets.QLabel(str(number))
        self.badge.setProperty("unlokBadge", True)
        self.badge.setFixedSize(22, 22)
        self.badge.setAlignment(QtCore.Qt.AlignCenter)
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(0)
        self.title = QtWidgets.QLabel(title)
        self.title.setProperty("unlokStepTitle", True)
        titles.addWidget(self.title)
        self.subtitle = QtWidgets.QLabel(subtitle)
        self.subtitle.setWordWrap(True)
        self.subtitle.setProperty("unlokHint", True)
        self.subtitle.setVisible(bool(subtitle))
        titles.addWidget(self.subtitle)
        head.addWidget(self.badge, 0, QtCore.Qt.AlignTop)
        head.addLayout(titles, 1)
        lay.addLayout(head)
        self.body = QtWidgets.QVBoxLayout()
        self.body.setSpacing(5)
        lay.addLayout(self.body)
        self.state = None
        self.set_state("todo")

    def add(self, widget, stretch=0):
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout):
        self.body.addLayout(layout)
        return layout

    def set_state(self, state):
        if state == self.state:
            return
        self.state = state
        self.badge.setText(u"\u2713" if state == "done" else str(self.number))
        for w in (self, self.badge, self.title):
            w.setProperty("unlokState", state)
        repolish(self, self.badge, self.title)


def scroll_column():
    """A vertical scroll area for step cards; returns (scroll, layout)."""
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    body = QtWidgets.QWidget()
    body.setProperty("unlokColumn", True)
    lay = QtWidgets.QVBoxLayout(body)
    lay.setContentsMargins(6, 2, 6, 8)
    lay.setSpacing(8)
    scroll.setWidget(body)
    return scroll, lay


def button_row(*buttons):
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    for b in buttons:
        lay.addWidget(b)
    return w


def secondary_button(text, tip=None):
    b = QtWidgets.QPushButton(text)
    if tip:
        b.setToolTip(tip)
    return b


# =============================================================================
# Path Scatter - panel
# =============================================================================

class PathScatterPanel(QtWidgets.QWidget):
    TOOL_NAME = "Path Scatter"
    TOOL_TIP = "Draw a path on a surface and scatter or array objects along it."

    def __init__(self, parent=None):
        super(PathScatterPanel, self).__init__(parent)
        self.system = None
        self.fields = {}
        self.labels = {}
        self._loading = False
        self._jobs = []
        self._callbacks = []
        self._watched = None
        self._last_message = ""
        self._baked_message = ""

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self.rebuild)

        self.drawer = SurfacePathDrawer(self._on_stroke, lambda: self.fields["smoothing"].value(),
                                        PathScatterSystem.all_roots)
        if maya_main_window() is not None:
            restore_scatter_previews()
        self.drawer.on_miss = lambda: self.set_status("That stroke didn't land on anything. Drag across a mesh "
                                                      "(or start on empty grid to draw on the ground).", level="warn")
        self._build()
        self._update_enabled()
        self._install_jobs()
        self._refresh_system_label()

    # ============================================================= layout
    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(6)

        top = QtWidgets.QWidget()
        tl = QtWidgets.QVBoxLayout(top)
        tl.setContentsMargins(6, 0, 6, 0)
        tl.setSpacing(6)
        tl.addWidget(ToolHeader("Path Scatter", "Lay shingles, thatch, rocks or neat arrays along a path you "
                                                "draw on any surface. Live, no MASH."))
        self.next_banner = NextBanner()
        tl.addWidget(self.next_banner)
        outer.addWidget(top)

        scroll, col = scroll_column()
        outer.addWidget(scroll, 1)

        # ---- 1. source
        card = self.step_source = StepCard(1, "Choose what to scatter",
                                           "A built-in shape sized here, or your own meshes. "
                                           "A recipe sets everything up in one click.")
        self.recipe_combo = _guard_focus(_Combo())
        self.recipe_combo.addItems(["Start from a recipe..."] + list(RECIPES))
        self.recipe_combo.setToolTip("Roof Shingles, Messy Thatch, Rocks... sets every option, then tweak.")
        self.recipe_combo.activated.connect(lambda i: self.apply_recipe(self.recipe_combo.itemText(i)))
        card.add(self.recipe_combo)
        grid = Section("", expanded=True, header=False)
        self._add(grid, "source_type", "Shape", SegmentField(SOURCE_TYPES),
                  "A built-in shape, or 'Mesh' to scatter your own objects.")
        pick = secondary_button("Use Selected Meshes",
                                "Selected objects become the source. Several objects = random variants (rocks, etc.). "
                                "Edits to them update the scatter live.")
        pick.clicked.connect(lambda *_: self.use_selected_meshes())
        grid.add_full(pick)
        self.sources_label = hint_label("")
        grid.add_full(self.sources_label)
        self._add(grid, "size_x", "Length", FloatField(0.001, 10000, 0.01, 5), "Size along the path (preset shapes).")
        self._add(grid, "size_y", "Height", FloatField(0.001, 10000, 0.01, 5), "Size along the up axis.")
        self._add(grid, "size_z", "Width", FloatField(0.001, 10000, 0.01, 5), "Size across the path.")
        self._add(grid, "preset_sides", "Sides", IntField(3, 128, 3, 48), "Cylinder / sphere subdivisions.")
        card.add(grid)
        sec = Section("Source axes && pivot", expanded=False)
        self._add(sec, "forward_axis", "Forward axis", ComboField(AXIS_NAMES),
                  "Which axis of the source points along the path.")
        self._add(sec, "up_axis", "Up axis", ComboField(("Y", "-Y", "Z", "-Z", "X", "-X")),
                  "Which axis of the source points away from the surface.")
        self._add(sec, "pivot", "Pivot", ComboField(PIVOT_MODES),
                  "Point of each item that sits on the path. Bottom = rests on the surface.")
        card.add(sec)
        col.addWidget(card)

        # ---- 2. path
        card = self.step_path = StepCard(2, "Draw the path",
                                         "Drag across any mesh: the stroke sticks to whatever you start on.")
        self.draw_btn = primary_button("Draw Path", checkable=True)
        self.draw_btn.setMinimumHeight(30)
        self.draw_btn.setToolTip("Drag on a mesh to draw a path. Shift: straight line. Ctrl: add another path. "
                                 "Press Q (or click this again) when done.")
        self.draw_btn.clicked.connect(lambda *_: self.toggle_draw())
        card.add(self.draw_btn)
        card.add(hint_label("Shift = straight line  \u00b7  Ctrl = add another path  \u00b7  Q = finish"))
        use_btn = secondary_button("Use Selection as Path",
                                   "Use selected curve(s), or selected polygon edges (converted to a curve).")
        use_btn.clicked.connect(lambda *_: self.use_selected_path())
        surf_btn = secondary_button("Set Surface",
                                    "Selected mesh(es) become the surface to draw on, snap to and align with. "
                                    "Nothing selected = auto-detect under the cursor.")
        surf_btn.clicked.connect(lambda *_: self.use_selected_surface())
        card.add(button_row(use_btn, surf_btn))
        sys_row = QtWidgets.QHBoxLayout()
        sys_row.setSpacing(4)
        self.system_label = QtWidgets.QLabel()
        self.system_label.setProperty("unlokHint", True)
        new_btn = secondary_button("New", "Leave the current scatter as it is; the next path starts a new one.")
        new_btn.clicked.connect(lambda *_: self.new_system())
        select_btn = secondary_button("Select", "Select the scatter in the scene.")
        select_btn.clicked.connect(lambda *_: self.select_system())
        del_btn = secondary_button("Delete", "Delete the live scatter (drawn paths included).")
        del_btn.clicked.connect(lambda *_: self.delete_system())
        sys_row.addWidget(self.system_label, 1)
        for b in (new_btn, select_btn, del_btn):
            b.setFixedWidth(54)
            sys_row.addWidget(b)
        card.add_layout(sys_row)
        col.addWidget(card)

        # ---- 3. shape it
        card = self.step_shape = StepCard(3, "Shape it", "Everything updates live while you tweak.")
        sec = Section("Spacing")
        self._add(sec, "dist_mode", "Mode", ComboField(DIST_MODES),
                  "Fit to Size: end to end using each item's length (+ gap).\n"
                  "Spacing: fixed distance.\nCount: exact number spread over the path.")
        self._add(sec, "gap", "Gap", FloatField(-1000, 1000, -1, 2), "Extra space between items (Fit to Size).")
        self._add(sec, "spacing", "Spacing", FloatField(0.001, 10000, 0.01, 5), "Distance between items.")
        self._add(sec, "count", "Count", IntField(1, 100000, 1, 200), "Items per row.")
        self._add(sec, "start_offset", "Start offset", FloatField(-10000, 10000, 0, 5), "Trim / slide the start.")
        self._add(sec, "end_offset", "End offset", FloatField(-10000, 10000, 0, 5), "Trim the end.")
        card.add(sec)

        sec = Section("Rows (grid)")
        self._add(sec, "rows", "Rows", IntField(1, 1000, 1, 50), "Copies of the line side by side, e.g. shingle courses.")
        self._add(sec, "row_spacing", "Row spacing", FloatField(-10000, 10000, -2, 2),
                  "Distance between rows across the path. Negative = other side.")
        self._add(sec, "row_stagger", "Stagger", FloatField(-1, 1, 0, 1, step=0.05),
                  "Shift every other row along the path (0.5 = brick / shingle pattern).")
        self._add(sec, "row_lift", "Row lift", FloatField(-100, 100, -0.2, 0.2, step=0.01),
                  "Raise each row along the normal, so rows overlap like shingles.")
        self._add(sec, "rows_centered", "", CheckField("Center rows on path"))
        card.add(sec)

        sec = Section("Orientation", expanded=False)
        self._add(sec, "follow_path", "", CheckField("Follow path direction"))
        self._add(sec, "up_mode", "Up", ComboField(UP_MODES), "Align items to the surface normal or keep them upright.")
        self._add(sec, "snap_surface", "", CheckField("Snap to surface"))
        self._add(sec, "surface_offset", "Surface offset", FloatField(-100, 100, -1, 1, step=0.01),
                  "Push items off (or into) the surface.")
        self._add(sec, "rot_x", "Rotate X", FloatField(-360, 360, -180, 180, decimals=2, step=1), "Roll around the path.")
        self._add(sec, "rot_y", "Rotate Y", FloatField(-360, 360, -180, 180, decimals=2, step=1), "Yaw around the up axis.")
        self._add(sec, "rot_z", "Rotate Z", FloatField(-360, 360, -180, 180, decimals=2, step=1),
                  "Tilt / pitch, e.g. to angle shingles.")
        card.add(sec)

        sec = Section("Scale", expanded=False)
        self._add(sec, "scale", "Scale", FloatField(0.001, 1000, 0.01, 5))
        self._add(sec, "scale_x", "Scale X (length)", FloatField(0.001, 1000, 0.01, 5))
        self._add(sec, "scale_y", "Scale Y (up)", FloatField(0.001, 1000, 0.01, 5))
        self._add(sec, "scale_z", "Scale Z (width)", FloatField(0.001, 1000, 0.01, 5))
        card.add(sec)

        sec = Section("Randomness", expanded=False)
        seed_row = QtWidgets.QWidget()
        sl = QtWidgets.QHBoxLayout(seed_row)
        sl.setContentsMargins(0, 0, 0, 0)
        seed = IntField(0, 999999, 0, 1000)
        roll = secondary_button("Re-roll", "Try a different random arrangement.")
        roll.clicked.connect(lambda *_: self.reroll())
        sl.addWidget(seed, 1)
        sl.addWidget(roll)
        self._add(sec, "seed", "Seed", seed, "Same seed = same result.", display=seed_row)
        self._add(sec, "rand_scale_min", "Scale min", FloatField(0.001, 100, 0.1, 2, step=0.05), "Random uniform scale range.")
        self._add(sec, "rand_scale_max", "Scale max", FloatField(0.001, 100, 0.1, 2, step=0.05))
        self._add(sec, "rand_scale_axis", "Axis scale jitter", FloatField(0, 1, 0, 1, step=0.05),
                  "Extra random stretch per axis (0.2 = up to 20%).")
        self._add(sec, "rand_rot_x", "Rotate X +/-", FloatField(0, 180, 0, 180, decimals=2, step=1))
        self._add(sec, "rand_rot_y", "Rotate Y +/-", FloatField(0, 180, 0, 180, decimals=2, step=1))
        self._add(sec, "rand_rot_z", "Rotate Z +/-", FloatField(0, 180, 0, 180, decimals=2, step=1))
        self._add(sec, "rand_along", "Offset along +/-", FloatField(0, 1000, 0, 1, step=0.01))
        self._add(sec, "rand_side", "Offset side +/-", FloatField(0, 1000, 0, 1, step=0.01))
        self._add(sec, "rand_up", "Offset up +/-", FloatField(0, 1000, 0, 1, step=0.01))
        self._add(sec, "skip_chance", "Skip %", FloatField(0, 100, 0, 100, decimals=1, step=1),
                  "Randomly leave items out.")
        self._add(sec, "variant_mode", "Variants", ComboField(VARIANT_MODES),
                  "With several source meshes: pick randomly, or cycle in order.")
        card.add(sec)

        sec = Section("Drawing && limits", expanded=False)
        self._add(sec, "smoothing", "Stroke smoothing", IntField(0, 10, 0, 10), "Higher = smoother drawn curves.")
        self._add(sec, "max_items", "Max items", IntField(1, 1000000, 100, 100000),
                  "Safety cap so a tiny spacing can't hang Maya.")
        self._add(sec, "preview_boxes", "", CheckField("Preview as bounding boxes (fast for heavy meshes)"))
        card.add(sec)
        col.addWidget(card)
        col.addStretch(1)

        # ---- 4. bake (pinned, always reachable)
        card = self.step_bake = StepCard(4, "Bake", "Turn the live preview into real geometry.")
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        self._add_free("bake_mode", ComboField(BAKE_MODES))
        self.fields["bake_mode"].setToolTip("Instances: light, shares geometry with the source (slow beyond a few "
                                            "thousand).\nCopies: separate editable meshes.\n"
                                            "Combined Mesh: one merged mesh (fastest for big counts).")
        self._add_free("keep_system", CheckField("Keep live system"))
        self.fields["keep_system"].setToolTip("Hide the live scatter after baking instead of deleting it, "
                                              "so you can come back and tweak it.")
        row.addWidget(QtWidgets.QLabel("Bake as"))
        row.addWidget(self.fields["bake_mode"], 1)
        row.addWidget(self.fields["keep_system"])
        card.add_layout(row)
        self.bake_btn = primary_button("Bake")
        self.bake_btn.setMinimumHeight(30)
        self.bake_btn.clicked.connect(lambda *_: self.bake())
        card.add(self.bake_btn)
        wrap = QtWidgets.QWidget()
        wl = QtWidgets.QVBoxLayout(wrap)
        wl.setContentsMargins(6, 0, 6, 0)
        wl.addWidget(card)
        outer.addWidget(wrap)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setContentsMargins(8, 0, 8, 6)
        outer.addWidget(self.status)

        self.set_settings(PS_DEFAULTS)

    def _update_guidance(self):
        """Step badges + the NEXT banner, from the current state."""
        system = self.system if (self.system is not None and self.system.exists()) else None
        try:
            has_source = self.fields["source_type"].value() in PRESET_TYPES or bool(system and system.sources())
            has_path = bool(system and system.paths())
        except Exception:
            has_source, has_path = True, False
        count = system.last_count if system else 0
        self.step_source.set_state("done" if has_source else "current")
        self.step_path.set_state("done" if has_path else ("current" if has_source else "todo"))
        self.step_shape.set_state("done" if count else "todo")
        self.step_bake.set_state("current" if count else "todo")
        if SurfacePathDrawer.is_active():
            self.next_banner.set_text("<b>Drag across a mesh</b> to draw. Shift = straight line, Ctrl = add "
                                      "another path. Press <b>Q</b> when you're done.", tag="DRAWING", tone="active")
        elif self._baked_message and system is None:
            self.next_banner.set_text(self._baked_message, tag="DONE", tone="done")
        elif not has_source:
            self.next_banner.set_text("Select the meshes to scatter and press <b>Use Selected Meshes</b> "
                                      "(or pick a built-in shape in step 1).")
        elif not has_path:
            self.next_banner.set_text("Press <b>Draw Path</b> and drag across a mesh, or select a curve or "
                                      "edges and press <b>Use Selection as Path</b>.")
        elif not count:
            self.next_banner.set_text("Nothing fits on the path yet: lower <b>Spacing</b> / item size in step 3, "
                                      "or check the status below.", tag="CHECK", tone="warn")
        else:
            self.next_banner.set_text("Tweak <b>step 3</b> (it updates live), then press <b>Bake</b> when it "
                                      "looks right.")

    def _add(self, section, key, label, widget, tip=None, display=None):
        self.labels[key] = section.add_row(label, display or widget, tip)
        self._add_free(key, widget)

    def _add_free(self, key, widget):
        self.fields[key] = widget
        widget.changed.connect(lambda k=key: self._field_changed(k))

    # ============================================================ settings
    def settings(self):
        out = dict(PS_DEFAULTS)
        for key, widget in self.fields.items():
            out[key] = widget.value()
        return out

    def set_settings(self, values):
        self._loading = True
        try:
            for key, widget in self.fields.items():
                if key in values:
                    widget.setValue(values[key])
        finally:
            self._loading = False
        self._update_enabled()

    def _field_changed(self, key):
        if self._loading:
            return
        self._update_enabled()
        if key == "source_type":
            self._update_guidance()
        self.schedule()

    def _update_enabled(self):
        s = self.settings()
        preset = s["source_type"] in PRESET_TYPES
        mode = s["dist_mode"]
        rules = {
            "size_x": preset, "size_y": preset and s["source_type"] != "Plane", "size_z": preset,
            "preset_sides": s["source_type"] in ("Cylinder", "Sphere"),
            "gap": mode == "Fit to Size", "spacing": mode == "Spacing", "count": mode == "Count",
            "row_spacing": s["rows"] > 1, "row_stagger": s["rows"] > 1, "row_lift": s["rows"] > 1,
            "rows_centered": s["rows"] > 1, "variant_mode": s["source_type"] == "Mesh",
        }
        for key, on in rules.items():
            self.fields[key].setEnabled(on)
            if key in self.labels:
                self.labels[key].setEnabled(on)

    # ============================================================== system
    def _system(self):
        """The active system, or None if it was deleted from the scene."""
        if self.system is not None and not self.system.exists():
            self.system = None
            self._refresh_system_label()
        return self.system

    def _ensure_system(self):
        system = self._system()
        if system is None:
            self._baked_message = ""
            system = PathScatterSystem.create(self.settings())
            self.set_system(system, load_settings=False)
        return system

    def set_system(self, system, load_settings=True):
        self.system = system
        if system is not None and load_settings:
            self.set_settings(system.get_settings())
        self._refresh_system_label()
        self._watch_inputs()
        if system is not None:
            self.schedule()

    def _refresh_system_label(self):
        self._refresh_system_label_inner()
        self._update_guidance()

    def _refresh_system_label_inner(self):
        system = self.system if (self.system is not None and self.system.exists()) else None
        if system is None:
            self.system_label.setText("No active scatter")
            self.sources_label.setText("")
            self.sources_label.setVisible(False)
            self.bake_btn.setEnabled(False)
            if not self._last_message:
                self.set_status("Pick a source, then press Draw Path.")
            return
        self.system_label.setText("Active:  <b>%s</b>" % system.name())
        srcs = system.sources()
        self.sources_label.setText(
            ("Source meshes: " + ", ".join(short_name(s) for s in srcs[:6]) + (" ..." if len(srcs) > 6 else ""))
            if srcs else "No source meshes picked yet.")
        self.sources_label.setVisible(self.fields["source_type"].value() == "Mesh" or bool(srcs))
        self.bake_btn.setEnabled(True)

    # ============================================================ actions
    def schedule(self, delay=15):
        if self._system() is not None:
            self._timer.start(delay)

    @ui_safe
    def rebuild(self):
        system = self._system()
        if system is None:
            return
        if self.drawer.anchor is not None:
            # Never rebuild mid-stroke (a dense scatter can take a few hundred
            # ms and would freeze the stroke). Try again once it's finished.
            self._timer.start(100)
            return
        self._callbacks_muted = True
        try:
            count, ms, warning = system.rebuild(self.settings())
        finally:
            self._callbacks_muted = False
        self._watch_inputs()
        if warning:
            self.set_status("%d items  |  %s" % (count, warning), level="warn")
        else:
            self.set_status("%d items  |  %.0f ms" % (count, ms))
        self._update_guidance()

    @ui_safe
    def toggle_draw(self):
        if SurfacePathDrawer.is_active():
            SurfacePathDrawer.deactivate()
            self.draw_btn.setChecked(False)
            self._update_guidance()
            return
        sel = cmds.ls(selection=True, long=True, type="transform") or []
        surfaces = [n for n in sel
                    if cmds.listRelatives(n, shapes=True, type="mesh", noIntermediate=True)
                    and PathScatterSystem.from_node(n) is None]
        self.drawer.activate(surfaces)
        self.draw_btn.setChecked(True)
        self._baked_message = ""
        self._update_guidance()
        if surfaces:
            self.set_status("Drawing on %s. Q when done." % ", ".join(short_name(s) for s in surfaces))
        else:
            self.set_status("Drag on any mesh (or the grid) to draw. Q when done.")

    @ui_safe
    def _on_stroke(self, curve, surfaces, add):
        system = self._ensure_system()
        curve = system.adopt_curve(curve)
        system.set_paths([curve], add=add)
        if surfaces:
            system.set_surfaces(surfaces, add=add)
        elif not add:
            system.set_surfaces([])
        self.schedule(0)

    @ui_safe
    def use_selected_path(self):
        sel = cmds.ls(selection=True, long=True, flatten=False) or []
        edges = [s for s in sel if ".e[" in s]
        curves = []
        for node in cmds.ls(sel, long=True, objectsOnly=True) or []:
            if cmds.nodeType(node) == "nurbsCurve":
                curves.append(long_name(cmds.listRelatives(node, parent=True, fullPath=True)[0]))
            elif cmds.listRelatives(node, shapes=True, type="nurbsCurve", noIntermediate=True):
                curves.append(node)
        surfaces = []
        system = None
        if edges:
            system = self._ensure_system()
            with NoUndo(), PreserveSelection():
                cmds.select(edges, replace=True)
                made = cmds.polyToCurve(form=2, degree=3, conformToSmoothMeshPreview=0)
                curve = long_name(made[0])
                cmds.delete(curve, constructionHistory=True)
                curve = cmds.rename(curve, "unlokEdgePath1")
            curves.append(system.adopt_curve(long_name(curve)))
            surfaces = list(dict.fromkeys(cmds.ls(edges, objectsOnly=True, long=True) or []))
        if not curves:
            self.set_status("Select one or more curves, or polygon edges.", level="warn")
            return
        system = system or self._ensure_system()
        system.set_paths(curves)
        if surfaces:
            system.set_surfaces(surfaces)
        self.schedule(0)

    @ui_safe
    def use_selected_surface(self):
        sel = cmds.ls(selection=True, long=True, objectsOnly=True) or []
        meshes = []
        for node in sel:
            if cmds.nodeType(node) == "mesh" or cmds.listRelatives(node, shapes=True, type="mesh", noIntermediate=True):
                if PathScatterSystem.from_node(node) is None:
                    meshes.append(node)
        system = self._ensure_system()
        system.set_surfaces(meshes)
        self.set_status("Surface: %s" % (", ".join(short_name(m) for m in meshes) if meshes else "none (cleared)"))
        self.schedule(0)

    @ui_safe
    def use_selected_meshes(self):
        sel = cmds.ls(selection=True, long=True, objectsOnly=True, type="transform") or []
        picks = [n for n in sel if PathScatterSystem.from_node(n) is None
                 and cmds.listRelatives(n, allDescendents=True, type="mesh", fullPath=True)]
        if not picks:
            self.set_status("Select one or more mesh objects first.", level="warn")
            return
        system = self._ensure_system()
        system.set_sources(picks)
        self.fields["source_type"].setValue("Mesh")
        self._update_enabled()
        self._refresh_system_label()
        self.schedule(0)

    @ui_safe
    def apply_recipe(self, name):
        recipe = RECIPES.get(name)
        if recipe is None:
            return
        current = self.settings()
        values = dict(PS_DEFAULTS)
        values.update({k: v for k, v in recipe.items() if not k.startswith("_")})
        for key in RECIPE_KEEP:
            values[key] = current[key]
        if recipe.get("_keep_mesh") and current["source_type"] == "Mesh":
            for key in ("source_type", "forward_axis", "up_axis"):
                values[key] = current[key]
        self.set_settings(values)
        self.recipe_combo.setCurrentIndex(0)
        self.schedule(0)
        self.set_status("%s recipe loaded. %s" % (
            name, "Tweak away." if self._system() else "Now press Draw Path."))

    @ui_safe
    def reroll(self):
        self.fields["seed"].setValue(random.randint(0, 99999))
        self.schedule()

    @ui_safe
    def new_system(self):
        self.system = None
        self._last_message = ""
        self._refresh_system_label()
        self._watch_inputs()
        self.set_status("Next path starts a new scatter.")

    @ui_safe
    def select_system(self):
        system = self._system()
        if system:
            cmds.select(system.root(), replace=True)

    @ui_safe
    def delete_system(self):
        system = self._system()
        if system is None:
            return
        system.delete()
        self.system = None
        self._watch_inputs()
        self._refresh_system_label()
        self.set_status("Scatter deleted.")

    INSTANCE_WARN_COUNT = 1500

    def _confirm_instance_bake(self, count):
        """Real Maya instances get slower the more there are (quadratic, in
        Maya itself). Offer the fast modes before a long bake."""
        est = 0.9e-6 * count * count
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Bake %d instances?" % count)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText("Maya slows down a lot when creating thousands of instances.\n"
                    "This bake will take roughly %d seconds." % max(1, round(est)))
        box.setInformativeText("Copies and Combined Mesh are much faster for this many items.")
        copies = box.addButton("Bake as Copies", QtWidgets.QMessageBox.AcceptRole)
        combined = box.addButton("Bake as Combined Mesh", QtWidgets.QMessageBox.AcceptRole)
        anyway = box.addButton("Bake Instances", QtWidgets.QMessageBox.DestructiveRole)
        box.addButton(QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(copies)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is copies:
            return "Copies"
        if clicked is combined:
            return "Combined Mesh"
        if clicked is anyway:
            return "Instances"
        return None

    @ui_safe
    def bake(self):
        system = self._system()
        if system is None:
            return
        if self.fields["bake_mode"].value() == "Instances" and system.last_count > self.INSTANCE_WARN_COUNT:
            choice = self._confirm_instance_bake(system.last_count)
            if choice is None:
                return
            self.fields["bake_mode"].setValue(choice)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            t0 = time.time()
            s = self.settings()
            count = system.last_count
            result = system.bake(s)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.system = None
        self._baked_message = "Baked <b>%d</b> items as %s. Draw another path to start a new scatter." % (
            count, s["bake_mode"].lower())
        self._watch_inputs()
        self._refresh_system_label()
        if result and cmds.objExists(result):
            cmds.select(result, replace=True)
        self.set_status("Baked %d items as %s in %.1fs: %s" % (
            count, s["bake_mode"].lower(), time.time() - t0, short_name(result or "")))

    def set_status(self, text, level="info"):
        self._last_message = text
        color = {"info": "#a8a8a8", "warn": "#e0b050", "error": "#e06060"}.get(level, "#a8a8a8")
        self.status.setText('<span style="color:%s">%s</span>' % (color, text))

    # ======================================================= scene events
    def _install_jobs(self):
        if maya_main_window() is None:
            return
        self._jobs = [
            cmds.scriptJob(event=["SelectionChanged", self._on_selection_changed]),
            cmds.scriptJob(event=["ToolChanged", self._on_tool_changed]),
            cmds.scriptJob(event=["NewSceneOpened", self._on_scene_changed]),
            cmds.scriptJob(event=["SceneOpened", self._on_scene_changed]),
        ]
        _registry()["jobs"].extend(self._jobs)

    def _on_selection_changed(self):
        try:
            if SurfacePathDrawer.is_active():
                return
            for node in cmds.ls(selection=True, long=True) or []:
                system = PathScatterSystem.from_node(node)
                if system is not None:
                    if self.system is None or system.uuid != self.system.uuid:
                        self.set_system(system)
                    return
        except Exception:
            traceback.print_exc()

    def _on_tool_changed(self):
        try:
            self.draw_btn.setChecked(SurfacePathDrawer.is_active())
            self._update_guidance()
        except Exception:
            pass

    def _on_scene_changed(self):
        try:
            self.system = None
            self._watch_inputs()
            self._refresh_system_label()
            restore_scatter_previews()
        except Exception:
            traceback.print_exc()

    def _watch_inputs(self):
        """Live-update when the user edits the path curves, surfaces or
        source meshes (e.g. moving CVs)."""
        system = self.system if (self.system is not None and self.system.exists()) else None
        nodes = []
        if system is not None:
            for node in system.paths() + system.surfaces() + system.sources():
                if cmds.nodeType(node) == "transform":
                    nodes.extend(cmds.listRelatives(node, allDescendents=True, fullPath=True, noIntermediate=True) or [])
                nodes.append(node)
        key = tuple(sorted(set(nodes)))
        if key == self._watched:
            return
        self._remove_callbacks()
        self._watched = key
        for node in key:
            obj = get_mobject(node)
            if obj is None:
                continue
            try:
                cid = om.MNodeMessage.addNodeDirtyCallback(obj, self._on_input_dirty)
                self._callbacks.append(cid)
                _registry()["callbacks"].append(cid)
            except RuntimeError:
                pass

    _callbacks_muted = False

    def _on_input_dirty(self, *args):
        # Called from inside Maya's evaluation: never touch the scene here,
        # just queue a rebuild on the Qt event loop.
        if self._callbacks_muted:
            return
        if self.system is not None:
            self.system.invalidate()
        if self.drawer.anchor is not None:
            # Mid-stroke: ray casts against the surface flag it dirty, and a
            # full rebuild here would stall the stroke. The stroke's release
            # schedules its own rebuild.
            return
        try:
            self._timer.start(40)
        except Exception:
            pass

    def _remove_callbacks(self):
        reg = _registry()["callbacks"]
        for cid in self._callbacks:
            try:
                om.MMessage.removeCallback(cid)
            except Exception:
                pass
            if cid in reg:
                reg.remove(cid)
        self._callbacks = []
        self._watched = None

    def shutdown(self):
        self._timer.stop()
        self._remove_callbacks()
        reg = _registry()["jobs"]
        for job in self._jobs:
            try:
                if cmds.scriptJob(exists=job):
                    cmds.scriptJob(kill=job, force=True)
            except Exception:
                pass
            if job in reg:
                reg.remove(job)
        self._jobs = []
        try:
            SurfacePathDrawer.delete_context()
        except Exception:
            pass


# =============================================================================
# Smart UDIM - naming (UnlokRenamer convention)
# =============================================================================
# Copied from UnlokRenamer (src/unlok_renamer/ui.py) so this file stays
# self-contained. Keep these lists and helpers in sync with UnlokRenamer.

UR_MATERIALS = [
    "stone", "brick", "plastic", "metal", "wood", "bone", "paint",
    "rock", "skin", "scales", "grass", "glass", "fabric", "rubber",
    "leather", "ceramic", "concrete", "default"
]

UR_COLORS = [
    "Default", "Red", "Blue", "Green", "Yellow", "White", "Black",
    "Grey", "Gray", "Cream", "Pink", "Brown", "Orange", "Purple",
    "Tan", "Beige", "Gold", "Silver"
]

UR_SUFFIXES = [
    "GES", "GEP", "PLY",
    "GED", "GEV", "GEN", "GEC",
    "NRB", "CRV", "BLS", "GEO",
    "GRP"
]


def ur_split_material_color(material_color):
    """'paintGrey' -> ('paint', 'Grey'); (None, None) if unparseable."""
    for color in sorted(UR_COLORS, key=len, reverse=True):
        if material_color.endswith(color):
            material = material_color[:-len(color)]
            if material:
                return material, color
    return None, None


def ur_base_suffix_of(token):
    """'GEP' -> ('GEP', ''), 'GEP1' -> ('GEP', '1'), unknown -> (None, '')."""
    match = re.match(r'^([A-Za-z]+)(\d*)$', token)
    if match and match.group(1) in UR_SUFFIXES:
        return match.group(1), match.group(2)
    return None, ''


def material_key_from_name(name):
    """Material key from a convention name, plus any naming issue.

    'woodGreen_C_beam0001_GEP' -> ('woodGreen', None)
    'steelRusty_C_beam_GEP'    -> ('steelRusty', "unrecognised material/colour 'steelRusty'")
    'pCube1'                   -> (None, 'no recognised suffix (GES, GEP, ...)')

    A key with an issue is still used for grouping; a None key means the
    name can't be used, so the caller falls back to shaders.
    """
    short = name.split("|")[-1].split(":")[-1]
    parts = short.split("_")
    if len(parts) < 2:
        return None, "no recognised suffix (GES, GEP, ...)"
    base, digits = ur_base_suffix_of(parts[-1])
    if base is None:
        return None, "no recognised suffix (GES, GEP, ...)"
    if len(parts) < 3:
        return None, "missing parts (expected material_pos_desc_SUFFIX)"
    token = parts[0]
    if not re.match(r'^[a-z][A-Za-z0-9]*$', token):
        return None, "material token '%s' isn't materialColour (e.g. woodGreen)" % token
    material, _ = ur_split_material_color(token)
    if material is None and token not in UR_MATERIALS:
        return token, "unrecognised material/colour '%s'" % token
    if digits:
        return token, "suffix variant '%s' (should be '%s')" % (parts[-1], base)
    return token, None


def sanitize_key(text):
    """Turn a shader/group name into a single camelCase token for set names."""
    text = text.split("|")[-1].split(":")[-1]
    parts = [p for p in re.split(r'[^A-Za-z0-9]+', text) if p]
    if not parts:
        return "default"
    key = parts[0][:1].lower() + parts[0][1:] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
    if key[0].isdigit():
        key = "m" + key
    return key


# =============================================================================
# Smart UDIM - selection-set data model
# =============================================================================
#
#   <asset>_smartUDIM_SET            root (one per root group)
#     <section>_UDS                  section, e.g. td80_westWing_UDS
#       td100_woodGreen_c085_stack   material group: meshes and/or faces
#
# The *name* is what users edit (outside the tool too), so on every scan the
# td / stack values are read from the name and mirrored to attributes;
# coverage (c###) is tool-owned and written from the attribute. Extra
# all-digit tokens (_2, _3) only keep Maya names unique and are ignored.

UDIM_ROLE = "unlokUdimRole"
UDIM_KEY = "unlokUdimKey"
UDIM_TD = "unlokUdimTd"
UDIM_COV = "unlokUdimCov"
UDIM_STACK = "unlokUdimStack"
UDIM_ORDER = "unlokUdimOrder"
UDIM_SOURCE = "unlokUdimSource"
UDIM_GROUP = "unlokUdimGroup"

SECTION_SUFFIX = "UDS"
ROOT_SUFFIX = "smartUDIM_SET"


def parse_group_name(name):
    """Parse a section or material set name.

    'td100_woodGreen_c085_stack' -> {'key': 'woodGreen', 'td': 100.0, 'cov': 85.0, 'stack': True}
    'td80_westWing_UDS'          -> {'key': 'westWing', 'td': 80.0, 'cov': None, 'stack': False}
    'woodGreen_2'                -> {'key': 'woodGreen', 'td': None, 'cov': None, 'stack': False}
    """
    short = name.split("|")[-1].split(":")[-1]
    td = cov = None
    stack = False
    key_parts = []
    for token in short.split("_"):
        if not token:
            continue
        m_td = re.match(r'^td(\d+(?:\.\d+)?)$', token)
        m_cov = re.match(r'^c(\d+(?:\.\d+)?)$', token)
        if m_td:
            td = float(m_td.group(1))
        elif m_cov:
            cov = float(m_cov.group(1))
        elif token.lower() == "stack":
            stack = True
        elif token.isdigit() or token in (SECTION_SUFFIX, "SET", "smartUDIM"):
            continue
        else:
            key_parts.append(token)
    return {"key": "_".join(key_parts) or None, "td": td, "cov": cov, "stack": stack}


def compose_material_set_name(key, td=100.0, cov=None, stack=False):
    parts = ["td%s" % _num_token(td), key]
    if cov is not None and cov >= 0:
        parts.append("c%03d" % int(round(cov)))
    if stack:
        parts.append("stack")
    return "_".join(parts)


def compose_section_set_name(key, td=100.0):
    parts = [] if abs(td - 100.0) < 1e-6 else ["td%s" % _num_token(td)]
    return "_".join(parts + [key, SECTION_SUFFIX])


def _num_token(value):
    value = float(value)
    return str(int(round(value))) if abs(value - round(value)) < 1e-6 else ("%g" % value)


def _unique_set_name(wanted, current=None):
    """Maya names are global; add _2, _3... ourselves rather than letting Maya
    glue digits onto a value token (td100_woodGreen_c0851)."""
    if current is not None and current.split("|")[-1] == wanted:
        return wanted
    if not cmds.objExists(wanted):
        return wanted
    i = 2
    while cmds.objExists("%s_%d" % (wanted, i)) and "%s_%d" % (wanted, i) != current:
        i += 1
    return "%s_%d" % (wanted, i)


def _add_set_attrs(node, role):
    def add(ln, **kw):
        if not cmds.attributeQuery(ln, node=node, exists=True):
            cmds.addAttr(node, longName=ln, **kw)
    add(UDIM_ROLE, dataType="string")
    cmds.setAttr(node + "." + UDIM_ROLE, role, type="string")
    add(UDIM_KEY, dataType="string")
    if role in ("section", "material"):
        add(UDIM_TD, attributeType="double", defaultValue=100.0)
    if role == "material":
        add(UDIM_COV, attributeType="double", defaultValue=-1.0)
        add(UDIM_STACK, attributeType="bool", defaultValue=False)
        add(UDIM_SOURCE, dataType="string")
    if role == "section":
        add(UDIM_ORDER, attributeType="long", defaultValue=0)
    if role in ("root", "section"):
        add(UDIM_GROUP, attributeType="message")


def _base_name(node):
    """Set name without the _2 / _3 we add to keep names unique."""
    return re.sub(r'_\d+$', "", node.split("|")[-1])


def set_role(node):
    if not node or not cmds.objExists(node) or cmds.nodeType(node) != "objectSet":
        return None
    if cmds.attributeQuery(UDIM_ROLE, node=node, exists=True):
        return cmds.getAttr(node + "." + UDIM_ROLE) or None
    return None


def _get(node, attr, default=None):
    if cmds.attributeQuery(attr, node=node, exists=True):
        value = cmds.getAttr(node + "." + attr)
        return default if value is None else value
    return default


def _child_sets(node):
    return [m for m in (cmds.sets(node, q=True) or []) if cmds.nodeType(m) == "objectSet"]


def _linked_group(node):
    if not cmds.attributeQuery(UDIM_GROUP, node=node, exists=True):
        return None
    conns = cmds.listConnections(node + "." + UDIM_GROUP, source=True, destination=False) or []
    return long_name(conns[0]) if conns else None


class UndoChunk(object):
    """Group a tool action into a single Ctrl+Z step."""

    def __init__(self, name):
        self.name = name

    def __enter__(self):
        cmds.undoInfo(openChunk=True, chunkName=self.name)
        return self

    def __exit__(self, *exc):
        cmds.undoInfo(closeChunk=True)
        return False


def face_ranges(indices):
    """[0,1,2,5,7,8] -> ['f[0:2]', 'f[5]', 'f[7:8]']"""
    out = []
    idx = sorted(set(indices))
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and idx[j + 1] == idx[j] + 1:
            j += 1
        out.append("f[%d]" % idx[i] if i == j else "f[%d:%d]" % (idx[i], idx[j]))
        i = j + 1
    return out


def _parse_face_spec(comp):
    """'f[0:3]' -> [0, 1, 2, 3]; non-face components -> None."""
    m = re.match(r'^f\[(\d+)(?::(\d+))?\]$', comp)
    if not m:
        return None
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    return list(range(a, b + 1))


def expand_members(set_node):
    """{transform long name: None (whole object) or set(face indices)} for
    the mesh members of a set; plus a list of members that aren't meshes."""
    out = {}
    odd = []
    for member in cmds.ls(cmds.sets(set_node, q=True) or [], long=True) or []:
        if cmds.objExists(member) and "." not in member and cmds.nodeType(member) == "objectSet":
            continue
        node, _, comp = member.partition(".")
        if cmds.objectType(node, isAType="shape"):
            node = long_name(cmds.listRelatives(node, parent=True, fullPath=True)[0])
        if not cmds.listRelatives(node, shapes=True, type="mesh", noIntermediate=True):
            odd.append(member)
            continue
        if not comp:
            out[node] = None
            continue
        faces = _parse_face_spec(comp)
        if faces is None:
            odd.append(member)
            continue
        if out.get(node, set()) is None:
            continue  # already whole
        out.setdefault(node, set()).update(faces)
    return out, odd


def shader_face_groups(transform):
    """{shaderKey: face indices or None (all faces)} using the mesh's
    per-face shading assignment."""
    shapes = cmds.listRelatives(transform, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or []
    if not shapes:
        return {}
    dag = get_dag_path(shapes[0])
    fn = om.MFnMesh(dag)
    try:
        shaders, ids = fn.getConnectedShaders(dag.instanceNumber())
    except RuntimeError:
        return {"default": None}
    keys = []
    for i in range(len(shaders)):
        sg = om.MFnDependencyNode(shaders[i]).name()
        mats = cmds.listConnections(sg + ".surfaceShader", source=True, destination=False) or []
        keys.append(sanitize_key(mats[0] if mats else sg))
    groups = {}
    for face, sid in enumerate(ids):
        key = keys[sid] if 0 <= sid < len(keys) else "default"
        groups.setdefault(key, []).append(face)
    if len(groups) == 1:
        return {list(groups)[0]: None}
    return groups


MATERIAL_SOURCES = ("Name, then shader", "Shader only", "Name only")


class SmartUdimAsset(object):
    """One Smart UDIM setup: a root set tied to a root group of geometry."""

    def __init__(self, root_set):
        self.uuid = cmds.ls(root_set, uuid=True)[0]

    # ----------------------------------------------------------- lookups
    @classmethod
    def all(cls):
        out = []
        for node in cmds.ls(type="objectSet") or []:
            if set_role(node) == "root":
                out.append(cls(node))
        return out

    @classmethod
    def for_group(cls, group, create=True):
        group = long_name(group)
        for asset in cls.all():
            if asset.root_group() == group:
                return asset
        if not create:
            return None
        base = short_name(group)
        base = re.sub(r'_(GRP|grp)$', "", base) or base
        name = _unique_set_name("%s_%s" % (sanitize_key(base), ROOT_SUFFIX))
        root = cmds.sets(empty=True, name=name)
        _add_set_attrs(root, "root")
        cmds.connectAttr(group + ".message", root + "." + UDIM_GROUP, force=True)
        return cls(root)

    def root_set(self):
        found = cmds.ls(self.uuid) or []
        return found[0] if found else None

    def exists(self):
        return self.root_set() is not None

    def root_group(self):
        root = self.root_set()
        return _linked_group(root) if root else None

    def name(self):
        return self.root_set() or ""

    def sections(self):
        root = self.root_set()
        if not root:
            return []
        secs = [s for s in _child_sets(root) if set_role(s) in ("section", None)]
        return sorted(secs, key=lambda s: (_get(s, UDIM_ORDER, 0), s))

    def materials(self, section):
        return sorted(m for m in _child_sets(section) if set_role(m) in ("material", None))

    def all_material_sets(self):
        out = []
        for sec in self.sections():
            out.extend(self.materials(sec))
        return out

    def meshes(self):
        """(meshes, instanced): non-intermediate mesh transforms under the
        root group, and the instanced ones (skipped)."""
        group = self.root_group()
        if not group:
            return [], []
        meshes, instanced = [], []
        for shape in cmds.listRelatives(group, allDescendents=True, type="mesh", fullPath=True,
                                        noIntermediate=True) or []:
            xform = long_name(cmds.listRelatives(shape, parent=True, fullPath=True)[0])
            if len(cmds.ls(shape, allPaths=True) or []) > 1:
                if xform not in instanced:
                    instanced.append(xform)
            elif xform not in meshes:
                meshes.append(xform)
        if cmds.listRelatives(group, shapes=True, type="mesh", noIntermediate=True) and group not in meshes:
            meshes.insert(0, group)
        return meshes, instanced

    # ------------------------------------------------------------ editing
    def create_section(self, key, group=None, td=100.0):
        root = self.root_set()
        key = sanitize_key(key)
        node = cmds.sets(empty=True, name=_unique_set_name(compose_section_set_name(key, td)))
        _add_set_attrs(node, "section")
        cmds.setAttr(node + "." + UDIM_KEY, key, type="string")
        cmds.setAttr(node + "." + UDIM_TD, td)
        orders = [_get(s, UDIM_ORDER, 0) for s in self.sections()]
        cmds.setAttr(node + "." + UDIM_ORDER, (max(orders) + 1) if orders else 0)
        if group:
            cmds.connectAttr(group + ".message", node + "." + UDIM_GROUP, force=True)
        cmds.sets(node, add=root)
        return node

    def material_set(self, section, key, source="manual", create=True):
        for m in self.materials(section):
            if (_get(m, UDIM_KEY) or parse_group_name(m)["key"]) == key:
                return m
        if not create:
            return None
        node = cmds.sets(empty=True, name=_unique_set_name(compose_material_set_name(key)))
        _add_set_attrs(node, "material")
        cmds.setAttr(node + "." + UDIM_KEY, key, type="string")
        cmds.setAttr(node + "." + UDIM_SOURCE, source, type="string")
        cmds.sets(node, add=section)
        return node

    def sync_names(self):
        """Read user-editable values (td, stack) from names, mirror them to
        attributes, and normalise every name (coverage, unique suffixes)."""
        for sec in self.sections():
            if set_role(sec) is None:
                _add_set_attrs(sec, "section")
            parsed = parse_group_name(sec)
            key = parsed["key"] or _get(sec, UDIM_KEY) or "section"
            td = parsed["td"] if parsed["td"] is not None else 100.0
            cmds.setAttr(sec + "." + UDIM_KEY, key, type="string")
            cmds.setAttr(sec + "." + UDIM_TD, td)
            wanted = compose_section_set_name(key, td)
            if _base_name(sec) != wanted:
                sec = cmds.rename(sec, _unique_set_name(wanted, sec))
            for mat in self.materials(sec):
                if set_role(mat) is None:
                    _add_set_attrs(mat, "material")
                    cmds.setAttr(mat + "." + UDIM_SOURCE, "manual", type="string")
                parsed = parse_group_name(mat)
                key = parsed["key"] or _get(mat, UDIM_KEY) or "default"
                td = parsed["td"] if parsed["td"] is not None else 100.0
                cmds.setAttr(mat + "." + UDIM_KEY, key, type="string")
                cmds.setAttr(mat + "." + UDIM_TD, td)
                cmds.setAttr(mat + "." + UDIM_STACK, bool(parsed["stack"]))
                cov = _get(mat, UDIM_COV, -1.0)
                wanted = compose_material_set_name(key, td, cov if cov >= 0 else None, parsed["stack"])
                if _base_name(mat) != wanted:
                    cmds.rename(mat, _unique_set_name(wanted, mat))

    def set_group_values(self, node, td=None, stack=None):
        role = set_role(node)
        with UndoChunk("Smart UDIM edit"):
            if td is not None:
                cmds.setAttr(node + "." + UDIM_TD, float(td))
            if stack is not None and role == "material":
                cmds.setAttr(node + "." + UDIM_STACK, bool(stack))
            key = _get(node, UDIM_KEY) or parse_group_name(node)["key"]
            if role == "section":
                wanted = compose_section_set_name(key, _get(node, UDIM_TD, 100.0))
            else:
                cov = _get(node, UDIM_COV, -1.0)
                wanted = compose_material_set_name(key, _get(node, UDIM_TD, 100.0), cov if cov >= 0 else None,
                                                   _get(node, UDIM_STACK, False))
            return cmds.rename(node, _unique_set_name(wanted, node))

    def move_section(self, section, step):
        secs = self.sections()
        if section not in secs:
            return
        i = secs.index(section)
        j = clamp(i + step, 0, len(secs) - 1)
        if i == j:
            return
        secs.insert(j, secs.pop(i))
        with UndoChunk("Smart UDIM reorder"):
            for order, sec in enumerate(secs):
                cmds.setAttr(sec + "." + UDIM_ORDER, order)

    # ---------------------------------------------------------- membership
    def assignments(self):
        """{transform: [(material set, faces or None)]} over all material sets."""
        out = {}
        for mat in self.all_material_sets():
            members, _ = expand_members(mat)
            for xform, faces in members.items():
                out.setdefault(xform, []).append((mat, faces))
        return out

    def _remove_items(self, items):
        """Take meshes / faces out of every material set of this asset.
        items = {transform: faces or None}."""
        for mat in self.all_material_sets():
            members, _ = expand_members(mat)
            for xform, faces in items.items():
                if xform not in members:
                    continue
                current = members[xform]
                if faces is None:
                    if current is None:
                        shapes = cmds.listRelatives(xform, shapes=True, fullPath=True) or []
                        cmds.sets([xform] + shapes, remove=mat)
                    else:
                        cmds.sets(["%s.%s" % (xform, r) for r in face_ranges(current)], remove=mat)
                    continue
                if current is None:
                    total = cmds.polyEvaluate(xform, face=True)
                    keep = set(range(total)) - set(faces)
                    cmds.sets(xform, remove=mat)
                    if keep:
                        cmds.sets(["%s.%s" % (xform, r) for r in face_ranges(keep)], add=mat)
                else:
                    gone = set(faces) & current
                    if gone:
                        cmds.sets(["%s.%s" % (xform, r) for r in face_ranges(gone)], remove=mat)

    def assign(self, items, material_set):
        """Move meshes / faces into material_set (exclusively)."""
        with UndoChunk("Smart UDIM assign"):
            self._remove_items(items)
            self._add_items(items, material_set)

    @staticmethod
    def _add_items(items, material_set):
        whole = [x for x, f in items.items() if f is None]
        comps = []
        for x, f in items.items():
            if f is not None:
                comps.extend("%s.%s" % (x, r) for r in face_ranges(f))
        if whole:
            cmds.sets(whole, add=material_set)
        if comps:
            cmds.sets(comps, add=material_set)

    # ----------------------------------------------------------------- read
    def read(self):
        """Snapshot for the UI (no scene changes)."""
        meshes, instanced = self.meshes()
        sections = []
        for sec in self.sections():
            mats = []
            for mat in self.materials(sec):
                members, odd = expand_members(mat)
                mats.append({
                    "set": mat,
                    "key": _get(mat, UDIM_KEY) or parse_group_name(mat)["key"],
                    "td": _get(mat, UDIM_TD, parse_group_name(mat)["td"] or 100.0),
                    "cov": _get(mat, UDIM_COV, -1.0),
                    "stack": bool(_get(mat, UDIM_STACK, parse_group_name(mat)["stack"])),
                    "objects": len(members),
                    "partial": sum(1 for f in members.values() if f is not None),
                    "odd": odd,
                    "source": _get(mat, UDIM_SOURCE, "manual"),
                })
            sections.append({
                "set": sec,
                "key": _get(sec, UDIM_KEY) or parse_group_name(sec)["key"],
                "td": _get(sec, UDIM_TD, parse_group_name(sec)["td"] or 100.0),
                "group": _linked_group(sec),
                "materials": mats,
            })
        naming = []
        for xform in meshes:
            key, issue = material_key_from_name(xform)
            if issue:
                naming.append({"node": xform, "reason": issue, "usable": key is not None})
        assigned = self.assignments()
        unassigned = [m for m in meshes if m not in assigned]
        overlaps = self.overlaps(assigned)
        return {"root": self.root_set(), "group": self.root_group(), "sections": sections,
                "meshes": meshes, "instanced": instanced, "naming": naming,
                "unassigned": unassigned, "overlaps": overlaps}

    @staticmethod
    def overlaps(assigned):
        """[(transform, [sets...])] where a mesh/face is in two material sets."""
        out = []
        for xform, entries in assigned.items():
            if len(entries) < 2:
                continue
            seen = set()
            clash = False
            for _, faces in entries:
                if faces is None:
                    clash = True
                    break
                if seen & faces:
                    clash = True
                    break
                seen |= faces
            if clash:
                out.append((xform, [m for m, _ in entries]))
        return out

    # ----------------------------------------------------------------- scan
    def scan(self, material_source="Name, then shader", sections_from_groups=False):
        """Build / refresh the sets for everything under the root group.

        Existing assignments are respected; only new or unassigned
        meshes / faces get sorted into sections and material sets.
        Returns a summary dict.
        """
        group = self.root_group()
        if not group or not cmds.objExists(group):
            raise RuntimeError("The root group for %s no longer exists." % self.name())
        added = 0
        with UndoChunk("Smart UDIM scan"), PreserveSelection():
            meshes, instanced = self.meshes()
            if not self.sections():
                self._create_default_sections(group, meshes, sections_from_groups)
            assigned = self.assignments()
            sections = self.sections()
            section_groups = [(s, _linked_group(s)) for s in sections]
            batches = {}  # material set -> {transform: faces or None}
            for xform in meshes:
                current = assigned.get(xform, [])
                if any(f is None for _, f in current):
                    continue
                taken = set()
                for _, f in current:
                    taken |= f
                section = self._section_for(xform, section_groups) or sections[0]
                for key, faces, source in self._material_split(xform, material_source):
                    if faces is None and taken:
                        total = cmds.polyEvaluate(xform, face=True)
                        faces = set(range(total)) - taken
                    elif faces is not None:
                        faces = set(faces) - taken
                    if faces is not None and not faces:
                        continue
                    mat = self.material_set(section, key, source=source)
                    batches.setdefault(mat, {})[xform] = faces
                    added += 1
            for mat, items in batches.items():
                self._add_items(items, mat)
            self.sync_names()
        return {"added": added, "meshes": len(meshes), "instanced": len(instanced)}

    def _create_default_sections(self, group, meshes, from_groups):
        if from_groups:
            children = cmds.listRelatives(group, children=True, type="transform", fullPath=True) or []
            # Only groups become sections; meshes sitting directly under the
            # root go to a section named after the root.
            children = [c for c in children if not cmds.listRelatives(c, shapes=True)]
            made = 0
            for child in children:
                if any(m.startswith(child + "|") for m in meshes):
                    base = re.sub(r'_\d*_?(GRP|grp)$', "", short_name(child)) or short_name(child)
                    self.create_section(base, group=child)
                    made += 1
            loose = [m for m in meshes if not any(m.startswith(c + "|") for c in children)]
            if made and not loose:
                return
        base = re.sub(r'_\d*_?(GRP|grp)$', "", short_name(group)) or short_name(group)
        self.create_section(base, group=group)

    @staticmethod
    def _section_for(xform, section_groups):
        best, depth = None, -1
        for sec, grp in section_groups:
            if grp and (xform == grp or xform.startswith(grp + "|")) and grp.count("|") > depth:
                best, depth = sec, grp.count("|")
        return best

    @staticmethod
    def _material_split(xform, material_source):
        """[(key, faces or None, source)] for one mesh."""
        if material_source != "Shader only":
            key, _ = material_key_from_name(xform)
            if key:
                return [(key, None, "name")]
            if material_source == "Name only":
                return [("default", None, "name")]
        return [(k, f, "shader") for k, f in shader_face_groups(xform).items()]


# =============================================================================
# Smart UDIM - pre-process
# =============================================================================

def _cleanup_args(lamina, nonmanifold, zero_area, select_only=False):
    """Arguments for Maya's polyCleanupArgList (version 4)."""
    return [
        "0",                         # [0] all meshes: no, use selection
        # [1] operation. The script's header says "select only (0/1)", but its
        # code treats 1 as "clean up" and 2 as "select matching only".
        "2" if select_only else "1",
        "1",                         # [2] keep construction history
        "0", "0", "0", "0", "0",     # [3-7] no triangulation of any kind
        "1" if zero_area else "0",   # [8] zero-area faces
        "1e-05",                     # [9] face area tolerance
        "0", "1e-05",                # [10-11] zero-length edges: off
        "0", "1e-05",                # [12-13] zero UV area: off
        "0",                         # [14] unshare UVs: off
        "2" if nonmanifold else "-1",  # [15] non-manifold, without conforming normals
        "1" if lamina else "0",      # [16] lamina faces
        "0",                         # [17] invalid components: off
    ]


def _run_cleanup(meshes, lamina, nonmanifold, zero_area, select_only=False):
    if not meshes:
        return []
    cmds.select(meshes, replace=True)
    args = _cleanup_args(lamina, nonmanifold, zero_area, select_only)
    mel.eval('polyCleanupArgList 4 {%s}' % ",".join('"%s"' % a for a in args))
    return cmds.ls(selection=True, long=True, flatten=False) or []


def _faces_by_mesh(components):
    """Group selected components by mesh transform -> count of faces."""
    out = {}
    for comp in components:
        node, _, spec = comp.partition(".")
        if not spec.startswith("f["):
            continue  # nothing found leaves whole meshes selected
        if cmds.objectType(node, isAType="shape"):
            node = long_name(cmds.listRelatives(node, parent=True, fullPath=True)[0])
        faces = _parse_face_spec(spec) if spec else None
        out[node] = out.get(node, 0) + (len(faces) if faces else 1)
    return out


def detect_geometry_issues(meshes):
    """{category: {transform: count}} for lamina, non-manifold, zero-area, n-gons."""
    issues = {"lamina": {}, "nonmanifold": {}, "zeroarea": {}, "ngons": {}}
    for xform in meshes:
        lam = cmds.polyInfo(xform, laminaFaces=True) or []
        if lam:
            issues["lamina"][xform] = len(cmds.ls(lam, flatten=True))
        nm = (cmds.polyInfo(xform, nonManifoldVertices=True) or []) + \
             (cmds.polyInfo(xform, nonManifoldEdges=True) or [])
        if nm:
            issues["nonmanifold"][xform] = len(cmds.ls(nm, flatten=True))
        shapes = cmds.listRelatives(xform, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or []
        if shapes:
            counts, _ = om.MFnMesh(get_dag_path(shapes[0])).getVertices()
            ngons = sum(1 for c in counts if c > 4)
            if ngons:
                issues["ngons"][xform] = ngons
    with PreserveSelection():
        zero = _run_cleanup(meshes, False, False, True, select_only=True)
    issues["zeroarea"] = {k: v for k, v in _faces_by_mesh(zero).items() if k in meshes}
    return issues


def detect_uv_issues(meshes, uv_set="map1"):
    """{category: {transform: count}} for missing UVs, faces without UVs and
    flipped UV faces. Meshes with missing UVs get skipped by layout."""
    issues = {"no_uvs": {}, "faces_without_uvs": {}, "flipped": {}, "no_uv_set": {}}
    for xform in meshes:
        shapes = cmds.listRelatives(xform, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or []
        if not shapes:
            continue
        fn = om.MFnMesh(get_dag_path(shapes[0]))
        if uv_set not in fn.getUVSetNames():
            issues["no_uv_set"][xform] = 1
            continue
        if fn.numUVs(uv_set) == 0:
            issues["no_uvs"][xform] = fn.numPolygons
            continue
        counts, ids = fn.getAssignedUVs(uv_set)
        missing = sum(1 for c in counts if c == 0)
        if missing:
            issues["faces_without_uvs"][xform] = missing
        us, vs = fn.getUVs(uv_set)
        flipped = 0
        k = 0
        for c in counts:
            if c >= 3:
                area = 0.0
                for i in range(c):
                    a = ids[k + i]
                    b = ids[k + (i + 1) % c]
                    area += us[a] * vs[b] - us[b] * vs[a]
                if area < -1e-12:
                    flipped += 1
            k += c
        if flipped:
            issues["flipped"][xform] = flipped
    return issues


PREPROCESS_LABELS = {
    "lamina": ("Lamina faces", "fixed"),
    "nonmanifold": ("Non-manifold geometry", "fixed"),
    "zeroarea": ("Zero-area faces", "fixed"),
    "ngons": ("N-gons (left as they are)", "warn"),
    "no_uv_set": ("Missing UV set (skipped)", "skip"),
    "no_uvs": ("No UVs (skipped)", "skip"),
    "faces_without_uvs": ("Faces without UVs (skipped)", "skip"),
    "flipped": ("Flipped UV faces", "warn"),
    "instanced": ("Instanced meshes (skipped)", "skip"),
    "remaining": ("Couldn't be fixed automatically", "warn"),
}


def preprocess(meshes, instanced=(), fix_lamina=True, fix_nonmanifold=True, fix_zero_area=True, uv_set="map1"):
    """Clean the geometry layout cares about and report UV problems.

    Returns {category: {transform: count}}. Everything it does (including
    the selection juggling Maya's cleanup needs) is one Ctrl+Z.
    """
    with UndoChunk("Smart UDIM pre-process"), PreserveSelection():
        return _preprocess(meshes, instanced, fix_lamina, fix_nonmanifold, fix_zero_area, uv_set)


def _preprocess(meshes, instanced, fix_lamina, fix_nonmanifold, fix_zero_area, uv_set):
    report = {}
    before = detect_geometry_issues(meshes)
    to_fix = set()
    for cat, on in (("lamina", fix_lamina), ("nonmanifold", fix_nonmanifold), ("zeroarea", fix_zero_area)):
        if on and before[cat]:
            report[cat] = dict(before[cat])
            to_fix.update(before[cat])
    if to_fix:
        _run_cleanup(sorted(to_fix), fix_lamina, fix_nonmanifold, fix_zero_area)
        after = detect_geometry_issues(sorted(to_fix))
        remaining = {}
        for cat, on in (("lamina", fix_lamina), ("nonmanifold", fix_nonmanifold), ("zeroarea", fix_zero_area)):
            if on:
                for xform, n in after[cat].items():
                    remaining[xform] = remaining.get(xform, 0) + n
        if remaining:
            report["remaining"] = remaining
    if before["ngons"]:
        report["ngons"] = before["ngons"]
    for cat, items in detect_uv_issues(meshes, uv_set).items():
        if items:
            report[cat] = items
    if instanced:
        report["instanced"] = {x: 1 for x in instanced}
    return report


def skipped_meshes(report):
    out = set()
    for cat in ("no_uv_set", "no_uvs", "faces_without_uvs", "instanced"):
        out.update(report.get(cat, {}))
    return out


# =============================================================================
# Smart UDIM - panel
# =============================================================================

def selection_items():
    """Current scene selection as {mesh transform: None (whole) or face set}."""
    items = {}
    sel = cmds.ls(selection=True, long=True, flatten=False) or []
    comps = [s for s in sel if "." in s]
    for node in [s for s in sel if "." not in s]:
        if cmds.objectType(node, isAType="shape"):
            node = long_name(cmds.listRelatives(node, parent=True, fullPath=True)[0])
        if cmds.listRelatives(node, shapes=True, type="mesh", noIntermediate=True):
            items[node] = None
    if comps:
        for face in cmds.ls(cmds.polyListComponentConversion(comps, toFace=True) or [], long=True) or []:
            node, _, spec = face.partition(".")
            if cmds.objectType(node, isAType="shape"):
                node = long_name(cmds.listRelatives(node, parent=True, fullPath=True)[0])
            faces = _parse_face_spec(spec)
            if faces is None or items.get(node, set()) is None:
                continue
            items.setdefault(node, set()).update(faces)
    return items


def _unlok_renamer_available():
    try:
        import importlib.util
        return importlib.util.find_spec("unlok_renamer") is not None
    except Exception:
        return False


LEVEL_COLORS = {"fixed": "#6fbf73", "warn": "#e0b050", "skip": "#e07a5f", "info": "#a8a8a8"}


class SmartUdimPanel(QtWidgets.QWidget):
    TOOL_NAME = "Smart UDIM"
    TOOL_TIP = "Organise geometry into UDIM sections and material groups, clean it and check its UVs."

    COL_NAME, COL_TD, COL_COV, COL_ITEMS, COL_STACK = range(5)

    def __init__(self, parent=None):
        super(SmartUdimPanel, self).__init__(parent)
        self.asset = None
        self.snapshot = None
        self.report = {}
        self._jobs = []
        self._populating = False
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(60)
        self._refresh_timer.timeout.connect(self.refresh)
        self._build()
        self._install_jobs()
        assets = SmartUdimAsset.all() if maya_main_window() is not None else []
        if len(assets) == 1:
            self.set_asset(assets[0])
        else:
            self.refresh()

    # ============================================================== layout
    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(6)

        top = QtWidgets.QWidget()
        tl = QtWidgets.QVBoxLayout(top)
        tl.setContentsMargins(6, 0, 6, 0)
        tl.setSpacing(6)
        tl.addWidget(ToolHeader("Smart UDIM", "Sort an asset into UDIM sections and material groups, clean it, "
                                              "and get it ready for layout."))
        self.next_banner = NextBanner()
        tl.addWidget(self.next_banner)
        outer.addWidget(top)

        scroll, col = scroll_column()
        outer.addWidget(scroll, 1)

        # ---- 1. asset
        card = self.step_root = StepCard(1, "Pick the asset", "Select the asset's top group, e.g. house_GRP.")
        row = QtWidgets.QHBoxLayout()
        self.root_label = QtWidgets.QLabel()
        self.root_label.setWordWrap(True)
        pick = secondary_button("Use Selected Group", "Select the top group of the asset, then press this.")
        pick.clicked.connect(lambda *_: self.pick_root())
        row.addWidget(self.root_label, 1)
        row.addWidget(pick)
        card.add_layout(row)
        col.addWidget(card)

        # ---- 2. scan
        card = self.step_scan = StepCard(2, "Scan", "Sorts every mesh into sections (rows of UDIMs) and material "
                                                    "groups. Re-scanning only sorts new meshes.")
        grid = Section("", header=False)
        self.source_combo = ComboField(MATERIAL_SOURCES)
        self.source_combo.setToolTip("Where material groups come from for meshes that aren't in a group yet.\n"
                                     "Name: the UnlokRenamer convention (woodGreen_C_beam0001_GEP).\n"
                                     "Shader: the Maya material assigned to each face.")
        grid.add_row("Materials from", self.source_combo)
        self.from_groups = CheckField("New sections from top-level groups")
        self.from_groups.setToolTip("On the first scan, each child group of the root (e.g. westWing_GRP) "
                                    "becomes its own section / row of UDIMs.")
        grid.add_full(self.from_groups)
        card.add(grid)
        self.scan_btn = primary_button("Scan")
        self.scan_btn.setMinimumHeight(28)
        self.scan_btn.setToolTip("Sort every mesh under the root into sections and material groups. "
                                 "Existing groups are kept; only new meshes get sorted. One Ctrl+Z undoes it.")
        self.scan_btn.clicked.connect(lambda *_: self.scan())
        card.add(self.scan_btn)
        col.addWidget(card)

        # ---- 3. organise
        card = self.step_groups = StepCard(3, "Organise groups",
                                           "Double-click TD % to change texel density, tick Stack for repeated "
                                           "pieces. They're plain Maya sets, so renaming works too.")
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Group", "TD %", "Cover", "Items", "Stack"])
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setMinimumHeight(220)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(self.COL_NAME, QtWidgets.QHeaderView.Stretch)
        for c in (self.COL_TD, self.COL_COV, self.COL_ITEMS, self.COL_STACK):
            header.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemDoubleClicked.connect(self._item_double_clicked)
        card.add(self.tree)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(3)
        buttons = [
            ("Select", "Select the meshes / faces in the highlighted groups.", self.select_members),
            ("Assign Selection", "Move the selected meshes / faces into the highlighted material group.",
             self.assign_selection),
            ("New Group", "Make a material group in the highlighted section from the selected meshes / faces.",
             self.new_group),
            ("New Section", "Make a new section (row of UDIMs); selected meshes move into it.", self.new_section),
            ("Move Up", "Lay this section out earlier (lower rows).", lambda: self.move_section(-1)),
            ("Move Down", "Lay this section out later (higher rows).", lambda: self.move_section(1)),
        ]
        for i, (text, tip, fn) in enumerate(buttons):
            b = secondary_button(text, tip)
            b.clicked.connect(lambda *_, f=fn: f())
            grid.addWidget(b, i // 3, i % 3)
        card.add_layout(grid)
        self.tree_hint = hint_label("")
        card.add(self.tree_hint)
        col.addWidget(card)

        # ---- 4. names
        card = self.naming_section = StepCard(4, "Fix names", "Meshes whose names break the UnlokRenamer "
                                                              "convention. Fix them there, then Scan again.")
        self.naming_list = QtWidgets.QTreeWidget()
        self.naming_list.setColumnCount(2)
        self.naming_list.setHeaderLabels(["Mesh", "Problem"])
        self.naming_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.naming_list.setMinimumHeight(110)
        self.naming_list.setAlternatingRowColors(True)
        self.naming_list.itemSelectionChanged.connect(self._naming_selected)
        card.add(self.naming_list)
        sel_all = secondary_button("Select All", "Select every mesh listed.")
        sel_all.clicked.connect(lambda *_: self._select_nodes(
            [n["node"] for n in (self.snapshot or {}).get("naming", [])]))
        self.renamer_btn = secondary_button("Open UnlokRenamer")
        self.renamer_btn.clicked.connect(lambda *_: self.open_renamer())
        card.add(button_row(sel_all, self.renamer_btn))
        col.addWidget(card)

        # ---- 5. pre-process
        card = self.step_prep = StepCard(5, "Pre-process", "Fixes geometry that breaks layout and checks UVs. "
                                                           "N-gons are only reported. One Ctrl+Z undoes it.")
        grid = Section("", header=False)
        self.fix_lamina = CheckField("Fix lamina faces")
        self.fix_nonmanifold = CheckField("Fix non-manifold geometry")
        self.fix_zero = CheckField("Remove zero-area faces")
        for w in (self.fix_lamina, self.fix_nonmanifold, self.fix_zero):
            w.setValue(True)
            grid.add_full(w)
        self.uv_set = QtWidgets.QLineEdit("map1")
        self.uv_set.setToolTip("UV set to check (and later lay out from).")
        grid.add_row("UV set", self.uv_set)
        card.add(grid)
        run = primary_button("Run Pre-process")
        run.setMinimumHeight(28)
        run.clicked.connect(lambda *_: self.run_preprocess())
        card.add(run)
        self.report_tree = QtWidgets.QTreeWidget()
        self.report_tree.setColumnCount(2)
        self.report_tree.setHeaderLabels(["Check", "Count"])
        self.report_tree.setMinimumHeight(130)
        self.report_tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.report_tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.report_tree.header().setStretchLastSection(False)
        self.report_tree.itemSelectionChanged.connect(self._report_selected)
        card.add(self.report_tree)
        col.addWidget(card)

        # ---- 6. layout (next milestone)
        card = self.step_layout = StepCard(6, "Lay out UDIMs", "Texel density, packing by material, one band of "
                                                               "rows per section and a UDIM map. Coming next.")
        soon = primary_button("Lay Out UDIMs (coming soon)")
        soon.setEnabled(False)
        card.add(soon)
        col.addWidget(card)
        col.addStretch(1)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setContentsMargins(8, 0, 8, 6)
        outer.addWidget(self.status)

    def _update_guidance(self):
        snap = self.snapshot
        asset = self._asset()
        has_root = bool(asset is not None and snap)
        scanned = has_root and bool(snap["sections"])
        sorted_ok = scanned and not snap["unassigned"]
        clean_groups = sorted_ok and not snap["overlaps"]
        names_ok = has_root and not snap["naming"]
        skipped = skipped_meshes(self.report) if self.report else set()
        prepped = bool(self.report) and not skipped
        self.step_root.set_state("done" if has_root else "current")
        self.step_scan.set_state("done" if sorted_ok else ("current" if has_root else "todo"))
        self.step_groups.set_state("done" if clean_groups else "todo")
        self.naming_section.set_state("done" if names_ok else "todo")
        self.step_prep.set_state("done" if prepped else ("current" if clean_groups else "todo"))
        self.step_layout.set_state("todo")
        if not has_root:
            self.next_banner.set_text("Select the asset's top group (e.g. <b>house_GRP</b>) and press "
                                      "<b>Use Selected Group</b>.")
        elif not scanned:
            self.next_banner.set_text("Press <b>Scan</b> to sort its meshes into sections and material groups.")
        elif snap["unassigned"]:
            self.next_banner.set_text("%d new mesh(es) aren't in a group yet. Press <b>Scan</b> again." %
                                      len(snap["unassigned"]))
        elif snap["overlaps"]:
            self.next_banner.set_text("%d mesh(es) are in two groups. Highlight the right group and press "
                                      "<b>Assign Selection</b>." % len(snap["overlaps"]), tag="CHECK", tone="warn")
        elif not self.report:
            self.next_banner.set_text("Check the groups in step 3 (TD %, Stack), then press <b>Run "
                                      "Pre-process</b>.")
        elif skipped:
            self.next_banner.set_text("%d mesh(es) will be skipped (no UVs / instanced). Fix them and run "
                                      "<b>Pre-process</b> again, or carry on without them." % len(skipped),
                                      tag="CHECK", tone="warn")
        else:
            self.next_banner.set_text("Ready for layout. UDIM layout (step 6) arrives in the next update.",
                                      tag="READY", tone="done")

    # ============================================================ state
    def set_status(self, text, level="info"):
        color = LEVEL_COLORS.get(level, "#a8a8a8") if level != "error" else "#e06060"
        self.status.setText('<span style="color:%s">%s</span>' % (color, text))

    def _asset(self):
        if self.asset is not None and not self.asset.exists():
            self.asset = None
        return self.asset

    def set_asset(self, asset):
        self.asset = asset
        self.report = {}
        self._fill_report()
        self.refresh()

    @ui_safe
    def refresh(self):
        asset = self._asset()
        if asset is None or not asset.root_group():
            self.snapshot = None
            self.root_label.setText('<span style="color:#8c8c8c">Pick the asset\'s top group</span>')
            self._fill_tree()
            self._fill_naming()
            if not self.status.text():
                self.set_status("Select the asset's top group and press 'Use Selected Group'.")
            return
        self.snapshot = asset.read()
        self.root_label.setText("<b>%s</b> &nbsp;<span style='color:#8c8c8c'>(%s)</span>" % (
            short_name(self.snapshot["group"]), asset.name()))
        self._fill_tree()
        self._fill_naming()

    # ============================================================ trees
    def _fill_tree(self):
        self._populating = True
        try:
            expanded = set()
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                if it.isExpanded():
                    expanded.add(it.data(0, QtCore.Qt.UserRole))
            self.tree.clear()
            snap = self.snapshot
            if not snap:
                self.tree_hint.setText("")
                return
            bold = QtGui.QFont()
            bold.setBold(True)
            for sec in snap["sections"]:
                total = sum(m["objects"] for m in sec["materials"])
                sitem = QtWidgets.QTreeWidgetItem([sec["key"], _num_token(sec["td"]), "", str(total), ""])
                sitem.setData(0, QtCore.Qt.UserRole, sec["set"])
                sitem.setToolTip(0, "%s\nSection: becomes its own band of UDIM rows%s" % (
                    sec["set"], ("\nGroup: " + short_name(sec["group"])) if sec["group"] else ""))
                sitem.setFont(0, bold)
                sitem.setFlags(sitem.flags() | QtCore.Qt.ItemIsEditable)
                self.tree.addTopLevelItem(sitem)
                for mat in sec["materials"]:
                    items = str(mat["objects"]) + (" (%d partial)" % mat["partial"] if mat["partial"] else "")
                    cov = "%d%%" % round(mat["cov"]) if mat["cov"] >= 0 else "-"
                    mitem = QtWidgets.QTreeWidgetItem([mat["key"], _num_token(mat["td"]), cov, items, ""])
                    mitem.setData(0, QtCore.Qt.UserRole, mat["set"])
                    mitem.setToolTip(0, "%s\nfrom %s" % (mat["set"], mat["source"]))
                    mitem.setFlags(mitem.flags() | QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsUserCheckable)
                    mitem.setCheckState(self.COL_STACK, QtCore.Qt.Checked if mat["stack"] else QtCore.Qt.Unchecked)
                    if mat["odd"]:
                        mitem.setForeground(self.COL_ITEMS, QtGui.QBrush(QtGui.QColor(LEVEL_COLORS["warn"])))
                        mitem.setToolTip(self.COL_ITEMS, "Has non-face members that layout ignores: %s" %
                                         ", ".join(mat["odd"][:5]))
                    sitem.addChild(mitem)
                sitem.setExpanded(not expanded or sec["set"] in expanded)
            notes = []
            if snap["unassigned"]:
                notes.append("%d mesh(es) not in any group yet; press Scan." % len(snap["unassigned"]))
            if snap["overlaps"]:
                notes.append("%d mesh(es) are in more than one group: %s" % (
                    len(snap["overlaps"]), ", ".join(short_name(x) for x, _ in snap["overlaps"][:4])))
            if snap["instanced"]:
                notes.append("%d instanced mesh(es) skipped." % len(snap["instanced"]))
            self.tree_hint.setText("  ".join(notes))
        finally:
            self._populating = False

    def _fill_naming(self):
        self.naming_list.clear()
        naming = (self.snapshot or {}).get("naming", [])
        for entry in naming:
            item = QtWidgets.QTreeWidgetItem([short_name(entry["node"]), entry["reason"]])
            item.setData(0, QtCore.Qt.UserRole, entry["node"])
            item.setToolTip(0, entry["node"])
            color = LEVEL_COLORS["warn"] if entry["usable"] else LEVEL_COLORS["skip"]
            item.setForeground(1, QtGui.QBrush(QtGui.QColor(color)))
            self.naming_list.addTopLevelItem(item)
        self.naming_section.title.setText("Fix names%s" % (
            "  (%d)" % len(naming) if naming else ""))
        available = _unlok_renamer_available()
        self.renamer_btn.setEnabled(available)
        self.renamer_btn.setToolTip("Open UnlokRenamer to fix these names." if available else
                                    "UnlokRenamer isn't loaded in this Maya session.")
        self._update_guidance()

    def _fill_report(self):
        self.report_tree.clear()
        for cat, items in sorted(self.report.items(), key=lambda kv: list(PREPROCESS_LABELS).index(kv[0])
                                 if kv[0] in PREPROCESS_LABELS else 99):
            label, level = PREPROCESS_LABELS.get(cat, (cat, "info"))
            top = QtWidgets.QTreeWidgetItem([label, str(sum(items.values()))])
            top.setForeground(0, QtGui.QBrush(QtGui.QColor(LEVEL_COLORS[level])))
            top.setData(0, QtCore.Qt.UserRole, list(items))
            for node, count in sorted(items.items()):
                child = QtWidgets.QTreeWidgetItem([short_name(node), str(count)])
                child.setData(0, QtCore.Qt.UserRole, [node])
                child.setToolTip(0, node)
                top.addChild(child)
            self.report_tree.addTopLevelItem(top)

    def _selected_sets(self):
        return [it.data(0, QtCore.Qt.UserRole) for it in self.tree.selectedItems()]

    def _selected_role(self, role):
        return [s for s in self._selected_sets() if s and cmds.objExists(s) and set_role(s) == role]

    # ======================================================== edits
    def _item_changed(self, item, column):
        if self._populating:
            return
        self._apply_item_edit(item, column)

    @ui_safe
    def _apply_item_edit(self, item, column):
        asset = self._asset()
        node = item.data(0, QtCore.Qt.UserRole)
        if asset is None or not node or not cmds.objExists(node):
            return
        if column == self.COL_TD:
            try:
                td = float(item.text(self.COL_TD).replace("%", "").strip())
            except ValueError:
                self.set_status("TD % must be a number, e.g. 150.", level="warn")
                self._refresh_timer.start()
                return
            if td <= 0:
                self.set_status("TD % must be above 0.", level="warn")
                self._refresh_timer.start()
                return
            asset.set_group_values(node, td=td)
        elif column == self.COL_STACK and set_role(node) == "material":
            asset.set_group_values(node, stack=item.checkState(self.COL_STACK) == QtCore.Qt.Checked)
        elif column == self.COL_NAME:
            key = sanitize_key(item.text(self.COL_NAME))
            cmds.setAttr(node + "." + UDIM_KEY, key, type="string")
            with UndoChunk("Smart UDIM rename"):
                renamed = cmds.rename(node, _unique_set_name(
                    compose_section_set_name(key, _get(node, UDIM_TD, 100.0)) if set_role(node) == "section"
                    else compose_material_set_name(key, _get(node, UDIM_TD, 100.0),
                                                   _get(node, UDIM_COV, -1.0) if _get(node, UDIM_COV, -1.0) >= 0
                                                   else None, _get(node, UDIM_STACK, False)), node))
            self.set_status("Renamed to %s" % renamed)
        self._refresh_timer.start()

    def _item_double_clicked(self, item, column):
        if column in (self.COL_TD, self.COL_NAME):
            self.tree.editItem(item, column)

    # ======================================================== actions
    @ui_safe
    def pick_root(self):
        sel = cmds.ls(selection=True, long=True, type="transform") or []
        if len(sel) != 1:
            self.set_status("Select exactly one group (the asset's top group).", level="warn")
            return
        if not cmds.listRelatives(sel[0], allDescendents=True, type="mesh"):
            self.set_status("%s has no meshes under it." % short_name(sel[0]), level="warn")
            return
        with UndoChunk("Smart UDIM root"):
            asset = SmartUdimAsset.for_group(sel[0])
        self.set_asset(asset)
        self.set_status("Root set to %s. Press Scan to sort its meshes into groups." % short_name(sel[0]))

    @ui_safe
    def scan(self):
        asset = self._asset()
        if asset is None:
            self.set_status("Pick a root group first.", level="warn")
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            t0 = time.time()
            result = asset.scan(self.source_combo.value(), self.from_groups.value())
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.refresh()
        naming = len(self.snapshot["naming"]) if self.snapshot else 0
        self.set_status("Scanned %d meshes in %.2fs: %d newly grouped%s." % (
            result["meshes"], time.time() - t0, result["added"],
            (", %d naming issue(s) (see below)" % naming) if naming else ""))

    @ui_safe
    def select_members(self):
        members = []
        for s in self._selected_sets():
            if s and cmds.objExists(s):
                if set_role(s) == "section":
                    for m in self._asset().materials(s):
                        members.extend(cmds.sets(m, q=True) or [])
                else:
                    members.extend(cmds.sets(s, q=True) or [])
        members = [m for m in members if cmds.objExists(m) and cmds.nodeType(m.split(".")[0]) != "objectSet"]
        if members:
            cmds.select(members, replace=True)
        else:
            cmds.select(clear=True)
        self.set_status("Selected %d item(s)." % len(members))

    @ui_safe
    def assign_selection(self):
        asset = self._asset()
        targets = self._selected_role("material")
        if asset is None or len(targets) != 1:
            self.set_status("Highlight one material group in the list first.", level="warn")
            return
        items = self._items_in_root(selection_items())
        if not items:
            self.set_status("Select meshes or faces (under the root) to assign.", level="warn")
            return
        asset.assign(items, targets[0])
        self.refresh()
        self.set_status("Moved %d mesh(es) into %s." % (len(items), targets[0]))

    @ui_safe
    def new_group(self):
        asset = self._asset()
        if asset is None:
            return
        sections = self._selected_role("section") or [
            p for p in (self._parent_section(s) for s in self._selected_role("material")) if p]
        if not sections:
            secs = asset.sections()
            if len(secs) != 1:
                self.set_status("Highlight the section the new group belongs to.", level="warn")
                return
            sections = secs
        items = self._items_in_root(selection_items())
        default = "newMaterial"
        if items:
            key, _ = material_key_from_name(list(items)[0])
            default = key or default
        key, ok = QtWidgets.QInputDialog.getText(self, "New material group", "Material name (e.g. woodGreen):",
                                                 text=default)
        if not ok or not key.strip():
            return
        key = sanitize_key(key)
        with UndoChunk("Smart UDIM new group"):
            mat = asset.material_set(sections[0], key, source="manual")
            if items:
                asset._remove_items(items)
                asset._add_items(items, mat)
        self.refresh()
        self.set_status("Group %s ready%s." % (mat, (" with %d mesh(es)" % len(items)) if items else ""))

    @ui_safe
    def new_section(self):
        asset = self._asset()
        if asset is None:
            return
        key, ok = QtWidgets.QInputDialog.getText(self, "New section", "Section name (e.g. westWing):")
        if not ok or not key.strip():
            return
        items = self._items_in_root(selection_items())
        with UndoChunk("Smart UDIM new section"):
            sec = asset.create_section(key)
            if items:
                asset._remove_items(items)
                batches = {}
                for xform, faces in items.items():
                    for mkey, mfaces, source in asset._material_split(xform, self.source_combo.value()):
                        if faces is not None:
                            mfaces = set(faces) if mfaces is None else (set(mfaces) & set(faces))
                            if not mfaces:
                                continue
                        mat = asset.material_set(sec, mkey, source=source)
                        batches.setdefault(mat, {})[xform] = mfaces
                for mat, its in batches.items():
                    asset._add_items(its, mat)
        self.refresh()
        self.set_status("Section %s made%s." % (sec, (" with %d mesh(es)" % len(items)) if items else ""))

    @ui_safe
    def move_section(self, step):
        asset = self._asset()
        secs = self._selected_role("section")
        if asset is None or len(secs) != 1:
            self.set_status("Highlight one section to move.", level="warn")
            return
        asset.move_section(secs[0], step)
        self.refresh()
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            it.setSelected(it.data(0, QtCore.Qt.UserRole) == secs[0])

    @ui_safe
    def run_preprocess(self):
        asset = self._asset()
        if asset is None:
            self.set_status("Pick a root group first.", level="warn")
            return
        meshes, instanced = asset.meshes()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            t0 = time.time()
            self.report = preprocess(meshes, instanced, self.fix_lamina.value(), self.fix_nonmanifold.value(),
                                     self.fix_zero.value(), self.uv_set.text().strip() or "map1")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._fill_report()
        self.refresh()
        fixed = sum(sum(self.report.get(c, {}).values()) for c in ("lamina", "nonmanifold", "zeroarea"))
        skipped = len(skipped_meshes(self.report))
        warn = sum(len(self.report.get(c, {})) for c in ("ngons", "flipped", "remaining"))
        level = "warn" if (skipped or warn) else "info"
        self.set_status("Pre-process on %d meshes in %.2fs: %d problem(s) fixed, %d mesh(es) will be skipped, "
                        "%d with warnings." % (len(meshes), time.time() - t0, fixed, skipped, warn), level=level)

    @ui_safe
    def open_renamer(self):
        import unlok_renamer
        unlok_renamer.main()

    # ======================================================== helpers
    def _parent_section(self, material_set):
        asset = self._asset()
        for sec in asset.sections() if asset else []:
            if material_set in asset.materials(sec):
                return sec
        return None

    def _items_in_root(self, items):
        group = self._asset().root_group() if self._asset() else None
        if not group:
            return {}
        return {x: f for x, f in items.items() if x == group or x.startswith(group + "|")}

    def _select_nodes(self, nodes):
        nodes = [n for n in nodes if cmds.objExists(n)]
        if nodes:
            cmds.select(nodes, replace=True)

    def _naming_selected(self):
        try:
            self._select_nodes([it.data(0, QtCore.Qt.UserRole) for it in self.naming_list.selectedItems()])
        except Exception:
            traceback.print_exc()

    def _report_selected(self):
        try:
            nodes = []
            for it in self.report_tree.selectedItems():
                nodes.extend(it.data(0, QtCore.Qt.UserRole) or [])
            self._select_nodes(nodes)
        except Exception:
            traceback.print_exc()

    # ======================================================= scene events
    def _install_jobs(self):
        if maya_main_window() is None:
            return
        refresh = lambda: self._refresh_timer.start()  # noqa: E731
        self._jobs = [
            cmds.scriptJob(event=["Undo", refresh]),
            cmds.scriptJob(event=["Redo", refresh]),
            cmds.scriptJob(event=["NewSceneOpened", self._on_scene_changed]),
            cmds.scriptJob(event=["SceneOpened", self._on_scene_changed]),
        ]
        _registry()["jobs"].extend(self._jobs)

    def _on_scene_changed(self):
        try:
            assets = SmartUdimAsset.all()
            self.set_asset(assets[0] if len(assets) == 1 else None)
        except Exception:
            traceback.print_exc()

    def shutdown(self):
        self._refresh_timer.stop()
        reg = _registry()["jobs"]
        for job in self._jobs:
            try:
                if cmds.scriptJob(exists=job):
                    cmds.scriptJob(kill=job, force=True)
            except Exception:
                pass
            if job in reg:
                reg.remove(job)
        self._jobs = []


# =============================================================================
# Toolbox window
# =============================================================================

# Category -> tool panels. Add new tools here.
TOOL_REGISTRY = [
    ("Modeling", [PathScatterPanel]),
    ("UV", [SmartUdimPanel]),
]


class CategoryPage(QtWidgets.QWidget):
    def __init__(self, tool_classes, parent=None):
        super(CategoryPage, self).__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        self.stack = QtWidgets.QStackedWidget()
        self.panels = []
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(6, 0, 6, 0)
        bar.setSpacing(2)
        group = QtWidgets.QButtonGroup(self)
        for i, cls in enumerate(tool_classes):
            panel = cls()
            self.panels.append(panel)
            self.stack.addWidget(panel)
            btn = QtWidgets.QPushButton(cls.TOOL_NAME)
            btn.setToolTip(cls.TOOL_TIP)
            btn.setCheckable(True)
            btn.setProperty("unlokSegment", True)
            btn.setChecked(i == 0)
            group.addButton(btn, i)
            bar.addWidget(btn)
        bar.addStretch(1)
        group.buttonClicked.connect(lambda b: self.stack.setCurrentIndex(group.id(b)))
        if len(tool_classes) > 1:  # one tool: its own header says what it is
            lay.addLayout(bar)
        else:
            for b in group.buttons():
                b.setParent(None)
                b.deleteLater()
        lay.addWidget(self.stack, 1)


class ToolboxWindow(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(ToolboxWindow, self).__init__(parent or maya_main_window(), QtCore.Qt.Window)
        self.setObjectName(WINDOW_OBJECT_NAME)
        self.setWindowTitle("Unlok Toolbox  %s" % TOOLBOX_VERSION)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(STYLE)
        self.resize(400, 860)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 6, 4, 4)
        lay.setSpacing(2)
        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(6, 0, 6, 0)
        title = QtWidgets.QLabel("UNLOK TOOLBOX")
        title.setProperty("unlokTitle", True)
        version = QtWidgets.QLabel("v" + TOOLBOX_VERSION)
        version.setProperty("unlokHint", True)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(version)
        lay.addLayout(head)

        self.tabs = QtWidgets.QTabWidget()
        self.pages = []
        for category, tools in TOOL_REGISTRY:
            page = CategoryPage(tools)
            self.pages.append(page)
            self.tabs.addTab(page, category)
        lay.addWidget(self.tabs, 1)

    def panels(self):
        return [p for page in self.pages for p in page.panels]

    def closeEvent(self, event):
        for panel in self.panels():
            try:
                panel.shutdown()
            except Exception:
                traceback.print_exc()
        super(ToolboxWindow, self).closeEvent(event)


def _close_existing():
    app = QtWidgets.QApplication.instance()
    if app is not None:
        for widget in app.topLevelWidgets():
            if widget.objectName() == WINDOW_OBJECT_NAME:
                try:
                    widget.close()
                    widget.deleteLater()
                except Exception:
                    pass
    # Anything a previous paste left behind (e.g. it crashed before closing).
    reg = _registry()
    for cid in list(reg["callbacks"]):
        try:
            om.MMessage.removeCallback(cid)
        except Exception:
            pass
    reg["callbacks"] = []
    for job in list(reg["jobs"]):
        try:
            if cmds.scriptJob(exists=job):
                cmds.scriptJob(kill=job, force=True)
        except Exception:
            pass
    reg["jobs"] = []
    try:
        SurfacePathDrawer.delete_context()
    except Exception:
        pass


def show():
    _close_existing()
    window = ToolboxWindow()
    window.show()
    _registry()["window"] = window
    return window


if __name__ == "__main__":
    show()
