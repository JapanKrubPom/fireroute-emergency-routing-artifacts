from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/fireroute_submission_data.zip'
INCLUDE = [
    ROOT / 'data',
    ROOT / 'docs/REPRODUCE.md',
    ROOT / 'docs/DATA_DICTIONARY.md',
    ROOT / 'outputs/tables/table2_scenarios.csv',
    ROOT / 'outputs/evidence_demo/sample_evidence_pack.zip',
]

with zipfile.ZipFile(OUT, 'w', compression=zipfile.ZIP_DEFLATED) as z:
    for item in INCLUDE:
        if item.is_dir():
            for p in item.rglob('*'):
                if p.is_file():
                    z.write(p, p.relative_to(ROOT))
        elif item.is_file():
            z.write(item, item.relative_to(ROOT))

print(f'Wrote {OUT}')
