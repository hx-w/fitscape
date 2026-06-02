#!/usr/bin/env python3
"""Parse any Garmin/FIT activity into a track + a rich set of formatted stat
strings ready for label templating. Drop a new .fit in resources/ and every
{distance}/{ascent}/{date}/{pace}/... placeholder fills automatically.
"""
import math
from dataclasses import dataclass, field
from datetime import timedelta
import numpy as np
import fitdecode

SEMI = 180.0 / 2**31

SPORT_CN = {
    "running": "跑步", "trail": "越野跑", "cycling": "骑行", "hiking": "徒步",
    "walking": "健走", "swimming": "游泳", "mountaineering": "登山",
}


@dataclass
class Activity:
    track: dict                 # arrays: lat lon alt dist spd hr t (seconds)
    stats: dict                 # numeric stats
    fmt: dict = field(default_factory=dict)   # formatted strings for labels
    sport_name: str = ""

    @property
    def bbox(self):
        la, lo = self.track["lat"], self.track["lon"]
        return dict(lat_min=float(la.min()), lat_max=float(la.max()),
                    lon_min=float(lo.min()), lon_max=float(lo.max()),
                    center_lat=float(la.mean()), center_lon=float(lo.mean()))


def _fmt_duration(s):
    h = int(s // 3600); m = int(round((s % 3600) / 60))
    if m == 60:
        h += 1; m = 0
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _fmt_pace(s_per_km):
    if not math.isfinite(s_per_km) or s_per_km <= 0:
        return "--"
    m = int(s_per_km // 60); sec = int(round(s_per_km % 60))
    if sec == 60:
        m += 1; sec = 0
    return f"{m}:{sec:02d}/km"


def parse(fit_path, utc_offset_hours=None):
    records, session, sport = [], {}, {}
    with fitdecode.FitReader(fit_path) as fr:
        for fr_ in fr:
            if not isinstance(fr_, fitdecode.FitDataMessage):
                continue
            g = lambda k: (fr_.get_value(k) if fr_.has_field(k) else None)
            if fr_.name == "record":
                la, lo = g("position_lat"), g("position_long")
                if la is None or lo is None:
                    continue
                records.append((g("timestamp"), la*SEMI, lo*SEMI,
                                g("enhanced_altitude") if g("enhanced_altitude") is not None else g("altitude"),
                                g("distance"),
                                g("enhanced_speed") if g("enhanced_speed") is not None else g("speed"),
                                g("heart_rate")))
            elif fr_.name == "session":
                for k in ["start_time", "total_distance", "total_elapsed_time", "total_ascent",
                          "total_descent", "total_calories", "sport", "sub_sport",
                          "avg_heart_rate", "max_heart_rate", "max_altitude", "min_altitude"]:
                    session[k] = g(k)
                session["avg_speed"] = g("enhanced_avg_speed") or g("avg_speed")
                session["max_speed"] = g("enhanced_max_speed") or g("max_speed")
            elif fr_.name == "sport":
                sport = {"name": g("name"), "sport": g("sport"), "sub_sport": g("sub_sport")}

    if not records:
        raise ValueError(f"no GPS records in {fit_path}")
    t0 = records[0][0]
    track = dict(
        lat=np.array([r[1] for r in records]),
        lon=np.array([r[2] for r in records]),
        alt=np.array([r[3] if r[3] is not None else np.nan for r in records], float),
        dist=np.array([r[4] if r[4] is not None else np.nan for r in records], float),
        spd=np.array([r[5] if r[5] is not None else np.nan for r in records], float),
        hr=np.array([r[6] if r[6] is not None else np.nan for r in records], float),
        t=np.array([(r[0]-t0).total_seconds() if r[0] else np.nan for r in records], float),
    )

    # timezone: explicit, else estimate from longitude
    if utc_offset_hours is None:
        utc_offset_hours = round(float(track["lon"].mean()) / 15.0)
    start_local = (session.get("start_time") or t0) + timedelta(hours=utc_offset_hours)

    dist_m = session.get("total_distance") or float(np.nanmax(track["dist"]))
    dur_s = session.get("total_elapsed_time") or float(np.nanmax(track["t"]))
    asc = session.get("total_ascent")
    desc = session.get("total_descent")
    avg_hr = session.get("avg_heart_rate")
    max_hr = session.get("max_heart_rate")
    cal = session.get("total_calories")
    dist_km = dist_m / 1000.0
    sub = session.get("sub_sport") or sport.get("sub_sport")
    sp = session.get("sport") or sport.get("sport")
    sport_cn = sport.get("name") or SPORT_CN.get(str(sub), SPORT_CN.get(str(sp), str(sp or "")))

    stats = dict(distance_m=dist_m, distance_km=dist_km, ascent_m=asc, descent_m=desc,
                 duration_s=dur_s, avg_hr=avg_hr, max_hr=max_hr, calories=cal,
                 avg_speed=session.get("avg_speed"), utc_offset=utc_offset_hours,
                 elev_max=float(np.nanmax(track["alt"])), elev_min=float(np.nanmin(track["alt"])),
                 start_local=start_local.isoformat(), n_points=len(records))

    pace = (dur_s / dist_km) if dist_km else float("inf")
    fmt = {
        "distance": f"{dist_km:.2f}km", "distance_full": f"{dist_km:.2f} km",
        "distance_mi": f"{dist_km*0.621371:.2f}mi",
        "ascent": f"{int(round(asc))}m" if asc is not None else "",
        "ascent_arrow": f"{int(round(asc))}m↑" if asc is not None else "",
        "descent": f"{int(round(desc))}m↓" if desc is not None else "",
        "date": start_local.strftime("%Y.%m.%d"),
        "date_dash": start_local.strftime("%Y-%m-%d"),
        "date_cn": start_local.strftime("%Y年%m月%d日"),
        "duration": _fmt_duration(dur_s),
        "duration_hms": f"{int(dur_s//3600)}:{int(dur_s%3600//60):02d}:{int(dur_s%60):02d}",
        "pace": _fmt_pace(pace) if math.isfinite(pace) and pace > 0 else "",
        "hr": f"{int(avg_hr)}" if avg_hr else "",
        "hr_heart": f"♥{int(avg_hr)}" if avg_hr else "",
        "maxhr": f"{int(max_hr)}" if max_hr else "",
        "maxhr_heart": f"♥{int(max_hr)}" if max_hr else "",
        "calories": f"{int(cal)}" if cal else "", "kcal": f"{int(cal)}kcal" if cal else "",
        "speed_kmh": f"{stats['avg_speed']*3.6:.1f}km/h" if stats['avg_speed'] else "",
        "elev_max": f"{int(round(stats['elev_max']))}m",
        "sport": sport_cn,
    }
    return Activity(track=track, stats=stats, fmt=fmt, sport_name=sport_cn)
