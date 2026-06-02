#!/usr/bin/env python3
"""TileConfig: every tunable for the relief tile, plus a flexible label system.

Defaults reproduce the original 雄鹰线 hexagon. Override via a YAML preset, a
per-activity YAML, or CLI flags. Labels are templated: `content` is a format
string over the activity's stat dict (e.g. "{distance}", "♥{hr}", or a literal).
"""
import math
from dataclasses import dataclass, field, asdict, fields
import numpy as np
import yaml


@dataclass
class TileConfig:
    # identity / footprint
    title: str = ""
    shape: str = "hexagon"
    across_mm: float = 132.0
    frame_width: float = 11.5
    frame_chamfer: float = 1.3
    frame_rim_margin: float = 1.8
    # vertical
    base_h: float = 3.0
    exaggeration: float = 1.55
    # terrain / DEM
    grid_spacing: float = 0.45
    dem_smooth_px: float = 0.8
    dem_zoom: int = 14
    dem_margin: float = 0.35          # extra geo margin fetched around route bbox
    route_safe_mm: float = 6.0
    elev_floor_pct: float = 2.0
    # route bead
    route_encode: str = "height"      # "height" | "uniform"
    route_metric: str = "speed"       # "speed" | "hr" | "grade"
    route_invert: bool = False        # invert so fast = tall
    route_w_fast: float = 1.05
    route_w_slow: float = 1.85
    route_h_fast: float = 0.9
    route_h_slow: float = 2.6
    route_embed: float = 0.45
    route_resample_mm: float = 1.2
    speed_smooth_s: float = 25.0
    # text
    h_title: float = 7.8
    h_stat: float = 5.8
    text_raise: float = 0.8
    text_ring_frac: float = 0.47
    embolden_title: float = 0.085
    font_title: str = "gothic"
    font_stat: str = "heiti"
    # colors (RGBA 0-255)
    color_terrain: tuple = (79, 125, 70, 255)
    color_route: tuple = (200, 40, 36, 255)
    color_frame: tuple = (28, 28, 30, 255)
    color_text: tuple = (244, 243, 239, 255)
    # labels: list of dicts {slot, content, size, rot, font, embolden}
    labels: list = field(default_factory=list)
    # misc
    utc_offset_hours: int = None

    # ---- merging ----
    @classmethod
    def from_dict(cls, d):
        cfg = cls()
        cfg.update(d or {})
        return cfg

    def update(self, d):
        valid = {f.name for f in fields(self)}
        for k, v in (d or {}).items():
            if k not in valid:
                raise KeyError(f"unknown config key {k!r}")
            if k.startswith("color_") and v is not None:
                v = tuple(v)
            setattr(self, k, v)
        return self

    def to_dict(self):
        return asdict(self)


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f) or {}


def merge(*dicts):
    out = {}
    for d in dicts:
        out.update({k: v for k, v in (d or {}).items() if v is not None})
    return out


# default stat priority for auto-filling slots
STAT_PRIORITY = ["{distance}", "{ascent_arrow}", "{duration}", "{hr_heart}",
                 "{pace}", "{kcal}", "{descent}"]


def auto_labels(shape, across, frame_width, fmt, title):
    """Build a sensible default label set for whatever slots the shape exposes."""
    slots = shape.slots(across, frame_width)
    named = [k for k in slots if not k.startswith("s")]
    used, out = set(), []

    def take(slot, content, size):
        used.add(slot)
        out.append({"slot": slot, "content": content, "size": size, "rot": "auto"})

    if "top" in named:
        take("top", title or "{sport}", "title")
    elif named:
        take(named[0], title or "{sport}", "title")
    if "bottom" in named and "bottom" not in used:
        take("bottom", "{date}", "stat")

    rest = [k for k in named if k not in used]
    rest.sort(key=lambda k: (round(math.sin(math.radians(slots[k].anchor_deg)), 3),
                             round(math.cos(math.radians(slots[k].anchor_deg)), 3)))
    contents = [c for c in STAT_PRIORITY if fmt.get(c.strip("{}"), "") != ""]
    for slot, content in zip(rest, contents):
        take(slot, content, "stat")
    return out
