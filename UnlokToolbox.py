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
    Bevel Resolver - turn the n-gons a chamfer-off bevel leaves at its ends
                     into clean SubD quads, mesh-wide or on a selection.
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


class Cancelled(Exception):
    """The user pressed Esc during a long run."""


class Progress(object):
    """Progress for long runs: Maya's main progress bar (Esc cancels) plus an
    optional callback(fraction, text) for a panel to show the same thing.

    stages = [(key, weight)]: each stage's share of the bar. Inside a stage,
    call item(detail, weight) before each piece of work. Updates are
    throttled to ~10 a second, so calling it per mesh costs next to nothing.
    Raises Cancelled from item() / update() once Esc was pressed.
    """

    def __init__(self, title, stages, callback=None):
        self.title = title
        self.callback = callback
        total = float(sum(w for _, w in stages)) or 1.0
        self.span = {}
        acc = 0.0
        for key, w in stages:
            self.span[key] = (acc / total, w / total)
            acc += w
        self.key, self.label, self.detail = None, "", ""
        self.count, self.items, self.pos, self.done, self._pending = 1.0, 1, 0, 0.0, 0.0
        self.t0 = time.time()
        self._last = 0.0
        self._last_view = 0.0
        self.refresh_view = False  # redraw the viewport about once a second (live UV colours)
        self.bar = None

    def __enter__(self):
        if not cmds.about(batch=True):
            try:
                self.bar = mel.eval("$unlokTmpBar = $gMainProgressBar")
                cmds.progressBar(self.bar, edit=True, beginProgress=True, isInterruptable=True,
                                 status=self.title, maxValue=1000)
            except Exception:
                self.bar = None
        return self

    def __exit__(self, *exc):
        if self.bar:
            try:
                cmds.progressBar(self.bar, edit=True, endProgress=True)
            except Exception:
                pass
        return False

    def stage(self, key, count, label, items=None):
        """count: total weight of the stage's items; items: how many there
        are, when weights aren't 1 each (e.g. batches weighted by faces)."""
        self.key, self.label, self.detail = key, label, ""
        self.count = float(max(1, count))
        self.items = int(count if items is None else items)
        self.pos, self.done, self._pending = 0, 0.0, 0.0
        self.update(force=True)

    def item(self, detail="", weight=1.0, force=False):
        """Mark the start of the next piece of work. force: show it now even
        if the bar updated less than 0.1 s ago, for anything that might take
        a while (otherwise a long wait could sit under the previous label)."""
        self.done += self._pending
        self._pending = float(weight)
        self.pos += 1
        self.detail = detail
        self.update(force=force or self.pos == 1)  # a stage's first item always shows

    def fraction(self):
        start, share = self.span.get(self.key, (0.0, 0.0))
        return min(1.0, start + share * min(1.0, self.done / self.count))

    def where(self):
        """'Unfolding (12 of 47)', for reports."""
        return "%s (%d of %d)" % (self.label, self.pos, self.items) if self.pos else self.label

    def text(self):
        f = self.fraction()
        spent = time.time() - self.t0
        txt = "%s - %s" % (self.title, self.label)
        if self.pos:
            txt += " %d of %d" % (self.pos, self.items)
        if self.detail:
            txt += ": %s" % self.detail
        txt += "  |  %d%%, %s" % (round(f * 100), _secs(spent))
        if f > 0.05 and spent > 2.0:
            txt += ", about %s left" % _secs(spent / f - spent)
        return txt

    def update(self, force=False):
        now = time.time()
        if not force and now - self._last < 0.1:
            return
        self._last = now
        if self.bar:
            if cmds.progressBar(self.bar, query=True, isCancelled=True):
                raise Cancelled(self.where())
            cmds.progressBar(self.bar, edit=True, progress=int(self.fraction() * 1000),
                             status=self.text() + "  |  Esc cancels")
            if self.refresh_view and now - self._last_view > 1.0:
                self._last_view = now
                cmds.refresh(currentView=True)
        if self.callback:
            self.callback(self.fraction(), self.text())


