"""
Load campus graph from CSVs into NetworkX for routing/analysis.

Usage:
  python graph_loader.py
"""

import csv
from pathlib import Path
from typing import Tuple

import networkx as nx

DATA_DIR = Path("data")
NODES_CSV = DATA_DIR / "nodes.csv"
EDGES_CSV = DATA_DIR / "edges.csv"


def load_graph() -> nx.Graph:
    G = nx.Graph()

    # Load nodes
    with NODES_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            node_id = row["id"]
            G.add_node(
                node_id,
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                label=row.get("label", ""),
            )

    # Load edges
    with EDGES_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            edge_id = row["id"]
            u, v = row["source"], row["target"]
            length = float(row["length_m"])
            capacity = float(row["capacity"])
            kind = row.get("kind", "path")
            G.add_edge(
                u,
                v,
                id=edge_id,
                length_m=length,
                capacity=capacity,
                kind=kind,
                weight=length,  # initial weight = distance; later add congestion penalty
            )
    return G


def describe_graph(G: nx.Graph) -> Tuple[int, int, bool]:
    n_nodes = G.number_of_nodes()
    n_edges = G.number_of_edges()
    connected = nx.is_connected(G) if n_nodes > 0 else False
    return n_nodes, n_edges, connected


if __name__ == "__main__":
    graph = load_graph()
    n_nodes, n_edges, connected = describe_graph(graph)
    print(f"Nodes: {n_nodes}, Edges: {n_edges}, Connected: {connected}")
