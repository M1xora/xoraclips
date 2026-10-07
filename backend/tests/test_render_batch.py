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
    monkeypatch.setattr(routes_render, "RENDER_BATCHES", type(routes_render.RENDER_BATCHES)())
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


# --- #70: URL, validation, titles, ZIP, forgetting --------------------------------------

import threading  # noqa: E402
import zipfile  # noqa: E402


def clips(*titles):
    return [{"title": t, "start_time": 10 * i, "end_time": 10 * i + 5} for i, t in enumerate(titles)]


def test_the_url_from_the_request_is_ignored_and_built_from_the_id(render):
    body = {"video_url": "http://169.254.169.254/latest/", "video_id": VIDEO_ID,
            "clips": clips("A"), "settings": {}}
    assert render.post("/api/render-batch", json=body, headers=ORIGIN).status_code == 200
    assert render.calls["download"][0][0] == f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest.mark.parametrize("change, status", [
    ({"video_id": "../../etc/x"}, 400),
    ({"clips": [{"title": 123, "start_time": 1, "end_time": 5}]}, 422),
    ({"clips": [{"title": "A", "start_time": 9, "end_time": 5}]}, 422),
    ({"clips": [{"title": "A", "start_time": -1, "end_time": 5}]}, 422),
    ({"clips": [{"title": "A"}]}, 422),
    ({"clips": clips(*["A"] * 51)}, 422),
])
def test_impossible_requests_are_refused_before_anything_runs(render, change, status):
    # With video_url, which older code required: only the change makes it impossible.
    body = {"video_id": VIDEO_ID, "video_url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
            "clips": clips("A"), "settings": {}, **change}
    assert render.post("/api/render-batch", json=body, headers=ORIGIN).status_code == status
    assert render.calls == {"download": [], "render": []}


def test_batch_ids_cannot_be_guessed(render):
    batch_id = start(render)
    assert len(batch_id) == len("batch_") + 32


def test_the_title_in_the_queue_never_changes_half_way(render, monkeypatch):
    seen_while_downloading = []
    real_download = routes_render.download_clip_segment

    def download(*args, **kwargs):
        seen_while_downloading.extend(b["clips"][0]["title"] for b in routes_render.RENDER_BATCHES.values())
        return real_download(*args, **kwargs)

    monkeypatch.setattr(routes_render, "download_clip_segment", download)
    one = [{"title": "Judul Asli", "start_time": 1, "end_time": 5}]
    batch_id = start(render, clips=one, title_text="Judul Dari Kolom")
    assert seen_while_downloading == ["Judul Dari Kolom"]
    assert progress(render, batch_id)["clips"][0]["title"] == "Judul Dari Kolom"
    assert render.calls["render"][0]["title_text"] == "Judul Dari Kolom"


def test_titles_off_keep_the_clip_name_in_the_queue(render):
    batch = progress(render, start(render, clips=clips("A"), title_position="none"))
    assert batch["clips"][0]["title"] == "A"
    assert render.calls["render"][0]["title_text"] is None


def zip_names(client, batch_id):
    res = client.get(f"/api/download-batch-zip/{batch_id}")
    assert res.status_code == 200
    path = video_engine.EXPORTS_DIR / f"xoraclips_{batch_id}.zip"
    with zipfile.ZipFile(path) as archive:
        return sorted(archive.namelist()), {i.compress_type for i in archive.infolist()}


def test_the_zip_uses_clip_titles_with_the_file_affixes_and_no_compression(render):
    batch_id = start(render, clips=clips("Sama", "Sama", "Lain/Judul"), title_prefix="[TAMPIL] ",
                     file_name_prefix="xc_", file_name_suffix="_final")
    names, compression = zip_names(render, batch_id)
    assert names == ["xc_LainJudul_final.mp4", "xc_Sama_final (1).mp4", "xc_Sama_final.mp4"]
    assert compression == {zipfile.ZIP_STORED}


def test_a_zip_made_on_request_has_the_same_names(render):
    batch_id = start(render, clips=clips("Satu", "Dua"), file_name_suffix="_x")
    before, _ = zip_names(render, batch_id)
    (video_engine.EXPORTS_DIR / f"xoraclips_{batch_id}.zip").unlink()
    after, _ = zip_names(render, batch_id)
    assert before == after == ["Dua_x.mp4", "Satu_x.mp4"]


