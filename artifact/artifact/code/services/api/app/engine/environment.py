"""Ambient conditions layer: temperature, humidity, PM2.5/PM10, dust, AQI, UV.

Two things separate this from every other layer in the demo, and both are load-bearing:

1. **It is real, not simulated.** The flood state is a synthetic storm; this is a vendored
   snapshot of Open-Meteo forecast and air-quality data. It carries `evidence_class:
   observed` and `is_synthetic: false`, so the UI must badge it differently.

2. **It runs on the real clock, not the scenario tick.** Mixing the two would let the UI
   imply that measured air quality belongs to the simulated storm hour. The API therefore
   indexes this layer by hour index into the fetched series and never by tick.

Resolution is the other honesty constraint. Both Open-Meteo products land on roughly
0.1-degree cells (~11 km), and the Thu Duc scene is ~6.6 km across, so the whole scene is
covered by a handful of source cells. Values are assigned to render tiles by *nearest
source cell* — a blocky, checkable statement — rather than interpolated into a smooth
field, which would invent structure the data does not have.

Nothing here feeds passability or routing. Heat and dust change what a trip costs a rider,
but the safety case is about water, and widening it silently would be a change to the
safety argument rather than an addition to the map.
"""
from __future__ import annotations
import functools
import json
import math
from datetime import datetime, timedelta, timezone

from ..deps import DATA

# Variables served, with the unit the source reports them in.
UNITS = {
    "temperature_2m": "°C",
    "apparent_temperature": "°C",
    "relative_humidity_2m": "%",
    "precipitation": "mm",
    "wind_speed_10m": "km/h",
    "pm2_5": "µg/m³",
    "pm10": "µg/m³",
    "dust": "µg/m³",
    "us_aqi": "US AQI",
    "uv_index": "",
}
METRICS = tuple(UNITS)
TILES = 12                      # render tiles per axis; deliberately blocky


@functools.lru_cache(maxsize=4)
def load(scene: str) -> dict | None:
    path = DATA / "raw" / f"{scene}.env.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _nearest(cells: list, lon: float, lat: float) -> int:
    best, bd = 0, math.inf
    for i, c in enumerate(cells):
        w = c["weather_cell"]
        d = (w["lon"] - lon) ** 2 + (w["lat"] - lat) ** 2
        if d < bd:
            best, bd = i, d
    return best


def _cell_span_km(cells: list) -> float:
    """Spacing between distinct source cells, reported so the UI can state its own limits."""
    if len(cells) < 2:
        return 11.0                     # single-cell scenes: the product's native ~0.1 deg
    lats = sorted({c["weather_cell"]["lat"] for c in cells})
    lons = sorted({c["weather_cell"]["lon"] for c in cells})
    d = min([abs(b - a) for a, b in zip(lats, lats[1:])] or [0.1]
            + [abs(b - a) for a, b in zip(lons, lons[1:])] or [0.1])
    return round(d * 111.0, 1)


def current_hour_index(scene: str) -> int:
    """Index of the series hour closest to now in the scene's timezone.

    The snapshot starts at local midnight of its fetch day, so opening the layer at index
    0 shows the small hours of a possibly stale day. Anchoring on the real clock is what
    makes "observed" mean anything to a viewer.
    """
    env = load(scene)
    if not env or not env.get("cells"):
        return 0
    times = env["cells"][0]["time"]
    now = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
    best, bd = 0, None
    for i, ts in enumerate(times):
        try:
            d = abs((datetime.fromisoformat(ts) - now).total_seconds())
        except ValueError:
            continue
        if bd is None or d < bd:
            best, bd = i, d
    return best


def hours(scene: str) -> list:
    env = load(scene)
    return env["cells"][0]["time"] if env and env.get("cells") else []


def snapshot(scene: str, hour: int) -> dict | None:
    """Per-cell values plus a nearest-assignment tile grid for one hour of the series."""
    env = load(scene)
    if not env or not env.get("cells"):
        return None
    cells = env["cells"]
    series_len = len(cells[0]["time"])
    h = max(0, min(int(hour), series_len - 1))

    values = []
    for c in cells:
        v = {"weather_cell": c["weather_cell"], "air_cell": c["air_cell"]}
        for m in METRICS:
            series = c.get(m) or []
            v[m] = series[h] if h < len(series) else None
        values.append(v)

    w, s, e, n = env["bbox"]
    tiles = []
    for i in range(TILES):
        for j in range(TILES):
            lon0, lon1 = w + (e - w) * j / TILES, w + (e - w) * (j + 1) / TILES
            lat0, lat1 = s + (n - s) * i / TILES, s + (n - s) * (i + 1) / TILES
            tiles.append({"bbox": [round(lon0, 6), round(lat0, 6),
                                   round(lon1, 6), round(lat1, 6)],
                          "cell": _nearest(cells, (lon0 + lon1) / 2, (lat0 + lat1) / 2)})

    # A source this coarse often resolves the whole scene to one value. Saying so beats a
    # uniformly washed map that a viewer might read as "measured everywhere".
    uniform = {}
    for m in METRICS:
        seen = {v[m] for v in values if v[m] is not None}
        uniform[m] = len(seen) <= 1

    return {
        "scene": scene,
        "hour_index": h,
        "current_hour_index": current_hour_index(scene),
        "uniform_across_scene": uniform,
        "time_local": cells[0]["time"][h],
        "timezone": env.get("timezone", "Asia/Bangkok"),
        "n_hours": series_len,
        "cells": values,
        "tiles": tiles,
        "tile_assignment": "nearest_source_cell",
        "n_source_cells": len(cells),
        "source_cell_span_km": _cell_span_km(cells),
        "units": dict(UNITS),
        "metrics": list(METRICS),
        "source": env.get("source", {}),
        "fetched_at": env.get("fetched_at"),
        # This layer is measured reality on the real clock; the flood layer is a synthetic
        # storm on scenario ticks. Callers must not conflate the two.
        "evidence_class": "observed",
        "is_synthetic": False,
        "independent_of_scenario_clock": True,
        "affects_routing": False,
    }


def series(scene: str, metric: str) -> dict | None:
    """Scene-mean series for one metric, for a sparkline. Mean across source cells only."""
    env = load(scene)
    if not env or metric not in UNITS:
        return None
    cells = env["cells"]
    times = cells[0]["time"]
    out = []
    for i in range(len(times)):
        vals = [c[metric][i] for c in cells
                if c.get(metric) and i < len(c[metric]) and c[metric][i] is not None]
        out.append(round(sum(vals) / len(vals), 1) if vals else None)
    return {"metric": metric, "unit": UNITS[metric], "time": times, "values": out,
            "averaged_over_source_cells": len(cells)}
