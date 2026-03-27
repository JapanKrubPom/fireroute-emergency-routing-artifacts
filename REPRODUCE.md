# Reproduce FireRoute Paper Artifacts

## 1. Environment setup
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Validate the structured data package
```bash
python scripts/validate_data.py
```
This validates the extracted graph, assets, scenario files, and selected governance seeds.

## 3. Regenerate the scenario summary table
```bash
python scripts/generate_table2.py
```
Expected output:
- `outputs/tables/table2_scenarios.csv`

## 4. Regenerate figure assets (optional)
```bash
python scripts/generate_figure1.py
python scripts/generate_figure2.py
```
Expected outputs:
- `outputs/figures/figure1_architecture.pdf`
- `outputs/figures/figure1_architecture.png`
- `outputs/figures/figure2_pilot_map.pdf`
- `outputs/figures/figure2_pilot_map.png`

## 5. Launch the prototype (optional)
```bash
streamlit run app/main.py
```

## 6. Paper source and compiled manuscript
The current paper files are included in:
- `paper/current_manuscript/source/`

The latest compiled PDF included in this package is:
- `paper/current_manuscript/IEEE_BigDataService_2026_paper.pdf`

## 7. What this package reproduces
This package supports inspection and replay of the core paper artifacts:
- pilot graph nodes, edges, and points of interest
- hydrant, sensor, and responder assets
- named scenario JSON files used in evaluation
- scenario summary output table
- figure assets used in the paper package
- sample evidence-pack ZIP for governance/evidence demonstration

