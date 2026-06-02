#!/usr/bin/env python3
"""Pluggable tile footprints. A Shape knows how to: draw its outer/inner outline,
build a (chamfered) prism, place named label slots around its rim, and fit the
GPS route fully inside its inner area with a safety margin.

All sizes are in mm. `across` = across-corners (max width): 2R for a polygon,
diameter for a circle.
"""
import math
from collections import OrderedDict
import numpy as np
from scipy.optimize import linprog
from . import geom

CANON = {"right": 0, "ur": 45, "top": 90, "ul": 135,
         "left": 180, "ll": 225, "bottom": 270, "lr": 315}
_CARDINAL = {"top": 90, "bottom": 270, "right": 0, "left": 180}


def _name_for(angle_deg, used, tol=14.0):
    """Name a slot by cardinal (top/bottom/left/right) or quadrant diagonal
    (ur/ul/ll/lr). Returns None if the natural name is already taken."""
    a = angle_deg % 360
    for nm, c in _CARDINAL.items():
        if min(abs(a - c), 360 - abs(a - c)) <= tol:
            return nm if nm not in used else None
    nm = "ur" if 0 < a < 90 else "ul" if 90 < a < 180 else "ll" if 180 < a < 270 else "lr"
    return nm if nm not in used else None


class Slot:
    def __init__(self, name, anchor_deg, tangent_deg, outer_ap, inner_ap, length):
        self.name = name
        self.anchor_deg = anchor_deg
        self.tangent_deg = tangent_deg
        self.outer_ap = outer_ap      # centre -> outer rim along anchor (mm)
        self.inner_ap = inner_ap      # centre -> inner rim along anchor (mm)
        self.length = length          # usable width along the edge/tangent (mm)


class Shape:
    aspect = 1.0
    def outer_contour(self, across): ...
    def inner_across(self, across, fw): return across - 2 * fw
    def cross_section_contour(self, across): return self.outer_contour(across)
    def prism(self, across, height, z0=0.0):
        return geom.prism(self.outer_contour(across), height, z0)
    def chamfered_prism(self, across, height, chamfer):
        return geom.chamfered_prism(self.outer_contour(across), height, chamfer,
                                    self.apothem(across))
    def apothem(self, across): ...
    def slots(self, across, fw): ...
    def fit_route(self, xy, inner_across, safety): ...


class RegularPolygon(Shape):
    def __init__(self, n, rotation_deg=0.0):
        self.n = n
        self.rot = rotation_deg
        self.aspect = self._bbox_aspect()

    def _verts(self, across):
        R = across / 2.0
        a = np.radians(self.rot + np.arange(self.n) * 360.0 / self.n)
        return np.column_stack([R * np.cos(a), R * np.sin(a)])

    def _bbox_aspect(self):
        v = self._verts(2.0)
        return (v[:, 0].max() - v[:, 0].min()) / (v[:, 1].max() - v[:, 1].min())

    def outer_contour(self, across):
        return self._verts(across)

    def apothem(self, across):
        return (across / 2.0) * math.cos(math.pi / self.n)

    def _edge_angles(self):
        return [(self.rot + (k + 0.5) * 360.0 / self.n) % 360 for k in range(self.n)]

    def slots(self, across, fw):
        oa = self.apothem(across)
        ia = self.apothem(self.inner_across(across, fw))
        angs = self._edge_angles()
        order = sorted(range(self.n), key=lambda k: ((90 - angs[k]) % 360))  # CW from top
        side = across * math.sin(math.pi / self.n)         # polygon edge length
        out = OrderedDict()
        for idx, k in enumerate(order):
            ang = angs[k]
            name = _name_for(ang, out)
            if name is None:
                name = f"s{idx}"
            slot = Slot(name, ang, (ang + 90) % 360, oa, ia, side)
            out[name] = slot
            out[f"s{idx}"] = slot
        return out

    def fit_route(self, xy, inner_across, safety):
        th = np.radians(self._edge_angles())
        N = np.column_stack([np.cos(th), np.sin(th)])
        H = (N @ xy.T).max(axis=1)
        A = np.column_stack([-N, -np.ones(len(th))])
        res = linprog(c=[0, 0, 1.0], A_ub=A, b_ub=-H, bounds=[(None, None)] * 3, method="highs")
        cx, cy, t = res.x
        target = self.apothem(inner_across) - safety
        return float(cx), float(cy), target / float(t)


