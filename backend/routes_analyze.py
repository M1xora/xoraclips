"""
/api/analyze and the Gemini model list. The analysis streams progress while
it fetches the video and its captions, asks Gemini for clips (trying other
models when one fails), and finishes them; the steps that need no network
live in analysis.py (#74).
"""
import asyncio
import json
import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

try:
    from backend import ai_errors, analysis, clip_lengths, youtube_errors
    from backend.analysis import (  # noqa: F401 (ViralClipGemini: the tests)
        AnalysisError, AnalyzeResponse, HeatmapPoint, VideoAnalysis, ViralClip, ViralClipGemini,
    )
    from backend.secrets_guard import (
        GEMINI_KEY_HEADER, is_mock_mode, redact_data, tracked_secret, user_key_from_header,
    )
    from backend.youtube_errors import CaptionUnavailable, YouTubeBlocked
    from backend.youtube_source import (
        extract_video_id, fetch_transcript, fetch_video_metadata, get_supadata_keys,
        parse_manual_subtitles,
    )
except ImportError:
    import ai_errors
    import analysis
    import clip_lengths
    import youtube_errors
    from analysis import (  # noqa: F401 (ViralClipGemini: the tests)
        AnalysisError, AnalyzeResponse, HeatmapPoint, VideoAnalysis, ViralClip, ViralClipGemini,
    )
    from secrets_guard import (
        GEMINI_KEY_HEADER, is_mock_mode, redact_data, tracked_secret, user_key_from_header,
    )
    from youtube_errors import CaptionUnavailable, YouTubeBlocked
    from youtube_source import (
        extract_video_id, fetch_transcript, fetch_video_metadata, get_supadata_keys,
        parse_manual_subtitles,
    )

logger = logging.getLogger("xoraclips")
router = APIRouter()


class AnalyzeRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL")
    duration: clip_lengths.Duration = Field("30s", description="Target clip duration: '15s', '30s', '60s', '120s' or '180s'")
    model: Optional[str] = Field("gemini-2.5-flash", description="Preferred Gemini model name")
    custom_prompt: Optional[str] = Field(None, description="Optional custom focus prompt for clips search")
    range_start: Optional[float] = Field(None, description="Search range start in seconds")
    range_end: Optional[float] = Field(None, description="Search range end in seconds")
    subtitles: Optional[str] = Field(None, description="Optional manual subtitles text (SRT or TXT)")
    subtitles_filename: Optional[str] = Field(None, description="Optional manual subtitles filename")
    target_clip_count: Optional[int] = Field(None, description="Optional target number of clips (1-50)")
    proxy: Optional[str] = Field(None, description="Optional custom proxy URL")


def _sse(data: dict) -> str:
    """Format a dict as a Server-Sent Event string. Keys are scrubbed on the way out,
    from the values before serialising, so the JSON always stays valid."""
    return f"data: {json.dumps(redact_data(data), ensure_ascii=False)}\n\n"


def parse_gemini_model_sort_key(name: str):
    """Sort key for Gemini models: parses major and minor versions (e.g. 3.7, 3.6, 3.5, 2.5, 2.0, 1.5),
    tier (standard > lite/8b > preview/exp), so newest and most capable models come first."""
    name_clean = (name or "").split('/')[-1].lower()
    m = re.search(r'(\d+)(?:\.(\d+))?', name_clean)
    if m:
        major = int(m.group(1))
        minor = int(m.group(2)) if m.group(2) is not None else 0
    else:
        major, minor = 0, 0

    if 'lite' in name_clean or '8b' in name_clean:
        tier = 2
    elif 'exp' in name_clean or 'preview' in name_clean:
        tier = 1
    else:
        tier = 3

    return (major, minor, tier, name_clean)


KNOWN_FLASH_MODELS = [
    'gemini-2.5-flash',
    'gemini-2.5-flash-lite',
    'gemini-2.0-flash',
    'gemini-2.0-flash-lite',
    'gemini-1.5-flash',
    'gemini-1.5-flash-8b',
]


# Non-text, specialized, or non-generative models.
EXCLUDED_MODEL_WORDS = (
    'tuning', 'thinking', 'vision', 'image', 'tts',
    'omni', 'customtools', 'embed', 'realtime', 'robotics',
)


def _text_models(models_page) -> List[str]:
    """Short names of the listed Gemini models that can write text, in listed
    order, each once."""
    names = []
    for m in models_page:
        short_name = (m.name or "").split('/')[-1]
        lower = short_name.lower()
        if "gemini" not in lower:
            continue
        if m.supported_actions and "generateContent" not in m.supported_actions:
            continue
        if any(x in lower for x in EXCLUDED_MODEL_WORDS):
            continue
        if short_name not in names:
            names.append(short_name)
    return names


