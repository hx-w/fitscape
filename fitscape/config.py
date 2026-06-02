#!/usr/bin/env python3
"""TileConfig: every tunable for the relief tile, plus a flexible label system.

Defaults reproduce the original 雄鹰线 hexagon. Override via a YAML preset, a
per-activity YAML, or CLI flags. Labels are templated: `content` is a format
string over the activity's stat dict (e.g. "{distance}", "♥{hr}", or a literal).
"""
import math
from dataclasses import dataclass, field, asdict, fields
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
    # route
    route_style: str = "bead"         # "bead" (tube on terrain) | "ribbon" (speed wall)
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
    # ribbon style — expressive for flat rides: a wall whose height encodes a metric
    ribbon_thick: float = 1.8
    ribbon_h_min: float = 1.6
    ribbon_h_max: float = 12.0
    ribbon_metric: str = "speed"      # "speed"|"hr"|"grade"|"elevation" (tall = high)
    ribbon_embed: float = 0.6
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
    color_decoration: tuple = (236, 232, 222, 255)
    # labels: list of dicts {slot, content, size, rot, font, embolden}
    labels: list = field(default_factory=list)
    # decorations: place-names etc. placed on the terrain at lon/lat (from AMap).
    # each {text, lat, lon, size?, dx?, dy?, font?, embolden?}
    decorations: list = field(default_factory=list)
    decoration_h: float = 3.4
    decoration_raise: float = 0.7
    decoration_embed: float = 0.4
    # base style: "relief" (DEM terrain) | "flat" (map plate, for flat rides)
    terrain_style: str = "relief"
    color_base: tuple = (30, 42, 68, 255)        # flat-base / map colour
    # roads (map style) — OSM major roads raised on the base
    roads_enabled: bool = False
    road_classes: list = field(default_factory=lambda: ["motorway", "trunk", "primary"])
    road_raise: float = 0.7
    road_w_mm: float = 1.0                        # width of the top class; scaled by class
    road_res: float = 0.2                         # raster resolution (mm/px)
    road_corridor_km: float = 0.0                 # >0: keep only roads within this of route
    color_roads: tuple = (232, 228, 212, 255)
    # icons: each {type, lat, lon, size?, height?, dx?, dy?, angle?}
    # types: dot ring star diamond triangle flag bar building tower skyline
    icons: list = field(default_factory=list)
    color_icon: tuple = (242, 167, 58, 255)
    icon_size: float = 4.0
    icon_height: float = 2.4
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


# stat priority for auto-filling slots — running/hiking vs cycling (speed, not pace)
STAT_PRIORITY = ["{distance}", "{ascent_arrow}", "{duration}", "{hr_heart}",
                 "{pace}", "{kcal}", "{descent}"]
CYCLING_PRIORITY = ["{distance}", "{speed_kmh}", "{duration}", "{hr_heart}",
                    "{kcal}", "{ascent_arrow}"]


def auto_labels(shape, across, frame_width, fmt, title, sport=""):
    """Build a sensible default label set for whatever slots the shape exposes.
    Cycling activities prioritise avg speed over pace."""
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
    is_cycling = any(w in (sport or "").lower() for w in ["cycl", "bike", "骑"])
    prio = CYCLING_PRIORITY if is_cycling else STAT_PRIORITY
    contents = [c for c in prio if fmt.get(c.strip("{}"), "") != ""]
    for slot, content in zip(rest, contents):
        take(slot, content, "stat")
    return out
