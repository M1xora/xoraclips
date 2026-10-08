import os
import sys
import re
import json
import time
import shutil
import logging
import subprocess
import threading
import importlib.util
import unicodedata
import uuid
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("xoraclips.video-engine")

try:
    from backend.captions import (
        ChunkRules, DEFAULT_RULES, apply_text_case, build_caption_chunks,
        clean_display_word, ends_phrase, words_from_transcript,
    )
except ImportError:
    from captions import (
        ChunkRules, DEFAULT_RULES, apply_text_case, build_caption_chunks,
        clean_display_word, ends_phrase, words_from_transcript,
    )

BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp_clips"
EXPORTS_DIR = BASE_DIR / "exports"
FONTS_DIR = BASE_DIR / "fonts"
COOKIES_PATH = BASE_DIR / "cookies.txt"

# Issue #42: a YouTube video ID is exactly 11 of these characters. The one
# definition, used by main.py too.
_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")


def is_video_id(value: Optional[str]) -> bool:
    """True for a well-formed YouTube video ID."""
    return bool(value) and _VIDEO_ID_RE.fullmatch(value) is not None


def watch_url(video_id: str) -> str:
    """The YouTube page of a video. Routes build it from a checked ID and
    never pass a URL from the request on to yt-dlp (#42, #64)."""
    return f"https://www.youtube.com/watch?v={video_id}"

CASCADE_PATH = BASE_DIR / "haarcascade_frontalface_default.xml"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
FONTS_DIR.mkdir(parents=True, exist_ok=True)

def ensure_ffmpeg_in_path():
    """Auto-detect FFmpeg if it was installed via winget, scoop, or local paths but not in PATH."""
    if shutil.which("ffmpeg"):
        return
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidate_roots = [
        Path(local_app_data) / "Microsoft" / "WinGet" / "Packages" if local_app_data else None,
        Path("C:/Program Files/ffmpeg/bin"),
        Path("C:/ffmpeg/bin"),
    ]
    for root in candidate_roots:
        if root and root.exists():
            if (root / "ffmpeg.exe").exists():
                os.environ["PATH"] = str(root) + os.pathsep + os.environ.get("PATH", "")
                logger.info(f"Auto-added FFmpeg to PATH: {root}")
                return
            for exe in root.glob("**/ffmpeg.exe"):
                bin_dir = str(exe.parent)
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                logger.info(f"Auto-added FFmpeg to PATH: {bin_dir}")
                return


ensure_ffmpeg_in_path()

# Global lazy-loaded whisper model
_WHISPER_MODEL = None


def get_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        try:
            import whisper
            logger.info("Loading Whisper 'base' model for word-level timestamps...")
            _WHISPER_MODEL = whisper.load_model("base")
        except Exception as e:
            logger.warning(f"Could not load Whisper model: {e}")
            _WHISPER_MODEL = False
    return _WHISPER_MODEL if _WHISPER_MODEL is not False else None


def check_encoder_support(encoder_name: str) -> bool:
    """Check if a specific FFmpeg video encoder is operational on this system."""
    try:
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=0.2",
            "-c:v", encoder_name, "-f", "null", "-"
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False


ENCODER_CONFIGS: Dict[str, Tuple[str, List[str]]] = {
    "nvenc": ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]),
    "amf": ("h264_amf", ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cbr", "-b:v", "6M"]),
    "qsv": ("h264_qsv", ["-c:v", "h264_qsv", "-preset", "veryfast"]),
    "cpu": ("libx264", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]),
}

_DETECTED_SUPPORT: Optional[Dict[str, Any]] = None


def detect_hardware_support() -> Dict[str, Any]:
    """Detects host GPU/CPU hardware acceleration support and caches the result."""
    global _DETECTED_SUPPORT
    if _DETECTED_SUPPORT is not None:
        return _DETECTED_SUPPORT

    has_nvenc = check_encoder_support("h264_nvenc")
    has_amf = check_encoder_support("h264_amf")
    has_qsv = check_encoder_support("h264_qsv")

    if has_nvenc:
        recommended = "nvenc"
    elif has_amf:
        recommended = "amf"
    elif has_qsv:
        recommended = "qsv"
    else:
        recommended = "cpu"

    _DETECTED_SUPPORT = {
        "nvenc": has_nvenc,
        "amf": has_amf,
        "qsv": has_qsv,
        "cpu": True,
        "recommended": recommended,
    }
    return _DETECTED_SUPPORT


def get_preferred_video_encoder() -> Tuple[str, List[str]]:
    """
    Auto-detects the fastest available hardware encoder:
    1. NVIDIA NVENC (h264_nvenc)
    2. AMD AMF (h264_amf)
    3. Intel QuickSync (h264_qsv)
    4. Universal CPU software encoding (libx264)
    """
    support = detect_hardware_support()
    rec = support.get("recommended", "cpu")
    if rec in ENCODER_CONFIGS:
        codec, args = ENCODER_CONFIGS[rec]
        logger.info(f"Hardware acceleration auto-select: {codec} (rec: {rec}) enabled.")
        return codec, args

    return ENCODER_CONFIGS["cpu"]


def resolve_encoder(user_selection: Optional[str] = "auto") -> Tuple[str, List[str]]:
    """
    Resolves user selection ('auto', 'nvenc', 'amf', 'qsv', 'cpu') to (codec_name, ffmpeg_args).
    """
    sel = (user_selection or "auto").lower().strip()
    if sel == "auto":
        return get_preferred_video_encoder()

    if sel in ENCODER_CONFIGS:
        return ENCODER_CONFIGS[sel]

    # Check direct codec names
    for key, (codec, args) in ENCODER_CONFIGS.items():
        if sel == codec or sel == key:
            return codec, args

    return ENCODER_CONFIGS["cpu"]


ACTIVE_ENCODER_NAME, ACTIVE_ENCODER_ARGS = get_preferred_video_encoder()
USE_NVENC = (ACTIVE_ENCODER_NAME == "h264_nvenc")


def format_section_time(seconds: float) -> str:
    """Format seconds into HH:MM:SS.cs for yt-dlp section cutting."""
    total_seconds = max(0.0, seconds)
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = int(total_seconds % 60)
    cs = int(round((total_seconds - int(total_seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h:02d}:{m:02d}:{s:02d}.{cs:02d}"


def get_yt_dlp_cookies_args() -> List[str]:
    """Returns yt-dlp cookies arguments if cookies.txt exists and is non-empty."""
    if COOKIES_PATH.exists() and COOKIES_PATH.stat().st_size > 0:
        return ["--cookies", str(COOKIES_PATH)]
    return []


def get_yt_dlp_base_cmd() -> List[str]:
    """
    Returns base command for yt-dlp with JavaScript runtime and cookies.
    Always the backend's own Python (`python -m yt_dlp`), never a yt-dlp found
    on PATH: that one may belong to another Python without yt-dlp-ejs, the
    solver for YouTube's JavaScript challenge that requirements.txt installs
    (issue #76).
    """
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "yt-dlp is not installed in this Python environment. "
            "Please run 'pip install -r backend/requirements.txt'."
        )
    cmd = [sys.executable, "-m", "yt_dlp"]

    if shutil.which("node"):
        cmd.extend(["--js-runtimes", "node"])
    elif shutil.which("deno"):
        cmd.extend(["--js-runtimes", "deno"])

    if COOKIES_PATH.exists() and COOKIES_PATH.stat().st_size > 0:
        logger.info(f"Using YouTube cookies from: {COOKIES_PATH}")
        cmd.extend(["--cookies", str(COOKIES_PATH)])
    return cmd


# ── Audio-only downloads (issue #10) ─────────────────────────────────────
# A download sometimes came back as audio only, saved as .mp4 without an
# error, and the render then failed on "[0:v] matches no streams". One way
# it happens (checked with yt-dlp's own selector): a bare `best` takes an
# audio format whose video codec is not stated. Every format choice below
# demands a video codec, and since that may not be the only way, every
# download is also checked for a video track before it is used.
# Issue #76: with cookies YouTube sends a JavaScript challenge. yt-dlp answers
# it with yt-dlp-ejs and Node.js or Deno; without them it fails with "The page
# needs to be reloaded", the same way on every method, so the download stops.
def _challenge_solver_installed() -> bool:
    return importlib.util.find_spec("yt_dlp_ejs") is not None


def is_challenge_error(text: Optional[str]) -> bool:
    return "page needs to be reloaded" in (text or "").lower()


def challenge_hint() -> str:
    """What to do about YouTube's challenge on this machine."""
    if not _challenge_solver_installed():
        return (f"The YouTube challenge solver (yt-dlp-ejs) is not installed: stop the backend, run "
                f"'{sys.executable} -m pip install -r backend/requirements.txt', then start it again.")
    if not (shutil.which("node") or shutil.which("deno")):
        return "The YouTube challenge solver needs Node.js or Deno: install one, then restart the backend."
    return ("YouTube refused this session: re-import your YouTube cookies with the Cookies button, "
            "or try again later.")


FORMAT_1080 = "bestvideo[height<=1080]+bestaudio/best[height<=1080][vcodec!=none]/bestvideo+bestaudio/best[vcodec!=none]"
FORMAT_720 = "bestvideo[height<=720]+bestaudio/best[height<=720][vcodec!=none]/best[vcodec!=none]"
# Issue #44: one preview frame needs no audio. YouTube stopped serving format
# 18 (360p mp4 with audio), so "18/..." failed and every preview frame was
# the video's thumbnail. Video-only is enough; -S "res" is the SHORT side, so
# a vertical Short gets about 480px across too, and H.264 decodes anywhere.
# The split_top_cam layout (#96). Both boxes are the full frame width, and
# their heights add up to 1920 exactly, so the pair needs no padding and
# leaves no bars. 40/60 gives the content box the larger share, since that is
# where the action is; both heights are multiples of 16, which every H.264
# encoder is happy with.
SPLIT_CAM_W = 1080
SPLIT_CAM_H = 768
SPLIT_GAME_H = 1152
# The cam box is a close-up, not a second wide shot: it takes this share of
# the largest crop that fits its shape. Without it the crop would be the full
# source height, which also pins the face offsets to 0 and kills tracking.
# Used when no face was detected, and as the ceiling below.
SPLIT_CAM_ZOOM = 0.65

# Issue #105: with a fixed zoom the crop ignores how big the face actually is,
# so a small facecam drowns in the room around it. Measured on the three
# sample videos, the detected face was 163px, 300px and 499px wide — three
# times apart — and filled 17%, 30% and 51% of the cam box.
#
# The crop is therefore the face's own width times a margin, which keeps the
# face the same size in the box whatever the source does. The numbers come
# from trying the combinations against those three samples and scoring how
# far the face ends up from the centre of the box (0.5 = dead centre):
#
#   factor 2.5, ceiling 0.55  ->  0.23   (chosen)
#   factor 3.0, ceiling 0.55  ->  0.37
#   factor 3.5, ceiling 0.70  ->  0.70
#   the old fixed zoom        ->  0.94
#
# The ceiling matters as much as the factor: without it a large face gives a
# crop nearly as tall as the frame, which then has no room to slide and
# leaves the face wherever it was. At 0.55 of frame height there is always
# room left to move, enough for the 110px the face was measured to wander
# over a clip.
SPLIT_CAM_FACE_MARGIN = 2.5
SPLIT_CAM_MAX_SHARE = 0.55

FRAME_FORMAT = "bv*/b"
FRAME_SORT = "res:480,vcodec:h264,ext:mp4"
# A second YouTube would not give is not asked again for this long (#44).
FRAME_FAILURE_TTL = 600.0

AUDIO_ONLY_MESSAGE = (
    "YouTube only sent audio for this clip (no video track). "
    "Please try rendering again in a little while."
)
# A rejected (audio-only) download is retried with the same method after a
# pause, once per clip (not once per method), only when the rejection came
# back quickly, and with a short timeout. That bounds the extra wait to one
# quick rejection + the pause + one short retry. Few retries on purpose:
# each request while YouTube is limiting us can make the limit last longer
# (issue #9).
AUDIO_ONLY_RETRY_DELAY = 8
QUICK_REJECTION_SECONDS = 60
RETRY_TIMEOUT_SECONDS = 90
STREAM_URL_TIMEOUT = 45
PROBE_TIMEOUT = 20
DOWNLOAD_METHODS = 3
# Issue #92: a googlevideo stream URL carries an `expire` timestamp and the
# connection can drop mid-trim. These let ffmpeg pick the transfer back up
# instead of failing the whole method. They are input options, so they go
# before each `-i`, and they only apply to HTTP inputs.
RECONNECT_ARGS = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"]


def download_timeouts(clip_duration: float) -> dict:
    """Per-method timeouts, shared by the download and its worst-case bound."""
    d = max(1.0, clip_duration)
    return {
        # Minimum 300s, plus 5s per clip second: slow HLS/DASH on 60-90s clips.
        "hd": max(300, int(d * 5) + 120),
        "trim": max(120, int(d * 3) + 30),
        "720p": max(180, int(d * 3) + 60),
        # The one audio-only retry: short, but long enough for a long clip.
        "retry": max(RETRY_TIMEOUT_SECONDS, int(d * 2) + 30),
    }


def render_timeouts(clip_duration: float) -> dict:
    """Final render timeouts: 180s/240s were fixed, too short for 3-minute clips (#34)."""
    d = max(1.0, clip_duration)
    return {
        "encoder": max(180, int(d * 3) + 60),
        "cpu": max(240, int(d * 4) + 60),
    }


def streams_have_video(ffprobe_json: str) -> bool:
    """True if ffprobe's JSON lists a real video stream (cover art does not count)."""
    try:
        data = json.loads(ffprobe_json or "{}")
    except ValueError:
        return False
    return any(
        st.get("codec_type") == "video" and not (st.get("disposition") or {}).get("attached_pic")
        for st in data.get("streams") or []
    )


def probe_video(path) -> str:
    """
    'video', 'no_video', 'unreadable' (ffprobe could not read the file, e.g.
    truncated) or 'unchecked' (ffprobe itself cannot run: the file is kept).
    """
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v",
             "-show_entries", "stream=codec_type:stream_disposition=attached_pic",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f"Could not check the downloaded file for a video track ({e}); keeping it.")
        return "unchecked"
    if res.returncode != 0:
        logger.warning(f"ffprobe could not read {path}: {(res.stderr or '').strip()[:200]}")
        return "unreadable"
    return "video" if streams_have_video(res.stdout) else "no_video"


def probe_video_size(path) -> Optional[Tuple[float, float]]:
    """A video's (width, height) in pixels, or None when it cannot be read.

    Issue #105: the split layout's cam crop is sized against the source, and a
    face measured as a share of a 1920x1080 frame means something different on
    a 1280x720 one. None lets the caller fall back to its own default rather
    than render with a wrong crop.
    """
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT,
        )
        if res.returncode != 0:
            return None
        stream = (json.loads(res.stdout or "{}").get("streams") or [{}])[0]
        w, h = float(stream.get("width") or 0), float(stream.get("height") or 0)
        return (w, h) if w > 0 and h > 0 else None
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired,
            json.JSONDecodeError, ValueError, IndexError) as e:
        logger.warning(f"Could not read the size of {path} ({e}); using the default.")
        return None


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except Exception:
        pass


