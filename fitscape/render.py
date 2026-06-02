#!/usr/bin/env python3
"""Offscreen preview renders with a raking key light (relief reads like hillshade)."""
import numpy as np
import pyvista as pv
from PIL import Image
pv.OFF_SCREEN = True


def _hex(c):
    return "#%02x%02x%02x" % (int(c[0]), int(c[1]), int(c[2]))


MAT = {  # name -> (specular, spec_power, ambient, diffuse)
    "frame":   (0.30, 20, 0.34, 0.85),
    "terrain": (0.18, 12, 0.30, 1.00),
    "route":   (0.55, 28, 0.30, 0.95),
    "labels":  (0.25, 14, 0.45, 0.90),
    "places":  (0.25, 14, 0.45, 0.90),
    "roads":   (0.12, 10, 0.42, 0.95),
    "icons":   (0.55, 26, 0.32, 0.95),
}


def _lights(p, ctr, span, key):
    k = np.array(key, float); k /= np.linalg.norm(k)
    p.add_light(pv.Light(position=tuple(ctr + k*span*2.2), color="#fff4e2", intensity=1.05))
    p.add_light(pv.Light(position=tuple(ctr + np.array([1.4, -0.3, 1.2])*span), color="#d6e4ff", intensity=0.4))
    p.add_light(pv.Light(position=tuple(ctr + np.array([0, 1.6, 0.9])*span), color="#ffffff", intensity=0.3))


def render(bodies, colors, view, out, size=(1400, 1240), zoom=1.0, bg="#eef0f3",
           flat_shade=()):
    """bodies: {name: trimesh}; colors: {name: rgba}. flat_shade: body names to
    render with flat (faceted) shading instead of smooth (fixes flat-base streaks)."""
    p = pv.Plotter(off_screen=True, window_size=size, lighting="none")
    p.set_background(bg)
    allb = []
    for name, tm in bodies.items():
        if tm is None:
            continue
        spec, sp, amb, dif = MAT.get(name, (0.2, 15, 0.3, 0.9))
        p.add_mesh(pv.wrap(tm), color=_hex(colors[name]), smooth_shading=(name not in flat_shade),
                   specular=spec, specular_power=sp, ambient=amb, diffuse=dif)
        allb.append(tm.bounds)
    p.enable_anti_aliasing("ssaa")
    b = np.array(allb); lo = b[:, 0].min(0); hi = b[:, 1].max(0)
    ctr = (lo + hi) / 2; span = float((hi - lo).max())
    cams = {
        "top":  [(ctr[0], ctr[1], ctr[2]+span*1.9), tuple(ctr), (0, 1, 0)],
        "iso":  [(ctr[0]-span*0.95, ctr[1]-span*1.15, ctr[2]+span*1.0), tuple(ctr), (0, 0, 1)],
        "iso2": [(ctr[0]+span*1.0, ctr[1]-span*1.0, ctr[2]+span*0.85), tuple(ctr), (0, 0, 1)],
        "low":  [(ctr[0]-span*0.2, ctr[1]-span*1.25, ctr[2]+span*0.42), tuple(ctr), (0, 0, 1)],
    }
    p.camera_position = cams[view]
    key = (-0.7, -0.8, 0.5) if view == "top" else (-1, -0.5, 0.6)
    _lights(p, ctr, span, key)
    p.camera.zoom(zoom)
    p.screenshot(out)
    p.close()
    return out


def contact_sheet(paths, out, cell=(740, 640), bg=(255, 255, 255)):
    cw, ch = cell
    def fit(im):
        im = im.copy(); im.thumbnail((cw, ch))
        b = Image.new("RGB", (cw, ch), (244, 245, 247))
        b.paste(im, ((cw-im.width)//2, (ch-im.height)//2)); return b
    cells = [fit(Image.open(p).convert("RGB")) for p in paths]
    cols = 2; rows = (len(cells)+1)//2
    sheet = Image.new("RGB", (cw*cols+24*(cols-1), ch*rows+24*(rows-1)), bg)
    for i, c in enumerate(cells):
        r, col = divmod(i, cols)
        sheet.paste(c, (col*(cw+24), r*(ch+24)))
    sheet.save(out)
    return out
