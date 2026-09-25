import importlib
import ipaddress
import socket
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

# main.py imports its siblings as `backend.<name>` (falling back to `<name>`),
# and tests import them as `<name>`. Make both names refer to ONE module
# object: a second copy would have its own state (e.g. the keys being scrubbed
# for the current request) and tests would pass or fail for the wrong reason.
# Every module is covered, so a module split out of main.py (#60) is too.
for path in (str(BACKEND), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

for module_path in sorted(BACKEND.glob("*.py")):
    name = module_path.stem
    if name not in ("main", "__init__"):
        sys.modules[name] = importlib.import_module(f"backend.{name}")


# --- No real network or programs in tests (#61) ------------------------------
# Tests fake YouTube, Gemini, yt-dlp and ffmpeg. When code moves between
# modules (#60), a fake set on the old module no longer applies and a test
# could quietly reach the real thing. These guards make that fail loudly.

def _is_loopback(address) -> bool:
    host = address[0] if isinstance(address, tuple) else address
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Connections to anything but loopback fail (asyncio uses loopback itself)."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded(real):
        def connect(sock, address):
            if not _is_loopback(address):
                raise RuntimeError(f"A test tried to reach the network ({address!r}). Fake it instead.")
            return real(sock, address)
        return connect

    monkeypatch.setattr(socket.socket, "connect", guarded(real_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guarded(real_connect_ex))


@pytest.fixture(autouse=True)
def no_real_programs(monkeypatch):
    """subprocess.run / Popen fail unless the test fakes them (yt-dlp, ffmpeg...)."""
    def refuse(cmd, *args, **kwargs):
        program = cmd[0] if isinstance(cmd, (list, tuple)) and cmd else cmd
        raise RuntimeError(f"A test tried to run a real program ({program!r}). Fake subprocess instead.")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
