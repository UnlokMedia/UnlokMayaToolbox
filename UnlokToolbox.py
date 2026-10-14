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
"""

import functools
import json
import math
import random
import time
import traceback

import maya.cmds as cmds
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
        self._msg_set("unlokSurfaces", meshes, add=add)

    def set_sources(self, nodes):
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

    def _surface_fns(self):
        fns = []
        for node in self.surfaces():
            if cmds.nodeType(node) == "mesh":
                shapes = [node]
            else:
                shapes = cmds.listRelatives(node, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or []
            for shape in shapes:
                dag = get_dag_path(shape)
                if dag is not None:
                    fns.append(om.MFnMesh(dag))
        return fns

    # --------------------------------------------------------------- compute
    def compute(self, s):
        """Return (items, warning). items = [(variant_index, MMatrix), ...]."""
        proxies = self.proxies()
        if not proxies:
            if s.get("source_type") == "Mesh":
                return [], "Pick source meshes: select them and press 'Use Selected Meshes'."
            return [], "No source."
        curves = self._curve_samplers()
        if not curves:
            return [], "No path yet. Draw one, or select a curve / edges and press 'Use Selection'."
        surfaces = self._surface_fns()

        remap, axes_ok = axis_remap_matrix(s["forward_axis"], s["up_axis"])
        warning = None if axes_ok else "Forward and Up axis can't be the same axis."

        # Per-variant pre-matrix: remap axes, then move the chosen pivot to origin.
        variants = []
        for proxy in proxies:
            corners = self._proxy_corners(proxy) or [om.MPoint(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)]
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
        n_var = len(variants)

        rot_offset = mat_euler_deg(s["rot_x"], s["rot_y"], s["rot_z"])
        base_scale = (s["scale"] * s["scale_x"], s["scale"] * s["scale_y"], s["scale"] * s["scale_z"])
        extent_cache = {}

        def extent(vi, sc):
            key = (vi, round(sc[0], 6), round(sc[1], 6), round(sc[2], 6))
            hit = extent_cache.get(key)
            if hit is None:
                m = mat_scale(*sc) * rot_offset
                xs = [(c * m).x for c in variants[vi][1]]
                hit = (min(xs), max(xs))
                extent_cache[key] = hit
            return hit

        seed = int(s["seed"])
        smin, smax = s["rand_scale_min"], s["rand_scale_max"]
        axis_j = s["rand_scale_axis"]
        rr = (s["rand_rot_x"], s["rand_rot_y"], s["rand_rot_z"])
        has_rand_rot = any(abs(v) > 1e-9 for v in rr)
        jit = (s["rand_along"], s["rand_side"], s["rand_up"])
        skip = s["skip_chance"]
        cycle = s["variant_mode"] == "Cycle"
        mode = s["dist_mode"]
        gap = s["gap"]
        rows = max(1, int(s["rows"]))
        max_items = max(1, int(s["max_items"]))
        use_normal = s["up_mode"] == "Surface Normal" and bool(surfaces)
        snap = s["snap_surface"] and bool(surfaces)
        follow = s["follow_path"]

        def item_random(pi, row, i):
            rng = random.Random(hash((seed, pi, row, i)))
            u = [rng.random() for _ in range(12)]
            vi = (i + row) % n_var if cycle else min(n_var - 1, int(u[0] * n_var))
            mult = smin + (smax - smin) * u[2]
            sc = tuple(max(1e-4, base_scale[a] * mult * (1.0 + (u[3 + a] * 2.0 - 1.0) * axis_j)) for a in range(3))
            rot = tuple((u[6 + a] * 2.0 - 1.0) * rr[a] for a in range(3))
            off = tuple((u[9 + a] * 2.0 - 1.0) * jit[a] for a in range(3))
            return vi, u[1] * 100.0 < skip, sc, rot, off

        def closest(point):
            best = None
            for fn in surfaces:
                try:
                    cp, normal, _ = fn.getClosestPointAndNormal(point, om.MSpace.kWorld)
                except RuntimeError:
                    continue
                dist = (cp - point).length()
                if best is None or dist < best[0]:
                    best = (dist, cp, normal)
            return best

        items = []
        truncated = False
        base_cache = {}  # rows share path samples: (path, distance) -> frame data
        for pi, curve in enumerate(curves):
            start = s["start_offset"]
            end = curve.length - s["end_offset"]
            usable = end - start
            if usable <= 1e-6:
                continue

            if mode == "Fit to Size":
                mn, mx = extent(0, base_scale)
                pitch = max(1e-4, (mx - mn) + gap)
            elif mode == "Spacing":
                pitch = max(1e-4, s["spacing"])
            else:
                n = max(1, int(s["count"]))
                pitch = usable / n if curve.closed else (usable / (n - 1) if n > 1 else usable)

            for row in range(rows):
                row_off = ((row - (rows - 1) * 0.5) if s["rows_centered"] else row) * s["row_spacing"]
                stagger = (row % 2) * s["row_stagger"] * pitch

                # --- slots along this row: (index, distance, random data)
                slots = []
                if mode == "Fit to Size":
                    d = start + stagger
                    i = 0
                    while len(items) + len(slots) < max_items:
                        rnd = item_random(pi, row, i)
                        mn, mx = extent(rnd[0], rnd[2])
                        pos = d - mn
                        if pos + mx > end + 1e-6:
                            break
                        slots.append((i, pos, rnd))
                        d = pos + max(1e-4, mx + gap)
                        i += 1
                    else:
                        truncated = True
                elif mode == "Spacing":
                    d = start + stagger
                    i = 0
                    while d <= end + 1e-6:
                        if len(items) + len(slots) >= max_items:
                            truncated = True
                            break
                        slots.append((i, d, item_random(pi, row, i)))
                        d += pitch
                        i += 1
                else:
                    n = max(1, int(s["count"]))
                    for i in range(n):
                        if len(items) + len(slots) >= max_items:
                            truncated = True
                            break
                        if n == 1 and not curve.closed:
                            d = start + usable * 0.5 + stagger
                        else:
                            d = start + i * pitch + stagger
                        if not curve.closed and d > end + 1e-6:
                            continue
                        slots.append((i, d, item_random(pi, row, i)))

                # --- place each slot
                for i, dist, (vi, skipped, sc, rot, off) in slots:
                    if skipped:
                        continue
                    key = (pi, round(dist, 6))
                    base = base_cache.get(key)
                    if base is None:
                        point, tangent = curve.sample(dist)
                        up = WORLD_UP
                        if use_normal:
                            hit = closest(point)
                            if hit:
                                up = om.MVector(hit[2]).normal()
                        x0 = tangent - up * (tangent * up)
                        if x0.length() < 1e-6:
                            x0 = WORLD_X - up * (WORLD_X * up)
                            if x0.length() < 1e-6:
                                x0 = WORLD_Z
                        x0.normalize()
                        z0 = (x0 ^ up).normal()
                        base = base_cache[key] = (point, tangent, up, x0, z0)
                    point, tangent, up, x0, z0 = base
                    p = om.MPoint(point) + z0 * (row_off + off[1]) + x0 * off[0]
                    if snap:
                        hit = closest(p)
                        if hit:
                            normal = om.MVector(hit[2]).normal()
                            p = om.MPoint(hit[1]) + normal * s["surface_offset"]
                            if use_normal:
                                up = normal
                    p = p + up * (s["row_lift"] * row + off[2])

                    ref = tangent if follow else WORLD_X
                    xf = ref - up * (ref * up)
                    if xf.length() < 1e-6:
                        xf = x0
                    xf.normalize()
                    zf = (xf ^ up).normal()
                    yf = (zf ^ xf).normal()
                    frame = mat_from_frame(xf, yf, zf, p)

                    local = variants[vi][0] * mat_scale(*sc) * rot_offset
                    if has_rand_rot:
                        local = local * mat_euler_deg(*rot)
                    items.append((vi, local * frame))
            if truncated:
                break

        if truncated:
            warning = "Capped at %d items (raise 'Max items' in Output if you really need more)." % max_items
        return items, warning

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
            self._push(items, s.get("preview_boxes", False))
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
        items, _ = self.compute(s)
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
            else:
                self._bake_copies(items, proxies, out_obj, short)
                result = out
                if mode == "Combined Mesh":
                    result = self._combine(out, short)
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
        self._reset()

    def _reset(self):
        self.points = []  # [(MPoint, mesh path or None for the plane)]
        self.candidates = []  # [(dag, fn, accel, world bbox or None)] for this stroke
        self.plane = None
        self.anchor = None
        self.last_screen = None
        self.straight = False
        self.add = False
        self.temp_curve = None

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
        if bb is None:
            return True
        tmin, tmax = -1e30, 1e30
        mn, mx = bb.min, bb.max
        for o, d, lo, hi in ((src.x, direction.x, mn.x, mx.x),
                             (src.y, direction.y, mn.y, mx.y),
                             (src.z, direction.z, mn.z, mx.z)):
            if abs(d) < 1e-12:
                if o < lo or o > hi:
                    return False
                continue
            t1, t2 = (lo - o) / d, (hi - o) / d
            if t1 > t2:
                t1, t2 = t2, t1
            tmin, tmax = max(tmin, t1), min(tmax, t2)
            if tmin > tmax:
                return False
        return tmax >= 0

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
            best = None
            for dag, fn, accel, bb in self.candidates:
                if not self._ray_hits_bbox(src, direction, bb):
                    continue
                hit = self._intersect((fn, accel), src, direction)
                if hit and (best is None or hit[1] < best[1]):
                    best = (hit[0], hit[1], dag)
            if best is None:
                return None
            return best[0], best[2].fullPathName()
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
            out.append((dag, fn, fn.autoUniformGridParams(), SurfacePathDrawer._world_box(dag)))
        return out

    def drag_at(self, x, y):
        if self.anchor is None:
            return
        if self.straight:
            ax, ay = self.anchor
            steps = max(2, int(math.hypot(x - ax, y - ay) / 6.0))
            pts = []
            for i in range(steps + 1):
                t = float(i) / steps
                p = self._cast(ax + (x - ax) * t, ay + (y - ay) * t)
                if p is not None:
                    pts.append(p)
            self.points = pts
        else:
            lx, ly = self.last_screen
            if math.hypot(x - lx, y - ly) < 3.0:
                return
            p = self._cast(x, y)
            if p is None:
                return
            self.points.append(p)
            self.last_screen = (x, y)
        self._update_temp_curve()

    def release(self):
        try:
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
            self._delete_temp_curve()
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
            self._delete_temp_curve()
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

    def _update_temp_curve(self):
        pts = self._clean_points([pt for pt, _ in self.points])
        if len(pts) < 2:
            return
        coords = [(p.x, p.y, p.z) for p in pts]
        with NoUndo(), PreserveSelection():
            if self.temp_curve and cmds.objExists(self.temp_curve):
                cmds.curve(self.temp_curve, replace=True, degree=1, point=coords)
            else:
                self.temp_curve = long_name(cmds.curve(degree=1, point=coords, name="unlokPathPreview"))
                shape = cmds.listRelatives(self.temp_curve, shapes=True, fullPath=True)[0]
                cmds.setAttr(shape + ".overrideEnabled", 1)
                cmds.setAttr(shape + ".overrideRGBColors", 1)
                cmds.setAttr(shape + ".overrideColorRGB", 1.0, 0.75, 0.2)
                cmds.setAttr(shape + ".lineWidth", 2.0)
        cmds.refresh(currentView=True, force=True)

    def _delete_temp_curve(self):
        if self.temp_curve and cmds.objExists(self.temp_curve):
            with NoUndo():
                cmds.delete(self.temp_curve)
        self.temp_curve = None


# =============================================================================
# UI building blocks
# =============================================================================

ACCENT = "#2f8f83"
ACCENT_HOVER = "#37a596"
ACTIVE = "#c9772a"

STYLE = """
#UnlokToolboxWindow QLabel[unlokTitle="true"] { font-size: 13px; font-weight: 600; letter-spacing: 1px; }
#UnlokToolboxWindow QLabel[unlokHint="true"] { color: #8c8c8c; }
#UnlokToolboxWindow QToolButton[unlokSection="true"] {
    border: none; border-bottom: 1px solid #3a3a3a; font-weight: 600; padding: 5px 2px; text-align: left; }
