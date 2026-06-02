#!/usr/bin/env python3
"""Build the four printable bodies (terrain / route / frame / labels) for any
shape + config. All booleans via manifold3d; every body comes out watertight."""
import math
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.interpolate import RegularGridInterpolator
import manifold3d as m3d

from . import geom
from .text3d import text_manifold


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
    zmax = float(Ztop.max())
    terr = block ^ shape.prism(inner_across, zmax + 20, z0=-5.0)
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


def build_route(activity, shape, cfg, proj, info):
    tr = activity.track
    mx, my = proj.lonlat_to_model(tr["lon"], tr["lat"])
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
            print(f"[fitrelief] label {text!r} shrunk to {h:.1f}mm to fit slot '{slot.name}'")
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
