"""Real ambient conditions for the scene: temperature, humidity, PM2.5/PM10, dust, AQI, UV.

Unlike the flood state, this is *not* simulated — it is a vendored snapshot of real
Open-Meteo forecast and air-quality data for the scene bbox, fetched once and checksummed
so the demo still runs with the network off.

The honest constraint, measured rather than assumed: both Open-Meteo products resolve to
roughly 0.1 degrees, about 11 km. The Thu Duc scene is ~6.6 x 6.1 km, so nine sample
points across it collapse into four distinct source cells. This script therefore records
the *source cells themselves*, with their real extents, instead of a dense grid. Painting
a smooth field from four samples would invent spatial structure the data does not contain,
which is the same failure the coverage layer exists to prevent (WORKFLOW G1.4).

Time basis matters too: these are real clock hours, not scenario ticks. The flood event is
a synthetic storm; ambient air is measured reality. The API keeps them separate and the UI
labels them differently.
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from common import RAW, load_scenes, scene_name

WX_URL = "https://api.open-meteo.com/v1/forecast"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WX_VARS = "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,wind_speed_10m"
AQ_VARS = "pm2_5,pm10,dust,us_aqi,uv_index"
SAMPLES = 3          # per axis; more than the source resolution, deliberately, to *measure* it
FORECAST_DAYS = 2


def _sample_points(bbox: list) -> tuple[list, list]:
    w, s, e, n = bbox
    lats, lons = [], []
    for i in range(SAMPLES):
        for j in range(SAMPLES):
            lats.append(round(s + (n - s) * i / (SAMPLES - 1), 4))
            lons.append(round(w + (e - w) * j / (SAMPLES - 1), 4))
    return lats, lons


def _get(url: str, lats: list, lons: list, hourly: str) -> list:
    q = urllib.parse.urlencode({
        "latitude": ",".join(map(str, lats)), "longitude": ",".join(map(str, lons)),
        "hourly": hourly, "timezone": "Asia/Bangkok", "forecast_days": FORECAST_DAYS,
    })
    req = urllib.request.Request(f"{url}?{q}", headers={
        "User-Agent": "duong-an-vn-hackathon-demo/0.1 (research demo; contact: local)"})
    with urllib.request.urlopen(req, timeout=90) as r:
        body = json.loads(r.read())
    return body if isinstance(body, list) else [body]


def _dedupe_cells(responses: list, keys: list) -> dict:
    """Collapse responses onto their distinct source cells.

    Open-Meteo snaps every request to its own grid, so several sample points can return
    byte-identical series. Keeping one entry per real cell is what makes the layer honest
    about how much spatial detail actually exists.
    """
    cells: dict = {}
    for d in responses:
        key = (round(d["latitude"], 4), round(d["longitude"], 4))
        if key in cells:
            continue
        hourly = d.get("hourly", {})
        cells[key] = {
            "lat": key[0], "lon": key[1],
            "time": hourly.get("time", []),
            **{k: hourly.get(k, []) for k in keys},
        }
    return cells


def main() -> None:
    scene = scene_name()
    scenes, _ = load_scenes()
    bbox = scenes[scene]["bbox"]
    lats, lons = _sample_points(bbox)

    wx = _dedupe_cells(_get(WX_URL, lats, lons, WX_VARS), WX_VARS.split(","))
    aq = _dedupe_cells(_get(AQ_URL, lats, lons, AQ_VARS), AQ_VARS.split(","))

    # Pair each weather cell with the air-quality cell nearest to it; the two products use
    # different grids, so the pairing is recorded rather than silently assumed.
    cells = []
    for (wlat, wlon), w in wx.items():
        alat, alon = min(aq, key=lambda k: (k[0] - wlat) ** 2 + (k[1] - wlon) ** 2)
        a = aq[(alat, alon)]
        cells.append({
            "weather_cell": {"lat": wlat, "lon": wlon},
            "air_cell": {"lat": alat, "lon": alon},
            "time": w["time"],
            **{k: w[k] for k in WX_VARS.split(",")},
            **{k: a[k] for k in AQ_VARS.split(",")},
        })

    out = {
        "scene": scene, "bbox": bbox,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timezone": "Asia/Bangkok",
        "sample_points": len(lats),
        "distinct_weather_cells": len(wx),
        "distinct_air_cells": len(aq),
        "source": {
            "weather": "Open-Meteo Forecast API (ECMWF/GFS blend)",
            "air_quality": "Open-Meteo Air Quality API (CAMS)",
            "licence": "CC-BY 4.0, non-commercial free tier",
        },
        "evidence_class": "observed",     # real measurement/forecast, NOT the storm sim
        "is_synthetic": False,
        "cells": cells,
    }
    path = RAW / f"{scene}.env.json"
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"[env] {scene}: {len(lats)} sample points -> {len(wx)} weather / {len(aq)} air "
          f"cells, {len(cells[0]['time'])} hours -> {path}")


if __name__ == "__main__":
    main()
