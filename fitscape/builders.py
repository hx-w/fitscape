#!/usr/bin/env python3
"""Build the four printable bodies (terrain / route / frame / labels) for any
shape + config. All booleans via manifold3d; every body comes out watertight."""
import math
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.interpolate import RegularGridInterpolator
import manifold3d as m3d

from . import geom
from . import osm
from .text3d import text_manifold


class _FlatZ:
    """Constant terrain-height callable for the flat map base."""
    def __init__(self, z): self.z = z
    def __call__(self, pts): return np.full(len(np.atleast_2d(pts)), self.z)


def build_base_flat(activity, shape, cfg, proj, sampler=None):
    """A plain plate (no DEM relief) — the canvas for a road map."""
    ia = proj.inner_across
    base = shape.prism(ia, cfg.base_h)
    info = dict(zmax=cfg.base_h, floor=0.0, zfun=_FlatZ(cfg.base_h), inner_across=ia)
    return base, info


# ----------------------------------------------------------------- terrain
def build_terrain(activity, shape, cfg, proj, sampler):
    inner_across = proj.inner_across
    cont = shape.outer_contour(inner_across)
    half_w = np.abs(cont[:, 0]).max() + 2.0
    half_h = np.abs(cont[:, 1]).max() + 2.0
    nx = int(np.ceil(2*half_w/cfg.grid_spacing)) + 1
    ny = int(np.ceil(2*half_h/cfg.grid_spacing)) + 1
    X = np.linspace(-half_w, half_w, nx); Y = np.linspace(-half_h, half_h, ny)
    XX, YY = np.meshgrid(X, Y)
    lon, lat = proj.model_to_lonlat(XX.ravel(), YY.ravel())
    elev = sampler(lon, lat).reshape(YY.shape)
    floor = float(np.percentile(elev, cfg.elev_floor_pct))
    Ztop = np.maximum(proj.elev_to_z(elev, floor), cfg.base_h)
    block = geom.to_manifold(geom.heightmap_solid(X, Y, Ztop, zbase=0.0))
    terr = block ^ shape.prism(inner_across, float(Ztop.max()) + 20, z0=-5.0)
    zmax = float(terr.bounding_box()[5])   # actual clipped-terrain top (robust to off-tile spikes)
    zfun = RegularGridInterpolator((Y, X), Ztop, bounds_error=False, fill_value=None)
    info = dict(zmax=zmax, floor=floor, zfun=zfun, inner_across=inner_across)
    return terr, info


# ----------------------------------------------------------------- route
def _metric_series(activity, cfg):
    tr = activity.track
    if cfg.route_metric == "hr":
        v = np.nan_to_num(tr["hr"], nan=np.nanmedian(tr["hr"]))
        v = gaussian_filter1d(v, cfg.speed_smooth_s)
        intensity = v                                   # high HR -> tall
    elif cfg.route_metric == "grade":
        d = np.nan_to_num(tr["dist"]); a = np.nan_to_num(tr["alt"])
        dd = np.gradient(d); da = np.gradient(a)
        grade = np.zeros_like(dd)
        ok = np.abs(dd) > 0.3                     # avoid /0 at pauses (dup distance)
        grade[ok] = np.clip(da[ok] / dd[ok], -1.5, 1.5)
        intensity = gaussian_filter1d(np.abs(grade), cfg.speed_smooth_s)
    else:  # speed -> slow = tall
        v = np.nan_to_num(tr["spd"], nan=0.0)
        v = gaussian_filter1d(v, cfg.speed_smooth_s)
        intensity = -v
    return intensity


