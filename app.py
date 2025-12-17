from pathlib import Path
from typing import Dict, List

import joblib
import networkx as nx
import numpy as np
import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS
from networkx.algorithms.shortest_paths.astar import astar_path
from networkx.algorithms.simple_paths import shortest_simple_paths
from waitress import serve

DATA_DIR = Path("data")
MODELS_DIR = Path("models")
NODES_CSV = DATA_DIR / "nodes.csv"
EDGES_CSV = DATA_DIR / "edges.csv"
MODEL_PATH = MODELS_DIR / "rf_flow.pkl"

FEATURES = [
    "hour",
    "day_of_week",
    "is_peak",
    "capacity",
    "length_m",
    "flow_lag1",
    "flow_lag2",
]

app = Flask(__name__)
CORS(app)


def load_graph() -> nx.Graph:
    G = nx.Graph()
    nodes_df = pd.read_csv(NODES_CSV)
    edges_df = pd.read_csv(EDGES_CSV)
    for _, row in nodes_df.iterrows():
        G.add_node(
            row["id"],
            lat=row["lat"],
            lon=row["lon"],
            label=row["label"],
        )
    for _, row in edges_df.iterrows():
        G.add_edge(
            row["source"],
            row["target"],
            id=row["id"],
            length_m=row["length_m"],
            capacity=row["capacity"],
            kind=row["kind"],
            weight=row["length_m"],  # base weight = distance
        )
    return G


def load_model():
    return joblib.load(MODEL_PATH)


GRAPH = load_graph()
MODEL = load_model()
FORECAST_CACHE: Dict[tuple, List[Dict]] = {}


def travel_time_minutes(length_m: float, speed_mps: float = 1.3) -> float:
    """Rough walking time in minutes for a given edge length."""
    return length_m / speed_mps / 60.0


def predict_forecast(hour: float, day_of_week: int, is_peak: int) -> List[Dict]:
    rows = []
    for u, v, data in GRAPH.edges(data=True):
        cap = data.get("capacity", 400)
        length_m = data.get("length_m", 100)
        # Default lag placeholders; real lag would come from time-series
        flow_lag1 = 0.1 * cap
        flow_lag2 = 0.1 * cap
        rows.append(
            {
                "edge_id": data["id"],
                "hour": hour,
                "day_of_week": day_of_week,
                "is_peak": is_peak,
                "capacity": cap,
                "length_m": length_m,
                "flow_lag1": flow_lag1,
                "flow_lag2": flow_lag2,
            }
        )
    df = pd.DataFrame(rows)
    X = df[FEATURES]
    preds = MODEL.predict(X)
    df["pred_flow"] = preds
    out = df[["edge_id", "pred_flow", "capacity"]].to_dict(orient="records")
    return out


def congestion_penalty(edge_id: str) -> float:
    forecast_map = getattr(app, "forecast_map", {})
    f = forecast_map.get(edge_id)
    if not f:
        return 0.0
    ratio = f["pred_flow"] / max(f["capacity"], 1)
    if ratio < 0.5:
        return 0.0
    if ratio < 0.8:
        return 0.3
    return 0.7


def astar_with_congestion(source: str, target: str) -> List[str]:
    def heuristic(u, v):
        return 0

    def cost(u, v, data):
        base = data.get("length_m", 1.0)
        pen = congestion_penalty(data.get("id"))
        return base * (1 + pen)

    return astar_path(GRAPH, source, target, heuristic=heuristic, weight=cost)


def astar_distance_only(source: str, target: str) -> List[str]:
    def heuristic(u, v):
        return 0

    def cost(u, v, data):
        return data.get("length_m", 1.0)

    return astar_path(GRAPH, source, target, heuristic=heuristic, weight=cost)


def path_length(path: List[str]) -> float:
    total = 0.0
    for u, v in zip(path, path[1:]):
        data = GRAPH.get_edge_data(u, v) or {}
        total += float(data.get("length_m", 0.0))
    return total


def build_penalized_graph() -> nx.Graph:
    """Create a copy of the graph with congestion-penalized weights."""
    Gp = GRAPH.copy()
    for u, v, data in Gp.edges(data=True):
        pen = congestion_penalty(data.get("id"))
        base = float(data.get("length_m", 1.0))
        data["pen_weight"] = base * (1 + pen)
    return Gp