def get_flash_models_for_key(client: genai.Client) -> List[str]:
    """Dynamically query all available flash models for the given API key.
    Discovers newer versions (e.g., 3.7, 3.6, 3.5) and earlier versions (2.5, 2.0, 1.5),
    merging with known fallback models and sorting in descending order of version/capability."""
    discovered = []
    try:
        discovered = [n for n in _text_models(client.models.list()) if "flash" in n.lower()]
    except Exception as e:
        logger.warning(f"Could not dynamically list models: {e}")

    # Combine discovered with known flash models, preserving uniqueness
    combined_pool = list(dict.fromkeys(discovered + KNOWN_FLASH_MODELS))
    # Sort descending so newest versions (3.7, 3.6, 3.5, 2.5, 2.0, 1.5) are prioritized
    ordered = sorted(combined_pool, key=parse_gemini_model_sort_key, reverse=True)
    return ordered


@router.get("/api/models")
def list_available_models(x_gemini_api_key: Optional[str] = Header(None, alias=GEMINI_KEY_HEADER)):
    """Lists Gemini models available to the user's key, prioritizing Flash models (newest first).
    The key comes only from the X-Gemini-Api-Key header (issue #12); a key in the URL is ignored.
    Doubles as a key check: a key Google rejects gets 401 with code key_invalid."""
    default_models = [
        'gemini-2.5-flash',
        'gemini-2.5-flash-lite',
        'gemini-2.0-flash',
        'gemini-2.0-flash-lite',
        'gemini-1.5-flash',
        'gemini-2.5-pro'
    ]
    key_to_use = user_key_from_header(x_gemini_api_key)
    if not key_to_use or is_mock_mode():
        return {"models": default_models}
    with tracked_secret(key_to_use):
        return _list_models_for_key(key_to_use, default_models)


def _list_models_for_key(key_to_use: str, default_models: List[str]):
    try:
        client = genai.Client(api_key=key_to_use)
        names = _text_models(client.models.list())
        flash_models = [n for n in names if "flash" in n.lower()]
        pro_models = [n for n in names if "flash" not in n.lower() and "pro" in n.lower()]
        other_models = [n for n in names if "flash" not in n.lower() and "pro" not in n.lower()
                        and any(x in n.lower() for x in ['lite', 'exp'])]

        # Sort flash models by version descending (e.g. 3.7, 3.6, 3.5, 2.5, 2.0, 1.5)
        ordered_flash = sorted(
            list(dict.fromkeys(flash_models + KNOWN_FLASH_MODELS)),
            key=parse_gemini_model_sort_key,
            reverse=True
        )
        ordered_pro = sorted(pro_models, key=parse_gemini_model_sort_key, reverse=True)
        ordered_other = sorted(other_models, key=parse_gemini_model_sort_key, reverse=True)
        
        final_list = ordered_flash + ordered_pro + ordered_other
        if not final_list:
            final_list = default_models
            
        return {"models": final_list}
    except Exception as e:
        # Any failure is reported as an error, never as a 200 with the default
        # list: the form treats a 200 as "key is valid".
        code = ai_errors.classify_gemini_error(e)
        logger.warning(f"Error listing models ({code}): {e}")
        raise HTTPException(
            status_code=ai_errors.STATUS[code],
            detail={"code": code, "message": ai_errors.MESSAGES[code]},
        )


# Sample data for MOCK_MODE (backend/.env). Mock analyses never contact
# YouTube or Gemini.
MOCK_METADATA = {
    "title": "Mock YouTube Video",
    "channel": "Xoraclips",
    "duration": 212.0,
    "heatmap": [],
    "is_live": False,
    "live_status": "not_live",
}


MOCK_TRANSCRIPT = [
    {"text": "Hello and welcome to this video.",            "start":  0.0, "duration": 3.0},
    {"text": "Today we are looking at how this app works.",  "start":  3.0, "duration": 4.0},
    {"text": "It finds viral hotspots and highlights them.",  "start":  7.0, "duration": 4.0},
    {"text": "Most people think it's magic.",               "start": 11.0, "duration": 3.0},
    {"text": "But it uses YouTube player heatmaps.",         "start": 14.0, "duration": 4.0},
    {"text": "And processes them with Gemini AI models.",    "start": 18.0, "duration": 4.0},
    {"text": "This is changing how editors crop videos.",    "start": 22.0, "duration": 5.0},
    {"text": "If you want to grow on TikTok, try it.",      "start": 27.0, "duration": 5.0},
    {"text": "We will explore the code next.",               "start": 32.0, "duration": 3.0},
]