def _secs(s):
    s = int(round(s))
    return "%ds" % s if s < 60 else "%dm %02ds" % (s // 60, s % 60)


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
# Copied from UnlokRenamer (unlok_renamer.py) so this file stays
# self-contained. Keep these lists and helpers in sync with UnlokRenamer.

UR_MATERIALS = [
    "stone", "brick", "plastic", "metal", "wood", "bone", "paint",
    "rock", "skin", "scales", "grass", "glass", "fabric", "rubber",
    "leather", "ceramic", "concrete", "default"
]

UR_COLORS = [
    "Default", "Red", "Blue", "Green", "Yellow", "White", "Black",
    "Grey", "Gray", "Cream", "Pink", "Brown", "Orange", "Purple",
    "Tan", "Beige", "Gold", "Silver", "Clear"
]

UR_SUFFIXES = [
    "GES", "GEP", "PLY",
    "GED", "GEV", "GEN", "GEC",
    "NRB", "CRV", "BLS", "GEO",
    "GRP"
]


# A guide, not a fixed list: any lowercase word, then capitalised word(s)
# (usually a colour, but woodMoulding is fine), then an optional capital
# variant letter (glassClearA).
UR_MATERIAL_TOKEN_RE = re.compile(r'^([a-z][a-z0-9]*)((?:[A-Z][a-z0-9]+)+)([A-Z]?)$')


def ur_split_material_color_variant(material_color):
    """'paintGrey' -> ('paint', 'Grey', ''); 'woodMoulding' -> ('wood',
    'Moulding', ''); 'glassClearA' -> ('glass', 'Clear', 'A');
    (None, None, '') when it isn't word + Word(s)."""
    match = UR_MATERIAL_TOKEN_RE.match(material_color or "")
    if not match:
        return None, None, ""
    return match.group(1), match.group(2), match.group(3)


def ur_split_material_color(material_color):
    """'paintGrey' -> ('paint', 'Grey'); a variant letter ('glassClearA') is
    accepted and dropped; (None, None) if unparseable."""
    material, color, _ = ur_split_material_color_variant(material_color)
    return material, color


def ur_base_suffix_of(token):
    """'GEP' -> ('GEP', ''), 'GEP1' -> ('GEP', '1'), unknown -> (None, '')."""
    match = re.match(r'^([A-Za-z]+)(\d*)$', token)
    if match and match.group(1) in UR_SUFFIXES:
        return match.group(1), match.group(2)
    return None, ''


def material_key_from_name(name):
    """Material key from a convention name, plus any naming issue.

    'woodGreen_C_beam0001_GEP' -> ('woodGreen', None)
    'woodMoulding_C_trim_GEP'  -> ('woodMoulding', None)  (any word + Word(s))
    'glassClearA_F_pane0001_GEP' -> ('glassClearA', None)  (variant A: its own group)
    'steel_C_beam_GEP'         -> ('steel', "material token 'steel' isn't ...")
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
        return token, "material token '%s' isn't a word then capitalised word(s), like woodBrown" % token
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
UDIM_ORIENT = "unlokUdimOrient"
ORIENT_TOKENS = ("up", "keep", "axis")  # per-group orientation override in set names

SECTION_SUFFIX = "UDS"
# Per-mesh UV status, stored as membership of two sets under the root set:
#   keep     = never re-unwrap, but still categorise, scale and pack
#   handsoff = never touch: no unwrap, no layout; the plan works around it
UV_STATUSES = ("auto", "keep", "handsoff")
UV_STATUS_LABELS = {"auto": "Auto", "keep": "Keep UVs", "handsoff": "Hands off"}
# Tool-owned tracking sets (also under the root): what Auto UV unwrapped, what
# Smart Layout laid out, and what needs a human (Auto UV failed / still bad).
_STATUS_ROLE = {"keep": "uvkeep", "handsoff": "uvhandsoff", "auto": "uvauto", "laidout": "uvlaidout",
                "problem": "uvproblem"}
_STATUS_SUFFIX = {"keep": "uvKeep_SET", "handsoff": "uvHandsOff_SET", "auto": "uvAuto_SET",
                  "laidout": "uvLaidOut_SET", "problem": "uvProblem_SET"}
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
    orient = None
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
        elif token.lower() in ORIENT_TOKENS:
            orient = token.lower()
        elif token.isdigit() or token in (SECTION_SUFFIX, "SET", "smartUDIM"):
            continue
        else:
            key_parts.append(token)
    out = {"key": "_".join(key_parts) or None, "td": td, "cov": cov, "stack": stack}
    if orient:
        out["orient"] = orient
    return out


def compose_material_set_name(key, td=100.0, cov=None, stack=False, orient=None):
    parts = ["td%s" % _num_token(td), key]
    if cov is not None and cov >= 0:
        parts.append("c%03d" % int(round(cov)))
    if stack:
        parts.append("stack")
    if orient in ORIENT_TOKENS:
        parts.append(orient)
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
        add(UDIM_ORIENT, dataType="string")
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
    per-face shading assignment (its real one while UV colours are on)."""
    shapes = cmds.listRelatives(transform, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or []
    if not shapes:
        return {}
    if cmds.attributeQuery(ORIG_SHADING_ATTR, node=shapes[0], exists=True):
        try:
            orig = json.loads(cmds.getAttr(shapes[0] + "." + ORIG_SHADING_ATTR) or "{}")
        except ValueError:
            orig = {}
        if orig:
            groups = {}
            for sg, ranges in orig.items():
                key = _sg_key(sg) if cmds.objExists(sg) else "default"
                if ranges is None:  # one shader on the whole mesh
                    return {key: None}
                faces = groups.setdefault(key, [])
                for r in ranges:
                    faces.extend(_parse_face_spec(r) or [])
            return groups
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
                if not cmds.attributeQuery(UDIM_ORIENT, node=mat, exists=True):
                    cmds.addAttr(mat, longName=UDIM_ORIENT, dataType="string")
                cmds.setAttr(mat + "." + UDIM_ORIENT, parsed.get("orient") or "", type="string")
                cov = _get(mat, UDIM_COV, -1.0)
                wanted = compose_material_set_name(key, td, cov if cov >= 0 else None, parsed["stack"],
                                                   parsed.get("orient"))
                if _base_name(mat) != wanted:
                    cmds.rename(mat, _unique_set_name(wanted, mat))

    def set_group_values(self, node, td=None, stack=None, orient=None):
        """orient: 'up' / 'keep' / 'axis', or '' to follow the layout setting."""
        role = set_role(node)
        with UndoChunk("Smart UDIM edit"):
            if td is not None:
                cmds.setAttr(node + "." + UDIM_TD, float(td))
            if stack is not None and role == "material":
                cmds.setAttr(node + "." + UDIM_STACK, bool(stack))
            if orient is not None and role == "material":
                if not cmds.attributeQuery(UDIM_ORIENT, node=node, exists=True):
                    cmds.addAttr(node, longName=UDIM_ORIENT, dataType="string")
                cmds.setAttr(node + "." + UDIM_ORIENT, orient if orient in ORIENT_TOKENS else "", type="string")
            key = _get(node, UDIM_KEY) or parse_group_name(node)["key"]
            if role == "section":
                wanted = compose_section_set_name(key, _get(node, UDIM_TD, 100.0))
            else:
                cov = _get(node, UDIM_COV, -1.0)
                wanted = compose_material_set_name(key, _get(node, UDIM_TD, 100.0), cov if cov >= 0 else None,
                                                   _get(node, UDIM_STACK, False), _get(node, UDIM_ORIENT, "") or None)
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

    # ----------------------------------------------------------- UV status
    def status_set(self, status, create=False):
        """The root's Keep UVs / Hands off set (made on demand)."""
        root = self.root_set()
        if not root or status not in _STATUS_ROLE:
            return None
        for node in _child_sets(root):
            if set_role(node) == _STATUS_ROLE[status]:
                return node
        if not create:
            return None
        base = re.sub(r'_?%s$' % ROOT_SUFFIX, "", short_name(root)) or "asset"
        node = cmds.sets(empty=True, name=_unique_set_name("%s_%s" % (base, _STATUS_SUFFIX[status])))
        _add_set_attrs(node, _STATUS_ROLE[status])
        cmds.sets(node, add=root)
        return node

    def uv_status(self):
        """{mesh transform: 'keep' / 'handsoff'}; meshes not listed are 'auto'.
        Hands off wins when a mesh is in both sets."""
        out = {}
        for status in ("keep", "handsoff"):
            node = self.status_set(status)
            if node:
                for xform in expand_members(node)[0]:
                    out[xform] = status
        return out

    def set_uv_status(self, meshes, status):
        """Mark whole meshes 'auto', 'keep' or 'handsoff' (one Ctrl+Z)."""
        meshes = [m for m in meshes if cmds.objExists(m)]
        if not meshes or status not in UV_STATUSES:
            return 0
        with UndoChunk("Smart UDIM UV status"):
            for st in ("keep", "handsoff"):
                node = self.status_set(st, create=(st == status))
                if node is None:
                    continue
                members = expand_members(node)[0]
                gone = []
                for m in meshes:
                    if m in members:
                        gone.append(m)
                        gone.extend(cmds.listRelatives(m, shapes=True, fullPath=True) or [])
                if gone:
                    cmds.sets(gone, remove=node)
                if st == status:
                    cmds.sets(meshes, add=node)
        return len(meshes)

    # ------------------------------------------------------------ sections
    @staticmethod
    def section_name_for(group):
        """'westWing_GRP' / 'westWing_01_GRP' -> 'westWing'."""
        base = short_name(group)
        return sanitize_key(re.sub(r'_\d*_?(GRP|grp|Grp)$', "", base) or base)

    def section_of_group(self, group):
        for sec in self.sections():
            if _linked_group(sec) == long_name(group):
                return sec
        return None

    def _material_keys_of(self, items, material_source):
        """{key: {xform: faces or None}} for items, keeping each mesh's current
        material group; anything not in a group yet is sorted by name / shader."""
        assigned = self.assignments()
        out = {}
        for xform, sel in items.items():
            taken = set()
            whole = False
            for mat, faces in assigned.get(xform, []):
                key = _get(mat, UDIM_KEY) or parse_group_name(mat)["key"]
                if sel is None:
                    part = faces
                elif faces is None:
                    part = set(sel)
                else:
                    part = set(sel) & faces
                    if not part:
                        continue
                if part is None:
                    whole = True
                else:
                    taken |= part
                cur = out.setdefault(key, {})
                if part is None or cur.get(xform, set()) is None:
                    cur[xform] = None
                else:
                    cur[xform] = cur.get(xform, set()) | part
            if whole:
                continue
            total = cmds.polyEvaluate(xform, face=True)
            wanted = set(range(total)) if sel is None else set(sel)
            rest = wanted - taken
            if not rest:
                continue
            for key, faces, _ in self._material_split(xform, material_source):
                part = rest if faces is None else (rest & set(faces))
                if not part:
                    continue
                cur = out.setdefault(key, {})
                if cur.get(xform, set()) is not None:
                    cur[xform] = None if part == set(range(total)) else (cur.get(xform, set()) | part)
        return out

    def move_to_section(self, items, section, material_source="Name, then shader", prune=True):
        """Move meshes / faces into a section, each into the material group
        it was in (made there if needed). One Ctrl+Z."""
        with UndoChunk("Smart UDIM move to section"):
            by_key = self._material_keys_of(items, material_source)
            self._remove_items(items)
            for key, its in by_key.items():
                self._add_items(its, self.material_set(section, key, source="manual"))
            if prune:
                self.prune_empty_groups()
            self.sync_names()
        return sum(len(v) for v in by_key.values())

    def section_from_group(self, group, name=None, material_source="Name, then shader"):
        """A section for a group (reused if one is already linked to it),
        holding every mesh under the group. Later Scans sort new meshes under
        the group into it too. Returns (section, meshes moved)."""
        group = long_name(group)
        meshes, _ = self.meshes()
        inside = [m for m in meshes if m == group or m.startswith(group + "|")]
        with UndoChunk("Smart UDIM section from group"):
            sec = self.section_of_group(group)
            if sec is None:
                sec = self.create_section(name or self.section_name_for(group), group=group)
            elif name and parse_group_name(sec)["key"] != sanitize_key(name):
                sec = self.rename_section(sec, name)
            moved = self.move_to_section({m: None for m in inside}, sec, material_source) if inside else 0
        return sec, moved

    def rename_section(self, section, name):
        with UndoChunk("Smart UDIM rename section"):
            key = sanitize_key(name)
            cmds.setAttr(section + "." + UDIM_KEY, key, type="string")
            wanted = compose_section_set_name(key, _get(section, UDIM_TD, 100.0))
            return cmds.rename(section, _unique_set_name(wanted, section))

    def delete_section(self, section, material_source="Name, then shader"):
        """Remove a section. Its meshes go to the section of the group they
        live in, else the first other section. Returns the number moved."""
        others = [s for s in self.sections() if s != section]
        if not others:
            raise RuntimeError("That's the only section: there's nowhere for its meshes to go.")
        linked = [(s, _linked_group(s)) for s in others]
        # set names change as members move (sync_names), so hold on by uuid
        sec_id = cmds.ls(section, uuid=True)[0]
        mat_ids = [cmds.ls(m, uuid=True)[0] for m in self.materials(section)]
        with UndoChunk("Smart UDIM delete section"):
            items = {}
            for mat in self.materials(section):
                members, _ = expand_members(mat)
                for xform, faces in members.items():
                    if items.get(xform, set()) is None or faces is None:
                        items[xform] = None
                    else:
                        items[xform] = items.get(xform, set()) | faces
            by_target = {}
            for xform, faces in items.items():
                target = self._section_for(xform, linked) or others[0]
                by_target.setdefault(target, {})[xform] = faces
            target_ids = {cmds.ls(t, uuid=True)[0]: its for t, its in by_target.items()}
            for tid, its in target_ids.items():
                self.move_to_section(its, cmds.ls(tid)[0], material_source, prune=False)
            for uid in mat_ids + [sec_id]:
                found = cmds.ls(uid)
                if found:
                    cmds.delete(found[0])
            self.prune_empty_groups()
            self.sync_names()
        return len(items)

    def prune_empty_groups(self):
        """Delete material groups left with no members."""
        gone = 0
        for sec in self.sections():
            for mat in self.materials(sec):
                if not (cmds.sets(mat, q=True) or []):
                    cmds.delete(mat)
                    gone += 1
        return gone

    def tool_members(self, kind):
        """Meshes in a tracking set ('auto', 'laidout', 'problem')."""
        node = self.status_set(kind)
        return set(expand_members(node)[0]) if node else set()

    def update_tool_sets(self, add=None, remove=None):
        """add / remove: {kind: [meshes]}. Runs in the caller's undo chunk."""
        for kind, meshes in (remove or {}).items():
            node = self.status_set(kind)
            if not node or not meshes:
                continue
            members = expand_members(node)[0]
            gone = []
            for m in meshes:
                if m in members:
                    gone.append(m)
                    gone.extend(cmds.listRelatives(m, shapes=True, fullPath=True) or [])
            if gone:
                cmds.sets(gone, remove=node)
        for kind, meshes in (add or {}).items():
            meshes = [m for m in meshes if cmds.objExists(m)]
            if meshes:
                cmds.sets(meshes, add=self.status_set(kind, create=True))

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
                    "locked": bool(_get(mat, LAYOUT_LOCK, False)),
                    "orient": _get(mat, UDIM_ORIENT, "") or "",
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
                "unassigned": unassigned, "overlaps": overlaps, "status": self.uv_status()}

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


def detect_geometry_issues(meshes, progress=None):
    """{category: {transform: count}} for lamina, non-manifold, zero-area, n-gons."""
    issues = {"lamina": {}, "nonmanifold": {}, "zeroarea": {}, "ngons": {}}
    for xform in meshes:
        if progress:
            progress.item(short_name(xform))
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
# Smart UDIM - Auto UV (scorched-earth first pass)
# =============================================================================
#
# For assets that are modelled, named and grouped but not UV'd: score how laid
# out each mesh already is, re-unwrap the bad ones (worst first) and pack
# everything by section and material. Not meant to be final UVs: a clean,
# organised, usable base that shows what's left to do.
#
#   unwrap = normal-based projection -> sew soft edges back together -> cut
#            hard / sharp edges as seams -> Unfold3D auto-seams for closed
#            shells (spheres, pipes) -> relax -> extra cuts where shells are
#            still stretched -> relax again
#
# All the heavy lifting is Maya's own C++ (projection, sew/cut, Unfold3D,
# per-face areas); Python only decides what to run on.

AUTO_UV_STRETCH_TOL = math.log(4.0)  # face area ratio 4x off its shell's = stretched
AUTO_UV_KEEP_SCORE = 0.85


def _mesh_fn(xform):
    shapes = cmds.listRelatives(xform, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or []
    if not shapes:
        return None
    dag = get_dag_path(shapes[0])
    return om.MFnMesh(dag) if dag is not None else None


def _face_areas(xform, nf):
    """Per-face (world area, UV area) from Maya's C++ evaluator."""
    faces = "%s.f[0:%d]" % (xform, nf - 1)
    a3 = cmds.polyEvaluate(faces, worldFaceArea=True)
    auv = cmds.polyEvaluate(faces, uvFaceArea=True)
    if not isinstance(a3, list):
        a3, auv = [a3], [auv]
    return a3, auv


def uv_quality(xform, uv_set="map1", check_overlap=True):
    """How laid out a mesh already is: (score 0..1, reason).

    Score = share of the surface (by 3D area) whose UVs are fine. A face is
    bad if it has no / zero-area UVs, is folded over inside its shell, overlaps
    another face, or its area ratio is more than 4x off its shell's median.
    Comparing each face to *its own shell* keeps rectangulated / straightened
    shells and shells at different densities from counting as stretched.
    """
    fn = _mesh_fn(xform)
    if fn is None:
        return 0.0, "not a mesh"
    if uv_set not in fn.getUVSetNames() or fn.numUVs(uv_set) == 0:
        return 0.0, "no UVs"
    counts, ids = fn.getAssignedUVs(uv_set)
    nf = len(counts)
    if nf == 0:
        return 0.0, "no faces"
    if any(c == 0 for c in counts):
        return 0.0, "faces without UVs"
    if fn.currentUVSetName() != uv_set:
        # per-face UV areas read the current set; switching it is view state,
        # so don't leave stray undo steps between tool actions
        with NoUndo():
            cmds.polyUVSet(xform, currentUVSet=True, uvSet=uv_set)
    a3, auv = _face_areas(xform, nf)
    nshell, uv_shell = fn.getUvShellsIds(uv_set)
    us, vs = fn.getUVs(uv_set)
    us, vs = list(us), list(vs)
    ids = list(ids)
    face_shell, signs = [], []
    k = 0
    for c in counts:
        face_shell.append(uv_shell[ids[k]])
        area = 0.0
        for i in range(c):
            a = ids[k + i]
            b = ids[k + (i + 1) % c]
            area += us[a] * vs[b] - us[b] * vs[a]
        signs.append(area >= 0)
        k += c
    logs, wind = {}, {}
    for f in range(nf):
        s = face_shell[f]
        if a3[f] > 1e-12 and auv[f] > 0.0:
            logs.setdefault(s, []).append(math.log(auv[f] / a3[f]))
        wind[s] = wind.get(s, 0.0) + (a3[f] if signs[f] else -a3[f])
    med = {}
    for s, v in logs.items():
        v.sort()
        med[s] = v[len(v) // 2]
    total = sum(a3) or 1.0
    bad = 0.0
    for f in range(nf):
        if a3[f] <= 1e-12:
            continue
        s = face_shell[f]
        if auv[f] <= 0.0 or s not in med:
            bad += a3[f]
        elif abs(math.log(auv[f] / a3[f]) - med[s]) > AUTO_UV_STRETCH_TOL:
            bad += a3[f]
        elif signs[f] != (wind[s] >= 0):
            bad += a3[f]  # folded over inside its shell
    if check_overlap:
        overlap = cmds.polyUVOverlap("%s.f[0:%d]" % (xform, nf - 1), overlappingComponents=True) or []
        if overlap:
            idx = set()
            for comp in overlap:
                faces = _parse_face_spec(comp.partition(".")[2])
                if faces:
                    idx.update(faces)
            bad += sum(a3[i] for i in idx if i < nf)
    score = max(0.0, 1.0 - bad / total)
    if nf > 20 and nshell > nf * 0.5:
        return score * 0.5, "over-split (%d shells for %d faces)" % (nshell, nf)
    if score < 1.0:
        return score, "stretched / overlapping / folded UVs"
    return score, ""


def _edges_by_constraint(meshes, **constraint):
    """Edges matching a polySelectConstraint, via Maya's C++ selection
    filter (fast on big meshes). Leaves the constraint state reset."""
    if not meshes:
        return []
    cmds.select([m + ".e[*]" for m in meshes], replace=True)
    try:
        cmds.polySelectConstraint(mode=2, type=0x8000, **constraint)
        return cmds.ls(selection=True, flatten=True, long=True) or []
    finally:
        cmds.polySelectConstraint(mode=0, angle=0, smoothness=0, disable=True)


def _stretched_shell_faces(xform, uv_set="map1"):
    """Faces in shells that are still badly stretched or collapsed."""
    fn = _mesh_fn(xform)
    if fn is None or fn.numUVs(uv_set) == 0:
        return []
    counts, ids = fn.getAssignedUVs(uv_set)
    nf = len(counts)
    a3, auv = _face_areas(xform, nf)
    _, uv_shell = fn.getUvShellsIds(uv_set)
    shell_faces = {}
    k = 0
    for f, c in enumerate(counts):
        if c:
            shell_faces.setdefault(uv_shell[ids[k]], []).append(f)
        k += c
    bad = []
    for fs in shell_faces.values():
        area3 = sum(a3[f] for f in fs)
        if area3 > 1e-12 and sum(auv[f] for f in fs) < 1e-10 * max(area3, 1.0):
            bad.extend(fs)
            continue
        logs = sorted(math.log(auv[f] / a3[f]) for f in fs if a3[f] > 1e-12 and auv[f] > 0.0)
        if not logs:
            continue
        med = logs[len(logs) // 2]
        off = sum(1 for v in logs if abs(v - med) > AUTO_UV_STRETCH_TOL)
        if off > max(1, 0.05 * len(logs)):
            bad.extend(fs)
    return bad


def uv_footprints(xform, uv_set="map1", faces=None):
    """Where a mesh's UV shells sit, without touching the mesh (no current UV
    set switch): [(udim, (x0, y0, x1, y1) inside that tile, UV area)]. A shell
    crossing tiles gives one clipped box per tile it touches; shells outside
    the UDIM range (U 0-10, V >= 0) are left out."""
    fn = _mesh_fn(xform)
    if fn is None or uv_set not in fn.getUVSetNames() or fn.numUVs(uv_set) == 0:
        return []
    counts, ids = fn.getAssignedUVs(uv_set)
    _, shell_of = fn.getUvShellsIds(uv_set)
    us, vs = fn.getUVs(uv_set)
    boxes = {}
    k = 0
    for face, c in enumerate(counts):
        if c and (faces is None or face in faces):
            sid = shell_of[ids[k]]
            box = boxes.get(sid)
            if box is None:
                box = boxes[sid] = [1e30, 1e30, -1e30, -1e30, 0.0]
            area = 0.0
            for i in range(c):
                a, b = ids[k + i], ids[k + (i + 1) % c]
                area += us[a] * vs[b] - us[b] * vs[a]
                box[0] = min(box[0], us[a])
                box[1] = min(box[1], vs[a])
                box[2] = max(box[2], us[a])
                box[3] = max(box[3], vs[a])
            box[4] += abs(area) * 0.5
        k += c
    out = []
    for u0, v0, u1, v1, area in boxes.values():
        if u0 < -1e-6 or v0 < -1e-6 or u1 > 10.0 + 1e-6:
            continue
        tus = range(int(math.floor(u0 + 1e-6)), int(math.floor(max(u0, u1 - 1e-6))) + 1)
        tvs = range(int(math.floor(v0 + 1e-6)), int(math.floor(max(v0, v1 - 1e-6))) + 1)
        n = float(len(tus) * len(tvs))
        for tu in tus:
            for tv in tvs:
                if 0 <= tu <= 9:
                    out.append((1001 + tu + 10 * tv, (max(0.0, u0 - tu), max(0.0, v0 - tv), min(1.0, u1 - tu),
                                                      min(1.0, v1 - tv)), area / n))
    return out


UV_STATE_ORDER = ("needs", "problem", "unknown", "good", "keep", "auto", "laidout", "handsoff")
UV_STATE_INFO = {  # state: (label, colour, what it means)
    "needs": ("Needs UVs", "#e8c23a", "No usable UVs yet: Auto UV will unwrap these."),
    "problem": ("Problem", "#e05050", "Auto UV failed or the result still needs a look (or the mesh is "
                                      "instanced). See the reason in step 6."),
    "unknown": ("Not checked", "#8a8a8a", "Not scored yet: press Check UVs."),
    "good": ("Good UVs", "#57c785", "Already laid out well enough, so Auto UV keeps them."),
    "keep": ("Keep UVs", "#2fa84f", "You marked these Keep UVs: never re-unwrapped."),
    "auto": ("Auto UV'd", "#a4d65e", "Unwrapped by Auto UV."),
    "laidout": ("Laid out", "#5aa9e6", "Placed by Smart Layout."),
    "handsoff": ("Hands off", "#3c5fd0", "You marked these Hands off: never touched."),
}
UV_COLOURS_ATTR = "unlokUVColours"   # bool on the root set: colours are on
ORIG_SHADING_ATTR = "unlokOrigShading"  # JSON on a mesh shape: its real shading while coloured


def uv_states(asset, scores=None, keep_score=AUTO_UV_KEEP_SCORE):
    """{mesh: state} (see UV_STATE_INFO). Marks and tracking sets come from
    the scene; 'good' vs 'needs' from scores {mesh: 0..1} (else 'unknown')."""
    meshes, instanced = asset.meshes()
    status = asset.uv_status()
    auto, laid, prob = asset.tool_members("auto"), asset.tool_members("laidout"), asset.tool_members("problem")
    out = {}
    for m in meshes:
        if status.get(m) == "handsoff":
            out[m] = "handsoff"
        elif m in laid:
            out[m] = "laidout"
        elif m in prob:
            out[m] = "problem"
        elif m in auto:
            out[m] = "auto"
        elif status.get(m) == "keep":
            out[m] = "keep"
        elif scores and m in scores and scores[m] is not None:
            out[m] = "good" if scores[m] >= keep_score else "needs"
        else:
            out[m] = "unknown"
    for m in instanced:
        out[m] = "problem"
    return out


def _sg_key(sg):
    mats = cmds.listConnections(sg + ".surfaceShader", source=True, destination=False) or []
    return sanitize_key(mats[0] if mats else sg)


def _shading_of(xform):
    """{shading group: face ranges or None (whole mesh)} for a mesh."""
    shapes = cmds.listRelatives(xform, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or []
    if not shapes:
        return {}
    dag = get_dag_path(shapes[0])
    try:
        sgs, ids = om.MFnMesh(dag).getConnectedShaders(dag.instanceNumber())
    except RuntimeError:
        return {}
    names = [om.MFnDependencyNode(sgs[i]).name() for i in range(len(sgs))]
    faces = {}
    for f, sid in enumerate(ids):
        if 0 <= sid < len(names):
            faces.setdefault(names[sid], []).append(f)
    if len(faces) == 1 and len(list(faces.values())[0]) == len(ids):
        return {list(faces)[0]: None}
    return {sg: face_ranges(fs) for sg, fs in faces.items()}


def _preview_sg(state):
    sg = "unlokUV_%s_SG" % state
    if cmds.objExists(sg):
        return sg
    mat = cmds.shadingNode("lambert", asShader=True, name="unlokUV_%s_MAT" % state)
    col = UV_STATE_INFO[state][1]
    cmds.setAttr(mat + ".color", int(col[1:3], 16) / 255.0, int(col[3:5], 16) / 255.0, int(col[5:7], 16) / 255.0,
                 type="double3")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=sg)
    cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader")
    return sg


def _is_preview_sg(sg):
    return sg.startswith("unlokUV_") and sg.endswith("_SG")


def show_uv_colours(asset, states):
    """Colour meshes by state with preview materials. Each mesh's real
    shading is stored on its shape first and comes back with
    hide_uv_colours. Kept out of undo: it's a display aid. Instanced meshes
    are left alone (shading is shared between instances)."""
    with NoUndo():
        by_state = {}
        for mesh, state in states.items():
            shapes = cmds.listRelatives(mesh, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or []
            if not shapes or len(cmds.ls(shapes[0], allPaths=True) or []) > 1:
                continue
            shape = shapes[0]
            if not cmds.attributeQuery(ORIG_SHADING_ATTR, node=shape, exists=True):
                orig = _shading_of(mesh)
                if all(_is_preview_sg(sg) for sg in orig):
                    continue  # nothing real to remember
                cmds.addAttr(shape, longName=ORIG_SHADING_ATTR, dataType="string")
                cmds.setAttr(shape + "." + ORIG_SHADING_ATTR, json.dumps(orig, sort_keys=True), type="string")
            by_state.setdefault(state, []).append(mesh)
        for state, meshes in by_state.items():
            cmds.sets(meshes, edit=True, forceElement=_preview_sg(state))
        root = asset.root_set()
        if root:
            if not cmds.attributeQuery(UV_COLOURS_ATTR, node=root, exists=True):
                cmds.addAttr(root, longName=UV_COLOURS_ATTR, attributeType="bool")
            cmds.setAttr(root + "." + UV_COLOURS_ATTR, True)
    return sum(len(v) for v in by_state.values())


def hide_uv_colours(asset=None):
    """Put every coloured mesh's real shading back. A mesh you re-shaded
    yourself while colours were on keeps your new shading."""
    restored = 0
    with NoUndo():
        for shape in cmds.ls(type="mesh", long=True) or []:
            if not cmds.attributeQuery(ORIG_SHADING_ATTR, node=shape, exists=True):
                continue
            xform = long_name(cmds.listRelatives(shape, parent=True, fullPath=True)[0])
            try:
                orig = json.loads(cmds.getAttr(shape + "." + ORIG_SHADING_ATTR) or "{}")
            except ValueError:
                orig = {}
            now = _shading_of(xform)
            if now and all(_is_preview_sg(sg) for sg in now):
                for sg, ranges in orig.items():
                    target = sg if cmds.objExists(sg) else "initialShadingGroup"
                    comps = [xform] if ranges is None else ["%s.%s" % (xform, r) for r in ranges]
                    cmds.sets(comps, edit=True, forceElement=target)
                restored += 1
            cmds.deleteAttr(shape + "." + ORIG_SHADING_ATTR)
        for state in UV_STATE_INFO:
            sg = "unlokUV_%s_SG" % state
            if cmds.objExists(sg) and not (cmds.sets(sg, q=True) or []):
                mats = cmds.listConnections(sg + ".surfaceShader", source=True, destination=False) or []
                cmds.delete([sg] + mats)
        root = asset.root_set() if asset else None
        if root and cmds.attributeQuery(UV_COLOURS_ATTR, node=root, exists=True):
            cmds.setAttr(root + "." + UV_COLOURS_ATTR, False)
    return restored


def uv_colours_on(asset):
    root = asset.root_set() if asset else None
    return bool(root and _get(root, UV_COLOURS_ATTR, False))


def backup_uvs(meshes, uv_set="map1", backup_set="map1_backup", progress=None):
    """Copy uv_set to backup_set on meshes that have UVs and no backup yet
    (an existing backup is never overwritten, so re-runs keep the original)."""
    made = 0
    for xform in meshes:
        if progress:
            progress.item(short_name(xform))
        fn = _mesh_fn(xform)
        if fn is None or uv_set not in fn.getUVSetNames() or fn.numUVs(uv_set) == 0:
            continue
        if backup_set in fn.getUVSetNames():
            continue
        cmds.polyUVSet(xform, copy=True, uvSet=uv_set, newUVSet=backup_set)
        made += 1
    return made


def restore_uvs(meshes, uv_set="map1", backup_set="map1_backup"):
    """Copy backup_set back over uv_set. Returns how many meshes had one."""
    restored = 0
    with UndoChunk("Smart UDIM restore UVs"):
        for xform in meshes:
            fn = _mesh_fn(xform)
            if fn is None or backup_set not in fn.getUVSetNames():
                continue
            cmds.polyUVSet(xform, copy=True, uvSet=backup_set, newUVSet=uv_set)
            cmds.polyUVSet(xform, currentUVSet=True, uvSet=uv_set)
            restored += 1
    return restored


def _unwrap_batches(meshes, budget=8000):
    """Split meshes into batches of about `budget` faces, so the Unfold3D
    calls report progress (and can be cancelled) between batches. A mesh
    bigger than the budget is a batch of its own. [(meshes, faces)]."""
    batches, cur, size = [], [], 0
    for m in meshes:
        n = cmds.polyEvaluate(m, face=True) or 0
        if cur and size + n > budget:
            batches.append((cur, size))
            cur, size = [], 0
        cur.append(m)
        size += n
    if cur:
        batches.append((cur, size))
    return batches


def _batch_label(batch):
    names, faces = batch
    if len(names) == 1:
        return "%s (%s faces)" % (short_name(names[0]), "{:,}".format(faces))
    return "%d meshes (%s faces)" % (len(names), "{:,}".format(faces))


def auto_unwrap(meshes, hard_angle=40.0, passes=2, progress=None, on_unfolded=None):
    """Unwrap meshes (see the section comment). Returns {mesh: error} for any
    that failed; one bad mesh never stops the rest. With a Progress, it
    reports stages 'project', 'seams', 'unfold' and 'fix'."""
    failed = {}
    if not meshes:
        return failed
    pr = progress or Progress("", [])
    cmds.loadPlugin("Unfold3D", quiet=True)
    ok = []
    pr.stage("project", len(meshes), "Projecting")
    for xform in meshes:  # projection works one object at a time
        pr.item(short_name(xform), force=(cmds.polyEvaluate(xform, face=True) or 0) > 5000)
        try:
            cmds.polyAutoProjection(xform + ".f[*]", planes=6, layoutMethod=0, layout=0, optimize=1,
                                    percentageSpace=0.2, scaleMode=1, constructionHistory=False)
            ok.append(xform)
        except Exception as exc:
            failed[xform] = "projection failed: %s" % exc
    pr.stage("seams", len(ok) + 1, "Cutting seams")
    pr.item("finding hard and sharp edges")
    hard = set(_edges_by_constraint(ok, smoothness=1))
    sharp = set(_edges_by_constraint(ok, angle=1, anglebound=(hard_angle, 180.0)))
    soft = [e for e in _edges_by_constraint(ok, angle=1, anglebound=(0.0, hard_angle)) if e not in hard]
    by_soft, by_seam = {}, {}
    for e in soft:
        by_soft.setdefault(e.split(".")[0], []).append(e)
    for e in hard | sharp:
        by_seam.setdefault(e.split(".")[0], []).append(e)
    for xform in ok:
        pr.item(short_name(xform))
        try:
            if by_soft.get(xform):
                cmds.polyMapSewMove(by_soft[xform], constructionHistory=False)
            if by_seam.get(xform):
                cmds.polyMapCut(by_seam[xform], constructionHistory=False)
        except Exception as exc:
            failed[xform] = "seams failed: %s" % exc
    ok = [m for m in ok if m not in failed]

    def unfold(targets):
        try:
            cmds.u3dUnfold(targets, iterations=1, pack=0, borderintersection=1, triangleflip=1,
                           mapsize=1024, roomspace=0)
        except Exception:
            for m in targets:  # isolate the culprit
                try:
                    cmds.u3dUnfold(m, iterations=1, pack=0, borderintersection=1, triangleflip=1,
                                   mapsize=1024, roomspace=0)
                except Exception as exc:
                    failed[m] = "unfold failed: %s" % exc

    batches = _unwrap_batches(ok)
    pr.stage("unfold", sum(n for _, n in batches), "Unfolding", items=len(batches))
    for batch in batches:  # batches, so progress moves (and Esc works) on big assets
        pr.item(_batch_label(batch), weight=batch[1], force=True)
        try:
            cmds.select(batch[0], replace=True)
            cmds.u3dAutoSeam(splitShells=0, cutPipes=1)  # closed shells need at least one seam
        except Exception:
            pass
        unfold(batch[0])
        if on_unfolded:
            on_unfolded([m for m in batch[0] if m not in failed])
    for i in range(passes):
        pr.stage("fix", len(ok), "Fixing stretched shells (pass %d of %d)" % (i + 1, passes))
        bad = []
        for m in ok:
            pr.item(short_name(m))
            if m in failed:
                continue
            bad.extend("%s.f[%s]" % (m, r[2:-1]) for r in face_ranges(_stretched_shell_faces(m)))
        if not bad:
            break
        by_mesh = {}
        for face in bad:
            by_mesh.setdefault(face.split(".")[0], []).append(face)
        for batch in _unwrap_batches(sorted(by_mesh)):
            pr.detail = "re-unfolding %s" % _batch_label(batch)
            pr.update(force=True)
            try:
                cmds.select([f for m in batch[0] for f in by_mesh[m]], replace=True)
                cmds.u3dAutoSeam(splitShells=0, cutPipes=1)
            except Exception:
                pass
            unfold(batch[0])
    return failed


def _pack_one_tile(shells, pad):
    """Fit a group's shells into one tile at even texel density, as big as
    possible. Returns ({id(shell): (x, y, k, angle)}, scale) or (None, 0).

    Every shell keeps its own 3D-to-UV ratio (k = sqrt(3D area / UV area)),
    times one scale for the whole group, found by bisection: the skyline
    packer (_TilePacker) says whether a scale fits. Shells lie on their main
    axis and may turn 90 degrees.
    """
    if not shells:
        return {}, 0.0
    base = []
    for sh in shells:
        angle, w0, h0 = sh.dims["axis"]
        k = math.sqrt(sh.area3d / sh.area_uv)
        base.append((sh, k, angle, w0 * k, h0 * k))
    base.sort(key=lambda t: (-round(max(t[3], t[4]), 9), -t[3] * t[4], t[0].mesh, t[0].uv_ids[0]))
    usable = 1.0 - 2.0 * pad
    area = sum(w * h for _, _, _, w, h in base) or 1e-12
    longest = max(max(w, h) for _, _, _, w, h in base) or 1e-12
    hi = min(math.sqrt(usable * usable / area), (usable - 1e-9) / longest)

    def attempt(scale):
        pk = _TilePacker((0, 0), pad)
        out = {}
        for sh, k, angle, w, h in base:
            rw, rh = w * scale + pad, h * scale + pad
            spot, turned = pk.find(rw, rh), False
            if abs(rw - rh) > 1e-12:
                alt = pk.find(rh, rw)
                if alt is not None and (spot is None or alt[0] < spot[0]):
                    spot, turned = alt, True
            if spot is None:
                return None
            pk.place(spot, rh if turned else rw, rw if turned else rh)
            out[id(sh)] = (spot[3], spot[4], k * scale, angle + (math.pi / 2.0 if turned else 0.0))
        return out

    best = attempt(hi)
    if best is not None:
        return best, hi
    lo = 0.0
    for _ in range(16):  # ~0.002% precision on the scale
        mid = (lo + hi) / 2.0
        got = attempt(mid)
        if got is None:
            hi = mid
        else:
            lo, best = mid, got
    return (best, lo) if best is not None else (None, 0.0)


def pack_udims(asset, exclude=(), resolution=None, padding=8.0 / 2048, avoid_tiles=(), progress=None,
               uv_set="map1", only_groups=None):
    """Pack every material group into its own UDIM tile.

    Sections take bands of rows (in section order); each material keeps the
    same column in every section, so e.g. glass sits in the same spot for
    every building. Texel density is even within a group. Pure maths plus
    one undoable UV write per mesh: about a second where Unfold3D's
    u3dLayout took 30+ s on a 141-mesh building. (resolution: unused, kept
    for old callers.)
    """
    exclude = set(exclude)
    sections = asset.sections()
    keys = sorted(set(_get(m, UDIM_KEY) or parse_group_name(m)["key"]
                      for s in sections for m in asset.materials(s)))
    column = {k: i for i, k in enumerate(keys)}
    rows_per_section = max(1, (len(keys) + 9) // 10)
    first_row = (max((t - 1001) // 10 for t in avoid_tiles) + 1) if avoid_tiles else 0  # above hands-off tiles
    pad = float(padding)
    unit_scale = _UNIT_TO_M.get(cmds.currentUnit(q=True, linear=True), 0.01) ** 2
    caches, claimed = {}, set()
    placed = []
    moves = {}  # mesh -> [(shell, tu, tv, x, y, k, angle)]
    for si, sec in enumerate(sections):
        for mat in asset.materials(sec):
            if only_groups is not None and mat not in only_groups:
                continue
            members, _ = expand_members(mat)
            shells = []
            for xform, faces in members.items():
                if xform in exclude:
                    continue
                got, _ = _read_shells(xform, faces, uv_set, unit_scale, caches, claimed)
                shells.extend(got or [])
            if not shells:
                continue
            if progress:
                progress.item("%s (%d shell%s)" % (short_name(mat), len(shells), "" if len(shells) == 1 else "s"))
            col = column[_get(mat, UDIM_KEY) or parse_group_name(mat)["key"]]
            u0 = col % 10
            v0 = first_row + si * rows_per_section + col // 10
            spots, _ = _pack_one_tile(shells, pad)
            if spots is None:  # too many pieces to fit even tiny: leave this group as it is
                continue
            for sh in shells:
                x, y, k, angle = spots[id(sh)]
                moves.setdefault(sh.mesh, []).append((sh, u0, v0, x, y, k, angle))
            placed.append((mat, 1001 + u0 + 10 * v0))
    for xform, items in moves.items():
        fn = _mesh_fn(xform)
        us, vs = fn.getUVs(uv_set)
        us, vs = list(us), list(vs)
        for sh, tu, tv, x, y, k, angle in items:
            _place_shell(us, vs, sh, tu, tv, x, y, k, angle)
        write_uvs(xform, uv_set, us, vs)
    pack_udims.last_moved = sorted(moves)
    return placed


AUTO_UV_STAGES = [("score", 8), ("clean", 4), ("backup", 2), ("project", 12), ("seams", 8), ("unfold", 40),
                  ("fix", 10), ("pack", 12), ("check", 4)]


def run_auto_uv(asset, uv_set="map1", backup=True, backup_set="map1_backup", keep_score=AUTO_UV_KEEP_SCORE,
                hard_angle=40.0, clean_first=True, pack=True, analyse_only=False, packing=None,
                progress_callback=None, only=None, colours=False):
    """The whole Auto UV pass on an asset, as one Ctrl+Z. (packing: unused
    since packing went pure-maths; kept for old callers.)

    Returns {"rows": [{mesh, before, reason, after, action}], "timing": {...},
    "tiles": [(material set, udim)], "backups": n}. Rows are worst first.
    Progress shows in Maya's progress bar and through progress_callback
    (fraction, text). Esc stops it at the next mesh: the result then has
    "cancelled" (where it stopped) and Ctrl+Z undoes what was done.

    only: just these meshes (e.g. a selected group), packing only the
    groups they're in. colours: recolour meshes as they're unwrapped (see
    show_uv_colours). Unwrapped meshes go into the asset's Auto UV'd set,
    failures and poor results into its Problem set, and anything packed
    leaves its Laid out set.
    """
    pr = Progress("Auto UV" if not analyse_only else "Analyse UVs",
                  AUTO_UV_STAGES if not analyse_only else [("score", 1)], progress_callback)
    try:
        with pr:
            pr.refresh_view = bool(colours)
            return _run_auto_uv(asset, uv_set, backup, backup_set, keep_score, hard_angle, clean_first, pack,
                                analyse_only, packing, pr, only, colours)
    except Cancelled:
        return {"rows": [], "timing": {"total": time.time() - pr.t0}, "tiles": [], "backups": 0,
                "cancelled": pr.where()}


def _run_auto_uv(asset, uv_set, backup, backup_set, keep_score, hard_angle, clean_first, pack, analyse_only,
                 packing, pr, only=None, colours=False):
    timing = {}
    t0 = time.time()
    meshes, instanced = asset.meshes()
    if only is not None:
        only = set(only)
        meshes = [m for m in meshes if m in only]
        instanced = [m for m in instanced if m in only]
    status = asset.uv_status()
    handsoff = [m for m in meshes if status.get(m) == "handsoff"]  # not even scored: never touched
    marked_keep = set(m for m in meshes if status.get(m) == "keep")
    meshes = [m for m in meshes if status.get(m) != "handsoff"]
    rows = []
    scores = {}
    pr.stage("score", len(meshes), "Scoring UVs")
    for m in meshes:
        pr.item(short_name(m))
        try:
            scores[m] = uv_quality(m, uv_set)
        except Exception as exc:
            scores[m] = (0.0, "couldn't score: %s" % exc)
    timing["score"] = time.time() - t0
    order = sorted(meshes, key=lambda m: scores[m][0])
    todo = [m for m in order if scores[m][0] < keep_score and m not in marked_keep]
    tail = [{"mesh": m, "before": None, "reason": "marked Hands off: never unwrapped or moved", "after": None,
             "action": "hands off"} for m in handsoff]
    tail += [{"mesh": m, "before": None, "reason": "instanced", "after": None, "action": "skip"} for m in instanced]
    if analyse_only:
        rows = [{"mesh": m, "before": scores[m][0], "reason": scores[m][1], "after": None,
                 "action": "keep UVs" if m in marked_keep else ("will unwrap" if m in todo else "keep")}
                for m in order]
        return {"rows": rows + tail, "timing": timing, "tiles": [], "backups": 0}

    backups = 0
    failed = {}
    tiles = []
    with UndoChunk("Smart UDIM Auto UV"), PreserveSelection():
        if clean_first and todo:
            t = time.time()
            pr.stage("clean", len(todo), "Checking geometry")
            issues = detect_geometry_issues(todo, pr)
            dirty = sorted(set(issues["lamina"]) | set(issues["nonmanifold"]) | set(issues["zeroarea"]))
            if dirty:
                _run_cleanup(dirty, True, True, True)
            timing["clean"] = time.time() - t
        if backup:
            pr.stage("backup", len(meshes), "Backing up UVs")
            backups = backup_uvs(meshes, uv_set, backup_set, pr)
        for m in meshes:
            fn = _mesh_fn(m)
            if fn is not None and uv_set in fn.getUVSetNames():
                if fn.currentUVSetName() != uv_set:
                    cmds.polyUVSet(m, currentUVSet=True, uvSet=uv_set)
            elif fn is not None:
                cmds.polyUVSet(m, create=True, uvSet=uv_set)
                cmds.polyUVSet(m, currentUVSet=True, uvSet=uv_set)
        t = time.time()
        live = (lambda done: show_uv_colours(asset, {m: "auto" for m in done})) if colours else None
        failed = auto_unwrap(todo, hard_angle=hard_angle, progress=pr, on_unfolded=live)
        timing["unwrap"] = time.time() - t
        if pack:
            t = time.time()
            avoid = set()
            all_handsoff = [m for m, st in status.items() if st == "handsoff"]  # not just the selection's
            for m in all_handsoff:
                avoid.update(t for t, _, _ in uv_footprints(m, uv_set))
            exclude = set(failed) | set(instanced) | set(all_handsoff)
            groups = None
            if only is not None:  # pack just the groups these meshes are in, around their finished members
                done = set(m for m in meshes if m not in failed)
                groups = set(mat for mat in asset.all_material_sets()
                             if done & set(expand_members(mat)[0]))
                ready = asset.tool_members("auto") | asset.tool_members("laidout") | marked_keep | done
                for mat in groups:
                    for m in expand_members(mat)[0]:
                        if m in exclude or m in ready:  # hands off is already in exclude
                            continue
                        if uv_quality(m, uv_set, check_overlap=False)[0] < keep_score:
                            exclude.add(m)
            pr.stage("pack", len(groups) if groups is not None else len(asset.all_material_sets()),
                     "Packing into UDIMs")
            tiles = pack_udims(asset, exclude=exclude, avoid_tiles=avoid, progress=pr, uv_set=uv_set,
                               only_groups=groups)
            asset.update_tool_sets(remove={"laidout": getattr(pack_udims, "last_moved", [])})
            timing["pack"] = time.time() - t
        # scoring can switch a mesh's current UV set: keep it inside the chunk so
        # one Ctrl+Z still undoes the whole run
        pr.stage("check", len(order), "Checking the result")
        for m in order:
            pr.item(short_name(m))
            if m in failed:
                rows.append({"mesh": m, "before": scores[m][0], "reason": failed[m], "after": None,
                             "action": "failed"})
                continue
            after = uv_quality(m, uv_set, check_overlap=pack)[0] if (m in todo or pack) else scores[m][0]
            action = "unwrapped" if m in todo else "kept"
            if after < keep_score:
                action = "check" if m in todo else "kept (check)"
            if m in marked_keep:
                action = "keep UVs"
            rows.append({"mesh": m, "before": scores[m][0], "reason": scores[m][1], "after": after,
                         "action": action})
        unwrapped = [r["mesh"] for r in rows if r["action"] == "unwrapped"]
        trouble = [r["mesh"] for r in rows if r["action"] in ("failed", "check")] + list(instanced)
        asset.update_tool_sets(add={"auto": unwrapped, "problem": trouble},
                               remove={"problem": unwrapped, "auto": [m for m in trouble if m in failed]})
    rows += tail
    timing["total"] = time.time() - t0
    return {"rows": rows, "timing": timing, "tiles": tiles, "backups": backups}


# =============================================================================
# Smart UDIM - smart layout (texel density, planning, packing, locks)
# =============================================================================
#
#   collect_shells -> plan_layout -> apply_layout
#
# collect_shells reads every UV shell of every (unlocked) material group once:
# its 3D area, UV area and UV points. plan_layout is pure math on those (so it
# can re-run in milliseconds while settings change): it scales each shell to the
# exact target texel density, rotates it onto its main axis and shelf-packs the
# shells tile by tile (tallest first, so similar pieces end up side by side).
# A group just flows into the next tile when one is full; no shell ever crosses
# a tile border. apply_layout writes the result through a scratch UV set and an
# undoable copy, so the whole layout is one Ctrl+Z.

LAYOUT_LOCK = "unlokUdimLock"
LAYOUT_TILES = "unlokUdimTiles"
LAYOUT_PRINT = "unlokUdimPrint"
LAYOUT_MODES = ("Fixed density", "Fit to tiles")
MAP_SIZES = ("1024", "2048", "4096", "8192")
# Main axis: longest direction along U (lying flat). Upright: world up along +V
# (brick courses stay horizontal, walls read upright). Keep: never rotate.
ORIENTATIONS = ("Main axis", "Upright", "Keep")
HANDSOFF_MODES = ("Pack around them", "Reserve their tiles")
_ORIENT_MODE = {"Main axis": "axis", "Upright": "up", "Keep": "keep"}
_UNIT_TO_M = {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0, "in": 0.0254, "ft": 0.3048, "yd": 0.9144,
              "mi": 1609.344}

LAYOUT_DEFAULTS = {
    "texel_density": 1024.0,  # px per metre
    "map_size": "4096",
    "mode": "Fixed density",
    "max_tiles": 10,
    "padding_px": 8,
    "orientation": "Main axis",
    "new_row_per_section": True,
    "auto_compensate": True,
    "growth": 0.0,  # spare room reserved per group (0.1 = 10%)
    "handsoff_tiles": "Pack around them",
}


class LayoutShell(object):
    """One UV shell of one material group (sizes before density scaling).

    dims[mode] = (angle, w0, h0) for each orientation mode ('axis', 'up',
    'keep'), so switching orientation is just a re-plan.
    """
    __slots__ = ("mesh", "uv_ids", "area3d", "area_uv", "cx", "cy", "dims", "group")

    def __init__(self, mesh, uv_ids, area3d, area_uv, pts, up_dir=None):
        self.mesh = mesh
        self.uv_ids = uv_ids
        self.area3d = area3d
        self.area_uv = area_uv
        n = float(len(pts))
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        self.cx, self.cy = cx, cy

        def box(angle):
            ca, sa = math.cos(angle), math.sin(angle)
            xs = [(p[0] - cx) * ca - (p[1] - cy) * sa for p in pts]
            ys = [(p[0] - cx) * sa + (p[1] - cy) * ca for p in pts]
            return max(xs) - min(xs), max(ys) - min(ys)

        axis = 0.0
        if len(pts) > 2:
            sxx = sum((p[0] - cx) ** 2 for p in pts)
            syy = sum((p[1] - cy) ** 2 for p in pts)
            sxy = sum((p[0] - cx) * (p[1] - cy) for p in pts)
            axis = -0.5 * math.atan2(2.0 * sxy, sxx - syy)  # main axis onto U
        w, h = box(axis)
        if h > w:  # lie flat: shelves pack wide shells best
            axis += math.pi / 2.0
            w, h = h, w
        self.dims = {"axis": (axis, w, h), "keep": (0.0,) + box(0.0)}
        if up_dir is not None:
            up = math.pi / 2.0 - math.atan2(up_dir[1], up_dir[0])  # world up -> +V
            self.dims["up"] = (up,) + box(up)
        else:  # flat (floor / roof) pieces have no up: fall back to the main axis
            self.dims["up"] = self.dims["axis"]
        self.group = None


def _mesh_cache(xform, uv_set, unit_scale):
    fn = _mesh_fn(xform)
    if fn is None or uv_set not in fn.getUVSetNames() or fn.numUVs(uv_set) == 0:
        return None
    counts, ids = fn.getAssignedUVs(uv_set)
    nf = len(counts)
    if nf == 0 or any(c == 0 for c in counts):
        return None
    if fn.currentUVSetName() != uv_set:
        with NoUndo():
            cmds.polyUVSet(xform, currentUVSet=True, uvSet=uv_set)
    a3, auv = _face_areas(xform, nf)
    _, uv_shell = fn.getUvShellsIds(uv_set)
    us, vs = fn.getUVs(uv_set)
    face_uvs = []
    k = 0
    ids = list(ids)
    for c in counts:
        face_uvs.append(ids[k:k + c])
        k += c
    vcounts, connects = fn.getVertices()
    face_vtx = []
    k = 0
    connects = list(connects)
    for c in vcounts:
        face_vtx.append(connects[k:k + c])
        k += c
    heights = [pt.y for pt in fn.getPoints(om.MSpace.kWorld)]
    return {"a3": [a * unit_scale for a in a3], "auv": auv, "uv_shell": list(uv_shell), "us": list(us),
            "vs": list(vs), "face_uvs": face_uvs, "face_vtx": face_vtx, "heights": heights, "nf": nf}


def _shell_up_direction(cache, faces):
    """UV direction in which world height increases across a shell, or None
    for flat (horizontal) pieces."""
    us, vs, hs = cache["us"], cache["vs"], cache["heights"]
    du_acc = dv_acc = 0.0
    total = 0.0
    for f in faces:
        uvs, vtx = cache["face_uvs"][f], cache["face_vtx"][f]
        c = len(uvs)
        for i in range(c):
            a, b = i, (i + 1) % c
            dy = hs[vtx[b]] - hs[vtx[a]]
            du, dv = us[uvs[b]] - us[uvs[a]], vs[uvs[b]] - vs[uvs[a]]
            du_acc += du * dy
            dv_acc += dv * dy
            total += abs(dy) * math.hypot(du, dv)
    mag = math.hypot(du_acc, dv_acc)
    if total <= 1e-12 or mag < 0.05 * total:
        return None
    return du_acc / mag, dv_acc / mag


def _group_print(members):
    """Fingerprint of a group's geometry, to spot changes since the last layout."""
    total_faces = 0
    area = 0.0
    for xform, faces in sorted(members.items()):
        n = cmds.polyEvaluate(xform, face=True) if faces is None else len(faces)
        total_faces += n
        try:
            area += cmds.polyEvaluate(xform, worldArea=True) if faces is None else 0.0
        except Exception:
            pass
    return "%d:%.4g" % (total_faces, area)


def _read_shells(xform, faces, uv_set, unit_scale, caches, claimed):
    """LayoutShells of one set member (whole mesh or some faces). Returns
    (shells, conflicts), or (None, 0) when the mesh has no usable UVs. A
    shell already claimed by an earlier group is skipped and counted."""
    if xform not in caches:
        caches[xform] = _mesh_cache(xform, uv_set, unit_scale)
    cache = caches[xform]
    if cache is None:
        return None, 0
    by_shell = {}
    for f in (range(cache["nf"]) if faces is None else sorted(faces)):
        if f < cache["nf"] and cache["face_uvs"][f]:
            by_shell.setdefault(cache["uv_shell"][cache["face_uvs"][f][0]], []).append(f)
    shells, conflicts = [], 0
    for shell, fs in by_shell.items():
        if (xform, shell) in claimed:
            conflicts += 1
            continue
        claimed.add((xform, shell))
        uv_ids = sorted(set(u for f in fs for u in cache["face_uvs"][f]))
        a3 = sum(cache["a3"][f] for f in fs)
        auv = sum(cache["auv"][f] for f in fs)
        if a3 <= 1e-12 or auv <= 1e-14:
            continue
        pts = [(cache["us"][u], cache["vs"][u]) for u in uv_ids]
        shells.append(LayoutShell(xform, uv_ids, a3, auv, pts, _shell_up_direction(cache, fs)))
    return shells, conflicts


def collect_shells(asset, uv_set="map1", rotate=True, exclude=()):  # rotate: kept for old callers
    """Read every UV shell of every material group.

    Returns {"groups": [group dict...], "locked": [...], "skipped": [meshes],
    "conflicts": n}. Locked groups are listed with their tiles but not read.
    """
    unit_scale = _UNIT_TO_M.get(cmds.currentUnit(q=True, linear=True), 0.01) ** 2
    exclude = set(exclude)
    handsoff = set(m for m, st in asset.uv_status().items() if st == "handsoff")
    fixed = []  # hands-off shells: [{"set", "key", "mesh", "udim", "box", "area"}]
    caches = {}
    claimed = set()
    groups, locked, skipped = [], [], set()
    conflicts = 0
    for si, sec in enumerate(asset.sections()):
        sec_td = _get(sec, UDIM_TD, 100.0)
        for mat in asset.materials(sec):
            key = _get(mat, UDIM_KEY) or parse_group_name(mat)["key"]
            members, _ = expand_members(mat)
            info = {"set": mat, "uuid": cmds.ls(mat, uuid=True)[0], "key": key, "section": sec,
                    "section_index": si,
                    "td": _get(mat, UDIM_TD, 100.0) * sec_td / 100.0, "shells": [],
                    "print": _group_print(members), "old_print": _get(mat, LAYOUT_PRINT, "") or "",
                    "stack": bool(_get(mat, UDIM_STACK, False)), "orient": _get(mat, UDIM_ORIENT, "") or None,
                    "tiles": [int(t) for t in (_get(mat, LAYOUT_TILES, "") or "").split(",") if t.strip()],
                    "fixed": []}
            if _get(mat, LAYOUT_LOCK, False):
                locked.append(info)
                continue
            for xform, faces in members.items():
                if xform in exclude:
                    continue
                if xform in handsoff:
                    for udim, box, area in uv_footprints(xform, uv_set, faces):
                        info["fixed"].append({"set": mat, "key": key, "mesh": xform, "udim": udim, "box": box,
                                              "area": area})
                    continue
                shells, clash = _read_shells(xform, faces, uv_set, unit_scale, caches, claimed)
                if shells is None:
                    skipped.add(xform)
                    continue
                conflicts += clash
                for shell_obj in shells:
                    shell_obj.group = mat
                info["shells"].extend(shells)
            groups.append(info)
            fixed.extend(info["fixed"])
    return {"groups": groups, "locked": locked, "skipped": sorted(skipped), "conflicts": conflicts,
            "fixed": fixed, "handsoff": sorted(handsoff)}


def _udim_tiles(start_row, count_needed, reserved):
    """Yield (u, v) tile coordinates row by row from start_row, skipping reserved."""
    v = start_row
    while True:
        for u in range(10):
            if 1001 + u + 10 * v not in reserved:
                yield u, v
        v += 1


class _TilePacker(object):
    """Skyline bottom-left packer for one UDIM tile, plus a list of the free
    gaps the skyline leaves under overhangs (reused first, guillotine-split).

    Coordinates are in tile space; every rect is reserved with `pad` on its
    right and top, inside [pad, 1] on both axes, so neighbours and the tile
    border all get `pad` of clearance.
    """
    __slots__ = ("tile", "lo", "segs", "gaps")

    def __init__(self, tile, pad):
        self.tile = tile
        self.lo = pad
        self.segs = [[pad, pad, 1.0 - pad]]  # [x, top y, width], left to right
        self.gaps = []  # [x, y, w, h] free rects below the skyline

    @staticmethod
    def free_around(boxes, pad):
        """Disjoint free rects of a tile once `boxes` (fixed shells, tile
        space) are blocked out with `pad` clearance, for a gaps-only packer."""
        free = [[pad, pad, 1.0 - pad, 1.0 - pad]]
        for x0, y0, x1, y1 in sorted(boxes):
            bx1, by1 = x1 + pad, y1 + pad  # placed rects reserve pad right/top already
            nxt = []
            for fx, fy, fw, fh in free:
                fx1, fy1 = fx + fw, fy + fh
                if x0 >= fx1 or bx1 <= fx or y0 >= fy1 or by1 <= fy:
                    nxt.append([fx, fy, fw, fh])
                    continue
                if y0 > fy:
                    nxt.append([fx, fy, fw, y0 - fy])  # below: full width
                if by1 < fy1:
                    nxt.append([fx, by1, fw, fy1 - by1])  # above: full width
                my0, my1 = max(fy, y0), min(fy1, by1)
                if x0 > fx:
                    nxt.append([fx, my0, x0 - fx, my1 - my0])  # left
                if bx1 < fx1:
                    nxt.append([bx1, my0, fx1 - bx1, my1 - my0])  # right
            free = [r for r in nxt if r[2] > 1e-5 and r[3] > 1e-5]
        return free

    def use_free(self, free):
        """Switch to gaps-only packing in the given free rects (a tile that
        already holds hands-off shells)."""
        self.segs = []
        self.gaps = [r[:] for r in free]

    def find(self, w, h):
        """Best spot for a w x h rect: (score, kind, index, x, y), or None.
        Gaps score below anything on the skyline, so they're used first."""
        eps = 1e-9
        best = None
        for i, gap in enumerate(self.gaps):
            if w <= gap[2] + eps and h <= gap[3] + eps:
                score = (-1.0, gap[2] * gap[3] - w * h, 0.0)  # tightest gap
                if best is None or score < best[0]:
                    best = (score, 1, i, gap[0], gap[1])
        if best is not None:
            return best
        segs = self.segs
        n = len(segs)
        for i in range(n):
            x = segs[i][0]
            if x + w > 1.0 + eps:
                break
            y = 0.0
            j = i
            right = x + w - eps
            while j < n and segs[j][0] < right:
                if segs[j][1] > y:
                    y = segs[j][1]
                j += 1
            if y + h > 1.0 + eps:
                continue
            score = (y + h, x, 0.0)
            if best is None or score < best[0]:
                best = (score, 0, i, x, y)
        return best

    def place(self, spot, w, h):
        _, kind, i, x, y = spot
        if kind == 1:  # inside a gap: split what's left into right and top parts
            gx, gy, gw, gh = self.gaps.pop(i)
            if gw - w > 1e-6:
                self.gaps.append([gx + w, gy, gw - w, gh])
            if gh - h > 1e-6:
                self.gaps.append([gx, gy + h, w, gh - h])
            return
        top = y + h
        right = x + w
        new = []
        for sx, sy, sw in self.segs:
            ex = sx + sw
            if ex <= x + 1e-12 or sx >= right - 1e-12:
                new.append([sx, sy, sw])
                continue
            a, b = max(sx, x), min(ex, right)
            if y - sy > 1e-6 and b - a > 1e-6:
                self.gaps.append([a, sy, b - a, y - sy])  # hole under the new rect
            if sx < x:
                new.append([sx, sy, x - sx])
            if ex > right:
                new.append([right, sy, ex - right])
        new.append([x, top, w])
        new.sort(key=lambda s: s[0])
        merged = [new[0]]
        for s in new[1:]:
            last = merged[-1]
            if abs(s[1] - last[1]) < 1e-9 and abs(last[0] + last[2] - s[0]) < 1e-9:
                last[2] += s[2]
            else:
                merged.append(s)
        self.segs = merged


def plan_layout(collected, settings, density_scale=1.0):
    """Pure-math layout plan. Returns a dict with per-shell placements, group
    stats, tiles used and warnings. Nothing in the scene changes."""
    s = dict(LAYOUT_DEFAULTS)
    s.update(settings or {})
    res = float(s["map_size"])
    td = float(s["texel_density"]) * density_scale
    pad = float(s["padding_px"]) / res
    usable = 1.0 - 2.0 * pad
    growth = max(0.0, float(s["growth"]))
    reserved = set()
    for g in collected["locked"]:
        reserved.update(g["tiles"])
    # hands-off shells: their tiles are never handed out as fresh tiles. In
    # "Pack around them" mode each such tile becomes a packer whose free space
    # is what's left around them (offered first to the groups those shells
    # belong to); in "Reserve their tiles" mode nothing else goes there.
    fixed = collected.get("fixed") or []
    fixed_boxes = {}
    for fx in fixed:
        fixed_boxes.setdefault(fx["udim"], []).append(fx["box"])
    reserved.update(fixed_boxes)
    pack_around = s.get("handsoff_tiles", HANDSOFF_MODES[0]) != "Reserve their tiles"
    fixed_packers = {}
    if pack_around and fixed_boxes:
        cache = collected.setdefault("_free_cache", {})
        for udim in sorted(fixed_boxes):
            free = cache.get((udim, round(pad, 9)))
            if free is None:
                free = cache[(udim, round(pad, 9))] = _TilePacker.free_around(fixed_boxes[udim], pad)
            pk = _TilePacker(((udim - 1001) % 10, (udim - 1001) // 10), pad)
            pk.use_free(free)
            fixed_packers[udim] = pk
    order = sorted(set(g["key"] for g in collected["groups"]))
    rank = {k: i for i, k in enumerate(order)}
    groups = sorted(collected["groups"], key=lambda g: (g["section_index"], rank[g["key"]]))

    placements = {}  # id(shell) -> (tile_u, tile_v, x, y, scale, angle, w, h)
    stats = {}
    warnings = []
    tiles_used = set()
    row = 0
    current_section = None
    tile_iter = None
    carry = []  # packers the previous group of this section ended on
    orientation = s.get("orientation") or ("Main axis" if s.get("rotate", True) else "Keep")
    default_mode = _ORIENT_MODE.get(orientation, "axis")

    def next_tile():
        t = next(tile_iter)
        tiles_used.add(1001 + t[0] + 10 * t[1])
        return _TilePacker(t, pad)

    for g in groups:
        if g["section_index"] != current_section:
            if current_section is not None and s["new_row_per_section"]:
                row = (max((t - 1001) // 10 for t in tiles_used) + 1) if tiles_used else row
                carry = []
            current_section = g["section_index"]
            tile_iter = _udim_tiles(row, 0, reserved)
        mode = g.get("orient") or default_mode
        density = td * g["td"] / 100.0
        compensate = 1.0
        sizes = []
        for sh in g["shells"]:
            angle, w0, h0 = sh.dims.get(mode, sh.dims["axis"])
            target = sh.area3d * (density / res) ** 2  # UV area in tiles
            k = math.sqrt(target / sh.area_uv)
            sizes.append((sh, k, angle, w0 * k, h0 * k))
        biggest = max([max(w, h) for _, _, _, w, h in sizes] or [0.0])
        if biggest > usable:
            if s["auto_compensate"]:
                compensate = usable / biggest * 0.999
                sizes = [(sh, k * compensate, a, w * compensate, h * compensate) for sh, k, a, w, h in sizes]
                warnings.append("%s: largest piece didn't fit a tile at %d px/m, so this group was lowered to "
                                "%d px/m." % (g["key"], round(density), round(density * compensate)))
            else:
                warnings.append("%s: a piece is bigger than a whole tile at %d px/m (raise Map size or lower "
                                "the density, or turn on Auto-compensate)." % (g["key"], round(density)))
        # _stack groups: identical pieces share one spot (one footprint for N copies)
        stacked = {}
        unique = []
        sizes.sort(key=lambda t: (t[0].mesh, t[0].uv_ids[0]))  # same representative every time
        for item in sizes:
            sh, k, a, w, h = item
            if g.get("stack"):
                sig = (len(sh.uv_ids), round(w, 3), round(h, 3))
                if sig in stacked:
                    stacked[sig][1].append(item)
                    continue
                stacked[sig] = (item, [])
            unique.append(item)
        # 2D packing: biggest first, each piece goes to the lowest spot on the
        # skyline of the first tile it fits (gaps under overhangs first). The
        # group may top up the tiles the previous group ended on, then opens
        # new ones, so groups stay in neighbouring tiles. Main axis may turn
        # pieces 90 degrees when that sits lower.
        unique.sort(key=lambda t: (-round(max(t[3], t[4]), 4), -round(t[3] * t[4], 8), t[0].mesh,
                                   t[0].uv_ids[0]))  # mesh/uv tie-break: same input, same layout
        can_turn = mode == "axis"
        own_fixed = sorted(set(fx["udim"] for fx in g.get("fixed", [])))
        packers = [fixed_packers[t] for t in own_fixed if t in fixed_packers]
        packers += [q for q in carry if q not in packers]
        g_tiles = set(own_fixed)
        area = sum(fx["area"] for fx in g.get("fixed", []))
        for item in unique:
            sh, k, a, w, h = item
            w_res, h_res = w * (1.0 + growth), h * (1.0 + growth)
            if w_res > usable or h_res > usable:  # still too big: place alone, may overhang
                w_res, h_res = min(w_res, usable), min(h_res, usable)
            rw, rh = w_res + pad, h_res + pad
            found = None
            for pk in packers:
                spot = pk.find(rw, rh)
                turned = False
                if can_turn and abs(rw - rh) > 1e-9:
                    alt = pk.find(rh, rw)
                    if alt is not None and (spot is None or alt[0] < spot[0]):
                        spot, turned = alt, True
                if spot is not None:
                    found = (pk, spot, turned)
                    break
            if found is None:
                pk = next_tile()
                packers.append(pk)
                spot = pk.find(rw, rh)
                turned = False
                if spot is None and can_turn:
                    spot, turned = pk.find(rh, rw), True
                if spot is None:  # can only happen for clamped oversize pieces
                    spot, turned = (None, 0, 0, pad, pad), False
                found = (pk, spot, turned)
            pk, spot, turned = found
            if turned:
                a += math.pi / 2.0
                w, h = h, w
                rw, rh = rh, rw
            if spot[0] is not None:
                pk.place(spot, rw, rh)
            x, y = spot[3], spot[4]
            tu, tv = pk.tile
            placements[id(sh)] = (tu, tv, x, y, k, a, w, h)
            g_tiles.add(1001 + tu + 10 * tv)
            area += w * h
            if g.get("stack"):
                for dup in stacked[(len(sh.uv_ids), round(item[3], 3), round(item[4], 3))][1]:
                    dsh, dk, da, dw, dh = dup
                    if turned:
                        da, dw, dh = da + math.pi / 2.0, dh, dw
                    placements[id(dsh)] = (tu, tv, x, y, dk, da, dw, dh)
        if packers:
            last = max(packers, key=lambda q: (q.tile[1], q.tile[0]))
            carry = [q for q in packers if 1001 + q.tile[0] + 10 * q.tile[1] in g_tiles] or [last]
        n_stacked = sum(len(v[1]) for v in stacked.values())
        stats[g["set"]] = {"key": g["key"], "uuid": g["uuid"], "tiles": sorted(g_tiles), "coverage": area * 100.0,
                           "density": density * compensate, "shells": len(g["shells"]), "stacked": n_stacked,
                           "orientation": mode, "handsoff": len(g.get("fixed", [])),
                           "changed": bool(g["old_print"]) and g["old_print"] != g["print"]}
    for g in collected["locked"]:
        stats[g["set"]] = {"key": g["key"], "uuid": g["uuid"], "tiles": g["tiles"], "coverage": None,
                           "density": None,
                           "shells": None, "locked": True,
                           "changed": bool(g["old_print"]) and g["old_print"] != g["print"]}
        if stats[g["set"]]["changed"]:
            warnings.append("%s is locked but its geometry changed since it was laid out: unlock it to re-lay "
                            "it, or leave it if the change doesn't matter." % g["key"])
    if fixed_boxes and not pack_around:
        for udim in sorted(fixed_boxes):
            used = sum((b[2] - b[0]) * (b[3] - b[1]) for b in fixed_boxes[udim])
            if used < 0.5:
                warnings.append("Tile %d is reserved for hands-off pieces that fill only about %d%% of it; "
                                "set Hands-off tiles to 'Pack around them' to use the rest." % (
                                    udim, round(used * 100)))
    return {"placements": placements, "stats": stats, "tiles": sorted(tiles_used | reserved),
            "new_tiles": sorted(tiles_used), "warnings": warnings, "density": td, "settings": s,
            "fixed_tiles": sorted(fixed_boxes), "pack_around": pack_around}


def plan_fit_to_tiles(collected, settings):
    """Highest density whose layout fits in settings['max_tiles'] tiles."""
    limit = max(1, int(settings.get("max_tiles", 10)))
    lo, hi = 0.0, 1.0
    plan = plan_layout(collected, settings, hi)
    while len(plan["new_tiles"]) <= limit and hi < 1e4:  # find an upper bound
        lo, hi = hi, hi * 2.0
        plan = plan_layout(collected, settings, hi)
    best = plan_layout(collected, settings, lo) if lo > 0 else None
    for _ in range(18):
        mid = (lo + hi) / 2.0
        p = plan_layout(collected, settings, mid)
        if len(p["new_tiles"]) <= limit:
            lo, best = mid, p
        else:
            hi = mid
    if best is not None:  # packing isn't monotonic: a bit denser can still fit, so probe upward
        base = lo
        for i in range(1, 13):
            p = plan_layout(collected, settings, base * (1.0 + 0.02 * i))
            if len(p["new_tiles"]) <= limit:
                best = p
    if best is None:
        best = plan_layout(collected, settings, max(lo, 1e-3))
        best["warnings"].append("Couldn't fit everything into %d tiles; showing the smallest layout." % limit)
    return best


def make_plan(collected, settings):
    if settings.get("mode") == "Fit to tiles":
        return plan_fit_to_tiles(collected, settings)
    return plan_layout(collected, settings)


def write_uvs(xform, uv_set, us, vs):
    """Set every UV of a mesh in one undoable step, with or without history.

    No history: one setAttr on the shape's own UV array. With history: UVs are
    recomputed from upstream, so write the difference into a polyTweakUV at
    the end of the history (that's what Maya's own UV tools do), again with
    one setAttr. (MFnMesh.setUVs is fast but not undoable.)
    """
    fn = _mesh_fn(xform)
    cur_u, cur_v = fn.getUVs(uv_set)
    n = len(cur_u)
    if n != len(us):
        raise RuntimeError("UV count changed on %s" % xform)
    shape = om.MDagPath.getAPathTo(fn.object()).fullPathName()
    if not cmds.listConnections(shape + ".inMesh", source=True, destination=False):
        names = cmds.polyUVSet(shape, q=True, allUVSets=True) or []
        idx = (cmds.polyUVSet(shape, q=True, allUVSetsIndices=True) or [])[names.index(uv_set)]
        for a in range(0, n, 5000):
            b = min(n, a + 5000)
            flat = []
            for i in range(a, b):
                flat.extend((us[i], vs[i]))
            cmds.setAttr("%s.uvst[%d].uvsp[%d:%d]" % (shape, idx, a, b - 1), *flat)
        return
    cmds.polyEditUV(xform + ".map[0]", u=0.0, v=0.0, relative=True, uvSetName=uv_set)
    tweaks = [h for h in (cmds.listHistory(shape) or []) if cmds.nodeType(h) == "polyTweakUV"
              and (cmds.getAttr(h + ".uvSetName") or uv_set) == uv_set]
    if not tweaks:
        raise RuntimeError("couldn't add a UV tweak to %s" % xform)
    node = tweaks[0]  # nearest the shape
    old = {}
    for i in cmds.getAttr(node + ".uvTweak", multiIndices=True) or []:
        old[i] = cmds.getAttr("%s.uvTweak[%d]" % (node, i))[0]
    for a in range(0, n, 5000):
        b = min(n, a + 5000)
        flat = []
        for i in range(a, b):
            ou, ov = old.get(i, (0.0, 0.0))
            flat.extend((ou + us[i] - cur_u[i], ov + vs[i] - cur_v[i]))
        cmds.setAttr("%s.uvTweak[%d:%d]" % (node, a, b - 1), *flat)


def _place_shell(us, vs, sh, tu, tv, x, y, k, angle):
    """Rotate a shell about its centre, scale it by k and put its bounding
    box's corner at (tu + x, tv + y). Edits us / vs in place."""
    ca, sa = math.cos(angle), math.sin(angle)
    pts = []
    for u in sh.uv_ids:
        du, dv = us[u] - sh.cx, vs[u] - sh.cy
        pts.append(((du * ca - dv * sa) * k, (du * sa + dv * ca) * k))
    mx = min(q[0] for q in pts)
    my = min(q[1] for q in pts)
    for u, (pu, pv) in zip(sh.uv_ids, pts):
        us[u] = tu + x + (pu - mx)
        vs[u] = tv + y + (pv - my)


def apply_layout(asset, collected, plan, uv_set="map1", backup=True, backup_set="map1_backup"):
    """Write the planned layout into uv_set (one Ctrl+Z). Returns stats."""
    by_mesh = {}
    for g in collected["groups"]:
        for sh in g["shells"]:
            if id(sh) in plan["placements"]:
                by_mesh.setdefault(sh.mesh, []).append(sh)
    with UndoChunk("Smart UDIM layout"), PreserveSelection():
        if backup:
            backup_uvs(sorted(by_mesh), uv_set, backup_set)
        for xform, shells in by_mesh.items():
            fn = _mesh_fn(xform)
            us, vs = fn.getUVs(uv_set)
            us, vs = list(us), list(vs)
            for sh in shells:
                _place_shell(us, vs, sh, *plan["placements"][id(sh)][:6])
            write_uvs(xform, uv_set, us, vs)
        asset.update_tool_sets(add={"laidout": sorted(by_mesh)})
        for g in collected["groups"]:
            st = plan["stats"].get(g["set"])
            if not st:
                continue
            node = g["set"]
            for ln, kw in ((LAYOUT_TILES, {"dataType": "string"}), (LAYOUT_PRINT, {"dataType": "string"}),
                           (LAYOUT_LOCK, {"attributeType": "bool"})):
                if not cmds.attributeQuery(ln, node=node, exists=True):
                    cmds.addAttr(node, longName=ln, **kw)
            cmds.setAttr(node + "." + LAYOUT_TILES, ",".join(str(t) for t in st["tiles"]), type="string")
            cmds.setAttr(node + "." + LAYOUT_PRINT, g["print"], type="string")
            cmds.setAttr(node + "." + UDIM_COV, st["coverage"])
        store_layout_settings(asset, plan)
        asset.sync_names()
    return {"meshes": len(by_mesh), "shells": len(plan["placements"])}


def set_group_lock(node, locked):
    with UndoChunk("Smart UDIM lock"):
        if not cmds.attributeQuery(LAYOUT_LOCK, node=node, exists=True):
            cmds.addAttr(node, longName=LAYOUT_LOCK, attributeType="bool")
        cmds.setAttr(node + "." + LAYOUT_LOCK, bool(locked))
        if locked and not (_get(node, LAYOUT_TILES, "") or ""):
            # never laid out by the tool: reserve the tiles its UVs sit in now
            members, _ = expand_members(node)
            tiles = set()
            for xform in members:
                uvs = cmds.polyEditUV(cmds.polyListComponentConversion(xform, toUV=True), q=True) or []
                for i in range(0, len(uvs), 2):
                    tiles.add(1001 + int(math.floor(uvs[i])) + 10 * int(math.floor(uvs[i + 1])))
            if not cmds.attributeQuery(LAYOUT_TILES, node=node, exists=True):
                cmds.addAttr(node, longName=LAYOUT_TILES, dataType="string")
            cmds.setAttr(node + "." + LAYOUT_TILES, ",".join(str(t) for t in sorted(tiles)), type="string")


# =============================================================================
# Smart UDIM - validation report + hand-off sheet
# =============================================================================

LAYOUT_SETTINGS_ATTR = "unlokUdimLayout"

VALIDATION_LABELS = {
    "out_of_range": ("UVs outside the UDIM range", "skip"),
    "crossing": ("Shells crossing a tile border", "skip"),
    "overlap": ("Overlapping shells", "skip"),
    "flipped": ("Flipped (mirrored) shells", "warn"),
    "tiny": ("Shells under 2 px", "warn"),
    "density": ("Density more than 10% off target", "warn"),
    "padding": ("Shells closer than the padding", "warn"),
}
VALIDATION_ORDER = ("out_of_range", "crossing", "overlap", "flipped", "tiny", "density", "padding")


def layout_settings_of(asset):
    """The settings the last Apply Layout used (stored on the root set)."""
    root = asset.root_set() if asset else None
    if not root or not cmds.attributeQuery(LAYOUT_SETTINGS_ATTR, node=root, exists=True):
        return {}
    try:
        return json.loads(cmds.getAttr(root + "." + LAYOUT_SETTINGS_ATTR) or "{}")
    except ValueError:
        return {}


def store_layout_settings(asset, plan):
    root = asset.root_set()
    if not root:
        return
    if not cmds.attributeQuery(LAYOUT_SETTINGS_ATTR, node=root, exists=True):
        cmds.addAttr(root, longName=LAYOUT_SETTINGS_ATTR, dataType="string")
    data = dict(plan["settings"])
    data["density"] = plan["density"]
    cmds.setAttr(root + "." + LAYOUT_SETTINGS_ATTR, json.dumps(data, sort_keys=True), type="string")


SESSION_ATTR = "unlokUdimSession"
SESSION_MAX_ITEMS = 500  # validation items kept per category


def save_session(asset, data):
    """Keep the panel's progress (reports, results, settings) as JSON on the
    asset's root set, so it's saved with the scene and picked up again when
    the scene is reopened. Kept out of the undo queue: it's bookkeeping."""
    root = asset.root_set() if asset else None
    if not root:
        return
    with NoUndo():
        if not cmds.attributeQuery(SESSION_ATTR, node=root, exists=True):
            cmds.addAttr(root, longName=SESSION_ATTR, dataType="string")
        cmds.setAttr(root + "." + SESSION_ATTR, json.dumps(data, sort_keys=True), type="string")


def load_session(asset):
    root = asset.root_set() if asset else None
    if not root or not cmds.attributeQuery(SESSION_ATTR, node=root, exists=True):
        return {}
    try:
        data = json.loads(cmds.getAttr(root + "." + SESSION_ATTR) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def session_summary(data):
    """'pre-process, Auto UV, layout applied' for a saved session."""
    done = []
    if data.get("report"):
        done.append("pre-process")
    auto = data.get("auto") or {}
    if auto.get("rows"):
        done.append("analysed" if auto.get("analysed_only") else "Auto UV")
    if data.get("layout_applied"):
        done.append("layout applied")
    if data.get("validation"):
        done.append("validated")
    return ", ".join(done) or "set up"


def pack_validation(res):
    """Validation result -> JSON-friendly (faces as ranges, capped)."""
    if not res:
        return None
    items = {}
    for cat, found in res["items"].items():
        items[cat] = [{"mesh": it["mesh"], "faces": face_ranges(it["faces"]), "detail": it["detail"]}
                      for it in found[:SESSION_MAX_ITEMS]]
    return {"items": items, "shells": res.get("shells", 0), "seconds": res.get("seconds", 0.0),
            "map_size": res.get("map_size")}


def unpack_validation(data):
    if not data:
        return None
    items = {k: [] for k in VALIDATION_ORDER}
    for cat, found in (data.get("items") or {}).items():
        if cat not in items:
            continue
        for it in found:
            if not cmds.objExists(it["mesh"]):
                continue
            faces = []
            for r in it["faces"]:
                faces.extend(_parse_face_spec(r) or [])
            items[cat].append({"mesh": it["mesh"], "faces": faces, "detail": it["detail"]})
    return {"items": items, "shells": data.get("shells", 0), "seconds": data.get("seconds", 0.0),
            "map_size": data.get("map_size")}


def _mesh_shells(xform, uv_set, unit_scale):
    """Every UV shell of a mesh: faces, uv ids, bbox, signed UV area, 3D / UV area."""
    fn = _mesh_fn(xform)
    if fn is None or uv_set not in fn.getUVSetNames() or fn.numUVs(uv_set) == 0:
        return []
    counts, ids = fn.getAssignedUVs(uv_set)
    nf = len(counts)
    if nf == 0:
        return []
    if fn.currentUVSetName() != uv_set:
        with NoUndo():
            cmds.polyUVSet(xform, currentUVSet=True, uvSet=uv_set)
    a3, auv = _face_areas(xform, nf)
    _, shell_of = fn.getUvShellsIds(uv_set)
    us, vs = fn.getUVs(uv_set)
    us, vs, ids = list(us), list(vs), list(ids)
    shells = {}
    k = 0
    for f, c in enumerate(counts):
        if c == 0:
            continue
        sid = shell_of[ids[k]]
        sh = shells.get(sid)
        if sh is None:
            sh = shells[sid] = {"mesh": xform, "faces": [], "uvs": set(), "signed": 0.0, "a3": 0.0, "auv": 0.0,
                                "box": [1e30, 1e30, -1e30, -1e30]}
        sh["faces"].append(f)
        area = 0.0
        for i in range(c):
            a = ids[k + i]
            b = ids[k + (i + 1) % c]
            area += us[a] * vs[b] - us[b] * vs[a]
            sh["uvs"].add(a)
        sh["signed"] += area
        sh["a3"] += a3[f] * unit_scale
        sh["auv"] += auv[f]
        k += c
    for sh in shells.values():
        box = sh["box"]
        for u in sh["uvs"]:
            box[0] = min(box[0], us[u])
            box[1] = min(box[1], vs[u])
            box[2] = max(box[2], us[u])
            box[3] = max(box[3], vs[u])
    return list(shells.values())


def _group_lookup(asset):
    """{(mesh, face) or (mesh, None): (set, td %, stack)} for the asset's groups."""
    out = {}
    for sec in asset.sections():
        sec_td = _get(sec, UDIM_TD, 100.0)
        for mat in asset.materials(sec):
            td = _get(mat, UDIM_TD, 100.0) * sec_td / 100.0
            stack = bool(_get(mat, UDIM_STACK, False))
            locked = bool(_get(mat, LAYOUT_LOCK, False))
            members, _ = expand_members(mat)
            for xform, faces in members.items():
                if faces is None:
                    out[(xform, None)] = (mat, td, stack, locked)
                else:
                    for f in faces:
                        out[(xform, f)] = (mat, td, stack, locked)
    return out


def validate_layout(asset, uv_set="map1", map_size=None, padding_px=None, target_density=None):
    """Check the finished layout. Returns {"items": {category: [item...]},
    "shells": n, "seconds": s}; each item is {"mesh", "faces", "detail"}."""
    t0 = time.time()
    stored = layout_settings_of(asset)
    map_size = float(map_size or stored.get("map_size") or 4096)
    padding_px = float(stored.get("padding_px", 8) if padding_px is None else padding_px)
    target = target_density or stored.get("density")
    unit_scale = _UNIT_TO_M.get(cmds.currentUnit(q=True, linear=True), 0.01) ** 2
    groups = _group_lookup(asset)
    meshes, _ = asset.meshes()
    handsoff = set(m for m, st in asset.uv_status().items() if st == "handsoff")
    shells = []
    for xform in meshes:
        for sh in _mesh_shells(xform, uv_set, unit_scale):
            g = groups.get((xform, sh["faces"][0])) or groups.get((xform, None))
            sh["group"], sh["td"], sh["stack"], sh["locked"] = g if g else (None, 100.0, False, False)
            sh["locked"] = sh["locked"] or xform in handsoff  # hands off keeps its own density
            shells.append(sh)
    items = {k: [] for k in VALIDATION_ORDER}

    def add(cat, sh, detail):
        items[cat].append({"mesh": sh["mesh"], "faces": sh["faces"], "detail": detail})

    for sh in shells:
        u0, v0, u1, v1 = sh["box"]
        if u0 < -1e-6 or v0 < -1e-6 or u1 > 10.0 + 1e-6:
            add("out_of_range", sh, "U %.2f-%.2f, V %.2f-%.2f" % (u0, u1, v0, v1))
        elif math.floor(u0 + 1e-6) != math.floor(u1 - 1e-6) or math.floor(v0 + 1e-6) != math.floor(v1 - 1e-6):
            add("crossing", sh, "spans U %.2f-%.2f, V %.2f-%.2f" % (u0, u1, v0, v1))
        if sh["signed"] < 0:
            add("flipped", sh, "mirrored: textures will read backwards")
        if max(u1 - u0, v1 - v0) * map_size < 2.0:
            add("tiny", sh, "%.1f px across at %d" % (max(u1 - u0, v1 - v0) * map_size, map_size))
        if target and not sh["locked"] and sh["a3"] > 1e-12 and sh["auv"] > 0:  # locked = frozen on purpose
            want = target * sh["td"] / 100.0
            got = math.sqrt(sh["auv"] / sh["a3"]) * map_size
            if abs(got / want - 1.0) > 0.10:
                add("density", sh, "%d px/m (layout target %d)" % (round(got), round(want)))

    # overlaps + padding: sweep over shell boxes, then confirm overlaps with Maya
    order = sorted(range(len(shells)), key=lambda i: shells[i]["box"][0])
    min_gap = max(1.0, padding_px * 0.5) / map_size
    candidates = set()
    tight = set()
    for a_pos, i in enumerate(order):
        bi = shells[i]["box"]
        for j in order[a_pos + 1:]:
            bj = shells[j]["box"]
            if bj[0] > bi[2] + min_gap:
                break
            if math.floor(bi[0] + 1e-6) != math.floor(bj[0] + 1e-6) or \
                    math.floor(bi[1] + 1e-6) != math.floor(bj[1] + 1e-6):
                continue  # different tiles
            gap = max(bj[0] - bi[2], bi[0] - bj[2], bj[1] - bi[3], bi[1] - bj[3])
            if gap < 0:
                if not (shells[i]["stack"] and shells[j]["stack"]):
                    candidates.update((i, j))
            elif gap < min_gap:
                tight.update((i, j))
    flagged = set()
    if candidates:
        comps = []
        for i in candidates:
            sh = shells[i]
            comps.extend("%s.%s" % (sh["mesh"], r) for r in face_ranges(sh["faces"]))
        hits = cmds.polyUVOverlap(comps, overlappingComponents=True) or []
        hit_faces = set()
        for comp in hits:
            node, _, spec = comp.partition(".")
            if cmds.objectType(node, isAType="shape"):
                node = long_name(cmds.listRelatives(node, parent=True, fullPath=True)[0])
            for f in _parse_face_spec(spec) or []:
                hit_faces.add((long_name(node), f))
        for i in candidates:
            sh = shells[i]
            if any((sh["mesh"], f) in hit_faces for f in sh["faces"]):
                flagged.add(i)
                add("overlap", sh, "overlaps another shell")
    for i in sorted(tight - flagged):
        add("padding", shells[i], "under %d px from a neighbour" % round(min_gap * map_size))
    return {"items": items, "shells": len(shells), "seconds": time.time() - t0, "map_size": map_size}


def render_handoff_sheet(asset, uv_set="map1", px_per_tile=512):
    """Paint the UDIM layout for texture artists: every shell filled and
    outlined in its material colour, tile numbers, section names per row and a
    legend. Returns a QImage."""
    stored = layout_settings_of(asset)
    groups = []
    for sec in asset.sections():
        sec_key = _get(sec, UDIM_KEY) or parse_group_name(sec)["key"]
        for mat in asset.materials(sec):
            members, _ = expand_members(mat)
            groups.append({"set": mat, "key": _get(mat, UDIM_KEY) or parse_group_name(mat)["key"],
                           "section": sec_key, "members": members, "cov": _get(mat, UDIM_COV, -1.0),
                           "td": _get(mat, UDIM_TD, 100.0), "tiles": set(), "faces": 0})
    polys_by_group = []
    max_u = max_v = 0
    for g in groups:
        polys, edges = [], []
        for xform, faces in g["members"].items():
            fn = _mesh_fn(xform)
            if fn is None or uv_set not in fn.getUVSetNames() or fn.numUVs(uv_set) == 0:
                continue
            counts, ids = fn.getAssignedUVs(uv_set)
            us, vs = fn.getUVs(uv_set)
            ids = list(ids)
            starts = []
            k = 0
            for c in counts:
                starts.append(k)
                k += c
            border = {}
            for f in (range(len(counts)) if faces is None else sorted(faces)):
                c = counts[f]
                if c < 3:
                    continue
                s = starts[f]
                face_ids = ids[s:s + c]
                polys.append([(us[u], vs[u]) for u in face_ids])
                for i in range(c):
                    a, b = face_ids[i], face_ids[(i + 1) % c]
                    key = (a, b) if a < b else (b, a)
                    border[key] = border.get(key, 0) + 1
            edges.extend(((us[a], vs[a]), (us[b], vs[b])) for (a, b), n in border.items() if n == 1)
        for poly in polys:
            for u, v in poly:
                if 0 <= u < 10 and v >= 0:
                    tile = 1001 + int(u) + 10 * int(v)
                    g["tiles"].add(tile)
                    max_u, max_v = max(max_u, int(u)), max(max_v, int(v))
        g["faces"] = len(polys)
        polys_by_group.append((g, polys, edges))
    cols, rows = max_u + 1, max_v + 1
    set_key_palette([g["key"] for g in groups])
    T = int(px_per_tile)
    left, top, gap = 190, 64, 6
    legend_h = 28 + 22 * len(groups)
    width = left + cols * T + 24
    height = top + rows * T + legend_h + 20
    img = QtGui.QImage(width, height, QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor("#262626"))
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)

    def to_px(u, v):
        return QtCore.QPointF(left + u * T, top + (rows - v) * T)

    title = QtGui.QFont()
    title.setPointSize(15)
    title.setBold(True)
    p.setFont(title)
    p.setPen(QtGui.QColor("#f0f0f0"))
    root_group = asset.root_group() or ""
    p.drawText(QtCore.QRectF(16, 10, width - 32, 28), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
               "%s  -  UDIM layout" % short_name(root_group))
    small = QtGui.QFont()
    small.setPointSize(9)
    p.setFont(small)
    p.setPen(QtGui.QColor("#a8a8a8"))
    info = "%d tile(s)" % len(set(t for g in groups for t in g["tiles"]))
    if stored:
        info += "  |  %d px/m on %s maps  |  %d px padding" % (round(stored.get("density", 0)),
                                                              stored.get("map_size", "?"),
                                                              stored.get("padding_px", 0))
    info += "  |  %s" % time.strftime("%Y-%m-%d")
    p.drawText(QtCore.QRectF(16, 36, width - 32, 20), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, info)

    # tiles + numbers
    tile_font = QtGui.QFont()
    tile_font.setPointSizeF(max(7.0, T / 40.0))
    for v in range(rows):
        for u in range(cols):
            tl = to_px(u, v + 1)
            rect = QtCore.QRectF(tl.x(), tl.y(), T, T)
            p.fillRect(rect, QtGui.QColor("#303030"))
            p.setPen(QtGui.QPen(QtGui.QColor("#4c4c4c"), 1))
            p.drawRect(rect)
    # shells
    for g, polys, edges in polys_by_group:
        fill = _key_color(g["key"], 120)
        line = _key_color(g["key"], 255)
        path = QtGui.QPainterPath()
        path.setFillRule(QtCore.Qt.WindingFill)
        for poly in polys:
            path.addPolygon(QtGui.QPolygonF([to_px(u, v) for u, v in poly]))
            path.closeSubpath()
        p.fillPath(path, fill)
        p.setPen(QtGui.QPen(line, 1.2))
        p.drawLines([QtCore.QLineF(to_px(*a), to_px(*b)) for a, b in edges])
    p.setFont(tile_font)
    for v in range(rows):
        for u in range(cols):
            tl = to_px(u, v + 1)
            p.setPen(QtGui.QColor("#d8d8d8"))
            p.drawText(QtCore.QRectF(tl.x() + 5, tl.y() + 3, T - 10, 20), QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
                       str(1001 + u + 10 * v))
    # section names per row
    p.setFont(small)
    for v in range(rows):
        names = sorted(set(g["section"] for g in groups if any((t - 1001) // 10 == v for t in g["tiles"])))
        tl = to_px(0, v + 1)
        p.setPen(QtGui.QColor("#e6e6e6"))
        p.drawText(QtCore.QRectF(12, tl.y(), left - 24, T), QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                   "\n".join(names) if names else "")
    # legend
    y = top + rows * T + 18
    p.setPen(QtGui.QColor("#a8a8a8"))
    p.drawText(QtCore.QRectF(16, y, width, 18), QtCore.Qt.AlignLeft, "Material groups")
    y += 22
    for g in groups:
        if not g["faces"]:
            continue
        p.fillRect(QtCore.QRectF(16, y + 2, 14, 14), _key_color(g["key"], 255))
        tiles = sorted(g["tiles"])
        tile_text = ("%d-%d" % (tiles[0], tiles[-1]) if len(tiles) > 2 else ", ".join(str(t) for t in tiles)) \
            if tiles else "-"
        cov = ("  |  %.2f tiles" % (g["cov"] / 100.0)) if g["cov"] >= 0 else ""
        p.setPen(QtGui.QColor("#e6e6e6"))
        p.drawText(QtCore.QRectF(38, y, width - 50, 18), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                   "%s   (%s)   tiles %s   |   TD %s%%%s" % (g["key"], g["section"], tile_text,
                                                           _num_token(g["td"]), cov))
        y += 22
    p.end()
    return img


# =============================================================================
# Smart UDIM - panel
# =============================================================================

def selection_items():
    """Current scene selection as {mesh transform: None (whole) or face set}.
    A selected group counts as every mesh under it."""
    items = {}
    sel = cmds.ls(selection=True, long=True, flatten=False) or []
    comps = [s for s in sel if "." in s]
    for node in [s for s in sel if "." not in s]:
        if cmds.objectType(node, isAType="shape"):
            node = long_name(cmds.listRelatives(node, parent=True, fullPath=True)[0])
        if cmds.listRelatives(node, shapes=True, type="mesh", noIntermediate=True):
            items[node] = None
        elif cmds.objectType(node, isAType="transform"):
            for shape in cmds.listRelatives(node, allDescendents=True, type="mesh", fullPath=True,
                                            noIntermediate=True) or []:
                items[long_name(cmds.listRelatives(shape, parent=True, fullPath=True)[0])] = None
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


def _unlok_renamer_main():
    """UnlokRenamer's main(): from the Script Editor if it was pasted and run
    there (secure setups), else from an importable unlok_renamer.py; None if
    neither."""
    import __main__
    if hasattr(__main__, "RenamerWindow") and callable(getattr(__main__, "main", None)):
        return __main__.main
    try:
        import importlib.util
        if importlib.util.find_spec("unlok_renamer") is not None:
            import unlok_renamer
            return unlok_renamer.main
    except Exception:
        pass
    return None


def _unlok_renamer_available():
    return _unlok_renamer_main() is not None


LEVEL_COLORS = {"fixed": "#6fbf73", "warn": "#e0b050", "skip": "#e07a5f", "info": "#a8a8a8"}
SHEET_SIZES = {"Small": 256, "Medium": 512, "Large": 1024}


# Distinct colours for material groups (hand-picked so neighbours never look
# alike). Keys get them in sorted order via set_key_palette; unknown keys fall
# back to a hash.
GROUP_PALETTE = ("#e0675a", "#5aa9e6", "#7fcf6b", "#e8b84a", "#b07ce0", "#4fc9b8", "#f08bb4", "#c9a27a",
                 "#9aa7ff", "#d9e05a", "#ff9f5a", "#8fd0ff")
_KEY_COLORS = {}


def set_key_palette(keys):
    """Give each material key a distinct palette colour (sorted, so the same
    asset always gets the same colours)."""
    _KEY_COLORS.clear()
    for i, k in enumerate(sorted(set(keys))):
        _KEY_COLORS[k] = GROUP_PALETTE[i % len(GROUP_PALETTE)]


def _key_color(key, alpha=255):
    hexcol = _KEY_COLORS.get(key)
    if hexcol is None:
        h = 0
        for ch in key:
            h = (h * 131 + ord(ch)) & 0xFFFFFF
        hexcol = GROUP_PALETTE[h % len(GROUP_PALETTE)]
    c = QtGui.QColor(hexcol)
    c.setAlpha(alpha)
    return c


class UdimMapWidget(QtWidgets.QWidget):
    """Painted overview of a layout plan: UDIM tiles, every shell coloured by
    material group, locked tiles hatched. Hover for details, click to select
    a group's meshes. Painting only rectangles keeps it instant."""

    groupClicked = QtCore.Signal(str)

    def __init__(self, parent=None):
        super(UdimMapWidget, self).__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(120)
        self.shells = []  # (u, v, w, h, set, key)
        self.fixed = []  # hands-off shells, same tuple
        self.locked_tiles = set()
        self.tiles = set()
        self.labels = {}  # set -> (key, info text)
        self.cols, self.rows = 4, 1

    def set_plan(self, collected, plan):
        self.shells = []
        self.fixed = []
        self.labels = {}
        if plan and collected:
            set_key_palette([g["key"] for g in collected["groups"] + collected["locked"]])
            for g in collected["groups"]:
                st = plan["stats"].get(g["set"], {})
                self.labels[g["set"]] = (g["key"], "%s  |  %d px/m  |  %d%% of a tile  |  tiles %s" % (
                    g["key"], round(st.get("density") or 0), round(st.get("coverage") or 0),
                    ", ".join(str(t) for t in st.get("tiles", []))))
                for sh in g["shells"]:
                    p = plan["placements"].get(id(sh))
                    if p:
                        self.shells.append((p[0] + p[2], p[1] + p[3], p[6], p[7], g["set"], g["key"]))
                for fx in g.get("fixed", []):
                    tu, tv = (fx["udim"] - 1001) % 10, (fx["udim"] - 1001) // 10
                    b = fx["box"]
                    self.fixed.append((tu + b[0], tv + b[1], b[2] - b[0], b[3] - b[1], g["set"], g["key"]))
                if g.get("fixed"):
                    self.labels[g["set"]] = (g["key"], self.labels[g["set"]][1] + "  |  %d hands-off" % len(
                        g["fixed"]))
            self.locked_tiles = set()
            for g in collected["locked"]:
                self.locked_tiles.update(g["tiles"])
                self.labels[g["set"]] = (g["key"], "%s  |  locked  |  tiles %s" % (
                    g["key"], ", ".join(str(t) for t in g["tiles"])))
            if not plan.get("pack_around", True):
                self.locked_tiles.update(plan.get("fixed_tiles", []))
            self.tiles = set(plan["tiles"])
        else:
            self.tiles, self.locked_tiles = set(), set()
        us = [(t - 1001) % 10 for t in self.tiles] or [3]
        vs = [(t - 1001) // 10 for t in self.tiles] or [0]
        self.cols = max(4, max(us) + 1)
        self.rows = max(1, max(vs) + 1)
        self.setMinimumHeight(int(max(120, min(520, self.rows * self._tile_px() + 24))))
        self.update()

    def _tile_px(self):
        return max(24.0, (self.width() - 12.0) / max(1, self.cols))

    def _to_px(self, u, v):
        t = self._tile_px()
        return 6.0 + u * t, 6.0 + (self.rows - v) * t

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        p.fillRect(self.rect(), QtGui.QColor("#2c2c2c"))
        t = self._tile_px()
        font = p.font()
        font.setPointSizeF(max(6.0, min(8.0, t / 9.0)))
        p.setFont(font)
        for v in range(self.rows):
            for u in range(self.cols):
                udim = 1001 + u + 10 * v
                x, y = self._to_px(u, v + 1)
                rect = QtCore.QRectF(x, y, t, t)
                if udim in self.locked_tiles:
                    p.fillRect(rect, QtGui.QBrush(QtGui.QColor("#4a4030"), QtCore.Qt.BDiagPattern))
                elif udim in self.tiles:
                    p.fillRect(rect, QtGui.QColor("#383838"))
                p.setPen(QtGui.QPen(QtGui.QColor("#555555")))
                p.drawRect(rect)
                p.setPen(QtGui.QColor("#8a8a8a"))
                p.drawText(rect.adjusted(3, 2, -2, -2), QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft, str(udim))
        for u, v, w, h, node, key in self.shells:
            x0, y1 = self._to_px(u, v)
            x1, y0 = self._to_px(u + w, v + h)
            rect = QtCore.QRectF(x0, y0, max(1.0, x1 - x0), max(1.0, y1 - y0))
            p.fillRect(rect, _key_color(key, 150))
        for u, v, w, h, node, key in self.fixed:  # hands off: hatched, outlined
            x0, y1 = self._to_px(u, v)
            x1, y0 = self._to_px(u + w, v + h)
            rect = QtCore.QRectF(x0, y0, max(1.0, x1 - x0), max(1.0, y1 - y0))
            p.fillRect(rect, _key_color(key, 70))
            p.fillRect(rect, QtGui.QBrush(_key_color(key, 230), QtCore.Qt.BDiagPattern))
            p.setPen(QtGui.QPen(_key_color(key, 230)))
            p.drawRect(rect)
        if not self.shells and not self.locked_tiles and not self.fixed:
            p.setPen(QtGui.QColor("#8a8a8a"))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, "Press Plan to preview the layout")
        p.end()

    def _hit(self, pos):
        t = self._tile_px()
        u = (pos.x() - 6.0) / t
        v = self.rows - (pos.y() - 6.0) / t
        for su, sv, w, h, node, key in self.shells + self.fixed:
            if su <= u <= su + w and sv <= v <= sv + h:
                return node
        udim = 1001 + int(math.floor(u)) + 10 * int(math.floor(v))
        if udim in self.locked_tiles:
            for node, (key, text) in self.labels.items():
                if "locked" in text and str(udim) in text:
                    return node
        return None

    def mouseMoveEvent(self, event):
        node = self._hit(event.pos())
        text = self.labels.get(node, ("", ""))[1] if node else ""
        if text:
            QtWidgets.QToolTip.showText(event.globalPos(), text, self)
        else:
            QtWidgets.QToolTip.hideText()

    def mousePressEvent(self, event):
        node = self._hit(event.pos())
        if node:
            self.groupClicked.emit(node)

    def resizeEvent(self, event):
        super(UdimMapWidget, self).resizeEvent(event)
        self.setMinimumHeight(int(max(120, min(520, self.rows * self._tile_px() + 24))))


class SmartUdimPanel(QtWidgets.QWidget):
    TOOL_NAME = "Smart UDIM"
    TOOL_TIP = "Organise geometry into UDIM sections and material groups, clean it and check its UVs."

    COL_NAME, COL_TD, COL_COV, COL_ITEMS, COL_STACK, COL_LOCK, COL_ORIENT = range(7)

    def __init__(self, parent=None):
        super(SmartUdimPanel, self).__init__(parent)
        self.asset = None
        self.snapshot = None
        self.report = {}
        self.auto_result = None
        self._jobs = []
        self._collected = None
        self._plan = None
        self.layout_applied = None
        self.validation = None
        self._replan_timer = QtCore.QTimer(self)
        self._replan_timer.setSingleShot(True)
        self._replan_timer.setInterval(60)
        self._replan_timer.timeout.connect(self._replan)
        self._populating = False
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(60)
        self._refresh_timer.timeout.connect(self.refresh)
        self.states = {}
        self._applied = {}  # mesh -> state last coloured
        self._scene_timer = QtCore.QTimer(self)
        self._scene_timer.setSingleShot(True)
        self._scene_timer.setInterval(0)
        self._scene_timer.timeout.connect(self._on_scene_changed)
        self._callbacks = []
        self._build()
        self._install_jobs()
        self.restored = None
        start = self.pick_startup_asset() if maya_main_window() is not None else None
        if start is not None:
            self.set_asset(start)
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
        strip = QtWidgets.QFrame()
        strip.setProperty("unlokStep", True)
        sl = QtWidgets.QVBoxLayout(strip)
        sl.setContentsMargins(8, 6, 8, 6)
        sl.setSpacing(4)
        self.colour_box = CheckField("Colour meshes by UV status")
        self.colour_box.setToolTip("Gives every mesh a temporary preview material so you can see in the viewport "
                                   "what still needs UVs (yellow), what's done (greens), what's laid out (light "
                                   "blue) and what has a problem (red). Meshes change colour live as Auto UV "
                                   "works. Untick to get your real materials back.")
        self.colour_box.changed.connect(self._colours_toggled)
        sl.addWidget(self.colour_box)
        legend = QtWidgets.QGridLayout()
        legend.setSpacing(2)
        self.legend = {}
        for i, state in enumerate(UV_STATE_ORDER):
            label, colour, tip = UV_STATE_INFO[state]
            b = QtWidgets.QPushButton(label)
            pix = QtGui.QPixmap(10, 10)
            pix.fill(QtGui.QColor(colour))
            b.setIcon(QtGui.QIcon(pix))
            b.setFlat(True)
            b.setStyleSheet("text-align: left; padding: 1px 4px;")
            b.setToolTip(tip + "\nClick to select them.")
            b.clicked.connect(lambda *_, s=state: self._select_state(s))
            legend.addWidget(b, i // 2, i % 2)
            self.legend[state] = b
        sl.addLayout(legend)
        tl.addWidget(strip)
        outer.addWidget(top)

        scroll, col = scroll_column()
        outer.addWidget(scroll, 1)

        # ---- 1. asset
        card = self.step_root = StepCard(1, "Pick the asset", "Select the asset's top group, e.g. house_GRP. "
                                                              "Your progress is saved with the scene and picked "
                                                              "up again when you reopen it.")
        row = QtWidgets.QHBoxLayout()
        self.root_label = QtWidgets.QLabel()
        self.root_label.setWordWrap(True)
        pick = secondary_button("Use Selected Group", "Select the top group of the asset, then press this.")
        pick.clicked.connect(lambda *_: self.pick_root())
        row.addWidget(self.root_label, 1)
        row.addWidget(pick)
        card.add_layout(row)
        setups = QtWidgets.QHBoxLayout()
        self.setup_combo = _guard_focus(_Combo())
        self.setup_combo.setToolTip("Every Smart UDIM setup in this scene, with how far it got. Pick one to "
                                    "carry on with it.")
        self.setup_combo.activated.connect(self._setup_chosen)
        fresh = secondary_button("Start Fresh", "Forget this setup's saved reports and results and start the "
                                                "steps again. Groups, marks, locks and UVs stay as they are.")
        fresh.clicked.connect(lambda *_: self.start_fresh())
        self.setup_label = QtWidgets.QLabel("Setups")
        setups.addWidget(self.setup_label)
        setups.addWidget(self.setup_combo, 1)
        setups.addWidget(fresh)
        card.add_layout(setups)
        self.resume_label = hint_label("")
        self.resume_label.setVisible(False)
        card.add(self.resume_label)
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
                                           "Sections are bands of UDIM rows (e.g. one wing each). Inside a "
                                           "section, material groups hold the meshes that share a material. "
                                           "Double-click a name or TD % to edit it; right-click for actions.")
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels(["Group", "TD %", "Cover", "Items", "Stack", "Lock", "Orient"])
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setMinimumHeight(220)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(self.COL_NAME, QtWidgets.QHeaderView.Stretch)
        for c in (self.COL_TD, self.COL_COV, self.COL_ITEMS, self.COL_STACK, self.COL_LOCK, self.COL_ORIENT):
            header.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemDoubleClicked.connect(self._item_double_clicked)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        card.add(self.tree)
        self._group_actions = {
            "from_group": ("Section from Group", "Select one or more groups in the Outliner: each becomes a section "
                                                 "named after it (westWing_GRP -> westWing) holding every mesh "
                                                 "inside. New meshes added to the group later go there on Scan.",
                           self.section_from_group),
            "to_section": ("Move to Section", "Select meshes or groups in the scene, highlight a section here, "
                                              "then press this. Meshes keep their material groups.",
                           self.move_selection_to_section),
            "del_section": ("Delete Section", "Remove the highlighted section. Its meshes go back to the section "
                                              "of the group they're in, or the first section. One Ctrl+Z.",
                            self.delete_sections),
            "up": ("Move Up", "Lay this section out earlier (lower rows).", lambda: self.move_section(-1)),
            "down": ("Move Down", "Lay this section out later (higher rows).", lambda: self.move_section(1)),
            "select": ("Select", "Select the meshes / faces in the highlighted sections or groups.",
                       self.select_members),
            "to_group": ("Move to Group", "Move the selected meshes / faces (or everything in selected groups) "
                                          "into the highlighted material group.", self.assign_selection),
            "new_group": ("New Material Group", "Make a material group in the highlighted section from the "
                                                "selected meshes / faces (or groups).", self.new_group),
        }
        for title, keys in (("Sections", ("from_group", "to_section", "del_section", "up", "down")),
                            ("Material groups", ("select", "to_group", "new_group"))):
            label = QtWidgets.QLabel(title)
            label.setProperty("unlokHint", True)
            card.add(label)
            grid = QtWidgets.QGridLayout()
            grid.setSpacing(3)
            for i, key in enumerate(keys):
                text, tip, fn = self._group_actions[key]
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

        # ---- 6. auto UV
        card = self.step_auto = StepCard(6, "Auto UV", "For assets without good UVs: unwraps the meshes that "
                                                       "aren't laid out yet (worst first), keeps the ones that are, "
                                                       "and packs everything by section and material.")
        grid = Section("", header=False)
        backup_row = QtWidgets.QWidget()
        bl2 = QtWidgets.QHBoxLayout(backup_row)
        bl2.setContentsMargins(0, 0, 0, 0)
        self.auto_backup = CheckField("Back up UVs to")
        self.auto_backup.setValue(True)
        self.auto_backup.setToolTip("Copies each mesh's current UVs into this set first (only if it doesn't "
                                    "exist yet, so re-runs keep your originals). Restore Backup copies it back.")
        self.auto_backup_name = QtWidgets.QLineEdit("map1_backup")
        bl2.addWidget(self.auto_backup)
        bl2.addWidget(self.auto_backup_name, 1)
        grid.add_full(backup_row)
        self.auto_keep = FloatField(0.0, 1.0, 0.0, 1.0, decimals=2, step=0.05)
        self.auto_keep.setValue(AUTO_UV_KEEP_SCORE)
        grid.add_row("Keep above", self.auto_keep,
                     "Meshes whose UVs score at least this (1 = clean, 0 = none / garbage) are kept as they are.")
        self.auto_angle = FloatField(1.0, 179.0, 10.0, 90.0, decimals=0, step=5.0)
        self.auto_angle.setValue(40.0)
        grid.add_row("Seam angle", self.auto_angle,
                     "Edges sharper than this, and edges marked hard, become UV seams.")
        self.auto_clean = CheckField("Clean bad geometry first")
        self.auto_clean.setValue(True)
        self.auto_clean.setToolTip("Fix lamina, non-manifold and zero-area faces on the meshes being unwrapped.")
        grid.add_full(self.auto_clean)
        self.auto_pack = CheckField("Pack into UDIM tiles by section and material")
        self.auto_pack.setValue(True)
        self.auto_pack.setToolTip("Each material group gets its own tile; sections take their own rows and a "
                                  "material keeps the same column in every section.")
        grid.add_full(self.auto_pack)
        card.add(grid)
        analyse = secondary_button("Check UVs", "Score every mesh's existing UVs (are there any, are they "
                                                "stretched, overlapping or folded?) without changing anything. "
                                                "It decides what Auto UV will unwrap, and with colours on, good "
                                                "ones turn green and the rest yellow. Not texel density: that's "
                                                "step 7.")
        analyse.clicked.connect(lambda *_: self.analyse_uvs())
        restore = secondary_button("Restore Backup", "Copy the backup set back into the UV set, for the selected "
                                                     "meshes (or all of them when nothing is selected).")
        restore.clicked.connect(lambda *_: self.restore_backup())
        card.add(button_row(analyse, restore))
        mark_label = QtWidgets.QLabel("Selected meshes:")
        mark_keep = secondary_button("Keep UVs", "You've UV'd these but not laid them out: never re-unwrap them, "
                                                 "but still sort them into groups, scale them to texel density and "
                                                 "pack them with everything else.")
        mark_keep.clicked.connect(lambda *_: self.mark_status("keep"))
        mark_off = secondary_button("Hands off", "These are finished and already sit in their UDIM: never unwrap "
                                                 "or move them. The layout plans everything else around them.")
        mark_off.clicked.connect(lambda *_: self.mark_status("handsoff"))
        mark_auto = secondary_button("Auto", "Back to normal: the UV score decides whether to unwrap.")
        mark_auto.clicked.connect(lambda *_: self.mark_status("auto"))
        card.add(button_row(mark_label, mark_keep, mark_off, mark_auto))
        self.status_hint = hint_label("")
        card.add(self.status_hint)
        run_auto = primary_button("Auto UV")
        run_auto.setMinimumHeight(28)
        run_auto.setToolTip("Back up, clean, unwrap what isn't laid out and pack. One Ctrl+Z undoes it all.")
        run_auto.clicked.connect(lambda *_: self.auto_uv())
        run_sel = secondary_button("Auto UV Selected", "Only the selected meshes or groups (bit by bit). Packing "
                                                       "covers just the material groups they're in.")
        run_sel.setMinimumHeight(28)
        run_sel.clicked.connect(lambda *_: self.auto_uv(selected=True))
        row = button_row(run_auto, run_sel)
        row.layout().setStretch(0, 1)
        card.add(row)
        self.auto_progress = QtWidgets.QProgressBar()
        self.auto_progress.setRange(0, 1000)
        self.auto_progress.setTextVisible(False)
        self.auto_progress.setFixedHeight(8)
        self.auto_progress.setVisible(False)
        card.add(self.auto_progress)
        self.auto_progress_label = hint_label("")
        self.auto_progress_label.setVisible(False)
        card.add(self.auto_progress_label)
        self.auto_tree = QtWidgets.QTreeWidget()
        self.auto_tree.setColumnCount(5)
        self.auto_tree.setHeaderLabels(["Mesh", "Before", "After", "Result", "Status"])
        self.auto_tree.setMinimumHeight(150)
        self.auto_tree.setAlternatingRowColors(True)
        self.auto_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        ah = self.auto_tree.header()
        ah.setStretchLastSection(False)
        ah.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for c in (1, 2, 3, 4):
            ah.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeToContents)
        self.auto_tree.itemSelectionChanged.connect(self._auto_selected)
        self.auto_tree.itemDoubleClicked.connect(self._auto_double_clicked)
        card.add(self.auto_tree)
        col.addWidget(card)

        # ---- 7. smart layout
        card = self.step_layout = StepCard(7, "Smart layout", "Every shell at the same texel density, packed tile "
                                                              "by tile per section. Plan previews instantly; Apply "
                                                              "writes it (one Ctrl+Z).")
        grid = Section("", header=False)
        self.lay_density = FloatField(1.0, 100000.0, 64.0, 4096.0, decimals=0, step=64.0)
        self.lay_density.setValue(LAYOUT_DEFAULTS["texel_density"])
        grid.add_row("Density px/m", self.lay_density, "Target texel density in pixels per metre (times each "
                                                       "group's and section's TD %).")
        self.lay_map = ComboField(MAP_SIZES)
        self.lay_map.setValue(LAYOUT_DEFAULTS["map_size"])
        grid.add_row("Map size", self.lay_map, "Texture resolution of one UDIM tile.")
        self.lay_mode = ComboField(LAYOUT_MODES)
        grid.add_row("Mode", self.lay_mode, "Fixed density: use the density above.\n"
                                            "Fit to tiles: find the highest density that fits in Max tiles.")
        self.lay_tiles = IntField(1, 1000, 1, 60)
        self.lay_tiles.setValue(LAYOUT_DEFAULTS["max_tiles"])
        self.lay_tiles_label = grid.add_row("Max tiles", self.lay_tiles, "Tile budget for Fit to tiles.")
        self.lay_padding = IntField(0, 128, 0, 32)
        self.lay_padding.setValue(LAYOUT_DEFAULTS["padding_px"])
        grid.add_row("Padding px", self.lay_padding, "Gap between shells and around each tile, in pixels.")
        self.lay_growth = FloatField(0.0, 100.0, 0.0, 50.0, decimals=0, step=5.0)
        grid.add_row("Spare room %", self.lay_growth, "Leave this much extra space around every shell so small "
                                                      "model changes still fit without moving anything.")
        self.lay_orient = ComboField(ORIENTATIONS)
        grid.add_row("Orientation", self.lay_orient,
                     "Main axis: each shell's longest direction along U, lying flat (packs tightest).\n"
                     "Upright: world up along +V, so brick courses stay level and walls read upright.\n"
                     "Keep: never rotate (you already straightened them).\n"
                     "Override per group in the Orient column (or _up / _keep / _axis in the set name).")
        self.lay_handsoff = ComboField(HANDSOFF_MODES)
        grid.add_row("Hands-off tiles", self.lay_handsoff,
                     "What happens to the tiles your Hands off meshes sit in (step 6).\n"
                     "Pack around them: other pieces fill the free space around them (no space wasted).\n"
                     "Reserve their tiles: nothing else goes in those tiles. Simple and predictable, but a "
                     "small hands-off piece can leave the rest of its tile empty.")
        self.lay_rows = CheckField("Each section starts a new row")
        self.lay_rows.setValue(True)
        grid.add_full(self.lay_rows)
        self.lay_comp = CheckField("Auto-compensate pieces bigger than a tile")
        self.lay_comp.setValue(True)
        grid.add_full(self.lay_comp)
        card.add(grid)
        plan_btn = secondary_button("Plan", "Preview the layout in the map below without changing anything.")
        plan_btn.clicked.connect(lambda *_: self.plan_layout())
        self.apply_btn = primary_button("Apply Layout")
        self.apply_btn.setMinimumHeight(28)
        self.apply_btn.setToolTip("Write the planned layout into the UV set (old UVs backed up if step 6's "
                                  "backup is ticked). One Ctrl+Z undoes it.")
        self.apply_btn.clicked.connect(lambda *_: self.apply_layout())
        card.add(button_row(plan_btn, self.apply_btn))
        self.udim_map = UdimMapWidget()
        self.udim_map.groupClicked.connect(self._map_clicked)
        card.add(self.udim_map)
        self.layout_summary = hint_label("")
        card.add(self.layout_summary)
        col.addWidget(card)
        for w in (self.lay_density, self.lay_map, self.lay_mode, self.lay_tiles, self.lay_padding, self.lay_growth,
                  self.lay_orient, self.lay_handsoff, self.lay_rows, self.lay_comp):
            w.changed.connect(self._layout_settings_changed)

        # ---- 8. check & hand off
        card = self.step_check = StepCard(8, "Check & hand off", "Validate the finished layout, then give texture "
                                                                 "artists a picture of what's where.")
        validate = primary_button("Validate")
        validate.setMinimumHeight(28)
        validate.setToolTip("Look for UVs outside the UDIM range, shells crossing tiles, overlaps, flipped or "
                            "tiny shells, density off target and shells closer than the padding.")
        validate.clicked.connect(lambda *_: self.validate())
        card.add(validate)
        self.check_tree = QtWidgets.QTreeWidget()
        self.check_tree.setColumnCount(2)
        self.check_tree.setHeaderLabels(["Check", "Count"])
        self.check_tree.setMinimumHeight(130)
        self.check_tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.check_tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.check_tree.header().setStretchLastSection(False)
        self.check_tree.itemSelectionChanged.connect(self._check_selected)
        card.add(self.check_tree)
        self.sheet_size = ComboField(list(SHEET_SIZES))
        self.sheet_size.setValue("Medium")
        self.sheet_size.setToolTip("Pixels per UDIM tile in the sheet: Small 256, Medium 512, Large 1024.")
        save = secondary_button("Save Sheet PNG...", "Save a picture of the layout (shells coloured by material, "
                                                    "tile numbers, sections and a legend) for texture artists.")
        save.clicked.connect(lambda *_: self.save_sheet())
        copy = secondary_button("Copy Sheet", "Copy the same picture to the clipboard (handy where saving "
                                             "files is locked down).")
        copy.clicked.connect(lambda *_: self.copy_sheet())
        sheet_label = QtWidgets.QLabel("Sheet")
        card.add(button_row(sheet_label, self.sheet_size, save, copy))
        col.addWidget(card)
        self._update_layout_enabled()
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
        auto_done = bool(self.auto_result and not self.auto_result.get("analysed_only"))
        auto_clean = auto_done and not any(r["action"] in ("failed", "check") for r in self.auto_result["rows"])
        self.step_prep.set_state("done" if prepped else ("current" if clean_groups and not auto_done else "todo"))
        self.step_auto.set_state("done" if auto_clean else ("current" if clean_groups else "todo"))
        self.step_layout.set_state("done" if self.layout_applied else ("current" if auto_done else "todo"))
        res = self.validation
        problems = sum(len(v) for k, v in res["items"].items() if VALIDATION_LABELS[k][1] == "skip") if res else 0
        warns = sum(len(v) for k, v in res["items"].items() if VALIDATION_LABELS[k][1] == "warn") if res else 0
        self.step_check.set_state("done" if res and not problems else ("current" if self.layout_applied else "todo"))
        if not has_root and SmartUdimAsset.all():
            self.next_banner.set_text("This scene has Smart UDIM setups. Pick one under <b>Setups</b> in step 1 "
                                      "to carry on, or select another top group and press <b>Use Selected "
                                      "Group</b>.")
        elif not has_root:
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
        elif res and problems:
            self.next_banner.set_text("Validation found <b>%d problem(s)</b>%s. Click them in step 8 to select "
                                      "the faces." % (problems, (" and %d warning(s)" % warns) if warns else ""),
                                      tag="CHECK", tone="warn")
        elif res:
            self.next_banner.set_text("Layout checked%s. <b>Save Sheet PNG</b> (or Copy Sheet) for the texture "
                                      "artists, and lock finished groups so re-layouts leave them alone." % (
                                          (" with %d warning(s)" % warns) if warns else ": all good"),
                                      tag="DONE", tone="done")
        elif self.layout_applied:
            self.next_banner.set_text("Laid out into <b>%d tile(s)</b> at %d px/m. Press <b>Validate</b> in step 8, "
                                      "then save the hand-off sheet." % (
                                          self.layout_applied["tiles"], round(self.layout_applied["density"])))
        elif auto_done and self._plan is not None:
            self.next_banner.set_text("Check the map in step 7 (hover for details), then press <b>Apply "
                                      "Layout</b>.")
        elif auto_done and not any(r["action"] in ("failed", "check") for r in self.auto_result["rows"]):
            self.next_banner.set_text("UVs are in place. Set the texel density in <b>step 7</b> and press "
                                      "<b>Plan</b> for an even-density UDIM layout.")
        elif auto_done:
            rows = self.auto_result["rows"]
            n_check = sum(1 for r in rows if r["action"] in ("failed", "check"))
            if n_check:
                self.next_banner.set_text("Auto UV done. <b>%d mesh(es)</b> still need a look (amber / red in step "
                                          "6): click one to select it." % n_check, tag="CHECK", tone="warn")
            else:
                self.next_banner.set_text("Auto UV done: everything is unwrapped and packed into UDIMs. Polish "
                                          "by hand from here; old UVs are in the backup set.", tag="DONE",
                                          tone="done")
        elif not self.report:
            self.next_banner.set_text("Check the groups in step 3, then <b>Run Pre-process</b>. No good UVs yet? "
                                      "Press <b>Auto UV</b> in step 6 to unwrap and pack the lot.")
        elif skipped:
            self.next_banner.set_text("%d mesh(es) will be skipped (no UVs / instanced). Fix them and run "
                                      "<b>Pre-process</b> again, or carry on without them." % len(skipped),
                                      tag="CHECK", tone="warn")
        else:
            self.next_banner.set_text("Press <b>Auto UV</b> (step 6) to unwrap what isn't laid out and pack it "
                                      "all into UDIMs, or <b>Analyse</b> to see the worst meshes first.")

    # ============================================================ state
    def set_status(self, text, level="info"):
        color = LEVEL_COLORS.get(level, "#a8a8a8") if level != "error" else "#e06060"
        self.status.setText('<span style="color:%s">%s</span>' % (color, text))

    def _asset(self):
        if self.asset is not None and not self.asset.exists():
            self.asset = None
        return self.asset

    def set_asset(self, asset, restore=True):
        """Switch to an asset; restore=True picks up its saved progress."""
        self.asset = asset
        self.report = {}
        self.auto_result = None
        self._plan = None
        self._collected = None
        self.layout_applied = None
        self.validation = None
        self.restored = None
        self._applied = {}
        if hasattr(self, "colour_box"):
            self.colour_box.setValue(uv_colours_on(asset))
        if hasattr(self, "check_tree"):
            self.check_tree.clear()
        if hasattr(self, "udim_map"):
            self.udim_map.set_plan(None, None)
            self.layout_summary.setText("")
        if asset is not None and restore and hasattr(self, "resume_label"):
            self._restore_session()
        self._fill_report()
        self.refresh()
        self._fill_auto()
        self._fill_check()
        self._update_guidance()

    # ------------------------------------------------------------ session
    def _widgets(self):
        """Settings that are saved with the session: name -> widget."""
        return {"source": self.source_combo, "from_groups": self.from_groups, "fix_lamina": self.fix_lamina,
                "fix_nonmanifold": self.fix_nonmanifold, "fix_zero": self.fix_zero, "uv_set": self.uv_set,
                "auto_backup": self.auto_backup, "auto_backup_name": self.auto_backup_name,
                "auto_keep": self.auto_keep, "auto_angle": self.auto_angle, "auto_clean": self.auto_clean,
                "auto_pack": self.auto_pack, "lay_density": self.lay_density,
                "lay_map": self.lay_map, "lay_mode": self.lay_mode, "lay_tiles": self.lay_tiles,
                "lay_padding": self.lay_padding, "lay_growth": self.lay_growth, "lay_orient": self.lay_orient,
                "lay_handsoff": self.lay_handsoff, "lay_rows": self.lay_rows, "lay_comp": self.lay_comp,
                "sheet_size": self.sheet_size}

    def _save_session(self):
        """Called after every step, so a closed scene picks up where it was."""
        asset = self._asset()
        if asset is None:
            return
        try:
            settings = {}
            for name, w in self._widgets().items():
                settings[name] = w.text() if isinstance(w, QtWidgets.QLineEdit) else w.value()
            data = {"version": 1, "saved": time.strftime("%d %b %H:%M"), "saved_at": time.time(),
                    "report": self.report or {},
                    "auto": self.auto_result, "layout_applied": self.layout_applied,
                    "validation": pack_validation(self.validation), "settings": settings}
            save_session(asset, data)
            self._refresh_setups()
        except Exception:
            traceback.print_exc()

    def _restore_session(self):
        data = load_session(self.asset)
        if not data:
            self.resume_label.setVisible(False)
            return
        for name, value in (data.get("settings") or {}).items():
            w = self._widgets().get(name)
            if w is None or value is None:
                continue
            if isinstance(w, QtWidgets.QLineEdit):
                w.setText(str(value))
            else:
                w.setValue(value)
        self._update_layout_enabled()
        exists = cmds.objExists
        self.report = {cat: {m: n for m, n in items.items() if exists(m)}
                       for cat, items in (data.get("report") or {}).items()}
        self.report = {cat: items for cat, items in self.report.items() if items}
        auto = data.get("auto")
        if auto and auto.get("rows"):
            auto["rows"] = [r for r in auto["rows"] if exists(r["mesh"])]
            auto["tiles"] = [tuple(t) for t in auto.get("tiles", [])]
            self.auto_result = auto
        self.layout_applied = data.get("layout_applied")
        self.validation = unpack_validation(data.get("validation"))
        self.restored = data
        self.resume_label.setText("Picked up where you left off (saved %s): %s. Groups, Keep UVs / Hands off "
                                  "marks and locks come straight from the scene's sets. Re-run Analyse or "
                                  "Validate if you've edited meshes since." % (data.get("saved", "?"),
                                                                              session_summary(data)))
        self.resume_label.setVisible(True)
        self.set_status("Picked up %s where you left off: %s." % (
            short_name(self.asset.root_group() or self.asset.name()), session_summary(data)))

    def _refresh_setups(self):
        assets = SmartUdimAsset.all()
        self.setup_combo.blockSignals(True)
        self.setup_combo.clear()
        current = self.asset.uuid if self.asset is not None else None
        for a in assets:
            data = load_session(a)
            name = short_name(a.root_group() or a.name())
            text = "%s  -  %s" % (name, session_summary(data)) + (
                ("  (saved %s)" % data["saved"]) if data.get("saved") else "")
            self.setup_combo.addItem(text, a.uuid)
            if a.uuid == current:
                self.setup_combo.setCurrentIndex(self.setup_combo.count() - 1)
        if current is None and assets:
            self.setup_combo.insertItem(0, "Pick a setup to carry on with...", None)
            self.setup_combo.setCurrentIndex(0)
        self.setup_combo.blockSignals(False)
        multi = len(assets) > 1 or (assets and current is None)
        self.setup_combo.setVisible(bool(multi))
        self.setup_label.setVisible(bool(multi))

    @ui_safe
    def _setup_chosen(self, index):
        uuid = self.setup_combo.itemData(index)
        if not uuid:
            return
        for a in SmartUdimAsset.all():
            if a.uuid == uuid and (self.asset is None or self.asset.uuid != uuid):
                self.set_asset(a)
                return

    @ui_safe
    def start_fresh(self):
        asset = self._asset()
        if asset is None:
            return
        save_session(asset, {})
        self.set_asset(asset, restore=False)
        self.resume_label.setVisible(False)
        self.set_status("Starting fresh on %s: saved reports and results cleared (groups, marks, locks and UVs "
                        "unchanged)." % short_name(asset.root_group() or asset.name()))

    @staticmethod
    def pick_startup_asset():
        """The setup to open with: the one saved most recently, else the only one."""
        assets = SmartUdimAsset.all()
        if len(assets) == 1:
            return assets[0]
        best, best_t = None, 0.0
        for a in assets:
            t = load_session(a).get("saved_at") or 0.0
            if t > best_t:
                best, best_t = a, t
        return best

    @ui_safe
    def refresh(self):
        self._collected = None  # shells are re-read on the next Plan
        asset = self._asset()
        if asset is None or not asset.root_group():
            self.snapshot = None
            self._refresh_setups()
            self.root_label.setText('<span style="color:#8c8c8c">Pick the asset\'s top group</span>')
            self._fill_tree()
            self._fill_naming()
            if not self.status.text():
                self.set_status("Select the asset's top group and press 'Use Selected Group'.")
            return
        self.snapshot = asset.read()
        self._refresh_setups()
        self.root_label.setText("<b>%s</b> &nbsp;<span style='color:#8c8c8c'>(%s)</span>" % (
            short_name(self.snapshot["group"]), asset.name()))
        self._fill_tree()
        self._fill_naming()
        self._fill_status_hint()
        self._update_states()

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
                    mitem.setCheckState(self.COL_LOCK, QtCore.Qt.Checked if mat["locked"] else QtCore.Qt.Unchecked)
                    mitem.setToolTip(self.COL_LOCK, "Locked groups keep their UVs and tiles when you lay out again.")
                    mitem.setText(self.COL_ORIENT, mat["orient"] or "auto")
                    mitem.setToolTip(self.COL_ORIENT, "Double-click to cycle: auto (the layout setting), up "
                                                      "(upright), keep (never rotate), axis (main axis).")
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
                                    "UnlokRenamer isn't loaded in this Maya session (paste and run "
                                    "unlok_renamer.py once, then re-scan).")
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
        elif column == self.COL_LOCK and set_role(node) == "material":
            locked = item.checkState(self.COL_LOCK) == QtCore.Qt.Checked
            set_group_lock(node, locked)
            self._collected = None
            self.set_status("%s %s." % (node, "locked: it keeps its UVs and tiles" if locked else "unlocked"))
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
        elif column == self.COL_ORIENT:
            self._cycle_orient(item)

    @ui_safe
    def _cycle_orient(self, item):
        asset = self._asset()
        node = item.data(0, QtCore.Qt.UserRole)
        if asset is None or not node or set_role(node) != "material":
            return
        order = ["", "up", "keep", "axis"]
        cur = _get(node, UDIM_ORIENT, "") or ""
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else ""
        renamed = asset.set_group_values(node, orient=nxt)
        self._collected = None
        self.set_status("%s orientation: %s." % (renamed, nxt or "auto (layout setting)"))
        self._refresh_timer.start()

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

    def _tree_menu(self, pos):
        try:
            item = self.tree.itemAt(pos)
            role = set_role(item.data(0, QtCore.Qt.UserRole)) if item else None
            if item and not item.isSelected():
                self.tree.clearSelection()
                item.setSelected(True)
            keys = {"section": ("to_section", "del_section", "up", "down", "select"),
                    "material": ("to_group", "select")}.get(role, ())
            keys = keys + ("from_group",) if "from_group" not in keys else keys
            menu = QtWidgets.QMenu(self)
            for key in keys:
                text, tip, fn = self._group_actions[key]
                act = menu.addAction(text)
                act.setToolTip(tip)
                act.triggered.connect(lambda *_, f=fn: f())
            if role in ("section", "material"):
                menu.addSeparator()
                ren = menu.addAction("Rename")
                ren.triggered.connect(lambda *_: self.tree.editItem(item, self.COL_NAME))
            menu.exec_(self.tree.viewport().mapToGlobal(pos))
        except Exception:
            traceback.print_exc()

    @ui_safe
    def section_from_group(self, name=None):
        asset = self._asset()
        if asset is None:
            self.set_status("Pick the asset's top group first (step 1).", level="warn")
            return
        root = asset.root_group()
        groups = [g for g in cmds.ls(selection=True, long=True, type="transform") or []
                  if not cmds.listRelatives(g, shapes=True) and (g == root or g.startswith(root + "|"))]
        if not groups:
            self.set_status("Select one or more groups (under %s) in the Outliner first." % short_name(root),
                            level="warn")
            return
        if len(groups) == 1 and name is None:
            name, ok = QtWidgets.QInputDialog.getText(self, "Section from group", "Section name:",
                                                      text=SmartUdimAsset.section_name_for(groups[0]))
            if not ok or not name.strip():
                return
        made = []
        moved = 0
        with UndoChunk("Smart UDIM sections from groups"):
            for g in groups:
                sec, n = asset.section_from_group(g, name if len(groups) == 1 else None,
                                                  self.source_combo.value())
                made.append(sec)
                moved += n
        self.refresh()
        self.set_status("%d section(s) from groups (%s) holding %d mesh piece(s). One Ctrl+Z undoes it." % (
            len(made), ", ".join(parse_group_name(s)["key"] or s for s in made), moved))

    @ui_safe
    def move_selection_to_section(self):
        asset = self._asset()
        secs = self._selected_role("section") or [
            p for p in (self._parent_section(s) for s in self._selected_role("material")) if p]
        if asset is None or len(set(secs)) != 1:
            self.set_status("Highlight one section in the list first.", level="warn")
            return
        items = self._items_in_root(selection_items())
        if not items:
            self.set_status("Select meshes, faces or groups (under the root) to move.", level="warn")
            return
        asset.move_to_section(items, secs[0], self.source_combo.value())
        self.refresh()
        self.set_status("Moved %d mesh(es) into %s. One Ctrl+Z undoes it." % (
            len(items), parse_group_name(secs[0])["key"] or secs[0]))

    @ui_safe
    def delete_sections(self):
        asset = self._asset()
        secs = self._selected_role("section")
        if asset is None or not secs:
            self.set_status("Highlight the section(s) to delete.", level="warn")
            return
        moved = 0
        with UndoChunk("Smart UDIM delete sections"):
            for sec in secs:
                moved += asset.delete_section(sec, self.source_combo.value())
        self.refresh()
        self.set_status("Deleted %d section(s); %d mesh(es) moved to other sections. One Ctrl+Z undoes it." % (
            len(secs), moved))

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
        self._save_session()
        fixed = sum(sum(self.report.get(c, {}).values()) for c in ("lamina", "nonmanifold", "zeroarea"))
        skipped = len(skipped_meshes(self.report))
        warn = sum(len(self.report.get(c, {})) for c in ("ngons", "flipped", "remaining"))
        level = "warn" if (skipped or warn) else "info"
        self.set_status("Pre-process on %d meshes in %.2fs: %d problem(s) fixed, %d mesh(es) will be skipped, "
                        "%d with warnings." % (len(meshes), time.time() - t0, fixed, skipped, warn), level=level)

    def _layout_settings(self):
        return {"texel_density": self.lay_density.value(), "map_size": self.lay_map.value(),
                "mode": self.lay_mode.value(), "max_tiles": self.lay_tiles.value(),
                "padding_px": self.lay_padding.value(), "growth": self.lay_growth.value() / 100.0,
                "orientation": self.lay_orient.value(), "new_row_per_section": self.lay_rows.value(),
                "handsoff_tiles": self.lay_handsoff.value(),
                "auto_compensate": self.lay_comp.value()}

    def _update_layout_enabled(self):
        fit = self.lay_mode.value() == "Fit to tiles"
        self.lay_tiles.setEnabled(fit)
        self.lay_tiles_label.setEnabled(fit)
        self.lay_density.setEnabled(not fit)

    def _layout_settings_changed(self):
        self._update_layout_enabled()
        if self._plan is not None:
            self._replan_timer.start()  # live re-plan: pure math on cached shells

    def _replan(self):
        try:
            if self._plan is not None:
                self.plan_layout(quiet=True)
        except Exception:
            traceback.print_exc()

    @ui_safe
    def plan_layout(self, quiet=False):
        asset = self._asset()
        if asset is None or not asset.sections():
            self.set_status("Pick a root and Scan first.", level="warn")
            return None
        t0 = time.time()
        settings = self._layout_settings()
        if self._collected is None:  # orientation etc. are re-plans only: no scene read
            uv_set = self.uv_set.text().strip() or "map1"
            self._collected = collect_shells(asset, uv_set)
        self._plan = make_plan(self._collected, settings)
        self.udim_map.set_plan(self._collected, self._plan)
        self._summarise_plan(time.time() - t0)
        self._update_guidance()
        return self._plan

    def _summarise_plan(self, seconds):
        plan, col = self._plan, self._collected
        n_shells = len(plan["placements"])
        lines = ["%d shells from %d groups -> %d tile(s) at %d px/m (%s map), planned in %.2fs." % (
            n_shells, len(col["groups"]), len(plan["new_tiles"]), round(plan["density"]),
            plan["settings"]["map_size"], seconds)]
        if col["locked"]:
            lines.append("%d locked group(s) keep tiles %s." % (len(col["locked"]), ", ".join(
                str(t) for g in col["locked"] for t in g["tiles"])))
        changed = [st["key"] for st in plan["stats"].values() if st.get("changed") and not st.get("locked")]
        if changed:
            lines.append("Changed since last layout: %s." % ", ".join(sorted(set(changed))))
        if col.get("fixed"):
            lines.append("%d hands-off piece(s) stay put on tile(s) %s (%s)." % (
                len(col["fixed"]), ", ".join(str(t) for t in plan.get("fixed_tiles", [])),
                "packed around" if plan.get("pack_around") else "tiles reserved"))
        if col["skipped"]:
            lines.append("%d mesh(es) without usable UVs skipped (run Auto UV)." % len(col["skipped"]))
        lines.extend(plan["warnings"][:4])
        self.layout_summary.setText("\n".join(lines))

    @ui_safe
    def apply_layout(self):
        asset = self._asset()
        if asset is None:
            return
        self._replan_timer.stop()
        if self.plan_layout(quiet=True) is None:  # always apply exactly what the current settings plan
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            t0 = time.time()
            opts = self._auto_options()
            result = apply_layout(asset, self._collected, self._plan, uv_set=opts["uv_set"],
                                  backup=opts["backup"], backup_set=opts["backup_set"])
            seconds = time.time() - t0
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        plan = self._plan
        self.layout_applied = {"tiles": len(plan["new_tiles"]), "density": plan["density"]}
        self.validation = None
        self.check_tree.clear()
        self.refresh()
        self.plan_layout(quiet=True)  # re-read so the map shows what's in the scene now
        self._save_session()
        self.set_status("Laid out %d shells on %d mesh(es) into %d tile(s) at %d px/m in %.1fs." % (
            result["shells"], result["meshes"], self.layout_applied["tiles"], round(plan["density"]), seconds))
        self._update_guidance()

    @ui_safe
    def validate(self):
        asset = self._asset()
        if asset is None:
            self.set_status("Pick a root group first.", level="warn")
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.validation = validate_layout(asset, self.uv_set.text().strip() or "map1")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._fill_check()
        self._save_session()
        res = self.validation
        problems = sum(len(v) for k, v in res["items"].items() if VALIDATION_LABELS[k][1] == "skip")
        warnings = sum(len(v) for k, v in res["items"].items() if VALIDATION_LABELS[k][1] == "warn")
        self.set_status("Checked %d shells in %.2fs: %d problem(s), %d warning(s)." % (
            res["shells"], res["seconds"], problems, warnings), level="warn" if problems or warnings else "info")
        self._update_guidance()

    def _fill_check(self):
        self.check_tree.clear()
        res = self.validation
        if not res:
            return
        any_found = False
        for cat in VALIDATION_ORDER:
            found = res["items"].get(cat) or []
            if not found:
                continue
            any_found = True
            label, level = VALIDATION_LABELS[cat]
            top = QtWidgets.QTreeWidgetItem([label, str(len(found))])
            top.setForeground(0, QtGui.QBrush(QtGui.QColor(LEVEL_COLORS[level])))
            top.setData(0, QtCore.Qt.UserRole, [(it["mesh"], it["faces"]) for it in found])
            for it in found[:500]:
                child = QtWidgets.QTreeWidgetItem([short_name(it["mesh"]), ""])
                child.setToolTip(0, "%s\n%s" % (it["mesh"], it["detail"]))
                child.setText(1, "")
                child.setData(0, QtCore.Qt.UserRole, [(it["mesh"], it["faces"])])
                child.setText(0, "%s  -  %s" % (short_name(it["mesh"]), it["detail"]))
                top.addChild(child)
            self.check_tree.addTopLevelItem(top)
        if not any_found:
            ok = QtWidgets.QTreeWidgetItem(["All checks passed", ""])
            ok.setForeground(0, QtGui.QBrush(QtGui.QColor(LEVEL_COLORS["fixed"])))
            self.check_tree.addTopLevelItem(ok)

    def _check_selected(self):
        try:
            comps = []
            for it in self.check_tree.selectedItems():
                for mesh, faces in it.data(0, QtCore.Qt.UserRole) or []:
                    if cmds.objExists(mesh):
                        comps.extend("%s.%s" % (mesh, r) for r in face_ranges(faces))
            if comps:
                cmds.select(comps, replace=True)
        except Exception:
            traceback.print_exc()

    def _sheet(self):
        asset = self._asset()
        if asset is None:
            self.set_status("Pick a root group first.", level="warn")
            return None
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            return render_handoff_sheet(asset, self.uv_set.text().strip() or "map1",
                                        SHEET_SIZES.get(self.sheet_size.value(), 512))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    @ui_safe
    def save_sheet(self):
        asset = self._asset()
        if asset is None:
            return
        name = "%s_udim_layout.png" % sanitize_key(short_name(asset.root_group() or "asset"))
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save hand-off sheet", name, "PNG image (*.png)")
        if not path:
            return
        img = self._sheet()
        if img is None:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if img.save(path, "PNG"):
            self.set_status("Saved the hand-off sheet (%dx%d) to %s" % (img.width(), img.height(), path))
        else:
            self.set_status("Couldn't save to %s (is the folder writable?). Try Copy Sheet." % path, level="error")

    @ui_safe
    def copy_sheet(self):
        img = self._sheet()
        if img is None:
            return
        QtWidgets.QApplication.clipboard().setImage(img)
        self.set_status("Hand-off sheet (%dx%d) copied to the clipboard." % (img.width(), img.height()))

    def _map_clicked(self, node):
        try:
            if cmds.objExists(node):
                members = cmds.sets(node, q=True) or []
                if members:
                    cmds.select(members, replace=True)
                self.set_status("Selected %s." % node)
        except Exception:
            traceback.print_exc()

    def _auto_options(self):
        return dict(uv_set=self.uv_set.text().strip() or "map1",
                    backup=self.auto_backup.value(),
                    backup_set=self.auto_backup_name.text().strip() or "map1_backup",
                    keep_score=self.auto_keep.value(), hard_angle=self.auto_angle.value(),
                    clean_first=self.auto_clean.value(), pack=self.auto_pack.value())

    # ------------------------------------------------------------ UV states
    def _scores(self):
        """Score per mesh from the last Check UVs / Auto UV (before it ran:
        what happened since is in the tracking sets)."""
        rows = (self.auto_result or {}).get("rows") or []
        return {r["mesh"]: r["before"] for r in rows if r.get("before") is not None}

    def _update_states(self, recolour=True):
        asset = self._asset()
        states = uv_states(asset, self._scores(), self.auto_keep.value()) if asset else {}
        self.states = states
        counts = {}
        for s in states.values():
            counts[s] = counts.get(s, 0) + 1
        for state, b in self.legend.items():
            n = counts.get(state, 0)
            b.setText("%s  %d" % (UV_STATE_INFO[state][0], n))
            b.setEnabled(n > 0)  # all eight always shown, so the grid never has holes
        if recolour and asset is not None and self.colour_box.value():
            changed = {m: s for m, s in states.items() if self._applied.get(m) != s}
            if changed:
                show_uv_colours(asset, changed)
                self._applied.update(changed)

    def _colours_toggled(self):
        try:
            asset = self._asset()
            if asset is None:
                self.colour_box.setValue(False)
                self.set_status("Pick an asset first.", level="warn")
                return
            if self.colour_box.value():
                if not self._scores():
                    self.analyse_uvs()  # need scores to tell yellow from green
                self._applied = {}
                self._update_states()
                self.set_status("Colouring meshes by UV status (your real materials come back when you untick "
                                "it).")
            else:
                n = hide_uv_colours(asset)
                self._applied = {}
                self.set_status("Real materials back on %d mesh(es)." % n)
            self._save_session()
        except Exception as exc:
            traceback.print_exc()
            self.set_status("Error: %s" % exc, level="error")

    def _select_state(self, state):
        try:
            meshes = [m for m, s in (self.states or {}).items() if s == state and cmds.objExists(m)]
            if meshes:
                cmds.select(meshes, replace=True)
            else:
                cmds.select(clear=True)
            self.set_status("Selected %d mesh(es): %s." % (len(meshes), UV_STATE_INFO[state][0]))
        except Exception:
            traceback.print_exc()

    def _progress_start(self):
        self.auto_progress.setValue(0)
        self.auto_progress_label.setText("Starting... (Esc cancels)")
        self.auto_progress.setVisible(True)
        self.auto_progress_label.setVisible(True)
        scroll = self.step_auto.parentWidget().parentWidget().parentWidget()
        if hasattr(scroll, "ensureWidgetVisible"):
            scroll.ensureWidgetVisible(self.auto_progress_label)
        self.repaint()

    def _progress(self, fraction, text):
        """Progress callback: only repaints these widgets (no event
        processing, so nothing else can run in the middle of a scene edit).
        Maya's own progress bar keeps the window responsive and catches Esc."""
        self.auto_progress.setValue(int(fraction * 1000))
        self.auto_progress_label.setText(text.split(" - ", 1)[-1] + "  |  Esc cancels")
        self.auto_progress.repaint()
        self.auto_progress_label.repaint()

    def _progress_end(self):
        self.auto_progress.setVisible(False)
        self.auto_progress_label.setVisible(False)

    def _cancelled(self, result, what):
        if not result.get("cancelled"):
            return False
        self.set_status("%s cancelled during %s after %.1fs. %s" % (
            what, result["cancelled"], result["timing"].get("total", 0.0),
            "Ctrl+Z undoes what was done." if what == "Auto UV" else "Nothing was changed."), level="warn")
        return True

    @ui_safe
    def analyse_uvs(self):
        asset = self._asset()
        if asset is None:
            self.set_status("Pick a root group first.", level="warn")
            return
        t0 = time.time()
        opts = self._auto_options()
        self._progress_start()
        try:
            result = run_auto_uv(asset, uv_set=opts["uv_set"], keep_score=opts["keep_score"], analyse_only=True,
                                 progress_callback=self._progress)
        finally:
            self._progress_end()
        if self._cancelled(result, "Analyse"):
            return
        result["analysed_only"] = True
        self.auto_result = result
        self._fill_auto()
        self._update_states()
        self._save_session()
        todo = sum(1 for r in result["rows"] if r["action"] == "will unwrap")
        self.set_status("Analysed %d meshes in %.2fs: %d need unwrapping (worst first in step 6)." % (
            len(result["rows"]), time.time() - t0, todo))
        self._update_guidance()

    @ui_safe
    def auto_uv(self, selected=False):
        asset = self._asset()
        if asset is None:
            self.set_status("Pick a root group first.", level="warn")
            return
        if not asset.sections():
            self.set_status("Press Scan first so meshes are grouped by section and material.", level="warn")
            return
        only = None
        if selected:
            only = sorted(self._items_in_root(selection_items()))
            if not only:
                self.set_status("Select the meshes or groups to Auto UV first.", level="warn")
                return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self._progress_start()
        try:
            result = run_auto_uv(asset, progress_callback=self._progress, only=only,
                                 colours=self.colour_box.value(), **self._auto_options())
        finally:
            self._progress_end()
            QtWidgets.QApplication.restoreOverrideCursor()
        if self._cancelled(result, "Auto UV"):
            self.refresh()
            return
        if only is not None and self.auto_result and self.auto_result.get("rows"):
            fresh = dict((r["mesh"], r) for r in result["rows"])  # merge into the full list
            merged = [fresh.pop(r["mesh"], r) for r in self.auto_result["rows"]]
            result["rows"] = merged + list(fresh.values())
        self.auto_result = result
        self._fill_auto()
        self.refresh()
        self._save_session()
        rows = result["rows"]
        count = lambda *acts: sum(1 for r in rows if r["action"] in acts)  # noqa: E731
        level = "warn" if count("failed", "check") else "info"
        self.set_status("Auto UV in %.1fs: %d unwrapped, %d kept, %d to check, %d failed. %d tile(s) packed%s." % (
            result["timing"].get("total", 0.0), count("unwrapped", "check"), count("kept", "kept (check)"),
            count("check", "kept (check)"), count("failed"), len(result["tiles"]),
            ("; %d backed up to %s" % (result["backups"], self.auto_backup_name.text())) if result["backups"]
            else ""), level=level)

    @ui_safe
    def restore_backup(self):
        asset = self._asset()
        if asset is None:
            return
        meshes = list(self._items_in_root(selection_items())) or asset.meshes()[0]
        opts = self._auto_options()
        with UndoChunk("Smart UDIM restore UVs"):
            n = restore_uvs(meshes, opts["uv_set"], opts["backup_set"])
            asset.update_tool_sets(remove={"auto": meshes, "laidout": meshes, "problem": meshes})
        self.refresh()
        self.set_status("Restored %s from %s on %d mesh(es)." % (opts["uv_set"], opts["backup_set"], n),
                        level="info" if n else "warn")

    def _fill_auto(self):
        self.auto_tree.clear()
        if not self.auto_result:  # nothing analysed yet: still show the marks, read from the sets
            status = ((self.snapshot or {}).get("status")) or {}
            for mesh, st in sorted(status.items()):
                item = QtWidgets.QTreeWidgetItem([short_name(mesh), "-", "-", "not analysed", UV_STATUS_LABELS[st]])
                item.setData(0, QtCore.Qt.UserRole, mesh)
                item.setToolTip(0, mesh)
                item.setToolTip(4, "Double-click to cycle: Auto, Keep UVs, Hands off.")
                self.auto_tree.addTopLevelItem(item)
            return
        colors = {"unwrapped": LEVEL_COLORS["fixed"], "kept": LEVEL_COLORS["info"],
                  "check": LEVEL_COLORS["warn"], "kept (check)": LEVEL_COLORS["warn"],
                  "will unwrap": LEVEL_COLORS["warn"], "failed": LEVEL_COLORS["skip"],
                  "skip": LEVEL_COLORS["skip"], "keep": LEVEL_COLORS["info"]}
        colors.update({"keep UVs": LEVEL_COLORS["info"], "hands off": LEVEL_COLORS["info"]})
        status = ((self.snapshot or {}).get("status")) or {}
        fmt = lambda v: "-" if v is None else "%.2f" % v  # noqa: E731
        for r in self.auto_result["rows"]:
            item = QtWidgets.QTreeWidgetItem([short_name(r["mesh"]), fmt(r["before"]), fmt(r["after"]),
                                              r["action"], UV_STATUS_LABELS[status.get(r["mesh"], "auto")]])
            item.setToolTip(4, "Double-click to cycle: Auto, Keep UVs, Hands off.")
            item.setData(0, QtCore.Qt.UserRole, r["mesh"])
            item.setToolTip(0, r["mesh"])
            item.setToolTip(3, r["reason"] or r["action"])
            item.setForeground(3, QtGui.QBrush(QtGui.QColor(colors.get(r["action"], LEVEL_COLORS["info"]))))
            self.auto_tree.addTopLevelItem(item)

    @ui_safe
    def mark_status(self, status):
        asset = self._asset()
        if asset is None:
            self.set_status("Pick a root group first.", level="warn")
            return
        meshes = sorted(self._items_in_root(selection_items()))
        if not meshes:
            self.set_status("Select meshes under the asset first (a face selection marks its whole mesh).",
                            level="warn")
            return
        self._apply_status(meshes, status)

    def _apply_status(self, meshes, status):
        n = self._asset().set_uv_status(meshes, status)
        self.refresh()
        if self.auto_result and self.auto_result.get("analysed_only"):
            self.analyse_uvs()  # re-score with the new marks
        else:
            self._fill_auto()
        if self._plan is not None:
            self.plan_layout(quiet=True)
        self._save_session()
        self.set_status("%d mesh(es) marked %s." % (n, UV_STATUS_LABELS[status]))
        self._update_guidance()

    @ui_safe
    def _auto_double_clicked(self, item, column):
        mesh = item.data(0, QtCore.Qt.UserRole)
        if column != 4 or not mesh or self._asset() is None:
            return
        cur = ((self.snapshot or {}).get("status") or {}).get(mesh, "auto")
        self._apply_status([mesh], UV_STATUSES[(UV_STATUSES.index(cur) + 1) % len(UV_STATUSES)])

    def _fill_status_hint(self):
        status = (self.snapshot or {}).get("status") or {}
        keep = sum(1 for s in status.values() if s == "keep")
        off = sum(1 for s in status.values() if s == "handsoff")
        if keep or off:
            self.status_hint.setText("Marked: %d Keep UVs (laid out, never unwrapped), %d Hands off (never "
                                     "touched). Double-click Status below to change one." % (keep, off))
        else:
            self.status_hint.setText("Already UV'd some meshes? Select them and mark Keep UVs, or Hands off if "
                                     "they're finished and in their UDIM.")

    def _auto_selected(self):
        try:
            self._select_nodes([it.data(0, QtCore.Qt.UserRole) for it in self.auto_tree.selectedItems()])
        except Exception:
            traceback.print_exc()

    @ui_safe
    def open_renamer(self):
        opener = _unlok_renamer_main()
        if opener is None:
            self.set_status("UnlokRenamer isn't loaded: paste unlok_renamer.py into the Script Editor and run it "
                            "once, then try again.", level="warn")
            return
        opener()

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
        ]
        _registry()["jobs"].extend(self._jobs)
        # New / Open: API scene messages fire during the file command itself
        # (scriptJob events can wait until Maya idles). Never touch the scene
        # from inside the callback: just queue the reload on the Qt loop.
        for msg in (om.MSceneMessage.kAfterNew, om.MSceneMessage.kAfterOpen):
            cid = om.MSceneMessage.addCallback(msg, lambda *_: self._scene_timer.start())
            self._callbacks.append(cid)
            _registry()["callbacks"].append(cid)

    def _on_scene_changed(self):
        try:
            self._collected = None
            self._plan = None
            self.set_asset(self.pick_startup_asset())
        except Exception:
            traceback.print_exc()

    def shutdown(self):
        self._refresh_timer.stop()
        self._scene_timer.stop()
        cbs = _registry()["callbacks"]
        for cid in self._callbacks:
            try:
                om.MMessage.removeCallback(cid)
            except Exception:
                pass
            if cid in cbs:
                cbs.remove(cid)
        self._callbacks = []
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
# Bevel Resolver - engine
# =============================================================================
#
# A chamfer-off bevel (support loops that keep a hard edge under SubD) leaves
# n-gons wherever a bevelled edge chain ends: the chamfer-corner cap spills one
# extra vertex into every face around the old end vertex. So you get
# cut-corner 5-gons, 6-gons with two chamfer tips, and an odd-sided cap.
#
# An odd-sided face can never be split into quads on its own (a quad mesh of a
# disk always has an even boundary). So the resolver works in two passes:
#   1. Parity: pair every odd n-gon with another odd face. Neighbours share an
#      edge, which gets one new vertex (the two chamfers "merge"). Otherwise a
#      short straight edge loop runs between them through flat quads (or
#      passes an even n-gon by adding a vertex on the way in and one out).
#   2. Split: every n-gon (now even) is cut into quads. If support loops end
#      on opposite sides in matching numbers they carry straight across (a
#      grid). Otherwise it gets diagonals between its existing vertices: every
#      possible split is scored, and the best one has the squarest quads,
#      gives the bevel's spilled vertices their fourth edge (so they stop
#      being poles), and leaves any pole on the flat area, not on a bevel.
# The plan is made from one snapshot of the mesh per pass. Maya keeps vertex,
# edge and face indices when it splits (new parts are appended), so the plan
# stays valid while the cuts are made.

BR_SCOPES = ("Bevel n-gons", "All n-gons")
BR_DEFAULTS = {"scope": "Bevel n-gons", "strip_ratio": 0.3, "max_loop": 6, "use_border": True}
BR_MAX_SIDES = 16
BR_REASONS = {
    "unpaired": "Odd-sided with no odd face to pair with nearby",
    "no_split": "No clean way to split into quads",
    "too_many": "More than %d sides" % BR_MAX_SIDES,
    "holed": "Face has holes",
    "degenerate": "Zero-area face (overlapping vertices)",
}

_BR_SPLITS = {}


def _br_ekey(a, b):
    return (a, b) if a < b else (b, a)


def _br_splits(n):
    """Every way to cut a polygon 0..n-1 (n even) into quads with diagonals.

    Returns a list of splits, each a list of quads (tuples of corner indices).
    There are 3 for a hexagon, 12 for an octagon and 7,752 for 16 sides.
    """
    if n in _BR_SPLITS:
        return _BR_SPLITS[n]
    memo = {}

    def rec(poly):
        if len(poly) == 4:
            return [[poly]]
        if poly in memo:
            return memo[poly]
        out = []
        m = len(poly)
        # The quad on the side poly[0]-poly[1] is (poly[0], poly[1], poly[x], poly[y]).
        # The three pieces it leaves (poly[1..x], poly[x..y] and poly[y..]+poly[0])
        # must each be a plain side or an even polygon.
        for x in range(2, m - 1, 2):
            for y in range(x + 1, m, 2):
                parts = [poly[1:x + 1], poly[x:y + 1], poly[y:] + poly[:1]]
                subs = [[[]] if len(p) == 2 else rec(p) for p in parts]
                quad = (poly[0], poly[1], poly[x], poly[y])
                for a in subs[0]:
                    for b in subs[1]:
                        for c in subs[2]:
                            out.append([quad] + a + b + c)
        memo[poly] = out
        return out

    _BR_SPLITS[n] = rec(tuple(range(n)))
    return _BR_SPLITS[n]


class BevelTopology(object):
    """Plain-Python snapshot of a mesh for planning (one API read)."""

    def __init__(self, dag):
        fn = om.MFnMesh(dag)
        counts, conn = fn.getVertices()
        conn = list(conn)
        self.pts = [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kObject)]
        self.faces = []
        off = 0
        for c in counts:
            self.faces.append(conn[off:off + c])
            off += c
        self.edge_faces = {}
        for f, vs in enumerate(self.faces):
            prev = vs[-1]
            for v in vs:
                self.edge_faces.setdefault((prev, v) if prev < v else (v, prev), []).append(f)
                prev = v
        self.valence = [0] * len(self.pts)
        self.border = set()
        for (a, b), fs in self.edge_faces.items():
            self.valence[a] += 1
            self.valence[b] += 1
            if len(fs) == 1:
                self.border.add(a)
                self.border.add(b)
        holes = fn.getHoles()
        info = list(holes[0]) if holes else []
        self.holed = set(info[0::3])
        self._bend = {}

    def dist(self, a, b):
        p, q = self.pts[a], self.pts[b]
        return math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2)

    def strip_faces(self, ratio):
        """Thin quads: bevel / support-loop strips."""
        out = set()
        for f, vs in enumerate(self.faces):
            if len(vs) != 4:
                continue
            a = self.dist(vs[0], vs[1]) + self.dist(vs[2], vs[3])
            b = self.dist(vs[1], vs[2]) + self.dist(vs[3], vs[0])
            if min(a, b) < ratio * max(a, b):
                out.add(f)
        return out

    def _corner_sum(self, face, a, b):
        """Normal of `face` near its side a-b (sum of the two corner normals)."""
        vs = self.faces[face]
        n = len(vs)
        out = [0.0, 0.0, 0.0]
        for v in (a, b):
            i = vs.index(v)
            p, c, q = self.pts[vs[i - 1]], self.pts[v], self.pts[vs[(i + 1) % n]]
            u = (q[0] - c[0], q[1] - c[1], q[2] - c[2])
            w = (p[0] - c[0], p[1] - c[1], p[2] - c[2])
            out[0] += u[1] * w[2] - u[2] * w[1]
            out[1] += u[2] * w[0] - u[0] * w[2]
            out[2] += u[0] * w[1] - u[1] * w[0]
        ln = math.sqrt(out[0] ** 2 + out[1] ** 2 + out[2] ** 2)
        return [c / ln for c in out] if ln > 1e-12 else None

    def edge_bend(self, key):
        """0 where the faces on both sides of an edge are flat, 1 at a 90 degree
        corner. Poles and new vertices belong on flat edges."""
        if key in self._bend:
            return self._bend[key]
        fs = self.edge_faces.get(key, [])
        if len(fs) != 2:
            bend = 0.0 if len(fs) == 1 else 2.0
        else:
            n1, n2 = self._corner_sum(fs[0], *key), self._corner_sum(fs[1], *key)
            bend = 1.0 if n1 is None or n2 is None else 1.0 - (n1[0] * n2[0] + n1[1] * n2[1] + n1[2] * n2[2])
        self._bend[key] = bend
        return bend

    def degenerate(self, face):
        """Zero area, or two corners on the same spot (bevels through tight
        corners leave these)."""
        vs = self.faces[face]
        if self.normal(vs) is None:
            return True
        size = max(self.dist(vs[i - 1], vs[i]) for i in range(len(vs)))
        seen = set()
        for v in vs:
            key = tuple(int(round(c / (size * 1e-4))) for c in self.pts[v])
            if key in seen:
                return True
            seen.add(key)
        return False

    def normal(self, verts):
        """Newell normal of a polygon (works for bent n-gons)."""
        nx = ny = nz = 0.0
        prev = self.pts[verts[-1]]
        for v in verts:
            p = self.pts[v]
            nx += (prev[1] - p[1]) * (prev[2] + p[2])
            ny += (prev[2] - p[2]) * (prev[0] + p[0])
            nz += (prev[0] - p[0]) * (prev[1] + p[1])
            prev = p
        ln = math.sqrt(nx * nx + ny * ny + nz * nz)
        return (nx / ln, ny / ln, nz / ln) if ln > 1e-12 else None


def bevel_ngons(topo, faces=None, scope="Bevel n-gons", strip_ratio=0.3):
    """N-gons to resolve. 'Bevel n-gons' keeps the ones that touch a thin bevel
    strip, plus n-gons up to two steps away from those through shared vertices
    (so the face between two chamfer tips counts too)."""
    pool = range(len(topo.faces)) if faces is None else faces
    ngons = set(f for f in pool if len(topo.faces[f]) > 4)
    if scope != "Bevel n-gons" or not ngons:
        return sorted(ngons)
    strip_verts = set()
    for f in topo.strip_faces(strip_ratio):
        strip_verts.update(topo.faces[f])
    by_vert = {}
    for f in ngons:
        for v in topo.faces[f]:
            by_vert.setdefault(v, []).append(f)
    found = set(f for f in ngons if any(v in strip_verts for v in topo.faces[f]))
    ring = set(found)
    for _ in range(2):
        nxt = set()
        for f in ring:
            for v in topo.faces[f]:
                nxt.update(g for g in by_vert[v] if g not in found)
        found.update(nxt)
        ring = nxt
    return sorted(found)


def _br_odd_paths(topo, start, partners, quads, ngons, strips, max_loop, use_border):
    """Ways to give odd face `start` one more side, cheapest first.

    A chain of new vertices leaves through one of its edges. Through a plain
    quad it runs straight to the opposite edge and cuts the quad in two (an
    edge loop). Through an even target n-gon it just leaves by another edge:
    the n-gon gains two vertices, stays even, and is split later. The chain
    ends at another odd face (or the mesh border). New vertices on bent edges
    (hard corners) and loops along bevel strips cost more.
    Returns [(cost, partner or None, edges, via)]; via[i] = (face, cut) is the
    face between edges[i] and edges[i + 1].
    """
    import heapq
    vs = topo.faces[start]
    n = len(vs)
    heap = []
    for i in range(n):
        key = _br_ekey(vs[i], vs[(i + 1) % n])
        heap.append((4.0 * topo.edge_bend(key), i, start, key, (key,), ()))
    heapq.heapify(heap)
    tick = n
    found, seen, pops = {}, set(), 0
    while heap and pops < 300:
        cost, _, cur, key, edges, via = heapq.heappop(heap)
        pops += 1
        if len(found) >= 4 and cost > min(o[0] for o in found.values()) + 6.0:
            break  # the rest would never be picked
        if (cur, key) in seen:
            continue
        seen.add((cur, key))
        nbs = [f for f in topo.edge_faces[key] if f != cur]
        if not nbs:
            if use_border and ("border", key) not in found:
                found[("border", key)] = (cost + 1.5, None, edges, via)
            continue
        nb = nbs[0]
        if len(nbs) > 1 or nb == start or any(nb == f for f, _ in via):
            continue
        if nb in partners:
            if nb not in found:
                # A triangle partner turns into a quad: a small bonus.
                found[nb] = (cost - (0.3 if len(topo.faces[nb]) == 3 else 0.0), nb, edges, via)
            continue
        if len(via) >= max_loop:
            continue
        q = topo.faces[nb]
        if nb in quads:
            k = [j for j in range(4) if _br_ekey(q[j], q[(j + 1) % 4]) == key][0]
            nxt = [(_br_ekey(q[(k + 2) % 4], q[(k + 3) % 4]), True)]
            step = 1.0
            if nb in strips:
                # Running along a bevel strip would add a loop to the bevel: avoid.
                step += 6.0 if topo.dist(*key) < topo.dist(q[(k + 1) % 4], q[(k + 2) % 4]) else 2.0
        elif nb in ngons and len(q) + 2 <= BR_MAX_SIDES:
            m = len(q)
            nxt = [(_br_ekey(q[j], q[(j + 1) % m]), False) for j in range(m)]
            step = 1.5
        else:
            continue
        for k2, cut in nxt:
            if k2 == key or k2 in edges:
                continue
            tick += 1
            heapq.heappush(heap, (cost + step + 4.0 * topo.edge_bend(k2), tick, nb, k2, edges + (k2,),
                                  via + ((nb, cut),)))
    return sorted(found.values(), key=lambda o: o[0])


BR_UNPAIRED_COST = 40.0


def _br_best_matching(nodes, options):
    """Cheapest way to pair up `nodes` (a small cluster of odd faces).

    options[f] lists (cost, partner, path); partner is another node, or a free
    end (border, triangle) when it isn't in `nodes`. Exact bitmask search, so
    two neighbours don't grab each other when that strands a third.
    """
    pos = dict((f, i) for i, f in enumerate(nodes))
    memo = {}

    def solve(mask):
        if mask == 0:
            return 0.0, []
        if mask in memo:
            return memo[mask]
        if len(memo) > 200000:
            raise _BRTooBig()
        i = (mask & -mask).bit_length() - 1
        f = nodes[i]
        rest = mask & ~(1 << i)
        sub_cost, sub_pick = solve(rest)
        best = (sub_cost + BR_UNPAIRED_COST, sub_pick)
        for cost, other, path in options[f]:
            j = pos.get(other)
            if j is None:
                c, pick = sub_cost, sub_pick
            elif rest & (1 << j):
                c, pick = solve(rest & ~(1 << j))
            else:
                continue
            if cost + c < best[0]:
                best = (cost + c, [(f, other, path)] + pick)
        memo[mask] = best
        return best

    try:
        return solve((1 << len(nodes)) - 1)[1]
    except _BRTooBig:
        pass
    # Too big to search exactly: pair the most constrained face first.
    picks, free = [], set(nodes)
    while free:
        def avail(f):
            return [o for o in options[f] if o[1] is None or o[1] not in pos or o[1] in free and o[1] != f]
        f = min(free, key=lambda g: (len(avail(g)) or 99, g))
        free.discard(f)
        opts = avail(f)
        if opts:
            cost, other, path = opts[0]
            free.discard(other)
            picks.append((f, other, path))
    return picks


class _BRTooBig(Exception):
    pass


def plan_parity(topo, targets, strips, max_loop=6, use_border=True):
    """Pair odd target faces. Returns (paths, unpaired): each path is
    (edges, via) as from _br_odd_paths; every edge gets a mid-point vertex."""
    odd = [f for f in targets if len(topo.faces[f]) % 2]
    if not odd:
        return [], []
    target_set = set(targets)
    partners = set(odd)
    partners.update(f for f, vs in enumerate(topo.faces) if len(vs) == 3)
    quads = set(f for f, vs in enumerate(topo.faces) if len(vs) == 4) - target_set
    ngons = set(f for f in targets if len(topo.faces[f]) % 2 == 0)
    options = {}
    for f in odd:
        opts = [(c, o, (e, v)) for c, o, e, v in
                _br_odd_paths(topo, f, partners, quads, ngons, strips, max_loop, use_border)]
        if opts:
            # Only near-best options link faces into a cluster; keeps clusters small.
            opts = [o for o in opts if o[0] <= opts[0][0] + 6.0][:6]
        options[f] = opts
    # Pairing is symmetric: if f can reach g, g can reach f the same way back.
    for f in odd:
        for cost, other, (edges, via) in list(options[f]):
            if other in options and not any(o[1] == f for o in options[other]):
                options[other].append((cost, f, (edges[::-1], via[::-1])))
    # Clusters: odd faces linked by a pairing option.
    parent = dict((f, f) for f in odd)

    def root(f):
        while parent[f] != f:
            parent[f] = parent[parent[f]]
            f = parent[f]
        return f

    for f in odd:
        for _, other, _ in options[f]:
            if other in parent:
                parent[root(f)] = root(other)
    clusters = {}
    for f in odd:
        clusters.setdefault(root(f), []).append(f)
    picks = []
    for nodes in clusters.values():
        picks.extend(_br_best_matching(sorted(nodes), options))
    # Free ends (triangles), edges and quads cut by a loop can only be used once.
    matched, used_faces, used_edges, paths = set(), set(), set(), []
    for f, other, (edges, via) in picks:
        cut = [q for q, c in via if c]
        if f in matched or (other is not None and other in matched):
            continue
        if any(e in used_edges for e in edges) or any(q in used_faces for q in cut):
            continue
        matched.add(f)
        if other is not None:
            matched.add(other)
        used_edges.update(edges)
        used_faces.update(cut)
        paths.append((edges, via))
    return paths, [f for f in odd if f not in matched]


def _br_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _br_quad_cost(topo, quad, normal):
    """How far a quad is from a clean square-ish quad (None if degenerate)."""
    pts = [topo.pts[v] for v in quad]
    qn = topo.normal(quad)
    if qn is None or qn[0] * normal[0] + qn[1] * normal[1] + qn[2] * normal[2] < 0.2:
        return None  # folded over or flipped against the n-gon
    cost = 0.0
    for i in range(4):
        u = _br_sub(pts[i - 1], pts[i])
        w = _br_sub(pts[(i + 1) % 4], pts[i])
        lu = math.sqrt(u[0] * u[0] + u[1] * u[1] + u[2] * u[2])
        lw = math.sqrt(w[0] * w[0] + w[1] * w[1] + w[2] * w[2])
        if lu < 1e-9 or lw < 1e-9:
            return None
        cos_a = clamp((u[0] * w[0] + u[1] * w[1] + u[2] * w[2]) / (lu * lw), -1.0, 1.0)
        ang = math.acos(cos_a)
        # Corner clearly turning the wrong way round the normal: concave quad.
        # A straight (180 degree) corner is allowed but costly: it's the
        # "triangle-shaped quad" that support loops end in.
        cx = (w[1] * u[2] - w[2] * u[1], w[2] * u[0] - w[0] * u[2], w[0] * u[1] - w[1] * u[0])
        if (cx[0] * qn[0] + cx[1] * qn[1] + cx[2] * qn[2]) / (lu * lw) < -0.08:
            return None
        cost += ((ang - math.pi / 2) / (math.pi / 2)) ** 2
        if ang > math.radians(160):
            cost += 3.0
    return cost


def plan_quads(topo, face, strip_verts, valence, val_weight=0.6):
    """Best set of diagonals that cuts even-sided `face` into quads, or None.

    `valence` is updated in place so faces planned later see the new edges.
    """
    verts = topo.faces[face]
    n = len(verts)
    normal = topo.normal(verts)
    if normal is None or n % 2 or n > BR_MAX_SIDES:
        return None
    quad_costs = {}
    best, best_cost = None, None
    for split in _br_splits(n):
        cost = 0.0
        for q in split:
            if q not in quad_costs:
                quad_costs[q] = _br_quad_cost(topo, [verts[i] for i in q], normal)
            qc = quad_costs[q]
            if qc is None:
                cost = None
                break
            cost += qc
        if cost is None or (best_cost is not None and cost >= best_cost + 10):
            continue
        diags = set()
        for q in split:
            for j in range(4):
                a, b = q[j], q[(j + 1) % 4]
                if (b - a) % n not in (1, n - 1):
                    diags.add(_br_ekey(a, b))
        added = {}
        for a, b in diags:
            added[a] = added.get(a, 0) + 1
            added[b] = added.get(b, 0) + 1
        for i, k in added.items():
            v = verts[i]
            want = 3 if v in topo.border else 4
            was = valence[v]
            delta = abs(was + k - want) - abs(was - want)
            if delta > 0 and v in strip_verts:
                delta *= 4.0  # never park a pole on a bevel strip
            cost += val_weight * delta
        if best_cost is None or cost < best_cost:
            best, best_cost = sorted(diags), cost
    if best is None:
        return None
    pairs = [(verts[a], verts[b]) for a, b in best]
    for a, b in pairs:
        valence[a] += 1
        valence[b] += 1
    return pairs


def plan_grid(topo, face, valence, corner_angle=155.0):
    """Rectangle-like n-gon whose opposite sides carry the same number of extra
    vertices (e.g. a boss top where four support loops end): carry each loop
    straight across, like an edge loop would. Returns (rows, cols) vertex
    pairs, or None. Rows are plain cuts; cols cross them when both exist."""
    verts = topo.faces[face]
    n = len(verts)
    normal = topo.normal(verts)
    if normal is None:
        return None
    corners = []
    for i in range(n):
        p, c, q = topo.pts[verts[i - 1]], topo.pts[verts[i]], topo.pts[verts[(i + 1) % n]]
        u, w = _br_sub(p, c), _br_sub(q, c)
        lu = math.sqrt(u[0] * u[0] + u[1] * u[1] + u[2] * u[2])
        lw = math.sqrt(w[0] * w[0] + w[1] * w[1] + w[2] * w[2])
        if lu < 1e-9 or lw < 1e-9:
            return None
        cx = (w[1] * u[2] - w[2] * u[1], w[2] * u[0] - w[0] * u[2], w[0] * u[1] - w[1] * u[0])
        sin_a = (cx[0] * normal[0] + cx[1] * normal[1] + cx[2] * normal[2]) / (lu * lw)
        cos_a = (u[0] * w[0] + u[1] * w[1] + u[2] * w[2]) / (lu * lw)
        ang = math.degrees(math.atan2(sin_a, cos_a)) % 360.0
        if ang < corner_angle or ang > 360.0 - corner_angle:
            corners.append(i)
    if len(corners) != 4:
        return None
    sides = []
    for k in range(4):
        a, b = corners[k], corners[(k + 1) % 4]
        sides.append([verts[(a + j) % n] for j in range(1, (b - a) % n)])
    if len(sides[0]) != len(sides[2]) or len(sides[1]) != len(sides[3]):
        return None
    rows = list(zip(sides[0], reversed(sides[2])))
    cols = list(zip(sides[1], reversed(sides[3])))
    if not rows and not cols:
        return None
    if not rows:
        rows, cols = cols, []
    for a, b in rows + cols:
        valence[a] += 1
        valence[b] += 1
    return rows, cols


def _br_cross_factor(topo, a, b, c, d):
    """Where segment a-b crosses segment c-d, as a 0..1 factor along c-d."""
    p, q, r, s = topo.pts[a], topo.pts[b], topo.pts[c], topo.pts[d]
    u, v, w = _br_sub(q, p), _br_sub(s, r), _br_sub(p, r)
    uu = u[0] * u[0] + u[1] * u[1] + u[2] * u[2]
    uv = u[0] * v[0] + u[1] * v[1] + u[2] * v[2]
    vv = v[0] * v[0] + v[1] * v[1] + v[2] * v[2]
    uw = u[0] * w[0] + u[1] * w[1] + u[2] * w[2]
    vw = v[0] * w[0] + v[1] * w[1] + v[2] * w[2]
    den = uu * vv - uv * uv
    t = (uu * vw - uv * uw) / den if abs(den) > 1e-12 else 0.5
    return clamp(t, 0.05, 0.95)


def _br_batches(groups, comp_faces):
    """Pack cuts into as few polyConnectComponents calls as possible.

    That command joins any two selected components (vertices or edges) that
    share a face. So within one call no face may hold two selected
    components unless they are exactly the cut planned for that face, and a
    face gets at most one planned cut (a fan's two diagonals go in different
    calls). groups: [(components, {face: planned components}, ...)]. Checked
    on the mesh before cutting, which is safe: cutting only shrinks faces.
    Returns (batches, solo): solo groups clash with themselves (two vertices
    sharing two faces) and need a polySplit of their own.
    """
    batches, solo = [], []
    for group in groups:
        comps, planned = group[0], group[1]
        touched = {}
        for c in comps:
            for g in comp_faces[c]:
                touched.setdefault(g, set()).add(c)

        def fits(batch):
            if any(f in batch[1] for f in planned):
                return False
            for g, mine in touched.items():
                sel = batch[2].get(g, set()) | mine
                if len(sel) > 1 and sel != planned.get(g, batch[1].get(g)):
                    return False
            return True

        batch = next((b for b in batches if fits(b)), None)
        if batch is None:
            batch = ([], {}, {})
            if not fits(batch):
                solo.append(group)
                continue
            batches.append(batch)
        batch[0].append(group)
        batch[1].update(planned)
        for g, mine in touched.items():
            batch[2].setdefault(g, set()).update(mine)
    return [b[0] for b in batches], solo


def _br_row_point(fn, dag, c, d, t, first_new):
    """Insert point at factor t along row c-d. An earlier column may already
    have split the row (new vertices >= first_new), so walk its pieces."""
    pc, pd = fn.getPoint(c), fn.getPoint(d)
    span = pd - pc
    length2 = span * span
    if length2 < 1e-18:
        return None
    prev, cur, cur_t = None, c, 0.0
    for _ in range(64):
        it = om.MItMeshVertex(dag)
        it.setIndex(cur)
        step = None
        for e in it.getConnectedEdges():
            o = it.getOppositeVertex(e)
            if o == prev:
                continue
            if o == d or o >= first_new:
                off = fn.getPoint(o) - pc
                ot = 1.0 if o == d else (off * span) / length2
                on_row = o == d or (off ^ span).length() < 1e-4 * length2 ** 0.5 + 1e-6
                if ot > cur_t and on_row:
                    step = (e, o, ot)
                    break
        if step is None:
            return None
        e, o, ot = step
        if t <= ot or o == d:
            local = clamp((t - cur_t) / (ot - cur_t), 0.05, 0.95) if ot > cur_t else 0.5
            return (e, local if fn.getEdgeVertices(e)[0] == cur else 1.0 - local)
        prev, cur, cur_t = cur, o, ot
    return None


def _br_edge_index(dag, a, b):
    it = om.MItMeshVertex(dag)
    it.setIndex(a)
    for e in it.getConnectedEdges():
        if b == it.getOppositeVertex(e):
            return e
    return None


def _br_vertex_point(fn, dag, face, v):
    """polySplit insert point that lands exactly on vertex v of `face`."""
    it = om.MItMeshPolygon(dag)
    it.setIndex(face)
    for e in it.getEdges():
        ends = fn.getEdgeVertices(e)
        if v in ends:
            return (e, 0.0 if ends[0] == v else 1.0)
    return None


def _br_history(shape):
    if cmds.listConnections(shape + ".inMesh", source=True, destination=False):
        return True
    return bool(cmds.constructionHistory(q=True, toggle=True))


def _br_shape(xform):
    shapes = cmds.listRelatives(xform, shapes=True, type="mesh", noIntermediate=True, fullPath=True) or []
    return shapes[0] if shapes else None


def resolve_mesh(xform, faces=None, scope="Bevel n-gons", strip_ratio=0.3, max_loop=6, use_border=True,
                 dry_run=False):
    """Resolve bevel n-gons on one mesh. `faces`: restrict to these (component
    selection: every n-gon among them is resolved, whatever the scope).

    Returns a dict: found, resolved, cuts, poles, strip_poles, unresolved
    ({final face id: reason}), dry_run plans when dry_run.
    """
    shape = _br_shape(xform)
    res = {"found": 0, "resolved": 0, "cuts": 0, "loops": 0, "poles": 0, "strip_poles": 0, "unresolved": {}}
    if not shape:
        return res
    dag = get_dag_path(shape)
    topo = BevelTopology(dag)
    targets = bevel_ngons(topo, faces, "All n-gons" if faces is not None else scope, strip_ratio)
    res["found"] = len(targets)
    if not targets:
        return res
    bad = {}
    for f in targets:
        if f in topo.holed:
            bad[f] = "holed"
        elif len(topo.faces[f]) > BR_MAX_SIDES:
            bad[f] = "too_many"
        elif topo.degenerate(f):
            bad[f] = "degenerate"
    targets = [f for f in targets if f not in bad]
    strips = topo.strip_faces(strip_ratio)
    paths, unpaired = plan_parity(topo, targets, strips, max_loop, use_border)
    for f in unpaired:
        bad[f] = "unpaired"
    if dry_run:
        res["unresolved"] = bad
        res["targets"] = targets
        res["paths"] = paths
        return res
    watch = set()
    for f in list(targets) + list(bad):
        watch.update(topo.faces[f])
    first_count = len(topo.pts)
    first_faces = len(topo.faces)
    mine = set(targets) | set(bad)
    before = dict((v, topo.valence[v]) for v in watch)
    history = _br_history(shape)
    name = cmds.ls(shape, long=True)[0]

    # --- pass 1: parity. Look every edge up before cutting: indices of edges a
    # cut doesn't touch stay put, and no two paths share an edge.
    # With construction history every new poly node re-evaluates the chain
    # (the bevel node itself), so the cost is in the number of commands, not
    # cuts: lone mid-points (faces touching, or passing an n-gon) go in one
    # polySubdivideEdge, and runs through quads (edge loops) are packed into
    # a few polyConnectComponents calls on their edges.
    mids, runs = [], []
    for edges, via in paths:
        run = [edges[0]]
        for i, (q, cut) in enumerate(via):
            if not cut:
                (runs if len(run) > 1 else mids).append(run)
                run = []
            run.append(edges[i + 1])
        (runs if len(run) > 1 else mids).append(run)
        res["loops"] += 1
    index = {}
    for key in set(k for r in mids + runs for k in r):
        index[key] = _br_edge_index(dag, *key)
    groups = []
    for run in runs:
        if None in [index[k] for k in run]:
            continue
        planned = {}
        for k1, k2 in zip(run, run[1:]):
            q = set(topo.edge_faces[k1]) & set(topo.edge_faces[k2])
            planned[q.pop()] = set((k1, k2))
        groups.append((set(run), planned, run))
    batches, solo = _br_batches(groups, topo.edge_faces)
    for batch in batches:
        _br_connect(name, ["%s.e[%d]" % (name, index[k]) for g in batch for k in g[2]], history)
    for g in solo:
        _br_split(name, [(index[k], 0.5) for k in g[2]], history)
    lone = [index[r[0]] for r in mids if index[r[0]] is not None]
    if lone:
        cmds.polySubdivideEdge(["%s.e[%d]" % (name, e) for e in lone], dv=1, ch=history)

    # --- pass 2: split every even n-gon into quads. Faces whose support loops
    # can run straight across get a grid; the rest get the best diagonals.
    dag = get_dag_path(name)
    topo = BevelTopology(dag)
    strip_verts = set()
    for f in topo.strip_faces(strip_ratio):
        strip_verts.update(topo.faces[f])
    valence = list(topo.valence)
    cuts, crossings = [], []
    fn = om.MFnMesh(dag)
    for f in targets:
        if f in bad or len(topo.faces[f]) <= 4:
            continue
        if topo.normal(topo.faces[f]) is None:
            bad[f] = "degenerate"
            continue
        grid = plan_grid(topo, f, valence)
        if grid:
            pairs, cols = grid
            if cols:
                crossings.append((f, pairs, cols))
        else:
            pairs = plan_quads(topo, f, strip_verts, valence)
        if pairs is None:
            bad[f] = "no_split"
            continue
        cuts.extend((f, a, b) for a, b in pairs)
    # Grid columns cross the rows: their vertex ends sit on the face's original
    # sides (never cut), so look those up before cutting.
    col_ends = []
    for f, rows, cols in crossings:
        for a, b in cols:
            col_ends.append((a, b, rows, _br_vertex_point(fn, dag, f, a), _br_vertex_point(fn, dag, f, b)))
    # A few polyConnectComponents calls instead of one polySplit per cut (a
    # 200-window wall went from 30 s to a couple of seconds).
    vert_faces = {}
    used = set(v for _, a, b in cuts for v in (a, b))
    for f, vs in enumerate(topo.faces):
        for v in vs:
            if v in used:
                vert_faces.setdefault(v, []).append(f)
    batches, solo = _br_batches([(set((a, b)), {f: set((a, b))}, (f, a, b)) for f, a, b in cuts], vert_faces)
    # Look polySplit points up before cutting (an MFnMesh mustn't outlive a cut).
    solo = [(_br_vertex_point(fn, dag, f, a), _br_vertex_point(fn, dag, f, b)) for _, _, (f, a, b) in solo]
    for batch in batches:
        if _br_connect(name, ["%s.vtx[%d]" % (name, v) for g in batch for v in sorted(g[0])], history):
            res["cuts"] += len(batch)
    for pa, pb in solo:
        if pa and pb and _br_split(name, [pa, pb], history):
            res["cuts"] += 1
    if col_ends:
        first_new = None
        for a, b, rows, pa, pb in col_ends:
            if not (pa and pb):
                continue
            dag = get_dag_path(name)
            fn = om.MFnMesh(dag)
            if first_new is None:
                first_new = fn.numVertices
            points = [pa]
            # Cross the rows in the order the column meets them, from a to b.
            for c, d in sorted(rows, key=lambda r: _br_cross_factor(topo, r[0], r[1], a, b)):
                hit = _br_row_point(fn, dag, c, d, _br_cross_factor(topo, a, b, c, d), first_new)
                if hit is None:
                    points = None
                    break
                points.append(hit)
            if points and _br_split(name, points + [pb], history):
                res["cuts"] += 1

    # --- report on the final mesh.
    topo = BevelTopology(get_dag_path(name))
    for v in watch | set(range(first_count, len(topo.pts))):
        if v in topo.border:
            continue
        val = topo.valence[v]
        if val != 4 and (v >= first_count or val != before[v]):
            res["poles"] += 1
            if v in strip_verts:
                res["strip_poles"] += 1
    # Split faces keep their index (the new parts are appended), so these are
    # the target n-gons that are still n-gons.
    for f, vs in enumerate(topo.faces):
        if len(vs) > 4 and (f in mine or f >= first_faces):
            res["unresolved"][f] = bad.get(f, "no_split")
    res["resolved"] = max(0, res["found"] - len(res["unresolved"]))
    return res


def _br_connect(name, comps, history):
    try:
        cmds.polyConnectComponents(comps, ch=history)
        return True
    except RuntimeError:
        traceback.print_exc()
        return False


def _br_split(name, points, history):
    try:
        cmds.polySplit(name, ip=points, ch=history)
        return True
    except RuntimeError:
        traceback.print_exc()
        return False


def resolve_bevel_ngons(items, scope="Bevel n-gons", strip_ratio=0.3, max_loop=6, use_border=True,
                        dry_run=False, select_unresolved=True):
    """Resolve (or with dry_run just find) bevel n-gons on {mesh transform:
    None (whole mesh) or set of faces}. One undo step for everything."""
    report = {}
    with UndoChunk("Bevel Resolver"):
        for xform, faces in items.items():
            try:
                report[xform] = resolve_mesh(xform, faces, scope, strip_ratio, max_loop, use_border, dry_run)
            except RuntimeError as exc:
                report[xform] = {"error": str(exc), "found": 0, "resolved": 0, "unresolved": {}}
        if select_unresolved and not dry_run:
            # Inside the chunk, so the selection change undoes with the cuts.
            comps = []
            for xform, r in report.items():
                comps.extend("%s.%s" % (xform, s) for s in face_ranges(r.get("unresolved", {})))
            keep = [x for x in items if cmds.objExists(x)]
            if comps:
                cmds.select(comps, replace=True)
            elif keep:
                cmds.select(keep, replace=True)
    return report


# =============================================================================
# Bevel Resolver - panel
# =============================================================================

def bevel_selection():
    """{mesh transform: None (whole mesh) or set of faces} from the selection.
    Selected vertices / edges count as the faces around them."""
    items = {}
    sel = cmds.ls(selection=True, long=True, flatten=False) or []
    for node in [s for s in sel if "." not in s]:
        if cmds.objectType(node, isAType="shape"):
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        if cmds.listRelatives(node, shapes=True, type="mesh", noIntermediate=True):
            items[node] = None
        else:
            for shape in cmds.listRelatives(node, allDescendents=True, type="mesh", fullPath=True) or []:
                if not cmds.getAttr(shape + ".intermediateObject"):
                    items[cmds.listRelatives(shape, parent=True, fullPath=True)[0]] = None
    comps = [s for s in sel if "." in s]
    if comps:
        for face in cmds.ls(cmds.polyListComponentConversion(comps, toFace=True) or [], long=True) or []:
            node, _, spec = face.partition(".")
            if cmds.objectType(node, isAType="shape"):
                node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
            m = re.match(r"f\[(\d+)(?::(\d+))?\]$", spec)
            if not m or items.get(node, set()) is None:
                continue
            lo = int(m.group(1))
            items.setdefault(node, set()).update(range(lo, int(m.group(2) or lo) + 1))
    return items


class BevelResolverPanel(QtWidgets.QWidget):
    TOOL_NAME = "Bevel Resolver"
    TOOL_TIP = "Turn the n-gons a chamfer-off bevel leaves at its ends into clean SubD quads."

    def __init__(self, parent=None):
        super(BevelResolverPanel, self).__init__(parent)
        self.last = None  # {"kind": "find"/"resolve", "selection": key, "found", "resolved", "left"}
        self._jobs = []
        self._sel_timer = QtCore.QTimer(self)
        self._sel_timer.setSingleShot(True)
        self._sel_timer.setInterval(80)
        self._sel_timer.timeout.connect(self._update_guidance)
        self._build()
        self._install_jobs()
        self._update_guidance()

    # ============================================================== layout
    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(6)

        top = QtWidgets.QWidget()
        tl = QtWidgets.QVBoxLayout(top)
        tl.setContentsMargins(6, 0, 6, 0)
        tl.setSpacing(6)
        tl.addWidget(ToolHeader("Bevel Resolver", "Turn the 5- and 6-sided faces a Chamfer-off bevel leaves "
                                                  "where it ends into clean SubD quads."))
        self.next_banner = NextBanner()
        tl.addWidget(self.next_banner)
        outer.addWidget(top)

        scroll, col = scroll_column()
        outer.addWidget(scroll, 1)

        # ---- 1. select
        card = self.step_select = StepCard(1, "Select", "Meshes (the whole mesh is checked), or faces / edges / "
                                                        "vertices around the bevel ends you want fixed.")
        self.sel_label = hint_label("")
        card.add(self.sel_label)
        grid = Section("", header=False)
        self.scope = SegmentField(BR_SCOPES)
        grid.add_row("Faces", self.scope, "Bevel n-gons: only n-gons touching a thin bevel strip (and their "
                                          "neighbours).\nAll n-gons: every face with more than 4 sides.\n"
                                          "With faces / edges / vertices selected, every n-gon among them.")
        card.add(grid)
        col.addWidget(card)

        # ---- 2. resolve
        card = self.step_resolve = StepCard(2, "Resolve", "Side-by-side chamfers merge, a lone chamfer gets a "
                                                          "diagonal to the next loop, and poles land on the flat "
                                                          "area. One Ctrl+Z undoes it.")
        find = secondary_button("Select N-gons", "Select the n-gons Resolve would work on, changing nothing.")
        find.clicked.connect(lambda *_: self.find())
        self.resolve_btn = primary_button("Resolve")
        self.resolve_btn.setMinimumHeight(28)
        self.resolve_btn.setToolTip("Cut the n-gons into quads. One Ctrl+Z undoes it. "
                                    "Faces that can't be resolved cleanly are left alone and selected.")
        self.resolve_btn.clicked.connect(lambda *_: self.resolve())
        row = button_row(find, self.resolve_btn)
        row.layout().setStretch(1, 1)
        card.add(row)
        adv = Section("Advanced", expanded=False)
        self.strip_ratio = FloatField(0.05, 0.6, decimals=2, step=0.05)
        self.strip_ratio.setValue(BR_DEFAULTS["strip_ratio"])
        adv.add_row("Strip ratio", self.strip_ratio, "A quad whose short sides are this much thinner than its "
                                                     "long sides counts as a bevel strip.")
        self.max_loop = IntField(0, 30, 0, 12)
        self.max_loop.setValue(BR_DEFAULTS["max_loop"])
        adv.add_row("Max loop", self.max_loop, "A 5- or 7-sided face can't become quads alone. If no other odd "
                                               "face touches it, a short edge loop runs through up to this many "
                                               "flat quads to reach one.")
        self.use_border = CheckField("Loops may end on an open border")
        self.use_border.setValue(BR_DEFAULTS["use_border"])
        adv.add_full(self.use_border)
        card.add(adv)
        col.addWidget(card)

        # ---- 3. check
        card = self.step_check = StepCard(3, "Check the result", "Anything it couldn't resolve cleanly is listed "
                                                                 "and left alone. Click a row to select it.")
        self.report_tree = QtWidgets.QTreeWidget()
        self.report_tree.setColumnCount(2)
        self.report_tree.setHeaderLabels(["Result", "Faces"])
        self.report_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.report_tree.setMinimumHeight(140)
        self.report_tree.setAlternatingRowColors(True)
        self.report_tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.report_tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.report_tree.header().setStretchLastSection(False)
        self.report_tree.itemSelectionChanged.connect(self._report_selected)
        card.add(self.report_tree)
        col.addWidget(card)
        col.addStretch(1)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setContentsMargins(8, 0, 8, 6)
        outer.addWidget(self.status)

    # ============================================================ guidance
    def _selection_key(self):
        return tuple(cmds.ls(selection=True, long=True) or [])

    def _update_guidance(self):
        try:
            sel = self._selection_key()
        except Exception:
            sel = ()
        meshes = set()
        comps = 0
        for s in sel:
            if "." in s:
                comps += 1
                meshes.add(s.split(".")[0])
            else:
                meshes.add(s)
        self.sel_label.setText("%d object(s) selected%s." % (len(meshes), (", %d component group(s)" % comps)
                                                             if comps else "") if sel else "Nothing selected.")
        last = self.last if self.last and self.last["selection"] == sel else None
        self.step_select.set_state("done" if sel else "current")
        resolved = last is not None and last["kind"] == "resolve"
        self.step_resolve.set_state("done" if resolved else ("current" if sel else "todo"))
        self.step_check.set_state(("current" if last["left"] else "done") if resolved else "todo")
        if not sel:
            self.next_banner.set_text("Select the bevelled mesh(es), or faces / edges / vertices around the "
                                      "bevel ends.")
        elif last is None:
            self.next_banner.set_text("Press <b>Resolve</b> (or <b>Select N-gons</b> to see what it will "
                                      "change first).")
        elif last["kind"] == "find":
            self.next_banner.set_text("%d n-gon(s) selected. Press <b>Resolve</b>." % last["found"]
                                      if last["found"] else "No %s here. Try <b>All n-gons</b>, or select "
                                      "other meshes." % self.scope.value().lower())
        elif last["left"]:
            self.next_banner.set_text("%d face(s) couldn't be resolved cleanly and are selected. See step 3; "
                                      "fix them by hand or with a different selection." % last["left"],
                                      tag="CHECK", tone="warn")
        elif last["found"]:
            self.next_banner.set_text("All %d n-gon(s) resolved. Check the smooth preview (press 3)."
                                      % last["resolved"], tag="DONE", tone="done")
        else:
            self.next_banner.set_text("No %s found. Try <b>All n-gons</b>, or select other meshes."
                                      % self.scope.value().lower())

    def set_status(self, text, level="info"):
        color = LEVEL_COLORS.get(level, "#a8a8a8") if level != "error" else "#e06060"
        self.status.setText('<span style="color:%s">%s</span>' % (color, text))

    def options(self):
        return {"scope": self.scope.value(), "strip_ratio": self.strip_ratio.value(),
                "max_loop": self.max_loop.value(), "use_border": self.use_border.value()}

    def _items(self):
        items = bevel_selection()
        if not items:
            self.set_status("Select one or more meshes, or faces / edges / vertices on them.", level="warn")
            self._update_guidance()
        return items

    # ============================================================= actions
    @ui_safe
    def find(self):
        items = self._items()
        if not items:
            return
        report = resolve_bevel_ngons(items, dry_run=True, **self.options())
        comps = []
        for xform, r in report.items():
            comps.extend("%s.%s" % (xform, s) for s in face_ranges(r.get("targets", [])))
        if comps:
            cmds.select(comps, replace=True)
        found = sum(r["found"] for r in report.values())
        stuck = sum(len(r["unresolved"]) for r in report.values())
        self._fill_report(report, dry_run=True)
        self.last = {"kind": "find", "selection": self._selection_key(), "found": found, "resolved": 0,
                     "left": stuck}
        if not found:
            self.set_status("No %s found on %d mesh(es)." % (self.scope.value().lower(), len(report)))
        else:
            self.set_status("%d n-gon(s) on %d mesh(es)%s." % (
                found, len(report), (", %d can't be paired (see step 3)" % stuck) if stuck else ""),
                level="warn" if stuck else "info")
        self._update_guidance()

    @ui_safe
    def resolve(self):
        items = self._items()
        if not items:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            t0 = time.time()
            report = resolve_bevel_ngons(items, **self.options())
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._fill_report(report)
        found = sum(r["found"] for r in report.values())
        done = sum(r["resolved"] for r in report.values())
        left = sum(len(r["unresolved"]) for r in report.values())
        self.last = {"kind": "resolve", "selection": self._selection_key(), "found": found, "resolved": done,
                     "left": left}
        errors = [x for x, r in report.items() if r.get("error")]
        if errors:
            self.set_status("Failed on %s: %s" % (short_name(errors[0]), report[errors[0]]["error"]), level="error")
        elif not found:
            self.set_status("No %s found." % self.scope.value().lower())
        else:
            self.set_status("Resolved %d of %d n-gon(s) in %.2fs%s. One Ctrl+Z undoes it." % (
                done, found, time.time() - t0, (", %d left and selected" % left) if left else ""),
                level="warn" if left else "fixed")
        self._update_guidance()

    # ============================================================== report
    def _fill_report(self, report, dry_run=False):
        self.report_tree.clear()
        for xform, r in sorted(report.items()):
            if r.get("error"):
                top = QtWidgets.QTreeWidgetItem([short_name(xform), "error"])
                top.setToolTip(0, r["error"])
                top.setForeground(1, QtGui.QBrush(QtGui.QColor("#e06060")))
                self.report_tree.addTopLevelItem(top)
                continue
            if dry_run:
                label = "%s: %d n-gon(s)" % (short_name(xform), r["found"])
                faces = r.get("targets", [])
            else:
                label = "%s: %d of %d resolved" % (short_name(xform), r["resolved"], r["found"])
                faces = list(r["unresolved"])
            top = QtWidgets.QTreeWidgetItem([label, str(len(faces)) if faces else ""])
            top.setData(0, QtCore.Qt.UserRole, [xform, faces])
            top.setToolTip(0, xform)
            if not dry_run:
                top.setForeground(0, QtGui.QBrush(QtGui.QColor(LEVEL_COLORS["warn" if faces else "fixed"])))
                tip = ("%d cut(s), %d odd-face pairing(s), %d new pole(s) (%d touching a bevel strip, "
                       "usually where the bevel ends)" % (r.get("cuts", 0), r.get("loops", 0), r.get("poles", 0),
                                                          r.get("strip_poles", 0)))
                top.setToolTip(1, tip)
                top.setToolTip(0, "%s\n%s" % (xform, tip))
            by_reason = {}
            for f, reason in r["unresolved"].items():
                by_reason.setdefault(reason, []).append(f)
            for reason, fs in sorted(by_reason.items()):
                child = QtWidgets.QTreeWidgetItem([BR_REASONS.get(reason, reason), str(len(fs))])
                child.setData(0, QtCore.Qt.UserRole, [xform, fs])
                child.setForeground(0, QtGui.QBrush(QtGui.QColor(LEVEL_COLORS["skip"])))
                top.addChild(child)
            top.setExpanded(True)
            self.report_tree.addTopLevelItem(top)

    def _report_selected(self):
        try:
            comps = []
            for it in self.report_tree.selectedItems():
                xform, faces = it.data(0, QtCore.Qt.UserRole) or (None, [])
                if not xform or not cmds.objExists(xform):
                    continue
                if faces:
                    comps.extend("%s.%s" % (xform, s) for s in face_ranges(faces))
                else:
                    comps.append(xform)
            if comps:
                cmds.select(comps, replace=True)
                # Picking from the report isn't a new selection to work on.
                if self.last:
                    self.last["selection"] = self._selection_key()
        except Exception:
            traceback.print_exc()

    # ======================================================= scene events
    def _install_jobs(self):
        if maya_main_window() is None:
            return
        self._jobs = [cmds.scriptJob(event=["SelectionChanged", lambda: self._sel_timer.start()])]
        _registry()["jobs"].extend(self._jobs)

    def shutdown(self):
        self._sel_timer.stop()
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
# Log Noise - natural-looking logs from cylinders (no plugin)
# =============================================================================
#
# Ported from a logNoise deformer node, minus the node: a custom plugin needs
# a file written into the plug-ins folder (not allowed in secure Mayas) and
# every machine that opens the scene needs it too. Here the mesh shape keeps
# its rest points in a hidden attribute and the noise is written as vertex
# tweaks (shape.pnts), so scenes need nothing extra, settings can be changed
# any time, and Reset / Bake are one click. The noise maths is unchanged, so
# a seed gives the same shape as the deformer did.

LOG_REST = "unlokLogRest"        # doubleArray: rest points, object space, x y z ...
LOG_WEIGHTS = "unlokLogWeights"  # doubleArray: per-vertex weight (empty = 1 everywhere)
LOG_SETTINGS = "unlokLogNoise"   # string: JSON settings
LOG_AXES = ("Auto", "X", "Y", "Z")
LOG_DEFAULTS = {"seed": 0, "bump": 0.04, "frequency": 2.0, "grain": 4.0, "octaves": 3, "bulge": 0.06,
                "bend": 0.02, "taper": 0.1, "axis": "Auto"}
LOG_MIN_VERTS = 200
_LN_BUMP_GAIN = 2.0   # gains map each control to roughly "fraction of radius / length"
_LN_BULGE_GAIN = 2.0
_LN_BEND_GAIN = 3.0
_LN_BULGE_FREQ = 0.35  # bulges per radius of length
_LN_BEND_FREQ = 1.0    # bends across the whole length


def _ln_lcg(state):
    return (state * 1664525 + 1013904223) & 0xFFFFFFFF


def _ln_make_perm():
    perm = list(range(256))
    s = 12345
    for i in range(255, 0, -1):
        s = _ln_lcg(s)
        j = s % (i + 1)
        perm[i], perm[j] = perm[j], perm[i]
    return perm + perm


_LN_P = _ln_make_perm()


def _ln_offsets(seed, salt, count):
    s = (seed * 2654435761 + salt * 40503 + 7) & 0xFFFFFFFF
    for _ in range(4):
        s = _ln_lcg(s)
    out = []
    for _ in range(count):
        s = _ln_lcg(s)
        out.append(s / 4294967296.0 * 256.0)
    return out


def _ln_fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _ln_grad(h, x, y, z):
    h &= 15
    u = x if h < 8 else y
    v = y if h < 4 else (x if h == 12 or h == 14 else z)
    return (u if h & 1 == 0 else -u) + (v if h & 2 == 0 else -v)


def ln_noise3(x, y, z):
    """Improved Perlin noise (fixed permutation, same on every Python), about -1..1."""
    fx, fy, fz = math.floor(x), math.floor(y), math.floor(z)
    X, Y, Z = int(fx) & 255, int(fy) & 255, int(fz) & 255
    x -= fx
    y -= fy
    z -= fz
    u, v, w = _ln_fade(x), _ln_fade(y), _ln_fade(z)
    P = _LN_P
    A = P[X] + Y
    AA = P[A] + Z
    AB = P[A + 1] + Z
    B = P[X + 1] + Y
    BA = P[B] + Z
    BB = P[B + 1] + Z
    g = _ln_grad
    x0 = g(P[AA], x, y, z) + u * (g(P[BA], x - 1, y, z) - g(P[AA], x, y, z))
    x1 = g(P[AB], x, y - 1, z) + u * (g(P[BB], x - 1, y - 1, z) - g(P[AB], x, y - 1, z))
    x2 = g(P[AA + 1], x, y, z - 1) + u * (g(P[BA + 1], x - 1, y, z - 1) - g(P[AA + 1], x, y, z - 1))
    x3 = g(P[AB + 1], x, y - 1, z - 1) + u * (g(P[BB + 1], x - 1, y - 1, z - 1) - g(P[AB + 1], x, y - 1, z - 1))
    y0 = x0 + v * (x1 - x0)
    y1 = x2 + v * (x3 - x2)
    return y0 + w * (y1 - y0)


def ln_fbm(x, y, z, octaves):
    total, amp, norm = 0.0, 1.0, 0.0
    for _ in range(octaves):
        total += amp * ln_noise3(x, y, z)
        norm += amp
        x *= 2.0
        y *= 2.0
        z *= 2.0
        amp *= 0.5
    return total / norm


def log_noise_points(rest, settings, weights=None):
    """The log shape for rest points [(x, y, z)] (pure maths, nothing in the
    scene changes). weights: per-vertex 0..1, or None for everywhere.

    Bumps and bulge are relative to the log's radius and bend to its length,
    so it works at any scale. Bend is measured from the straight line
    between the ends, so the ends stay put. Bend, bulge and taper are
    worked out once per height ring."""
    s = dict(LOG_DEFAULTS)
    s.update(settings or {})
    count = len(rest)
    if count == 0:
        return []
    bump = float(s["bump"]) * _LN_BUMP_GAIN
    freq = float(s["frequency"])
    stretch = max(1e-6, float(s["grain"]))
    octaves = max(1, int(s["octaves"]))
    bulge = float(s["bulge"]) * _LN_BULGE_GAIN
    bend = float(s["bend"]) * _LN_BEND_GAIN
    taper = float(s["taper"])
    lo = [min(c[k] for c in rest) for k in range(3)]
    hi = [max(c[k] for c in rest) for k in range(3)]
    ext = [hi[k] - lo[k] for k in range(3)]
    # the log runs along the longest bounding-box side unless told otherwise
    axis = s.get("axis", "Auto")
    a = ext.index(max(ext)) if axis not in ("X", "Y", "Z") else "XYZ".index(axis)
    b, c = (a + 1) % 3, (a + 2) % 3
    length = ext[a]
    radius = 0.25 * (ext[b] + ext[c])
    out = [tuple(pt) for pt in rest]
    if length < 1e-6 or radius < 1e-6:
        return out
    inv_r = 1.0 / radius
    base = lo[a]
    center_b = 0.5 * (lo[b] + hi[b])
    center_c = 0.5 * (lo[c] + hi[c])
    o = _ln_offsets(int(s["seed"]), 0, 9)
    bend_scale = bend * length
    end0_b, end1_b = ln_noise3(o[0], o[1], 0.37), ln_noise3(_LN_BEND_FREQ + o[0], o[1], 0.37)
    end0_c, end1_c = ln_noise3(o[2], o[3], 0.37), ln_noise3(_LN_BEND_FREQ + o[2], o[3], 0.37)
    rows = {}
    for i, pt in enumerate(rest):
        w = 1.0 if weights is None else weights[i]
        if w == 0.0:
            continue
        h = pt[a] - base
        key = round(h / length, 6)
        row = rows.get(key)
        if row is None:
            t = h / length
            off_b = ln_noise3(t * _LN_BEND_FREQ + o[0], o[1], 0.37) - (end0_b + (end1_b - end0_b) * t)
            off_c = ln_noise3(t * _LN_BEND_FREQ + o[2], o[3], 0.37) - (end0_c + (end1_c - end0_c) * t)
            scale = (1.0 - taper * t) * (1.0 + bulge * ln_fbm(h * inv_r * _LN_BULGE_FREQ + o[4], o[5], 0.71, 2))
            row = rows[key] = (off_b * bend_scale, off_c * bend_scale, scale)
        off_b, off_c, scale = row
        db = pt[b] - center_b
        dc = pt[c] - center_c
        n = ln_fbm(db * inv_r * freq + o[6], dc * inv_r * freq + o[7], h * inv_r * freq / stretch + o[8], octaves)
        k = scale * (1.0 + bump * n)
        q = list(pt)
        q[b] += w * (center_b + db * k + off_b - pt[b])
        q[c] += w * (center_c + dc * k + off_c - pt[c])
        out[i] = (q[0], q[1], q[2])
    return out


def _log_shape(xform):
    shapes = cmds.listRelatives(xform, shapes=True, type="mesh", noIntermediate=True, fullPath=True) or []
    return shapes[0] if shapes else None


def log_selection():
    """(logs, weights): mesh transforms in the selection, plus per-vertex
    weights {xform: [w...]} for logs picked by components (soft selection
    falloff included)."""
    logs = []
    for node in cmds.ls(selection=True, objectsOnly=True, long=True) or []:
        if cmds.objectType(node, isAType="shape"):
            node = long_name(cmds.listRelatives(node, parent=True, fullPath=True)[0])
        if node not in logs and _log_shape(node):
            logs.append(node)
    weights = {}
    if any("." in s for s in cmds.ls(selection=True) or []):
        try:
            rich = om.MGlobal.getRichSelection().getSelection()
        except RuntimeError:
            rich = om.MSelectionList()
        for i in range(rich.length()):
            try:
                dag, comp = rich.getComponent(i)
            except Exception:
                continue
            if comp.isNull():
                continue
            path = dag.fullPathName()
            xform = long_name(cmds.listRelatives(path, parent=True, fullPath=True)[0]
                              if dag.node().hasFn(om.MFn.kMesh) else path)
            if xform not in logs:
                continue
            w = weights.setdefault(xform, [0.0] * om.MFnMesh(dag).numVertices)
            fn = om.MFnSingleIndexedComponent(comp)
            kind = comp.apiType()
            if kind == om.MFn.kMeshVertComponent:
                soft = fn.hasWeights
                for j, v in enumerate(fn.getElements()):
                    w[v] = max(w[v], fn.weight(j).influence if soft else 1.0)
                continue
            prefix = {om.MFn.kMeshPolygonComponent: "f", om.MFn.kMeshEdgeComponent: "e"}.get(kind)
            if prefix is None:
                continue
            comps = ["%s.%s[%d]" % (xform, prefix, e) for e in fn.getElements()]
            for vtx in cmds.ls(cmds.polyListComponentConversion(comps, toVertex=True) or [], flatten=True):
                w[int(vtx.rsplit("[", 1)[1][:-1])] = 1.0  # faces / edges: their vertices, full weight
    return logs, weights


def has_log_noise(xform):
    shape = _log_shape(xform)
    return bool(shape) and cmds.attributeQuery(LOG_SETTINGS, node=shape, exists=True)


def log_settings(xform):
    shape = _log_shape(xform)
    s = dict(LOG_DEFAULTS)
    if shape and cmds.attributeQuery(LOG_SETTINGS, node=shape, exists=True):
        try:
            s.update(json.loads(cmds.getAttr(shape + "." + LOG_SETTINGS) or "{}"))
        except ValueError:
            pass
    return s


def logs_with_noise(nodes=None):
    """Every mesh transform carrying Log Noise (under nodes, or in the scene)."""
    shapes = cmds.ls(nodes, dag=True, type="mesh", long=True, noIntermediate=True) if nodes else \
        cmds.ls(type="mesh", long=True, noIntermediate=True)
    out = []
    for shape in shapes or []:
        if cmds.attributeQuery(LOG_SETTINGS, node=shape, exists=True):
            xform = long_name(cmds.listRelatives(shape, parent=True, fullPath=True)[0])
            if xform not in out:
                out.append(xform)
    return out


def _ln_points(shape):
    return [(p.x, p.y, p.z) for p in om.MFnMesh(get_dag_path(shape)).getPoints(om.MSpace.kObject)]


def _ln_write(shape, new):
    """Write object-space points as vertex tweaks: one undoable setAttr per
    5,000 vertices (type float3 is what makes a history-free mesh update)."""
    cur = _ln_points(shape)
    n = len(cur)
    tweaks = [(0.0, 0.0, 0.0)] * n
    plug = om.MFnDependencyNode(get_dag_path(shape).node()).findPlug("pnts", False)
    for idx in plug.getExistingArrayAttributeIndices():
        if idx < n:
            el = plug.elementByLogicalIndex(idx)
            tweaks[idx] = (el.child(0).asFloat(), el.child(1).asFloat(), el.child(2).asFloat())
    for a in range(0, n, 5000):
        b = min(n, a + 5000)
        flat = []
        for i in range(a, b):
            t, c, q = tweaks[i], cur[i], new[i]
            flat.extend((t[0] + q[0] - c[0], t[1] + q[1] - c[1], t[2] + q[2] - c[2]))
        cmds.setAttr("%s.pnts[%d:%d]" % (shape, a, b - 1), *flat, type="float3")


def _ln_rest(shape):
    flat = cmds.getAttr(shape + "." + LOG_REST) or []
    return [(flat[i], flat[i + 1], flat[i + 2]) for i in range(0, len(flat) - 2, 3)]


def _ln_weights(shape):
    if not cmds.attributeQuery(LOG_WEIGHTS, node=shape, exists=True):
        return None
    w = cmds.getAttr(shape + "." + LOG_WEIGHTS) or []
    return list(w) or None


def add_log_noise(logs, settings=None, weights=None, seeds=None):
    """Give each log its noise (one Ctrl+Z). Each gets a random seed unless
    seeds {xform: seed} says otherwise. Returns {"added", "skipped", "low"}."""
    weights = weights or {}
    seeds = seeds or {}
    report = {"added": [], "skipped": [], "low": []}
    with UndoChunk("Log Noise"):
        for xform in logs:
            shape = _log_shape(xform)
            if shape is None:
                continue
            if has_log_noise(xform):
                report["skipped"].append(xform)
                continue
            rest = _ln_points(shape)
            if len(rest) < LOG_MIN_VERTS:
                report["low"].append(xform)
            s = dict(LOG_DEFAULTS)
            s.update(settings or {})
            s["seed"] = int(seeds.get(xform, random.randint(0, 9999)))
            for ln, kw in ((LOG_REST, {"dataType": "doubleArray"}), (LOG_SETTINGS, {"dataType": "string"})):
                if not cmds.attributeQuery(ln, node=shape, exists=True):
                    cmds.addAttr(shape, longName=ln, **kw)
            cmds.setAttr(shape + "." + LOG_REST, [c for pt in rest for c in pt], type="doubleArray")
            w = weights.get(xform)
            if w:
                if not cmds.attributeQuery(LOG_WEIGHTS, node=shape, exists=True):
                    cmds.addAttr(shape, longName=LOG_WEIGHTS, dataType="doubleArray")
                cmds.setAttr(shape + "." + LOG_WEIGHTS, list(w), type="doubleArray")
            cmds.setAttr(shape + "." + LOG_SETTINGS, json.dumps(s, sort_keys=True), type="string")
            _ln_write(shape, log_noise_points(rest, s, w))
            report["added"].append(xform)
    return report


def update_log_noise(changes, live=True):
    """Change settings on logs and re-shape them. changes: {xform: {key: value}}.
    live: slider edits, kept out of the undo queue (like Path Scatter's
    previews); otherwise one Ctrl+Z. Returns logs whose topology changed
    since the noise was added (left alone: Bake them, then re-apply)."""
    stale = []
    with (NoUndo() if live else UndoChunk("Log Noise edit")):
        for xform, change in changes.items():
            shape = _log_shape(xform)
            if not shape or not has_log_noise(xform):
                continue
            rest = _ln_rest(shape)
            if len(rest) != om.MFnMesh(get_dag_path(shape)).numVertices:
                stale.append(xform)
                continue
            s = log_settings(xform)
            s.update(change)
            _ln_write(shape, log_noise_points(rest, s, _ln_weights(shape)))
            cmds.setAttr(shape + "." + LOG_SETTINGS, json.dumps(s, sort_keys=True), type="string")
    return stale


def _ln_drop_attrs(shape):
    for ln in (LOG_REST, LOG_WEIGHTS, LOG_SETTINGS):
        if cmds.attributeQuery(ln, node=shape, exists=True):
            cmds.deleteAttr(shape + "." + ln)


def reset_log_noise(logs):
    """Back to the plain cylinder and forget the noise (one Ctrl+Z)."""
    done, stale = [], []
    with UndoChunk("Log Noise reset"):
        for xform in logs:
            shape = _log_shape(xform)
            if not shape or not has_log_noise(xform):
                continue
            rest = _ln_rest(shape)
            if len(rest) != om.MFnMesh(get_dag_path(shape)).numVertices:
                stale.append(xform)
                continue
            _ln_write(shape, rest)
            _ln_drop_attrs(shape)
            done.append(xform)
    return done, stale


def bake_log_noise(logs):
    """Keep the shape, drop the stored rest shape and settings (one Ctrl+Z)."""
    done = []
    with UndoChunk("Log Noise bake"):
        for xform in logs:
            shape = _log_shape(xform)
            if shape and has_log_noise(xform):
                _ln_drop_attrs(shape)
                done.append(xform)
    return done


class LogNoisePanel(QtWidgets.QWidget):
    TOOL_NAME = "Log Noise"
    TOOL_TIP = "Turn cylinders into natural-looking logs: bumps along the grain, bulges, a slight bend and taper."

    FIELDS = ("bump", "frequency", "grain", "octaves", "bulge", "bend", "taper", "axis", "seed")

    def __init__(self, parent=None):
        super(LogNoisePanel, self).__init__(parent)
        self._jobs = []
        self._pending = set()
        self._sel_timer = QtCore.QTimer(self)
        self._sel_timer.setSingleShot(True)
        self._sel_timer.setInterval(80)
        self._sel_timer.timeout.connect(self._sync_from_selection)
        self._edit_timer = QtCore.QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.setInterval(40)
        self._edit_timer.timeout.connect(self._apply_pending)
        self._build()
        self._install_jobs()
        self._sync_from_selection()

    # ============================================================== layout
    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(6)
        top = QtWidgets.QWidget()
        tl = QtWidgets.QVBoxLayout(top)
        tl.setContentsMargins(6, 0, 6, 0)
        tl.setSpacing(6)
        tl.addWidget(ToolHeader("Log Noise", "Turn cylinders into natural-looking logs (shack supports, posts, "
                                             "fences). Nothing extra in the scene: no plugin, no nodes."))
        self.next_banner = NextBanner()
        tl.addWidget(self.next_banner)
        outer.addWidget(top)
        scroll, col = scroll_column()
        outer.addWidget(scroll, 1)

        # ---- 1. select
        card = self.step_select = StepCard(1, "Select logs", "Cylinders with some height and axis subdivisions "
                                                             "(e.g. 24 x 20). Select vertices (soft selection "
                                                             "too) to roughen just part of a log.")
        self.sel_label = hint_label("")
        card.add(self.sel_label)
        col.addWidget(card)

        # ---- 2. add
        card = self.step_add = StepCard(2, "Add noise", "Each log gets its own random seed. One Ctrl+Z undoes it.")
        self.apply_btn = primary_button("Apply to Selected")
        self.apply_btn.setMinimumHeight(28)
        self.apply_btn.setToolTip("Add the noise to every selected log that doesn't have it yet, with the "
                                  "settings below.")
        self.apply_btn.clicked.connect(lambda *_: self.apply())
        card.add(self.apply_btn)
        col.addWidget(card)

        # ---- 3. shape
        card = self.step_shape = StepCard(3, "Shape", "Edits the selected logs live (each keeps its own seed). "
                                                      "Select several to change them together.")
        grid = Section("", header=False)
        self.f = {}
        self.f["bump"] = FloatField(0.0, 1.0, 0.0, 0.3, decimals=3, step=0.01)
        grid.add_row("Bumps", self.f["bump"], "How rough the surface is, relative to the log's radius.")
        self.f["frequency"] = FloatField(0.01, 50.0, 0.1, 10.0, decimals=2, step=0.1)
        grid.add_row("Bump size", self.f["frequency"], "Bumps per radius: higher = smaller, busier bumps.")
        self.f["grain"] = FloatField(1.0, 50.0, 1.0, 10.0, decimals=1, step=0.5)
        grid.add_row("Grain", self.f["grain"], "Stretches the bumps along the log like wood grain (1 = round "
                                               "bumps).")
        self.f["bulge"] = FloatField(0.0, 2.0, 0.0, 0.5, decimals=3, step=0.01)
        grid.add_row("Bulge", self.f["bulge"], "Slow swelling and thinning along the length.")
        self.f["bend"] = FloatField(0.0, 1.0, 0.0, 0.15, decimals=3, step=0.005)
        grid.add_row("Bend", self.f["bend"], "How far the log wanders off straight, relative to its length. "
                                             "The ends stay put.")
        self.f["taper"] = FloatField(0.0, 0.9, 0.0, 0.9, decimals=2, step=0.05)
        grid.add_row("Taper", self.f["taper"], "Thinner towards the top end.")
        card.add(grid)
        seed_row = QtWidgets.QWidget()
        sl = QtWidgets.QHBoxLayout(seed_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        seed_label = QtWidgets.QLabel("Seed")
        seed_label.setMinimumWidth(92)
        self.f["seed"] = IntField(0, 99999, 0, 9999)
        self.f["seed"].setToolTip("Typing a seed gives every selected log that seed (same shape on the same "
                                  "cylinder).")
        rand = secondary_button("Randomize Seeds", "A new random seed for each selected log (each with noise if "
                                                   "nothing is selected).")
        rand.clicked.connect(lambda *_: self.randomize())
        sl.addWidget(seed_label)
        sl.addWidget(self.f["seed"], 1)
        sl.addWidget(rand)
        card.add(seed_row)
        adv = Section("Advanced", expanded=False)
        self.f["octaves"] = IntField(1, 6)
        adv.add_row("Detail", self.f["octaves"], "Noise octaves: more = finer detail on the bumps (slower).")
        self.f["axis"] = ComboField(LOG_AXES)
        adv.add_row("Axis", self.f["axis"], "The log's length direction. Auto = its longest bounding-box side.")
        card.add(adv)
        for key, widget in self.f.items():
            widget.setValue(LOG_DEFAULTS[key])
            widget.changed.connect(lambda k=key: self._queue(k))
        col.addWidget(card)

        # ---- 4. finish
        card = self.step_finish = StepCard(4, "Finish", "Bake keeps the shape and forgets the settings. Reset "
                                                        "puts the cylinder back. Both are one Ctrl+Z.")
        pick = secondary_button("Select Logs With Noise", "Select every log that has Log Noise (under the "
                                                          "selection, or in the whole scene).")
        pick.clicked.connect(lambda *_: self.select_noisy())
        reset = secondary_button("Reset", "Put the selected logs back to their original shape.")
        reset.clicked.connect(lambda *_: self.reset())
        bake = secondary_button("Bake", "Keep the selected logs as they are and drop the stored settings.")
        bake.clicked.connect(lambda *_: self.bake())
        card.add(button_row(pick, reset, bake))
        col.addWidget(card)
        col.addStretch(1)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setContentsMargins(8, 0, 8, 6)
        outer.addWidget(self.status)

    # ============================================================ state
    def set_status(self, text, level="info"):
        color = LEVEL_COLORS.get(level, "#a8a8a8") if level != "error" else "#e06060"
        self.status.setText('<span style="color:%s">%s</span>' % (color, text))

    def _settings(self):
        return {k: w.value() for k, w in self.f.items()}

    def _selected(self):
        logs, _ = log_selection()
        return logs

    def _sync_from_selection(self):
        try:
            logs = self._selected()
            noisy = [x for x in logs if has_log_noise(x)]
            if noisy:  # show the first selected log's settings, like the Channel Box
                s = log_settings(noisy[0])
                for key, widget in self.f.items():
                    widget.setValue(s.get(key, LOG_DEFAULTS[key]))
            low = [x for x in logs if om.MFnMesh(get_dag_path(_log_shape(x))).numVertices < LOG_MIN_VERTS]
            if not logs:
                text = "Nothing selected."
            else:
                text = "%d log(s) selected, %d with noise." % (len(logs), len(noisy))
                if low:
                    text += " %d have under %d vertices: add subdivisions for the noise to show." % (
                        len(low), LOG_MIN_VERTS)
            self.sel_label.setText(text)
            self.step_select.set_state("done" if logs else "current")
            self.step_add.set_state("done" if noisy and len(noisy) == len(logs) else
                                    ("current" if logs else "todo"))
            self.step_shape.set_state("current" if noisy else "todo")
            self.step_finish.set_state("todo")
            if not logs:
                self.next_banner.set_text("Select cylinders to turn into logs (they need height and axis "
                                          "subdivisions, e.g. 24 x 20).")
            elif len(noisy) < len(logs):
                self.next_banner.set_text("Press <b>Apply to Selected</b>.")
            else:
                self.next_banner.set_text("Shape them with the sliders in step 3 (live). <b>Bake</b> when you're "
                                          "happy, or <b>Reset</b> to get the cylinders back.")
        except Exception:
            traceback.print_exc()

    # ============================================================= actions
    def _queue(self, key):
        self._pending.add(key)
        self._edit_timer.start()

    @ui_safe
    def _apply_pending(self):
        keys, self._pending = self._pending, set()
        logs = [x for x in self._selected() if has_log_noise(x)]
        if not keys or not logs:
            return
        values = self._settings()
        change = {k: values[k] for k in keys}
        t0 = time.time()
        stale = update_log_noise({x: change for x in logs}, live=True)
        if stale:
            self.set_status("%d log(s) changed topology since the noise was added: Bake them, then apply again."
                            % len(stale), level="warn")
        else:
            self.set_status("Updated %d log(s) in %.2fs." % (len(logs), time.time() - t0))

    @ui_safe
    def apply(self):
        logs, weights = log_selection()
        if not logs:
            self.set_status("Select some cylinders (or vertices on them) first.", level="warn")
            return
        s = self._settings()
        s.pop("seed")
        t0 = time.time()
        report = add_log_noise(logs, s, weights)
        msg = "Added noise to %d log(s) in %.2fs" % (len(report["added"]), time.time() - t0)
        if report["skipped"]:
            msg += "; %d already had it (use the sliders)" % len(report["skipped"])
        if report["low"]:
            msg += "; %d have under %d vertices, so the noise barely shows" % (len(report["low"]), LOG_MIN_VERTS)
        self.set_status(msg + ". One Ctrl+Z undoes it.", level="warn" if report["low"] else "fixed")
        self._sync_from_selection()

    @ui_safe
    def randomize(self):
        logs = [x for x in self._selected() if has_log_noise(x)] or logs_with_noise()
        if not logs:
            self.set_status("No logs with noise to re-seed.", level="warn")
            return
        update_log_noise({x: {"seed": random.randint(0, 9999)} for x in logs}, live=True)
        self.set_status("New seeds for %d log(s)." % len(logs))
        self._sync_from_selection()

    @ui_safe
    def select_noisy(self):
        sel = cmds.ls(selection=True, long=True, objectsOnly=True) or []
        logs = logs_with_noise(sel) if sel else []
        logs = logs or logs_with_noise()
        if logs:
            cmds.select(logs, replace=True)
        self.set_status("Selected %d log(s) with noise." % len(logs) if logs else "No logs with noise found.")

    @ui_safe
    def reset(self):
        done, stale = reset_log_noise(self._selected())
        msg = "Reset %d log(s) to their original shape." % len(done)
        if stale:
            msg += " %d changed topology since, so they can't be reset (Bake them instead)." % len(stale)
        self.set_status(msg, level="warn" if stale or not done else "info")
        self._sync_from_selection()

    @ui_safe
    def bake(self):
        done = bake_log_noise(self._selected())
        self.set_status("Baked %d log(s): the shape stays, the settings are gone." % len(done) if done else
                        "Select logs with noise to bake.", level="info" if done else "warn")
        self._sync_from_selection()

    # ======================================================= scene events
    def _install_jobs(self):
        if maya_main_window() is None:
            return
        self._jobs = [cmds.scriptJob(event=["SelectionChanged", lambda: self._sel_timer.start()])]
        _registry()["jobs"].extend(self._jobs)

    def shutdown(self):
        self._sel_timer.stop()
        self._edit_timer.stop()
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
    ("Modeling", [PathScatterPanel, BevelResolverPanel, LogNoisePanel]),
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
