import "leaflet/dist/leaflet.css";
import L from "leaflet";
import axios from "axios";
import "./style.css";

const API_BASE = `${window.location.protocol}//${window.location.hostname}:5000`;

const root = document.querySelector("#app");

root.innerHTML = `
  <main class="page">
    <header class="hero">
      <h1>Smart Campus Navigation</h1>
      <p>Rendering GIKI campus from local GeoJSON.</p>
    </header>
    <section class="controls">
      <div class="control">
        <label for="start">Start</label>
        <select id="start"></select>
      </div>
      <div class="control">
        <label for="end">End</label>
        <select id="end"></select>
      </div>
      <div class="control">
        <label for="hour">Hour</label>
        <input id="hour" type="range" min="0" max="23" value="9" />
        <span id="hourLabel">09:00</span>
      </div>
      <div class="control">
        <label for="day">Day</label>
        <select id="day">
          <option value="0">Sun</option>
          <option value="1" selected>Mon</option>
          <option value="2">Tue</option>
          <option value="3">Wed</option>
          <option value="4">Thu</option>
          <option value="5">Fri</option>
          <option value="6">Sat</option>
        </select>
      </div>
      <button id="updateBtn">Update</button>
      <button id="routeBtn">Route</button>
      <div class="control">
        <button id="pickStartBtn">Pick Start</button>
        <button id="pickEndBtn">Pick End</button>
      </div>
      <div class="control">
        <label><input type="checkbox" id="toggleNodes" checked /> Nodes</label>
        <label><input type="checkbox" id="toggleEdges" checked /> Edges</label>
        <label><input type="checkbox" id="toggleRoute" checked /> Route</label>
        <label><input type="checkbox" id="toggleHeatmap" /> Heat</label>
      </div>
      <div class="legend">
        <span class="legend-item"><span class="legend-swatch" style="background:#16a34a;"></span>Low</span>
        <span class="legend-item"><span class="legend-swatch" style="background:#f59e0b;"></span>Med</span>
        <span class="legend-item"><span class="legend-swatch" style="background:#dc2626;"></span>High</span>
      </div>
    </section>
    <section class="info">
      <span id="routeInfo">Route info will appear here.</span>
      <span id="status" class="status"></span>
    </section>
    <section id="map"></section>
  </main>
`;

const map = L.map("map", {
  center: [34.0705, 72.6445],
  zoom: 23,
  maxZoom: 25,
});

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 25,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const styleByType = {
  highway: { color: "#16a34a", weight: 3 },
  path: { color: "#3b82f6", weight: 2, dashArray: "4 2" },
  building: { color: "#f97316", weight: 1, fillColor: "#fed7aa", fillOpacity: 0.5 },
};

const nodeLayer = L.layerGroup().addTo(map);
const edgeLayer = L.layerGroup().addTo(map);
let routeLayer = L.layerGroup().addTo(map);
let heatLayer = L.layerGroup().addTo(map);
const heatToggle = document.querySelector("#toggleHeatmap");
let altRouteLayer = L.layerGroup().addTo(map);
const WALK_SPEED_MPS = 1.3;
let forecastByEdge = {};
let nodesCache = {};
let edgesCache = [];
let edgeLookup = {};
let pickMode = null;
const routeInfoEl = document.querySelector("#routeInfo");
const hourInput = document.querySelector("#hour");
const hourLabel = document.querySelector("#hourLabel");
const daySelect = document.querySelector("#day");
const statusEl = document.querySelector("#status");

// Load the campus GeoJSON directly (already clipped), and render.
fetch("/giki_map.geojson")
  .then((res) => res.json())
  .then((geojson) => {
    // Drop point features (if any) to avoid marker clutter.
    const filtered = {
      type: "FeatureCollection",
      features: (geojson.features || []).filter(
        (f) => f.geometry && f.geometry.type !== "Point"
      ),
    };

    const layer = L.geoJSON(filtered, {
      style: () => styleByType.building,
    }).addTo(map);

    if (layer.getBounds && layer.getBounds().isValid()) {
      map.fitBounds(layer.getBounds(), { padding: [20, 20] });
    }
  })
  .catch((err) => {
    console.error("Failed to load campus GeoJSON", err);
  });

// Simple CSV parser for small files.
const parseCSV = (text) => {
  // Strip BOM if present.
  const clean = text.replace(/^\uFEFF/, "");
  const [headerLine, ...lines] = clean.trim().split(/\r?\n/);
  const headers = headerLine.split(",");
  return lines.map((line) => {
    const cells = line.split(",");
    const row = {};
    headers.forEach((h, i) => {
      row[h] = cells[i];
    });
    return row;
  });
};

