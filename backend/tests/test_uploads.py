"""
Studio uploads (background music, hook sound effect, watermark). Issue #48
made the three endpoints share one implementation; #58 added size limits,
one table of media types, generic errors, and saved names instead of server
paths. Uploads go to a temporary folder, never to backend/temp_clips/uploads.
"""
import re

import pytest
from fastapi.testclient import TestClient

import main
import routes_uploads
import uploads as upload_rules
import video_engine

MB = 1024 * 1024
KINDS = [
    # endpoint, file name, name prefix, url base
    ("/api/upload-bgm", "lagu latar.mp3", "bgm_", "/api/audio/"),
    ("/api/upload-sfx", "whoosh.wav", "sfx_", "/api/audio/"),
    ("/api/upload-watermark", "logo saya.png", "wm_", "/api/watermark/"),
]
AUDIO_TYPES = ".mp3, .wav, .m4a, .aac, .ogg, .flac"
IMAGE_TYPES = ".png, .jpg, .jpeg, .webp"


@pytest.fixture
def uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(video_engine, "TEMP_DIR", tmp_path)
    return tmp_path / "uploads"


def client():
    return TestClient(main.app)


def post(endpoint, name, content=b"isi file"):
    return client().post(endpoint, files={"file": (name, content)})


@pytest.mark.parametrize("endpoint, name, prefix, url_base", KINDS)
def test_a_valid_upload_is_saved_and_described_by_its_name(uploads, endpoint, name, prefix, url_base):
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
        "file_path": body["saved_name"],   # no server path any more (#58)
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


def test_a_very_long_name_is_shortened_and_keeps_its_extension(uploads):
    body = post("/api/upload-bgm", "a" * 300 + ".mp3").json()
    assert body["saved_name"].endswith(".mp3")
    assert len(body["saved_name"]) <= len("bgm_12345678_") + upload_rules.MAX_NAME_CHARS


@pytest.mark.parametrize("endpoint, name, allowed, kind", [
    ("/api/upload-bgm", "video.mp4", AUDIO_TYPES, "audio"),
    ("/api/upload-sfx", "catatan.txt", AUDIO_TYPES, "audio"),
    ("/api/upload-watermark", "lagu.mp3", IMAGE_TYPES, "image"),
    ("/api/upload-watermark", "tanpa_ekstensi", IMAGE_TYPES, "image"),
    ("/api/upload-watermark", "logo.svg", IMAGE_TYPES, "image"),   # ffmpeg cannot overlay SVG
])
def test_a_wrong_type_is_refused_with_the_same_message(uploads, endpoint, name, allowed, kind):
    res = post(endpoint, name)
    assert res.status_code == 400
    assert res.json() == {"detail": f"Unsupported {kind} format. Allowed: {allowed}"}
    assert not uploads.exists() or list(uploads.iterdir()) == []


@pytest.mark.parametrize("endpoint", [k[0] for k in KINDS])
def test_a_request_without_a_file_is_refused(uploads, endpoint):
    res = client().post(endpoint)
    assert res.status_code == 422


# --- size limits (#58) ------------------------------------------------------------------

@pytest.mark.parametrize("endpoint, name, limit", [
    ("/api/upload-bgm", "besar.mp3", 50),
    ("/api/upload-watermark", "besar.png", 10),
])
def test_a_file_over_its_limit_is_refused_before_it_is_read(uploads, monkeypatch, endpoint, name, limit):
    reached = []
    monkeypatch.setattr(routes_uploads, "_save_upload", lambda *a: reached.append(a))
    res = post(endpoint, name, b"x" * (limit * MB + 100 * 1024))
    assert res.status_code == 413
    assert res.json() == {"detail": f"File too large: {'audio' if 'bgm' in endpoint else 'image'} files "
                                    f"can be at most {limit} MB"}
    assert reached == []


def test_a_file_just_over_the_limit_is_caught_while_writing_and_removed(uploads):
    # Inside the room left for the multipart envelope, so the first check lets it through.
    res = post("/api/upload-watermark", "pas.png", b"x" * (10 * MB + 1))
    assert res.status_code == 413
    assert list(uploads.iterdir()) == []


def test_a_file_at_the_limit_is_accepted(uploads):
    assert post("/api/upload-watermark", "pas.png", b"x" * (10 * MB)).status_code == 200


def test_an_upload_without_a_length_is_refused():
    def body():
        yield b"--x\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.mp3\"\r\n\r\nabc\r\n--x--\r\n"
    res = client().post("/api/upload-bgm", content=body(),
                        headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert res.status_code == 411


def test_a_failed_write_leaves_no_file_and_no_server_path_in_the_answer(uploads, monkeypatch):
    real_open = open

    def failing_open(path, mode="r", *args, **kwargs):
        if "w" in mode:
            handle = real_open(path, mode, *args, **kwargs)
            handle.write = lambda data: (_ for _ in ()).throw(OSError(f"disk full at {path}"))
            return handle
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", failing_open)
    res = post("/api/upload-bgm", "lagu.mp3")
    monkeypatch.undo()
    assert res.status_code == 500
    assert res.json() == {"detail": "Could not save the audio file"}
    assert list(uploads.iterdir()) == []


# --- serving (#58) ----------------------------------------------------------------------

@pytest.mark.parametrize("endpoint, name, served_at, media_type", [
    ("/api/upload-bgm", "LAGU.MP3", "/api/audio/", "audio/mpeg"),
    ("/api/upload-bgm", "lagu.m4a", "/api/audio/", "audio/mp4"),
    ("/api/upload-sfx", "efek.ogg", "/api/audio/", "audio/ogg"),
    ("/api/upload-sfx", "efek.flac", "/api/audio/", "audio/flac"),
    ("/api/upload-watermark", "Logo.PNG", "/api/watermark/", "image/png"),
    ("/api/upload-watermark", "logo.jpeg", "/api/watermark/", "image/jpeg"),
    ("/api/upload-watermark", "logo.webp", "/api/watermark/", "image/webp"),
])
def test_files_are_served_with_their_own_type(uploads, endpoint, name, served_at, media_type):
    saved = post(endpoint, name).json()["saved_name"]
    res = client().get(served_at + saved)
    assert res.status_code == 200
    assert res.headers["content-type"].split(";")[0] == media_type


def test_only_known_types_are_served(uploads):
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "wm_x_notes.txt").write_text("secret")
    assert client().get("/api/watermark/wm_x_notes.txt").status_code == 404
    assert client().get("/api/audio/wm_x_notes.txt").status_code == 404


# --- renders find uploads by name (#58) -------------------------------------------------

def test_a_render_finds_an_upload_by_name_or_by_an_old_full_path(uploads):
    saved = post("/api/upload-bgm", "lagu.mp3").json()["saved_name"]
    expected = str(uploads / saved)
    assert upload_rules.resolve_upload(saved, "bgm") == expected
    assert upload_rules.resolve_upload(rf"C:\old\server\temp_clips\uploads\{saved}", "bgm") == expected
    assert upload_rules.resolve_upload(f"/srv/app/temp_clips/uploads/{saved}", "bgm") == expected


@pytest.mark.parametrize("reference", [
    None, "", "bgm_missing.mp3",
    r"C:\Windows\win.ini", "/etc/passwd", r"..\..\cookies.txt",
    "wm_12345678_logo.png",       # an upload of another kind
])
def test_anything_else_is_ignored(uploads, reference):
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "wm_12345678_logo.png").write_bytes(b"png")
    assert upload_rules.resolve_upload(reference, "bgm") is None
