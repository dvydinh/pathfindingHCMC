"""One-time raw data fetch: OSM extract (Overpass) + Copernicus GLO-30 DEM tile.
Network is required only here; everything downstream is offline."""
import json, math, sys
import httpx
from common import DATA, RAW, load_scenes, sha256

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
HEADERS = {"User-Agent": "duong-an-vn-hackathon-demo/0.1 (research demo; contact: local)"}
HIGHWAYS = ("motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
            "living_street|service|path|track|footway|cycleway")
# Named places the assistant must be able to resolve WITHOUT guessing coordinates
# (docs/AI_FEATURES.md §F1-grounding). Every landmark the gazetteer serves is sourced
# from OSM here; nothing is hand-entered from model memory.
POI_AMENITY = ("marketplace|hospital|clinic|doctors|pharmacy|school|university|college|"
               "kindergarten|police|fire_station|place_of_worship|bus_station|fuel|"
               "townhall|community_centre|library|bank|post_office")
POI_PLACE = ("city|town|suburb|quarter|neighbourhood|village|hamlet|city_block")
DEM_URL = ("https://copernicus-dem-30m.s3.amazonaws.com/"
           "Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM/"
           "Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM.tif")

def fetch_osm(scene: str, bbox: list) -> None:
    out = RAW / f"{scene}.osm.json"
    if out.exists():
        print(f"[skip] {out} exists"); return
    w, s, e, n = bbox
    q = (f'[out:json][timeout:180];'
         f'way["highway"~"^({HIGHWAYS})(_link)?$"]({s},{w},{n},{e});'
         f'out body; >; out skel qt;')
    print(f"[osm] {scene} bbox={bbox}")
    data, last = None, None
    for url in OVERPASS_URLS:
        try:
            r = httpx.post(url, data={"data": q}, headers=HEADERS, timeout=240)
            r.raise_for_status()
            data = r.json(); break
        except Exception as ex:  # try mirror
            last = ex; print(f"[warn] {url}: {ex}")
    if data is None:
        raise last
    n_ways = sum(1 for el in data["elements"] if el["type"] == "way")
    print(f"[osm] {n_ways} ways, {len(data['elements'])} elements")
    out.write_text(json.dumps(data), encoding="utf-8")

def fetch_poi(scene: str, bbox: list) -> None:
    """Named POIs + place (ward/neighbourhood) nodes — the landmark half of the gazetteer."""
    out = RAW / f"{scene}.poi.json"
    if out.exists():
        print(f"[skip] {out} exists"); return
    w, s, e, n = bbox
    box = f"({s},{w},{n},{e})"
    q = (f'[out:json][timeout:180];('
         f'nwr["amenity"~"^({POI_AMENITY})$"]["name"]{box};'
         f'nwr["shop"~"^(supermarket|mall|department_store)$"]["name"]{box};'
         f'nwr["place"~"^({POI_PLACE})$"]["name"]{box};'
         f'nwr["railway"~"^(station|halt)$"]["name"]{box};'
         f'nwr["leisure"~"^(park|stadium|sports_centre)$"]["name"]{box};'
         f'nwr["tourism"~"^(attraction|museum)$"]["name"]{box};'
         f'nwr["office"="government"]["name"]{box};'
         f'nwr["amenity"="bridge"]["name"]{box};'
         f'way["man_made"="bridge"]["name"]{box};'
         f');out center;')
    print(f"[poi] {scene} bbox={bbox}")
    data, last = None, None
    for url in OVERPASS_URLS:
        try:
            r = httpx.post(url, data={"data": q}, headers=HEADERS, timeout=240)
            r.raise_for_status()
            data = r.json(); break
        except Exception as ex:
            last = ex; print(f"[warn] {url}: {ex}")
    if data is None:
        raise last
    print(f"[poi] {len(data['elements'])} named elements")
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

def fetch_dem(scene: str, bbox: list) -> None:
    lat, lon = int(math.floor(bbox[1])), int(math.floor(bbox[0]))
    out = RAW / f"glo30_N{lat:02d}_E{lon:03d}.tif"
    if out.exists():
        print(f"[skip] {out} exists"); return
    url = DEM_URL.format(lat=lat, lon=lon)
    print(f"[dem] {url}")
    with httpx.stream("GET", url, timeout=600, headers=HEADERS) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    print(f"[dem] {out.stat().st_size/1e6:.1f} MB")

if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    scenes, _ = load_scenes()
    for scene, meta in scenes.items():
        fetch_osm(scene, meta["bbox"])
        fetch_poi(scene, meta["bbox"])
        fetch_dem(scene, meta["bbox"])
    lines = [f"{sha256(p)}  {p.name}" for p in sorted(RAW.iterdir()) if p.suffix in (".json", ".tif")]
    (RAW / "CHECKSUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("[ok] checksums written")
