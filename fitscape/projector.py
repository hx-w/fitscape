#!/usr/bin/env python3
"""Geographic <-> model(mm) transforms. Uses the shape to fit the route fully
inside the inner footprint (Chebyshev/min-enclosing fit) at uniform scale."""
import numpy as np


class Projector:
    def __init__(self, activity, shape, cfg):
        bb = activity.bbox
        self.lat0, self.lon0 = bb["center_lat"], bb["center_lon"]
        self.K_lon = 111320.0 * np.cos(np.radians(self.lat0))
        self.K_lat = 110540.0
        xm = (activity.track["lon"] - self.lon0) * self.K_lon
        ym = (activity.track["lat"] - self.lat0) * self.K_lat
        xy = np.column_stack([xm, ym])
        self.inner_across = shape.inner_across(cfg.across_mm, cfg.frame_width)
        cx, cy, scale = shape.fit_route(xy, self.inner_across, cfg.route_safe_mm)
        self.cx_m, self.cy_m, self.scale_xy = cx, cy, scale
        self.cfg = cfg

    def lonlat_to_model(self, lon, lat):
        xm = (np.asarray(lon) - self.lon0) * self.K_lon
        ym = (np.asarray(lat) - self.lat0) * self.K_lat
        return (xm - self.cx_m) * self.scale_xy, (ym - self.cy_m) * self.scale_xy

    def model_to_lonlat(self, mx, my):
        xm = np.asarray(mx) / self.scale_xy + self.cx_m
        ym = np.asarray(my) / self.scale_xy + self.cy_m
        return xm / self.K_lon + self.lon0, ym / self.K_lat + self.lat0

    def elev_to_z(self, elev, floor):
        return self.cfg.base_h + (np.asarray(elev) - floor) * self.scale_xy * self.cfg.exaggeration