def _check_download(path: Path, label: str) -> str:
    """'ok', 'audio_only', 'unreadable' or 'missing' for a finished download attempt."""
    if not path.exists() or path.stat().st_size <= 10000:
        return "missing"
    size = path.stat().st_size
    verdict = probe_video(path)
    if verdict == "no_video":
        logger.warning(f"{label}: rejected, the file has no video track ({size} bytes, audio only)")
        _remove(path)
        return "audio_only"
    if verdict == "unreadable":
        logger.warning(f"{label}: rejected, the downloaded file cannot be read ({size} bytes)")
        _remove(path)
        return "unreadable"
    logger.info(f"{label}: downloaded {path} ({size} bytes)")
    return "ok"


def worst_case_download_seconds(clip_duration: float) -> dict:
    """
    An upper bound on a clip download (issue #10). "before": every method
    runs to its timeout, as before this issue. "after" adds an ffprobe check
    per attempt (4 at most: 3 methods + 1 retry) and the one audio-only
    retry: a quick rejection, the pause, stream URLs again (method 2) and
    the retry itself.
    """
    t = download_timeouts(clip_duration)
    before = t["hd"] + (STREAM_URL_TIMEOUT + t["trim"]) + t["720p"]
    retry = QUICK_REJECTION_SECONDS + AUDIO_ONLY_RETRY_DELAY + STREAM_URL_TIMEOUT + t["retry"]
    probes = (DOWNLOAD_METHODS + 1) * PROBE_TIMEOUT
    return {"before": before, "after": before + retry + probes}


