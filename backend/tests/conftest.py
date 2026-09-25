import asyncio
import importlib
import ipaddress
import os
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


def backend_modules():
    """Dotted names of the backend's own modules, main and tests excluded."""
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND)
        if rel.parts[0] in ("tests", "__pycache__") or path.name in ("main.py", "__init__.py"):
            continue
        yield ".".join(rel.with_suffix("").parts)


for name in backend_modules():
    existing = sys.modules.get(name)
    if name.split(".")[0] in sys.stdlib_module_names or (
        existing is not None and not str(getattr(existing, "__file__", "")).startswith(str(BACKEND))
    ):
        raise RuntimeError(
            f"backend/{name.replace('.', '/')}.py shadows the module '{name}' from Python or a "
            "package: tests alias backend modules by their bare name. Rename it.")
    sys.modules[name] = importlib.import_module(f"backend.{name}")


# --- No real data files in tests (#61) ----------------------------------------
# A test once overwrote the real backend/cookies.txt: its fake was set on
# main.COOKIES_PATH after the endpoint had moved to a module with its own copy
# of that name (#60). Every backend module's data paths now point into the
# test's own temporary folder before the test runs, whatever the test fakes.

_DATA_PATHS = {
    "COOKIES_PATH": "cookies.txt",
    "TEMP_DIR": "temp_clips",
    "EXPORTS_DIR": "exports",
    "UPLOADS_DIR": "temp_clips/uploads",
}


def _loaded_backend_modules():
    seen = set()
    for key, module in list(sys.modules.items()):
        if module is None or id(module) in seen:
            continue
        origin = str(getattr(module, "__file__", "") or "")
        if origin.startswith(str(BACKEND)) and "tests" not in Path(origin).relative_to(BACKEND).parts:
            seen.add(id(module))
            yield module


@pytest.fixture(autouse=True)
def no_real_data_files(monkeypatch, tmp_path_factory):
    # Its own folder, not the test's tmp_path, which tests inspect themselves.
    data = tmp_path_factory.mktemp("backend_data")
    for module in _loaded_backend_modules():
        for name, relative in _DATA_PATHS.items():
            if hasattr(module, name):
                target = data / relative
                if not relative.endswith(".txt"):
                    target.mkdir(parents=True, exist_ok=True)
                monkeypatch.setattr(module, name, target)
    return data


# --- No real network or programs in tests (#61) ------------------------------
# Tests fake YouTube, Gemini, yt-dlp and ffmpeg. When code moves between
# modules (#60), a fake set on the old module no longer applies and a test
# could quietly reach the real thing. These guards stop the call AND fail the
# test at teardown: the backend has many `except Exception` blocks that would
# otherwise swallow the error and carry on down a fallback path.
#
# Not covered: code that runs when a module is imported (video_engine probes
# ffmpeg encoders at import), and asyncio connections to a bare IP on
# Windows (the Proactor loop does not call socket.connect; Linux CI does).

# Settings that make code talk to the network, from backend/.env or the shell.
_NETWORK_ENV = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
    "PROXY_URL", "WEBSHARE_PROXY", "WEBSHARE_USERNAME", "WEBSHARE_PASSWORD",
    "SUPADATA_API_KEYS", "SUPADATA_API_KEY",
)


def _is_loopback(host) -> bool:
    if host in ("localhost", "", None):
        return True
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def no_real_io(monkeypatch):
    violations = []

    def refuse(message):
        violations.append(message)
        raise RuntimeError(message)

    for var in _NETWORK_ENV:
        monkeypatch.delenv(var, raising=False)

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(real):
        def connect(sock, address):
            host = address[0] if isinstance(address, tuple) else address
            if not _is_loopback(host):
                refuse(f"A test tried to reach the network ({address!r}). Fake it instead.")
            return real(sock, address)
        return connect

    def guarded_getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host):
            refuse(f"A test tried to reach the network (DNS lookup of {host!r}). Fake it instead.")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect(real_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect(real_connect_ex))
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)

    def program_of(cmd):
        return cmd[0] if isinstance(cmd, (list, tuple)) and cmd else cmd

    def refuse_program(cmd, *args, **kwargs):
        refuse(f"A test tried to run a real program ({program_of(cmd)!r}). Fake subprocess instead.")

    class GuardedPopen(subprocess.Popen):
        """Still a Popen for isinstance(); refuses to start anything."""
        def __init__(self, cmd, *args, **kwargs):  # noqa: D401
            refuse_program(cmd)

    async def refuse_async(program, *args, **kwargs):
        refuse_program([program])

    monkeypatch.setattr(subprocess, "run", refuse_program)
    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)
    monkeypatch.setattr(os, "system", refuse_program)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse_async)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", refuse_async)

    yield violations

    if violations:
        pytest.fail("Real network or programs were used (possibly swallowed by an "
                    "`except Exception`):\n  " + "\n  ".join(violations), pytrace=False)
