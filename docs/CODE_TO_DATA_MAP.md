# Code-to-Data Extraction Map

This document records which sections of the original `fire_route_demo.py` should be externalized into data/config files for the full paper and reproducible repo.

## 1. `build_pilot_graph()`
Move hard-coded graph objects into:
- `data/graph/nodes.csv`
- `data/graph/edges.csv`
- `data/graph/points_of_interest.csv` (optional extension)

## 2. `build_default_hydrants()`
Move hydrant metadata into:
- `data/assets/hydrants.csv`
- `data/assets/hydrant_health_checks.json`

## 3. `build_default_sensors()`
Move sensor states into:
- `data/assets/sensors.csv`

## 4. `build_default_responders()`
Move responder metadata into:
- `data/assets/responders.csv`

## 5. Scenario controls in routing/governance tabs
Move smoke factors, alley factors, blocked edges, and incident seeds into:
- `data/scenarios/*.json`

## 6. `load_governor_demo()`
Move governance seed rows into:
- `data/governance/demo_incidents.csv`
- `data/governance/demo_status_log.csv`

## 7. `make_evidence_pack_zip()` outputs
Keep logic in code, but include one sample artifact in:
- `outputs/evidence_demo/sample_evidence_pack.zip`

## Keep in code
- dataclasses
- routing algorithms
- risk multipliers
- hydrant selection logic
- evidence-pack assembly
- UI rendering
