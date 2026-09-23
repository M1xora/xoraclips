import sys
from pathlib import Path

# main.py imports video_engine as a top-level module, so tests do the same.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
