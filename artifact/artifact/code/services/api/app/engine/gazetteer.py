"""Place name -> coordinate lookup for the conversational layer (docs/AI_FEATURES.md).

The assistant is forbidden to emit coordinates of its own. Every origin, destination and
street it talks about is resolved here, against names built from OSM by
scripts/build_gazetteer.py. A query that does not match is *refused*, not guessed: the
failure mode this whole layer exists to prevent is a confident route between two places
the model invented.
"""
from __future__ import annotations
import difflib, functools, json, unicodedata
from ..deps import DATA

# Generic head nouns. "chợ Thủ Đức" must still match the entry "Chợ Thủ Đức", but
# "chợ" alone must not match every market, so these are stripped only for a secondary key.
HEAD_NOUNS = ("duong", "pho", "cho", "nga tu", "nga ba", "nga sau", "cau", "phuong",
              "quan", "khu pho", "ben xe", "ga", "truong dai hoc", "truong", "benh vien",
              "cong vien", "sieu thi", "chung cu", "khu cong nghiep", "khu che xuat")
# Two thresholds, deliberately. ACCEPT_SCORE is only cleared by a *structural* match —
# exact name, head-noun variant, prefix, or full token containment. A merely similar
# string ("chợ Bến Thành" vs "Trương Văn Thành") never becomes an answer, because a
# confident route between two places that are not the ones asked for is the exact
# failure this layer exists to prevent. Weaker hits come back as did_you_mean only.
ACCEPT_SCORE = 0.86
SUGGEST_SCORE = 0.62
CLOSE_MARGIN = 0.06       # top two within this margin -> ambiguous, ask the user


def norm(s: str) -> str:
    """Mirror of build_gazetteer.norm — diacritic-free lowercase key."""
    s = s.replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


def _strip_head(key: str) -> str:
    for h in sorted(HEAD_NOUNS, key=len, reverse=True):
        if key.startswith(h + " "):
            return key[len(h) + 1:]
    return key


@functools.lru_cache(maxsize=4)
def load(scene: str) -> dict:
    path = DATA / "derived" / f"{scene}_places.json"
    if not path.exists():
        return {"scene": scene, "bbox": None, "streets": [], "landmarks": [],
                "by_key": {}, "missing": True}
    gz = json.loads(path.read_text(encoding="utf-8"))
    by_key: dict[str, list] = {}
    for entry in gz["streets"] + gz["landmarks"]:
        by_key.setdefault(entry["key"], []).append(entry)
        stripped = _strip_head(entry["key"])
        if stripped != entry["key"]:
            by_key.setdefault(stripped, []).append(entry)
    gz["by_key"] = by_key
    gz["missing"] = False
    return gz


@functools.lru_cache(maxsize=4)
def edge_names(scene: str) -> dict:
    path = DATA / "derived" / f"{scene}_edge_names.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def name_of(scene: str, edge_id: str) -> str:
    """Street name for an edge, '' when the way is unnamed in OSM."""
    return edge_names(scene).get(edge_id.split("-")[0], "")


# Containment on a very short key matches almost anything ("b" inside "hang bac ha
# noi"), which is how an out-of-area query silently lands on a local road. Require a
# substantive overlap instead.
MIN_CONTAIN_LEN = 4

# The head noun a user says is itself a type signal: "ga Thủ Đức" and "chợ Thủ Đức" name
# different places that share a name. Used only to break ties between equally-scoring
# entries — never to raise a score, so it cannot rescue a weak match.
HEAD_KIND = {
    "ga": ("station", "halt"), "cho": ("marketplace",),
    "duong": ("street",), "pho": ("street",),
    "nga tu": ("street",), "nga ba": ("street",), "nga sau": ("street",),
    "cau": ("bridge",), "ben xe": ("bus_station",),
    "benh vien": ("hospital", "clinic"), "cong vien": ("park",),
    "sieu thi": ("supermarket", "mall", "department_store"),
    "truong dai hoc": ("university", "college"),
    "truong": ("school", "university", "college", "kindergarten"),
    "phuong": ("suburb", "quarter", "neighbourhood"),
    "khu pho": ("neighbourhood", "city_block"),
}


def _kind_hint(q: str) -> tuple:
    for h in sorted(HEAD_KIND, key=len, reverse=True):
        if q.startswith(h + " "):
            return HEAD_KIND[h]
    return ()


def _score(q: str, q_stripped: str, entry: dict) -> float:
    key = entry["key"]
    stripped = _strip_head(key)
    if q == key:
        return 1.0                      # full name matched — outranks a head-stripped hit
    if q_stripped == stripped:
        return 0.97
    best = 0.0
    for a in (q, q_stripped):
        for b in (key, stripped):
            if len(a) < MIN_CONTAIN_LEN or len(b) < MIN_CONTAIN_LEN:
                continue
            if b.startswith(a) or a.startswith(b):
                best = max(best, 0.93)
            elif a in b:
                best = max(best, 0.86)      # user said a shorter form of a longer name
            elif b in a:
                # The entry merely appears *somewhere inside* a longer phrase. For
                # "quán cà phê Sương Mai ở hẻm 12 đường Lê Văn Việt" that is true of the
                # street, the alley and a hospital on it — none of which is the café the
                # user asked about. Only treat it as an answer when the entry accounts
                # for most of what was said; otherwise it is a suggestion at best.
                covered = len(b.split()) / max(len(a.split()), 1)
                best = max(best, 0.86 if covered >= 0.5 else 0.80)
            best = max(best, difflib.SequenceMatcher(None, a, b).ratio())
    # Token containment catches "dai hoc nong lam" inside a long official name.
    qt, bt = set(q_stripped.split()), set(stripped.split())
    if qt and bt and qt <= bt:
        best = max(best, 0.90)
    return best