def _ribbon_intensity(activity, cfg):
    tr = activity.track
    m = cfg.ribbon_metric
    if m == "hr":
        v = np.nan_to_num(tr["hr"], nan=np.nanmedian(tr["hr"]))
    elif m == "elevation":
        v = np.nan_to_num(tr["alt"], nan=np.nanmedian(tr["alt"]))
    elif m == "grade":
        d = np.nan_to_num(tr["dist"]); a = np.nan_to_num(tr["alt"])
        dd = np.gradient(d); da = np.gradient(a)
        v = np.zeros_like(dd); ok = np.abs(dd) > 0.3
        v[ok] = np.abs(np.clip(da[ok] / dd[ok], -1.5, 1.5))
    else:  # speed: tall = fast
        v = np.nan_to_num(tr["spd"], nan=0.0)
    return gaussian_filter1d(v, cfg.speed_smooth_s)


def _resample_xy(mx, my, vals, step):
    seg = np.hypot(np.diff(mx), np.diff(my))
    cum = np.concatenate([[0], np.cumsum(seg)])
    s = np.arange(0, cum[-1], step)
    return np.interp(s, cum, mx), np.interp(s, cum, my), np.interp(s, cum, vals)


def build_route(activity, shape, cfg, proj, info):
    tr = activity.track
    mx, my = proj.lonlat_to_model(tr["lon"], tr["lat"])
    if cfg.route_style == "ribbon":
        return _build_ribbon(mx, my, activity, cfg, info)

    seg = np.hypot(np.diff(mx), np.diff(my))
    cum = np.concatenate([[0], np.cumsum(seg)])
    intensity = _metric_series(activity, cfg)
    s_new = np.arange(0, cum[-1], cfg.route_resample_mm)
    rx = np.interp(s_new, cum, mx); ry = np.interp(s_new, cum, my)
    ri = np.interp(s_new, cum, intensity)
    lo, hi = np.percentile(ri, [12, 88])
    t = np.clip((ri - lo) / max(hi - lo, 1e-6), 0, 1)          # 0 easy .. 1 effort
    if cfg.route_invert:
        t = 1 - t
    if cfg.route_encode == "uniform":
        t = np.full_like(t, 0.5)
    W = cfg.route_w_fast + t * (cfg.route_w_slow - cfg.route_w_fast)
    H = cfg.route_h_fast + t * (cfg.route_h_slow - cfg.route_h_fast)
    E = cfg.route_embed
    Zr = (H + E) / 2.0
    zc = info["zfun"](np.column_stack([ry, rx])) + (H - E) / 2.0
    unit = m3d.Manifold.sphere(1.0, 22)
    beads = [unit.scale([float(W[i]), float(W[i]), float(Zr[i])])
                 .translate([float(rx[i]), float(ry[i]), float(zc[i])])
             for i in range(len(rx))]
    caps = [m3d.Manifold.batch_hull([beads[i], beads[i+1]]) for i in range(len(beads)-1)]
    route = m3d.Manifold.batch_boolean(caps, m3d.OpType.Add)
    stats = dict(n=len(rx), effort_frac=float((t > 0.6).mean()))
    return route, stats


def _build_ribbon(mx, my, activity, cfg, info):
    """Route as a vertical wall whose height encodes a ride metric (speed/HR/...).
    Turns a flat ride into a winding 'skyline' of effort. Single body."""
    inten = _ribbon_intensity(activity, cfg)
    rx, ry, ri = _resample_xy(mx, my, inten, cfg.route_resample_mm)
    lo, hi = np.percentile(ri, [8, 92])
    t = np.clip((ri - lo) / max(hi - lo, 1e-6), 0, 1)
    if cfg.route_invert:
        t = 1 - t
    H = cfg.ribbon_h_min + t * (cfg.ribbon_h_max - cfg.ribbon_h_min)
    zbase = info["zfun"](np.column_stack([ry, rx])) - cfg.ribbon_embed
    th = cfg.ribbon_thick
    unit = m3d.Manifold.cube([1, 1, 1], center=True)
    posts = []
    for i in range(len(rx)):
        h = float(H[i]) + cfg.ribbon_embed
        posts.append(unit.scale([th, th, h]).translate(
            [float(rx[i]), float(ry[i]), float(zbase[i]) + h / 2.0]))
    caps = [m3d.Manifold.batch_hull([posts[i], posts[i+1]]) for i in range(len(posts)-1)]
    ribbon = m3d.Manifold.batch_boolean(caps, m3d.OpType.Add)
    stats = dict(n=len(rx), effort_frac=float((t > 0.6).mean()),
                 h_range=[round(float(H.min()), 1), round(float(H.max()), 1)])
    return ribbon, stats


