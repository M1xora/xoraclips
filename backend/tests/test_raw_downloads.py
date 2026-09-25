"""Raw video and raw clip downloads (#64): checked ID, server-built URL,
checked times, one title, unguessable jobs that are forgotten after an hour."""
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import routes_downloads
import video_engine
from job_store import JobStore, new_job_id

VIDEO_ID = "p1t-074cn38"
ORIGIN = {"Origin": "http://localhost:5174"}


@pytest.fixture
def api(monkeypatch):
    calls = {"video": [], "clip": [], "ffmpeg": []}

    def fake_full(url, out_path, progress=None):
        calls["video"].append(url)
        Path(out_path).write_bytes(b"V" * 5000)
        return out_path

    def fake_segment(url, start, end, name, *args, **kwargs):
        calls["clip"].append((url, start, end))
        path = video_engine.TEMP_DIR / name
        path.write_bytes(b"C" * 5000)
        return str(path)

    def fake_run(cmd, **kwargs):
        calls["ffmpeg"].append(cmd)
        shutil.copy(cmd[cmd.index("-i") + 1], cmd[-1])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(routes_downloads, "download_full_raw_video", fake_full)
    monkeypatch.setattr(routes_downloads, "download_clip_segment", fake_segment)
    monkeypatch.setattr(routes_downloads.subprocess, "run", fake_run)
    monkeypatch.setattr(routes_downloads, "raw_download_jobs", JobStore())
    monkeypatch.setattr(routes_downloads, "raw_clip_download_jobs", JobStore())
    client = TestClient(main.app)
    client.calls = calls
    return client


def clip_body(**extra):
    return {"video_id": VIDEO_ID, "video_url": "https://www.youtube.com/watch?v=" + VIDEO_ID,
            "start_time": 60, "end_time": 85, "title": "Nunggu Siap", **extra}


# --- the video --------------------------------------------------------------------------

@pytest.mark.parametrize("path, body", [
    ("/api/download-raw-video", {"video_id": "not-an-id"}),
    ("/api/download-raw-video", {"video_id": "--exec=calc"}),
    ("/api/download-raw-clip", clip_body(video_id="../../etc")),
])
def test_an_invalid_video_id_is_refused_before_anything_runs(api, path, body):
    res = api.post(path, json=body, headers=ORIGIN)
    assert res.status_code == 400
    assert api.calls == {"video": [], "clip": [], "ffmpeg": []}


def test_the_url_from_the_request_is_ignored_and_built_from_the_id(api):
    body = {"video_id": VIDEO_ID, "video_url": "http://169.254.169.254/latest/meta-data/"}
    assert api.post("/api/download-raw-video", json=body, headers=ORIGIN).status_code == 200
    body = clip_body(video_url="http://127.0.0.1:8000/api/cookies")
    assert api.post("/api/download-raw-clip", json=body, headers=ORIGIN).status_code == 200
    watch = f"https://www.youtube.com/watch?v={VIDEO_ID}"
    assert api.calls["video"] == [watch]
    assert [c[0] for c in api.calls["clip"]] == [watch]


def test_the_app_may_leave_the_url_out(api):
    res = api.post("/api/download-raw-video", json={"video_id": VIDEO_ID}, headers=ORIGIN)
    assert res.status_code == 200


# --- times ------------------------------------------------------------------------------

@pytest.mark.parametrize("times", [
    {"start_time": 85, "end_time": 60},          # backwards
    {"start_time": 60, "end_time": 60},          # empty
    {"start_time": -5, "end_time": 10},          # before the video
    {"start_time": 0, "end_time": 25 * 3600},    # longer than any video
    {"start_time": "NaN", "end_time": 10},
    {"start_time": 0, "end_time": "Infinity"},
])
def test_impossible_times_are_refused(api, times):
    res = api.post("/api/download-raw-clip", json=clip_body(**times), headers=ORIGIN)
    assert res.status_code == 422
    assert api.calls["clip"] == []


# --- titles and jobs --------------------------------------------------------------------

def test_a_clip_keeps_one_title_from_start_to_download(api):
    job = api.post("/api/download-raw-clip", json=clip_body(title='Nunggu: "Siap"?'), headers=ORIGIN).json()
    status = api.get(f"/api/download-raw-clip-status/{job['job_id']}").json()
    assert status["status"] == "ready"
    assert status["title"] == "Nunggu Siap (raw)"
    assert status["filename"] == "Nunggu Siap (raw).mp4"
    assert status["download_url"].endswith("?title=Nunggu%20Siap%20%28raw%29")


def test_a_clip_without_a_title_is_named_after_its_times_everywhere(api):
    job = api.post("/api/download-raw-clip", json=clip_body(title="  "), headers=ORIGIN).json()
    status = api.get(f"/api/download-raw-clip-status/{job['job_id']}").json()
    assert status["title"] == "clip_60_85 (raw)" and status["filename"] == "clip_60_85 (raw).mp4"


def test_a_full_video_is_named_after_its_title(api):
    job = api.post("/api/download-raw-video", json={"video_id": VIDEO_ID, "title": "Judul/Video"},
                   headers=ORIGIN).json()
    status = api.get(f"/api/download-raw-status/{job['job_id']}").json()
    assert status["status"] == "ready" and status["filename"] == "JudulVideo (Full Video).mp4"


def test_job_ids_cannot_be_guessed():
    ids = {new_job_id() for _ in range(100)}
    assert len(ids) == 100 and all(len(i) == 32 for i in ids)


def test_unknown_jobs_are_404(api):
    assert api.get("/api/download-raw-status/nope").status_code == 404
    assert api.get("/api/download-raw-clip-status/nope").status_code == 404


def test_a_finished_job_is_forgotten_after_an_hour_and_a_running_one_is_not():
    now = [0.0]
    jobs = JobStore(clock=lambda: now[0])
    jobs.add("done", {"status": "ready"})
    jobs.add("running", {"status": "downloading"})
    jobs.finish("done")
    now[0] = 3599
    assert jobs.lookup("done") and jobs.lookup("running")
    now[0] = 3600
    assert jobs.lookup("done") is None
    assert jobs.lookup("running") == {"status": "downloading"}
    now[0] = 10 ** 6
    jobs.add("new", {})
    assert set(jobs) == {"running", "new"}


def test_a_failed_download_is_also_forgotten(api, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("YouTube said no")
    monkeypatch.setattr(routes_downloads, "download_full_raw_video", broken)
    job = api.post("/api/download-raw-video", json={"video_id": VIDEO_ID}, headers=ORIGIN).json()
    status = api.get(f"/api/download-raw-status/{job['job_id']}").json()
    assert status["status"] == "failed" and "YouTube said no" in status["error"]
    assert job["job_id"] in routes_downloads.raw_download_jobs._finished_at


def test_a_local_full_video_is_trimmed_instead_of_downloading_again(api):
    full = video_engine.EXPORTS_DIR / f"{VIDEO_ID}_raw_1.mp4"
    full.write_bytes(b"F" * (6 * 1024 * 1024))
    job = api.post("/api/download-raw-clip", json=clip_body(), headers=ORIGIN).json()
    assert api.get(f"/api/download-raw-clip-status/{job['job_id']}").json()["status"] == "ready"
    assert api.calls["clip"] == []
    assert api.calls["ffmpeg"][0][api.calls["ffmpeg"][0].index("-i") + 1] == str(full)
