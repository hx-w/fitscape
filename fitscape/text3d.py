#!/usr/bin/env python3
"""CJK + latin text -> watertight extruded Manifold, with correct glyph holes.

Glyph outlines come from matplotlib's TextPath; manifold3d's CrossSection with the
even-odd fill rule turns nested contours into holes automatically. `embolden`
thickens dense strokes so small CJK still prints crisply on a 0.4 mm nozzle.
"""
import numpy as np
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties
import manifold3d as m3d
from .geom import to_trimesh

# macOS fonts (Medium/Gothic weights survive FDM). Override via config.fonts.
FONTS = {
    "gothic": "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "heiti":  "/System/Library/Fonts/STHeiti Medium.ttc",
    "songti": "/System/Library/Fonts/Songti.ttc",
}


def resolve_font(name_or_path):
    return FONTS.get(name_or_path, name_or_path)


def _loops(s, font_path, size=100.0):
    fp = FontProperties(fname=resolve_font(font_path))
    tp = TextPath((0, 0), s, size=size, prop=fp)
    return [np.asarray(l, float) for l in tp.to_polygons(closed_only=True) if len(l) >= 4]


def text_manifold(s, font_path, height_mm=1.0, target_h_mm=None, size=100.0, embolden=0.0):
    loops = _loops(s, font_path, size)
    if not loops:
        raise ValueError(f"empty geometry for {s!r}")
    allp = np.vstack(loops)
    minx, miny = allp[:, 0].min(), allp[:, 1].min()
    caph = allp[:, 1].max() - miny
    sc = (target_h_mm / caph) if target_h_mm else 1.0
    loops = [(np.asarray(l) - [minx, miny]) * sc for l in loops]
    cs = m3d.CrossSection(loops, m3d.FillRule.EvenOdd)
    if embolden:
        cs = cs.offset(embolden, m3d.JoinType.Round, 2.0, 32)
    return cs.extrude(height_mm)


def text_mesh(s, font_path, height_mm=1.0, target_h_mm=None, size=100.0, embolden=0.0):
    man = text_manifold(s, font_path, height_mm, target_h_mm, size, embolden)
    mesh = to_trimesh(man)
    b = mesh.bounds
    mesh.apply_translation([-b[0][0], -b[0][1], 0])
    return mesh, (mesh.extents[0], mesh.extents[1])
