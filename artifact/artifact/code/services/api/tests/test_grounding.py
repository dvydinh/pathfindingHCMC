"""F1-grounding: the assistant must resolve geography, never invent it.

These tests encode the failure mode the layer exists to prevent — a confident answer
about places nobody asked for — so they assert on *refusals* as much as on hits.
"""
import pytest
from conftest import needs_scenario

pytestmark = needs_scenario


@pytest.fixture(scope="module")
def sc():
    from app.engine import state
    return state.get("thuduc")


# ---------- gazetteer ----------

def test_landmarks_and_streets_are_built_from_osm():
    from app.engine import gazetteer
    gz = gazetteer.load("thuduc")
    assert not gz["missing"], "run scripts/build_gazetteer.py"
    assert len(gz["streets"]) > 500 and len(gz["landmarks"]) > 100
    assert all(e["source"] == "osm" for e in gz["streets"] + gz["landmarks"]), \
        "every entry must be sourced, never hand-entered from model memory"


@pytest.mark.parametrize("query,expected", [
    ("chợ Thủ Đức", "Chợ Thủ Đức"),
    ("cho thu duc", "Chợ Thủ Đức"),        # diacritics are optional, not required
    ("CHỢ THỦ ĐỨC", "Chợ Thủ Đức"),
    ("Kha Vạn Cân", "Kha Vạn Cân"),
    ("kha van can", "Kha Vạn Cân"),
    ("đường Võ Nguyên Giáp", "Võ Nguyên Giáp"),
    ("đường Kha Vạn Cân", "Kha Vạn Cân"),
])
def test_resolves_real_places(query, expected):
    from app.engine import gazetteer
    r = gazetteer.resolve("thuduc", query)
    assert r["candidates"], f"{query!r} resolved to nothing"
    assert r["candidates"][0]["name"] == expected


@pytest.mark.parametrize("query", [
    "chợ Bến Thành",        # District 1 — real place, wrong city area
    "phố Hàng Bạc Hà Nội",  # Hanoi
    "Hồ Gươm",              # Hanoi
    "asdkjhasd",            # nonsense
])
def test_refuses_places_outside_the_scene(query):
    """The dangerous outcome is not 'no answer', it is a *confident nearby* answer."""
    from app.engine import gazetteer
    r = gazetteer.resolve("thuduc", query)
    assert r["status"] == "not_found"
    assert r["candidates"] == [], f"{query!r} was offered a usable candidate"


def test_duplicate_names_report_ambiguity_rather_than_picking():
    from app.engine import gazetteer
    r = gazetteer.resolve("thuduc", "Khu phố 14")
    assert r["status"] == "ambiguous"
    assert len(r["candidates"]) > 1


def test_head_noun_variants_collapse_to_the_longest_road():
    """OSM holds both 'Võ Nguyên Giáp' (156 edges, 4 km arterial) and 'Đường Võ Nguyên
    Giáp' (2 edges, 239 m stub). Ranking on string match alone sends the natural
    Vietnamese phrasing to the stub, so the substantive road must win the merge."""
    from app.engine import gazetteer
    r = gazetteer.resolve("thuduc", "đường Võ Nguyên Giáp")
    assert r["status"] == "ok"
    top = r["candidates"][0]
    assert top["name"] == "Võ Nguyên Giáp" and top["n_edges"] > 100


@pytest.mark.parametrize("query,kind", [
    ("chợ Thủ Đức", "marketplace"),
    ("ga Thủ Đức", "station"),
    ("đường Tam Bình", "street"),
    ("phường Tam Bình", "suburb"),
])
def test_spoken_head_noun_selects_the_right_kind(query, kind):
    """OSM holds a station, a suburb, a street and a market all named "Thủ Đức" or
    "Tam Bình". The head noun the user actually says is the type signal that separates
    them, so it breaks the tie instead of forcing a clarification round-trip."""
    from app.engine import gazetteer
    r = gazetteer.resolve("thuduc", query)
    assert r["status"] == "ok"
    assert r["candidates"][0]["kind"] == kind


def test_a_bare_shared_name_still_asks():
    """Without a head noun there is no signal, and guessing would be the bug."""
    from app.engine import gazetteer
    assert gazetteer.resolve("thuduc", "Tam Bình")["status"] == "ambiguous"


def test_a_place_mentioned_inside_a_longer_phrase_is_not_the_answer():
    """Found by probing the live tool loop with a small model: asking for a café on a
    named street returned the street, an alley and a hospital as candidates *for the
    café*. An entry that merely appears inside a longer phrase is a suggestion, not an
    answer, unless it accounts for most of what was said."""
    from app.engine import gazetteer
    r = gazetteer.resolve("thuduc", "quán cà phê Sương Mai ở hẻm 12 đường Lê Văn Việt")
    assert r["status"] == "not_found"
    assert r["candidates"] == []
    assert r.get("did_you_mean"), "the user still deserves something to correct against"
    # the street itself, asked for plainly, must still resolve
    assert gazetteer.resolve("thuduc", "Lê Văn Việt")["status"] == "ok"


# ---------- snapping ----------

