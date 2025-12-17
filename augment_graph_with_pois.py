"""
Augment the path graph by adding POI nodes (from giki_map.geojson Point features)
and connecting each to its nearest existing node within a radius.
"""

import csv
import json
import math
from pathlib import Path

DATA_DIR = Path("data")
NODES_CSV = DATA_DIR / "nodes.csv"
EDGES_CSV = DATA_DIR / "edges.csv"
GEOJSON_POI = Path("giki_map.geojson")

R = 6371000  # Earth radius meters


def hav(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_nodes():
    nodes = []
    with NODES_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nodes.append(row)
    return nodes


def load_edges():
    edges = []
    with EDGES_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            edges.append(row)
    return edges


def load_pois():
    gj = json.load(GEOJSON_POI.open(encoding="utf-8"))
    pois = []
    for feat in gj.get("features", []):
        geom = feat.get("geometry", {})
        if geom.get("type") != "Point":
            continue
        lon, lat = geom.get("coordinates", [None, None])
        if lon is None or lat is None:
            continue
        label = feat.get("properties", {}).get("building_name")
        if not label:
            continue
        pois.append({"label": label, "lat": lat, "lon": lon})
    return pois


def main():
    nodes = load_nodes()
    edges = load_edges()
    pois = load_pois()

    node_index = {n["id"]: n for n in nodes}
    # Build simple list for nearest search
    node_list = [(n["id"], float(n["lat"]), float(n["lon"])) for n in nodes]

    next_node_id = 1 + max(int(n["id"][1:]) for n in nodes if n["id"].startswith("n"))
    next_edge_id = 1 + max(int(e["id"][1:]) for e in edges if e["id"].startswith("e"))

    added = 0
    for poi in pois:
        # find nearest existing nodes (up to 2) within a larger radius
        nearest = []
        for nid, lat, lon in node_list:
            d = hav(poi["lat"], poi["lon"], lat, lon)
            nearest.append((d, nid, lat, lon))
        nearest.sort(key=lambda x: x[0])
        nearest = [n for n in nearest[:2] if n[0] <= 400]  # up to 400m
        if not nearest:
            continue

        new_id = f"p{next_node_id}"
        next_node_id += 1
        nodes.append(
            {
                "id": new_id,
                "lat": poi["lat"],
                "lon": poi["lon"],
                "label": poi["label"],
            }
        )
        node_list.append((new_id, poi["lat"], poi["lon"]))
        node_index[new_id] = nodes[-1]

        for d, tgt, _, _ in nearest:
            edges.append(
                {
                    "id": f"e{next_edge_id}",
                    "source": new_id,
                    "target": tgt,
                    "length_m": round(d, 1),
                    "capacity": 300,
                    "kind": "path",
                }
            )
            next_edge_id += 1
        added += 1

    # write back
    with NODES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "lat", "lon", "label"])
        writer.writeheader()
        writer.writerows(nodes)
    with EDGES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id", "source", "target", "length_m", "capacity", "kind"]
        )
        writer.writeheader()
        writer.writerows(edges)

    print(f"Added {added} POI nodes/connectors. Total nodes={len(nodes)}, edges={len(edges)}")


if __name__ == "__main__":
    main()
