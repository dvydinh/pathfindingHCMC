"""OSM JSON -> directed edge graph with attributes (PLAN.md §3.2).
Splits ways at intersections, chunks long segments to ~<250 m for edge-level flood state."""
import json
from common import RAW, DERIVED, haversine_m, load_scenes, scene_name

# class -> (default width m, free-flow speed km/h, car allowed, motorbike allowed)
CLASS = {
    "motorway": (14, 80, True, False), "trunk": (12, 60, True, True),
    "primary": (10, 45, True, True), "secondary": (8, 40, True, True),
    "tertiary": (7, 35, True, True), "unclassified": (5.5, 30, True, True),
    "residential": (5, 25, True, True), "living_street": (4, 15, True, True),
    "service": (4, 15, True, True), "path": (2, 10, False, True),
    "track": (3, 15, False, True), "footway": (2, 8, False, False),
    "cycleway": (2.5, 12, False, True),
}
MAX_SEG_M = 250.0

def base_class(hw: str) -> str:
    return hw[:-5] if hw.endswith("_link") else hw

def chunk(coords, node_ids):
    """Split a node-to-node polyline into chunks <= MAX_SEG_M."""
    segs, cur, cur_len = [], [coords[0]], 0.0
    for a, b in zip(coords, coords[1:]):
        d = haversine_m(*a, *b)
        if cur_len + d > MAX_SEG_M and len(cur) > 1:
            segs.append(cur); cur = [cur[-1]]; cur_len = 0.0
        cur.append(b); cur_len += d
    if len(cur) > 1:
        segs.append(cur)
    return segs

def main() -> None:
    scene = scene_name()
    scenes, _ = load_scenes()
    data = json.loads((RAW / f"{scene}.osm.json").read_text(encoding="utf-8"))
    nodes = {el["id"]: (el["lon"], el["lat"]) for el in data["elements"] if el["type"] == "node"}
    ways = [el for el in data["elements"] if el["type"] == "way"]

    use = {}
    for w in ways:
        nds = [n for n in w["nodes"] if n in nodes]
        for n in nds:
            use[n] = use.get(n, 0) + 1
        if nds:
            use[nds[0]] += 1; use[nds[-1]] += 1  # endpoints always split points

    edges, next_node_id = [], [max(nodes) + 1]
    def synth_node(coord):
        nid = next_node_id[0]; next_node_id[0] += 1
        nodes[nid] = coord
        return nid

    for w in ways:
        tags = w.get("tags", {})
        hw = base_class(tags.get("highway", ""))
        if hw not in CLASS:
            continue
        width_d, speed, car, moto = CLASS[hw]
        try:
            width = float(str(tags.get("width", width_d)).split(";")[0].replace("m", ""))
        except ValueError:
            width = width_d
        surface = tags.get("surface", "asphalt" if hw not in ("path", "track") else "unknown")
        oneway = tags.get("oneway", "no") in ("yes", "1", "true") or hw == "motorway"
        has_tags = int("width" in tags) + int("surface" in tags)

        nds = [n for n in w["nodes"] if n in nodes]
        if len(nds) < 2:
            continue
        # split at intersections
        parts, cur = [], [nds[0]]
        for n in nds[1:]:
            cur.append(n)
            if use.get(n, 0) > 1 and n != nds[-1]:
                parts.append(cur); cur = [n]
        if len(cur) > 1:
            parts.append(cur)

        seg_i = 0
        for part in parts:
            coords = [nodes[n] for n in part]
            for ck in chunk(coords, part):
                u = part[0] if ck[0] == coords[0] else synth_node(ck[0])
                v = part[-1] if ck[-1] == coords[-1] else synth_node(ck[-1])
                length = sum(haversine_m(*a, *b) for a, b in zip(ck, ck[1:]))
                if length < 5:
                    continue
                base = {
                    "way_id": w["id"], "road_class": hw, "length_m": round(length, 1),
                    "width_m": width, "surface": surface, "oneway": oneway,
                    "speed_kmh": speed, "access_car": car, "access_motorbike": moto,
                    "access_response": True, "tag_quality": has_tags,
                    "coords": [[round(c[0], 7), round(c[1], 7)] for c in ck],
                }
                edges.append({"edge_id": f"{w['id']}-{seg_i}-f", "u": u, "v": v, **base})
                if not oneway:
                    edges.append({"edge_id": f"{w['id']}-{seg_i}-b", "u": v, "v": u,
                                  **{**base, "coords": base["coords"][::-1]}})
                seg_i += 1

    DERIVED.mkdir(parents=True, exist_ok=True)
    out = DERIVED / f"{scene}_edges.json"
    out.write_text(json.dumps(edges), encoding="utf-8")
    n_alley = sum(1 for e in edges if e["road_class"] in ("residential", "living_street", "service", "path"))
    print(f"[ok] {scene}: {len(edges)} directed edges ({n_alley} alley-class), {len(nodes)} nodes -> {out}")

if __name__ == "__main__":
    main()
