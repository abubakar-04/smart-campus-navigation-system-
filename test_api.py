"""
Minimal sanity checks for backend endpoints using Flask test client.

Run: python test_api.py
"""

from app import app


def run_sanity():
    client = app.test_client()

    # graph
    g = client.get("/graph")
    assert g.status_code == 200, f"/graph failed: {g.status_code}"
    data = g.get_json()
    assert "nodes" in data and "edges" in data, "graph payload missing keys"

    # forecast
    f = client.get("/forecast?hour=9&day_of_week=1&is_peak=1")
    assert f.status_code == 200, f"/forecast failed: {f.status_code}"
    forecast = f.get_json()
    assert isinstance(forecast, list) and len(forecast) > 0, "empty forecast"

    # route using first two nodes (if available)
    if data["nodes"]:
        src = data["nodes"][0]["id"]
        tgt = data["nodes"][-1]["id"]
        r = client.get(f"/route?source={src}&target={tgt}")
        assert r.status_code in (200, 404, 400), f"/route unexpected status {r.status_code}"

    print("Sanity checks passed.")


if __name__ == "__main__":
    run_sanity()