const loadForecast = async (params = {}) => {
  try {
    const res = await axios.get(`${API_BASE}/forecast`, { params });
    const data = res.data;
    forecastByEdge = {};
    data.forEach((d) => {
      forecastByEdge[d.edge_id] = d;
    });
    if (heatToggle && heatToggle.checked) {
      renderHeatmap();
    }
  } catch (err) {
    console.error("Failed to load forecast", err);
    setStatus("Failed to load forecast", true);
  }
};

const getEdgeColor = (edgeId) => {
  const f = forecastByEdge[edgeId];
  if (!f) return "#16a34a";
  const ratio = f.pred_flow / Math.max(f.capacity || 1, 1);
  if (ratio < 0.5) return "#16a34a"; // low
  if (ratio < 0.8) return "#3b82f6"; // med (blue)
  return "#dc2626"; // high
};

const loadGraphOverlay = async () => {
  try {
    const [nodesRes, edgesRes] = await Promise.all([
      fetch("/data/nodes.csv"),
      fetch("/data/edges.csv"),
    ]);
    const nodesText = await nodesRes.text();
    const edgesText = await edgesRes.text();
    const nodes = parseCSV(nodesText).reduce((acc, row) => {
      acc[row.id] = {
        lat: Number(row.lat),
        lon: Number(row.lon),
        label: row.label || row.id,
      };
      return acc;
    }, {});
    const edges = parseCSV(edgesText);
    edgesCache = edges;

    // Draw nodes (POIs only in selectors; we still display all nodes)
  nodeLayer.clearLayers();
  nodesCache = nodes;
  Object.values(nodes).forEach((n) => {
      const marker = L.circleMarker([n.lat, n.lon], {
        radius: 4,
        color: "#0ea5e9",
        weight: 2,
        fillColor: "#fff",
        fillOpacity: 1,
      })
        .bindPopup(n.label)
        .addTo(nodeLayer);
      marker.bindTooltip(n.label, { permanent: false, direction: "top" });
    });

    // Draw edges
  edgeLayer.clearLayers();
  edges.forEach((e) => {
      const u = nodes[e.source];
      const v = nodes[e.target];
      if (!u || !v) return;
      const color = getEdgeColor(e.id);
      L.polyline(
        [
          [u.lat, u.lon],
          [v.lat, v.lon],
        ],
        { color, weight: 3, opacity: 0.8 }
      )
        .bindPopup(
          `Edge ${e.id}<br/>${u.label} → ${v.label}<br/>${Number(
            e.length_m
          ).toFixed(1)} m | ~${edgeEtaMinutes(Number(e.length_m)).toFixed(1)} min<br/>cap ${e.capacity}`
        )
        .addTo(edgeLayer);
    });
    if (heatToggle && heatToggle.checked) {
      renderHeatmap();
    }
    // Build edge lookup for quick ratio checks
    edgeLookup = {};
    edges.forEach((e) => {
      edgeLookup[`${e.source}-${e.target}`] = e;
      edgeLookup[`${e.target}-${e.source}`] = e;
    });
  } catch (err) {
    console.error("Failed to load graph overlay", err);
    setStatus("Graph load failed", true);
  }
};

const populateSelectors = () => {
  const startSel = document.querySelector("#start");
  const endSel = document.querySelector("#end");
  const entries = Object.entries(nodesCache).filter(([id]) => id.startsWith("p"));
  const options = entries
    .map(
      ([id, n]) =>
        `<option value="${id}">${n.label ? n.label : id}</option>`
    )
    .join("");
  startSel.innerHTML = options;
  endSel.innerHTML = options;
};