def resolve(scene: str, query: str, limit: int = 5, kinds: tuple | None = None) -> dict:
    """Rank gazetteer entries against a free-text place name.

    Returns {status, candidates[]}. status is 'ok' (one clear winner), 'ambiguous'
    (several plausible — the caller must ask, never pick) or 'not_found'.
    """
    gz = load(scene)
    if gz["missing"]:
        return {"status": "not_found", "reason": "gazetteer_not_built", "candidates": []}
    q = norm(query)
    if not q:
        return {"status": "not_found", "reason": "empty_query", "candidates": []}
    q_stripped = _strip_head(q)
    hint = _kind_hint(q)

    pool = gz["streets"] + gz["landmarks"]
    if kinds:
        pool = [e for e in pool if e["kind"] in kinds]

    scored = []
    for e in pool:
        s = _score(q, q_stripped, e)
        if s >= SUGGEST_SCORE:
            scored.append((s, e))
    if not scored:
        return {"status": "not_found", "reason": "no_match", "candidates": []}

    # Prefer a longer street (more edges) when scores tie; it is the more likely referent.
    scored.sort(key=lambda t: (-t[0], 0 if t[1]["kind"] in hint else 1,
                               -t[1].get("n_edges", 0), len(t[1]["name"])))
    # OSM carries the same road as both "Kha Vạn Cân" and "Đường Kha Vạn Cân". Those are
    # one place, not a genuine ambiguity, so collapse same-kind head-noun variants.
    # The survivor is the *longest* variant, not the best-matching string: in Thủ Đức
    # "Đường Võ Nguyên Giáp" is a 2-edge stub while "Võ Nguyên Giáp" is the 4 km
    # arterial, so scoring alone would send the natural Vietnamese phrasing to a
    # 239 m fragment. The group keeps the best score of any of its members.
    groups: dict = {}
    for s_, e in scored:
        sig = (_strip_head(e["key"]), e["kind"])
        cur = groups.get(sig)
        if cur is None:
            groups[sig] = [s_, e]
        else:
            cur[0] = max(cur[0], s_)
            if e.get("n_edges", 0) > cur[1].get("n_edges", 0):
                cur[1] = e
    deduped = sorted(([s_, e] for s_, e in groups.values()),
                     key=lambda t: (-t[0], 0 if t[1]["kind"] in hint else 1,
                                    -t[1].get("n_edges", 0), len(t[1]["name"])))
    accepted = [t for t in deduped if t[0] >= ACCEPT_SCORE]
    if not accepted:
        # Similar-looking but not actually this place. Offer names to ask about; the
        # caller is told never to route to a did_you_mean entry on its own.
        return {"status": "not_found", "reason": "low_confidence", "candidates": [],
                "did_you_mean": [e["name"] for _, e in deduped[:limit]]}
    top = accepted[:limit]
    cands = [{
        "name": e["name"], "kind": e["kind"], "kind_vi": e["kind_vi"],
        "lon": e["lon"], "lat": e["lat"], "match_score": round(s, 3),
        "source": e["source"],
        **({"n_edges": e["n_edges"], "extent_m": e["extent_m"]} if e["kind"] == "street" else {}),
        **({"spans_wide_area": True} if e.get("ambiguous") else {}),
    } for s, e in top]

    # Exactness outranks proximity. "chợ Thủ Đức" matches the entry "Chợ Thủ Đức" in
    # full (1.0) while the station "Thủ Đức" only matches after the head noun is stripped
    # (0.97) — close in score, but not close in kind of evidence. Treating that as a tie
    # turns the clearest possible query into a clarification prompt. A genuine tie between
    # two *exact* matches, or a name the gazetteer already flagged as duplicated, still
    # comes back ambiguous.
    exact = [t for t in top if t[0] >= 1.0]
    # The hint only has to separate the candidates that are actually tied with the
    # leader: "đường Tam Bình" also matches several alleys off Tam Bình, and those are
    # streets too, but they score lower and were never the ambiguity.
    tied = [t for t in top if abs(t[0] - top[0][0]) < CLOSE_MARGIN]
    hinted = [t for t in tied if t[1]["kind"] in hint] if hint else []
    status = "ok"
    if len(hinted) == 1 and hinted[0] is top[0]:
        status = "ok"                       # the spoken head noun settled it
    elif len(exact) > 1:
        status = "ambiguous"
    elif not exact and len(top) > 1 and top[0][0] - top[1][0] < CLOSE_MARGIN:
        status = "ambiguous"
    elif top[0][1].get("ambiguous") and top[0][1]["kind"] != "street":
        status = "ambiguous"
    return {"status": status, "candidates": cands}


def street_edges(scene: str, name: str) -> tuple[str, list] | None:
    """Exact-ish street lookup -> (canonical name, edge_ids). None when unmatched."""
    gz = load(scene)
    if gz["missing"]:
        return None
    r = resolve(scene, name, limit=1, kinds=("street",))
    if not r["candidates"]:
        return None
    want = norm(r["candidates"][0]["name"])
    for e in gz["streets"]:
        if e["key"] == want:
            return e["name"], e["edge_ids"]
    return None
