# FireRoute Review Artifact Package

This repository is provided as a review artifact repository accompanying the FireRoute conference paper. It is intended to support inspection and reproduction of the main paper results through the included code, data, scenarios, outputs, and documentation.

## Package contents
- `app/` – prototype application, legacy source, core modules, and data loaders
- `data/graph/` – extracted graph files (`nodes.csv`, `edges.csv`, `points_of_interest.csv`)
- `data/assets/` – hydrants, sensors, responders, and hydrant health-check metadata
- `data/scenarios/` – named JSON scenario files used in the paper
- `data/governance/` – seed incident/status/ticket data for governance and evidence flows
- `scripts/` – validation, figure generation, scenario export, and table-generation utilities
- `outputs/` – generated figures, scenario summary table, packaged submission data, and sample evidence pack
- `docs/` – reproducibility notes, system overview, data dictionary, and code-to-data map
- `paper/current_manuscript/` – current paper PDF and LaTeX source files used to prepare the manuscript
- `REPRODUCE.md` – concise step-by-step reproduction guide at the package root

## Minimum artifact checklist
This package contains the minimum elements requested for paper-linked artifact availability:
- source code
- graph / assets / scenarios data
- outputs
- `README.md`
- `REPRODUCE.md`

