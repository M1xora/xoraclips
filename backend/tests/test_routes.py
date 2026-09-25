r"""
Issue #61: guards for splitting backend/main.py into modules (#60).

Moving an endpoint must not lose it, register it twice, change its address,
its parameters or its validation. The route list below is the readable
check; the API shape snapshot catches the rest (limits such as the 0-24h
frame timestamp, request models and their fields). The snapshot keeps only
what the app defines, not what the FastAPI version happens to print, so a
FastAPI upgrade does not break it.

After a deliberate API change, regenerate the snapshot:
    venv\Scripts\python backend\tests\test_routes.py
"""
import ast
import json
import socket
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import requests
from fastapi.routing import APIRoute

BACKEND = Path(__file__).resolve().parents[1]
for _path in (str(BACKEND), str(BACKEND.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import main  # noqa: E402

SNAPSHOT = Path(__file__).parent / "fixtures" / "api_shape_snapshot.json"

# (method, path, endpoint function, parameters)
ROUTES = [
    ("DELETE", "/api/cookies", "delete_youtube_cookies", ""),
    ("GET", "/api/audio/{file_name}", "get_audio_file", "path:file_name"),
    ("GET", "/api/clip-frame", "get_clip_frame", "query:timestamp,query:video_id"),
    ("GET", "/api/cookies", "get_youtube_cookies_status", ""),
    ("GET", "/api/detect-face", "detect_face", "query:timestamp,query:video_id"),
    ("GET", "/api/download-batch-zip/{batch_id}", "download_batch_zip", "path:batch_id"),
    ("GET", "/api/download-raw-clip-status/{job_id}", "get_raw_clip_download_status", "path:job_id"),
    ("GET", "/api/download-raw-status/{job_id}", "get_raw_download_status", "path:job_id"),
    ("GET", "/api/download-rendered/{file_name}", "download_rendered_file", "path:file_name,query:title"),
    ("GET", "/api/hardware-accel", "get_hardware_acceleration_status", ""),
    ("GET", "/api/health", "health_check", "query:refresh"),
    ("GET", "/api/models", "list_available_models", "header:x_gemini_api_key"),
    ("GET", "/api/render-progress/{batch_id}", "get_render_progress", "path:batch_id"),
    ("GET", "/api/supadata-usage", "supadata_usage_endpoint", "query:refresh"),
    ("GET", "/api/temp-storage-info", "get_temp_storage_info", ""),
    ("GET", "/api/watermark/{file_name}", "get_watermark_file", "path:file_name"),
    ("POST", "/api/analyze", "analyze_video", "body:request,header:x_gemini_api_key"),
    ("POST", "/api/caption-chunks", "get_caption_chunks", "body:request"),
    ("POST", "/api/clear-temp", "clear_temp_folder", ""),
    ("POST", "/api/cookies", "save_youtube_cookies", "body:req"),
    ("POST", "/api/download-raw-clip", "handle_download_raw_clip", "body:req"),
    ("POST", "/api/download-raw-video", "handle_download_raw_video", "body:req"),
    ("POST", "/api/render-batch", "start_batch_render", "body:request"),
    ("POST", "/api/upload-bgm", "upload_bgm", "body:file"),
    ("POST", "/api/upload-sfx", "upload_hook_sfx", "body:file"),
    ("POST", "/api/upload-watermark", "upload_watermark", "body:file"),
]

# Constraint keys an app sets on a field; everything else (title, format,
# contentMediaType...) is how a FastAPI version chooses to describe it.
_SCHEMA_KEYS = ("type", "$ref", "enum", "const", "default", "minimum", "maximum",
                "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "pattern")


def _simplify(schema):
    if not isinstance(schema, dict):
        return schema
    kept = {k: schema[k] for k in _SCHEMA_KEYS if k in schema}
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            kept[key] = _simplify(schema[key])
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            kept[key] = sorted((_simplify(s) for s in schema[key]),
                               key=lambda s: json.dumps(s, sort_keys=True))
    return kept


def api_shape(openapi: dict) -> dict:
    """The parts of the OpenAPI document a refactor must not change."""
    operations = {}
    for path, ops in openapi["paths"].items():
        for method, op in ops.items():
            body = op.get("requestBody", {})
            operations[f"{method.upper()} {path}"] = {
                "operationId": op.get("operationId"),
                "parameters": sorted(
                    ([p["in"], p["name"], p.get("required", False), _simplify(p.get("schema", {}))]
                     for p in op.get("parameters", [])),
                    key=lambda p: (p[0], p[1]),
                ),
                "body": {ct: _simplify(c.get("schema", {})) for ct, c in body.get("content", {}).items()},
                "body_required": body.get("required", False),
            }
    models = {
        name: {"required": sorted(s.get("required", [])),
               "properties": {k: _simplify(v) for k, v in s.get("properties", {}).items()}}
        for name, s in openapi.get("components", {}).get("schemas", {}).items()
        if name not in ("HTTPValidationError", "ValidationError")  # FastAPI's own
    }
    return json.loads(json.dumps({"operations": operations, "models": models}))


def api_routes(routes, prefix=""):
    """Every APIRoute with its full path. Routers included from routes_* modules
    (#60) are copied into app.routes by older FastAPI versions and kept as a
    wrapper (with `original_router`) by newer ones; both are walked."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        inner = getattr(route, "original_router", None)
        if inner is not None:
            context = getattr(route, "include_context", None)
            yield from api_routes(inner.routes, prefix + (getattr(context, "prefix", "") or ""))


def route_rows():
    def params(route):
        d = route.dependant
        found = []
        for kind, items in (("path", d.path_params), ("query", d.query_params),
                            ("header", d.header_params), ("body", d.body_params)):
            found += [f"{kind}:{p.name}" for p in items]
        return ",".join(sorted(found))

    return [
        (method, path, route.endpoint.__name__, params(route))
        for path, route in api_routes(main.app.routes)
        for method in route.methods
    ]


def test_every_route_exists_exactly_once():
    rows = route_rows()
    assert [row for row, n in Counter(rows).items() if n > 1] == []
    assert sorted(rows) == sorted(ROUTES)


def test_the_route_list_matches_what_the_app_serves():
    # Public output, independent of how FastAPI stores included routers.
    served = sorted((method.upper(), path) for path, ops in main.app.openapi()["paths"].items() for method in ops)
    assert served == sorted((method, path) for method, path, _, _ in ROUTES)


def test_the_api_shape_is_unchanged():
    assert api_shape(main.app.openapi()) == json.loads(SNAPSHOT.read_text(encoding="utf-8")), (
        "The API changed (parameters, limits or models). If that is deliberate, "
        "regenerate the snapshot (see this file's docstring).")


def test_the_origin_check_for_writes_is_installed():
    dispatchers = [getattr(m, "kwargs", {}).get("dispatch") for m in main.app.user_middleware]
    assert any(getattr(f, "__name__", "") == "refuse_writes_from_other_sites" for f in dispatchers)


BACKEND_FILES = sorted(
    str(p.relative_to(BACKEND)) for p in BACKEND.rglob("*.py")
    if p.name != "main.py" and p.relative_to(BACKEND).parts[0] not in ("tests", "__pycache__")
)


def imported_names(source: str) -> set:
    """Every module a file imports, relative imports written with their dots."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            names.add(base)
            for alias in node.names:
                names.add(f"{base}.{alias.name}" if node.module else base + alias.name)
    return names


@pytest.mark.parametrize("module", BACKEND_FILES)
def test_no_backend_module_imports_main(module):
    # A router that imports main would be a circular import (#60).
    names = imported_names((BACKEND / module).read_text(encoding="utf-8"))
    assert not names & {"main", "backend.main", ".main"}, names


def test_the_import_check_sees_every_way_of_importing_main():
    for source in ("import main", "from backend import main", "from . import main",
                   "from backend.main import app", "import backend.main"):
        assert imported_names(source) & {"main", "backend.main", ".main"}, source


# --- The guards in conftest.py really guard -----------------------------------
# These tests trigger the guards on purpose, so they clear the record the guard
# would otherwise fail them with at teardown.

def test_a_test_cannot_reach_the_network(no_real_io):
    with pytest.raises(RuntimeError, match="reach the network"):
        requests.get("https://www.youtube.com", timeout=5)
    no_real_io.clear()


def test_a_raw_socket_to_the_internet_is_refused(no_real_io):
    with socket.socket() as sock, pytest.raises(RuntimeError, match="reach the network"):
        sock.connect(("142.250.0.1", 443))
    no_real_io.clear()


def test_a_test_cannot_run_a_real_program(no_real_io):
    with pytest.raises(RuntimeError, match="real program"):
        subprocess.run(["ffmpeg", "-version"])
    with pytest.raises(RuntimeError, match="real program"):
        subprocess.Popen(["yt-dlp", "--version"])
    no_real_io.clear()


def test_a_swallowed_violation_still_fails_the_test(no_real_io):
    # What happens inside `try: ... except Exception: pass` in backend code.
    try:
        subprocess.run(["yt-dlp", "--version"])
    except Exception:
        pass
    assert len(no_real_io) == 1  # recorded: the fixture fails the test at teardown
    no_real_io.clear()


if __name__ == "__main__":
    SNAPSHOT.write_text(json.dumps(api_shape(main.app.openapi()), indent=1, sort_keys=True,
                                   ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {SNAPSHOT}")


def test_no_backend_module_points_at_the_real_data_files(no_real_data_files):
    # The guard that stopped a test overwriting the real backend/cookies.txt.
    import conftest
    real = {BACKEND / "cookies.txt", BACKEND / "temp_clips", BACKEND / "exports",
            BACKEND / "temp_clips" / "uploads"}
    checked = 0
    for module in conftest._loaded_backend_modules():
        for name in conftest._DATA_PATHS:
            if hasattr(module, name):
                checked += 1
                value = Path(getattr(module, name))
                assert value not in real, f"{module.__name__}.{name} is the real {value}"
                assert str(value).startswith(str(no_real_data_files)), f"{module.__name__}.{name} = {value}"
    assert checked >= 4  # main and video_engine at least


def test_saving_cookies_without_a_fake_never_touches_the_real_file(no_real_data_files):
    from fastapi.testclient import TestClient
    real = BACKEND / "cookies.txt"
    before = real.read_bytes() if real.exists() else None
    res = TestClient(main.app).post("/api/cookies", json={"cookies_content": "dari test"})
    assert res.status_code == 200
    assert (real.read_bytes() if real.exists() else None) == before


def test_clear_temp_in_a_test_never_empties_the_real_backend_folders(no_real_data_files):
    import routes_system
    assert not Path(routes_system._base_dir).samefile(BACKEND)
    temp = Path(routes_system.video_engine.TEMP_DIR)
    assert not temp.samefile(BACKEND / "temp_clips") if (BACKEND / "temp_clips").exists() else True


def test_only_video_engine_holds_the_data_locations():
    # A copy per module is how a test once overwrote the real cookies.txt:
    # its fake reached one copy while the endpoint used another (#63, #64).
    import importlib
    for path in BACKEND.glob("*.py"):
        if path.stem in ("video_engine", "__init__"):
            continue
        module = importlib.import_module(f"backend.{path.stem}")
        copies = [n for n in ("COOKIES_PATH", "TEMP_DIR", "EXPORTS_DIR") if hasattr(module, n)]
        assert copies == [], f"{path.name} keeps its own {copies}: read video_engine.<name> when used"


def test_the_windows_hotfix_runs_before_yt_dlp_wherever_it_is_imported():
    # youtube_source imports yt-dlp; it must load compat first (#66).
    names = imported_names((BACKEND / "youtube_source.py").read_text(encoding="utf-8"))
    source = (BACKEND / "youtube_source.py").read_text(encoding="utf-8")
    assert "backend.compat" in names or "compat" in names
    assert source.index("import compat") < source.index("import yt_dlp")
