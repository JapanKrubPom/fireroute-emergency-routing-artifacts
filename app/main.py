from __future__ import annotations

import json
import math
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

try:
    import folium
    from folium.plugins import HeatMap
    from streamlit_folium import st_folium
except Exception as e:
    folium = None
    st_folium = None

BKK_TZ = timezone(timedelta(hours=7))


# -----------------------------
# Styling
# -----------------------------
APP_TITLE = "FireRoute KU"
APP_SUBTITLE = "Campus-scale operational emergency routing and dispatch prototype"

CSS = """
<style>
:root { --card-bg: rgba(255,255,255,.06); --card-bd: rgba(255,255,255,.12); }
.block-container { padding-top: 1.2rem; padding-bottom: 3rem; }
.small { opacity: 0.86; font-size: 0.92rem; }
.badge { display:inline-block; padding: 0.15rem .45rem; border-radius: 999px; font-size: .78rem; border: 1px solid var(--card-bd); background: var(--card-bg); }
.card {
  border: 1px solid var(--card-bd);
  background: linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.03));
  border-radius: 18px;
  padding: 14px 14px;
  box-shadow: 0 8px 30px rgba(0,0,0,.15);
}
.card h3 { margin: 0 0 6px 0; font-size: 1.05rem; }
.card p { margin: 0; }
hr.soft { border: none; height: 1px; background: rgba(255,255,255,.12); margin: .75rem 0; }
.kpi { font-size: 1.55rem; font-weight: 700; line-height: 1.0; }
.kpi-label { opacity: .82; font-size: .85rem; margin-top: .25rem; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
</style>
"""


# -----------------------------
# Data models
# -----------------------------
@dataclass
class Node:
    id: str
    lat: float
    lon: float
    kind: str  # road, shelter, station


@dataclass
class Edge:
    a: str
    b: str
    kind: str  # main, alley, footpath
    width_m: float
    turn_radius_m: float
    one_way: bool
    gate: bool
    base_speed_kmh: float

    # Compatibility fields (safe to ignore if unused)
    risk_smoke: float = 0.0
    risk_congestion: float = 0.0
    one_way_ab: 'Optional[bool]' = None

    def __post_init__(self):
        if self.one_way_ab is not None:
            self.one_way = bool(self.one_way_ab)
@dataclass
class Hydrant:
    id: str
    lat: float
    lon: float
    district: str
    status: str  # WORKING, BLOCKED, LOW_PRESSURE, UNKNOWN, FAILED

    # Optional / UI fields (defaults keep dataclass init safe)
    evidence_photo: str = "assets/hydrant_placeholder.jpg"
    health_checks: list = field(default_factory=list)
    last_updated: str = ""  # ISO timestamp
    last_seen: str = ""  # Alias used in some UI blocks


    def __post_init__(self):
        # keep timestamps in sync
        if not self.last_updated and self.last_seen:
            self.last_updated = self.last_seen
        if not self.last_seen and self.last_updated:
            self.last_seen = self.last_updated
@dataclass
class SensorNode:
    id: str
    lat: float
    lon: float
    smoke_ppm: float
    co_ppm: float
    temp_c: float

    last_seen: str = ""
    last_updated: str = ""

    link: str = ""

    def __post_init__(self):
        # keep timestamps in sync
        if not self.last_updated and self.last_seen:
            self.last_updated = self.last_seen
        if not self.last_seen and self.last_updated:
            self.last_seen = self.last_updated
@dataclass
class ResponderUnit:
    id: str
    name: str
    kind: str  # motorbike, truck
    node_id: str
    status: str  # Available, Busy, En-route, On-scene, Need water, Clear
    last_ping: str


