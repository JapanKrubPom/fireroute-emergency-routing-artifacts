import importlib.util
import json
import sys
import types
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'app/main.py'
OUT = ROOT / 'outputs/tables/table2_scenarios.csv'

fake_streamlit = types.ModuleType('streamlit')
fake_streamlit.session_state = {}
sys.modules['streamlit'] = fake_streamlit

spec = importlib.util.spec_from_file_location('fr_app', SRC)
mod = importlib.util.module_from_spec(spec)
sys.modules['fr_app'] = mod
spec.loader.exec_module(mod)

nodes, edges = mod.build_pilot_graph()
hydrants = mod.build_default_hydrants()

def blocked_key(a, b, kind):
    return tuple(sorted((a, b)) + [kind])

rows = []
for path in sorted((ROOT / 'data/scenarios').glob('*.json')):
    payload = json.loads(path.read_text(encoding='utf-8'))
    blocked = set(blocked_key(x['a'], x['b'], x['kind']) for x in payload.get('blocked_edges', []))
    direct_path, direct_eta = mod.dijkstra(nodes, edges, payload['start_node'], payload['incident_node'], blocked, payload['smoke_factor'], payload['alley_factor'])
    hid, chain_eta, p1, p2 = mod.choose_best_working_hydrant(nodes, edges, payload['start_node'], payload['incident_node'], hydrants, blocked, payload['smoke_factor'], payload['alley_factor'])
    rows.append({
        'scenario_id': payload['scenario_id'],
        'direct_eta_s': 'Infeasible' if direct_eta == float('inf') or direct_eta > 1e8 else round(direct_eta, 1),
        'selected_hydrant': hid or '---',
        'chain_eta_s': 'Infeasible' if chain_eta == float('inf') or chain_eta > 1e8 else round(chain_eta, 1),
        'direct_path': ' -> '.join(direct_path) if direct_path else '',
        'hydrant_path_1': ' -> '.join(p1) if p1 else '',
        'hydrant_path_2': ' -> '.join(p2) if p2 else '',
    })

pd.DataFrame(rows).to_csv(OUT, index=False)
print(f'Wrote {OUT}')