def _gemini_key_problem(key: str) -> Optional[str]:
    """
    A cheap key check (list one page of models). Returns the error code when
    the key cannot work (invalid, out of quota, region), else None. A busy or
    unclear answer returns None: the analysis goes on and reports later.
    """
    # Keep the client in a variable: a temporary Client is garbage-collected at
    # once, closes its HTTP connection, and the request then fails with
    # "Cannot send a request, as the client has been closed".
    client = genai.Client(api_key=key)
    try:
        next(iter(client.models.list()), None)
    except Exception as e:
        code = ai_errors.classify_gemini_error(e)
        if code in (ai_errors.KEY_INVALID, ai_errors.KEY_QUOTA, ai_errors.REGION_UNSUPPORTED):
            logger.warning(f"Gemini key check failed ({code}): {e}")
            return code
    return None


def _event(step: int, step_progress: int, overall_progress: int, stage: str, detail: str,
           message: Optional[str] = None, **extra) -> str:
    """A progress event."""
    data = {"step": step, "step_progress": step_progress, "overall_progress": overall_progress,
            "stage": stage, "detail": detail, **extra}
    if message is not None:
        data["message"] = message
    return _sse(data)


def _error(message: str, status: int) -> str:
    return _sse({"error": message, "status": status})


def _clock(seconds: float) -> str:
    """Seconds as m:ss, or h:mm:ss past an hour, for text the user reads.

    The analysis limit is mostly hit by videos over an hour (#101), where a
    bare minute count ("103:20") cannot be typed into the h/m/s range inputs.
    Negative values clamp to zero: cut_at comes from the transcript while the
    bound comes from metadata, and the two can disagree by a line.
    """
    total = max(0, int(seconds))
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


async def _transcript_events(video_id: str, proxy: Optional[str], got: dict):
    """Fetches the captions in a thread and passes its progress on as events.
    The lines end up in got["lines"]; a failure is raised."""
    loop = asyncio.get_running_loop()
    progress_queue = asyncio.Queue()

    def progress_callback(stage: str, detail: str, step_pct: int = 30):
        loop.call_soon_threadsafe(progress_queue.put_nowait, {
            "step": 3,
            "step_progress": step_pct,
            "overall_progress": min(68, 50 + int(step_pct * 0.2)),
            "stage": stage,
            "detail": detail,
            "message": detail
        })

    task = asyncio.create_task(asyncio.to_thread(fetch_transcript, video_id, proxy, progress_callback))
    while not task.done():
        try:
            evt = await asyncio.wait_for(progress_queue.get(), timeout=0.2)
            yield _sse(evt)
        except asyncio.TimeoutError:
            pass
    while not progress_queue.empty():
        yield _sse(progress_queue.get_nowait())
    got["lines"] = await task


def _transcript_error(e: Exception, video_id: str, metadata: dict) -> str:
    """A short message per cause; the details are already in the log."""
    if isinstance(e, YouTubeBlocked):
        return _sse(youtube_errors.error_event(e.code, e.retry_after))
    if metadata.get("is_live", False) or metadata.get("live_status", "not_live") in ('is_live', 'is_upcoming', 'post_live'):
        return _sse(youtube_errors.error_event(youtube_errors.VIDEO_LIVE))
    if isinstance(e, CaptionUnavailable):
        return _sse(youtube_errors.error_event(e.code))
    logger.exception(f"Subtitle retrieval failed unexpectedly for {video_id}")
    return _sse(youtube_errors.error_event(youtube_errors.CAPTIONS_UNAVAILABLE))


