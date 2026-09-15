"""OSM -> place gazetteer + edge street names (docs/AI_FEATURES.md §F1-grounding).

Why this exists: the conversational assistant must never invent coordinates. Published
evaluations put LLM city-level localisation from raw lat/lon below 25% for every model
tested, and LLM geocoders degrade further on non-English toponyms in under-represented
geographies — exactly Thu Duc. So place -> coordinate is a *lookup against OSM*, never a
model recall. This script builds that lookup.

Outputs (both derived, both reproducible from data/raw):
  {scene}_places.json      streets + landmarks with coordinates, extent and edge members
  {scene}_edge_names.json  way_id -> street name, so engine replies can name roads

Neither output feeds the physics pipeline, so rebuilding it never invalidates a scenario.
"""
import json, math, unicodedata
from collections import defaultdict
from common import RAW, DERIVED, haversine_m, load_scenes, scene_name

# Landmark class -> the Vietnamese noun a user would actually say, for reply text.
KIND_VI = {
    "marketplace": "chợ", "hospital": "bệnh viện", "clinic": "phòng khám",
    "doctors": "phòng khám", "pharmacy": "nhà thuốc", "school": "trường",
    "university": "trường đại học", "college": "trường cao đẳng",
    "kindergarten": "trường mầm non", "police": "công an", "fire_station": "trạm cứu hỏa",
    "place_of_worship": "cơ sở tôn giáo", "bus_station": "bến xe", "fuel": "cây xăng",
    "townhall": "trụ sở hành chính", "community_centre": "nhà văn hóa",
    "library": "thư viện", "bank": "ngân hàng", "post_office": "bưu điện",
    "supermarket": "siêu thị", "mall": "trung tâm thương mại",
    "department_store": "trung tâm thương mại", "station": "ga", "halt": "ga",
    "park": "công viên", "stadium": "sân vận động", "sports_centre": "trung tâm thể thao",
    "attraction": "điểm tham quan", "museum": "bảo tàng", "government": "cơ quan nhà nước",
    "bridge": "cầu", "city": "khu vực", "town": "khu vực", "suburb": "phường/khu vực",
    "quarter": "khu vực", "neighbourhood": "khu phố", "village": "khu vực",
    "hamlet": "khu vực", "city_block": "khu phố",
}
TAG_ORDER = ("amenity", "shop", "place", "railway", "leisure", "tourism", "office",
             "man_made")
# A name whose members sprawl wider than this is not one findable place.
AMBIGUOUS_SPREAD_M = 2500.0


def norm(s: str) -> str:
    """Diacritic-free, lowercase, single-spaced key. Vietnamese d-stroke needs an
    explicit rule — NFD does not decompose U+0111."""
    s = s.replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


def _centroid(pts: list) -> tuple:
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _bbox(pts: list) -> list:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [round(min(xs), 6), round(min(ys), 6), round(max(xs), 6), round(max(ys), 6)]


def _spread_m(bb: list) -> float:
    return haversine_m(bb[0], bb[1], bb[2], bb[3])


def build_streets(scene: str) -> tuple[list, dict]:
    """Street entries from named OSM ways, joined to the built edge set by way_id.

    edge_id is '{way_id}-{seg}-{dir}' (build_graph.py), so the join needs no new field
    in the edge artifact and cannot drift from it.
    """
    osm = json.loads((RAW / f"{scene}.osm.json").read_text(encoding="utf-8"))
    way_name = {w["id"]: w["tags"]["name"] for w in osm["elements"]
                if w["type"] == "way" and w.get("tags", {}).get("name")}
    edges = json.loads((DERIVED / f"{scene}_edges.json").read_text(encoding="utf-8"))

    by_name: dict[str, dict] = defaultdict(lambda: {"edge_ids": [], "pts": []})
    for e in edges:
        nm = way_name.get(e["way_id"])
        if not nm:
            continue
        g = by_name[nm]
        g["edge_ids"].append(e["edge_id"])
        g["pts"].extend(e["coords"])

    streets = []
    for nm, g in by_name.items():
        bb = _bbox(g["pts"])
        lon, lat = _centroid(g["pts"])
        spread = _spread_m(bb)
        streets.append({
            "name": nm, "key": norm(nm), "kind": "street", "kind_vi": "đường",
            "lon": round(lon, 6), "lat": round(lat, 6), "bbox": bb,
            "extent_m": round(spread, 1), "n_edges": len(g["edge_ids"]),
            "edge_ids": sorted(g["edge_ids"]),
            "ambiguous": spread > AMBIGUOUS_SPREAD_M, "source": "osm",
        })
    streets.sort(key=lambda s: -s["n_edges"])
    return streets, {str(w): n for w, n in way_name.items()}


def build_landmarks(scene: str, bbox: list) -> list:
    """Named POIs / place nodes. `out center` gives ways and relations a centre point."""
    path = RAW / f"{scene}.poi.json"
    if not path.exists():
        print(f"[warn] {path} missing — landmarks empty; run fetch_raw.py")
        return []
    w, s, e, n = bbox
    out = []
    for el in json.loads(path.read_text(encoding="utf-8"))["elements"]:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        if lon is None or lat is None or not (w <= lon <= e and s <= lat <= n):
            continue
        kind = next((tags[k] for k in TAG_ORDER if k in tags), "place")
        out.append({
            "name": name, "key": norm(name), "kind": kind,
            "kind_vi": KIND_VI.get(kind, "địa điểm"),
            "lon": round(lon, 6), "lat": round(lat, 6),
            "osm_id": f"{el['type']}/{el['id']}", "source": "osm",
        })
    # Duplicate names (179 generic "Khu phố N" in Thu Duc) must announce themselves so
    # find_place returns candidates instead of silently picking one.
    counts: dict[str, int] = defaultdict(int)
    for p in out:
        counts[p["key"]] += 1
    for p in out:
        p["ambiguous"] = counts[p["key"]] > 1
    out.sort(key=lambda p: p["name"])
    return out


def main() -> None:
    scene = scene_name()
    scenes, _ = load_scenes()
    bbox = scenes[scene]["bbox"]

    streets, way_names = build_streets(scene)
    landmarks = build_landmarks(scene, bbox)

    DERIVED.mkdir(parents=True, exist_ok=True)
    places = {"scene": scene, "bbox": bbox, "streets": streets, "landmarks": landmarks}
    (DERIVED / f"{scene}_places.json").write_text(
        json.dumps(places, ensure_ascii=False), encoding="utf-8")
    (DERIVED / f"{scene}_edge_names.json").write_text(
        json.dumps(way_names, ensure_ascii=False), encoding="utf-8")

    amb_s = sum(1 for s in streets if s["ambiguous"])
    amb_l = sum(1 for p in landmarks if p["ambiguous"])
    print(f"[ok] {scene}: {len(streets)} streets ({amb_s} spread>{AMBIGUOUS_SPREAD_M:.0f}m), "
          f"{len(landmarks)} landmarks ({amb_l} duplicate-name), "
          f"{len(way_names)} named ways -> {DERIVED}/{scene}_places.json")


if __name__ == "__main__":
    main()