def k_shortest_paths(
    G: nx.Graph, source: str, target: str, weight: str, k: int = 3
) -> List[List[str]]:
    """Return up to k shortest simple paths by given weight."""
    paths = []
    for path in shortest_simple_paths(G, source, target, weight=weight):
        paths.append(path)
        if len(paths) >= k:
            break
    return paths


@app.route("/graph")
def get_graph():
    nodes = []
    for node_id, data in GRAPH.nodes(data=True):
        nodes.append(
            {
                "id": node_id,
                "lat": data.get("lat"),
                "lon": data.get("lon"),
                "label": data.get("label"),
            }
        )
    edges = []
    for u, v, data in GRAPH.edges(data=True):
        edges.append(
            {
                "id": data.get("id"),
                "source": u,
                "target": v,
                "length_m": data.get("length_m"),
                "capacity": data.get("capacity"),
                "kind": data.get("kind"),
            }
        )
    return jsonify({"nodes": nodes, "edges": edges})


@app.route("/forecast", methods=["GET"])
def forecast():
    try:
        hour = float(request.args.get("hour", 9))
        day_of_week = int(request.args.get("day_of_week", 1))
        is_peak = int(request.args.get("is_peak", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid hour/day_of_week/is_peak"}), 400

    key = (hour, day_of_week, is_peak)
    use_cache = request.args.get("use_cache", "true").lower() != "false"
    if use_cache and key in FORECAST_CACHE:
        result = FORECAST_CACHE[key]
    else:
        result = predict_forecast(hour, day_of_week, is_peak)
        FORECAST_CACHE[key] = result
    app.forecast_map = {r["edge_id"]: r for r in result}
    return jsonify(result)


@app.route("/route", methods=["GET"])
def route():
    source = request.args.get("source")
    target = request.args.get("target")
    mode = request.args.get("mode", "both")
    k = int(request.args.get("k", 3))
    if not source or not target:
        return jsonify({"error": "source and target are required"}), 400
    if source not in GRAPH or target not in GRAPH:
        return jsonify({"error": "invalid source/target"}), 400
    if not getattr(app, "forecast_map", None):
        return jsonify({"error": "forecast not loaded; call /forecast first"}), 400
    out = {}
    try:
        if mode in ("both", "penalized"):
            # Primary congestion-aware path
            best = astar_with_congestion(source, target)
            Gp = build_penalized_graph()
            alt_paths = k_shortest_paths(Gp, source, target, "pen_weight", k)
            out["best"] = {
                "path": best,
                "len_m": path_length(best),
                "coords": [
                    {
                        "id": n,
                        "lat": GRAPH.nodes[n]["lat"],
                        "lon": GRAPH.nodes[n]["lon"],
                        "label": GRAPH.nodes[n]["label"],
                    }
                    for n in best
                ],
            }
            out["best_alts"] = [
                {
                    "path": p,
                    "len_m": path_length(p),
                    "coords": [
                        {
                            "id": n,
                            "lat": GRAPH.nodes[n]["lat"],
                            "lon": GRAPH.nodes[n]["lon"],
                            "label": GRAPH.nodes[n]["label"],
                        }
                        for n in p
                    ],
                }
                for p in alt_paths
            ]
        if mode in ("both", "distance"):
            shortest = astar_distance_only(source, target)
            alt_d = k_shortest_paths(GRAPH, source, target, "weight", k)
            out["shortest"] = {
                "path": shortest,
                "len_m": path_length(shortest),
                "coords": [
                    {
                        "id": n,
                        "lat": GRAPH.nodes[n]["lat"],
                        "lon": GRAPH.nodes[n]["lon"],
                        "label": GRAPH.nodes[n]["label"],
                    }
                    for n in shortest
                ],
            }
            out["shortest_alts"] = [
                {
                    "path": p,
                    "len_m": path_length(p),
                    "coords": [
                        {
                            "id": n,
                            "lat": GRAPH.nodes[n]["lat"],
                            "lon": GRAPH.nodes[n]["lon"],
                            "label": GRAPH.nodes[n]["label"],
                        }
                        for n in p
                    ],
                }
                for p in alt_d
            ]
    except nx.NetworkXNoPath:
        return jsonify({"error": "no path"}), 404
    if not out:
        return jsonify({"error": "no path"}), 404
    return jsonify(out)


if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=5000)