def test_no_finished_clip_means_no_zip(render, monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("ffmpeg failed")
    monkeypatch.setattr(routes_render, "render_clip_to_mp4", broken)
    batch_id = start(render)
    batch = progress(render, batch_id)
    assert batch["overall_status"] == "error" and batch["zip_url"] is None
    assert render.get(f"/api/download-batch-zip/{batch_id}").status_code == 404
    assert not (video_engine.EXPORTS_DIR / f"xoraclips_{batch_id}.zip").exists()


def test_a_zip_that_fails_half_way_leaves_nothing_to_serve(render, monkeypatch):
    batch_id = start(render)
    real_write = zipfile.ZipFile.write

    def failing_write(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(zipfile.ZipFile, "write", failing_write)
    res = render.get(f"/api/download-batch-zip/{batch_id}")
    assert res.status_code == 500 and res.json() == {"detail": "Could not make the ZIP. Please try again."}
    assert list(video_engine.EXPORTS_DIR.glob(f"xoraclips_{batch_id}*")) == []
    monkeypatch.setattr(zipfile.ZipFile, "write", real_write)
    assert render.get(f"/api/download-batch-zip/{batch_id}").status_code == 200   # a retry works


def test_the_zip_is_made_off_the_event_loop_and_only_when_asked(render, monkeypatch):
    threads = {}
    real_write = routes_render.write_zip

    def write(files, target):
        threads["zip"] = threading.current_thread()
        return real_write(files, target)

    monkeypatch.setattr(routes_render, "write_zip", write)
    batch_id = start(render)
    assert "zip" not in threads                       # not made at the end of the batch
    assert progress(render, batch_id)["zip_url"] == f"/api/download-batch-zip/{batch_id}"
    assert render.get(f"/api/download-batch-zip/{batch_id}").status_code == 200
    assert threads["zip"] is not threading.main_thread()


def test_a_zip_asked_for_while_rendering_is_never_kept(render, monkeypatch):
    real_render = routes_render.render_clip_to_mp4
    asked = []

    rendered = []

    def render_then_ask(**kwargs):
        if rendered:   # the second clip: the first one has finished
            batch_id = next(iter(routes_render.RENDER_BATCHES))
            res = render.get(f"/api/download-batch-zip/{batch_id}")
            asked.append((res.status_code, res.content[:2]))
        rendered.append(kwargs)
        real_render(**kwargs)

    monkeypatch.setattr(routes_render, "render_clip_to_mp4", render_then_ask)
    batch_id = start(render, clips=clips("Satu", "Dua"))
    assert asked == [(200, b"PK")]
    # The early ZIP was removed after it was sent; the final one has both clips.
    names, _ = zip_names(render, batch_id)
    assert names == ["Dua.mp4", "Satu.mp4"]


def test_file_name_affixes_keep_their_spaces(render):
    batch_id = start(render, clips=clips("Hook"), file_name_prefix="Part 1 - ", file_name_suffix=" final")
    names, _ = zip_names(render, batch_id)
    assert names == ["Part 1 - Hook final.mp4"]


def test_zip_names_are_unique_even_ignoring_case():
    assert routes_render.zip_entry_names(["Sama", "Sama", "Sama (1)", "Hook", "hook"]) == [
        "Sama.mp4", "Sama (1).mp4", "Sama (1) (1).mp4", "Hook.mp4", "hook (1).mp4"]


def test_a_clip_longer_than_thirty_minutes_is_refused(render):
    body = {"video_id": VIDEO_ID, "clips": [{"title": "A", "start_time": 0, "end_time": 30 * 60 + 1}], "settings": {}}
    res = render.post("/api/render-batch", json=body, headers=ORIGIN)
    assert res.status_code == 422 and "at most 30 minutes" in res.text


def test_a_running_batch_is_kept_and_a_finished_one_is_forgotten_after_an_hour(render, monkeypatch):
    now = [0.0]
    store = routes_render.JobStore(max_age=None, clock=lambda: now[0])
    monkeypatch.setattr(routes_render, "RENDER_BATCHES", store)
    store.add("running", {"clips": []})
    batch_id = start(render)
    now[0] = 3599
    assert store.lookup(batch_id) and store.lookup("running")
    now[0] = 10 ** 6
    assert store.lookup(batch_id) is None
    assert store.lookup("running") is not None   # a long render is never dropped


# --- the split_top_cam layout (#96) ------------------------------------------------------

def split_chain(ratio="9:16", background="black"):
    return video_engine.build_ffmpeg_filtergraph(
        aspect_ratio=ratio,
        background_style=background,
        streamer_preset="split_top_cam",
        face_box={"cx": 0.5, "cy": 0.35},
    )[0]


def test_the_split_boxes_fill_the_frame_exactly():
    assert video_engine.SPLIT_CAM_W == 1080
    assert video_engine.SPLIT_CAM_H + video_engine.SPLIT_GAME_H == 1920
    # Both heights are multiples of 16, which every H.264 encoder takes.
    assert video_engine.SPLIT_CAM_H % 16 == 0
    assert video_engine.SPLIT_GAME_H % 16 == 0
    # The feed gets the larger share, where the action is.
    assert video_engine.SPLIT_GAME_H > video_engine.SPLIT_CAM_H


def test_the_split_scales_both_boxes_to_the_full_width():
    chain = split_chain()
    assert "scale=1080:768[cam_box]" in chain
    assert "scale=1080:1152[game_box]" in chain
    assert "vstack=inputs=2[layout_base]" in chain


def test_the_split_needs_no_padding_and_leaves_no_bars():
    """The old layout padded a 540px stack into a 1080px frame, which is
    where the bars came from. A full-width stack pads nothing."""
    chain = split_chain()
    assert "pad=" not in chain
    assert "overlay=" not in chain


@pytest.mark.parametrize("ratio", ["9:16", "1:1", "4:3", "16:9"])
def test_the_split_is_the_same_whatever_ratio_is_picked(ratio):
    assert split_chain(ratio) == split_chain("9:16")


@pytest.mark.parametrize("background", ["black", "blurred"])
def test_the_split_ignores_the_background_since_nothing_shows_through(background):
    assert split_chain(background=background) == split_chain(background="black")


def test_the_split_crops_the_cam_around_the_face():
    chain = video_engine.build_ffmpeg_filtergraph(
        aspect_ratio="9:16", background_style="black", streamer_preset="split_top_cam",
        face_box={"cx": 0.8, "cy": 0.2},
    )[0]
    assert "iw*0.800-ow/2" in chain
    assert "ih*0.200-oh/2" in chain