async def _mock_events(video_id: str, title: str, channel: str, duration: float, heatmap: List[dict]):
    """MOCK_MODE: sample stages and clips, without Gemini."""
    mock_stages = [
        ("Context Assembly", "Aligning 9 transcript dialogue lines with retention telemetry...", 30, 78),
        ("Viral Hook & Curiosity Detection", "Scanning transcript dialogue for viral hooks & curiosity gaps...", 65, 88),
        ("Virality Scoring & Selection", "Calculating virality coefficients and formatting clip candidates...", 92, 95),
    ]
    for s_name, s_detail, s_prog, o_prog in mock_stages:
        yield _event(4, s_prog, o_prog, s_name, s_detail, f"Mock AI ({s_name}): {s_detail}",
                     model="gemini-2.5-flash (Mock)")
        await asyncio.sleep(0.7)

    mock_clips = [
        ViralClip(title="Finding hotspots using heatmaps",  start_time=11.0, end_time=22.0, hook_time=14.0, virality_score=95,
                  key_quotes=["Uses YouTube player heatmaps.", "Processes using Gemini AI."],
                  transcript="Most people think it's magic. But it uses YouTube player heatmaps.",
                  title_suggestion="Unlock Video Virality Secrets",
                  caption_suggestion="Stop guessing what works! Here's how to use heatmaps to find viral hotspots in seconds. 🔥",
                  hashtag_suggestion="#viralclips #videoediting #heatmaps #aitools"),
        ViralClip(title="Grow on TikTok or Reels",          start_time=22.0, end_time=32.0, hook_time=27.0, virality_score=88,
                  key_quotes=["Changing how editors crop videos.", "If you want to grow on TikTok, try it."],
                  transcript="This is changing how editors crop videos. If you want to grow on TikTok, try it.",
                  title_suggestion="The Ultimate TikTok Growth Hack",
                  caption_suggestion="Want to scale your TikTok views? This tool will revolutionize your workflow. 🚀",
                  hashtag_suggestion="#tiktokgrowth #reels #shorts #editingtips"),
        ViralClip(title="Introductory overview of the tool", start_time=0.0,  end_time=11.0, hook_time=3.0, virality_score=72,
                  key_quotes=["Hello and welcome.", "Finds viral hotspots."],
                  transcript="Hello and welcome. It finds viral hotspots and highlights them.",
                  title_suggestion="Meet Xoraclips AI",
                  caption_suggestion="Say hello to your new AI co-editor. Find the absolute best parts of any video instantly.",
                  hashtag_suggestion="#xoraclips #aiediting #growthmindset"),
    ]
    mock_heatmap = [
        HeatmapPoint(start_time=i*10.0, end_time=(i+1)*10.0,
                     value=0.2 + (0.6 if i in [2,5,8,12,16] else 0.1))
        for i in range(20)
    ] if not heatmap else analysis.heatmap_points(heatmap)
    result = AnalyzeResponse(
        video_id=video_id, title=title, channel=channel, duration=duration or 200.0,
        heatmap=mock_heatmap,
        summary="Mock analysis: this video explains how Xoraclips works. #aitools #videoediting #productivity",
        clips=mock_clips,
        model="Mock Gemini"
    )
    yield _event(4, 100, 100, "Analysis Complete", "Generated 3 viral clip candidates successfully.",
                 done=True, result=result.model_dump())


# ── Gemini: a chain of models, a busy one tried twice ─────────────────────────

GEMINI_TRIES = 2        # per model, only when it is busy
RETRY_WAIT_SECONDS = 2

# Issue #124: a per-minute limit heals itself in tens of seconds, so waiting it
# out keeps the better model instead of dropping to the weakest one in the
# chain. A daily quota does not heal in time -- those have been reported as
# hours -- so anything past this ceiling falls through to the next model as
# before. 90s sits above the per-minute window and far below a daily one.
QUOTA_WAIT_MAX_SECONDS = 90

# A per-minute limit belongs to the key, not to one model, so when it is hit
# every model in the chain answers 429. Without a budget spanning the whole
# chain the real ceiling would be QUOTA_WAIT_MAX_SECONDS times its length.
QUOTA_WAIT_BUDGET_SECONDS = 120

# The wait is long enough that a silent stream looks like a hang, and long
# enough for an idle proxy to drop it, so it ticks the way _heartbeat does.
QUOTA_WAIT_TICK_SECONDS = 2


def _models_to_try(requested_model: str, discovered_flash: List[str]) -> List[str]:
    """The requested model first, then every discovered and known Flash model,
    newest first, so all of them are tried before giving up."""
    models_to_try = [requested_model]
    for fm in discovered_flash:
        if fm not in models_to_try:
            models_to_try.append(fm)
    for km in KNOWN_FLASH_MODELS:
        if km not in models_to_try:
            models_to_try.append(km)
    return models_to_try


async def _quota_wait_events(model_name: str, seconds: float):
    """Sleeps `seconds`, ticking throughout so the stream is never silent.

    Issue #124: the wait can run to QUOTA_WAIT_MAX_SECONDS, long enough for an
    idle proxy to drop the connection and long enough to look like a hang, so
    it keeps the stream alive exactly as _heartbeat does for a model call.
    """
    left = seconds
    while left > 0:
        step = min(QUOTA_WAIT_TICK_SECONDS, left)
        await asyncio.sleep(step)
        left -= step
        yield _event(4, 22, 75, "Quota Wait",
                     (f"{model_name} reached its per-minute limit - waiting "
                      f"{left:.0f}s more to keep using it instead of dropping "
                      f"to a weaker model..."),
                     f"{model_name} rate-limited - {left:.0f}s left...",
                     keepalive=True, model=model_name)


