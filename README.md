# Smart Campus Navigation System

Backend (Flask + NetworkX + scikit-learn) with a Vite + Leaflet frontend for congestion-aware campus routing. The backend builds required models on first run so a new machine can start with minimal setup.

## Prerequisites
- Python 3.10+ with pip
- Node 18+ and npm (for the frontend dev server)
- Recommended: create and activate a Python virtual environment

## Install dependencies
```bash
pip install flask flask-cors waitress numpy pandas networkx scikit-learn joblib
npm install
```

## First run (backend)
```bash
python app.py
```
What happens on first startup:
- Loads graph data from `data/nodes.csv` and `data/edges.csv`.
- If `models/rf_flow.pkl` (RandomForest) is missing, it trains it automatically. If the flow splits are missing, it first synthesizes them via `generate_synthetic_flows.py`. The trained RF model is saved to `models/rf_flow.pkl` (~3.3 GB).
- Ensures the baseline linear model exists at `models/linear_flow.pkl`.
- Serves the API on port 5000 via waitress.

## First run (frontend)
In a second terminal:
```bash
npm run dev
```
Vite will start a dev server (default port 5173) and the app will call the backend at `http://localhost:5000`.

## API quickstart
- `GET /graph` — nodes and edges of the campus graph.
- `GET /forecast?hour=9&day_of_week=1&is_peak=1` — generates (or reuses cached) forecast and stores it in-memory for routing penalties.
- `GET /route?source=<node_id>&target=<node_id>&mode=both|penalized|distance&k=3` — returns routes; requires `/forecast` to be called first.

## Useful scripts
- `python generate_synthetic_flows.py` — rebuild synthetic flow dataset and splits in `data/`.
- `python train_rf_model.py` — train the RandomForest model manually.
- `python train_linear_model.py` — train the baseline linear model manually.
- `python test_api.py` — lightweight sanity checks against the running app.

## Project layout
- `app.py` — Flask API, routing/forecast logic, first-run model bootstrap.
- `data/` — graph CSVs, flow splits, metrics, forecast example.
- `models/` — trained model artifacts (created on first run if missing).
- `src/` — frontend code (`main.js`, `style.css`).
- `giki_map.geojson`, `giki_path.geojson` — source GeoJSONs for graph building.
- `build_graph_from_paths.py`, `augment_graph_with_pois.py` — utilities to regenerate graph CSVs.

## Notes
- First model build can take a few minutes and uses several GB of disk for `rf_flow.pkl`.
- Forecast results are cached in memory per `(hour, day_of_week, is_peak)` to speed up routing calls.
