r"""
Issue #61: guards for splitting backend/main.py into modules (#60).

Moving an endpoint must not lose it, register it twice, change its address,
its parameters or its validation. The route list below is the readable
check; the OpenAPI snapshot catches everything else (limits such as the
0-24h frame timestamp, request and response models).

After a deliberate API change, regenerate the snapshot:
    venv\Scripts\python -c "import sys,json; sys.path[:0]=['backend','.']; import main; open('backend/tests/fixtures/openapi_snapshot.json','w',encoding='utf-8').write(json.dumps(main.app.openapi(), indent=1, sort_keys=True, ensure_ascii=False)+'\n')"
"""
import ast
import json
import socket
import subprocess
from collections import Counter
from pathlib import Path

import pytest
import requests
from fastapi.routing import APIRoute

import main

BACKEND = Path(main.__file__).resolve().parent
SNAPSHOT = Path(__file__).parent / "fixtures" / "openapi_snapshot.json"

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


def route_rows():
    def params(route):
        d = route.dependant
        found = []
        for kind, items in (("path", d.path_params), ("query", d.query_params),
                            ("header", d.header_params), ("body", d.body_params)):
            found += [f"{kind}:{p.name}" for p in items]
        return ",".join(sorted(found))

    return [
        (method, route.path, route.endpoint.__name__, params(route))
        for route in main.app.routes if isinstance(route, APIRoute)
        for method in route.methods
    ]


def test_every_route_exists_exactly_once():
    rows = route_rows()
    doubles = [row for row, n in Counter(rows).items() if n > 1]
    assert doubles == []
    assert sorted(rows) == sorted(ROUTES)


def test_the_api_schema_is_unchanged():
    current = json.loads(json.dumps(main.app.openapi(), sort_keys=True))
    assert current == json.loads(SNAPSHOT.read_text(encoding="utf-8")), (
        "The API changed (parameters, limits or models). If that is deliberate, "
        "regenerate the snapshot (see this file's docstring).")


def test_the_origin_check_for_writes_is_installed():
    names = [getattr(m, "kwargs", {}).get("dispatch") for m in main.app.user_middleware]
    assert any(getattr(f, "__name__", "") == "refuse_writes_from_other_sites" for f in names)


@pytest.mark.parametrize("module", sorted(p.name for p in BACKEND.glob("*.py") if p.name != "main.py"))
def test_no_backend_module_imports_main(module):
    # A router that imports main would be a circular import (#60).
    tree = ast.parse((BACKEND / module).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {f"{node.module}.{alias.name}" for alias in node.names}
    assert not imported & {"main", "backend.main"}


# --- The guards in conftest.py really guard ----------------------------------

def test_a_test_cannot_reach_the_network():
    with pytest.raises(RuntimeError, match="reach the network"):
        requests.get("https://www.youtube.com", timeout=5)


def test_a_raw_socket_to_the_internet_is_refused():
    with socket.socket() as sock, pytest.raises(RuntimeError, match="reach the network"):
        sock.connect(("142.250.0.1", 443))


def test_a_test_cannot_run_a_real_program():
    with pytest.raises(RuntimeError, match="real program"):
        subprocess.run(["ffmpeg", "-version"])
    with pytest.raises(RuntimeError, match="real program"):
        subprocess.Popen(["yt-dlp", "--version"])
