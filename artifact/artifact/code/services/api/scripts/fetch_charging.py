"""EV charging stations for the scene, from OpenStreetMap.

Written after checking what the data actually says, which changed the design. Inside the
Thu Duc bbox OSM holds **zero** charging stations; the nearest is 7.5 km from the scene
centre. Da Nang is the same story. Vietnam is not unmapped in general — Hanoi has ~310
stations, mostly VinFast — so this is a coverage gap in these two areas, not evidence that
no station exists there.

That distinction drives the whole script. It fetches the bbox *and* a buffer around it, and
records `in_scene` per station, so the app can say "no station is mapped inside the demo
area, and here is the nearest one that is" instead of showing an empty map that reads as
"there is nowhere to charge". Absence of data is not data of absence, and inventing a pin
to fill the gap would be the same failure the gazetteer layer exists to prevent.
"""
import json
import math
import time
import urllib.parse
import urllib.request

from common import RAW, load_scenes, scene_name

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
HEADERS = {"User-Agent": "duong-an-vn-hackathon-demo/0.1 (research demo; contact: local)"}
BUFFER_KM = 12.0        # far enough to reach the nearest real station from either scene


def _haversine_km(lon1, lat1, lon2, lat2) -> float:
    r, p1, p2 = 6371.0, math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _bearing_vi(lon1, lat1, lon2, lat2) -> str:
    dx = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    dy = lat2 - lat1
    deg = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    names = ["bắc", "đông bắc", "đông", "đông nam", "nam", "tây nam", "tây", "tây bắc"]
    return names[int((deg + 22.5) // 45) % 8]


def _query(box: str) -> str:
    return (f'[out:json][timeout:180];('
            f'nwr["amenity"="charging_station"]{box};'
            f'nwr["amenity"="fuel"]["fuel:electricity"="yes"]{box};'
            f');out center tags;')


def _fetch(box: str) -> list:
    """Overpass is flaky under load; alternate mirrors with backoff rather than failing."""
    last = None
    for attempt in range(5):
        url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
        try:
            req = urllib.request.Request(
                url, data=urllib.parse.urlencode({"data": _query(box)}).encode(),
                headers=HEADERS)
            with urllib.request.urlopen(req, timeout=200) as r:
                return json.loads(r.read().decode())["elements"]
        except Exception as ex:
            last = ex
            print(f"[warn] {url.split('/')[2]}: {ex}")
            time.sleep(4 * (attempt + 1))
    raise SystemExit(f"Overpass unreachable after 5 attempts: {last}")


def _sockets(tags: dict) -> list:
    return sorted(k.split(":", 1)[1] for k in tags if k.startswith("socket:")
                  and not k.endswith((":output", ":voltage", ":current")))


def main() -> None:
    scene = scene_name()
    scenes, _ = load_scenes()
    w, s, e, n = scenes[scene]["bbox"]
    cx, cy = (w + e) / 2, (s + n) / 2
    dlat = BUFFER_KM / 111.0
    dlon = BUFFER_KM / (111.0 * math.cos(math.radians(cy)))
    box = f"({s - dlat:.4f},{w - dlon:.4f},{n + dlat:.4f},{e + dlon:.4f})"
    print(f"[charging] {scene}: bbox + {BUFFER_KM:.0f} km buffer")

    stations = []
    for el in _fetch(box):
        tags = el.get("tags", {})
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        if lon is None or lat is None:
            continue
        in_scene = w <= lon <= e and s <= lat <= n
        stations.append({
            "osm_id": f"{el['type']}/{el['id']}",
            "name": tags.get("name") or tags.get("operator") or tags.get("brand")
                    or "Trạm sạc (OSM không ghi tên)",
            "operator": tags.get("operator") or tags.get("brand") or "",
            "capacity": tags.get("capacity", ""),
            "sockets": _sockets(tags),
            "access": tags.get("access", ""),
            "fee": tags.get("fee", ""),
            "motorcar": tags.get("motorcar", ""),
            "motorcycle": tags.get("motorcycle", ""),
            "lon": round(lon, 6), "lat": round(lat, 6),
            "in_scene": in_scene,
            "km_from_scene_centre": round(_haversine_km(cx, cy, lon, lat), 2),
            "bearing_from_scene_vi": _bearing_vi(cx, cy, lon, lat),
            "source": "osm",
        })
    stations.sort(key=lambda st: (not st["in_scene"], st["km_from_scene_centre"]))

    n_in = sum(1 for st in stations if st["in_scene"])
    out = {
        "scene": scene, "bbox": [w, s, e, n], "buffer_km": BUFFER_KM,
        "n_in_scene": n_in, "n_in_buffer": len(stations) - n_in,
        "stations": stations,
        "source": {"name": "OpenStreetMap (Overpass)", "licence": "ODbL",
                   "tags": "amenity=charging_station, amenity=fuel + fuel:electricity=yes"},
        # Locations are real. Whether a station is reachable during the event is computed
        # from the SIMULATED flood layer, so the two are tagged separately at serve time.
        "evidence_class": "real geometry",
        "coverage_note": ("Không có trạm nào được ánh xạ trong vùng demo không có nghĩa là "
                          "không tồn tại trạm — OSM phủ trạm sạc ở VN còn thưa."),
    }
    path = RAW / f"{scene}.charging.json"
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"[charging] {scene}: {n_in} in scene, {len(stations) - n_in} within "
          f"{BUFFER_KM:.0f} km buffer -> {path}")


if __name__ == "__main__":
    main()