# ----------------------------------------------------------------- decorations
def build_decorations(activity, shape, cfg, proj, info):
    """Place-name labels (from AMap) embossed on the terrain at their lon/lat,
    turning a bare base into a journey map. Returns a Manifold or None."""
    if not cfg.decorations:
        return None
    zfun = info["zfun"]
    mans = []
    for d in cfg.decorations:
        mx, my = proj.lonlat_to_model(d["lon"], d["lat"])
        mx = float(mx) + d.get("dx", 0.0); my = float(my) + d.get("dy", 0.0)
        h = float(d.get("size", cfg.decoration_h))
        font = d.get("font", cfg.font_stat)
        man = text_manifold(d["text"], font, height_mm=cfg.decoration_raise,
                            target_h_mm=h, embolden=d.get("embolden", 0.04))
        bb = man.bounding_box(); cx, cy = (bb[0]+bb[3])/2, (bb[1]+bb[4])/2
        z = float(zfun([[my, mx]])[0]) - cfg.decoration_embed
        man = man.translate([-cx, -cy, 0]).translate([mx, my, z])
        mans.append(man)
    if not mans:
        return None
    return m3d.Manifold.batch_boolean(mans, m3d.OpType.Add).simplify(0.012)


# ----------------------------------------------------------------- roads (map)
def build_roads(activity, shape, cfg, proj, info):
    """OSM major roads rasterised then extruded as a raised network on the base."""
    if not cfg.roads_enabled:
        return None
    from PIL import Image, ImageDraw
    from skimage import measure
    bb = activity.bbox; mg = 0.05
    roads = osm.fetch_roads(bb["lon_min"]-mg, bb["lat_min"]-mg,
                            bb["lon_max"]+mg, bb["lat_max"]+mg, classes=cfg.road_classes)
    if not roads:
        return None
    ia = proj.inner_across; cont = shape.outer_contour(ia)
    hw = np.abs(cont[:, 0]).max() + 2; hh = np.abs(cont[:, 1]).max() + 2
    res = cfg.road_res
    W = int(2*hw/res); H = int(2*hh/res)
    to_px = lambda mx, my: [((float(mx[i])+hw)/res, (hh-float(my[i]))/res) for i in range(len(mx))]
    img = Image.new("L", (W, H), 0); dr = ImageDraw.Draw(img)
    for r in roads:
        lon = np.array([p[0] for p in r["pts"]]); lat = np.array([p[1] for p in r["pts"]])
        mx, my = proj.lonlat_to_model(lon, lat)
        w = max(1, int(round(cfg.road_w_mm * r["w"] / res)))
        dr.line(to_px(mx, my), fill=255, width=w, joint="curve")
    mask = np.asarray(img) > 128
    # clip roads to a corridor around the route (declutter -> streets along the way)
    if cfg.road_corridor_km > 0:
        rmx, rmy = proj.lonlat_to_model(activity.track["lon"], activity.track["lat"])
        cimg = Image.new("L", (W, H), 0); cdr = ImageDraw.Draw(cimg)
        cw = max(2, int(round(cfg.road_corridor_km*1000*proj.scale_xy*2 / res)))
        cdr.line(to_px(rmx, rmy), fill=255, width=cw, joint="curve")
        mask = mask & (np.asarray(cimg) > 128)
    if not mask.any():
        return None
    P = 3                                    # zero-pad so roads never touch the raster
    mask = np.pad(mask, P)                    # edge -> all contours close -> no flood-fill
    loops = []
    for c in measure.find_contours(mask.astype(float), 0.5):
        if len(c) >= 4:
            loops.append(np.column_stack([(c[:, 1]-P)*res - hw, hh - (c[:, 0]-P)*res]))
    cs = m3d.CrossSection(loops, m3d.FillRule.EvenOdd)
    z0 = info["zmax"]
    man = cs.extrude(cfg.road_raise + 0.3).translate([0, 0, z0 - 0.3])   # slight embed
    return man ^ shape.prism(ia, z0 + cfg.road_raise + 4, z0=z0 - 4)     # clip to footprint


