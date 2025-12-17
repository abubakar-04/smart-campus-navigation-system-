"""
Rebuild the graph using giki_path.geojson (roads/paths) and giki_map.geojson POIs.

Outputs:
- data/nodes.csv : path vertices (n*) + POIs (p*)
- data/edges.csv : path segment edges + POI connectors to nearest path node
"""

import csv
import json
import math
from pathlib import Path
from collections import OrderedDict

PATH_GJ = Path("giki_path.geojson")
POI_GJ = Path("giki_map.geojson")
NODES_CSV = Path("data/nodes.csv")
EDGES_CSV = Path("data/edges.csv")

R = 6371000  # meters


def hav(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_paths():
    gj = json.load(PATH_GJ.open(encoding="utf-8"))
    return [
        f
        for f in gj.get("features", [])
        if f.get("geometry", {}).get("type") == "LineString"
    ]


def load_pois():
    gj = json.load(POI_GJ.open(encoding="utf-8"))
    pois = []
    for feat in gj.get("features", []):
        geom = feat.get("geometry", {})
        if geom.get("type") != "Point":
            continue
        lon, lat = geom.get("coordinates", [None, None])
        name = feat.get("properties", {}).get("building_name")
        if lon is None or lat is None or not name:
            continue
        pois.append({"lat": lat, "lon": lon, "label": name})
    return pois


def kind_and_capacity(highway: str):
    road_tags = {"service", "residential", "unclassified", "road"}
    path_tags = {"footway", "path", "cycleway", "track"}
    if highway in road_tags:
        return "road", 600
    if highway in path_tags:
        return "path", 400
    return "path", 400


def build_graph():
    precision = 6  # coordinate rounding for node dedup
    path_features = load_paths()
    pois = load_pois()

    nodes = OrderedDict()
    edges = []

    # Build path vertices as nodes
    next_node_id = 1
    coord_to_id = {}
    for feat in path_features:
        coords = feat["geometry"]["coordinates"]
        for lon, lat in coords:
            key = (round(lat, precision), round(lon, precision))
            if key not in coord_to_id:
                nid = f"n{next_node_id}"
                coord_to_id[key] = nid
                nodes[nid] = {"id": nid, "lat": lat, "lon": lon, "label": f"Node {next_node_id}"}
                next_node_id += 1

    # Build path edges
    next_edge_id = 1
    for feat in path_features:
        coords = feat["geometry"]["coordinates"]
        props = feat.get("properties", {})
        highway = props.get("highway", "path")
        kind, cap = kind_and_capacity(highway)
        for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
            key1 = (round(lat1, precision), round(lon1, precision))
            key2 = (round(lat2, precision), round(lon2, precision))
            u = coord_to_id.get(key1)
            v = coord_to_id.get(key2)
            if not u or not v or u == v:
                continue
            length = round(hav(lat1, lon1, lat2, lon2), 1)
            if length <= 0:
                continue
            edges.append(
                {
                    "id": f"e{next_edge_id}",
                    "source": u,
                    "target": v,
                    "length_m": length,
                    "capacity": cap,
                    "kind": kind,
                }
            )
            next_edge_id += 1

    # Snap POIs to nearest path node
    path_nodes_list = [
        (nid, float(n["lat"]), float(n["lon"])) for nid, n in nodes.items()
    ]
    snap_threshold = 200.0  # meters
    for idx, poi in enumerate(pois, start=1):
        nearest = []
        for nid, lat, lon in path_nodes_list:
            d = hav(poi["lat"], poi["lon"], lat, lon)
            nearest.append((d, nid))
        nearest.sort(key=lambda x: x[0])
        nearest = [pair for pair in nearest if pair[0] <= snap_threshold][:2]
        if not nearest:
            continue
        pid = f"p{idx}"
        nodes[pid] = {"id": pid, "lat": poi["lat"], "lon": poi["lon"], "label": poi["label"]}
        for d, nid in nearest:
            edges.append(
                {
                    "id": f"e{next_edge_id}",
                    "source": pid,
                    "target": nid,
                    "length_m": round(d, 1),
                    "capacity": 300,
                    "kind": "path",
                }
            )
            next_edge_id += 1

    # Write CSVs
    with NODES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "lat", "lon", "label"])
        writer.writeheader()
        writer.writerows(nodes.values())
    with EDGES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id", "source", "target", "length_m", "capacity", "kind"]
        )
        writer.writeheader()
        writer.writerows(edges)

    print(f"Built graph: nodes={len(nodes)}, edges={len(edges)}")


if __name__ == "__main__":
    build_graph()
