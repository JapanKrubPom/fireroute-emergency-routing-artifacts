from pathlib import Path
import subprocess, sys
ROOT = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'app/main.py')], check=False)