const requestRoute = async () => {
  const startId = document.querySelector("#start").value;
  const endId = document.querySelector("#end").value;
  if (!startId || !endId || !nodesCache[startId] || !nodesCache[endId]) {
    setStatus("Invalid start/end", true);
    return;
  }
  try {
    const res = await axios.get(`${API_BASE}/route`, {
      params: { source: startId, target: endId, mode: "both", k: 3 },
    });
    const best = res.data.best || {};
    const shortest = res.data.shortest || {};
    const bestAlts = res.data.best_alts || [];
    const shortestAlts = res.data.shortest_alts || [];
    const bestCoords = best.coords || [];
    const shortestCoords = shortest.coords || [];
    const bestLen = best.len_m || 0;
    const shortestLen = shortest.len_m || 0;
    const bestPathIds = best.path || (bestCoords.length ? bestCoords.map((c) => c.id) : []);
    const shortestPathIds =
      shortest.path || (shortestCoords.length ? shortestCoords.map((c) => c.id) : []);
    routeLayer.clearLayers();
    altRouteLayer.clearLayers();
    if (shortestCoords.length) {
      const latlngs = shortestCoords.map((c) => [c.lat, c.lon]);
      const ratio = pathRatio(shortestPathIds);
      const line = L.polyline(latlngs, {
        color: colorFromRatio(ratio),
        weight: 4,
        dashArray: "6 4",
      }).addTo(routeLayer);
      const dist = polylineLength(latlngs);
      const mins = Math.round(dist / 1.3 / 60);
      line.bindTooltip(`Shortest: ~${dist.toFixed(1)} m | ~${mins} min`).openTooltip();
    }
    if (bestCoords.length) {
      const latlngs = bestCoords.map((c) => [c.lat, c.lon]);
      const ratio = pathRatio(bestPathIds);
      const line = L.polyline(latlngs, { color: colorFromRatio(ratio), weight: 6 }).addTo(routeLayer);
      const dist = polylineLength(latlngs);
      const mins = Math.round(dist / 1.3 / 60);
      line.bindTooltip(`Recommended: ~${dist.toFixed(1)} m | ~${mins} min`).openTooltip();
      bestAlts.forEach((alt, idx) => {
        const coords = alt.coords || [];
        if (!coords.length) return;
        const ll = coords.map((c) => [c.lat, c.lon]);
        const altDist = polylineLength(ll);
        const altMins = Math.round(altDist / 1.3 / 60);
        const altRatio = pathRatio(alt.path || coords.map((c) => c.id));
        L.polyline(ll, {
          color: colorFromRatio(altRatio),
          weight: 3,
          opacity: 0.6,
          dashArray: "4 4",
        })
          .bindTooltip(`Alt ${idx + 1}: ~${altDist.toFixed(1)} m | ~${altMins} min`, { sticky: true })
          .addTo(altRouteLayer);
      });
      shortestAlts.forEach((alt, idx) => {
        const coords = alt.coords || [];
        if (!coords.length) return;
        const ll = coords.map((c) => [c.lat, c.lon]);
        const altDist = polylineLength(ll);
        const altMins = Math.round(altDist / 1.3 / 60);
        const altRatio = pathRatio(alt.path || coords.map((c) => c.id));
        L.polyline(ll, {
          color: colorFromRatio(altRatio),
          weight: 3,
          opacity: 0.5,
          dashArray: "2 6",
        })
          .bindTooltip(`Shortest alt ${idx + 1}: ~${altDist.toFixed(1)} m | ~${altMins} min`, { sticky: true })
          .addTo(altRouteLayer);
      });
      routeInfoEl.textContent = `Routes: Recommended ~${dist.toFixed(1)} m (~${mins} min); Shortest ~${shortestLen.toFixed(
        1
      )} m | Start: ${nodesCache[startId].label} → End: ${nodesCache[endId].label}`;
      setStatus("Routes ready", false);
    } else {
      routeInfoEl.textContent = "No route geometry returned.";
      setStatus("No route geometry", true);
    }
  } catch (err) {
    console.error("Route error", err);
    if (err.response && err.response.data && err.response.data.error) {
      routeInfoEl.textContent = `Route error: ${err.response.data.error}`;
      setStatus(err.response.data.error, true);
    } else {
      routeInfoEl.textContent = "Route error: backend not reachable.";
      setStatus("Backend not reachable", true);
    }
  }
};

const polylineLength = (latlngs) => {
  const R = 6371000;
  let total = 0;
  for (let i = 1; i < latlngs.length; i++) {
    const [lat1, lon1] = latlngs[i - 1];
    const [lat2, lon2] = latlngs[i];
    const phi1 = (lat1 * Math.PI) / 180;
    const phi2 = (lat2 * Math.PI) / 180;
    const dphi = ((lat2 - lat1) * Math.PI) / 180;
    const dlam = ((lon2 - lon1) * Math.PI) / 180;
    const a =
      Math.sin(dphi / 2) * Math.sin(dphi / 2) +
      Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlam / 2) * Math.sin(dlam / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    total += R * c;
  }
  return total;
};

const edgeEtaMinutes = (length) => length / WALK_SPEED_MPS / 60;

const edgeRatio = (uId, vId) => {
  const e = edgeLookup[`${uId}-${vId}`];
  if (!e) return 0;
  const f = forecastByEdge[e.id];
  if (!f) return 0;
  return f.pred_flow / Math.max(f.capacity || 1, 1);
};

const pathRatio = (pathIds = []) => {
  if (!pathIds.length) return 0;
  let maxRatio = 0;
  for (let i = 1; i < pathIds.length; i++) {
    maxRatio = Math.max(maxRatio, edgeRatio(pathIds[i - 1], pathIds[i]));
  }
  return maxRatio;
};

const colorFromRatio = (r) => {
  if (r < 0.5) return "#16a34a"; // low = green
  if (r < 0.8) return "#2563eb"; // medium = blue
  return "#dc2626"; // high = red
};

const isPeakHour = (hour) => {
  const h = Math.floor(hour);
  return [8, 9, 10, 13, 14, 15, 16].includes(h) ? 1 : 0;
};

