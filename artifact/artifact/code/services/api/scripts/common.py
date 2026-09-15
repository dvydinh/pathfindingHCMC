"""Shared helpers for data-pipeline scripts (run inside the api container)."""
import os, json, hashlib, math, pathlib
import yaml

DATA = pathlib.Path(os.environ.get("DATA_DIR", "/data"))
CONFIG = pathlib.Path(os.environ.get("CONFIG_DIR", "/config"))
RAW, DERIVED = DATA / "raw", DATA / "derived"

def load_scenes() -> dict:
    cfg = yaml.safe_load((CONFIG / "bbox.yaml").read_text(encoding="utf-8"))
    return cfg["scenes"], cfg["default_scene"]

def scene_name() -> str:
    scenes, default = load_scenes()
    s = os.environ.get("SCENE", default)
    if s not in scenes:
        raise SystemExit(f"unknown scene {s!r}; known: {list(scenes)}")
    return s

def haversine_m(lon1, lat1, lon2, lat2) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