def download_clip_segment(
    video_url: str,
    start_time: float,
    end_time: float,
    output_filename: str,
    on_status: Optional[Callable[[dict], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """
    Downloads only the requested time slice in high definition (1080p) using yt-dlp.
    Falls back to stream fetching + ffmpeg trimming, then to 720p.

    Every result must have a video track (issue #10). An audio-only result
    is deleted and, if it came back quickly, retried once after a pause;
    `on_status` hears about retries and method changes so the UI can show
    that the app is still working.
    """
    output_path = TEMP_DIR / output_filename
    if output_path.exists():
        try:
            output_path.unlink()
        except Exception:
            pass

    def notify(event: dict) -> None:
        if on_status:
            try:
                on_status(event)
            except Exception:
                pass

    # Sanitize video URL
    clean_url = video_url.strip()
    if not clean_url.startswith("http"):
        clean_url = f"https://www.youtube.com/watch?v={clean_url}"

    clip_duration = max(1.0, end_time - start_time)
    t_start_fmt = format_section_time(start_time)
    t_end_fmt = format_section_time(end_time)
    base_cmd = get_yt_dlp_base_cmd()

    timeouts = download_timeouts(clip_duration)
    timeout_sec = timeouts["hd"]

    state: Dict[str, Any] = {"err": "unknown", "audio_only": False, "retried": False,
                             "challenge": None, "real_err": ""}

    # Issue #92: the last method to run is not the one with the best reason. A
    # method that simply produced nothing leaves the placeholder below, which
    # would otherwise bury a real error ("403 Forbidden") from an earlier one.
    def placeholder(text: str) -> bool:
        """True when `text` is no real reason: the stand-in set before a method
        runs, or stderr that is only warnings (yt-dlp writes those on success)."""
        stripped = text.strip()
        if not stripped or stripped.endswith(": no usable file"):
            return True
        return all(line.strip().upper().startswith("WARNING:")
                   for line in stripped.splitlines() if line.strip())

    def record(text: str) -> None:
        """Keeps the last real reason any method gave, for the final message."""
        state["err"] = text
        if not placeholder(text):
            state["real_err"] = text

    def attempt(method: int, label: str, run: Callable[[Optional[int]], None]) -> bool:
        """Runs one method; after a quick audio-only rejection, once more (once per clip)."""
        cap: Optional[int] = None
        for try_no in (1, 2):
            # A timed-out run can leave a partial file: never let the next try use it.
            _remove(output_path)
            record(f"{label}: no usable file")
            started = clock()
            try:
                run(cap)
            except subprocess.TimeoutExpired as e:
                logger.warning(f"{label} timed out after {e.timeout}s for {clean_url}")
                record(f"{label} timed out after {e.timeout}s")
                return False
            except Exception as e:
                logger.warning(f"{label} failed ({e})")
                record(str(e))
                return False
            took = clock() - started
            verdict = _check_download(output_path, label)
            if verdict == "ok":
                return True
            if verdict == "unreadable":
                record(f"{label}: the downloaded file could not be read")
            if verdict != "audio_only":
                return False
            state["audio_only"] = True
            if try_no == 1 and took < QUICK_REJECTION_SECONDS and not state["retried"]:
                state["retried"] = True
                cap = timeouts["retry"]
                notify({"code": "audio_only_retry", "method": method, "methods": DOWNLOAD_METHODS,
                        "wait": AUDIO_ONLY_RETRY_DELAY})
                logger.info(f"{label}: retrying once in {AUDIO_ONLY_RETRY_DELAY}s")
                sleep(AUDIO_ONLY_RETRY_DELAY)
                continue
            return False
        return False

    # Method 1: yt-dlp --download-sections with multi-fragment acceleration & retries
    def method_1(cap: Optional[int] = None) -> None:
        cmd = [
            *base_cmd,
            "--download-sections", f"*{t_start_fmt}-{t_end_fmt}",
            "--force-keyframes-at-cuts",
            "-f", FORMAT_1080,
            "-N", "4",
            "--fragment-retries", "10",
            "--retries", "10",
            "--file-access-retries", "5",
            "-o", str(output_path),
            "--merge-output-format", "mp4",
            "--no-warnings",
            "--", clean_url
        ]
        logger.info(f"Downloading HD section ({clip_duration:.1f}s) {t_start_fmt} -> {t_end_fmt} for {clean_url} (timeout: {timeout_sec}s)")
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=min(timeout_sec, cap or timeout_sec))
        if res and res.stderr:
            record(res.stderr[:300])

    # Method 2: Fallback - Extract direct stream URLs with yt-dlp and slice using FFmpeg
    def method_2(cap: Optional[int] = None) -> None:
        url_cmd = [*base_cmd, "-g", "-f", FORMAT_1080, "--", clean_url]
        url_res = subprocess.run(url_cmd, capture_output=True, text=True, timeout=STREAM_URL_TIMEOUT)
        if url_res.returncode != 0 or not url_res.stdout.strip():
            record((url_res.stderr or "no stream URLs")[:300])
            return
        urls = url_res.stdout.strip().split("\n")
        video_stream = urls[0]
        audio_stream = urls[1] if len(urls) > 1 else urls[0]

        trim_timeout = timeouts["trim"]
        trim_cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
            *RECONNECT_ARGS,
            "-ss", str(start_time),
            "-i", video_stream,
            *RECONNECT_ARGS,
            "-ss", str(start_time),
            "-i", audio_stream,
            "-t", str(clip_duration),
            "-map", "0:v:0", "-map", "1:a:0?",
            *ACTIVE_ENCODER_ARGS,
            "-c:a", "aac",
            "-b:a", "192k",
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            str(output_path)
        ]
        # The error that matters is ffmpeg's, not the stream URLs' (issue #92): a
        # successful `yt-dlp -g` still writes to stderr, and without this the user
        # was shown that leftover instead of the reason the trim failed.
        trim_res = subprocess.run(
            trim_cmd, capture_output=True, text=True,
            timeout=min(trim_timeout, cap or trim_timeout),
        )
        if trim_res.returncode != 0:
            record((trim_res.stderr or "ffmpeg failed with no output").strip()[:300])

    # Method 3: Fallback - Download at 720p (vastly lower bandwidth, skips SABR/1080p throttling)
    def method_3(cap: Optional[int] = None) -> None:
        cmd_720p = [
            *base_cmd,
            "--download-sections", f"*{t_start_fmt}-{t_end_fmt}",
            "--force-keyframes-at-cuts",
            "-f", FORMAT_720,
            "-N", "4",
            "--fragment-retries", "10",
            "--retries", "10",
            "-o", str(output_path),
            "--merge-output-format", "mp4",
            "--no-warnings",
            "--", clean_url
        ]
        timeout_720p = timeouts["720p"]
        res_720p = subprocess.run(cmd_720p, capture_output=True, text=True, timeout=min(timeout_720p, cap or timeout_720p))
        if res_720p and res_720p.stderr:
            record(res_720p.stderr[:300])

    methods = [
        (1, "Method 1 (HD section)", method_1),
        (2, "Method 2 (stream URL trim)", method_2),
        (3, "Method 3 (720p section)", method_3),
    ]
    for number, label, run in methods:
        if number > 1:
            logger.info(f"{label}: trying after the previous method failed ({state['err'][:120]})")
            notify({"code": "next_method", "method": number, "methods": DOWNLOAD_METHODS})
        if attempt(number, label, run):
            return str(output_path)
        if is_challenge_error(state["err"]):
            # Every method runs the same yt-dlp: the others would fail the same way.
            state["challenge"] = state["err"]
            break

    if state["challenge"]:
        raise RuntimeError(f"YouTube asked for a challenge ({state['challenge'].strip()[:200]}). {challenge_hint()}")
    # The last method may have ended on a placeholder or on warnings alone; the
    # last real reason any of them gave says far more about why this failed.
    reason = state["err"]
    if placeholder(reason) and state["real_err"]:
        reason = state["real_err"]
    err_lower = reason.lower()
    if "confirm you're not a bot" in err_lower or "sign in" in err_lower or "login" in err_lower:
        raise RuntimeError("YouTube blocked video download (Bot verification). Please import/save your YouTube cookies using the 🍪 Cookies Manager button in the top navbar.")
    if state["audio_only"]:
        # A real error from the last method stays visible in the technical details.
        if placeholder(reason):
            raise RuntimeError(AUDIO_ONLY_MESSAGE)
        raise RuntimeError(f"{AUDIO_ONLY_MESSAGE} Last error: {reason[:200]}")
    raise RuntimeError(f"Failed to download video clip segment from YouTube ({reason}). Please try again or check your network/cookies.")


def download_full_raw_video(video_url: str, output_path: str, progress_callback=None) -> str:
    """
    Downloads the full raw video from YouTube in maximum quality (up to 1080p).
    Reports real-time progress to progress_callback if provided.
    """
    clean_url = video_url.strip()
    if not clean_url.startswith("http"):
        clean_url = f"https://www.youtube.com/watch?v={clean_url}"

    base_cmd = get_yt_dlp_base_cmd()
    cmd = [
        *base_cmd,
        "--no-colors",
        "-f", FORMAT_1080,
        "-o", str(output_path),
        "--merge-output-format", "mp4",
        "--newline",
        "--progress-template", "download:%(progress._percent_str)s|%(progress._downloaded_bytes_str)s|%(progress._total_bytes_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
        "--", clean_url
    ]
    logger.info(f"Downloading full raw video from {clean_url} to {output_path}...")

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    last_error = ""
    for line in iter(process.stdout.readline, ''):
        raw_line = line.strip()
        if not raw_line:
            continue
        clean_line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw_line).strip()
        if clean_line.startswith("ERROR:"):
            last_error = clean_line

        if clean_line.startswith("download:") and progress_callback:
            raw_data = clean_line[len("download:"):].strip()
            parts = raw_data.split("|")
            if len(parts) >= 5:
                pct_str, dl_str, tot_str, spd_str, eta_str = parts[0], parts[1], parts[2], parts[3], parts[4]
                try:
                    clean_pct = re.sub(r'[^0-9.]', '', pct_str)
                    pct_val = float(clean_pct) if clean_pct else 0.0
                except Exception:
                    pct_val = 0.0
                progress_callback({
                    "percent": pct_val,
                    "downloaded": dl_str.strip() if dl_str and dl_str != "NA" else f"{pct_val:.1f}%",
                    "total": tot_str.strip() if tot_str and tot_str != "NA" else "",
                    "speed": spd_str.strip() if spd_str and spd_str != "NA" else "",
                    "eta": eta_str.strip() if eta_str and eta_str != "NA" else ""
                })
        elif "[download]" in clean_line and progress_callback:
            match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*%', clean_line)
            if match:
                try:
                    pct_val = float(match.group(1))
                except Exception:
                    pct_val = 0.0
                spd_match = re.search(r'at\s+([0-9.]+\s*[a-zA-Z]+/s)', clean_line)
                eta_match = re.search(r'ETA\s+([0-9:]+)', clean_line)
                tot_match = re.search(r'of\s+~?([0-9.]+\s*[a-zA-Z]+)', clean_line)
                progress_callback({
                    "percent": pct_val,
                    "downloaded": f"{pct_val:.1f}%",
                    "total": tot_match.group(1) if tot_match else "",
                    "speed": spd_match.group(1) if spd_match else "",
                    "eta": eta_match.group(1) if eta_match else ""
                })
    process.stdout.close()
    returncode = process.wait()

    verdict = _check_download(Path(output_path), "Full raw video")
    if verdict == "ok":
        return str(output_path)
    if verdict == "audio_only":
        raise RuntimeError(AUDIO_ONLY_MESSAGE)
    if verdict == "unreadable":
        raise RuntimeError("The downloaded video file is damaged and cannot be read. Please try again.")

    if is_challenge_error(last_error):
        raise RuntimeError(f"YouTube asked for a challenge ({last_error[:200]}). {challenge_hint()}")
    raise RuntimeError(f"Failed to download raw video. Process exited with code: {returncode}")


