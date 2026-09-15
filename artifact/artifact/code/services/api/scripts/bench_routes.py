"""G3.5 / G8.5 latency bench: p95 of POST /v1/routes over 200 random OD pairs."""
import sys, time
import numpy as np
sys.path.insert(0, "/srv")
from fastapi.testclient import TestClient
from app.main import app
from app.engine import state

def main():
    sc = state.get("thuduc")
    c = TestClient(app)
    g = sc.g
    lon = np.array([x[0][0] for x in g.coords]); lat = np.array([x[0][1] for x in g.coords])
    rng = np.random.default_rng(0)
    # warm caches across the tick range first (server warms the same way at boot)
    from app.engine import router as eng_router
    eng_router._snap_index(sc)
    for t in range(sc.T):
        eng_router._tick_layer(sc, "motorbike", t)
        c.get("/v1/state", params={"at": t, "vehicle": "motorbike"})
    times = []
    for k in range(200):
        i, j = rng.integers(0, g.n, 2)
        t0 = time.time()
        r = c.post("/v1/routes", json={
            "origin": [float(lon[i]), float(lat[i])],
            "destination": [float(lon[j]), float(lat[j])],
            "depart_tick": int(rng.choice([10, 14, 18, 22, 26])),
            "vehicle": "motorbike"})
        assert r.status_code == 200, r.text
        times.append(time.time() - t0)
    times = np.array(times)
    print(f"n=200 p50={np.percentile(times,50)*1000:.0f}ms "
          f"p95={np.percentile(times,95)*1000:.0f}ms max={times.max()*1000:.0f}ms")
    assert np.percentile(times, 95) < 2.0, "G3.5 FAIL: p95 >= 2s"
    print("G3.5 PASS")

if __name__ == "__main__":
    main()