def _welzl(points):
    """Smallest enclosing circle (Welzl, randomized-free on hull). -> (cx,cy,r)."""
    P = [tuple(p) for p in points]

    def circ2(a, b):
        cx, cy = (a[0]+b[0])/2, (a[1]+b[1])/2
        return (cx, cy, math.hypot(a[0]-cx, a[1]-cy))

    def circ3(a, b, c):
        ax, ay, bx, by, cx_, cy_ = *a, *b, *c
        d = 2 * (ax*(by-cy_) + bx*(cy_-ay) + cx_*(ay-by))
        if abs(d) < 1e-12:
            return None
        ux = ((ax**2+ay**2)*(by-cy_) + (bx**2+by**2)*(cy_-ay) + (cx_**2+cy_**2)*(ay-by))/d
        uy = ((ax**2+ay**2)*(cx_-bx) + (bx**2+by**2)*(ax-cx_) + (cx_**2+cy_**2)*(bx-ax))/d
        return (ux, uy, math.hypot(ax-ux, ay-uy))

    def inside(c, p):
        return c and math.hypot(p[0]-c[0], p[1]-c[1]) <= c[2] + 1e-9

    c = None
    for i, p in enumerate(P):
        if inside(c, p):
            continue
        c = (p[0], p[1], 0.0)
        for j in range(i):
            if inside(c, P[j]):
                continue
            c = circ2(p, P[j])
            for k in range(j):
                if inside(c, P[k]):
                    continue
                c = circ3(p, P[j], P[k]) or c
    return c


class Circle(Shape):
    aspect = 1.0
    SEG = 256
    # default rim slots
    DEFAULT_SLOTS = ["top", "ur", "right", "lr", "bottom", "ll", "left", "ul"]

    def outer_contour(self, across):
        R = across / 2.0
        a = np.linspace(0, 2*np.pi, self.SEG, endpoint=False)
        return np.column_stack([R*np.cos(a), R*np.sin(a)])

    def apothem(self, across):
        return across / 2.0

    def slots(self, across, fw):
        oa = across/2.0; ia = oa - fw
        length = 0.62 * oa            # tangent budget between adjacent rim slots
        out = OrderedDict()
        for i, name in enumerate(self.DEFAULT_SLOTS):
            ang = CANON[name]
            out[name] = Slot(name, ang, (ang+90) % 360, oa, ia, length)
            out[f"s{i}"] = out[name]
        return out

    def fit_route(self, xy, inner_across, safety):
        cx, cy, r = _welzl(xy)
        target = inner_across/2.0 - safety
        return float(cx), float(cy), target / float(r)


# ---- factory ----
_SHAPES = {
    "hexagon":      lambda: RegularPolygon(6, 0.0),    # flat top/bottom, pointed L/R
    "hexagon_flat": lambda: RegularPolygon(6, 0.0),
    "hexagon_pointy": lambda: RegularPolygon(6, 30.0),
    "square":       lambda: RegularPolygon(4, 45.0),   # flat top/bottom/sides
    "diamond":      lambda: RegularPolygon(4, 0.0),
    "triangle":     lambda: RegularPolygon(3, 90.0),   # flat bottom, point up
    "pentagon":     lambda: RegularPolygon(5, 90.0),
    "octagon":      lambda: RegularPolygon(8, 22.5),
    "circle":       lambda: Circle(),
}


def make_shape(name):
    key = name.lower()
    if key not in _SHAPES:
        raise ValueError(f"unknown shape {name!r}; options: {sorted(_SHAPES)}")
    return _SHAPES[key]()