def transcribe_clip_words(
    video_path: str,
    fallback_transcript: Optional[List[Dict[str, Any]]] = None,
    clip_start_time: float = 0.0,
    clip_end_time: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Extracts word-level timestamps using the analyzed video transcript.
    This guarantees 100% fidelity with the analyzed speech (no mis-speech or Whisper hallucinations).
    Timestamps are mapped relative to the sliced clip audio (0.0s = clip_start_time).
    Line timing and text cleaning live in captions.py, shared with the preview.
    Whisper is only used as a fallback if no video transcript is available.
    """
    # 1. Primary: Use the analyzed video transcript (exact matches from YouTube)
    if fallback_transcript:
        words = words_from_transcript(fallback_transcript, clip_start_time, clip_end_time)
        if words:
            logger.info(f"Using analyzed video transcript: mapped {len(words)} words for clip range [{clip_start_time:.1f}s -> {clip_end_time:.1f}s].")
            return words

    # 2. Secondary fallback: Whisper if no transcript was returned from YouTube
    whisper_model = get_whisper_model()
    if whisper_model is not None:
        try:
            logger.info("Running Whisper word-level transcription as fallback...")
            result = whisper_model.transcribe(video_path, word_timestamps=True, fp16=False)
            words = []
            for segment in result.get("segments", []):
                seg_words = []
                for w in segment.get("words", []):
                    raw_word = w.get("word", "").strip()
                    word_clean = clean_display_word(raw_word)
                    if word_clean:
                        seg_words.append({
                            "word": word_clean,
                            "start": max(0.0, float(w.get("start", 0.0))),
                            "end": max(float(w.get("start", 0.0)) + 0.1, float(w.get("end", 0.0))),
                            "break_after": ends_phrase(raw_word),
                        })
                    elif seg_words and ends_phrase(raw_word):
                        seg_words[-1]["break_after"] = True
                if seg_words:
                    seg_words[-1]["break_after"] = True
                words.extend(seg_words)
            if words:
                logger.info(f"Whisper transcribed {len(words)} words successfully.")
                return words
        except Exception as e:
            logger.warning(f"Whisper word transcription error: {e}")

    return []


def format_ass_timestamp(seconds: float) -> str:
    """Format seconds into ASS timestamp format: H:MM:SS.cs"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def wrap_title_smart(text: str, max_single_len: int = 22) -> Tuple[str, int]:
    """
    Wraps title cleanly into 1, 2, 3 or more balanced lines separated by \\N.
    Preserves manual newlines if present, otherwise balances words across lines.
    Returns (formatted_title, line_count).
    """
    raw = text.strip()
    if not raw:
        return "", 1

    # Preserve manual newlines if the user specifically broke lines
    if "\n" in raw:
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        return "\\N".join(lines), len(lines)

    words = raw.split()
    if len(words) <= 1:
        return raw, 1

    total_len = len(raw)
    if total_len <= max_single_len:
        return raw, 1

    # Determine target line count dynamically based on character count and max_single_len
    target_lines = min(4, max(2, math.ceil(total_len / max_single_len)))

    target_per_line = total_len / target_lines
    lines = []
    current_line = []
    current_len = 0

    for i, w in enumerate(words):
        remaining_words = len(words) - i
        remaining_lines = target_lines - len(lines)
        if remaining_lines > 1 and len(current_line) > 0 and (current_len + len(w) > target_per_line * 1.15 or remaining_words <= remaining_lines - 1):
            lines.append(" ".join(current_line))
            current_line = [w]
            current_len = len(w)
        else:
            current_line.append(w)
            current_len += len(w) + 1

    if current_line:
        lines.append(" ".join(current_line))

    return "\\N".join(lines), len(lines)


def is_emoji_char(ch: str) -> bool:
    """Checks if a character is an emoji, symbol, or emoji presentation modifier."""
    code = ord(ch)
    if (0x1F000 <= code <= 0x1FAFF or
        0x2600 <= code <= 0x27BF or
        0x2300 <= code <= 0x23FF or
        0x2B50 <= code <= 0x2B55 or
        code == 0x200D or
        0xFE00 <= code <= 0xFE0F or
        code == 0x20E3):
        return True
    cat = unicodedata.category(ch)
    return cat in ('So', 'Sk')


def has_emoji(text: Optional[str]) -> bool:
    """Returns True if the string contains one or more emoji characters."""
    if not text:
        return False
    return any(is_emoji_char(ch) for ch in text)


def split_text_and_emojis(text: str) -> List[Tuple[str, str]]:
    """Splits text into contiguous runs of ('emoji', text) and ('text', text)."""
    segments = []
    if not text:
        return segments
    current_type = None
    current_buf = []
    for ch in text:
        t = 'emoji' if is_emoji_char(ch) else 'text'
        if current_type is None:
            current_type = t
            current_buf.append(ch)
        elif t == current_type:
            current_buf.append(ch)
        else:
            segments.append((current_type, "".join(current_buf)))
            current_type = t
            current_buf = [ch]
    if current_buf:
        segments.append((current_type, "".join(current_buf)))
    return segments


def get_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    """Resolves font with fallback to Montserrat or default font."""
    fonts_dir = str(FONTS_DIR)
    for ext in [".ttf", ".otf", ""]:
        p = os.path.join(fonts_dir, f"{font_name}{ext}")
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    p_fallback = os.path.join(fonts_dir, "Montserrat.ttf")
    if os.path.exists(p_fallback):
        try:
            return ImageFont.truetype(p_fallback, size)
        except Exception:
            pass
    return ImageFont.load_default()


def get_emoji_font(size: int) -> Optional[ImageFont.FreeTypeFont]:
    """Finds and loads a color emoji font (seguiemj.ttf, NotoColorEmoji.ttf, etc.)."""
    env_emoji = os.environ.get("EMOJI_FONT_PATH", "").strip()
    candidates = [
        env_emoji if env_emoji else None,
        str(FONTS_DIR / "seguiemj.ttf"),
        str(FONTS_DIR / "NotoColorEmoji.ttf"),
        "C:/Windows/Fonts/seguiemj.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/google-noto-color-emoji/NotoColorEmoji.ttf",
        "/usr/share/fonts/opentype/noto/NotoColorEmoji.otf",
        "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception as e:
                logger.debug(f"Could not load emoji font {c}: {e}")
    return None


def render_title_overlay_png(
    title_text: str,
    output_png_path: str,
    font_name: str = "Montserrat",
    target_aspect_ratio: str = "9:16",
    font_size_preset: str = "medium",
    text_case: str = "uppercase",
    title_position: str = "auto",
    title_y_percent: Optional[float] = None,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
    title_font_size_preset: Optional[str] = None
) -> Optional[str]:
    """
    Renders the title with full-color emojis and bold styled typography into a transparent
    1080x1920 PNG overlay for seamless FFmpeg compositing.
    """
    if not title_text or title_position == "none":
        return None

    effective_title_preset = (title_font_size_preset or font_size_preset or "medium").lower()

    if effective_title_preset == "small":
        max_wrap_len = 24
    elif effective_title_preset == "big":
        max_wrap_len = 13
    else:  # medium
        max_wrap_len = 19

    # Format Title & Determine Line Count
    formatted_title, title_line_count = wrap_title_smart(
        apply_text_case(title_text, text_case),
        max_single_len=max_wrap_len
    )

    if not formatted_title:
        return None

    # Distinct, calibrated title font sizes based on preset
    if effective_title_preset == "small":
        title_font_size = 58 if title_line_count >= 3 else 68
    elif effective_title_preset == "big":
        title_font_size = 106 if title_line_count >= 3 else 124
    else:  # medium
        title_font_size = 82 if title_line_count >= 3 else 94

    # Create dummy draw to measure line widths and prevent edge overflow
    temp_draw = ImageDraw.Draw(Image.new("RGBA", (canvas_w, canvas_h)))
    text_font = get_font(font_name, title_font_size)
    emoji_font = get_emoji_font(int(title_font_size * 0.90))

    lines = [l.strip() for l in formatted_title.split("\\N") if l.strip()]
    if not lines:
        lines = [formatted_title]

    # Measure maximum line width to prevent clipping off screen edges
    max_line_w = 0
    for line in lines:
        seg_w = 0
        for kind, chunk in split_text_and_emojis(line):
            f = emoji_font if (kind == 'emoji' and emoji_font) else text_font
            bbox = temp_draw.textbbox((0, 0), chunk, font=f)
            seg_w += (bbox[2] - bbox[0])
        max_line_w = max(max_line_w, seg_w)

    max_allowed_w = canvas_w - 70  # 1010px safe width
    if max_line_w > max_allowed_w and max_line_w > 0:
        scale_factor = max_allowed_w / max_line_w
        title_font_size = max(40, int(title_font_size * scale_factor))
        text_font = get_font(font_name, title_font_size)
        emoji_font = get_emoji_font(int(title_font_size * 0.90))

    # Content boundaries for aspect ratios (Canvas is 1080x1920)
    if target_aspect_ratio == "1:1":
        content_top = 420
        content_bot = 1500
    elif target_aspect_ratio == "4:3":
        content_top = 555
        content_bot = 1365
    elif target_aspect_ratio == "16:9":
        content_top = 656
        content_bot = 1264
    else:
        content_top = 0
        content_bot = 1920

    line_step = int(title_font_size * 0.86)
    est_title_h = int(title_line_count * line_step)

    # Title Positioning: identical to ASS calculations
    if target_aspect_ratio != "9:16":
        default_title_y = max(20, content_top - est_title_h - 15)
        if title_y_percent is not None:
            title_y = int(1920 * (title_y_percent / 100.0))
        else:
            title_y = default_title_y
        max_safe_title_y = max(15, content_top - est_title_h - 5)
        title_y = min(title_y, max_safe_title_y)
    else:
        if title_line_count >= 3 and (title_y_percent is None or title_y_percent == 14.0):
            effective_title_y_pct = 10.5
        elif title_line_count == 2 and (title_y_percent is None or title_y_percent == 14.0):
            effective_title_y_pct = 13.5
        else:
            effective_title_y_pct = title_y_percent if title_y_percent is not None else 13.5
        title_y = max(20, min(1800, int(1920 * (effective_title_y_pct / 100.0))))

    # Create transparent canvas
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    stroke_width = max(3, int(title_font_size * 0.055))
    shadow_offset = max(2, int(title_font_size * 0.025))

    # Reference baseline height for uppercase text
    t_ref_bbox = draw.textbbox((0, 0), "HGY", font=text_font)
    t_ref_mid = (t_ref_bbox[1] + t_ref_bbox[3]) / 2.0

    for line_idx, line in enumerate(lines):
        line_top = title_y + (line_idx * line_step)
        segments = split_text_and_emojis(line)

        # 1. Measure total width
        segment_widths = []
        for kind, chunk in segments:
            f = emoji_font if (kind == 'emoji' and emoji_font) else text_font
            bbox = draw.textbbox((0, 0), chunk, font=f)
            w = bbox[2] - bbox[0]
            segment_widths.append(w)

        total_line_w = sum(segment_widths)
        start_x = (canvas_w - total_line_w) / 2.0

        # 2. Draw shadow first (for text segments)
        cur_x = start_x
        for (kind, chunk), w in zip(segments, segment_widths):
            if kind != 'emoji':
                draw.text(
                    (cur_x + shadow_offset, line_top + shadow_offset),
                    chunk,
                    font=text_font,
                    fill=(0, 0, 0, 160),
                    stroke_width=stroke_width,
                    stroke_fill=(0, 0, 0, 160)
                )
            cur_x += w

        # 3. Draw outline / stroke and color emojis
        cur_x = start_x
        for (kind, chunk), w in zip(segments, segment_widths):
            if kind == 'emoji' and emoji_font:
                e_bbox = draw.textbbox((0, 0), chunk, font=emoji_font)
                e_mid = (e_bbox[1] + e_bbox[3]) / 2.0
                offset_y = t_ref_mid - e_mid

                draw.text(
                    (cur_x, line_top + offset_y),
                    chunk,
                    font=emoji_font,
                    embedded_color=True
                )
            else:
                draw.text(
                    (cur_x, line_top),
                    chunk,
                    font=text_font,
                    fill=(255, 255, 255, 255),
                    stroke_width=stroke_width,
                    stroke_fill=(0, 0, 0, 255)
                )
            cur_x += w

    os.makedirs(os.path.dirname(output_png_path), exist_ok=True)
    img.save(output_png_path, "PNG")
    return output_png_path


def generate_ass_file(
    words: List[Dict[str, Any]],
    style_preset: str,
    font_name: str,
    output_ass_path: str,
    target_aspect_ratio: str = "9:16",
    font_size_preset: str = "medium",
    text_case: str = "uppercase",
    title_text: Optional[str] = None,
    title_position: str = "auto",
    title_duration: str = "entire",
    duration_seconds: float = 60.0,
    title_y_percent: Optional[float] = None,
    subtitle_y_percent: Optional[float] = None,
    subtitle_position_mode: str = "bottom",
    subtitle_center_y_percent: float = 50.0,
    skip_title: bool = False,
    title_font_size_preset: Optional[str] = None,
    chunk_rules: ChunkRules = DEFAULT_RULES
) -> str:
    """
    Generates an Advanced SubStation Alpha (.ass) subtitle and title file with karaoke / word-level animation.
    Enforces WrapStyle: 2 and short 1-to-3 word chunks so subtitles are ALWAYS strictly 1 line.
    Uses \\an2\\pos(540, Y) for bottom or \\an5\\pos(540, Y) for center to permanently freeze subtitle in place.
    Keeps title and subtitle snug and close to video content (top & bottom) without touching.
    Supports subtitle_position_mode ('bottom' | 'center') with custom center Y position.
    """
    effective_title_preset = (title_font_size_preset or font_size_preset or "medium").lower()

    if effective_title_preset == "small":
        max_wrap_len = 24
    elif effective_title_preset == "big":
        max_wrap_len = 13
    else:  # medium
        max_wrap_len = 19

    # 1. Format Title & Determine Line Count
    if title_text and title_position != "none":
        formatted_title, title_line_count = wrap_title_smart(
            apply_text_case(title_text, text_case),
            max_single_len=max_wrap_len
        )
    else:
        formatted_title, title_line_count = "", 1

    # 2. Font Sizes based on preset, with automatic scale-down for 3+ line titles
    # Subtitle font sizes based on font_size_preset
    if font_size_preset == "small":
        sub_font_size = 65
    elif font_size_preset == "big":
        sub_font_size = 94
    else:  # medium
        sub_font_size = 78

    # Title font sizes based on effective_title_preset
    if effective_title_preset == "small":
        title_font_size = 58 if title_line_count >= 3 else 68
    elif effective_title_preset == "big":
        title_font_size = 106 if title_line_count >= 3 else 124
    else:  # medium
        title_font_size = 82 if title_line_count >= 3 else 94

    # 3. Content boundaries for aspect ratios (Canvas is 1080x1920)
    if target_aspect_ratio == "1:1":
        content_top = 420
        content_bot = 1500
    elif target_aspect_ratio == "4:3":
        content_top = 555
        content_bot = 1365
    elif target_aspect_ratio == "16:9":
        content_top = 656
        content_bot = 1264
    else:
        content_top = 0
        content_bot = 1920

    # Tight line height step (0.86x) for close, compact multi-line title layout
    line_step = int(title_font_size * 0.86)
    est_title_h = int(title_line_count * line_step)
    est_sub_h = int(sub_font_size * 1.08)
    sub_align = 5 if subtitle_position_mode == "center" else 2

    # Title Positioning: keep it SNUG and CLOSE to the top of the video content
    if target_aspect_ratio != "9:16":
        # Snug title default: title bottom sits closer to content_top
        default_title_y = max(20, content_top - est_title_h - 15)
        if title_y_percent is not None:
            title_y = int(1920 * (title_y_percent / 100.0))
        else:
            title_y = default_title_y

        # Hard boundary: title bottom must stay at least 5px clear above content_top
        max_safe_title_y = max(15, content_top - est_title_h - 5)
        title_y = min(title_y, max_safe_title_y)

        # Subtitle Positioning:
        if subtitle_position_mode == "center":
            sub_y = int(1920 * (subtitle_center_y_percent / 100.0))
            sub_y = max(content_top + 40, min(content_bot - 40, sub_y))
        else:
            # Snug bottom default: subtitle sits closer below content_bot
            default_sub_y = content_bot + est_sub_h + 12
            if subtitle_y_percent is not None:
                sub_y = int(1920 * (1.0 - (subtitle_y_percent / 100.0)))
            else:
                sub_y = default_sub_y
            min_safe_sub_y = content_bot + est_sub_h + 8
            sub_y = max(sub_y, min_safe_sub_y)
    else:
        # 9:16 Fullscreen - title moved down closer to video center
        if title_line_count >= 3 and (title_y_percent is None or title_y_percent == 14.0):
            effective_title_y_pct = 10.5
        elif title_line_count == 2 and (title_y_percent is None or title_y_percent == 14.0):
            effective_title_y_pct = 13.5
        else:
            effective_title_y_pct = title_y_percent if title_y_percent is not None else 13.5
        title_y = max(20, min(1800, int(1920 * (effective_title_y_pct / 100.0))))

        if subtitle_position_mode == "center":
            sub_y = max(60, min(1860, int(1920 * (subtitle_center_y_percent / 100.0))))
        else:
            # Bottom subtitle moved middle a bit (closer to center, ~21% from bottom)
            effective_sub_y_pct = subtitle_y_percent if subtitle_y_percent is not None else 21.0
            sub_y = max(60, min(1880, int(1920 * (1.0 - (effective_sub_y_pct / 100.0)))))

    # Preset color schemes (ASS uses &HAABBGGRR in hex)
    if style_preset == "viral_pop":
        primary_color = "&H00FFFFFF"
        outline_color = "&H00000000"
        back_color = "&H80000000"
        highlight_color = "&H0000E6FF"  # #FFE600 Lemon Yellow
        outline_w = 4.8
        shadow_w = 2.0
    elif style_preset == "beast_punch":
        primary_color = "&H00FFFFFF"
        outline_color = "&H00111111"
        back_color = "&HA0000000"
        highlight_color = "&H0066FF00"  # #00FF66 High-voltage Neon Green
        outline_w = 5.0
        shadow_w = 2.2
    elif style_preset == "cyber_violet":
        primary_color = "&H00FFFFFF"
        outline_color = "&H00330033"
        back_color = "&H80500050"
        highlight_color = "&H00EF46D9"  # #D946EF Vivid Magenta
        outline_w = 4.8
        shadow_w = 2.0
    elif style_preset == "fire_red":
        primary_color = "&H00FFFFFF"
        outline_color = "&H00000020"
        back_color = "&H90000060"
        highlight_color = "&H002E2EFF"  # #FF2E2E Blazing Fire Red
        outline_w = 4.8
        shadow_w = 2.0
    elif style_preset == "electric_cyan":
        primary_color = "&H00FFFFFF"
        outline_color = "&H00102020"
        back_color = "&H90002030"
        highlight_color = "&H00FFF000"  # #00F0FF Electric Cyan
        outline_w = 4.8
        shadow_w = 2.0
    elif style_preset == "golden_aura":
        primary_color = "&H00FFFFFF"
        outline_color = "&H000a1220"
        back_color = "&HA0001830"
        highlight_color = "&H0000B8FF"  # #FFB800 Warm Gold
        outline_w = 4.8
        shadow_w = 2.0
    else:  # clean_minimal or none
        primary_color = "&H00FFFFFF"
        outline_color = "&H00111111"
        back_color = "&HB0000000"
        highlight_color = "&H00E0E0E0"
        outline_w = 3.6
        shadow_w = 1.8

    # Title styling: clean transparent background across ALL formats (no black box border)
    title_box_back = "&H00000000"
    title_border_style = 1

    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2
Collisions: Reverse

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TitleStyle,{font_name},{title_font_size},&H00FFFFFF,&H000000FF,&H00000000,{title_box_back},-1,0,0,0,100,100,0,0,{title_border_style},4.4,2.0,8,40,40,0,1
Style: SubStyle,{font_name},{sub_font_size},{primary_color},&H000000FF,{outline_color},{back_color},-1,0,0,0,100,100,0,0,1,{outline_w},{shadow_w},2,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []

    # 3. Add Title Event with selectable visibility duration (5s, 10s, or entire clip)
    # If skip_title is True or title contains emojis, title is composited via PNG overlay with full color
    if formatted_title and title_position != "none" and not skip_title and not has_emoji(title_text):
        if title_duration == "5s":
            t_end_sec = min(5.0, duration_seconds)
        elif title_duration == "10s":
            t_end_sec = min(10.0, duration_seconds)
        else:
            t_end_sec = max(1.0, duration_seconds)

        end_time_str = format_ass_timestamp(t_end_sec)
        title_lines = [l.strip() for l in formatted_title.split("\\N") if l.strip()]
        for line_idx, t_line in enumerate(title_lines):
            line_y = title_y + (line_idx * line_step)
            events.append(
                f"Dialogue: 1,0:00:00.00,{end_time_str},TitleStyle,,0,0,0,,{{\\q2\\an8\\pos(540,{line_y})}}{t_line}"
            )

    # 4. Add Subtitle Events if captions are enabled (guaranteed ZERO vertical glitch / jumping)
    # Chunking and word timing come from captions.build_caption_chunks, the
    # same function that feeds the browser preview.
    if words and style_preset != "none":
        for chunk in build_caption_chunks(words, text_case, chunk_rules):
            chunk_words = chunk["words"]
            for active_idx, active in enumerate(chunk_words):
                w_start, w_end = active["start"], active["end"]
                if w_end <= w_start:
                    continue

                line_parts = []
                for idx, item in enumerate(chunk_words):
                    w_txt = item["text"]
                    if idx == active_idx:
                        # Highlight active word with color only (no font scale or bold toggle so metrics stay 100% identical)
                        line_parts.append(r"{\c" + highlight_color + r"\3c" + outline_color + r"}" + w_txt + r"{\c" + primary_color + r"\3c" + outline_color + r"}")
                    else:
                        line_parts.append(w_txt)

                styled_line = " ".join(line_parts)
                # Lock position to sub_y with \q2\an{sub_align}\pos(540, sub_y) (zero vertical jump / collision)
                events.append(
                    f"Dialogue: 0,{format_ass_timestamp(w_start)},{format_ass_timestamp(w_end)},SubStyle,,0,0,0,,{{\\q2\\an{sub_align}\\pos(540,{sub_y})}}{styled_line}"
                )

    ass_content = ass_header + "\n".join(events) + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(output_ass_path)), exist_ok=True)
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    return output_ass_path