# ----------------------------------------------------------------- icons
def _star(points, r_out, r_in):
    ang = np.linspace(-np.pi/2, 1.5*np.pi, 2*points, endpoint=False)
    rr = np.where(np.arange(2*points) % 2 == 0, r_out, r_in)
    return np.column_stack([rr*np.cos(ang), rr*np.sin(ang)])


def _icon_manifold(kind, size, h):
    s = size / 2.0
    if kind == "dot":
        return m3d.Manifold.cylinder(h, s, s, 28)
    if kind == "ring":
        return m3d.Manifold.cylinder(h, s, s, 32) - m3d.Manifold.cylinder(h+2, s*0.55, s*0.55, 32).translate([0, 0, -1])
    if kind == "star":
        return geom.extrude_contours([_star(5, s, s*0.42)], h)
    if kind == "diamond":
        return geom.extrude_contours([_star(2, s, s)], h)   # square on its point
    if kind == "triangle":
        ang = np.deg2rad([90, 210, 330]); v = np.column_stack([s*np.cos(ang), s*np.sin(ang)])
        return geom.extrude_contours([v], h)
    if kind == "flag":
        pole = m3d.Manifold.cube([max(0.7, s*0.18), max(0.7, s*0.18), h], center=True).translate([0, 0, h/2])
        flagh = h*0.42
        pen = m3d.Manifold.cube([s*1.1, max(0.7, s*0.2), flagh], center=True).translate([s*0.55, 0, h - flagh*0.7])
        return pole + pen
    if kind == "bar":
        return m3d.Manifold.cube([s*0.5, s*0.5, h], center=True).translate([0, 0, h/2])
    if kind == "building":
        return m3d.Manifold.cube([size*0.78, size*0.78, h], center=True).translate([0, 0, h/2])
    if kind == "tower":                                  # tapered landmark tower
        sq = np.array([[-s, -s], [s, -s], [s, s], [-s, s]], float)
        return m3d.CrossSection([sq], m3d.FillRule.EvenOdd).extrude(h, scale_top=(0.42, 0.42))
    if kind == "skyline":                                # cluster of small buildings (起伏的小楼)
        hs = [0.55, 0.85, 0.65, 1.0, 0.5, 0.78]
        n = len(hs); bw = size / n * 0.92                # overlap neighbours -> one solid
        boxes = [m3d.Manifold.cube([size, bw*1.3, max(0.6, h*0.22)], center=True)
                     .translate([0, 0, h*0.11])]        # shared base slab connects them
        for i, hf in enumerate(hs):
            bx = (i - (n-1)/2) * (size / n); bh = h * hf
            boxes.append(m3d.Manifold.cube([bw, bw*1.3, bh], center=True).translate([bx, 0, bh/2]))
        return geom.union(boxes)
    return m3d.Manifold.cylinder(h, s, s, 24)