def test_snap_refuses_coordinates_far_from_any_road(sc):
    """Nearest-neighbour snapping never fails on its own: a Hanoi coordinate would
    otherwise return a Thủ Đức node and route confidently from the wrong place."""
    from app.engine import router
    node, dist = router.snap_checked(sc, 105.85, 21.03)      # Hoàn Kiếm, Hà Nội
    assert node is None and dist > 1_000_000


def test_snap_accepts_a_real_in_scene_place(sc):
    from app.engine import router, gazetteer
    p = gazetteer.resolve("thuduc", "chợ Thủ Đức")["candidates"][0]
    node, dist = router.snap_checked(sc, p["lon"], p["lat"])
    assert node is not None and dist <= router.SNAP_MAX_M


# ---------- narration ----------

def test_graph_carries_street_names(sc):
    named = sum(1 for n in sc.g.name if n)
    assert named > sc.g.n * 0.3, "street names missing — run scripts/build_gazetteer.py"


def test_route_narration_uses_real_graph_names(sc):
    from app.engine import router, narrate, gazetteer
    o = gazetteer.resolve("thuduc", "chợ Thủ Đức")["candidates"][0]
    d = gazetteer.resolve("thuduc", "đại học Nông Lâm")["candidates"][0]
    res = router.route(sc, "motorbike", (o["lon"], o["lat"]), (d["lon"], d["lat"]), 24)
    shown = res["recommended"] or res["dry"]
    seq = narrate.street_sequence(sc, shown["edges"], 24)
    assert seq, "route produced no narration"
    real = {n for n in sc.g.name if n} | {narrate.UNNAMED_VI}
    assert all(s["name"] in real for s in seq), "narration invented a street name"
    assert all(s["at_minute"] >= 0 for s in seq)


def test_street_state_is_driven_by_its_worst_segment(sc):
    """I2: an aggregate must never render safer than the parts it summarises."""
    from app.engine import gazetteer, narrate
    name, edge_ids = gazetteer.street_edges("thuduc", "Kha Vạn Cân")
    st = narrate.street_state(sc, edge_ids, name, 24, "motorbike")
    order = {"avoid": 0, "uncertain": 1, "unknown": 2, "low": 3}
    present = [b for b, n in st["segments_by_band"].items() if n]
    assert st["overall_band"] == min(present, key=lambda b: order[b])


def test_summaries_annotate_units_and_never_emit_negative_ages(sc):
    """A raw -1 sentinel would read to a model as an age, so it must surface as null."""
    from app.engine import narrate
    summary = narrate.area_summary(sc, 24, "motorbike")
    assert "units" in summary and summary["is_synthetic"] is True
    for s in summary["worst_streets"]:
        age = s.get("evidence_age_s")
        assert age is None or age >= 0
        if age is None:
            assert s.get("no_evidence_yet") is True


def test_area_summary_never_ships_geometry(sc):
    """25k edges must not reach a prompt; the digest is bounded and name-based."""
    from app.engine import narrate
    summary = narrate.area_summary(sc, 24, "motorbike")
    assert len(summary["worst_streets"]) <= 6
    assert "coords" not in repr(summary) and "geometry" not in repr(summary)


@needs_scenario
def test_worst_streets_ranks_water_not_vehicle_restrictions(sc):
    """A dry footbridge must not outrank a street under half a metre of water.

    pi is forced to 0 both by deep water and by "this vehicle may not use this edge"
    (passability.py:33). That collapse is correct for routing and wrong for a list titled
    "worst flooding": before this was filtered, "Cầu vượt Bộ hành Quốc lộ 1" — a footway
    with 5.6 cm on it and access_motorbike=0 — ranked above "Đường số 30" at 57.6 cm.
    """
    from app.engine import narrate
    g = sc.g
    summary = narrate.area_summary(sc, 22, "motorbike")
    worst = summary["worst_streets"]
    assert worst, "no worst streets at the storm peak"

    # every ranked street must have at least one segment this vehicle may actually use
    usable = {g.name[e] for e in range(g.n) if g.name[e] and g.access["motorbike"][e]}
    for s in worst:
        assert s["street"] in usable, \
            f"{s['street']!r} is ranked as flooded but no segment allows a motorbike"

    # the list is ordered by water, so the top entry must actually be deep
    assert worst[0]["depth_p50_cm"] > 20.0, \
        f"top 'worst flooded' street is only {worst[0]['depth_p50_cm']}cm deep"

    # the exclusion is reported, not silent
    assert summary["n_streets_excluded_no_access"] >= 1
    assert "ranking_note" in summary


@needs_scenario
def test_band_counts_still_describe_the_whole_network(sc):
    """Filtering the ranking must not quietly shrink the scene-wide band histogram.

    The counts answer a different question — how much of the network is in each band as
    the router sees it — and inaccessible edges belong in that answer.
    """
    from app.engine import narrate, passability
    summary = narrate.area_summary(sc, 22, "motorbike")
    st = passability.edge_states(sc, 22, "motorbike")
    assert sum(summary["segments_by_band"].values()) == sc.g.n == len(st["bands"])