const updateHourLabel = () => {
  const h = Number(hourInput.value || 0);
  const hh = h.toString().padStart(2, "0");
  hourLabel.textContent = `${hh}:00`;
};

const refreshForecastAndOverlay = async () => {
  const hour = Number(hourInput.value || 9);
  const day = Number(daySelect.value || 1);
  await loadForecast({ hour, day_of_week: day, is_peak: isPeakHour(hour) });
  await loadGraphOverlay();
};

const init = async () => {
  await refreshForecastAndOverlay();
  populateSelectors();
  updateHourLabel();

  document.querySelector("#updateBtn").addEventListener("click", async () => {
    await refreshForecastAndOverlay();
  });

  document.querySelector("#routeBtn").addEventListener("click", async () => {
    await refreshForecastAndOverlay();
    await requestRoute();
  });

  // layer toggles
  document.querySelector("#toggleNodes").addEventListener("change", (e) => {
    if (e.target.checked) map.addLayer(nodeLayer);
    else map.removeLayer(nodeLayer);
  });
  document.querySelector("#toggleEdges").addEventListener("change", (e) => {
    if (e.target.checked) map.addLayer(edgeLayer);
    else map.removeLayer(edgeLayer);
  });
  document.querySelector("#toggleRoute").addEventListener("change", (e) => {
    if (e.target.checked) {
      map.addLayer(routeLayer);
      map.addLayer(altRouteLayer);
    } else {
      map.removeLayer(routeLayer);
      map.removeLayer(altRouteLayer);
    }
  });
  document.querySelector("#toggleHeatmap").addEventListener("change", (e) => {
    if (e.target.checked) {
      renderHeatmap();
    } else if (heatLayer) {
      map.removeLayer(heatLayer);
      heatLayer = L.layerGroup().addTo(map);
    }
  });

  // pick start/end via map click
  document.querySelector("#pickStartBtn").addEventListener("click", () => {
    pickMode = "start";
  });
  document.querySelector("#pickEndBtn").addEventListener("click", () => {
    pickMode = "end";
  });

  map.on("click", (e) => {
    if (!pickMode) return;
    const nearest = findNearestNode(e.latlng.lat, e.latlng.lng);
    if (nearest) {
      document.querySelector(pickMode === "start" ? "#start" : "#end").value =
        nearest.id;
    }
    pickMode = null;
  });
};

init();

const findNearestNode = (lat, lon) => {
  let best = null;
  let bestDist = Infinity;
  Object.entries(nodesCache).forEach(([id, n]) => {
    const dLat = lat - n.lat;
    const dLon = lon - n.lon;
    const dist = dLat * dLat + dLon * dLon;
    if (dist < bestDist) {
      bestDist = dist;
      best = { id, ...n };
    }
  });
  return best;
};

const setStatus = (msg, isError) => {
  if (!statusEl) return;
  if (!msg) {
    statusEl.textContent = "";
    statusEl.className = "status";
    return;
  }
  statusEl.textContent = msg;
  statusEl.className = `status ${isError ? "err" : "ok"}`;
};

const renderHeatmap = () => {
  if (heatLayer) {
    map.removeLayer(heatLayer);
  }
  heatLayer = L.layerGroup().addTo(map);
  edgesCache.forEach((e) => {
    const f = forecastByEdge[e.id];
    if (!f) return;
    const u = nodesCache[e.source];
    const v = nodesCache[e.target];
    if (!u || !v) return;
    const lat = (u.lat + v.lat) / 2;
    const lon = (u.lon + v.lon) / 2;
    const ratio = f.pred_flow / Math.max(f.capacity || 1, 1);
    if (ratio < 0.5) return; // show only med/high
    let color = "#f59e0b";
    let radius = 8;
    if (ratio >= 0.8) {
      color = "#dc2626";
      radius = 10;
    }
    L.circleMarker([lat, lon], {
      radius,
      color,
      fillColor: color,
      fillOpacity: 0.4,
      weight: 0,
    })
      .bindTooltip(
        `${e.id} | ${(ratio * 100).toFixed(0)}% cap<br>${Number(e.length_m).toFixed(
          1
        )} m`,
        { sticky: true }
      )
      .addTo(heatLayer);
  });
};

// Time controls
hourInput.addEventListener("input", () => {
  updateHourLabel();
});
hourInput.addEventListener("change", async () => {
  await refreshForecastAndOverlay();
});
daySelect.addEventListener("change", async () => {
  await refreshForecastAndOverlay();
});

// Heat toggle
if (document.querySelector("#toggleHeatmap")) {
  document.querySelector("#toggleHeatmap").addEventListener("change", (e) => {
    if (e.target.checked) {
      renderHeatmap();
    } else {
      if (heatLayer) {
        map.removeLayer(heatLayer);
        heatLayer = L.layerGroup().addTo(map);
      }
    }
  });
}
