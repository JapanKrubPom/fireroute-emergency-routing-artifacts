# Reproduce FireRoute KU Pilot Outputs

## Environment
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Validate the extracted data package
```bash
python scripts/validate_data.py
```

## Regenerate Table II scenario outputs
```bash
python scripts/generate_table2.py
```
This writes `outputs/tables/table2_scenarios.csv`.

## Launch the prototype
```bash
streamlit run app/main.py
```

## What is reproducible in this package
- pilot graph nodes and edges
- hydrant, sensor, and responder assets
- named scenario files used to derive routing outputs
- a sample evidence-pack ZIP
- figure assets currently used in the paper package
