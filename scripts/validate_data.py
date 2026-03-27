from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def main() -> None:
    checks = {
        'nodes': pd.read_csv(ROOT / 'data/graph/nodes.csv'),
        'edges': pd.read_csv(ROOT / 'data/graph/edges.csv'),
        'hydrants': pd.read_csv(ROOT / 'data/assets/hydrants.csv'),
        'sensors': pd.read_csv(ROOT / 'data/assets/sensors.csv'),
        'responders': pd.read_csv(ROOT / 'data/assets/responders.csv'),
    }
    for name, df in checks.items():
        print(f'{name}: {len(df)} rows')
    for p in sorted((ROOT / 'data/scenarios').glob('*.json')):
        obj = json.loads(p.read_text(encoding='utf-8'))
        print(f'scenario: {obj["scenario_id"]}')
    print('Validation complete.')

if __name__ == '__main__':
    main()
