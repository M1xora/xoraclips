import importlib
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

# main.py imports its siblings as `backend.<name>` (falling back to `<name>`),
# and tests import them as `<name>`. Make both names refer to ONE module
# object: a second copy would have its own state (e.g. the keys being scrubbed
# for the current request) and tests would pass or fail for the wrong reason.
for path in (str(BACKEND), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

for name in ("secrets_guard", "ai_errors", "youtube_errors", "title_rules", "captions", "video_engine", "clip_bounds", "clip_lengths"):
    sys.modules[name] = importlib.import_module(f"backend.{name}")