async def _heartbeat(task: asyncio.Task, model_name: str, n_lines: int, clip_range: str):
    """Events every 2 s while Gemini works: they keep mobile connections open
    and move the progress bar."""
    loop = asyncio.get_running_loop()
    call_start = loop.time()
    while not task.done():
        done, _ = await asyncio.wait([task], timeout=2.0)
        if not done:
            elapsed = int(loop.time() - call_start)
            stage, detail, step_prog = analysis.waiting_stage(elapsed, n_lines, model_name, clip_range)
            yield _event(4, step_prog, 70 + int(step_prog * 0.28), stage, detail,
                         f"[{model_name} | {elapsed}s] {stage}: {detail}",
                         keepalive=True, model=model_name, elapsed=elapsed)


async def _gemini_events(client, models_to_try: List[str], prompt: str, n_lines: int, clip_range: str,
                         outcome: dict):
    """Asks each model in turn until one answers with clips, passing progress on
    as events. Sets outcome["data"] and outcome["model"], or outcome["code"]
    when every model failed."""
    last_error = None
    encountered_quota_error = None
    key_rejected = False
    seen_codes: List[str] = []
    last_code = ai_errors.AI_FAILED
    analysis_data = None
    successful_model = None
    # Issue #124: a queue rather than a plain list, so a model whose
    # per-minute limit was waited out goes back to the front and is tried
    # again. The budget is chain-wide because the limit belongs to the key:
    # left per-model, every model in the chain would ask for its own wait.
    queue = list(models_to_try)
    quota_budget_left = float(QUOTA_WAIT_BUDGET_SECONDS)
    waited_models = set()

    while queue:
        model_name = queue.pop(0)
        next_model_hint = queue[0] if queue else None
        switch_announced = False
        quota_wait = 0.0

        for attempt in range(GEMINI_TRIES):
            if attempt > 0:
                wait = RETRY_WAIT_SECONDS
                yield _event(4, 25, 75, "Transient Retry",
                             f"{model_name} busy — waiting {wait}s before retry ({attempt + 1}/{GEMINI_TRIES})...",
                             f"{model_name} is busy — waiting {wait}s before retry {attempt + 1}/{GEMINI_TRIES}...",
                             model=model_name)
                await asyncio.sleep(wait)

            yield _event(4, 18, 74, "Neural Model Dispatch",
                         f"Dispatched {n_lines} lines to {model_name} (attempt {attempt + 1})...",
                         f"Calling {model_name} (attempt {attempt + 1}/{GEMINI_TRIES})...",
                         model=model_name)

            task = asyncio.create_task(asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=VideoAnalysis,
                    temperature=0.2,
                )
            ))
            async for event in _heartbeat(task, model_name, n_lines, clip_range):
                yield event

            try:
                resp_candidate = await task
                last_error = None
                parsed_data = analysis.parse_gemini_answer(resp_candidate, model_name)

                if parsed_data is not None:
                    clips_found = len(parsed_data.get('clips', []))
                    if clips_found == 0 and next_model_hint is not None:
                        logger.warning(f"{model_name} returned 0 clips. Will try next flash model {next_model_hint}...")
                        yield _event(4, 40, 78, "Flash Model Fallback",
                                     f"{model_name} returned 0 clips — switching to {next_model_hint} for deeper extraction...",
                                     f"{model_name} returned 0 clips — switching to {next_model_hint}...",
                                     model=next_model_hint)
                        last_error = Exception(f"{model_name} returned 0 clips")
                        switch_announced = True
                        break

                    analysis_data = parsed_data
                    successful_model = model_name
                    break
                else:
                    # A model that answered with nothing usable failed: it
                    # counts in the final error like any other failure.
                    last_error = Exception(f"{model_name} returned empty or unparseable response")
                    last_code = ai_errors.AI_FAILED
                    seen_codes.append(last_code)
                    break

            except Exception as e:
                last_error = e
                last_code = ai_errors.classify_gemini_error(e)
                if last_code == ai_errors.KEY_INVALID and not ai_errors.is_definitely_bad_key(e):
                    # A 403 for one model (e.g. a locked preview) says nothing
                    # about the key, which the up-front check already accepted.
                    last_code = ai_errors.MODEL_UNAVAILABLE
                seen_codes.append(last_code)
                logger.warning(f"Error from {model_name} (attempt {attempt + 1}, {last_code}): {e}")

                if ai_errors.is_definitely_bad_key(e):
                    # Every model will reject the same key: stop now.
                    key_rejected = True
                    break
                if last_code == ai_errors.KEY_QUOTA:
                    encountered_quota_error = e
                    # Issue #124: the server says how long to wait. Tens of
                    # seconds is a per-minute limit, worth sitting out to keep
                    # this model; hours are a daily quota, which is not. The
                    # retry is scheduled below rather than here, so it costs
                    # no GEMINI_TRIES slot and the call budget stays honest.
                    hint = ai_errors.retry_after_seconds(e)
                    if (hint is not None and 0 < hint <= QUOTA_WAIT_MAX_SECONDS
                            and hint <= quota_budget_left
                            and model_name not in waited_models):
                        quota_wait = hint
                    break
                # Only a busy server is worth retrying on the same model.
                if last_code != ai_errors.AI_BUSY:
                    break

        if analysis_data is not None or key_rejected:
            break

        if quota_wait:
            # Issue #124: a per-minute limit heals itself, so wait it out and
            # put this model back at the front rather than dropping to a
            # weaker one. Once per model and within the chain-wide budget,
            # both checked where quota_wait was set.
            waited_models.add(model_name)
            quota_budget_left -= quota_wait
            logger.info(f"{model_name} hit a per-minute limit; waiting "
                        f"{quota_wait:.0f}s as the server asked "
                        f"({quota_budget_left:.0f}s of budget left).")
            async for event in _quota_wait_events(model_name, quota_wait):
                yield event
            queue.insert(0, model_name)
            continue

        if next_model_hint is not None and not switch_announced:
            err_summary = {
                ai_errors.KEY_QUOTA: "quota reached",
                ai_errors.MODEL_UNAVAILABLE: "not available or deprecated",
                ai_errors.AI_FAILED: "failed",
            }.get(last_code, "temporarily busy")
            yield _event(4, 35, 76, "Flash Fallback",
                         f"{model_name} {err_summary} — switching to fallback {next_model_hint}...",
                         f"{model_name} {err_summary} — switching to flash fallback model {next_model_hint}...",
                         model=next_model_hint)

    if analysis_data is not None:
        outcome.update(data=analysis_data, model=successful_model)
        return
    # Several models may have failed differently; a retired model at the
    # end of the chain (404) must not hide "busy" or "wrong key".
    if seen_codes:
        code = ai_errors.most_relevant(seen_codes)
    elif last_error is not None:
        code = ai_errors.classify_gemini_error(last_error)
    else:
        code = ai_errors.AI_FAILED
    logger.error(f"Gemini analysis failed ({code}): {encountered_quota_error or last_error}")
    outcome["code"] = code


