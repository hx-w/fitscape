#!/usr/bin/env python3
"""End-to-end: FIT + TileConfig -> isolated, printable output bundle."""
import json, os
import numpy as np
import trimesh
import yaml

from . import activity as A
from . import dem as DEM
from . import shapes as SH
from . import geom
from .projector import Projector
from . import builders as B
from . import config as CFG
from . import render as R

CACHE = ".demcache"


def _geo_bbox(proj, shape, inner_across, margin):
    cont = shape.outer_contour(inner_across)
    lon, lat = proj.model_to_lonlat(cont[:, 0], cont[:, 1])
    dlon = lon.max() - lon.min(); dlat = lat.max() - lat.min()
    return (lon.min()-margin*dlon, lat.min()-margin*dlat,
            lon.max()+margin*dlon, lat.max()+margin*dlat)


def build_tile(fit_path, cfg, out_dir, renders=True, verbose=True):
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(f"{out_dir}/stl", exist_ok=True)
    os.makedirs(f"{out_dir}/renders", exist_ok=True)

    act = A.parse(fit_path, cfg.utc_offset_hours)
    shape = SH.make_shape(cfg.shape)
    proj = Projector(act, shape, cfg)

    # DEM over the inner-footprint extent (+ margin) so corners are covered
    bb = _geo_bbox(proj, shape, proj.inner_across, cfg.dem_margin)
    elev, meta = DEM.fetch(*bb, zoom=cfg.dem_zoom, cache=CACHE)
    elev = DEM.clean(elev, cfg.dem_smooth_px)
    sampler = DEM.sampler(elev, meta)

    terr_man, info = B.build_terrain(act, shape, cfg, proj, sampler)
    route_man, rstats = B.build_route(act, shape, cfg, proj, info)
    frame_man, finfo = B.build_frame(shape, cfg, info)
    if not cfg.labels:
        cfg.labels = CFG.auto_labels(shape, cfg.across_mm, cfg.frame_width, act.fmt, cfg.title)
    labels_man = B.build_labels(act, shape, cfg, finfo)

    # carve route + frame out of terrain -> non-overlapping bodies (clean colours)
    terrain = geom.to_trimesh(terr_man - route_man - frame_man, cfg.color_terrain)
    route = geom.to_trimesh(route_man, cfg.color_route)
    frame = geom.to_trimesh(frame_man, cfg.color_frame)
    labels = geom.to_trimesh(labels_man, cfg.color_text) if labels_man else None

    bodies = {"frame": frame, "terrain": terrain, "route": route}
    if labels is not None:
        bodies["labels"] = labels
    colors = {"frame": cfg.color_frame, "terrain": cfg.color_terrain,
              "route": cfg.color_route, "labels": cfg.color_text}

    if verbose:
        for n, tm in bodies.items():
            print(" ", geom.stats(tm, n))

    # ---- exports ----
    stem = os.path.splitext(os.path.basename(fit_path))[0]
    for n, tm in bodies.items():
        tm.export(f"{out_dir}/stl/{n}.stl")
    scene = trimesh.Scene()
    for n, tm in bodies.items():
        g = tm.copy()
        g.visual.face_colors = np.tile(np.array(colors[n], np.uint8), (len(g.faces), 1))
        scene.add_geometry(g, geom_name=n)
    scene.export(f"{out_dir}/{stem}.3mf")
    scene.export(f"{out_dir}/{stem}.glb")

    total = trimesh.util.concatenate(list(bodies.values()))
    size = total.extents
    report = dict(activity=act.fmt, stats=act.stats, shape=cfg.shape,
                  size_mm=[round(float(x), 1) for x in size],
                  watertight={n: bool(tm.is_watertight) for n, tm in bodies.items()},
                  filament_g={n: round(float(tm.volume)*1.24e-3, 1) for n, tm in bodies.items()},
                  effort_frac=round(rstats["effort_frac"], 2),
                  labels=cfg.labels)
    json.dump(report, open(f"{out_dir}/stats.json", "w"), ensure_ascii=False, indent=2)
    yaml.safe_dump(cfg.to_dict(), open(f"{out_dir}/config_used.yaml", "w"),
                   allow_unicode=True, sort_keys=False)

    rpaths = []
    if renders:
        for v in ["top", "iso", "iso2", "low"]:
            z = 1.05 if v == "top" else (1.5 if v == "low" else 1.18)
            sz = (1500, 950) if v == "low" else (1400, 1240)
            rpaths.append(R.render(bodies, colors, v, f"{out_dir}/renders/{v}.png", size=sz, zoom=z))
        R.contact_sheet([f"{out_dir}/renders/top.png", f"{out_dir}/renders/iso.png",
                         f"{out_dir}/renders/iso2.png", f"{out_dir}/renders/low.png"],
                        f"{out_dir}/renders/contact.png")

    _write_readme(out_dir, stem, cfg, act, report)
    return report


def _write_readme(out_dir, stem, cfg, act, report):
    f = act.fmt
    rows = "\n".join(
        f"| {spec['slot']} | {spec['content'].format(**f)} |" for spec in cfg.labels)
    fil = report["filament_g"]
    body_rows = "\n".join(
        f"| {n} | {report['watertight'][n]} | {report['filament_g'][n]} g |"
        for n in report["filament_g"])
    md = f"""# {cfg.title or f['sport']} · {cfg.shape} 地形纪念牌

由 `{os.path.basename(stem)}` 自动生成（fitscape）。

![预览](renders/contact.png)

## 运动数据
- 运动: **{f.get('sport','')}**　距离: **{f['distance']}**　爬升: **{f.get('ascent_arrow','')}**
- 日期: **{f['date']}**　用时: **{f['duration']}**　配速: **{f['pace']}**　平均心率: **{f.get('hr_heart','')}**
- 整体尺寸: **{report['size_mm'][0]} × {report['size_mm'][1]} × {report['size_mm'][2]} mm**

## 标注
| 位置 | 内容 |
|---|---|
{rows}

## 打印（拓竹 Bambu Studio）
1. 拖入 **`{stem}.3mf`**（4 个部件已对齐）；如提示合并为单对象的多部件，选「是」。
2. 分配滤料：frame=黑　terrain=绿　route=红　labels=白。
3. 平躺、底面贴板，**无需支撑**（地形是高度场）；层高 0.16mm，填充 10–15%。
4. 也可单色：只用 `stl/terrain.stl`（已含路线凹槽）。

## 文件
- `{stem}.3mf` / `.glb`，`stl/*.stl`，`renders/*.png`
- `stats.json`（解析数据）、`config_used.yaml`（可复现/再编辑）

| 部件 | 水密 | 估算用料(满实心) |
|---|---|---|
{body_rows}

> 重新生成或微调：编辑 `config_used.yaml` 后运行
> `python make.py {os.path.basename(stem)}.fit --config <该yaml>`
"""
    open(f"{out_dir}/README.md", "w").write(md)
