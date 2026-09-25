"""/api/render-batch with the download, captions and ffmpeg faked: what each
clip is rendered with (#58, #70)."""
import json

import pytest
from fastapi.testclient import TestClient

import main
import routes_render
import video_engine

VIDEO_ID = "p1t-074cn38"
ORIGIN = {"Origin": "http://localhost:5174"}


@pytest.fixture
def render(monkeypatch):
    calls = {"download": [], "render": []}

    def fake_download(url, start, end, name, status=None):
        calls["download"].append((url, start, end))
        path = video_engine.TEMP_DIR / name
        path.write_bytes(b"raw")
        return str(path)

    def fake_render(**kwargs):
        calls["render"].append(kwargs)
        with open(kwargs["output_mp4_path"], "wb") as f:
            f.write(b"mp4")

    monkeypatch.setattr(routes_render, "download_clip_segment", fake_download)
    monkeypatch.setattr(routes_render, "transcribe_clip_words", lambda *a, **k: [])
    monkeypatch.setattr(routes_render, "generate_ass_file", lambda **k: None)
    monkeypatch.setattr(routes_render, "render_clip_to_mp4", fake_render)
    client = TestClient(main.app)
    client.calls = calls
    return client


def start(client, clips=None, **settings):
    body = {"video_url": f"https://www.youtube.com/watch?v={VIDEO_ID}", "video_id": VIDEO_ID,
            "clips": clips or [{"title": "Klip Satu", "start_time": 10, "end_time": 20}],
            "settings": {"enable_face_tracking": False, **settings}}
    res = client.post("/api/render-batch", json=body, headers=ORIGIN)
    assert res.status_code == 200, res.text
    return res.json()["batch_id"]


def upload(client, endpoint, name):
    return client.post(endpoint, files={"file": (name, b"data")}, headers=ORIGIN).json()


def test_uploaded_files_reach_the_render_by_their_saved_name(render):
    bgm = upload(render, "/api/upload-bgm", "lagu.mp3")
    sfx = upload(render, "/api/upload-sfx", "whoosh.wav")
    wm = upload(render, "/api/upload-watermark", "logo.png")
    start(render, bgm_enabled=True, bgm_file_path=bgm["file_path"],
          hook_sfx_enabled=True, hook_sfx_file_path=sfx["file_path"],
          watermark_enabled=True, watermark_file_path=wm["file_path"])
    kwargs = render.calls["render"][0]
    folder = video_engine.TEMP_DIR / "uploads"
    assert kwargs["bgm_path"] == str(folder / bgm["saved_name"])
    assert kwargs["hook_sfx_path"] == str(folder / sfx["saved_name"])
    assert kwargs["watermark_image_path"] == str(folder / wm["saved_name"])


def progress(client, batch_id):
    line = [l for l in client.get(f"/api/render-progress/{batch_id}").text.splitlines() if l.startswith("data:")][-1]
    return json.loads(line[5:])


@pytest.mark.parametrize("settings", [
    {"bgm_enabled": True, "bgm_file_path": r"C:\Windows\win.ini"},
    {"watermark_enabled": True, "watermark_file_path": "/etc/passwd"},
    {"hook_sfx_enabled": True, "hook_sfx_file_path": "cookies.txt"},
])
def test_a_path_outside_the_uploads_never_reaches_ffmpeg(render, settings):
    batch = progress(render, start(render, **settings))
    assert render.calls == {"download": [], "render": []}
    assert batch["overall_status"] == "error"
    assert "Upload it again" in batch["clips"][0]["error"]


def test_an_upload_cleared_since_it_was_chosen_fails_with_a_clear_message(render):
    bgm = upload(render, "/api/upload-bgm", "lagu.mp3")
    (video_engine.TEMP_DIR / "uploads" / bgm["saved_name"]).unlink()
    batch = progress(render, start(render, bgm_enabled=True, bgm_file_path=bgm["file_path"]))
    assert batch["overall_status"] == "error" and "BGM file is no longer on the server" in batch["error_message"]


def test_a_text_watermark_ignores_an_old_image(render):
    start(render, watermark_enabled=True, watermark_type="text", watermark_text="@kanal",
          watermark_file_path="wm_gone_logo.png")
    assert render.calls["render"][0]["watermark_image_path"] is None
