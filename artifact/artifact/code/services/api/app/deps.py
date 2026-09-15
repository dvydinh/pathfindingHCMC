import os, pathlib, functools
import psycopg
import yaml

DATA = pathlib.Path(os.environ.get("DATA_DIR", "/data"))
CONFIG = pathlib.Path(os.environ.get("CONFIG_DIR", "/config"))

def db() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"])

@functools.lru_cache
def scenes() -> dict:
    return yaml.safe_load((CONFIG / "bbox.yaml").read_text(encoding="utf-8"))["scenes"]

def default_scene() -> str:
    return yaml.safe_load((CONFIG / "bbox.yaml").read_text(encoding="utf-8"))["default_scene"]