def build_icons(activity, shape, cfg, proj, info):
    if not cfg.icons:
        return None
    zf = info["zfun"]; mans = []
    for ic in cfg.icons:
        mx, my = proj.lonlat_to_model(ic["lon"], ic["lat"])
        mx = float(mx) + ic.get("dx", 0.0); my = float(my) + ic.get("dy", 0.0)
        size = float(ic.get("size", cfg.icon_size)); h = float(ic.get("height", cfg.icon_height))
        m = _icon_manifold(ic.get("type", "dot"), size, h)
        if ic.get("angle"):
            m = m.rotate([0, 0, float(ic["angle"])])
        z = float(zf([[my, mx]])[0]) - 0.3
        mans.append(m.translate([mx, my, z]))
    if not mans:
        return None
    return m3d.Manifold.batch_boolean(mans, m3d.OpType.Add)


# ----------------------------------------------------------------- frame
def build_frame(shape, cfg, info):
    rim_z = info["zmax"] + cfg.frame_rim_margin
    outer = shape.chamfered_prism(cfg.across_mm, rim_z, cfg.frame_chamfer)
    inner = shape.prism(info["inner_across"] - 0.8, rim_z + 6, z0=-3.0)
    return (outer - inner), dict(rim_z=rim_z)


# ----------------------------------------------------------------- labels
def _resolve_rot(mode, slot):
    if isinstance(mode, (int, float)):
        return float(mode)
    a = slot.anchor_deg
    if mode == "upright":
        return 0.0
    if mode == "coin":
        r = (a - 270) % 360
        return r - 360 if r > 180 else r
    # "auto"/"tangent": horizontal at top/bottom, else tangent in (-90,90]
    if mode == "auto" and (min(abs(a-90), 360-abs(a-90)) <= 14 or
                           min(abs(a-270), 360-abs(a-270)) <= 14):
        return 0.0
    t = slot.tangent_deg
    while t > 90:
        t -= 180
    while t <= -90:
        t += 180
    return t


def build_labels(activity, shape, cfg, frame_info):
    rim_z = frame_info["rim_z"]
    slots = shape.slots(cfg.across_mm, cfg.frame_width)
    mans = []
    for spec in cfg.labels:
        slot = slots.get(spec["slot"])
        if slot is None:
            continue
        text = spec["content"].format(**activity.fmt).strip()
        if not text:
            continue
        size = spec.get("size", "stat")
        h = cfg.h_title if size == "title" else cfg.h_stat if size == "stat" else float(size)
        font = spec.get("font") or (cfg.font_title if size == "title" else cfg.font_stat)
        emb = spec.get("embolden")
        if emb is None:
            emb = cfg.embolden_title if size == "title" else 0.0
        rot = _resolve_rot(spec.get("rot", "auto"), slot)
        flat_outer = slot.outer_ap - cfg.frame_chamfer
        ring_r = slot.inner_ap + cfg.text_ring_frac * (flat_outer - slot.inner_ap)
        man = text_manifold(text, font, height_mm=cfg.text_raise, target_h_mm=h, embolden=emb)
        bb = man.bounding_box()
        w = bb[3] - bb[0]
        avail_w = 0.92 * slot.length                       # along the edge
        avail_h = 2.0 * (flat_outer - ring_r) * 0.98        # outward radial room
        fac = min(1.0, avail_w / max(w, 1e-6), avail_h / max(h, 1e-6))
        if fac < 0.995:                                    # auto-shrink to fit the slot
            h *= fac
            print(f"[fitscape] label {text!r} shrunk to {h:.1f}mm to fit slot '{slot.name}'")
            man = text_manifold(text, font, height_mm=cfg.text_raise, target_h_mm=h, embolden=emb)
            bb = man.bounding_box()
        cx, cy = (bb[0]+bb[3])/2, (bb[1]+bb[4])/2
        ap = math.radians(slot.anchor_deg)
        man = (man.translate([-cx, -cy, 0]).rotate([0, 0, rot])
                  .translate([ring_r*math.cos(ap), ring_r*math.sin(ap), rim_z]))
        mans.append(man)
    if not mans:
        return None
    return m3d.Manifold.batch_boolean(mans, m3d.OpType.Add).simplify(0.012)