#UnlokToolboxWindow QPushButton[unlokPrimary="true"] {
    background: %(accent)s; color: white; font-weight: 600; padding: 6px 10px; border-radius: 3px; border: none; }
#UnlokToolboxWindow QPushButton[unlokPrimary="true"]:hover { background: %(hover)s; }
#UnlokToolboxWindow QPushButton[unlokPrimary="true"]:checked { background: %(active)s; }
#UnlokToolboxWindow QPushButton[unlokPrimary="true"]:disabled { background: #444; color: #888; }
#UnlokToolboxWindow QPushButton[unlokSegment="true"] {
    padding: 4px 6px; border: 1px solid #2b2b2b; border-radius: 2px; background: #5a5a5a; }
#UnlokToolboxWindow QPushButton[unlokSegment="true"]:hover { background: #666; }
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

    def __init__(self, title, expanded=True, parent=None):
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

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self.rebuild)

        self.drawer = SurfacePathDrawer(self._on_stroke, lambda: self.fields["smoothing"].value(),
                                        PathScatterSystem.all_roots)
        self.drawer.on_miss = lambda: self.set_status("That stroke didn't land on anything. Drag across a mesh "
                                                      "(or start on empty grid to draw on the ground).", level="warn")
        self._build()
        self._update_enabled()
        self._install_jobs()
        self._refresh_system_label()

    # ============================================================= layout
    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # --- actions
        actions = QtWidgets.QWidget()
        al = QtWidgets.QGridLayout(actions)
        al.setContentsMargins(6, 6, 6, 0)
        al.setSpacing(4)
        self.draw_btn = primary_button("Draw Path", checkable=True)
        self.draw_btn.setToolTip("Drag on a mesh to draw a path. Shift: straight line. Ctrl: add another path. "
                                 "Press Q (or click this again) when done.")
        self.draw_btn.clicked.connect(lambda *_: self.toggle_draw())
        use_btn = QtWidgets.QPushButton("Use Selection as Path")
        use_btn.setToolTip("Use selected curve(s), or selected polygon edges (converted to a curve).")
        use_btn.clicked.connect(lambda *_: self.use_selected_path())
        surf_btn = QtWidgets.QPushButton("Set Surface")
        surf_btn.setToolTip("Selected mesh(es) become the surface to draw on, snap to and align with. "
                            "Nothing selected = auto-detect under the cursor.")
        surf_btn.clicked.connect(lambda *_: self.use_selected_surface())
        al.addWidget(self.draw_btn, 0, 0, 1, 2)
        al.addWidget(use_btn, 1, 0)
        al.addWidget(surf_btn, 1, 1)
        al.addWidget(hint_label("Shift: straight line   Ctrl: add path   Q: finish"), 2, 0, 1, 2)

        sys_row = QtWidgets.QHBoxLayout()
        sys_row.setSpacing(4)
        self.system_label = QtWidgets.QLabel()
        new_btn = QtWidgets.QPushButton("New")
        new_btn.setToolTip("Leave the current scatter as it is; the next path starts a new one.")
        new_btn.clicked.connect(lambda *_: self.new_system())
        select_btn = QtWidgets.QPushButton("Select")
        select_btn.clicked.connect(lambda *_: self.select_system())
        del_btn = QtWidgets.QPushButton("Delete")
        del_btn.clicked.connect(lambda *_: self.delete_system())
        sys_row.addWidget(self.system_label, 1)
        for b in (new_btn, select_btn, del_btn):
            b.setFixedWidth(52)
            sys_row.addWidget(b)
        al.addLayout(sys_row, 3, 0, 1, 2)
        outer.addWidget(actions)

        # --- settings (scrolling)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        body = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(body)
        bl.setContentsMargins(6, 0, 6, 6)
        bl.setSpacing(2)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        sec = Section("Source")
        self.recipe_combo = _guard_focus(_Combo())
        self.recipe_combo.addItems(["Start from a recipe..."] + list(RECIPES))
        self.recipe_combo.activated.connect(lambda i: self.apply_recipe(self.recipe_combo.itemText(i)))
        sec.add_row("Recipe", self.recipe_combo, "Set everything up for a common job in one click, then tweak.")
        self._add(sec, "source_type", "Type", SegmentField(SOURCE_TYPES),
                  "A built-in shape, or 'Mesh' to scatter your own objects.")
        pick = QtWidgets.QPushButton("Use Selected Meshes")
        pick.setToolTip("Selected objects become the source. Several objects = random variants (rocks, etc.). "
                        "Edits to them update the scatter live.")
        pick.clicked.connect(lambda *_: self.use_selected_meshes())
        sec.add_full(pick)
        self.sources_label = hint_label("")
        sec.add_full(self.sources_label)
        self._add(sec, "size_x", "Length", FloatField(0.001, 10000, 0.01, 5), "Size along the path (preset shapes).")
        self._add(sec, "size_y", "Height", FloatField(0.001, 10000, 0.01, 5), "Size along the up axis.")
        self._add(sec, "size_z", "Width", FloatField(0.001, 10000, 0.01, 5), "Size across the path.")
        self._add(sec, "preset_sides", "Sides", IntField(3, 128, 3, 48), "Cylinder / sphere subdivisions.")
        self._add(sec, "forward_axis", "Forward axis", ComboField(AXIS_NAMES),
                  "Which axis of the source points along the path.")
        self._add(sec, "up_axis", "Up axis", ComboField(("Y", "-Y", "Z", "-Z", "X", "-X")),
                  "Which axis of the source points away from the surface.")
        self._add(sec, "pivot", "Pivot", ComboField(PIVOT_MODES),
                  "Point of each item that sits on the path. Bottom = rests on the surface.")
        bl.addWidget(sec)

        sec = Section("Distribution")
        self._add(sec, "dist_mode", "Mode", ComboField(DIST_MODES),
                  "Fit to Size: end to end using each item's length (+ gap).\n"
                  "Spacing: fixed distance.\nCount: exact number spread over the path.")
        self._add(sec, "gap", "Gap", FloatField(-1000, 1000, -1, 2), "Extra space between items (Fit to Size).")
        self._add(sec, "spacing", "Spacing", FloatField(0.001, 10000, 0.01, 5), "Distance between items.")
        self._add(sec, "count", "Count", IntField(1, 100000, 1, 200), "Items per row.")
        self._add(sec, "start_offset", "Start offset", FloatField(-10000, 10000, 0, 5), "Trim / slide the start.")
        self._add(sec, "end_offset", "End offset", FloatField(-10000, 10000, 0, 5), "Trim the end.")
        bl.addWidget(sec)

        sec = Section("Rows (grid)")
        self._add(sec, "rows", "Rows", IntField(1, 1000, 1, 50), "Copies of the line side by side, e.g. shingle courses.")
        self._add(sec, "row_spacing", "Row spacing", FloatField(-10000, 10000, -2, 2),
                  "Distance between rows across the path. Negative = other side.")
        self._add(sec, "row_stagger", "Stagger", FloatField(-1, 1, 0, 1, step=0.05),
                  "Shift every other row along the path (0.5 = brick / shingle pattern).")
        self._add(sec, "row_lift", "Row lift", FloatField(-100, 100, -0.2, 0.2, step=0.01),
                  "Raise each row along the normal, so rows overlap like shingles.")
        self._add(sec, "rows_centered", "", CheckField("Center rows on path"))
        bl.addWidget(sec)

        sec = Section("Orientation")
        self._add(sec, "follow_path", "", CheckField("Follow path direction"))
        self._add(sec, "up_mode", "Up", ComboField(UP_MODES), "Align items to the surface normal or keep them upright.")
        self._add(sec, "snap_surface", "", CheckField("Snap to surface"))
        self._add(sec, "surface_offset", "Surface offset", FloatField(-100, 100, -1, 1, step=0.01),
                  "Push items off (or into) the surface.")
        self._add(sec, "rot_x", "Rotate X", FloatField(-360, 360, -180, 180, decimals=2, step=1), "Roll around the path.")
        self._add(sec, "rot_y", "Rotate Y", FloatField(-360, 360, -180, 180, decimals=2, step=1), "Yaw around the up axis.")
        self._add(sec, "rot_z", "Rotate Z", FloatField(-360, 360, -180, 180, decimals=2, step=1),
                  "Tilt / pitch, e.g. to angle shingles.")
        bl.addWidget(sec)

        sec = Section("Scale")
        self._add(sec, "scale", "Scale", FloatField(0.001, 1000, 0.01, 5))
        self._add(sec, "scale_x", "Scale X (length)", FloatField(0.001, 1000, 0.01, 5))
        self._add(sec, "scale_y", "Scale Y (up)", FloatField(0.001, 1000, 0.01, 5))
        self._add(sec, "scale_z", "Scale Z (width)", FloatField(0.001, 1000, 0.01, 5))
        bl.addWidget(sec)

        sec = Section("Randomness")
        seed_row = QtWidgets.QWidget()
        sl = QtWidgets.QHBoxLayout(seed_row)
        sl.setContentsMargins(0, 0, 0, 0)
        seed = IntField(0, 999999, 0, 1000)
        roll = QtWidgets.QPushButton("Re-roll")
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
        bl.addWidget(sec)

        sec = Section("Drawing & Output", expanded=False)
        self._add(sec, "smoothing", "Stroke smoothing", IntField(0, 10, 0, 10), "Higher = smoother drawn curves.")
        self._add(sec, "max_items", "Max items", IntField(1, 1000000, 100, 100000),
                  "Safety cap so a tiny spacing can't hang Maya.")
        self._add(sec, "preview_boxes", "", CheckField("Preview as bounding boxes (fast for heavy meshes)"))
        bl.addWidget(sec)
        bl.addStretch(1)

        # --- footer
        footer = QtWidgets.QWidget()
        fl = QtWidgets.QGridLayout(footer)
        fl.setContentsMargins(6, 0, 6, 6)
        fl.setSpacing(4)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self._add_free("bake_mode", ComboField(BAKE_MODES))
        self.fields["bake_mode"].setToolTip("Instances: light, shares geometry with the source.\n"
                                            "Copies: separate editable meshes.\n"
                                            "Combined Mesh: one merged mesh.")
        self._add_free("keep_system", CheckField("Keep live system"))
        self.fields["keep_system"].setToolTip("Hide the live scatter after baking instead of deleting it, "
                                              "so you can come back and tweak it.")
        self.bake_btn = primary_button("Bake")
        self.bake_btn.clicked.connect(lambda *_: self.bake())
        fl.addWidget(self.status, 0, 0, 1, 3)
        fl.addWidget(QtWidgets.QLabel("Bake as"), 1, 0)
        fl.addWidget(self.fields["bake_mode"], 1, 1)
        fl.addWidget(self.fields["keep_system"], 1, 2)
        fl.addWidget(self.bake_btn, 2, 0, 1, 3)
        fl.setColumnStretch(1, 1)
        outer.addWidget(footer)

        self.set_settings(PS_DEFAULTS)

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

    @ui_safe
    def toggle_draw(self):
        if SurfacePathDrawer.is_active():
            SurfacePathDrawer.deactivate()
            self.draw_btn.setChecked(False)
            return
        sel = cmds.ls(selection=True, long=True, type="transform") or []
        surfaces = [n for n in sel
                    if cmds.listRelatives(n, shapes=True, type="mesh", noIntermediate=True)
                    and PathScatterSystem.from_node(n) is None]
        self.drawer.activate(surfaces)
        self.draw_btn.setChecked(True)
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

    @ui_safe
    def bake(self):
        system = self._system()
        if system is None:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            t0 = time.time()
            s = self.settings()
            count = system.last_count
            result = system.bake(s)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.system = None
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
        except Exception:
            pass

    def _on_scene_changed(self):
        try:
            self.system = None
            self._watch_inputs()
            self._refresh_system_label()
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
# Toolbox window
# =============================================================================

# Category -> tool panels. Add new tools here.
TOOL_REGISTRY = [
    ("Modeling", [PathScatterPanel]),
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
        lay.addLayout(bar)
        lay.addWidget(self.stack, 1)


class ToolboxWindow(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(ToolboxWindow, self).__init__(parent or maya_main_window(), QtCore.Qt.Window)
        self.setObjectName(WINDOW_OBJECT_NAME)
        self.setWindowTitle("Unlok Toolbox  %s" % TOOLBOX_VERSION)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(STYLE)
        self.resize(380, 780)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 6, 4, 4)
        lay.setSpacing(4)
        title = QtWidgets.QLabel("UNLOK TOOLBOX")
        title.setProperty("unlokTitle", True)
        lay.addWidget(title)

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
