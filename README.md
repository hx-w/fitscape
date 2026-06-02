# fitscape

**把一份 Garmin/FIT 运动记录变成一块可直接 3D 打印的地形浮雕纪念牌。**
Turn any Garmin `.fit` activity into a 3D-printable terrain-relief medallion — real terrain,
your GPS route as a raised red ridge that thickens where you slowed down, auto-labelled stats,
and a swappable frame shape. Outputs print-ready `.3mf` / `.stl` for Bambu Studio & friends.

<p align="center">
  <img src="docs/images/hexagon-iso.png" width="48%"/>
  <img src="docs/images/hexagon-top.png" width="48%"/>
</p>

> 往 `resources/` 扔一个 `.fit`，跑一行命令，就在 `output/<名字>/` 得到**隔离、完整、可打印**的产物：
> `*.3mf`（四部件已对齐分色）、`.glb`、`stl/`、渲染图、`stats.json`、`config_used.yaml`、专属打印说明。

---

## ✨ 能做什么

- 🗺️ **真实地形浮雕**：按路线坐标抓取全球高程（AWS Terrarium，无需 API key，WGS-84 与 GPS 同基准），生成等高浮雕。
- 🟥 **路线即故事**：你的 GPS 轨迹做成凸起的红色「线脊」，**越慢/越陡的地方越高越粗**（可改用心率、坡度驱动）。单色，任何打印机可打。
- 🏷️ **成绩自动标注**：距离 / 爬升 / 日期 / 用时 / 配速 / 心率 / 卡路里… 从 FIT 自动算出，模板化布局到边框各边。
- ⬡ **边框可换形状**：六边形 / 方形 / 菱形 / 三角 / 五边 / 八边 / 圆形，路线自动收进盘内不出界。
- 🧩 **四色实体已分离**：地形/路线/边框/文字互不重叠，多色打印颜色干净；也可单色只打地形。
- ✅ **几何保证水密**：全部布尔运算走 `manifold3d`，导出 STL/3MF 重载均水密，可直接切片。

## 🖼️ 示例（同一条「雄鹰线」越野跑，换不同边框）

| 六边形 hexagon | 圆形 circle | 方形 square |
|:---:|:---:|:---:|
| <img src="docs/images/hexagon-top.png" width="240"/> | <img src="docs/images/circle-top.png" width="240"/> | <img src="docs/images/square-top.png" width="240"/> |

<p align="center"><img src="docs/images/hexagon-low.png" width="70%"/><br/>
<sub>低角度可见：红色线脊随快慢起伏——爬坡的艰难「立」在线上。</sub></p>

可打印示例文件：[`docs/sample/xiongying-hexagon.3mf`](docs/sample/xiongying-hexagon.3mf)（直接拖进 Bambu Studio）。

## 🚀 快速开始

```bash
pip install -r requirements.txt          # macOS 自带中日韩字体；其它系统见下方“字体”

# 把 .fit 放进 resources/，然后：
python make.py 600371130_ACTIVITY.fit --title 雄鹰线        # 默认六边形
python make.py 600371130_ACTIVITY.fit --shape circle --title 雄鹰线
python make.py 600371130_ACTIVITY.fit --preset square_modern --title 雄鹰线
python make.py --all                                        # 批量处理 resources/ 下所有 fit
```

仓库自带一份示例 `resources/600371130_ACTIVITY.fit`，开箱即可复现上面的图。

### 命令行
| 参数 | 说明 |
|---|---|
| `fit` | FIT 文件名或路径（会在 `resources/` 里找） |
| `--all` | 处理 `resources/` 下所有 fit |
| `--shape` | `hexagon`/`hexagon_pointy`/`square`/`diamond`/`triangle`/`pentagon`/`octagon`/`circle` |
| `--title` | 顶部标题文字（缺省 = 运动类型，如「越野跑」） |
| `--preset` | `presets/` 里的样式名（不含 .yaml） |
| `--config` | 单次活动的 YAML 覆盖 |
| `--exaggeration` | 垂直放大倍率（快捷覆盖） |
| `--out` / `--no-render` | 自定义输出目录 / 跳过渲染 |

