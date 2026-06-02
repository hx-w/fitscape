#!/usr/bin/env python3
"""Fetch & sample elevation from AWS Terrarium terrain tiles (global, no API key,
WGS-84 — same datum as the GPS). elevation_m = (R*256 + G + B/256) - 32768.
"""
import io, math, os
import numpy as np
import requests
from PIL import Image
from scipy.ndimage import gaussian_filter

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
R_MAJOR = 6378137.0
MERC_MAX = math.pi * R_MAJOR


def lonlat_to_merc(lon, lat):
    return (np.radians(lon) * R_MAJOR,
            np.log(np.tan(np.pi/4 + np.radians(lat)/2)) * R_MAJOR)


def merc_to_tile(x, y, z):
    n = 2 ** z
    return ((x + MERC_MAX) / (2*MERC_MAX) * n, (MERC_MAX - y) / (2*MERC_MAX) * n)


def _tile(z, x, y, session, cache):
    p = f"{cache}/{z}_{x}_{y}.png"
    if os.path.exists(p):
        return np.asarray(Image.open(p).convert("RGB"), float)
    r = session.get(TILE_URL.format(z=z, x=x, y=y), timeout=30); r.raise_for_status()
    open(p, "wb").write(r.content)
    return np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"), float)


def _tile_range(lon_min, lat_min, lon_max, lat_max, z):
    xm0, ym0 = lonlat_to_merc(lon_min, lat_max)
    xm1, ym1 = lonlat_to_merc(lon_max, lat_min)
    tx0 = int(merc_to_tile(xm0, ym0, z)[0]); tx1 = int(merc_to_tile(xm1, ym1, z)[0])
    ty0 = int(merc_to_tile(xm0, ym0, z)[1]); ty1 = int(merc_to_tile(xm1, ym1, z)[1])
    return tx0, tx1, ty0, ty1


def choose_zoom(lon_min, lat_min, lon_max, lat_max, max_zoom=14, max_px=2304):
    """Highest zoom whose mosaic longest side stays <= max_px (prevents OOM on
    long rides/ultras). -> (zoom, tx0, tx1, ty0, ty1)."""
    for z in range(int(max_zoom), 5, -1):
        tx0, tx1, ty0, ty1 = _tile_range(lon_min, lat_min, lon_max, lat_max, z)
        if max(tx1-tx0+1, ty1-ty0+1) * 256 <= max_px:
            return z, tx0, tx1, ty0, ty1
    return (6, *_tile_range(lon_min, lat_min, lon_max, lat_max, 6))


def fetch(lon_min, lat_min, lon_max, lat_max, zoom=14, cache=".demcache", max_px=2304):
    """Fetch terrarium tiles, auto-stepping zoom down so the mosaic stays <= max_px."""
    os.makedirs(cache, exist_ok=True)
    zoom, tx0, tx1, ty0, ty1 = choose_zoom(lon_min, lat_min, lon_max, lat_max, zoom, max_px)
    nx, ny = tx1 - tx0 + 1, ty1 - ty0 + 1
    s = requests.Session(); s.headers.update({"User-Agent": "fitscape/1.0"})
    mosaic = np.zeros((ny*256, nx*256, 3))
    for j, ty in enumerate(range(ty0, ty1+1)):
        for i, tx in enumerate(range(tx0, tx1+1)):
            mosaic[j*256:(j+1)*256, i*256:(i+1)*256] = _tile(zoom, tx, ty, s, cache)
    elev = (mosaic[:, :, 0]*256 + mosaic[:, :, 1] + mosaic[:, :, 2]/256) - 32768
    return elev, dict(zoom=zoom, tx0=tx0, ty0=ty0)


def clean(elev, smooth_px=0.8, lo=0.0, hi=9000.0):
    elev = np.clip(elev, lo, hi)
    return gaussian_filter(elev, sigma=smooth_px)


def sampler(elev, meta):
    z, tx0, ty0 = meta["zoom"], meta["tx0"], meta["ty0"]
    H, W = elev.shape

    def sample(lon, lat):
        xm, ym = lonlat_to_merc(np.asarray(lon, float), np.asarray(lat, float))
        fx, fy = merc_to_tile(xm, ym, z)
        px = np.clip((fx - tx0) * 256, 0, W - 1.001)
        py = np.clip((fy - ty0) * 256, 0, H - 1.001)
        x0 = np.floor(px).astype(int); y0 = np.floor(py).astype(int)
        dx = px - x0; dy = py - y0
        return (elev[y0, x0]*(1-dx)*(1-dy) + elev[y0, x0+1]*dx*(1-dy) +
                elev[y0+1, x0]*(1-dx)*dy + elev[y0+1, x0+1]*dx*dy)
    return sample
