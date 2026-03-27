# Data Dictionary

## `data/graph/nodes.csv`
- `id`: unique node identifier used by the routing graph
- `lat`, `lon`: WGS84 coordinates
- `kind`: semantic class such as `station`, `road`, `shelter`, or `poi`
- `label`: human-readable label used in figures/docs

## `data/graph/edges.csv`
- `a`, `b`: endpoint node IDs
- `kind`: edge type (`main`, `alley`, `footpath`)
- `width_m`: nominal corridor width in meters
- `turn_radius_m`: nominal turn radius in meters
- `one_way`: whether edge traversal is directed
- `gate`: whether a gate penalty applies
- `base_speed_kmh`: nominal traversal speed used before risk penalties

## `data/assets/hydrants.csv`
- `status`: `WORKING`, `BLOCKED`, `LOW_PRESSURE`, `UNKNOWN`, or `FAILED`
- `evidence_photo`: placeholder path for UI/evidence integration

## `data/assets/hydrant_health_checks.json`
Per-hydrant list of health-check events used by the governance layer.

## `data/assets/sensors.csv`
- `smoke_ppm`, `co_ppm`, `temp_c`: environmental cues used by explainable risk
- `link`: mock backhaul reference (e.g., LoRa gateway ID)

## `data/assets/responders.csv`
- `kind`: `motorbike` or `truck`
- `node_id`: current graph anchor
- `status`: operational availability string used in dispatch logic

## `data/scenarios/*.json`
Named scenario controls for smoke, alley, and blocked-edge perturbations.
Each file carries an incident block plus top-level routing controls.

## `data/governance/*.csv`
Seed data for governance/demo views, incident timeline examples, and maintenance placeholders.