配置叠加顺序：内置默认 → `--preset` → `--config` → 命令行参数。

## 🏷️ 标注系统（模板化、自动布局）

不写 `labels` 时按形状插槽 + 解析到的成绩**自动布局**；要自定义就在 YAML 里写：

```yaml
title: 雄鹰线
labels:
  - {slot: top,    content: "{title}",        size: title, rot: upright}
  - {slot: bottom, content: "{date}",         size: stat,  rot: auto}
  - {slot: ll,     content: "{distance}"}
  - {slot: lr,     content: "{ascent_arrow}"}
  - {slot: ul,     content: "{duration}"}
  - {slot: ur,     content: "♥{hr}"}
```

`content` 可混排占位符与文字（`"D+{ascent}"`、`"♥{hr}"`、`"{date_cn}"`）。过长会自动缩放并提示。

**可用占位符**（FIT 自动算出）：`{distance}` `{distance_full}` `{distance_mi}` `{ascent}`
`{ascent_arrow}` `{descent}` `{date}` `{date_dash}` `{date_cn}` `{duration}` `{duration_hms}`
`{pace}` `{hr}` `{hr_heart}` `{maxhr}` `{maxhr_heart}` `{calories}` `{kcal}` `{speed_kmh}` `{elev_max}` `{sport}`

## ⚙️ 主要可配置项（`fitscape/config.py`，YAML 全可覆盖）

- **外形**：`shape` `across_mm` `frame_width` `frame_chamfer` `frame_rim_margin`
- **立体**：`base_h` `exaggeration`
- **地形/DEM**：`grid_spacing` `dem_smooth_px` `dem_zoom`（最大缩放，长活动自动降级防爆内存）`route_safe_mm`
- **路线红脊**：`route_encode`(`height`/`uniform`) `route_metric`(`speed`/`hr`/`grade`) `route_invert`
  `route_w_fast/slow` `route_h_fast/slow` `route_embed` `route_resample_mm` `speed_smooth_s`
- **文字**：`h_title` `h_stat` `text_raise` `text_ring_frac` `embolden_title` `font_title` `font_stat`
- **配色**：`color_terrain` `color_route` `color_frame` `color_text`（RGBA 0–255）
- **其他**：`utc_offset_hours`（缺省按经度估算时区）

## 🖨️ 打印（拓竹 Bambu Studio）

拖入 `<stem>.3mf` → 四部件已对齐 → 分配滤料（frame=黑 / terrain=绿 / route=红 / labels=白）→
平躺、底面贴板、**无需支撑**（地形是高度场）→ 层高 0.16 mm、填充 10–15%。
也可单色：只用 `stl/terrain.stl`（已含路线凹槽）。每个产物目录都有专属 `README.md`。

## 🧱 架构（`fitscape/`）

| 模块 | 职责 |
|---|---|
| `activity.py` | 解析 FIT → 轨迹 + 成绩模板串 |
| `dem.py` | AWS Terrarium 高程瓦片抓取/采样/去噪（自动选缩放） |
| `shapes.py` | 形状抽象：轮廓 / 棱柱 / 倒角 / 标注插槽 / 路线内接拟合 |
| `projector.py` | 经纬度 ↔ 模型(mm)，按形状把路线收进盘内 |
| `text3d.py` | 文字（含 CJK）→ 水密实体；密集字加粗 |
| `builders.py` | 地形 / 路线 / 边框 / 文字 四个实体 |
| `geom.py` | manifold3d ↔ trimesh、布尔、高度场实体 |
| `render.py` · `pipeline.py` · `config.py` | 渲染 / 串联 / 配置与自动标注 |

## 🔤 字体

CJK 标题默认用 macOS 的 `Hiragino Sans GB` / `STHeiti`。其它系统在 `fitscape/text3d.py` 的 `FONTS`
里换成本机字体路径（如思源黑体 `SourceHanSansSC`），或在 config 用 `font_title` / `font_stat` 指定。

## 📄 License

[MIT](LICENSE) © hx-w · 示例数据 `resources/600371130_ACTIVITY.fit` 为作者本人在苏州「雄鹰线」的一次越野跑记录。