def _heatmap_events(heatmap: List[dict]) -> List[str]:
    events = [_event(2, 40, 35, "Scraping Retention", "Extracting viewer replay telemetry and retention curve...",
                     "Scraping player viewer retention curve...")]
    if heatmap:
        events.append(_event(2, 100, 50, "Retention Decoded",
                             f"Viewer retention heatmap loaded — {len(heatmap)} audience interest data points parsed.",
                             f"Viewer retention heatmap loaded — {len(heatmap)} data points scraped."))
    else:
        events.append(_event(2, 100, 50, "Dialogue Fallback",
                             "No heatmap curve available — relying on full transcript dialogue analysis.",
                             "No heatmap available for this video — will rely on transcript content analysis."))
    return events


async def _caption_events(request: AnalyzeRequest, video_id: str, duration: float, metadata: dict,
                          is_mock: bool, got: dict):
    """Step 3: the manual subtitles, or the captions from YouTube. The lines end
    up in got["lines"]; on failure an error event is sent and got stays empty."""
    if request.subtitles:
        yield _event(3, 30, 55, "Parsing Subtitles", "Parsing custom SRT/TXT subtitle timestamps...",
                     "Parsing manual subtitles...")
        try:
            transcript_lines = parse_manual_subtitles(request.subtitles, duration)
            if not transcript_lines:
                raise Exception("Custom subtitles parsed into empty array.")
            yield _event(3, 100, 70, "Subtitles Ready",
                         f"Custom subtitles parsed — {len(transcript_lines)} timestamped lines loaded.",
                         f"Custom subtitles parsed — {len(transcript_lines)} lines loaded successfully.")
        except Exception as e:
            yield _error(f"Failed to parse manual subtitles: {str(e)}", 400)
            return
        got["lines"] = transcript_lines
        return

    yield _event(3, 25, 55, "Fetching Subtitles", "Initializing multi-tier subtitle extraction pipeline...",
                 "Initializing multi-tier subtitle extraction pipeline...")
    try:
        if is_mock:
            transcript_lines = [dict(line) for line in MOCK_TRANSCRIPT]  # never contacts YouTube
        else:
            fetched = {}
            async for event in _transcript_events(video_id, request.proxy, fetched):
                yield event
            transcript_lines = fetched["lines"]
        yield _event(3, 100, 70, "Subtitles Ready",
                     f"Subtitles loaded — {len(transcript_lines)} dialogue sentences with timestamps ready.",
                     f"Subtitles loaded — {len(transcript_lines)} lines parsed successfully.")
    except Exception as e:
        yield _transcript_error(e, video_id, metadata)
        return
    got["lines"] = transcript_lines


