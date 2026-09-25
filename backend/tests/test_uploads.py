"""
Issue #48: the three upload endpoints (background music, hook sound effect,
watermark) share one implementation. These tests pin what they did before
that refactor, so it cannot change behaviour: they were written against the
old copies and must keep passing unchanged.

Uploads go to a temporary folder, never to backend/temp_clips/uploads.
"""
import re

import pytest
from fastapi.testclient import TestClient

import main

KINDS = [
    # endpoint, file name, name prefix, url base
    ("/api/upload-bgm", "lagu latar.mp3", "bgm_", "/api/audio/"),
    ("/api/upload-sfx", "whoosh.wav", "sfx_", "/api/audio/"),
    ("/api/upload-watermark", "logo saya.png", "wm_", "/api/watermark/"),
]
AUDIO_TYPES = ".mp3, .wav, .m4a, .aac, .ogg, .flac"
IMAGE_TYPES = ".png, .jpg, .jpeg, .webp, .svg"


@pytest.fixture
def uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOADS_DIR", tmp_path)
    return tmp_path


def post(endpoint, name, content=b"isi file"):
    return TestClient(main.app).post(endpoint, files={"file": (name, content)})


@pytest.mark.parametrize("endpoint, name, prefix, url_base", KINDS)
def test_a_valid_upload_is_saved_and_described(uploads, endpoint, name, prefix, url_base):
    content = b"\x00\x01 isi file asli \xff"
    res = post(endpoint, name, content)
    assert res.status_code == 200
    body = res.json()

    clean = re.sub(r"[^a-zA-Z0-9_.-]", "_", name)
    assert re.fullmatch(re.escape(prefix) + r"[0-9a-f]{8}_" + re.escape(clean), body["saved_name"])
    assert body == {
        "success": True,
        "filename": name,
        "saved_name": body["saved_name"],
        "file_path": str(uploads / body["saved_name"]),
        "url": url_base + body["saved_name"],
        "size_bytes": len(content),
    }
    assert (uploads / body["saved_name"]).read_bytes() == content


@pytest.mark.parametrize("endpoint, name", [
    ("/api/upload-bgm", "LAGU.MP3"),
    ("/api/upload-sfx", "Efek.FLAC"),
    ("/api/upload-watermark", "Logo.PNG"),
])
def test_upper_case_extensions_are_accepted(uploads, endpoint, name):
    assert post(endpoint, name).status_code == 200


def test_odd_characters_in_the_name_become_underscores(uploads):
    body = post("/api/upload-bgm", "lagu (remix) #1 é.mp3").json()
    assert body["saved_name"].endswith("_lagu__remix___1__.mp3")
    assert body["filename"] == "lagu (remix) #1 é.mp3"


@pytest.mark.parametrize("endpoint, name, allowed, kind", [
    ("/api/upload-bgm", "video.mp4", AUDIO_TYPES, "audio"),
    ("/api/upload-sfx", "catatan.txt", AUDIO_TYPES, "audio"),
    ("/api/upload-watermark", "lagu.mp3", IMAGE_TYPES, "image"),
    ("/api/upload-watermark", "tanpa_ekstensi", IMAGE_TYPES, "image"),
])
def test_a_wrong_type_is_refused_with_the_same_message(uploads, endpoint, name, allowed, kind):
    res = post(endpoint, name)
    assert res.status_code == 400
    assert res.json() == {"detail": f"Unsupported {kind} format. Allowed: {allowed}"}
    assert list(uploads.iterdir()) == []


@pytest.mark.parametrize("endpoint", [k[0] for k in KINDS])
def test_a_request_without_a_file_is_refused(uploads, endpoint):
    res = TestClient(main.app).post(endpoint)
    assert res.status_code == 422
