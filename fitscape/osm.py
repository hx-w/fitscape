#!/usr/bin/env python3
"""Fetch the road network (OSM via Overpass) for the map-style base. Roads come
back as WGS-84 polylines — same datum as the GPS track, so no reprojection."""
import hashlib, json, os
import requests

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
# class -> weight (relative line width); only these are fetched (keeps it clean)
ROAD_WEIGHT = {
    "motorway": 1.0, "trunk": 0.95, "primary": 0.8,
    "secondary": 0.6, "tertiary": 0.45,
    "motorway_link": 0.7, "trunk_link": 0.65, "primary_link": 0.55,
}


def fetch_roads(lon_min, lat_min, lon_max, lat_max, classes=None, cache=".demcache"):
    os.makedirs(cache, exist_ok=True)
    classes = classes or ["motorway", "trunk", "primary", "secondary",
                          "motorway_link", "trunk_link", "primary_link"]
    key = hashlib.md5(f"{lon_min},{lat_min},{lon_max},{lat_max},{','.join(sorted(classes))}"
                      .encode()).hexdigest()[:12]
    path = f"{cache}/roads_{key}.json"
    if os.path.exists(path):
        return json.load(open(path))
    regex = "^(" + "|".join(classes) + ")$"
    bbox = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    q = (f'[out:json][timeout:90];way["highway"~"{regex}"]({bbox});out geom;')
    data = None
    for url in ENDPOINTS:
        try:
            r = requests.post(url, data={"data": q}, timeout=120)
            if r.status_code == 200:
                data = r.json(); break
        except Exception:
            continue
    if data is None:
        return []
    roads = []
    for el in data.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        cls = el.get("tags", {}).get("highway", "tertiary")
        pts = [(g["lon"], g["lat"]) for g in el["geometry"]]
        if len(pts) >= 2:
            roads.append({"cls": cls, "w": ROAD_WEIGHT.get(cls, 0.4), "pts": pts})
    if roads:                       # never cache an empty/failed fetch
        json.dump(roads, open(path, "w"))
    return roads