# -----------------------------
# Utilities
# -----------------------------
def now_iso() -> str:
    return datetime.now(BKK_TZ).isoformat(timespec="seconds")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # meters
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    d1 = math.radians(lat2 - lat1)
    d2 = math.radians(lon2 - lon1)
    a = math.sin(d1 / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d2 / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def fmt_mins(seconds: float) -> str:
    if seconds <= 0:
        return "0m"
    m = seconds / 60.0
    if m < 1:
        return "<1m"
    return f"{m:.0f}m"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def add_audit(event: str, detail: dict, actor: str = "system") -> None:
    st.session_state.audit_log.append(
        {
            "ts": now_iso(),
            "event": event,
            "actor": actor,
            "detail": detail,
        }
    )


# -----------------------------
# Pilot graph data (Kasetsart University campus + surroundings - demo scale)
# -----------------------------
def build_pilot_graph() -> Tuple[Dict[str, Node], List[Edge]]:
    """
    Pilot graph = demo-scale road network used by the routing engine.

    Demo scope (B): **Kasetsart University (Bangkhen) + รอบมหาลัย**
    - Inside campus: campus roads + service alleys
    - Outside: main access on Ngamwongwan / nearby connectors

    Notes
    - Coordinates are approximate (good enough for demo + UI).
    - The same graph interface scales to a real Bangkok-wide graph.
    """

    # --- Nodes (IDs kept stable because other demo components reference them) ---
    # Center reference: Kasetsart University (Bangkhen) ~ (13.8488, 100.5678)
    nodes = [
        # Station / command
        Node("HQ", 13.84880, 100.56780, "station"),  # KU Fire Command (pilot)

        # Campus spine (north -> south-east)
        Node("N1", 13.85090, 100.56740, "road"),
        Node("N2", 13.85180, 100.56840, "road"),  # Science / academic core
        Node("N3", 13.85180, 100.56980, "road"),  # Library / north loop
        Node("N4", 13.85080, 100.57100, "road"),  # East loop
        Node("N5", 13.84960, 100.57020, "road"),  # Dorm / canteen junction
        Node("N6", 13.84820, 100.56960, "road"),  # Engineering / stadium junction
        Node("N7", 13.84730, 100.56860, "road"),
        Node("N8", 13.84670, 100.56720, "road"),

        # East connectors (Vibhavadi-side access / service lane)
        Node("E1", 13.84900, 100.57220, "road"),
        Node("E2", 13.84800, 100.57160, "road"),
        Node("E3", 13.84720, 100.57100, "road"),

        # West / Ngamwongwan access (gate + frontage)
        Node("W1", 13.84880, 100.56550, "road"),
        Node("W2", 13.85000, 100.56400, "road"),  # Main gate area (Ngamwongwan)
        Node("W3", 13.84680, 100.56450, "road"),

        # Shelters / assembly points (campus evacuation)
        Node("S1", 13.84880, 100.57300, "shelter"),  # East parking / open area
        Node("S2", 13.84680, 100.57200, "shelter"),
        Node("S3", 13.84550, 100.56700, "shelter"),

        # POIs (demo-only: helps show "place" markers)
        Node("POI_KU_StudentCenter", 13.84870, 100.56860, "poi"),
        Node("POI_KU_Stadium", 13.84660, 100.56660, "poi"),
        Node("POI_KU_VetHospital", 13.85210, 100.56610, "poi"),
    ]

    nd = {n.id: n for n in nodes}

    # NOTE: Edge in this demo uses physical road constraints (width/turn radius) rather than
    # per-edge smoke/congestion risks (those are modeled via dynamic events and overlays).
    def e(
        a: str,
        b: str,
        kind: str = "main",
        width_m: float = 6.0,
        turn_radius_m: float = 10.0,
        one_way: bool = False,
        gate: bool = False,
        base_speed_kmh: float = 30.0,
    ) -> Edge:
        return Edge(
            a=a,
            b=b,
            kind=kind,
            width_m=width_m,
            turn_radius_m=turn_radius_m,
            one_way=one_way,
            gate=gate,
            base_speed_kmh=base_speed_kmh,
        )

    edges: List[Edge] = []

    # Main spine (campus roads)
    edges += [
        e("HQ", "N1", "main", 8, 10, False, False, 25),
        e("N1", "N2", "main", 6, 9, False, False, 25),
        e("N2", "N3", "main", 5, 8, False, False, 22),
        e("N3", "N4", "main", 6, 9, False, False, 22),
        e("N4", "N5", "main", 7, 10, False, True, 20),
        e("N5", "N6", "main", 6, 9, False, False, 20),
        e("N6", "N7", "main", 5, 8, False, False, 20),
        e("N7", "N8", "main", 5, 8, False, False, 20),
    ]

    # East branch (service lane + vibhavadi-side access)
    edges += [
        e("N4", "E1", "main", 8, 11, False, False, 35),
        e("E1", "E2", "alley", 4, 7, False, True, 18),
        e("E2", "E3", "alley", 5, 8, False, False, 18),
        e("E2", "N6", "alley", 3, 6, True, False, 16),
    ]

    # West / Ngamwongwan access
    edges += [
        e("HQ", "W1", "main", 6, 10, False, False, 30),
        e("W1", "W2", "main", 6, 10, False, True, 35),
        e("W2", "W3", "main", 7, 11, False, False, 35),
        e("W3", "N8", "alley", 3, 5, False, False, 18),
    ]

    # Evacuation links (walk paths)
    edges += [
        e("E1", "S1", "footpath", 0, 0, False, False, 6),
        e("E3", "S2", "footpath", 0, 0, False, False, 6),
        e("N8", "S3", "footpath", 0, 0, False, False, 6),
    ]

    # POIs
    edges += [
        e("N8", "POI_KU_StudentCenter", "alley", 2, 4, False, False, 10),
        e("W1", "POI_KU_VetHospital", "main", 4, 7, False, False, 25),
        e("W1", "POI_KU_Stadium", "main", 4, 7, False, False, 25),
    ]

    # Back-links (makes routing more robust for demo)
    edges += [
        e("N6", "N5", "main", 6, 9, False, False, 20),
        e("N5", "N4", "main", 7, 10, False, False, 20),
        e("N4", "N3", "main", 6, 9, False, False, 22),
    ]

    return nd, edges


def build_default_hydrants() -> Dict[str, Hydrant]:
    # Demo hydrants with realistic metadata / evidence hooks.
    # Scope: Kasetsart University (Bangkhen) + รอบมหาลัย
    demo = [
        ("HYD-101", 13.85000, 100.56410, "Chatuchak", "WORKING"),       # Near main gate
        ("HYD-102", 13.85170, 100.56830, "Chatuchak", "WORKING"),       # Academic core
        ("HYD-103", 13.85070, 100.57110, "Chatuchak", "LOW_PRESSURE"),  # East loop
        ("HYD-104", 13.84890, 100.57230, "Chatuchak", "WORKING"),       # East access
        ("HYD-105", 13.84740, 100.57120, "Chatuchak", "BLOCKED"),       # Construction
        ("HYD-106", 13.84550, 100.56710, "Chatuchak", "WORKING"),       # South
        ("HYD-201", 13.84920, 100.56320, "Chatuchak", "UNKNOWN"),       # Ngamwongwan frontage
        ("HYD-202", 13.84690, 100.56460, "Chatuchak", "WORKING"),       # West-south
        ("HYD-203", 13.84880, 100.56560, "Chatuchak", "WORKING"),       # West inside
        ("HYD-301", 13.85220, 100.56610, "Chatuchak", "WORKING"),       # North loop
        ("HYD-302", 13.85210, 100.57010, "Chatuchak", "WORKING"),       # North-east
        ("HYD-303", 13.84790, 100.56990, "Chatuchak", "WORKING"),       # Central-east
    ]
    out: Dict[str, Hydrant] = {}
    for hid, lat, lon, dist, stt in demo:
        out[hid] = Hydrant(
            id=hid,
            lat=lat,
            lon=lon,
            district=dist,
            status=stt,
            last_updated=now_iso(),
            evidence_photo="assets/hydrant_placeholder.jpg",
            health_checks=[
                {"ts": now_iso(), "step": "Visual", "result": "OK" if stt != "BLOCKED" else "Blocked"},
                {"ts": now_iso(), "step": "Flow", "result": "OK" if stt == "WORKING" else "Needs inspection"},
            ],
        )
    return out



def build_default_sensors() -> Dict[str, SensorNode]:
    # Demo sensor nodes (smoke/CO/temp) + link to LoRa gateway (mock)
    demo = [
        ("SN-01", 13.84980, 100.56500, 14.0, 2.0, 31.0, "LoRa-KU-01"),  # Gate zone
        ("SN-02", 13.85160, 100.56960, 28.0, 6.0, 36.0, "LoRa-KU-02"),  # Academic core
        ("SN-03", 13.84760, 100.57100, 20.0, 4.0, 34.0, "LoRa-KU-03"),  # East service lane
    ]
    out: Dict[str, SensorNode] = {}
    for sid, lat, lon, smoke, co, temp, link in demo:
        out[sid] = SensorNode(
            id=sid,
            lat=lat,
            lon=lon,
            smoke_ppm=smoke,
            co_ppm=co,
            temp_c=temp,
            link=link,
            last_seen=now_iso(),
        )
    return out



def build_default_responders() -> Dict[str, ResponderUnit]:
    demo = [
        ResponderUnit("FR-01", "First Responder Motorbike 01", "motorbike", "HQ", "Available", now_iso()),
        ResponderUnit("TR-07", "Fire Truck 07", "truck", "W2", "Available", now_iso()),
        ResponderUnit("TR-12", "Fire Truck 12", "truck", "N6", "Busy", now_iso()),
    ]
    return {u.id: u for u in demo}


# -----------------------------
# Routing (Dijkstra over pilot graph)
# -----------------------------
def edge_distance_m(nodes: Dict[str, Node], e: Edge) -> float:
    a = nodes[e.a]
    b = nodes[e.b]
    return haversine_m(a.lat, a.lon, b.lat, b.lon)


def edge_travel_time_s(nodes: Dict[str, Node], e: Edge, risk_multiplier: float) -> float:
    dist = edge_distance_m(nodes, e)
    speed_ms = (e.base_speed_kmh * 1000.0) / 3600.0
    speed_ms = max(speed_ms, 0.5)
    base = dist / speed_ms
    return base * risk_multiplier


def compute_risk_multiplier(
    e: Edge,
    blocked: bool,
    smoke_factor: float,
    alley_constraints_factor: float,
) -> float:
    # risk-weighted graph: travel_time * (1 + penalties)
    if blocked:
        return 1e9  # effectively unreachable
    k = 1.0
    if e.kind == "alley":
        k *= (1.0 + 0.25 * alley_constraints_factor)
    if e.gate:
        k *= (1.0 + 0.20)
    if e.one_way:
        k *= (1.0 + 0.05)
    k *= (1.0 + 0.30 * smoke_factor)
    return k


def dijkstra(
    nodes: Dict[str, Node],
    edges: List[Edge],
    start: str,
    goal: str,
    blocked_edges: set,
    smoke_factor: float,
    alley_constraints_factor: float,
) -> Tuple[List[str], float]:
    # adjacency
    adj: Dict[str, List[Tuple[str, Edge]]] = {nid: [] for nid in nodes.keys()}
    for e in edges:
        adj[e.a].append((e.b, e))
        if not e.one_way:
            adj[e.b].append((e.a, e))

    dist: Dict[str, float] = {nid: float("inf") for nid in nodes.keys()}
    prev: Dict[str, Optional[str]] = {nid: None for nid in nodes.keys()}
    prev_edge: Dict[str, Optional[Edge]] = {nid: None for nid in nodes.keys()}

    dist[start] = 0.0
    visited = set()

    # simple priority queue
    import heapq

    pq = [(0.0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if u == goal:
            break
        for v, e in adj.get(u, []):
            key = tuple(sorted((u, v)) + [e.kind])  # stable id-ish
            blocked = key in blocked_edges
            rm = compute_risk_multiplier(e, blocked, smoke_factor, alley_constraints_factor)
            w = edge_travel_time_s(nodes, e, rm)
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                prev_edge[v] = e
                heapq.heappush(pq, (nd, v))

    if dist[goal] == float("inf"):
        return [], float("inf")

    # reconstruct
    path = []
    cur = goal
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return path, dist[goal]


def nearest_node(nodes: Dict[str, Node], lat: float, lon: float) -> str:
    best = None
    bestd = float("inf")
    for nid, n in nodes.items():
        d = haversine_m(lat, lon, n.lat, n.lon)
        if d < bestd:
            bestd = d
            best = nid
    assert best is not None
    return best


def choose_best_working_hydrant(
    nodes: Dict[str, Node],
    edges: List[Edge],
    start_node: str,
    incident_node: str,
    hydrants: Dict[str, Hydrant],
    blocked_edges: set,
    smoke_factor: float,
    alley_constraints_factor: float,
) -> Tuple[Optional[str], float, List[str], List[str]]:
    # minimize: start->hydrant + hydrant->incident, hydrant must be WORKING
    best_h = None
    best_t = float("inf")
    best_p1: List[str] = []
    best_p2: List[str] = []

    for hid, h in hydrants.items():
        if h.status != "WORKING":
            continue
        h_node = nearest_node(nodes, h.lat, h.lon)
        p1, t1 = dijkstra(nodes, edges, start_node, h_node, blocked_edges, smoke_factor, alley_constraints_factor)
        p2, t2 = dijkstra(nodes, edges, h_node, incident_node, blocked_edges, smoke_factor, alley_constraints_factor)
        tot = t1 + t2
        if tot < best_t and t1 < float("inf") and t2 < float("inf"):
            best_t = tot
            best_h = hid
            best_p1 = p1
            best_p2 = p2
    return best_h, best_t, best_p1, best_p2


# -----------------------------
# Incident logic (Intake & triage)
# -----------------------------
FUEL_TYPES = {
    "Unknown": 0,
    "Electrical": 10,
    "Gas/LPG": 20,
    "Chemical": 35,
    "Fuel / Oil": 30,
}

ALLEY_CONSTRAINTS = ["None", "Narrow (<3m)", "Gated/Locked", "One-way + tight turn", "Unknown/complex"]


def compute_confidence(incident: dict, dup_count: int) -> Tuple[float, dict]:
    # A quick heuristic confidence for dispatch triage
    score = 0.35
    explain = {}

    completeness = 0.0
    for k in ["lat", "lon", "desc", "reporter"]:
        if incident.get(k):
            completeness += 0.2
    score += completeness
    explain["completeness"] = round(completeness, 2)

    media_boost = 0.0
    if incident.get("media_count", 0) >= 1:
        media_boost = 0.20
    if incident.get("panic", False):
        media_boost += 0.10
    score += media_boost
    explain["media_panic_boost"] = round(media_boost, 2)

    dup_penalty = 0.0
    if dup_count >= 1:
        dup_penalty = min(0.30, 0.10 * dup_count)
    score -= dup_penalty
    explain["duplicate_penalty"] = round(dup_penalty, 2)

    score = clamp(score, 0.0, 1.0)
    explain["confidence"] = round(score, 2)
    return score, explain


def find_duplicates(incidents: List[dict], lat: float, lon: float, within_m: float = 220.0, within_min: int = 12) -> List[dict]:
    out = []
    now = datetime.now(BKK_TZ)
    for inc in incidents:
        t = datetime.fromisoformat(inc["created_at"])
        if abs((now - t).total_seconds()) > within_min * 60:
            continue
        d = haversine_m(lat, lon, inc["lat"], inc["lon"])
        if d <= within_m:
            out.append(inc)
    return out


def compute_explainable_risk(incident: dict, sensors: Dict[str, SensorNode]) -> Tuple[float, dict]:
    # Explainable risk score for command center prioritization.
    breakdown = {}

    base = 20.0
    breakdown["base"] = base

    trapped = float(incident.get("people_trapped", 0))
    trapped_pts = 8.0 * trapped
    breakdown["people_trapped"] = trapped_pts

    fuel = incident.get("fuel_type", "Unknown")
    fuel_pts = float(FUEL_TYPES.get(fuel, 0))
    breakdown["fuel_type"] = fuel_pts

    alley = incident.get("alley_constraint", "None")
    alley_pts = {
        "None": 0.0,
        "Narrow (<3m)": 10.0,
        "Gated/Locked": 14.0,
        "One-way + tight turn": 12.0,
        "Unknown/complex": 8.0,
    }.get(alley, 5.0)
    breakdown["alley_constraints"] = alley_pts

    panic_pts = 10.0 if incident.get("panic", False) else 0.0
    breakdown["panic_mode"] = panic_pts

    # nearest sensor contributes smoke/CO/Temp
    near = None
    best = float("inf")
    for sn in sensors.values():
        d = haversine_m(incident["lat"], incident["lon"], sn.lat, sn.lon)
        if d < best:
            best = d
            near = sn
    env_pts = 0.0
    if near is not None:
        env_pts += clamp((near.smoke_ppm - 15) * 0.6, 0, 20)
        env_pts += clamp((near.co_ppm - 3) * 1.2, 0, 20)
        env_pts += clamp((near.temp_c - 30) * 0.9, 0, 20)
        breakdown["env_sensor_near_km"] = round(best / 1000.0, 2)
        breakdown["env_points"] = round(env_pts, 1)
    else:
        breakdown["env_points"] = 0.0

    total = base + trapped_pts + fuel_pts + alley_pts + panic_pts + env_pts
    total = clamp(total, 0, 100)
    breakdown["risk_score"] = round(total, 1)
    return total, breakdown


# -----------------------------
# Evidence pack export
# -----------------------------
def make_evidence_pack_zip(incident: dict, routes: dict, audit_log: list, hydrants: Dict[str, Hydrant], tickets: list) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("incident.json", json.dumps(incident, ensure_ascii=False, indent=2))
        z.writestr("routes.json", json.dumps(routes, ensure_ascii=False, indent=2))
        z.writestr("audit_log.jsonl", "\n".join(json.dumps(x, ensure_ascii=False) for x in audit_log))
        z.writestr("hydrants.json", json.dumps({k: h.__dict__ for k, h in hydrants.items()}, ensure_ascii=False, indent=2))
        z.writestr("maintenance_tickets.json", json.dumps(tickets, ensure_ascii=False, indent=2))

        # AAR-style lightweight HTML
        html = f"""
        <html><head><meta charset="utf-8"><title>Evidence Pack</title></head><body>
        <h2>Bangkok FireSmart Evidence Pack</h2>
        <p><b>Incident:</b> {incident.get('id')} | <b>Status:</b> {incident.get('status')}</p>
        <p><b>Created:</b> {incident.get('created_at')}</p>
        <h3>Key KPIs</h3>
        <ul>
          <li>Confidence: {incident.get('confidence'):.2f}</li>
          <li>Risk score: {incident.get('risk_score'):.1f}</li>
          <li>Assigned unit: {incident.get('assigned_unit') or '-'}</li>
        </ul>
        <h3>Timeline (Audit Log)</h3>
        <pre style="white-space: pre-wrap;">{json.dumps(audit_log[-120:], ensure_ascii=False, indent=2)}</pre>
        <h3>Routing Summary</h3>
        <pre style="white-space: pre-wrap;">{json.dumps(routes, ensure_ascii=False, indent=2)}</pre>
        </body></html>
        """
        z.writestr("evidence_pack.html", html)

    return buf.getvalue()


# -----------------------------
# Session init
# -----------------------------
def init_state() -> None:
    if "nodes" not in st.session_state:
        nodes, edges = build_pilot_graph()
        st.session_state.nodes = nodes
        st.session_state.edges = edges

    if "hydrants" not in st.session_state:
        st.session_state.hydrants = build_default_hydrants()

    if "sensors" not in st.session_state:
        st.session_state.sensors = build_default_sensors()

    if "responders" not in st.session_state:
        st.session_state.responders = build_default_responders()

    if "incidents" not in st.session_state:
        st.session_state.incidents = []

    if "blocked_edges" not in st.session_state:
        st.session_state.blocked_edges = set()  # set of tuple ids

    if "audit_log" not in st.session_state:
        st.session_state.audit_log = []

    if "tickets" not in st.session_state:
        st.session_state.tickets = []

    if "selected_incident_id" not in st.session_state:
        st.session_state.selected_incident_id = None

    if "map_last_click" not in st.session_state:
        st.session_state.map_last_click = None

    if "routing_cache" not in st.session_state:
        st.session_state.routing_cache = {}

    if "role" not in st.session_state:
        st.session_state.role = "Command Center"

    if "degraded_mode" not in st.session_state:
        st.session_state.degraded_mode = False

    if "sim_smoke_factor" not in st.session_state:
        st.session_state.sim_smoke_factor = 0.0

    if "sim_alley_factor" not in st.session_state:
        st.session_state.sim_alley_factor = 0.0


# -----------------------------
# UI helpers
# -----------------------------
def card(title: str, body_html: str) -> None:
    st.markdown(f'<div class="card"><h3>{title}</h3>{body_html}</div>', unsafe_allow_html=True)


def kpi(label: str, value: str, hint: str = "") -> None:
    hint_html = f'<div class="small">{hint}</div>' if hint else ""
    st.markdown(
        f"""
        <div class="card">
          <div class="kpi">{value}</div>
          <div class="kpi-label">{label}</div>
          {hint_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def role_guard_can_view_pii(role: str) -> bool:
    return role in ["Command Center"]


def role_guard_can_dispatch(role: str) -> bool:
    return role in ["Command Center", "Responder"]


def role_guard_can_ops(role: str) -> bool:
    return role in ["Command Center", "City Ops"]


def status_badge(status: str) -> str:
    colors = {
        "New": "🟡",
        "Needs Verify": "🟠",
        "Verified": "🟢",
        "Dispatched": "🚒",
        "On-scene": "🔥",
        "Contained": "✅",
        "Clear": "🧯",
    }
    return f"{colors.get(status, '•')} {status}"


# -----------------------------
# Map rendering
# -----------------------------
def make_map(
    center: Tuple[float, float],
    show_hydrants: bool,
    show_sensors: bool,
    show_graph: bool,
    show_heatmap: bool,
    selected_incident: Optional[dict],
    route_polyline: Optional[List[Tuple[float, float]]],
    evac_polyline: Optional[List[Tuple[float, float]]],
    selected_hydrant_id: Optional[str],
) -> object:
    if folium is None:
        return None

    tiles = "OpenStreetMap" if not st.session_state.degraded_mode else "CartoDB positron"
    m = folium.Map(location=center, zoom_start=14, tiles=tiles, control_scale=True)

    # Graph layer (alley/entry points)
    if show_graph:
        fg = folium.FeatureGroup(name="Alley Graph (pilot)", show=True)
        for e in st.session_state.edges:
            a = st.session_state.nodes[e.a]
            b = st.session_state.nodes[e.b]
            key = tuple(sorted((e.a, e.b)) + [e.kind])
            blocked = key in st.session_state.blocked_edges
            style = {"weight": 4 if e.kind == "main" else 3, "opacity": 0.75}
            if blocked:
                style["dash_array"] = "6"
                style["opacity"] = 0.9
            fg.add_child(
                folium.PolyLine(
                    locations=[(a.lat, a.lon), (b.lat, b.lon)],
                    tooltip=f"{e.kind} | width={e.width_m:.1f}m | gate={e.gate} | one_way={e.one_way} | blocked={blocked}",
                    color="#5dade2",
                    **style,
                )
            )
        m.add_child(fg)

    # Hydrants
    if show_hydrants:
        fg = folium.FeatureGroup(name="Hydrant Reality Layer", show=True)
        for hid, h in st.session_state.hydrants.items():
            icon = "tint"
            color = {
                "WORKING": "green",
                "LOW_PRESSURE": "orange",
                "BLOCKED": "red",
                "FAILED": "darkred",
                "UNKNOWN": "gray",
            }.get(h.status, "blue")
            popup = folium.Popup(
                f"""
                <b>{hid}</b><br>
                Status: <b>{h.status}</b><br>
                District: {h.district}<br>
                Last updated: {h.last_updated}<br>
                Evidence: {h.evidence_photo}<br>
                """,
                max_width=320,
            )
            marker = folium.Marker(
                location=(h.lat, h.lon),
                tooltip=f"{hid} ({h.status})",
                popup=popup,
                icon=folium.Icon(color=color, icon=icon, prefix="fa"),
            )
            fg.add_child(marker)

        m.add_child(fg)

    # Sensors
    if show_sensors:
        fg = folium.FeatureGroup(name="Micro-Node Sensors (LoRa)", show=True)
        for sid, sn in st.session_state.sensors.items():
            popup = folium.Popup(
                f"""
                <b>{sid}</b><br>
                Smoke: {sn.smoke_ppm:.1f} ppm<br>
                CO: {sn.co_ppm:.1f} ppm<br>
                Temp: {sn.temp_c:.1f} °C<br>
                Last seen: {sn.last_seen}<br>
                Link: {sn.link}<br>
                """,
                max_width=320,
            )
            fg.add_child(
                folium.CircleMarker(
                    location=(sn.lat, sn.lon),
                    radius=7,
                    tooltip=f"{sid} (smoke {sn.smoke_ppm:.0f}ppm)",
                    popup=popup,
                    fill=True,
                    opacity=0.9,
                )
            )
        m.add_child(fg)

    # Incident markers
    fg_inc = folium.FeatureGroup(name="Incidents", show=True)
    for inc in st.session_state.incidents[-40:]:
        is_sel = selected_incident and inc["id"] == selected_incident["id"]
        color = "purple" if is_sel else "blue"
        fg_inc.add_child(
            folium.CircleMarker(
                location=(inc["lat"], inc["lon"]),
                radius=9 if is_sel else 6,
                tooltip=f"{inc['id']} | {inc['status']} | conf={inc['confidence']:.2f}",
                popup=folium.Popup(f"<b>{inc['id']}</b><br>Status: {inc['status']}<br>Risk: {inc['risk_score']:.1f}", max_width=280),
                fill=True,
                color=color,
                fill_opacity=0.8,
            )
        )
    m.add_child(fg_inc)

    # Route
    if route_polyline:
        folium.PolyLine(route_polyline, weight=7, opacity=0.9, tooltip="Responder route").add_to(m)
    if evac_polyline:
        folium.PolyLine(evac_polyline, weight=5, opacity=0.85, dash_array="8", tooltip="Evacuation route").add_to(m)

    # Selected hydrant highlight
    if selected_hydrant_id and selected_hydrant_id in st.session_state.hydrants:
        h = st.session_state.hydrants[selected_hydrant_id]
        folium.Marker(
            location=(h.lat, h.lon),
            tooltip=f"Selected hydrant: {selected_hydrant_id}",
            icon=folium.Icon(color="darkgreen", icon="tint", prefix="fa"),
        ).add_to(m)

    # Heatmap (historical + current)
    if show_heatmap:
        pts = [(inc["lat"], inc["lon"], clamp(inc.get("risk_score", 50) / 100.0, 0.1, 1.0)) for inc in st.session_state.incidents]
        if pts:
            HeatMap(pts, min_opacity=0.2, radius=22, blur=18, max_zoom=16).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m


def path_to_polyline(nodes: Dict[str, Node], path: List[str]) -> List[Tuple[float, float]]:
    return [(nodes[n].lat, nodes[n].lon) for n in path]


# -----------------------------
# Core app
# -----------------------------

def load_governor_demo() -> None:
    """Seed a few realistic incidents for the demo timeline (Kasetsart University campus)."""

    rows = [
        {
            "incident_id": "INC-2026-0001",
            "reported_at": "2026-01-20 09:05",
            "severity": "HIGH",
            "type": "Electrical fire",
            "address": "KU Dorm Zone (Bangkhen) - near N5",
            "lat": 13.8496,
            "lon": 100.5702,
            "notes": "Smoke from electrical cabinet; students evacuated; request: fastest-to-incident + nearest working hydrant",
        },
        {
            "incident_id": "INC-2026-0002",
            "reported_at": "2026-01-20 10:40",
            "severity": "MED",
            "type": "Chemical spill",
            "address": "Faculty of Science - Lab area (near N2)",
            "lat": 13.8518,
            "lon": 100.5684,
            "notes": "Small spill; needs hazmat + ventilation; keep public away; route must avoid pedestrian footpaths",
        },
        {
            "incident_id": "INC-2026-0003",
            "reported_at": "2026-01-20 12:15",
            "severity": "LOW",
            "type": "Gas leak",
            "address": "KU Student Center / cafeteria area (near HQ)",
            "lat": 13.8488,
            "lon": 100.5678,
            "notes": "Suspected LPG leak; isolate valves; standby unit; prefer shortest safe path",
        },
    ]

    df = pd.DataFrame(rows)

    # Store in session state so all tabs can reuse it
    st.session_state["gov_incidents"] = df

    # Also create a simple status log (for UI demo)
    st.session_state["gov_status"] = pd.DataFrame(
        [
            {"timestamp": "2026-01-20 09:08", "event": "Unit dispatched", "incident_id": "INC-2026-0001"},
            {"timestamp": "2026-01-20 09:12", "event": "Hydrant check", "incident_id": "INC-2026-0001"},
            {"timestamp": "2026-01-20 10:42", "event": "Safety perimeter", "incident_id": "INC-2026-0002"},
            {"timestamp": "2026-01-20 12:17", "event": "Valve isolation", "incident_id": "INC-2026-0003"},
        ]
    )

def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    init_state()

    # Header
    left, right = st.columns([0.72, 0.28])
    with left:
        st.title("🚒 " + APP_TITLE)
        st.caption(APP_SUBTITLE)
    with right:
        with st.container():
            st.session_state.role = st.selectbox("Role (RBAC Demo)", ["Public", "Responder", "City Ops", "Command Center"], index=["Public", "Responder", "City Ops", "Command Center"].index(st.session_state.role))
            st.session_state.degraded_mode = st.toggle("Degraded/Offline-first Mode", value=st.session_state.degraded_mode, help="จำลองโหมดเน็ตล่ม: คำนวณเส้นทางในเครื่อง + UI ลดภาระระบบ")
            st.markdown('<span class="badge">PDPA: least exposure</span> <span class="badge">Audit-ready</span> <span class="badge">Simulation</span>', unsafe_allow_html=True)

    st.divider()

    # One-click executive scenario
    with st.expander("🎬 One-click Governor Demo Scenario (Chatuchak pilot)", expanded=False):
        st.write("โหลดข้อมูลเดโมให้พร้อมพรีเซนต์: incidents + hydrant reality + sensors + responders + audit logs")
        c1, c2, c3 = st.columns([0.34, 0.33, 0.33])
        with c1:
            if st.button("⚡ Load demo data (reset)", use_container_width=True):
                load_governor_demo()
                st.success("Loaded demo scenario. ไปที่แท็บ Routing/Command เพื่อเริ่มเดโมได้ทันที")
        with c2:
            if st.button("🧹 Clear incidents only", use_container_width=True):
                st.session_state.incidents = []
                st.session_state.selected_incident_id = None
                add_audit("clear_incidents", {}, actor="operator")
                st.success("Cleared incidents")
        with c3:
            st.session_state.sim_smoke_factor = st.slider("Global smoke factor", 0.0, 2.0, float(st.session_state.sim_smoke_factor), 0.05)
            st.session_state.sim_alley_factor = st.slider("Global alley factor", 0.0, 2.0, float(st.session_state.sim_alley_factor), 0.05)


    # Key KPIs (top bar)
    incidents = st.session_state.incidents
    open_cnt = sum(1 for i in incidents if i["status"] not in ["Clear"])
    hydr_ready = sum(1 for h in st.session_state.hydrants.values() if h.status == "WORKING")
    hydr_total = len(st.session_state.hydrants)
    avg_routing_latency_ms = st.session_state.routing_cache.get("last_latency_ms", 42)

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        kpi("Open incidents", f"{open_cnt}")
    with k2:
        kpi("Working hydrants (pilot)", f"{hydr_ready}/{hydr_total}", hint="Hydrant Reality Layer + health checks")
    with k3:
        kpi("Routing latency", f"{avg_routing_latency_ms:.0f} ms", hint="Dijkstra + risk-weighted graph")
    with k4:
        q = len(st.session_state.audit_log)
        kpi("Evidence logs", f"{q}", hint="AAR + audit trail")

    st.markdown("<hr class='soft'/>", unsafe_allow_html=True)

    tabs = st.tabs(
        [
            "A) Citizen Intake & Triage",
            "B) Incident Model & Timeline",
            "C) Routing Engine",
            "D) Reality Layers (Hydrants/Alleys/Sensors)",
            "E) Dispatch & Command",
            "F) Maintenance & City Ops",
            "G) Governance & Evidence Pack",
        ]
    )

    # -----------------------------
    # A) Intake
    # -----------------------------
    with tabs[0]:
        colL, colR = st.columns([0.46, 0.54], gap="large")

        with colL:
            card(
                "LINE Chatbot Intake (Demo UI)",
                """
                <p class="small">
                ✅ แจ้งเหตุ + รูป/วิดีโอ + guided questions + <b>panic mode</b><br>
                ✅ Location capture: share location / LIFF permission<br>
                ✅ Duplicate / false report handling: merge by area–time–media
                </p>
                """,
            )
            st.write("")

            # Map click to set location
            st.subheader("📍 Location capture (click on map to set incident pin)")
            if folium is None or st_folium is None:
                st.error("Missing dependency: folium + streamlit-folium. See requirements.txt")
                st.stop()

            # Basic map for picking incident location
            pick_center = (13.8488, 100.5678)
            m_pick = folium.Map(location=pick_center, zoom_start=15, tiles="OpenStreetMap")
            folium.Marker(pick_center, tooltip="Kasetsart University (HQ / Command)").add_to(m_pick)
            pick_res = st_folium(m_pick, height=420, returned_objects=["last_clicked"])
            if pick_res and pick_res.get("last_clicked"):
                st.session_state.map_last_click = pick_res["last_clicked"]

            if st.session_state.map_last_click:
                st.success(f"Selected: lat={st.session_state.map_last_click['lat']:.6f}, lon={st.session_state.map_last_click['lng']:.6f}")
            else:
                st.info("Tip: Click anywhere on the map to set incident location.")

            st.write("")
            st.subheader("🧾 Report form (guided questions)")
            with st.form("intake_form", clear_on_submit=False):
                reporter = st.text_input("ผู้แจ้ง (ชื่อ/รหัสผู้ใช้ LINE)", value="citizen_anon_001")
                desc = st.text_area("รายละเอียดเหตุ (สั้น ๆ แต่ชัด)", value="มีกลุ่มควันหนา / ได้กลิ่นไหม้ / ได้ยินเสียงระเบิดเล็กน้อย")
                people_trapped = st.number_input("จำนวนคนติด (ประมาณ)", min_value=0, max_value=50, value=0, step=1)
                fuel_type = st.selectbox("เชื้อเพลิง/ต้นเหตุ", list(FUEL_TYPES.keys()), index=0)
                alley_constraint = st.selectbox("ข้อจำกัดซอย/ทางเข้า", ALLEY_CONSTRAINTS, index=1)
                panic = st.checkbox("🚨 Panic mode (เร่งด่วน)", value=False)

                media_files = st.file_uploader("แนบรูป/วิดีโอ (demo)", accept_multiple_files=True, type=["png", "jpg", "jpeg", "mp4", "mov"])
                submit = st.form_submit_button("ส่งแจ้งเหตุ → สร้างเคส")

            if submit:
                if not st.session_state.map_last_click:
                    st.error("กรุณาคลิกแผนที่เพื่อกำหนดพิกัดก่อนส่งแจ้งเหตุ")
                else:
                    lat = float(st.session_state.map_last_click["lat"])
                    lon = float(st.session_state.map_last_click["lng"])

                    duplicates = find_duplicates(st.session_state.incidents, lat, lon)
                    inc_id = f"INC-{datetime.now(BKK_TZ).strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
                    incident = {
                        "id": inc_id,
                        "created_at": now_iso(),
                        "reporter": reporter,
                        "desc": desc,
                        "lat": lat,
                        "lon": lon,
                        "people_trapped": int(people_trapped),
                        "fuel_type": fuel_type,
                        "alley_constraint": alley_constraint,
                        "panic": bool(panic),
                        "media_count": len(media_files) if media_files else 0,
                        "media_names": [f.name for f in media_files] if media_files else [],
                        "merged_into": None,
                        "status": "New",
                        "verified": False,
                        "confidence": 0.0,
                        "confidence_explain": {},
                        "risk_score": 0.0,
                        "risk_explain": {},
                        "assigned_unit": None,
                        "dispatch_mode": "Fastest-to-Incident",
                    }

                    conf, conf_explain = compute_confidence(incident, dup_count=len(duplicates))
                    incident["confidence"] = conf
                    incident["confidence_explain"] = conf_explain

                    risk, r_explain = compute_explainable_risk(incident, st.session_state.sensors)
                    incident["risk_score"] = risk
                    incident["risk_explain"] = r_explain

                    # Duplicate handling: do not auto-merge; mark needs verify if duplicates exist
                    if duplicates:
                        incident["status"] = "Needs Verify"
                        add_audit("intake_duplicate_suspected", {"incident": inc_id, "duplicates": [d["id"] for d in duplicates]}, actor="citizen")
                    else:
                        add_audit("intake_new", {"incident": inc_id}, actor="citizen")

                    st.session_state.incidents.append(incident)
                    st.session_state.selected_incident_id = inc_id

                    st.success(f"สร้างเคสสำเร็จ: {inc_id} | Confidence={conf:.2f} | Risk={risk:.1f}")
                    if media_files:
                        st.caption("Attached media (demo): " + ", ".join([f.name for f in media_files]))

        with colR:
            st.subheader("🗂️ Live Triage Queue")
            if not st.session_state.incidents:
                st.info("ยังไม่มีเคส — ลองสร้างเคสจากฟอร์มด้านซ้าย")
            else:
                # sort by risk desc then confidence desc
                sorted_inc = sorted(st.session_state.incidents, key=lambda x: (x.get("status") != "Clear", x["risk_score"], x["confidence"]), reverse=True)
                df = pd.DataFrame(
                    [
                        {
                            "Incident": i["id"],
                            "Status": i["status"],
                            "Risk": round(i["risk_score"], 1),
                            "Confidence": round(i["confidence"], 2),
                            "Panic": "YES" if i["panic"] else "",
                            "Trapped": i["people_trapped"],
                            "Fuel": i["fuel_type"],
                        }
                        for i in sorted_inc
                    ]
                )
                st.dataframe(df, use_container_width=True, hide_index=True)

                st.write("")
                st.subheader("✅ Verify / Merge (demo)")
                sel = st.selectbox("Select incident", [i["id"] for i in sorted_inc], index=0, key="select_incident_triage")
                inc = next(i for i in st.session_state.incidents if i["id"] == sel)

                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button("Mark Verified ✅", use_container_width=True, disabled=inc["status"] == "Verified"):
                        inc["verified"] = True
                        inc["status"] = "Verified"
                        add_audit("incident_verified", {"incident": inc["id"]}, actor="operator")
                        st.success("Verified")
                with c2:
                    if st.button("Mark False Report ❌", use_container_width=True):
                        inc["status"] = "Clear"
                        add_audit("incident_closed_false_report", {"incident": inc["id"]}, actor="operator")
                        st.warning("Closed as false report (demo)")
                with c3:
                    # Merge into
                    merge_targets = [i["id"] for i in st.session_state.incidents if i["id"] != inc["id"]]
                    target = st.selectbox("Merge into", ["—"] + merge_targets)
                    if st.button("Merge", use_container_width=True, disabled=(target == "—" or not merge_targets)):
                        inc["merged_into"] = target
                        inc["status"] = "Clear"
                        add_audit("incident_merged", {"incident": inc["id"], "into": target}, actor="operator")
                        st.success(f"Merged into {target} (demo)")

                st.write("")
                st.subheader("📌 Quick preview")
                if role_guard_can_view_pii(st.session_state.role):
                    st.json({k: inc[k] for k in ["id", "reporter", "desc", "lat", "lon", "confidence", "risk_score", "status"]})
                else:
                    st.json({k: inc[k] for k in ["id", "desc", "confidence", "risk_score", "status"]})

    # -----------------------------
    # B) Incident model & timeline
    # -----------------------------
    with tabs[1]:
        st.subheader("Incident Data Model (evidence-ready)")
        card(
            "Schema (demo)",
            """
            <p class="small mono">
            reporter / lat,lng / media / people_trapped / fuel_type / alley_constraints / entry_points / status / confidence / risk_score<br>
            + evidence-ready timeline: audit_log (AAR-ready)
            </p>
            """,
        )
        st.write("")

        if not st.session_state.incidents:
            st.info("สร้าง incident ก่อน (Tab A)")
        else:
            sel = st.selectbox("Select incident", [i["id"] for i in st.session_state.incidents[::-1]], index=0, key="select_incident_model")
            st.session_state.selected_incident_id = sel
            inc = next(i for i in st.session_state.incidents if i["id"] == sel)

            c1, c2 = st.columns([0.55, 0.45], gap="large")
            with c1:
                st.markdown("#### 🧾 Incident details")
                if role_guard_can_view_pii(st.session_state.role):
                    st.json(inc)
                else:
                    redacted = inc.copy()
                    redacted["reporter"] = "REDACTED"
                    redacted["media_names"] = ["REDACTED"] if redacted.get("media_names") else []
                    st.json(redacted)

            with c2:
                st.markdown("#### 🧠 Confidence & risk explainability")
                st.write("**Confidence** (dispatch certainty)")
                st.json(inc.get("confidence_explain", {}))
                st.write("**Risk score** (prioritization)")
                st.json(inc.get("risk_explain", {}))

            st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
            st.subheader("🧷 Evidence-ready timeline (Audit Log)")
            # filter audit log relevant to this incident
            rel = [x for x in st.session_state.audit_log if (inc["id"] in json.dumps(x.get("detail", {}), ensure_ascii=False))]
            df = pd.DataFrame(rel[-250:])
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("ยังไม่มีเหตุการณ์ใน timeline (ลอง verify/dispatch/simulate เพื่อสร้าง log)")

    # -----------------------------
    # C) Routing engine
    # -----------------------------
    with tabs[2]:
        st.subheader("Routing Engine (Dual Routing + Risk-weighted Dijkstra + RE-ROUTE)")
        if not st.session_state.incidents:
            st.info("สร้าง incident ก่อน (Tab A)")
        else:
            inc = next(i for i in st.session_state.incidents if i["id"] == (st.session_state.selected_incident_id or st.session_state.incidents[-1]["id"]))

            # controls
            left, mid, right = st.columns([0.33, 0.33, 0.34], gap="large")
            with left:
                mode = st.radio("Responder Mode", ["Fastest-to-Incident", "Fastest-to-Nearest-Working-Hydrant-then-Incident"], index=0)
                show_evac = st.toggle("Compute Evacuation Route", value=True)
                st.session_state.sim_smoke_factor = st.slider("Smoke factor (simulation)", 0.0, 2.0, float(st.session_state.sim_smoke_factor), 0.05)
                st.session_state.sim_alley_factor = st.slider("Alley constraints factor", 0.0, 2.0, float(st.session_state.sim_alley_factor), 0.05)

            with mid:
                # choose start node based on unit
                available_units = list(st.session_state.responders.values())
                unit_id = st.selectbox("Start from unit", [u.id for u in available_units], index=0)
                unit = st.session_state.responders[unit_id]
                start_node = unit.node_id

                selected_hydrant_id = st.selectbox(
                    "Hydrant selection (override)",
                    ["Auto (best WORKING)"] + list(st.session_state.hydrants.keys()),
                    index=0,
                    help="Auto จะเลือก hydrant WORKING ที่ทำให้เวลา (start->hydrant->incident) ต่ำสุด",
                )
                if selected_hydrant_id.startswith("Auto"):
                    selected_hydrant_id = None

                reroute = st.button("🔁 RE-ROUTE now", use_container_width=True)

            with right:
                st.markdown("##### Event-driven simulation")
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("🚧 Block alley A3 (demo)", use_container_width=True):
                        # block N5<->E3 (alley) + E3<->N6
                        st.session_state.blocked_edges.add(tuple(sorted(("N5", "E3")) + ["alley"]))
                        st.session_state.blocked_edges.add(tuple(sorted(("E3", "N6")) + ["alley"]))
                        add_audit("sim_blocked_edges", {"edges": ["N5-E3", "E3-N6"]}, actor="sim")
                        reroute = True
                    if st.button("✅ Clear all blocks", use_container_width=True):
                        st.session_state.blocked_edges = set()
                        add_audit("sim_clear_blocks", {}, actor="sim")
                        reroute = True
                with b2:
                    if st.button("💧 Hydrant HYD-104 FAIL", use_container_width=True):
                        if "HYD-104" in st.session_state.hydrants:
                            st.session_state.hydrants["HYD-104"].status = "FAILED"
                            st.session_state.hydrants["HYD-104"].last_updated = now_iso()
                            add_audit("sim_hydrant_failed", {"hydrant": "HYD-104"}, actor="sim")
                            reroute = True
                    if st.button("🟢 Restore hydrants", use_container_width=True):
                        for h in st.session_state.hydrants.values():
                            if h.status in ["FAILED"]:
                                h.status = "WORKING"
                                h.last_updated = now_iso()
                        add_audit("sim_restore_hydrants", {}, actor="sim")
                        reroute = True

                st.markdown("##### Notes")
                st.caption("Routing engine คำนวณในเครื่อง (offline-first) ด้วย Dijkstra บน risk-weighted graph — demo scale แต่ออกแบบให้ขยายได้ทั้งเมือง")

            # compute
            nodes = st.session_state.nodes
            edges = st.session_state.edges
            incident_node = nearest_node(nodes, inc["lat"], inc["lon"])

            t0 = time.perf_counter()
            selected_hid = None
            routes_payload = {}

            if mode == "Fastest-to-Incident":
                path, t_s = dijkstra(
                    nodes,
                    edges,
                    start_node,
                    incident_node,
                    st.session_state.blocked_edges,
                    st.session_state.sim_smoke_factor,
                    st.session_state.sim_alley_factor,
                )
                routes_payload["mode"] = mode
                routes_payload["path"] = path
                routes_payload["eta_s"] = t_s
                responder_poly = path_to_polyline(nodes, path) if path else None

            else:
                # override hydrant if selected
                if selected_hydrant_id is not None:
                    selected_hid = selected_hydrant_id
                    h = st.session_state.hydrants[selected_hid]
                    h_node = nearest_node(nodes, h.lat, h.lon)
                    p1, t1 = dijkstra(nodes, edges, start_node, h_node, st.session_state.blocked_edges, st.session_state.sim_smoke_factor, st.session_state.sim_alley_factor)
                    p2, t2 = dijkstra(nodes, edges, h_node, incident_node, st.session_state.blocked_edges, st.session_state.sim_smoke_factor, st.session_state.sim_alley_factor)
                    t_s = t1 + t2
                    routes_payload["mode"] = mode
                    routes_payload["hydrant"] = selected_hid
                    routes_payload["path_to_hydrant"] = p1
                    routes_payload["path_to_incident"] = p2
                    routes_payload["eta_s"] = t_s
                    responder_poly = path_to_polyline(nodes, p1) + path_to_polyline(nodes, p2)[1:] if p1 and p2 else None
                else:
                    best_h, best_t, p1, p2 = choose_best_working_hydrant(
                        nodes,
                        edges,
                        start_node,
                        incident_node,
                        st.session_state.hydrants,
                        st.session_state.blocked_edges,
                        st.session_state.sim_smoke_factor,
                        st.session_state.sim_alley_factor,
                    )
                    selected_hid = best_h
                    routes_payload["mode"] = mode
                    routes_payload["hydrant"] = best_h
                    routes_payload["path_to_hydrant"] = p1
                    routes_payload["path_to_incident"] = p2
                    routes_payload["eta_s"] = best_t
                    responder_poly = path_to_polyline(nodes, p1) + path_to_polyline(nodes, p2)[1:] if p1 and p2 else None

            evac_poly = None
            if show_evac:
                # Evac route: incident to nearest shelter
                shelters = [nid for nid, n in nodes.items() if n.kind == "shelter"]
                best = None
                best_t = float("inf")
                best_path = []
                for s in shelters:
                    p, t_s = dijkstra(nodes, edges, incident_node, s, st.session_state.blocked_edges, st.session_state.sim_smoke_factor, st.session_state.sim_alley_factor)
                    if t_s < best_t:
                        best_t = t_s
                        best = s
                        best_path = p
                if best_path:
                    routes_payload["evac_shelter"] = best
                    routes_payload["evac_eta_s"] = best_t
                    evac_poly = path_to_polyline(nodes, best_path)

            latency_ms = (time.perf_counter() - t0) * 1000.0
            st.session_state.routing_cache["last_latency_ms"] = latency_ms
            st.session_state.routing_cache["latest_routes_payload"] = routes_payload

            # event-driven reroute logging
            if reroute:
                add_audit("reroute", {"incident": inc["id"], "mode": mode, "latency_ms": round(latency_ms, 1)}, actor="operator")

            # display
            c1, c2, c3 = st.columns([0.38, 0.32, 0.30], gap="large")
            with c1:
                st.markdown("##### Result")
                eta_s = routes_payload.get("eta_s", float("inf"))
                if eta_s == float("inf") or (responder_poly is None):
                    st.error("No feasible route (blocked network) — try clearing blocks")
                else:
                    st.success(f"ETA (responder): {fmt_mins(eta_s)}   |  routing latency {latency_ms:.0f} ms")
                    if selected_hid:
                        st.info(f"Hydrant used: {selected_hid} (WORKING-first mode)")
                st.json(routes_payload)

            with c2:
                st.markdown("##### Explainable routing knobs")
                st.write("- Dual routing: Responder + Evacuation")
                st.write("- Risk-weighted graph: smoke / alley constraints / gates / one-way")
                st.write("- RE-ROUTE: event-driven recompute on blocked roads / hydrant status / smoke")
                st.write("")
                if st.session_state.blocked_edges:
                    st.warning(f"Blocked edges: {len(st.session_state.blocked_edges)}")
                st.caption("Design intent: ต่อให้ Google Maps บอกเวลาเร็ว แต่ไม่รู้ ‘จริงภาคสนาม’ เช่น hydrant ใช้ไม่ได้, ซอยแคบเข้าไม่ได้, ควันเพิ่ม ฯลฯ")

            with c3:
                st.markdown("##### Evacuation route")
                if routes_payload.get("evac_eta_s") is not None:
                    st.write(f"Shelter: `{routes_payload.get('evac_shelter')}` | ETA: {fmt_mins(routes_payload.get('evac_eta_s', 0))}")
                else:
                    st.write("Disabled")

            st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
            # Layer toggles (requested)
            lt1, lt2, lt3, lt4 = st.columns([0.22, 0.22, 0.22, 0.34])
            with lt1:
                show_hyd = st.toggle("Hydrant layer", value=True)
            with lt2:
                show_sen = st.toggle("Sensor layer", value=True)
            with lt3:
                show_g = st.toggle("Alley graph", value=True)
            with lt4:
                st.caption("Tip: ลองกด Block alley / Hydrant FAIL → ระบบจะ RE-ROUTE อัตโนมัติ")

            st.subheader("🗺️ Tactical Map (interactive)")
            center = (inc["lat"], inc["lon"])
            m = make_map(
                center=center,
                show_hydrants=show_hyd,
                show_sensors=show_sen,
                show_graph=show_g,
                show_heatmap=False,
                selected_incident=inc,
                route_polyline=responder_poly,
                evac_polyline=evac_poly,
                selected_hydrant_id=selected_hid,
            )
            st_folium(m, height=560, returned_objects=[])

    # -----------------------------
    # D) Reality layers
    # -----------------------------
    with tabs[3]:
        st.subheader("Reality Layers: ต่างจาก Maps เพราะมีข้อมูล ‘จริงภาคสนาม’")
        if folium is None or st_folium is None:
            st.error("Missing dependency: folium + streamlit-folium. See requirements.txt")
            st.stop()

        left, right = st.columns([0.32, 0.68], gap="large")

        with left:
            card(
                "Hydrant Reality Layer",
                """
                <p class="small">
                สถานะ + last updated + QR/NFC + รูปหลักฐาน + ระยะ/เวลาไปถึงเหตุ<br>
                + Hydrant Health Check workflow (log)
                </p>
                """,
            )
            show_hyd = st.toggle("Show hydrants", value=True)
            show_sen = st.toggle("Show sensors", value=True)
            show_graph = st.toggle("Show alley graph", value=True)
            show_heat = st.toggle("Show incident heatmap", value=True)

            st.markdown("##### Hydrant health check (demo)")
            hid = st.selectbox("Select hydrant", list(st.session_state.hydrants.keys()), index=0)
            h = st.session_state.hydrants[hid]
            st.write(f"Status: **{h.status}**")
            step = st.selectbox("Check step", ["Visual", "Flow", "Pressure", "Access/Gate", "QR/NFC scan"], index=0)
            result = st.selectbox("Result", ["OK", "Needs repair", "Blocked", "Low pressure", "Not found"], index=0)
            if st.button("Log health check", use_container_width=True):
                h.health_checks.append({"ts": now_iso(), "step": step, "result": result})
                h.last_updated = now_iso()
                # auto status heuristic
                if result in ["Blocked"]:
                    h.status = "BLOCKED"
                elif result in ["Low pressure"]:
                    h.status = "LOW_PRESSURE"
                elif result in ["OK"]:
                    h.status = "WORKING"
                add_audit("hydrant_health_check", {"hydrant": hid, "step": step, "result": result}, actor="city_ops")
                st.success("Logged")

            st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
            st.markdown("##### Sensor update simulation")
            if st.button("📡 Simulate new LoRa packets", use_container_width=True):
                for sn in st.session_state.sensors.values():
                    sn.smoke_ppm = clamp(sn.smoke_ppm + (math.sin(time.time()) * 3.5), 5, 120)
                    sn.co_ppm = clamp(sn.co_ppm + (math.cos(time.time()) * 1.2), 0.5, 40)
                    sn.temp_c = clamp(sn.temp_c + (math.sin(time.time()/2) * 1.0), 25, 65)
                    sn.last_seen = now_iso()
                add_audit("sensor_update", {"count": len(st.session_state.sensors)}, actor="lora_gateway")
                st.success("Updated sensor readings")

        with right:
            # map center at Chatuchak
            center = (13.6695, 100.6270)
            m = make_map(
                center=center,
                show_hydrants=show_hyd,
                show_sensors=show_sen,
                show_graph=show_graph,
                show_heatmap=show_heat,
                selected_incident=None,
                route_polyline=None,
                evac_polyline=None,
                selected_hydrant_id=None,
            )
            st_folium(m, height=680, returned_objects=[])

    # -----------------------------
    # E) Dispatch & Command
    # -----------------------------
    with tabs[4]:
        st.subheader("Dispatch & Command Center (ETA-minimization + Multi-unit strategy + Explainable Risk)")
        if not st.session_state.incidents:
            st.info("สร้าง incident ก่อน (Tab A)")
        else:
            inc = next(i for i in st.session_state.incidents if i["id"] == (st.session_state.selected_incident_id or st.session_state.incidents[-1]["id"]))

            colL, colR = st.columns([0.45, 0.55], gap="large")
            with colL:
                st.markdown("#### 🚒 Responder availability tracking")
                dfu = pd.DataFrame([u.__dict__ for u in st.session_state.responders.values()])
                st.dataframe(dfu[["id", "name", "kind", "node_id", "status", "last_ping"]], use_container_width=True, hide_index=True)

                if role_guard_can_dispatch(st.session_state.role):
                    st.markdown("#### 🎛️ Update unit status")
                    unit_id = st.selectbox("Unit", list(st.session_state.responders.keys()), index=0)
                    new_status = st.selectbox("Status", ["Available", "Busy", "En-route", "On-scene", "Need water", "Contained", "Clear"], index=0)
                    if st.button("Update status", use_container_width=True):
                        st.session_state.responders[unit_id].status = new_status
                        st.session_state.responders[unit_id].last_ping = now_iso()
                        add_audit("unit_status_update", {"unit": unit_id, "status": new_status}, actor="responder_app")
                        st.success("Updated")
                else:
                    st.info("Role นี้ดูได้ แต่สั่งการไม่ได้ (RBAC demo)")

            with colR:
                st.markdown("#### 🧠 Command: prioritize & dispatch")
                st.write(f"Selected incident: **{inc['id']}**  |  {status_badge(inc['status'])}")
                st.caption("Dispatch = เลือกหน่วยว่างที่ ETA ต่ำสุด ภายใต้โหมด routing ที่กำหนด")

                mode = st.selectbox("Dispatch mode", ["Fastest-to-Incident", "Fastest-to-Nearest-Working-Hydrant-then-Incident"], index=0)
                inc["dispatch_mode"] = mode

                if st.button("⚡ Auto-dispatch (ETA-minimization)", use_container_width=True, disabled=not role_guard_can_dispatch(st.session_state.role)):
                    nodes = st.session_state.nodes
                    edges = st.session_state.edges
                    incident_node = nearest_node(nodes, inc["lat"], inc["lon"])

                    best_unit = None
                    best_eta = float("inf")
                    best_payload = None

                    for u in st.session_state.responders.values():
                        if u.status != "Available":
                            continue
                        start_node = u.node_id
                        if mode == "Fastest-to-Incident":
                            p, eta = dijkstra(nodes, edges, start_node, incident_node, st.session_state.blocked_edges, st.session_state.sim_smoke_factor, st.session_state.sim_alley_factor)
                            payload = {"mode": mode, "path": p, "eta_s": eta}
                        else:
                            h, eta, p1, p2 = choose_best_working_hydrant(nodes, edges, start_node, incident_node, st.session_state.hydrants, st.session_state.blocked_edges, st.session_state.sim_smoke_factor, st.session_state.sim_alley_factor)
                            payload = {"mode": mode, "hydrant": h, "path_to_hydrant": p1, "path_to_incident": p2, "eta_s": eta}
                        if eta < best_eta:
                            best_eta = eta
                            best_unit = u
                            best_payload = payload

                    if best_unit is None or best_eta == float("inf"):
                        st.error("No available unit or no feasible route")
                    else:
                        # assign
                        best_unit.status = "En-route"
                        best_unit.last_ping = now_iso()
                        inc["assigned_unit"] = best_unit.id
                        inc["status"] = "Dispatched"
                        add_audit("dispatch", {"incident": inc["id"], "unit": best_unit.id, "eta_s": best_eta, "payload": best_payload}, actor="command_center")
                        st.success(f"Dispatched {best_unit.id} | ETA {fmt_mins(best_eta)}")

                # Multi-unit strategy (demo)
                st.markdown("#### 🧩 Multi-unit strategy (demo)")
                st.write("- 1st responder (motorbike) → verify + initial suppression")
                st.write("- fire truck → water plan + entry point")
                st.write("- water plan → nearest working hydrant or alternative water source")
                st.write("")

                st.markdown("#### 🔎 Explainable risk score")
                st.json(inc.get("risk_explain", {}))

    # -----------------------------
    # F) Maintenance & City ops
    # -----------------------------
    with tabs[5]:
        st.subheader("Maintenance & City Ops (Hydrant ticketing + readiness dashboard per district)")
        colL, colR = st.columns([0.42, 0.58], gap="large")

        with colL:
            st.markdown("#### 🎫 Hydrant Maintenance Workflow (Ticketing)")
            hid = st.selectbox("Hydrant", list(st.session_state.hydrants.keys()), index=0, key="ticket_hyd_sel")
            issue = st.selectbox("Issue", ["Blocked", "Broken", "Low pressure", "Need repaint", "Missing QR/NFC"], index=0)
            priority = st.selectbox("Priority", ["P1 (critical)", "P2", "P3"], index=0)
            assignee = st.text_input("Assign to (ทีม/ผู้รับผิดชอบ)", value="BMA-OPS-TEAM-3")
            if st.button("Open ticket", use_container_width=True, disabled=not role_guard_can_ops(st.session_state.role)):
                tid = f"TCK-{uuid.uuid4().hex[:6].upper()}"
                t = {"ticket_id": tid, "hydrant": hid, "issue": issue, "priority": priority, "assignee": assignee, "status": "Open", "opened_at": now_iso(), "closed_at": None}
                st.session_state.tickets.append(t)
                add_audit("ticket_opened", t, actor="city_ops")
                st.success(f"Opened {tid}")

            if st.session_state.tickets:
                st.markdown("#### 📋 Tickets")
                df = pd.DataFrame(st.session_state.tickets)
                st.dataframe(df, use_container_width=True, hide_index=True)

                st.markdown("#### ✅ Close ticket (demo)")
                tsel = st.selectbox("Ticket", [t["ticket_id"] for t in st.session_state.tickets], index=0)
                if st.button("Close (Fix done)", use_container_width=True, disabled=not role_guard_can_ops(st.session_state.role)):
                    for t in st.session_state.tickets:
                        if t["ticket_id"] == tsel:
                            t["status"] = "Closed"
                            t["closed_at"] = now_iso()
                            # update hydrant status optimistic
                            h = st.session_state.hydrants[t["hydrant"]]
                            h.status = "WORKING"
                            h.last_updated = now_iso()
                            add_audit("ticket_closed", {"ticket_id": tsel}, actor="city_ops")
                            break
                    st.success("Closed")
            else:
                st.info("ยังไม่มี ticket (ลองเปิด ticket)")

        with colR:
            st.markdown("#### 📊 Hydrant readiness dashboard (pilot)")
            hydrants = list(st.session_state.hydrants.values())
            dfh = pd.DataFrame([h.__dict__ for h in hydrants])
            readiness = (dfh["status"] == "WORKING").mean() * 100.0 if len(dfh) else 0.0
            aging_open = sum(1 for t in st.session_state.tickets if t["status"] == "Open")
            k1, k2, k3 = st.columns(3)
            with k1:
                kpi("Readiness rate", f"{readiness:.0f}%")
            with k2:
                kpi("Open tickets", f"{aging_open}")
            with k3:
                worst = dfh["status"].value_counts().to_dict()
                kpi("Status mix", f"{len(worst)} types", hint=str(worst))

            st.markdown("##### High-risk zones (demo)")
            st.caption("โซนที่ hydrant ไม่พร้อม + ซอยแคบ + sensor ควันสูง → ติดธง ‘เร่งแก้ไข/ซ้อมแผน’")

            # simple table
            zone_rows = []
            for hid, h in st.session_state.hydrants.items():
                # risk proxy: non-working hydrant + near smoke
                near_smoke = min(haversine_m(h.lat, h.lon, sn.lat, sn.lon) for sn in st.session_state.sensors.values())
                zone_risk = 0
                if h.status != "WORKING":
                    zone_risk += 20
                zone_risk += clamp((30 - (near_smoke / 100.0)) * 0.4, 0, 15)
                zone_rows.append({"Hydrant": hid, "Status": h.status, "ZoneRisk": round(zone_risk, 1), "NearestSensor_m": int(near_smoke)})
            zdf = pd.DataFrame(sorted(zone_rows, key=lambda x: x["ZoneRisk"], reverse=True)[:12])
            st.dataframe(zdf, use_container_width=True, hide_index=True)

    # -----------------------------
    # G) Governance, reliability, integration, evidence
    # -----------------------------
    with tabs[6]:
        st.subheader("Governance, Reliability, Integration & Evidence Pack (PDPA + RBAC + Audit + AAR)")
        colL, colR = st.columns([0.46, 0.54], gap="large")

        with colL:
            card(
                "PDPA / Data Governance Pack (demo)",
                """
                <p class="small">
                • Retention policy + RBAC + Audit log + process to request historical data<br>
                • Security/Privacy by design: least exposure + audit-ready<br>
                • Integration: CSV/GeoJSON/API — ใช้ “เลเยอร์เดียวกัน” ร่วมกันได้<br>
                </p>
                """,
            )
            st.write("")
            st.markdown("#### 🛡️ Security/Privacy knobs (demo)")
            retention_days = st.slider("Retention (days)", 1, 365, 90)
            st.checkbox("Least exposure (hide PII)", value=(not role_guard_can_view_pii(st.session_state.role)), disabled=True)
            st.checkbox("Audit log enabled", value=True, disabled=True)
            st.caption("Note: ใน production จะผูกกับ KMS, encryption-at-rest, per-field access controls, DLP scans")

            st.markdown("#### 🔌 Integration export (demo)")
            if st.session_state.incidents:
                inc_df = pd.DataFrame(st.session_state.incidents)
                csv_bytes = inc_df.to_csv(index=False).encode("utf-8")
                st.download_button("Download incidents.csv", data=csv_bytes, file_name="incidents.csv", mime="text/csv")
                geo = {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [i["lon"], i["lat"]]},
                            "properties": {"id": i["id"], "status": i["status"], "risk": i["risk_score"], "confidence": i["confidence"]},
                        }
                        for i in st.session_state.incidents
                    ],
                }
                st.download_button("Download incidents.geojson", data=json.dumps(geo, ensure_ascii=False, indent=2).encode("utf-8"), file_name="incidents.geojson", mime="application/geo+json")
            else:
                st.info("สร้าง incident ก่อนเพื่อ export")

        with colR:
            st.markdown("#### 📦 Evidence Pack (one-click)")
            if not st.session_state.incidents:
                st.info("สร้าง incident ก่อน (Tab A)")
            else:
                inc = next(i for i in st.session_state.incidents if i["id"] == (st.session_state.selected_incident_id or st.session_state.incidents[-1]["id"]))

                # Build a quick routes payload snapshot
                routes = st.session_state.routing_cache.get("latest_routes_payload", {})
                if not routes:
                    # minimal payload for export if routing not run yet
                    routes = {"note": "Run routing tab to generate detailed route payloads"}

                pack = make_evidence_pack_zip(
                    incident=inc,
                    routes=routes,
                    audit_log=st.session_state.audit_log,
                    hydrants=st.session_state.hydrants,
                    tickets=st.session_state.tickets,
                )
                st.download_button(
                    "⬇️ Download Evidence Pack (.zip)",
                    data=pack,
                    file_name=f"evidence_pack_{inc['id']}.zip",
                    mime="application/zip",
                    help="รวม incident + routing + audit log + hydrant layer + tickets + AAR HTML สำหรับส่งผู้บริหาร",
                )

                st.markdown("#### 📈 Reliability & monitoring (demo)")
                # mock metrics
                uptime = 99.96 if not st.session_state.degraded_mode else 99.50
                webhook_delay_ms = 180 if not st.session_state.degraded_mode else 420
                routing_latency_ms = st.session_state.routing_cache.get("last_latency_ms", 42)

                m1, m2, m3 = st.columns(3)
                with m1:
                    kpi("Uptime", f"{uptime:.2f}%")
                with m2:
                    kpi("Webhook delay", f"{webhook_delay_ms} ms")
                with m3:
                    kpi("Routing latency", f"{routing_latency_ms:.0f} ms")

                st.caption("Production intent: health dashboard (uptime, webhook delay, routing latency, queue backlog) + degrade mode")

                st.markdown("#### 🧾 AAR (After-Action Review) auto (demo)")
                # Show last logs
                last = pd.DataFrame(st.session_state.audit_log[-80:])
                if not last.empty:
                    st.dataframe(last, use_container_width=True, hide_index=True)
                else:
                    st.info("ยังไม่มี audit logs")

    st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
    st.caption("Demo scope: pilot graph (Chatuchak) but architecture supports full Bangkok scale with real alley graph + hydrant reality + sensor fusion + governance + evidence export.")


if __name__ == "__main__":
    main()