# Issue #53: OpenCV 5 dropped CascadeClassifier, so face tracking silently
# fell back to the centre for every clip. Said once, loudly, instead.
_face_tracking_off_logged = False
_face_tracking_off_lock = threading.Lock()


def _opencv_requirement() -> str:
    """The opencv-python line of requirements.txt, for the fix message."""
    try:
        for line in (BASE_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("opencv-python"):
                return line.strip()
    except OSError:
        pass
    return "opencv-python"


def _log_face_tracking_off(reason: str) -> None:
    """One ERROR per process, however many clips or threads hit it."""
    global _face_tracking_off_logged
    with _face_tracking_off_lock:
        if _face_tracking_off_logged:
            return
        _face_tracking_off_logged = True
    logger.error(
        f"Face tracking is OFF: {reason}. Fix: pip install \"{_opencv_requirement()}\" "
        "(backend/requirements.txt), remove any opencv-python-headless or "
        "opencv-contrib-python 5.x (pip list), then restart the backend."
    )


def detect_speaker_face_box(source_path: str) -> Dict[str, Any]:
    """
    Detects speaker face bounding box using OpenCV Haar Cascade Classifier.
    Can accept a video file or an image frame.
    Returns normalized coordinates:
    {
        "found": bool,
        "cx": float,  # horizontal center (0.0 to 1.0)
        "cy": float,  # vertical center (0.0 to 1.0)
        "w": float,   # face width ratio (0.0 to 1.0)
        "h": float    # face height ratio (0.0 to 1.0)
    }
    Defaults to cx=0.5, cy=0.35, w=0.25, h=0.25 if no face is detected.
    """
    default_res = {"found": False, "cx": 0.5, "cy": 0.35, "w": 0.25, "h": 0.25}
    if not source_path or not os.path.exists(source_path):
        return default_res

    try:
        try:
            import cv2
        except ImportError:
            _log_face_tracking_off("OpenCV is not installed")
            return default_res

        if not CASCADE_PATH.exists():
            logger.warning(f"Haar cascade XML not found at {CASCADE_PATH}")
            return default_res

        if not hasattr(cv2, "CascadeClassifier"):
            version = getattr(cv2, "__version__", "?")
            _log_face_tracking_off(f"OpenCV {version} has no CascadeClassifier (removed in OpenCV 5)")
            return default_res

        cascade = cv2.CascadeClassifier(str(CASCADE_PATH))

        # Check if source is an image
        ext = os.path.splitext(source_path)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
            frame = cv2.imread(source_path)
            if frame is None:
                return default_res
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(28, 28))
            if len(faces) > 0:
                largest = max(faces, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = largest
                cx = float(fx + fw / 2.0) / w
                cy = float(fy + fh / 2.0) / h
                return {
                    "found": True,
                    "cx": round(float(cx), 3),
                    "cy": round(float(cy), 3),
                    "w": round(float(fw / w), 3),
                    "h": round(float(fh / h), 3)
                }
            return default_res

        # Source is a video file
        cap = cv2.VideoCapture(source_path)
        if not cap.isOpened():
            return default_res

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        # Sample across the entire clip duration rather than only the first ~18 seconds
        step = max(1, total_frames // 25) if total_frames > 25 else max(1, int(fps * 0.75))

        detections = []
        frame_idx = 0
        checked = 0
        while cap.isOpened() and frame_idx < total_frames and checked < 25:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                # Seek may miss non-keyframes; continue to next frame instead of aborting the loop
                frame_idx += step
                checked += 1
                continue
            checked += 1
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(28, 28))
            if len(faces) > 0:
                largest = max(faces, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = largest
                cx = float(fx + fw / 2.0) / w
                cy = float(fy + fh / 2.0) / h
                detections.append((cx, cy, float(fw) / w, float(fh) / h))

            frame_idx += step

        cap.release()

        if detections:
            avg_cx = sum(d[0] for d in detections) / len(detections)
            avg_cy = sum(d[1] for d in detections) / len(detections)
            avg_w = sum(d[2] for d in detections) / len(detections)
            avg_h = sum(d[3] for d in detections) / len(detections)
            logger.info(f"Face tracking detected speaker: center=({avg_cx:.3f}, {avg_cy:.3f}), size=({avg_w:.3f}x{avg_h:.3f}) across {len(detections)} frames")
            return {
                "found": True,
                "cx": round(float(avg_cx), 3),
                "cy": round(float(avg_cy), 3),
                "w": round(float(avg_w), 3),
                "h": round(float(avg_h), 3)
            }
    except Exception as e:
        logger.warning(f"Face detection encountered error: {e}, falling back to defaults.")

    return default_res


def detect_speaker_center_ratio(video_path: str) -> float:
    """
    Detects speaker faces across sample frames and returns the smoothed horizontal center ratio (0.0 to 1.0).
    Defaults to 0.5 (center) if no face is detected.
    """
    box = detect_speaker_face_box(video_path)
    return float(box.get("cx", 0.5))


def split_cam_crop_share(
    face_w: float,
    zoom: Optional[float] = None,
    *,
    source_w: float = 1920.0,
    source_h: float = 1080.0,
) -> float:
    """How much of the cam-shaped crop the split layout keeps (issue #105).

    `face_w` is the detected face's width as a share of the frame; 0 or less
    means no face was found and the old fixed zoom is used, so a video the
    detector cannot read behaves exactly as before.

    `zoom` overrides everything, for the manual control in the Studio.

    The result is a share of the *widest cam-shaped crop that fits the
    source*, which is what SPLIT_CAM_ZOOM has always been — not a share of
    the frame width. On a 1920x1080 source the two differ: the widest
    cam-shaped crop is 1519px, not 1920px, so a face measured against the
    frame has to be rebased before the margin is applied.
    """
    if zoom is not None:
        return max(0.05, min(1.0, float(zoom)))
    if face_w <= 0:
        return SPLIT_CAM_ZOOM
    widest = min(source_w, source_h * SPLIT_CAM_W / SPLIT_CAM_H) or source_w
    tallest = min(source_h, source_w * SPLIT_CAM_H / SPLIT_CAM_W) or source_h
    # The face as a share of that crop, not of the frame.
    face_of_crop = (face_w * source_w) / widest
    share = face_of_crop * SPLIT_CAM_FACE_MARGIN
    # The ceiling keeps room to slide the crop, and has to hold on BOTH axes:
    # on a portrait source the height limit alone leaves a crop as wide as the
    # frame, with nowhere to move sideways — the very failure it exists to
    # prevent. Each axis is capped against its own side of the source.
    ceiling = min(
        (SPLIT_CAM_MAX_SHARE * source_h) / tallest,
        (SPLIT_CAM_MAX_SHARE * source_w) / widest,
    )
    return max(0.05, min(ceiling, 1.0, share))


def build_ffmpeg_filtergraph(
    aspect_ratio: str,
    background_style: str,
    face_center_ratio: float = 0.5,
    streamer_preset: str = "none",
    title_text: Optional[str] = None,
    title_position: str = "auto",
    ass_subtitles_path: Optional[str] = None,
    face_box: Optional[Dict[str, Any]] = None,
    # Issue #105: the Studio's manual override. None means follow the
    # detected face; a value here wins over it.
    cam_zoom: Optional[float] = None,
    cam_center_x: Optional[float] = None,
    cam_center_y: Optional[float] = None,
    source_size: Optional[Tuple[float, float]] = None,
) -> Tuple[str, str]:
    """
    Constructs the FFmpeg -filter_complex chain with proper aspect ratio center-cropping.
    Canvas is always 1080x1920 (9:16).
    """
    filters = []

    face_cx = float(face_box.get("cx", face_center_ratio)) if face_box else face_center_ratio
    face_cy = float(face_box.get("cy", 0.35)) if face_box else 0.35
    # Issue #105: a manual centre from the Studio wins over the detector, but
    # only for the layout whose control the user can actually see. The Studio
    # shows these sliders under the split preset alone, so letting them reach
    # pip_corner or a plain crop would move those with nothing to undo it.
    if streamer_preset == "split_top_cam":
        if cam_center_x is not None:
            face_cx = max(0.0, min(1.0, float(cam_center_x)))
        if cam_center_y is not None:
            face_cy = max(0.0, min(1.0, float(cam_center_y)))
    # And the cam crop follows the face's own width, so a small facecam does
    # not drown in the room around it.
    face_w = float(face_box.get("w", 0.0)) if face_box and face_box.get("found") else 0.0
    src_w, src_h = source_size if source_size else (1920.0, 1080.0)
    cam_share = split_cam_crop_share(face_w, cam_zoom, source_w=src_w, source_h=src_h)

    # 1. Base Layout & Scaling
    if streamer_preset == "split_top_cam":
        # Two boxes stacked to exactly 1080x1920 (#96). The ratio the user
        # picked does not shape the boxes here: two 9:16 boxes stacked are
        # 4.5:16, which cannot fill a 9:16 frame, and the old code left 270px
        # of bar on each side because of it. Full width always, split 40/60 so
        # the content box (where the action is) gets the larger share. Both
        # heights are multiples of 16 and add up to 1920 exactly.
        filters.append(
            f"[0:v]split=2[cam_raw][game_raw];"
            f"[cam_raw]crop='min(iw,ih*{SPLIT_CAM_W}/{SPLIT_CAM_H})*{cam_share:.4f}':"
            f"'min(ih,iw*{SPLIT_CAM_H}/{SPLIT_CAM_W})*{cam_share:.4f}':"
            f"'max(0,min(iw-ow,iw*{face_cx:.3f}-ow/2))':'max(0,min(ih-oh,ih*{face_cy:.3f}-oh/2))',"
            f"scale={SPLIT_CAM_W}:{SPLIT_CAM_H}[cam_box];"
            f"[game_raw]crop='min(iw,ih*{SPLIT_CAM_W}/{SPLIT_GAME_H})':'min(ih,iw*{SPLIT_GAME_H}/{SPLIT_CAM_W})':"
            f"'(iw-min(iw,ih*{SPLIT_CAM_W}/{SPLIT_GAME_H}))/2':'(ih-min(ih,iw*{SPLIT_GAME_H}/{SPLIT_CAM_W}))/2',"
            f"scale={SPLIT_CAM_W}:{SPLIT_GAME_H}[game_box];"
            f"[cam_box][game_box]vstack=inputs=2[layout_base]"
        )
        # The stack is already the whole frame, so there is nothing to pad and
        # no bar for a blurred background to fill: background_style is unused.
        current_v = "[layout_base]"

    elif streamer_preset == "pip_corner":
        # PIP Box cropped on face, placed in the top-right corner of the video content for EACH aspect ratio
        pip_crop = f"[pip_raw]crop='min(iw,ih*4/3*0.5)':'ih*0.5':'max(0,min(iw-ow,iw*{face_cx:.3f}-ow/2))':'max(0,min(ih-oh,ih*{face_cy:.3f}-oh/2))',scale=320:240[pip_box];"

        if aspect_ratio == "1:1":
            crop_main = "crop='min(iw,ih)':'min(iw,ih)':'(iw-min(iw,ih))/2':'(ih-min(iw,ih))/2',scale=1080:1080"
            pip_x, pip_y = 736, 444
            if background_style == "blurred":
                filters.append(
                    f"[0:v]split=3[bg_raw][main_raw][pip_raw];"
                    f"[bg_raw]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                    f"[main_raw]{crop_main}[fg_square];"
                    f"[bg_blurred][fg_square]overlay=0:420[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )
            else:
                filters.append(
                    f"[0:v]split=2[main_raw][pip_raw];"
                    f"[main_raw]{crop_main},pad=1080:1920:0:420:black[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )

        elif aspect_ratio == "4:3":
            crop_main = "crop='min(iw,ih*4/3)':'min(ih,iw*3/4)':'(iw-min(iw,ih*4/3))/2':'(ih-min(ih,iw*3/4))/2',scale=1080:810"
            pip_x, pip_y = 736, 579
            if background_style == "blurred":
                filters.append(
                    f"[0:v]split=3[bg_raw][main_raw][pip_raw];"
                    f"[bg_raw]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                    f"[main_raw]{crop_main}[fg_43];"
                    f"[bg_blurred][fg_43]overlay=0:555[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )
            else:
                filters.append(
                    f"[0:v]split=2[main_raw][pip_raw];"
                    f"[main_raw]{crop_main},pad=1080:1920:0:555:black[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )

        elif aspect_ratio == "16:9":
            crop_main = "crop='min(iw,ih*16/9)':'min(ih,iw*9/16)':'(iw-min(iw,ih*16/9))/2':'(ih-min(ih,iw*9/16))/2',scale=1080:608"
            pip_x, pip_y = 736, 676
            if background_style == "blurred":
                filters.append(
                    f"[0:v]split=3[bg_raw][main_raw][pip_raw];"
                    f"[bg_raw]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                    f"[main_raw]{crop_main}[fg_169];"
                    f"[bg_blurred][fg_169]overlay=0:656[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )
            else:
                filters.append(
                    f"[0:v]split=2[main_raw][pip_raw];"
                    f"[main_raw]{crop_main},pad=1080:1920:0:656:black[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )

        else:  # 9:16
            crop_ratio_safe = max(0.0, min(1.0, (face_cx - 0.158) / 0.684))
            pip_x, pip_y = 736, 120
            filters.append(
                f"[0:v]split=2[main_raw][pip_raw];"
                f"[main_raw]crop=ih*9/16:ih:(iw-ih*9/16)*{crop_ratio_safe:.3f}:0,scale=1080:1920[main_base];"
                f"{pip_crop}"
                f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
            )

        current_v = "[layout_base]"

    elif aspect_ratio == "9:16":
        # Full Bleed 9:16 with Face Tracking horizontal crop offset
        crop_ratio_safe = max(0.0, min(1.0, (face_cx - 0.158) / 0.684))
        filters.append(
            f"[0:v]crop=ih*9/16:ih:(iw-ih*9/16)*{crop_ratio_safe:.3f}:0,scale=1080:1920[layout_base]"
        )
        current_v = "[layout_base]"

    elif aspect_ratio == "1:1":
        # 1:1 Square (1080x1080) - Center crop to 1:1 square then scale to 1080x1080
        crop_11 = "crop='min(iw,ih)':'min(iw,ih)':'(iw-min(iw,ih))/2':'(ih-min(iw,ih))/2',scale=1080:1080"
        if background_style == "blurred":
            filters.append(
                f"[0:v]split=2[bg_raw][fg_raw];"
                f"[bg_raw]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                f"[fg_raw]{crop_11}[fg_square];"
                f"[bg_blurred][fg_square]overlay=0:420[layout_base]"
            )
        else:
            filters.append(
                f"[0:v]{crop_11},pad=1080:1920:0:420:black[layout_base]"
            )
        current_v = "[layout_base]"

    elif aspect_ratio == "4:3":
        # 4:3 Standard (1080x810) - Center crop 16:9/source to 4:3 then scale to 1080x810
        crop_43 = "crop='min(iw,ih*4/3)':'min(ih,iw*3/4)':'(iw-min(iw,ih*4/3))/2':'(ih-min(ih,iw*3/4))/2',scale=1080:810"
        if background_style == "blurred":
            filters.append(
                f"[0:v]split=2[bg_raw][fg_raw];"
                f"[bg_raw]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                f"[fg_raw]{crop_43}[fg_43];"
                f"[bg_blurred][fg_43]overlay=0:555[layout_base]"
            )
        else:
            filters.append(
                f"[0:v]{crop_43},pad=1080:1920:0:555:black[layout_base]"
            )
        current_v = "[layout_base]"

    else:  # 16:9 Letterbox
        # 16:9 Letterbox (1080x608)
        crop_169 = "crop='min(iw,ih*16/9)':'min(ih,iw*9/16)':'(iw-min(iw,ih*16/9))/2':'(ih-min(ih,iw*9/16))/2',scale=1080:608"
        if background_style == "blurred":
            filters.append(
                f"[0:v]split=2[bg_raw][fg_raw];"
                f"[bg_raw]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                f"[fg_raw]{crop_169}[fg_169];"
                f"[bg_blurred][fg_169]overlay=0:656[layout_base]"
            )
        else:
            filters.append(
                f"[0:v]{crop_169},pad=1080:1920:0:656:black[layout_base]"
            )
        current_v = "[layout_base]"

    # 2. Subtitles & Title Burning via libass (.ass)
    # (If ass_subtitles_path is provided, it contains BOTH the title and subtitles rendered with exact matching fonts)
    if ass_subtitles_path and os.path.exists(ass_subtitles_path):
        escaped_ass = str(ass_subtitles_path).replace("\\", "/").replace(":", "\\:")
        if FONTS_DIR.exists() and any(FONTS_DIR.glob("*.ttf")):
            escaped_fonts = str(FONTS_DIR).replace("\\", "/").replace(":", "\\:")
            sub_filter = f"{current_v}subtitles='{escaped_ass}':fontsdir='{escaped_fonts}'[v_final]"
        else:
            sub_filter = f"{current_v}subtitles='{escaped_ass}'[v_final]"
        filters.append(sub_filter)
        current_v = "[v_final]"
    elif title_text and title_position != "none":
        # Fallback drawtext if no ASS was generated
        clean_title = title_text.replace("'", "").replace(":", "-").replace('"', "").strip()
        y_pos = 345 if aspect_ratio == "1:1" else (480 if aspect_ratio in ["4:3", "9:16"] else 581)
        box_style = "box=0"
        title_filter = (
            f"{current_v}drawtext=text='{clean_title}':fontsize=60:fontcolor=white:"
            f"x=(w-text_w)/2:y={y_pos}:borderw=2.5:bordercolor=black@0.8:{box_style}[v_with_title]"
        )
        filters.append(title_filter)
        current_v = "[v_with_title]"

    full_filter_str = ";".join(filters)
    return full_filter_str, current_v


def check_has_audio(video_path: str) -> bool:
    """Checks if the video file contains a readable audio stream."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(video_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        return bool(res.stdout and res.stdout.strip())
    except Exception:
        return True


def render_clip_to_mp4(
    video_path: str,
    output_mp4_path: str,
    aspect_ratio: str = "9:16",
    background_style: str = "black",
    enable_face_tracking: bool = True,
    streamer_preset: str = "none",
    title_text: Optional[str] = None,
    title_position: str = "auto",
    ass_subtitles_path: Optional[str] = None,
    clip_duration: float = 30.0,
    # Title Overlay (for full-color emojis and styling)
    title_overlay_path: Optional[str] = None,
    title_duration: str = "entire",
    # Watermark options
    watermark_enabled: bool = False,
    watermark_type: str = "image",
    watermark_image_path: Optional[str] = None,
    watermark_text: Optional[str] = None,
    watermark_size: float = 20.0,
    watermark_opacity: float = 0.8,
    watermark_x_percent: float = 90.0,
    watermark_y_percent: float = 8.0,
    # Background Music options
    bgm_enabled: bool = False,
    bgm_path: Optional[str] = None,
    bgm_volume: float = 0.25,
    bgm_start_offset: float = 0.0,
    # Hook SFX options (plays at frame 0)
    hook_sfx_enabled: bool = False,
    hook_sfx_path: Optional[str] = None,
    hook_sfx_volume: float = 1.0,
    # Raw voice / original audio boost (0.0 to 2.0)
    original_audio_volume: float = 1.0,
    # Hardware acceleration selection ('auto', 'nvenc', 'amf', 'qsv', 'cpu')
    hardware_accel: Optional[str] = "auto",
    # Issue #105: manual facecam framing from the Studio, when the detected
    # face is not where the user wants the cam box pointed.
    cam_zoom: Optional[float] = None,
    cam_center_x: Optional[float] = None,
    cam_center_y: Optional[float] = None
) -> str:
    """
    Renders the final 1080x1920 short-form video with layout, aspect ratio, titles, subtitles,
    watermark branding, background music with start offset, and hook sound effect at frame 0.
    """
    face_box = {"found": False, "cx": 0.5, "cy": 0.35, "w": 0.25, "h": 0.25}
    if enable_face_tracking or streamer_preset in ["pip_corner", "split_top_cam"]:
        face_box = detect_speaker_face_box(video_path)

    filter_complex, out_video_map = build_ffmpeg_filtergraph(
        aspect_ratio=aspect_ratio,
        background_style=background_style,
        face_center_ratio=float(face_box.get("cx", 0.5)),
        streamer_preset=streamer_preset,
        title_text=title_text if not (title_overlay_path and os.path.exists(title_overlay_path)) else None,
        title_position=title_position,
        ass_subtitles_path=ass_subtitles_path,
        face_box=face_box,
        cam_zoom=cam_zoom,
        cam_center_x=cam_center_x,
        cam_center_y=cam_center_y,
        # Only the split layout sizes its crop against the source, so no
        # other preset pays for an ffprobe it will not read.
        source_size=probe_video_size(video_path) if streamer_preset == "split_top_cam" else None,
    )

    filter_chains = [filter_complex]
    extra_input_args = []
    input_idx_counter = 1
    dur = max(1.0, float(clip_duration))

    # 1. Apply Title Overlay (Full-Color Emojis & Titles)
    if title_overlay_path and os.path.exists(title_overlay_path):
        t_idx = input_idx_counter
        input_idx_counter += 1
        extra_input_args.extend(["-i", str(title_overlay_path)])

        if title_duration == "5s":
            t_end_sec = min(5.0, dur)
            enable_expr = f":enable='between(t,0,{t_end_sec:.2f})'"
        elif title_duration == "10s":
            t_end_sec = min(10.0, dur)
            enable_expr = f":enable='between(t,0,{t_end_sec:.2f})'"
        else:
            enable_expr = ""

        overlay_title_cmd = f"{out_video_map}[{t_idx}:v]overlay=0:0{enable_expr}[v_with_title_overlay]"
        filter_chains.append(overlay_title_cmd)
        out_video_map = "[v_with_title_overlay]"

    # 2. Apply Watermark Overlay
    if watermark_enabled and float(watermark_size) > 0:
        wm_opacity = max(0.05, min(1.0, float(watermark_opacity)))
        wm_x_ratio = max(-1.0, min(2.0, float(watermark_x_percent) / 100.0))
        wm_y_ratio = max(-1.0, min(2.0, float(watermark_y_percent) / 100.0))

        if watermark_type == "image" and watermark_image_path and os.path.exists(watermark_image_path):
            wm_idx = input_idx_counter
            input_idx_counter += 1
            extra_input_args.extend(["-i", str(watermark_image_path)])

            # Canvas width is 1080. Calculate watermark width based on percentage (0-500%)
            wm_w = max(16, min(5400, int(1080 * (float(watermark_size) / 100.0))))
            wm_prep = f"[{wm_idx}:v]format=rgba,colorchannelmixer=aa={wm_opacity:.2f},scale={wm_w}:-1[wm_proc]"
            filter_chains.append(wm_prep)

            # Center-based positioning: (X%, Y%) represents the center anchor point on the canvas.
            # This ensures full 100% travel range across the canvas regardless of watermark size.
            overlay_cmd = (
                f"{out_video_map}[wm_proc]overlay="
                f"x='main_w*{wm_x_ratio:.4f}-overlay_w/2':"
                f"y='main_h*{wm_y_ratio:.4f}-overlay_h/2':eval=init[v_watermarked]"
            )
            filter_chains.append(overlay_cmd)
            out_video_map = "[v_watermarked]"

        elif watermark_text and watermark_text.strip():
            clean_text = watermark_text.replace("'", "").replace(":", "\\:").replace("%", "").strip()
            # Font size scaled smoothly across 0-500% range: 20% -> 36px, 100% -> 180px, 500% -> 900px
            wm_font_size = max(10, min(900, int(180 * (float(watermark_size) / 100.0))))
            # Center-based positioning: text anchor is centered at (X%, Y%) coordinates on the canvas
            overlay_x_expr = f"w*{wm_x_ratio:.4f}-text_w/2"
            overlay_y_expr = f"h*{wm_y_ratio:.4f}-text_h/2"
            drawtext_cmd = (
                f"{out_video_map}drawtext=text='{clean_text}':fontsize={wm_font_size}:"
                f"fontcolor=white@{wm_opacity:.2f}:borderw=2:bordercolor=black@{wm_opacity:.2f}:"
                f"x='{overlay_x_expr}':y='{overlay_y_expr}'[v_watermarked]"
            )
            filter_chains.append(drawtext_cmd)
            out_video_map = "[v_watermarked]"

    # 2. Audio Processing (Original Audio with Boost, BGM with start offset, and Hook SFX at frame 0)
    audio_inputs_to_mix = []
    has_orig_audio = check_has_audio(video_path)
    if has_orig_audio:
        orig_vol = max(0.0, min(2.0, float(original_audio_volume)))
        if abs(orig_vol - 1.0) > 0.01:
            filter_chains.append(f"[0:a:0]volume={orig_vol:.3f}[v_orig_boosted]")
            audio_inputs_to_mix.append("[v_orig_boosted]")
        else:
            audio_inputs_to_mix.append("[0:a:0]")

    dur = max(1.0, float(clip_duration))

    # BGM input with start offset & looping
    if bgm_enabled and bgm_path and os.path.exists(bgm_path):
        bgm_idx = input_idx_counter
        input_idx_counter += 1
        offset_sec = max(0.0, float(bgm_start_offset))
        if offset_sec > 0.0:
            extra_input_args.extend(["-ss", f"{offset_sec:.2f}"])
        extra_input_args.extend(["-stream_loop", "-1", "-i", str(bgm_path)])

        vol = max(0.0, min(1.0, float(bgm_volume)))
        fade_st = max(0.0, dur - 1.5)
        filter_chains.append(
            f"[{bgm_idx}:a]asetpts=PTS-STARTPTS,volume={vol:.3f},afade=t=out:st={fade_st:.2f}:d=1.5[bgm_proc]"
        )
        audio_inputs_to_mix.append("[bgm_proc]")

    # Hook SFX input placed at the very first frame (t=0)
    if hook_sfx_enabled and hook_sfx_path and os.path.exists(hook_sfx_path):
        sfx_idx = input_idx_counter
        input_idx_counter += 1
        extra_input_args.extend(["-i", str(hook_sfx_path)])

        sfx_vol = max(0.0, min(2.0, float(hook_sfx_volume)))
        filter_chains.append(
            f"[{sfx_idx}:a]asetpts=PTS-STARTPTS,atrim=end={dur:.2f},volume={sfx_vol:.3f}[sfx_proc]"
        )
        audio_inputs_to_mix.append("[sfx_proc]")

    # Mix audio streams together
    if len(audio_inputs_to_mix) > 1:
        mix_inputs_str = "".join(audio_inputs_to_mix)
        filter_chains.append(
            f"{mix_inputs_str}amix=inputs={len(audio_inputs_to_mix)}:duration=first:dropout_transition=2:normalize=0[a_final]"
        )
        out_audio_map = "[a_final]"
    elif len(audio_inputs_to_mix) == 1:
        single_stream = audio_inputs_to_mix[0]
        if single_stream == "[0:a:0]":
            out_audio_map = "0:a:0"
        else:
            filter_chains.append(f"{single_stream}anull[a_final]")
            out_audio_map = "[a_final]"
    else:
        out_audio_map = "0:a:0?"

    final_filter_complex = ";".join(filter_chains)

    # Video encoder (resolved from user choice: auto, nvenc, amf, qsv, cpu)
    chosen_encoder_name, chosen_encoder_args = resolve_encoder(hardware_accel)
    v_codec_args = chosen_encoder_args

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        *extra_input_args,
        "-filter_complex", final_filter_complex,
        "-map", out_video_map,
        "-map", out_audio_map,
        *v_codec_args,
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-shortest",
        str(output_mp4_path)
    ]

    # Check if FFmpeg is installed and accessible
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is not installed or not found in system PATH. Please install FFmpeg (e.g. 'winget install Gyan.FFmpeg') and restart your terminal.")

    logger.info(f"Rendering final vertical clip to {output_mp4_path} with {chosen_encoder_name} (Selection: {hardware_accel}, BGM: {bgm_enabled}, Watermark: {watermark_enabled})...")
    timeouts = render_timeouts(clip_duration)
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeouts["encoder"])
    if res.returncode != 0:
        logger.warning(f"Hardware encoder ({chosen_encoder_name}) failed (code {res.returncode}): {res.stderr[:250] if res.stderr else ''}")
        # Automatic fallback to universal CPU encoding (libx264) if chosen hardware encoder fails
        if chosen_encoder_name != "libx264":
            logger.info("Retrying render with universal multi-threaded CPU encoder (libx264)...")
            cpu_cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(video_path),
                *extra_input_args,
                "-filter_complex", final_filter_complex,
                "-map", out_video_map,
                "-map", out_audio_map,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-shortest",
                str(output_mp4_path)
            ]
            res_cpu = subprocess.run(cpu_cmd, capture_output=True, text=True, timeout=timeouts["cpu"])
            if res_cpu.returncode == 0 and os.path.exists(output_mp4_path) and os.path.getsize(output_mp4_path) > 1000:
                logger.info(f"Successfully rendered with CPU fallback: {output_mp4_path}")
                return str(output_mp4_path)
            else:
                logger.error(f"FFmpeg CPU fallback also failed: {res_cpu.stderr}")
                raise RuntimeError(f"FFmpeg rendering failed: {res_cpu.stderr or res.stderr}")
        else:
            logger.error(f"FFmpeg render error: {res.stderr}")
            raise RuntimeError(f"FFmpeg rendering failed: {res.stderr}")

    return str(output_mp4_path)


_frame_failures: Dict[Tuple[str, int], float] = {}
_frame_locks: Dict[Tuple[str, int], threading.Lock] = {}
_frame_locks_guard = threading.Lock()


def _frame_lock(key: Tuple[str, int]) -> threading.Lock:
    """One lock per (video, second): the backdrop and detect-face ask at once."""
    with _frame_locks_guard:
        return _frame_locks.setdefault(key, threading.Lock())


def extract_clip_frame(video_id: str, timestamp: float = 0.0) -> Optional[str]:
    """The preview JPEG for `timestamp` (see extract_clip_frame_info), path only."""
    return extract_clip_frame_info(video_id, timestamp)[0]


def extract_clip_frame_info(
    video_id: str,
    timestamp: float = 0.0,
    clock: Callable[[], float] = time.monotonic,
) -> Tuple[Optional[str], bool]:
    """
    A JPEG for the preview at `timestamp`, and whether it is exact.

    Exact: this second's frame, cut from a 1-second YouTube slice and cached
    as frames/<id>_<sec>.jpg. Otherwise a stand-in that is never stored as
    this second (issue #44): the nearest cached frame of the same video, else
    its thumbnail (frames/<id>_thumb.jpg). (None, False) when there is none.

    A second YouTube refused is not asked again for FRAME_FAILURE_TTL. Takes
    a video ID, never a URL (issue #42), and returns (None, False) for
    anything that is not a well-formed ID, whatever the caller checked.
    """
    if not is_video_id(video_id):
        return None, False

    frames_dir = TEMP_DIR / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    target_ts = max(1.0, timestamp if timestamp > 0 else 5.0)
    sec = int(round(target_ts))
    frame_path = frames_dir / f"{video_id}_{sec}.jpg"

    def cached() -> bool:
        return frame_path.exists() and frame_path.stat().st_size > 2000

    if cached():
        return str(frame_path), True

    key = (video_id, sec)
    with _frame_lock(key):
        if cached():  # the other request cut it while this one waited
            return str(frame_path), True
        failed_at = _frame_failures.get(key)
        if failed_at is None or clock() - failed_at > FRAME_FAILURE_TTL:
            if _cut_frame(video_id, target_ts, frame_path):
                _frame_failures.pop(key, None)
                return str(frame_path), True
            _frame_failures[key] = clock()

    return _stand_in_frame(frames_dir, video_id, sec), False


def _cut_frame(video_id: str, target_ts: float, frame_path: Path) -> bool:
    """Cuts one frame at target_ts from a 1-second YouTube slice. True on success."""
    frames_dir = frame_path.parent
    # Own names per call: two requests must never share a slice or half a JPEG.
    token = uuid.uuid4().hex[:8]
    temp_slice = frames_dir / f"slice_{video_id}_{int(target_ts)}_{token}.mp4"
    temp_jpg = frames_dir / f"tmp_{video_id}_{int(target_ts)}_{token}.jpg"
    try:
        slice_cmd = [
            *get_yt_dlp_base_cmd(),
            "-f", FRAME_FORMAT,
            "-S", FRAME_SORT,
            "--download-sections",
            f"*{format_section_time(target_ts)}-{format_section_time(target_ts + 1.0)}",
            "-o", str(temp_slice),
            "--no-warnings",
            "--", f"https://www.youtube.com/watch?v={video_id}",
        ]
        subprocess.run(slice_cmd, capture_output=True, text=True, timeout=20)
        if not (temp_slice.exists() and temp_slice.stat().st_size > 1000):
            return False
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", "00:00:00.20", "-i", str(temp_slice),
            "-vframes", "1", "-strict", "-1", str(temp_jpg),
        ], capture_output=True, timeout=5)
        if temp_jpg.exists() and temp_jpg.stat().st_size > 2000:
            os.replace(temp_jpg, frame_path)
            return True
        return False
    except Exception as e:
        logger.warning(f"Frame extraction failed for {video_id} at {target_ts:.1f}s: {e}")
        return False
    finally:
        _remove(temp_slice)
        _remove(temp_jpg)


def _stand_in_frame(frames_dir: Path, video_id: str, sec: int) -> Optional[str]:
    """The nearest cached real frame of this video, else its thumbnail."""
    seconds = []
    for path in frames_dir.glob(f"{video_id}_*.jpg"):
        suffix = path.stem[len(video_id) + 1:]
        if suffix.isdigit() and path.stat().st_size > 2000:
            seconds.append(int(suffix))
    if seconds:
        nearest = min(seconds, key=lambda s: abs(s - sec))
        return str(frames_dir / f"{video_id}_{nearest}.jpg")

    thumb_path = frames_dir / f"{video_id}_thumb.jpg"
    if thumb_path.exists() and thumb_path.stat().st_size > 2000:
        return str(thumb_path)
    try:
        import urllib.request
        for thumb_url in (
            f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
            f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        ):
            try:
                req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=3) as resp, open(thumb_path, "wb") as f_out:
                    f_out.write(resp.read())
                if thumb_path.exists() and thumb_path.stat().st_size > 2000:
                    return str(thumb_path)
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Thumbnail fallback failed for {video_id}: {e}")
    return None