# ── /api/analyze ──────────────────────────────────────────────────────────────

async def _analysis_events(request: AnalyzeRequest, gemini_key: Optional[str]):
    is_mock = is_mock_mode()
    if not gemini_key and not is_mock:
        yield _sse(ai_errors.error_event(ai_errors.KEY_MISSING))
        return
    # Check the key first: a wrong key must fail in a second, before the
    # YouTube metadata/transcript work (which can spend Supadata/proxy quota).
    if not is_mock:
        key_problem = await asyncio.to_thread(_gemini_key_problem, gemini_key)
        if key_problem:
            yield _sse(ai_errors.error_event(key_problem))
            return

    # ── Step 1: video ID and metadata ──
    video_id = extract_video_id(request.url)
    if not video_id:
        if not is_mock:
            yield _error("Invalid YouTube URL. Please check the link and try again.", 400)
            return
        video_id = "dQw4w9WgXcQ"
    # YouTube refused us recently: answer now instead of knocking again
    # (issue #9). Manual subtitles and Supadata (not YouTube) still go on.
    if not is_mock and not request.subtitles and not get_supadata_keys():
        remaining = youtube_errors.block_memory.remaining()
        if remaining:
            yield _sse(youtube_errors.error_event(youtube_errors.YOUTUBE_BLOCKED, remaining))
            return

    yield _event(1, 30, 8, "Connecting to YouTube", "Connecting to YouTube & fetching video metadata...",
                 "Connecting to YouTube — fetching video title and duration...")
    try:
        if is_mock:
            metadata = dict(MOCK_METADATA)  # MOCK_MODE never contacts YouTube
        else:
            metadata = await asyncio.to_thread(
                fetch_video_metadata, f"https://www.youtube.com/watch?v={video_id}", request.proxy)
        title, duration = metadata["title"], metadata["duration"]
        channel = metadata.get("channel", "")
        heatmap = metadata.get("heatmap") or []
        yield _event(1, 100, 25, "Video Verified", f"Loaded metadata for \"{title[:45]}\" ({int(duration)}s)",
                     f"Connected — \"{title[:45]}\" ({int(duration)}s)")
    except Exception as e:
        msg = e.detail if isinstance(e, HTTPException) else str(e)
        yield _error(f"Failed to fetch video details: {msg}", 500)
        return
    logger.info(f"Metadata fetched: title='{title}', duration={duration}s, heatmap_pts={len(heatmap)}")

    # ── Steps 2 and 3: heatmap and captions ──
    for event in _heatmap_events(heatmap):
        yield event
    got = {}
    async for event in _caption_events(request, video_id, duration, metadata, is_mock, got):
        yield event
    if "lines" not in got:
        return
    transcript_lines = got["lines"]

    duration = analysis.estimate_duration(duration, transcript_lines)
    try:
        transcript_lines, start_bound, end_bound, duration = analysis.apply_range(
            transcript_lines, duration, request.range_start, request.range_end)
    except AnalysisError as e:
        yield _error(e.message, e.status)
        return
    enriched = analysis.enrich_transcript(transcript_lines, heatmap)

    if is_mock:
        async for event in _mock_events(video_id, title, channel, duration, heatmap):
            yield event
        return

    # ── Step 4: Gemini ──
    is_long_video = duration > 3600
    # Issue #101: a transcript over the line limit is cut from the back, so
    # everything after this second is invisible to Gemini. Narrowing the end
    # bound here keeps the clip count, the clip bounds and the backup clips
    # inside what Gemini actually saw, instead of only the prompt text.
    cut_at = analysis.transcript_cut_at(enriched)
    searched_end = end_bound
    if cut_at is not None:
        end_bound = min(end_bound, cut_at)
    # Issue #34: never more clips than fit in the searched span.
    clip_range, capped_count = clip_lengths.clip_count_range(
        request.target_clip_count, is_long_video, end_bound - start_bound, request.duration)
    prompt, n_lines, _ = analysis.build_prompt(
        enriched, heatmap=heatmap, title=title, channel=channel, start_bound=start_bound,
        end_bound=end_bound, duration=duration, clip_duration=request.duration, clip_range=clip_range,
        custom_prompt=request.custom_prompt)
    requested_model = analysis.pick_model(request.model)

    yield _event(4, 10, 72, "Context Assembly",
                 f"Aligning {n_lines} dialogue segments with engagement data for {requested_model}...",
                 f"Assembling prompt and engagement context for {requested_model}...", model=requested_model)
    if cut_at is not None:
        # Issue #101: the transcript did not fit, so the end of the video never
        # reached Gemini. Saying so beats letting the user believe otherwise.
        yield _event(4, 11, 72, "Transcript Limit",
                     (f"Too many subtitle lines to analyse at once: only up to {_clock(cut_at)} "
                      f"was sent to {requested_model}, leaving the last "
                      f"{_clock(searched_end - cut_at)} unread. "
                      f"Set a search range over that part to analyse it."),
                     f"Only up to {_clock(cut_at)} fit the analysis limit...",
                     model=requested_model, transcript_cut_at=round(cut_at, 1),
                     transcript_unread_seconds=round(max(0.0, searched_end - cut_at), 1))
    if capped_count is not None:
        # end_bound is already narrowed to the cut, so this span agrees with
        # the Transcript Limit notice instead of contradicting it.
        yield _event(4, 12, 72, "Clip Count",
                     (f"{request.target_clip_count} clips of {clip_lengths.label(request.duration)} do not fit in "
                      f"{_clock(end_bound - start_bound)} of video: asking for at most {capped_count}."),
                     f"Asking for at most {capped_count} clip(s) so they do not overlap...", model=requested_model)

    client = genai.Client(api_key=gemini_key)
    models_to_try = _models_to_try(requested_model, await asyncio.to_thread(get_flash_models_for_key, client))
    logger.info(f"Flash fallback chain prepared: {models_to_try}")
    outcome = {}
    async for event in _gemini_events(client, models_to_try, prompt, n_lines, clip_range, outcome):
        yield event
    if "code" in outcome:
        yield _sse(ai_errors.error_event(outcome["code"]))
        return
    analysis_data, model = outcome["data"], outcome["model"]

    if len(analysis_data.get('clips', [])) == 0 and enriched:
        analysis_data['clips'] = analysis.backup_clips(enriched, request.duration, start_bound, end_bound)
        if not analysis_data.get('summary'):
            analysis_data['summary'] = (f"Analysis of \"{title}\" identifying {len(analysis_data['clips'])} "
                                        f"key segments. #viral #highlights")
    clip_count = len(analysis_data.get('clips', []))
    yield _event(4, 98, 98, "Clip Verification & Alignment",
                 f"Verified {clip_count} clip segments with precise video timestamps and key quotes.",
                 f"Found {clip_count} viral clip candidates with {model} — reconstructing transcripts...",
                 model=model)
    logger.info(f"Gemini analysis complete with {model}. Found {clip_count} clips.")

    clips = analysis.finish_clips(analysis_data.get('clips', []), enriched, request.duration,
                                  start_bound, end_bound, channel)
    result = analysis.build_response(
        video_id=video_id, title=title, channel=channel, duration=duration, heatmap=heatmap,
        summary=analysis_data.get("summary", ""), clips=clips, enriched_transcript=enriched, model=model,
        clip_duration=request.duration)
    yield _sse({"done": True, "result": result.model_dump()})


@router.post("/api/analyze")
async def analyze_video(
    request: AnalyzeRequest,
    x_gemini_api_key: Optional[str] = Header(None, alias=GEMINI_KEY_HEADER),
):
    """Stream real-time progress via Server-Sent Events, then deliver the final result.
    The Gemini key comes only from the X-Gemini-Api-Key header (issue #12)."""
    gemini_key = user_key_from_header(x_gemini_api_key)

    async def stream():
        # Scrub this exact key from every log line and event for the whole analysis.
        with tracked_secret(gemini_key):
            async for event in _analysis_events(request, gemini_key):
                yield event

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection":    "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
