import os, pathlib, sys
sys.path.insert(0, "/srv")
import pytest

DATA = pathlib.Path(os.environ.get("DATA_DIR", "/data"))

def scenario_ready() -> bool:
    return (DATA / "scenarios" / "thuduc_meta.json").exists()

needs_scenario = pytest.mark.skipif(not scenario_ready(), reason="storm scenario not computed")


def needs_feature(flag: str):
    """Skip a test whose feature is switched off in app.main.DEMO_FEATURES.

    De-scoping the demo must not look like a broken test suite, and it must not tempt
    anyone to delete the test either: the code behind the flag is still there and still
    expected to work when the flag is on. So the gate is read from the same dict the app
    mounts from, and flipping the flag back on re-arms the test with no edit here.
    """
    from app.main import FEATURES
    return pytest.mark.skipif(
        not FEATURES.get(flag, False),
        reason=f"DEMO_FEATURES[{flag!r}] is off — de-scoped from the demo, code retained")
