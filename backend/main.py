import os

# Windows Python 3.14 compatibility hotfix for unix RTLD flags and uname used in yt-dlp plugins
for flag in ('RTLD_LAZY', 'RTLD_NOW', 'RTLD_GLOBAL', 'RTLD_LOCAL', 'RTLD_NODELETE', 'RTLD_NOLOAD', 'RTLD_DEEPBIND'):
    if not hasattr(os, flag):
        setattr(os, flag, 1)

if not hasattr(os, 'uname'):
    from collections import namedtuple
    UnameResult = namedtuple('UnameResult', ['sysname', 'nodename', 'release', 'version', 'machine'])
    os.uname = lambda: UnameResult('Windows', 'localhost', '10', '10.0', 'AMD64')

from dotenv import load_dotenv

# Automatically load environment variables from backend/.env or root .env
_base_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_base_dir, ".env"))
load_dotenv(os.path.join(_base_dir, "..", ".env"))
load_dotenv()

import re
import logging
import asyncio
import json
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

try:
    from backend.video_engine import (
        TEMP_DIR,
        EXPORTS_DIR,
        download_clip_segment,
        transcribe_clip_words,
        generate_ass_file,
        render_clip_to_mp4,
        detect_hardware_support,
        ACTIVE_ENCODER_NAME,
        has_emoji,
        render_title_overlay_png
    )
except ImportError:
    from video_engine import (
        TEMP_DIR,
        EXPORTS_DIR,
        download_clip_segment,
        transcribe_clip_words,
        generate_ass_file,
        render_clip_to_mp4,
        detect_hardware_support,
        ACTIVE_ENCODER_NAME,
        has_emoji,
        render_title_overlay_png
    )

try:
    from backend.captions import caption_chunks_for_clip
except ImportError:
    from captions import caption_chunks_for_clip

try:
    from backend.secrets_guard import (
        GEMINI_KEY_HEADER, install_log_redaction, is_mock_mode, redact_data,
        tracked_secret, user_key_from_header,
    )
    from backend import ai_errors
    from backend import youtube_errors
    from backend.youtube_errors import CaptionUnavailable, YouTubeBlocked
    from backend import title_rules
    from backend import clip_bounds
    from backend import clip_lengths
except ImportError:
    from secrets_guard import (
        GEMINI_KEY_HEADER, install_log_redaction, is_mock_mode, redact_data,
        tracked_secret, user_key_from_header,
    )
    import ai_errors
    import youtube_errors
    from youtube_errors import CaptionUnavailable, YouTubeBlocked
    import title_rules
    import clip_bounds
    import clip_lengths

try:
    from backend.youtube_source import (
        extract_video_id, fetch_transcript, fetch_video_metadata, get_supadata_keys,
        parse_manual_subtitles,
    )
except ImportError:
    from youtube_source import (
        extract_video_id, fetch_transcript, fetch_video_metadata, get_supadata_keys,
        parse_manual_subtitles,
    )

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("xoraclips")
# Scrub API keys from every log line (issue #8). Installed again at startup,
# after uvicorn has set up its own handlers.
install_log_redaction()


@asynccontextmanager
async def _lifespan(_app):
    # uvicorn has configured its log handlers by now; make sure they scrub keys too.
    install_log_redaction()
    if is_mock_mode():
        logger.warning("MOCK_MODE is on: analysis returns sample data and never calls Gemini or YouTube.")
    yield


app = FastAPI(
    title="XORACLIPS API",
    description="AI Powered YouTube Auto Clipper",
    lifespan=_lifespan,
)

# CORS (issue #45): only the app itself may read API responses. The frontend
# calls the API through the Vite proxy (same origin), so a browser tab on any
# other site gets no Access-Control-Allow-Origin header. Set ALLOWED_ORIGINS
# in .env (comma-separated) when the app is served from another address.
DEFAULT_ALLOWED_ORIGINS = "http://localhost:5174,http://127.0.0.1:5174"


def allowed_origins() -> List[str]:
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip() or DEFAULT_ALLOWED_ORIGINS
    # A browser's Origin never ends in "/", so "https://site/" would never match.
    origins = (origin.strip().rstrip("/") for origin in raw.split(","))
    return [origin for origin in origins if origin]


CORS_ORIGINS = allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", GEMINI_KEY_HEADER],
)


@app.middleware("http")
async def refuse_writes_from_other_sites(request: Request, call_next):
    """
    CORS only stops other sites from READING responses; a page can still send
    a POST without asking first (issue #45). A browser always sends Origin on
    such a request, so anything that changes state is refused unless it comes
    from an allowed origin. Requests without Origin (curl, scripts) pass; the
    Vite proxy forwards the app's own Origin, which is allowed.
    """
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/") not in CORS_ORIGINS:
            return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
    return await call_next(request)


# The endpoints are grouped in routes_* modules (#60); main.py builds the app.
try:
    from backend import routes_cookies, routes_downloads, routes_media, routes_system, routes_uploads
except ImportError:
    import routes_cookies
    import routes_downloads
    import routes_media
    import routes_system
    import routes_uploads

for _routes in (routes_system, routes_uploads, routes_cookies, routes_media, routes_downloads):
    app.include_router(_routes.router)

# ----------------------------------------------------------------
# Pydantic Schemas for Gemini Structured Output
# ----------------------------------------------------------------

class ViralClip(BaseModel):
    title: str = Field(description="Catchy clip title, max 8 words. MUST NEVER use first-person pronouns ('I', 'me', 'my', 'saya', 'aku'). Attribute to the speaker/host by name, role, or use objective framing.")
    start_time: float = Field(description="Clip start in seconds, aligned to a sentence boundary")
    end_time: float = Field(description="Clip end in seconds, aligned to a sentence boundary")
    hook_time: float = Field(description="Absolute timestamp in seconds from video start where the potential hook occurs inside this clip range (must be >= start_time and <= end_time)")
    virality_score: int = Field(description="Virality score 1-100")
    key_quotes: List[str] = Field(description="1-2 key quotes from the clip")
    transcript: str = Field(description="Spoken text of the clip")
    title_suggestion: str = Field(default="", description="Catchy alternative title suggestion. MUST NEVER use first-person pronouns ('I', 'me', 'my'). Attribute to speaker or objective topic.")
    caption_suggestion: str = Field(default="", description="Engaging social media caption suggestion attributing quotes or insights to the speaker.")
    hashtag_suggestion: str = Field(default="", description="Relevant hashtags suggestion (e.g. #hashtag1 #hashtag2)")
    # Issue #31: the checked hook titles, first = active (also in title and
    # title_suggestion). Empty for analyses made before this change.
    title_options: List[str] = Field(default_factory=list, description="Up to 3 hook titles; the first is the active one")
    content_type: str = Field(default="", description="Kind of content Gemini saw, e.g. lucu, edukasi, motivasi")

class TitleOption(BaseModel):
    text: str = Field(description="One hook title in casual Indonesian, following the HOOK TITLE RULES in the prompt")
    angle: str = Field(default="", description="The approach of this title: question, surprising statement, situation, reaction, or another")

class ViralClipGemini(BaseModel):
    title: str = Field(description="Same text as the first entry of title_options (a hook title in casual Indonesian). NEVER first-person ('I', 'me', 'my', 'saya', 'aku', 'gue').")
    start_time: float = Field(description="Clip start in seconds, aligned to a sentence boundary")
    end_time: float = Field(description="Clip end in seconds, aligned to a sentence boundary")
    hook_time: float = Field(description="Absolute timestamp in seconds from video start where the potential hook occurs inside this clip range (must be >= start_time and <= end_time)")
    virality_score: int = Field(description="Virality score 1-100")
    key_quotes: List[str] = Field(description="1-2 key quotes from the clip")
    title_suggestion: str = Field(default="", description="Leave empty: alternative titles go in title_options.")
    caption_suggestion: str = Field(default="", description="Engaging social media caption suggestion attributing insights or story to the speaker.")
    hashtag_suggestion: str = Field(default="", description="Relevant hashtags suggestion (e.g. #hashtag1 #hashtag2)")
    title_options: List[TitleOption] = Field(description="Exactly the number of hook titles the HOOK TITLE RULES ask for, strongest first, each with a different angle")
    content_type: str = Field(default="", description="Kind of content in this clip, e.g. lucu, edukasi/kesehatan, motivasi, kontroversi, cerita")

class VideoAnalysis(BaseModel):
    summary: str = Field(description="1-2 sentence video summary, followed by 2-4 general hashtags (e.g. #podcast #marriage #success)")
    clips: List[ViralClipGemini] = Field(description="List of viral clip candidates, sorted by virality_score desc")

# ----------------------------------------------------------------
# API Request/Response Schemas
# ----------------------------------------------------------------

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

class HeatmapPoint(BaseModel):
    start_time: float
    end_time: float
    value: float

class TranscriptLine(BaseModel):
    start: float
    end: float
    text: str
    engagement: Optional[float] = None

class AnalyzeResponse(BaseModel):
    video_id: str
    title: str
    channel: Optional[str] = None
    duration: float
    heatmap: List[HeatmapPoint]
    summary: str
    clips: List[ViralClip]
    transcript: Optional[List[TranscriptLine]] = None
    model: Optional[str] = None

# ----------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------


def lowercase_hashtags_in_string(text: str) -> str:
    """Finds all hashtags (#word) in a string and converts them to lowercase."""
    if not text:
        return text
    return re.sub(r'#\w+', lambda m: m.group(0).lower(), text)

def sanitize_first_person_title(title: str, speaker_or_channel: str = "") -> str:
    """
    Sanitizes accidental first-person perspective ('I', 'Me', 'My', 'Saya', 'Aku', 'Gue')
    from generated clip titles and title suggestions, replacing them with speaker or channel attribution,
    or objective framing so titles never appear as the user's personal opinion.
    """
    if not title:
        return title
    t = title.strip()
    speaker = speaker_or_channel.strip() if speaker_or_channel else ""
    subject = speaker if speaker else "The Speaker"

    # 1. English Why / How / What / When / Where
    t = re.sub(r"^why\s+i\s+think\b", f"{subject} Explains Why", t, flags=re.IGNORECASE)
    t = re.sub(r"^why\s+i\s+believe\b", f"{subject} Explains Why", t, flags=re.IGNORECASE)
    t = re.sub(r"^why\s+i\s+", f"Why {subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^how\s+i\s+", f"How {subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^what\s+i\s+think\b", f"{subject}'s Thoughts On", t, flags=re.IGNORECASE)
    t = re.sub(r"^what\s+i\s+learned\b", f"What {subject} Learned", t, flags=re.IGNORECASE)
    t = re.sub(r"^what\s+i\s+", f"What {subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^when\s+i\s+", f"When {subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^where\s+i\s+", f"Where {subject} ", t, flags=re.IGNORECASE)

    # 2. English My [Noun] (e.g. My Opinion, My Story, My Regret)
    t = re.sub(r"^my\s+([a-zA-Z]+)", lambda m: f"{subject}'s {m.group(1)}" if speaker else f"The {m.group(1)}", t, flags=re.IGNORECASE)

    # 3. English First-person action verbs (e.g. I Tried, I Discovered, I Built)
    t = re.sub(r"^i\s+(tried|found|made|discovered|bought|quit|lost|learned|realized|spent|built|saw|went|started|joined|left|hate|love)\b", rf"{subject} \1", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+was\b", f"{subject} Was", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+am\b", f"{subject} Is", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+have\b", f"{subject} Has", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+had\b", f"{subject} Had", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+got\b", f"{subject} Got", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+think\b", f"{subject} Thinks", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+believe\b", f"{subject} Believes", t, flags=re.IGNORECASE)

    # 4. Indonesian / Malay first-person replacements (Saya, Aku, Gue, Gw)
    indo_subject = speaker if speaker else "Host"
    t = re.sub(r"^(kenapa|mengapa)\s+(saya|aku|gue|gw)\s+", rf"\1 {indo_subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^(cara|bagaimana)\s+(saya|aku|gue|gw)\s+", rf"Cara {indo_subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^(alasan)\s+(saya|aku|gue|gw)\s+", rf"Alasan {indo_subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^(saya|aku|gue|gw)\s+(mencoba|menemukan|membuat|yakin|berpikir|menyesal|kehilangan|belajar|mulai|berhenti)\b", rf"{indo_subject} \2", t, flags=re.IGNORECASE)
    t = re.sub(r"^(pendapat|opini)\s+(saya|aku|gue|gw)\b", rf"Opini {indo_subject}", t, flags=re.IGNORECASE)

    return t.strip()

def get_average_heatmap_value(start: float, end: float, heatmap: List[dict]) -> float:
    """Calculates the average retention score from the heatmap for a transcript time segment."""
    if not heatmap:
        return 0.0
    
    overlaps = []
    for point in heatmap:
        p_start = point.get('start_time', 0.0)
        p_end = point.get('end_time', 0.0)
        p_val = point.get('value', 0.0)
        
        # Check if heatmap point overlaps with transcript segment
        if max(start, p_start) < min(end, p_end):
            overlaps.append(p_val)
            
    if overlaps:
        return sum(overlaps) / len(overlaps)
        
    # Fallback to closest point if no direct overlap matches
    closest_val = 0.0
    min_dist = float('inf')
    mid_time = (start + end) / 2.0
    for point in heatmap:
        p_mid = (point.get('start_time', 0.0) + point.get('end_time', 0.0)) / 2.0
        dist = abs(p_mid - mid_time)
        if dist < min_dist:
            min_dist = dist
            closest_val = point.get('value', 0.0)
    return closest_val

# ----------------------------------------------------------------
# Routes
# ----------------------------------------------------------------

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

def get_flash_models_for_key(client: genai.Client) -> List[str]:
    """Dynamically query all available flash models for the given API key.
    Discovers newer versions (e.g., 3.7, 3.6, 3.5) and earlier versions (2.5, 2.0, 1.5),
    merging with known fallback models and sorting in descending order of version/capability."""
    discovered = []
    try:
        models_page = client.models.list()
        for m in models_page:
            name = m.name or ""
            short_name = name.split('/')[-1]
            if "gemini" in short_name.lower() and "flash" in short_name.lower():
                if m.supported_actions and "generateContent" not in m.supported_actions:
                    continue
                # Exclude non-text, specialized, or non-generative tasks
                exclude_keywords = [
                    'tuning', 'thinking', 'vision', 'image', 'tts',
                    'omni', 'customtools', 'embed', 'realtime', 'robotics'
                ]
                if not any(x in short_name.lower() for x in exclude_keywords):
                    if short_name not in discovered:
                        discovered.append(short_name)
    except Exception as e:
        logger.warning(f"Could not dynamically list models: {e}")

    # Combine discovered with known flash models, preserving uniqueness
    combined_pool = list(dict.fromkeys(discovered + KNOWN_FLASH_MODELS))
    # Sort descending so newest versions (3.7, 3.6, 3.5, 2.5, 2.0, 1.5) are prioritized
    ordered = sorted(combined_pool, key=parse_gemini_model_sort_key, reverse=True)
    return ordered


@app.get("/api/models")
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
        models_page = client.models.list()
        
        flash_models = []
        pro_models = []
        other_models = []
        
        for m in models_page:
            name = m.name or ""
            if "gemini" in name.lower():
                if m.supported_actions and "generateContent" not in m.supported_actions:
                    continue
                
                short_name = name.split('/')[-1]
                exclude_keywords = [
                    'tuning', 'thinking', 'vision', 'image', 'tts',
                    'omni', 'customtools', 'embed', 'realtime', 'robotics'
                ]
                if any(x in short_name.lower() for x in exclude_keywords):
                    continue
                
                if "flash" in short_name.lower():
                    if short_name not in flash_models:
                        flash_models.append(short_name)
                elif "pro" in short_name.lower():
                    if short_name not in pro_models:
                        pro_models.append(short_name)
                elif any(x in short_name.lower() for x in ['lite', 'exp']):
                    if short_name not in other_models:
                        other_models.append(short_name)
        
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


@app.post("/api/analyze")
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
            async for event in analysis_events():
                yield event

    async def analysis_events():
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

        # ── Step 1: Extract video ID & metadata ─────────────────────────────
        video_id = extract_video_id(request.url)
        if not video_id:
            if not is_mock:
                yield _sse({"error": "Invalid YouTube URL. Please check the link and try again.", "status": 400})
                return
            video_id = "dQw4w9WgXcQ"

        # YouTube refused us recently: answer now instead of knocking again
        # (issue #9). Manual subtitles and Supadata (not YouTube) still go on.
        if not is_mock and not request.subtitles and not get_supadata_keys():
            remaining = youtube_errors.block_memory.remaining()
            if remaining:
                yield _sse(youtube_errors.error_event(youtube_errors.YOUTUBE_BLOCKED, remaining))
                return

        canonical_url = f"https://www.youtube.com/watch?v={video_id}"

        yield _sse({
            "step": 1,
            "step_progress": 30,
            "overall_progress": 8,
            "stage": "Connecting to YouTube",
            "detail": "Connecting to YouTube & fetching video metadata...",
            "message": "Connecting to YouTube — fetching video title and duration..."
        })

        channel = ""
        try:
            if is_mock:
                # MOCK_MODE never contacts YouTube: use the sample metadata.
                metadata = dict(MOCK_METADATA)
            else:
                metadata = await asyncio.to_thread(fetch_video_metadata, canonical_url, request.proxy)
            title    = metadata["title"]
            channel  = metadata.get("channel", "")
            duration = metadata["duration"]
            heatmap  = metadata.get("heatmap") or []
            is_live  = metadata.get("is_live", False)
            live_status = metadata.get("live_status", "not_live")
            yield _sse({
                "step": 1,
                "step_progress": 100,
                "overall_progress": 25,
                "stage": "Video Verified",
                "detail": f"Loaded metadata for \"{title[:45]}\" ({int(duration)}s)",
                "message": f"Connected — \"{title[:45]}\" ({int(duration)}s)"
            })
        except Exception as e:
            msg = e.detail if isinstance(e, HTTPException) else str(e)
            yield _sse({"error": f"Failed to fetch video details: {msg}", "status": 500})
            return

        logger.info(f"Metadata fetched: title='{title}', duration={duration}s, heatmap_pts={len(heatmap)}")

        # ── Step 2: Heatmap ──────────────────────────────────────────────────
        yield _sse({
            "step": 2,
            "step_progress": 40,
            "overall_progress": 35,
            "stage": "Scraping Retention",
            "detail": "Extracting viewer replay telemetry and retention curve...",
            "message": "Scraping player viewer retention curve..."
        })
        if heatmap:
            yield _sse({
                "step": 2,
                "step_progress": 100,
                "overall_progress": 50,
                "stage": "Retention Decoded",
                "detail": f"Viewer retention heatmap loaded — {len(heatmap)} audience interest data points parsed.",
                "message": f"Viewer retention heatmap loaded — {len(heatmap)} data points scraped."
            })
        else:
            yield _sse({
                "step": 2,
                "step_progress": 100,
                "overall_progress": 50,
                "stage": "Dialogue Fallback",
                "detail": "No heatmap curve available — relying on full transcript dialogue analysis.",
                "message": "No heatmap available for this video — will rely on transcript content analysis."
            })

        # ── Step 3: Transcript ───────────────────────────────────────────────
        if request.subtitles:
            yield _sse({
                "step": 3,
                "step_progress": 30,
                "overall_progress": 55,
                "stage": "Parsing Subtitles",
                "detail": "Parsing custom SRT/TXT subtitle timestamps...",
                "message": "Parsing manual subtitles..."
            })
            try:
                transcript_lines = parse_manual_subtitles(request.subtitles, duration)
                if not transcript_lines:
                    raise Exception("Custom subtitles parsed into empty array.")
                yield _sse({
                    "step": 3,
                    "step_progress": 100,
                    "overall_progress": 70,
                    "stage": "Subtitles Ready",
                    "detail": f"Custom subtitles parsed — {len(transcript_lines)} timestamped lines loaded.",
                    "message": f"Custom subtitles parsed — {len(transcript_lines)} lines loaded successfully."
                })
            except Exception as e:
                yield _sse({"error": f"Failed to parse manual subtitles: {str(e)}", "status": 400})
                return
        else:
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

            # Initial stage event
            yield _sse({
                "step": 3,
                "step_progress": 25,
                "overall_progress": 55,
                "stage": "Fetching Subtitles",
                "detail": "Initializing multi-tier subtitle extraction pipeline...",
                "message": "Initializing multi-tier subtitle extraction pipeline..."
            })

            try:
                if is_mock:
                    # MOCK_MODE never contacts YouTube: use the sample transcript.
                    transcript_lines = [dict(line) for line in MOCK_TRANSCRIPT]
                else:
                    task = asyncio.create_task(
                        asyncio.to_thread(fetch_transcript, video_id, request.proxy, progress_callback)
                    )

                    while not task.done():
                        try:
                            evt = await asyncio.wait_for(progress_queue.get(), timeout=0.2)
                            yield _sse(evt)
                        except asyncio.TimeoutError:
                            pass

                    while not progress_queue.empty():
                        yield _sse(progress_queue.get_nowait())

                    transcript_lines = await task
                yield _sse({
                    "step": 3,
                    "step_progress": 100,
                    "overall_progress": 70,
                    "stage": "Subtitles Ready",
                    "detail": f"Subtitles loaded — {len(transcript_lines)} dialogue sentences with timestamps ready.",
                    "message": f"Subtitles loaded — {len(transcript_lines)} lines parsed successfully."
                })
            except Exception as e:
                # A short message per cause; the details are already in the log.
                if isinstance(e, YouTubeBlocked):
                    yield _sse(youtube_errors.error_event(e.code, e.retry_after))
                elif is_live or live_status in ('is_live', 'is_upcoming', 'post_live'):
                    yield _sse(youtube_errors.error_event(youtube_errors.VIDEO_LIVE))
                elif isinstance(e, CaptionUnavailable):
                    yield _sse(youtube_errors.error_event(e.code))
                else:
                    logger.exception(f"Subtitle retrieval failed unexpectedly for {video_id}")
                    yield _sse(youtube_errors.error_event(youtube_errors.CAPTIONS_UNAVAILABLE))
                return

        # Estimate duration from transcript if missing
        if duration == 0.0 and transcript_lines:
            last = transcript_lines[-1]
            duration = last.get("start", 0.0) + last.get("duration", 0.0)


        # Slice transcript based on custom search range if provided
        start_bound = 0.0
        end_bound = duration
        if request.range_start is not None or request.range_end is not None:
            start_bound = request.range_start if request.range_start is not None else 0.0
            end_bound = request.range_end if request.range_end is not None else duration

            if start_bound < 0.0:
                start_bound = 0.0
            if end_bound > duration:
                end_bound = duration

            if start_bound >= end_bound:
                yield _sse({"error": "Invalid search range: start time must be less than end time.", "status": 400})
                return

            filtered_lines = []
            for line in transcript_lines:
                ls = line.get("start", 0.0)
                le = ls + line.get("duration", 0.0)
                if max(ls, start_bound) < min(le, end_bound):
                    filtered_lines.append(line)
            
            transcript_lines = filtered_lines
            if not transcript_lines:
                yield _sse({"error": f"No subtitles found in the specified range {start_bound}s to {end_bound}s.", "status": 400})
                return
            
            duration = end_bound - start_bound
            logger.info(f"Filtered transcript to custom range: {start_bound}s to {end_bound}s (duration: {duration}s)")

        # Enrich transcript with heatmap engagement scores
        enriched_transcript = []
        for line in transcript_lines:
            ls   = line.get("start", 0.0)
            ld   = line.get("duration", 0.0)
            le   = ls + ld
            score = get_average_heatmap_value(ls, le, heatmap)
            enriched_transcript.append({
                "start":      round(ls, 2),
                "end":        round(le, 2),
                "text":       line.get("text", ""),
                "engagement": round(score, 3)
            })

        # ── Mock short-circuit ───────────────────────────────────────────────
        if is_mock:
            mock_stages = [
                ("Context Assembly", "Aligning 9 transcript dialogue lines with retention telemetry...", 30, 78),
                ("Viral Hook & Curiosity Detection", "Scanning transcript dialogue for viral hooks & curiosity gaps...", 65, 88),
                ("Virality Scoring & Selection", "Calculating virality coefficients and formatting clip candidates...", 92, 95),
            ]
            for s_name, s_detail, s_prog, o_prog in mock_stages:
                yield _sse({
                    "step": 4,
                    "step_progress": s_prog,
                    "overall_progress": o_prog,
                    "stage": s_name,
                    "detail": s_detail,
                    "model": "gemini-2.5-flash (Mock)",
                    "message": f"Mock AI ({s_name}): {s_detail}"
                })
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
            ] if not heatmap else [
                HeatmapPoint(start_time=float(pt.get('start_time',0.0)),
                             end_time=float(pt.get('end_time',0.0)),
                             value=float(pt.get('value',0.0)))
                for pt in heatmap
            ]
            result = AnalyzeResponse(
                video_id=video_id, title=title, channel=channel, duration=duration or 200.0,
                heatmap=mock_heatmap,
                summary="Mock analysis: this video explains how Xoraclips works. #aitools #videoediting #productivity",
                clips=mock_clips,
                model="Mock Gemini"
            )
            yield _sse({
                "step": 4,
                "step_progress": 100,
                "overall_progress": 100,
                "stage": "Analysis Complete",
                "detail": "Generated 3 viral clip candidates successfully.",
                "done": True,
                "result": result.model_dump()
            })
            return

        is_long_video = duration > 3600
        # Issue #34: never more clips than fit in the searched span.
        clip_range, capped_count = clip_lengths.clip_count_range(
            request.target_clip_count, is_long_video, end_bound - start_bound, request.duration)

        # ── Step 4: Build prompt ─────────────────────────────────────────────
        transcript_dump = []
        for line in enriched_transcript:
            eng = f"|{line['engagement']:.2f}" if heatmap and line['engagement'] > 0 else ""
            transcript_dump.append(f"{line['start']:.1f}|{line['end']:.1f}{eng} {line['text']}")

        MAX_LINES = 2500 if is_long_video else 800
        if len(transcript_dump) > MAX_LINES:
            logger.warning(f"Transcript {len(transcript_dump)} lines — truncating to {MAX_LINES}.")
            transcript_dump = transcript_dump[:MAX_LINES]

        transcript_text = "\n".join(transcript_dump)
        dur_range   = clip_lengths.prompt_range(request.duration)
        heatmap_note = (
            "Columns: start|end|audience_interest(0-1). Prioritise high-interest peaks."
            if heatmap else
            "No audience interest data. Use content hooks, energy, and story arcs."
        )
        focus_instruction = ""
        if request.custom_prompt and request.custom_prompt.strip():
            focus_instruction = f"CRITICAL FOCUS: The user specifically wants you to find clips matching the following query/theme: \"{request.custom_prompt.strip()}\". Prioritize and tailor your selection of viral clips to fit this request, while still ensuring they make good standalone clips.\n\n"

        channel_context = f"- Channel / Host / Creator: {channel}\n" if channel else ""

        prompt = (
            f"You are an expert viral video clip editor finding top clip candidates for TikTok, Instagram Reels, and YouTube Shorts.\n"
            f"Analyze this YouTube video transcript and find {clip_range} high-performing, standalone clip candidates.\n\n"
            f"VIDEO CONTEXT:\n"
            f"- Video Title: {title}\n"
            f"{channel_context}"
            f"- Video Duration: {int(start_bound)}s to {int(end_bound)}s (Total: {int(duration)}s) | Target clip length: {dur_range}\n"
            f"- Heatmap: {heatmap_note}\n\n"
            f"{focus_instruction}"
            f"{clip_lengths.prompt_rules(request.duration)}"
            f"{title_rules.prompt_rules()}"
            f"Write caption_suggestion, key_quotes and hashtag_suggestion in the language of the transcript.\n\n"
            f"Transcript (start|end[|interest] text):\n---\n{transcript_text}\n---\n\n"
            f"Rules: use exact seconds from transcript; clips must start/end at sentence boundaries; do not overlap.\n"
            f"Return {clip_range} clips sorted by virality_score desc."
        )

        requested_model = (request.model or 'gemini-2.5-flash').strip()
        if any(dep in requested_model.lower() for dep in ['gemini-1.0', 'gemini-pro-vision']):
            logger.info(f"Requested model '{requested_model}' is outdated. Upgrading to gemini-2.5-flash.")
            requested_model = 'gemini-2.5-flash'

        yield _sse({
            "step": 4,
            "step_progress": 10,
            "overall_progress": 72,
            "stage": "Context Assembly",
            "detail": f"Aligning {len(transcript_dump)} dialogue segments with engagement data for {requested_model}...",
            "model": requested_model,
            "message": f"Assembling prompt and engagement context for {requested_model}..."
        })
        if capped_count is not None:
            span_s = int(end_bound - start_bound)
            yield _sse({
                "step": 4,
                "step_progress": 12,
                "overall_progress": 72,
                "stage": "Clip Count",
                "detail": (f"{request.target_clip_count} clips of {clip_lengths.label(request.duration)} do not fit in "
                           f"{span_s // 60}:{span_s % 60:02d} of video: asking for at most {capped_count}."),
                "model": requested_model,
                "message": f"Asking for at most {capped_count} clip(s) so they do not overlap...",
            })

        # ── Step 4: Gemini API call with dynamic Flash fallback models and retry ───────────
        client = genai.Client(api_key=gemini_key)
        
        # Discover all available Flash models for the user's API key
        discovered_flash = await asyncio.to_thread(get_flash_models_for_key, client)
        
        # Build models_to_try:
        # 1. Start with the requested model
        # 2. Append all discovered and known flash models in version descending order (e.g. 3.7, 3.6, 3.5, 2.5, 2.0, 1.5)
        #    so all available flash models are tried before giving up
        models_to_try = [requested_model]
        for fm in discovered_flash:
            if fm not in models_to_try:
                models_to_try.append(fm)
        for km in KNOWN_FLASH_MODELS:
            if km not in models_to_try:
                models_to_try.append(km)

        logger.info(f"Flash fallback chain prepared: {models_to_try}")

        response = None
        last_error = None
        encountered_quota_error = None
        key_rejected = False
        seen_codes: List[str] = []
        last_code = ai_errors.AI_FAILED
        analysis_data = None
        successful_model = None

        for idx, model_name in enumerate(models_to_try):
            next_model_hint = models_to_try[idx + 1] if idx + 1 < len(models_to_try) else None

            MAX_RETRIES = 2
            
            for attempt in range(MAX_RETRIES):
                if attempt > 0:
                    wait = 2
                    yield _sse({
                        "step": 4,
                        "step_progress": 25,
                        "overall_progress": 75,
                        "stage": "Transient Retry",
                        "detail": f"{model_name} busy — waiting {wait}s before retry ({attempt + 1}/{MAX_RETRIES})...",
                        "model": model_name,
                        "message": f"{model_name} is busy — waiting {wait}s before retry {attempt + 1}/{MAX_RETRIES}..."
                    })
                    await asyncio.sleep(wait)
                
                yield _sse({
                    "step": 4,
                    "step_progress": 18,
                    "overall_progress": 74,
                    "stage": "Neural Model Dispatch",
                    "detail": f"Dispatched {len(transcript_dump)} lines to {model_name} (attempt {attempt + 1})...",
                    "model": model_name,
                    "message": f"Calling {model_name} (attempt {attempt + 1}/{MAX_RETRIES})..."
                })
                
                # Execute Gemini call with heartbeat to keep mobile connection alive and show live stages
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
                
                call_start = asyncio.get_event_loop().time()
                while not task.done():
                    done, _ = await asyncio.wait([task], timeout=2.0)
                    if not done:
                        elapsed = int(asyncio.get_event_loop().time() - call_start)
                        
                        if elapsed < 5:
                            stage = "Neural Context Loading"
                            detail = f"Transmitting {len(transcript_dump)} timestamped dialogue segments to {model_name}..."
                            step_prog = min(35, 12 + elapsed * 4)
                        elif elapsed < 12:
                            stage = "Retention Spike Cross-Analysis"
                            detail = f"Correlating viewer retention peaks against speaker dialogue to isolate viral moments..."
                            step_prog = min(55, 35 + int((elapsed - 5) * 3))
                        elif elapsed < 20:
                            stage = "Viral Hook & Curiosity Detection"
                            detail = f"Scanning transcript dialogue for opening hooks, punchlines, controversial takes & emotional peaks..."
                            step_prog = min(72, 55 + int((elapsed - 12) * 2.2))
                        elif elapsed < 30:
                            stage = "Coherence & Sentence Boundary Snapping"
                            detail = f"Ensuring clip candidates start and end naturally on sentence boundaries without mid-word cuts..."
                            step_prog = min(85, 72 + int((elapsed - 20) * 1.3))
                        elif elapsed < 42:
                            stage = "Virality Scoring & Selection"
                            detail = f"Calculating virality coefficients (1-100) and selecting the top {clip_range} highest potential clips..."
                            step_prog = min(92, 85 + int((elapsed - 30) * 0.7))
                        else:
                            stage = "Social Media Metadata Synthesis"
                            detail = f"Drafting attention-grabbing titles, social captions, and targeted hashtags ({elapsed}s)..."
                            step_prog = min(95, 92 + min(3, int((elapsed - 42) * 0.3)))

                        overall_prog = 70 + int(step_prog * 0.28)
                        yield _sse({
                            "step": 4,
                            "keepalive": True,
                            "step_progress": step_prog,
                            "overall_progress": overall_prog,
                            "stage": stage,
                            "detail": detail,
                            "model": model_name,
                            "elapsed": elapsed,
                            "message": f"[{model_name} | {elapsed}s] {stage}: {detail}"
                        })
                
                try:
                    resp_candidate = await task
                    last_error = None
                    
                    # Parse structured response
                    parsed_data = None
                    if hasattr(resp_candidate, 'parsed') and resp_candidate.parsed is not None:
                        parsed = resp_candidate.parsed
                        parsed_data = {
                            "summary": getattr(parsed, 'summary', ''),
                            "clips": [
                                {
                                    "title": getattr(c, 'title', ''),
                                    "start_time": getattr(c, 'start_time', 0.0),
                                    "end_time": getattr(c, 'end_time', 0.0),
                                    "hook_time": getattr(c, 'hook_time', None),
                                    "virality_score": getattr(c, 'virality_score', 0),
                                    "key_quotes": getattr(c, 'key_quotes', []),
                                    "title_suggestion": getattr(c, 'title_suggestion', ''),
                                    "caption_suggestion": getattr(c, 'caption_suggestion', ''),
                                    "hashtag_suggestion": getattr(c, 'hashtag_suggestion', ''),
                                    "title_options": [
                                        {"text": getattr(o, 'text', ''), "angle": getattr(o, 'angle', '')}
                                        for o in (getattr(c, 'title_options', []) or [])
                                    ],
                                    "content_type": getattr(c, 'content_type', ''),
                                }
                                for c in (getattr(parsed, 'clips', []) or [])
                            ]
                        }
                    elif resp_candidate.text:
                        raw_text = resp_candidate.text.strip()
                        if raw_text.startswith("```"):
                            raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
                            raw_text = re.sub(r"\n?```$", "", raw_text)
                        try:
                            parsed_data = json.loads(raw_text)
                        except Exception as json_err:
                            logger.warning(f"JSON parsing error from {model_name}: {json_err}")
                            parsed_data = None

                    if parsed_data is not None:
                        clips_found = len(parsed_data.get('clips', []))
                        if clips_found == 0 and next_model_hint is not None:
                            logger.warning(f"{model_name} returned 0 clips. Will try next flash model {next_model_hint}...")
                            yield _sse({
                                "step": 4,
                                "step_progress": 40,
                                "overall_progress": 78,
                                "stage": "Flash Model Fallback",
                                "detail": f"{model_name} returned 0 clips — switching to {next_model_hint} for deeper extraction...",
                                "model": next_model_hint,
                                "message": f"{model_name} returned 0 clips — switching to {next_model_hint}..."
                            })
                            last_error = Exception(f"{model_name} returned 0 clips")
                            break
                        
                        response = resp_candidate
                        analysis_data = parsed_data
                        successful_model = model_name
                        break
                    else:
                        last_error = Exception(f"{model_name} returned empty or unparseable response")
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
                        break
                    # Only a busy server is worth retrying on the same model.
                    if last_code != ai_errors.AI_BUSY:
                        break

            if analysis_data is not None and response is not None:
                break
            if key_rejected:
                break
                
            if next_model_hint is not None:
                err_summary = {
                    ai_errors.KEY_QUOTA: "quota reached",
                    ai_errors.MODEL_UNAVAILABLE: "not available or deprecated",
                }.get(last_code, "temporarily busy")
                yield _sse({
                    "step": 4,
                    "step_progress": 35,
                    "overall_progress": 76,
                    "stage": "Flash Fallback",
                    "detail": f"{model_name} {err_summary} — switching to fallback {next_model_hint}...",
                    "model": next_model_hint,
                    "message": f"{model_name} {err_summary} — switching to flash fallback model {next_model_hint}..."
                })

        if analysis_data is None:
            # If any model in the fallback chain suffered quota exhaustion, prioritize showing the quota explanation
            # Several models may have failed differently; a retired model at the
            # end of the chain (404) must not hide "busy" or "wrong key".
            if seen_codes:
                code = ai_errors.most_relevant(seen_codes)
            elif last_error is not None:
                code = ai_errors.classify_gemini_error(last_error)
            else:
                code = ai_errors.AI_FAILED
            logger.error(f"Gemini analysis failed ({code}): {encountered_quota_error or last_error}")
            yield _sse(ai_errors.error_event(code))
            return

        # Fallback clip synthesis if 0 clips were returned after all models
        if len(analysis_data.get('clips', [])) == 0 and enriched_transcript:
            logger.info("Generating fallback clips from heatmap and transcript segments...")
            sorted_lines = sorted(enriched_transcript, key=lambda l: l.get('engagement', 0.0), reverse=True)
            # Issue #34: windows around the peaks that do not overlap and stay
            # inside the searched range (end_bound, not the range's length).
            windows = clip_lengths.backup_windows(
                [l['start'] for l in sorted_lines], request.duration, start_bound, end_bound)

            fallback_clips_list = []
            for i, (st, et, peak) in enumerate(windows):
                seg_lines = [l['text'] for l in enriched_transcript if max(l['start'], st) < min(l['end'], et)]
                seg_text = " ".join(seg_lines).strip()
                preview = seg_text[:60] + "..." if len(seg_text) > 60 else seg_text or f"Viral Highlight #{i+1}"
                fallback_clips_list.append({
                    "title": f"Key Highlight #{i+1}",
                    "start_time": st,
                    "end_time": et,
                    "hook_time": peak,
                    "virality_score": max(70, int(95 - i * 5)),
                    "key_quotes": [seg_text[:80]] if seg_text else [],
                    "title_suggestion": f"Must Watch Moment #{i+1}",
                    "caption_suggestion": f"Key highlight from video: {preview} #viral #trending",
                    "hashtag_suggestion": "#viral #shorts #trending",
                    "is_fallback": True,
                })
            analysis_data['clips'] = fallback_clips_list
            if not analysis_data.get('summary'):
                analysis_data['summary'] = f"Analysis of \"{title}\" identifying {len(fallback_clips_list)} key segments. #viral #highlights"

        clip_count = len(analysis_data.get('clips', []))
        yield _sse({
            "step": 4,
            "step_progress": 98,
            "overall_progress": 98,
            "stage": "Clip Verification & Alignment",
            "detail": f"Verified {clip_count} clip segments with precise video timestamps and key quotes.",
            "model": successful_model or requested_model,
            "message": f"Found {clip_count} viral clip candidates with {successful_model or requested_model} — reconstructing transcripts..."
        })
        logger.info(f"Gemini analysis complete with {successful_model or requested_model}. Found {clip_count} clips.")
        logger.info(f"Gemini analysis complete with {successful_model or requested_model}. Found {clip_count} clips.")

        # Issue #35: move clip starts/ends to transcript line edges (and, when
        # the transcript has punctuation, the end to the next sentence end)
        # so a clip does not open or close mid-line.
        raw_clips = analysis_data.get('clips', [])
        def _seconds(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        raw_bounds = [(_seconds(c.get('start_time')), _seconds(c.get('end_time'))) for c in raw_clips]
        lines_index = clip_bounds.Lines(enriched_transcript)
        snapped_bounds = clip_bounds.snap_clips(
            raw_bounds, enriched_transcript, start_bound, end_bound, lines=lines_index)
        moved = sum(1 for r, s in zip(raw_bounds, snapped_bounds) if r != s)
        logger.info(f"Clip bounds: {moved}/{len(raw_bounds)} clip(s) moved to line/sentence edges.")
        # Issue #38: 2m/3m clips Gemini made too short are widened to the minimum.
        stretched = clip_lengths.stretch_short_clips(
            snapped_bounds, lines_index, request.duration, start_bound, end_bound)
        widened = sum(1 for a, b in zip(snapped_bounds, stretched) if a != b)
        short = clip_lengths.still_short(stretched, request.duration)
        if widened or short:
            logger.info(f"Clip length: {widened} clip(s) widened toward the {clip_lengths.label(request.duration)} "
                        f"minimum; {short} still under it (no room next to other clips).")
        snapped_bounds = stretched
        # Issue #34: the length limit runs after snapping, which can lengthen a clip.
        capped_bounds = [(s, clip_lengths.cap_length(s, e, lines_index, end_bound)) for s, e in snapped_bounds]
        cut = sum(1 for a, b in zip(snapped_bounds, capped_bounds) if a != b)
        if cut:
            logger.info(f"Clip length: {cut} clip(s) cut back to {clip_lengths.MAX_CLIP_SECONDS:.0f}s.")
        snapped_bounds = capped_bounds

        # Reconstruct clip transcripts from enriched_transcript
        final_clips = []
        for clip_no, raw_clip in enumerate(raw_clips, start=1):
            start, end = snapped_bounds[clip_no - 1]
            hook  = raw_clip.get('hook_time')
            if hook is None or not (start <= hook <= end):
                hook = start
            
            clip_lines = [
                line.get("text", "")
                for line in enriched_transcript
                if max(line.get("start", 0.0), start) < min(line.get("end", 0.0), end)
            ]
            
            # Ensure hashtags are always lowercase
            caption_sug = lowercase_hashtags_in_string(raw_clip.get('caption_suggestion', ''))
            hashtag_sug = lowercase_hashtags_in_string(raw_clip.get('hashtag_suggestion', ''))
            
            if raw_clip.get('is_fallback'):
                # Backup clips made above when Gemini returned none: their
                # titles ("Must Watch Moment #1") stay exactly as before.
                clip_title = raw_clip.get('title', '')
                clip_suggestion = raw_clip.get('title_suggestion', '')
                titles = []
            else:
                # Issue #31: every title Gemini wrote is checked against the
                # rules; rejections are logged and a safe fallback keeps the
                # clip usable.
                titles, _ = title_rules.pick_titles(
                    raw_clip.get('title_options'),
                    legacy_title=raw_clip.get('title', ''),
                    legacy_suggestion=raw_clip.get('title_suggestion', ''),
                    sanitize=lambda t: sanitize_first_person_title(t, channel),
                    label=f"clip {clip_no} ({start:.1f}-{end:.1f}s)",
                )
                clip_title = clip_suggestion = titles[0]

            final_clips.append(ViralClip(
                title=clip_title,
                start_time=start,
                end_time=end,
                hook_time=hook,
                virality_score=raw_clip.get('virality_score', 0),
                key_quotes=raw_clip.get('key_quotes') or [],
                transcript=" ".join(clip_lines),
                title_suggestion=clip_suggestion,
                caption_suggestion=caption_sug,
                hashtag_suggestion=hashtag_sug,
                title_options=titles,
                content_type=str(raw_clip.get('content_type') or ''),
            ))

        response_heatmap = [
            HeatmapPoint(
                start_time=float(pt.get('start_time', 0.0)),
                end_time=float(pt.get('end_time', 0.0)),
                value=float(pt.get('value', 0.0))
            )
            for pt in (heatmap or [])
        ]

        response_transcript = [
            TranscriptLine(
                start=float(line["start"]),
                end=float(line["end"]),
                text=line["text"],
                engagement=line.get("engagement")
            )
            for line in enriched_transcript
        ]

        # Ensure hashtags are lowercase in the overall summary
        clean_summary = lowercase_hashtags_in_string(analysis_data.get("summary", ""))

        final_result = AnalyzeResponse(
            video_id=video_id,
            title=title,
            channel=channel,
            duration=duration,
            heatmap=response_heatmap,
            summary=clean_summary,
            clips=final_clips,
            transcript=response_transcript,
            model=successful_model or requested_model
        )

        yield _sse({"done": True, "result": final_result.model_dump()})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection":    "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ----------------------------------------------------------------
# Batch Auto-Clipper & Video Studio Endpoints
# ----------------------------------------------------------------

class RenderSettingsModel(BaseModel):
    aspect_ratio: str = "9:16"
    background_style: str = "black"
    enable_face_tracking: bool = True
    streamer_preset: str = "none"
    title_text: Optional[str] = None
    title_prefix: Optional[str] = ""
    title_suffix: Optional[str] = ""
    file_name_prefix: Optional[str] = ""
    file_name_suffix: Optional[str] = ""
    title_position: str = "auto"
    title_duration: Optional[str] = "entire"
    subtitles_enabled: Optional[bool] = True
    caption_style: str = "viral_pop"
    caption_font: str = "Outfit"
    font_size: str = "medium"
    title_font_size: Optional[str] = "medium"
    text_case: str = "uppercase"
    title_y_percent: Optional[float] = 14.0
    subtitle_y_percent: Optional[float] = 18.0
    subtitle_position_mode: Optional[str] = "bottom"
    subtitle_center_y_percent: Optional[float] = 50.0
    # Background Music
    bgm_enabled: Optional[bool] = False
    bgm_file_path: Optional[str] = None
    bgm_volume: Optional[float] = 25.0
    bgm_start_offset: Optional[float] = 0.0
    # Hook SFX
    hook_sfx_enabled: Optional[bool] = False
    hook_sfx_file_path: Optional[str] = None
    hook_sfx_volume: Optional[float] = 100.0
    # Raw Audio / Voice Boost
    original_audio_volume: Optional[float] = 100.0
    # Watermark
    watermark_enabled: Optional[bool] = False
    watermark_type: Optional[str] = "image"
    watermark_file_path: Optional[str] = None
    watermark_text: Optional[str] = None
    watermark_size: Optional[float] = 20.0
    watermark_opacity: Optional[float] = 80.0
    watermark_x: Optional[float] = 90.0
    watermark_y: Optional[float] = 8.0
    hardware_accel: Optional[str] = "auto"


class RenderBatchRequest(BaseModel):
    video_url: str
    video_id: str
    clips: List[Dict[str, Any]]
    settings: RenderSettingsModel
    transcript: Optional[List[Dict[str, Any]]] = None


RENDER_BATCHES: Dict[str, Dict[str, Any]] = {}


async def process_batch_rendering(batch_id: str, request: RenderBatchRequest):
    batch = RENDER_BATCHES.get(batch_id)
    if not batch:
        return

    clips = request.clips
    settings = request.settings

    # Normalize video URL for history or direct URL
    target_url = (request.video_url or "").strip()
    if not target_url.startswith("http"):
        target_url = f"https://www.youtube.com/watch?v={request.video_id or target_url}"

    for idx, clip in enumerate(clips):
        clip_status = batch["clips"][idx]
        clip_status["status"] = "downloading"
        clip_status["progress_percent"] = 15

        try:
            # 1. Download
            start_t = float(clip.get("start_time", 0.0))
            end_t = float(clip.get("end_time", start_t + 30.0))
            seg_filename = f"{batch_id}_clip_{idx}_raw.mp4"

            # Retries and method changes show on screen while downloading (#10).
            def download_status(event, clip_status=clip_status):
                clip_status["download_note"] = event

            raw_path = await asyncio.to_thread(
                download_clip_segment,
                target_url,
                start_t,
                end_t,
                seg_filename,
                download_status,
            )
            clip_status.pop("download_note", None)

            # 2. Transcribe & Generate Subtitles / Title (.ass)
            clip_status["status"] = "transcribing"
            clip_status["progress_percent"] = 40

            display_title = None
            base_title = (
                clip.get("custom_title")
                or clip.get("title_suggestion")
                or clip.get("title")
                or f"Clip {idx+1}"
            ).strip()

            if settings.title_position != "none":
                pfx = settings.title_prefix or ""
                sfx = settings.title_suffix or ""
                if pfx or sfx:
                    display_title = f"{pfx}{base_title}{sfx}".strip()
                elif len(clips) == 1 and settings.title_text and settings.title_text.strip() and not (clip.get("custom_title") or clip.get("title_suggestion")):
                    display_title = settings.title_text.strip()
                else:
                    display_title = base_title

            # Ensure clip status reflects this clip's unique title and base_title
            clip_status["title"] = display_title or base_title
            clip_status["base_title"] = base_title

            ass_path = None
            title_overlay_path = None
            skip_ass_title = False
            duration_sec = max(1.0, end_t - start_t)

            # Check if title has emoji -> render transparent color emoji PNG overlay
            if display_title and settings.title_position != "none" and has_emoji(display_title):
                title_png_filename = f"{batch_id}_clip_{idx}_title.png"
                title_png_path = str(TEMP_DIR / title_png_filename)
                try:
                    rendered_overlay = await asyncio.to_thread(
                        render_title_overlay_png,
                        title_text=display_title,
                        output_png_path=title_png_path,
                        font_name=settings.caption_font or "Montserrat",
                        target_aspect_ratio=settings.aspect_ratio or "9:16",
                        font_size_preset=settings.font_size or "medium",
                        text_case=settings.text_case or "uppercase",
                        title_position=settings.title_position or "auto",
                        title_y_percent=settings.title_y_percent if settings.title_y_percent is not None else 14.0,
                        title_font_size_preset=settings.title_font_size or settings.font_size or "medium"
                    )
                    if rendered_overlay and os.path.exists(rendered_overlay):
                        title_overlay_path = rendered_overlay
                        skip_ass_title = True
                        logger.info(f"Rendered full-color emoji title overlay: {title_overlay_path}")
                except Exception as ex:
                    logger.warning(f"Could not render color emoji title overlay: {ex}")
                    skip_ass_title = False

            if settings.caption_style != "none" or (display_title and settings.title_position != "none" and not skip_ass_title):
                words = []
                if settings.caption_style != "none":
                    words = await asyncio.to_thread(
                        transcribe_clip_words,
                        raw_path,
                        request.transcript,
                        start_t,
                        end_t
                    )
                ass_filename = f"{batch_id}_clip_{idx}.ass"
                ass_path = str(TEMP_DIR / ass_filename)
                await asyncio.to_thread(
                    generate_ass_file,
                    words=words,
                    style_preset=settings.caption_style,
                    font_name=settings.caption_font,
                    output_ass_path=ass_path,
                    target_aspect_ratio=settings.aspect_ratio,
                    font_size_preset=settings.font_size,
                    text_case=settings.text_case,
                    title_text=display_title if not skip_ass_title else None,
                    title_position=settings.title_position,
                    title_duration=settings.title_duration if settings.title_duration else "entire",
                    duration_seconds=duration_sec,
                    title_y_percent=settings.title_y_percent if settings.title_y_percent is not None else 14.0,
                    subtitle_y_percent=settings.subtitle_y_percent if settings.subtitle_y_percent is not None else 18.0,
                    subtitle_position_mode=settings.subtitle_position_mode if settings.subtitle_position_mode else "bottom",
                    subtitle_center_y_percent=settings.subtitle_center_y_percent if settings.subtitle_center_y_percent is not None else 50.0,
                    skip_title=skip_ass_title,
                    title_font_size_preset=settings.title_font_size or settings.font_size or "medium"
                )

            # 3. Render Final Vertical MP4
            clip_status["status"] = "rendering"
            clip_status["progress_percent"] = 70

            out_filename = f"clip_{idx+1}_{batch_id}.mp4"
            out_path = str(EXPORTS_DIR / out_filename)

            await asyncio.to_thread(
                render_clip_to_mp4,
                video_path=raw_path,
                output_mp4_path=out_path,
                aspect_ratio=settings.aspect_ratio,
                background_style=settings.background_style,
                enable_face_tracking=settings.enable_face_tracking,
                streamer_preset=settings.streamer_preset,
                title_text=display_title if not skip_ass_title else None,
                title_position=settings.title_position,
                ass_subtitles_path=ass_path,
                clip_duration=duration_sec,
                title_overlay_path=title_overlay_path,
                title_duration=settings.title_duration if settings.title_duration else "entire",
                watermark_enabled=bool(settings.watermark_enabled),
                watermark_type=settings.watermark_type or "image",
                watermark_image_path=settings.watermark_file_path,
                watermark_text=settings.watermark_text,
                watermark_size=float(settings.watermark_size if settings.watermark_size is not None else 20.0),
                watermark_opacity=float((settings.watermark_opacity if settings.watermark_opacity is not None else 80.0) / 100.0),
                watermark_x_percent=float(settings.watermark_x if settings.watermark_x is not None else 90.0),
                watermark_y_percent=float(settings.watermark_y if settings.watermark_y is not None else 8.0),
                bgm_enabled=bool(settings.bgm_enabled),
                bgm_path=settings.bgm_file_path,
                bgm_volume=float((settings.bgm_volume if settings.bgm_volume is not None else 25.0) / 100.0),
                bgm_start_offset=float(settings.bgm_start_offset or 0.0),
                hook_sfx_enabled=bool(settings.hook_sfx_enabled),
                hook_sfx_path=settings.hook_sfx_file_path,
                hook_sfx_volume=float((settings.hook_sfx_volume if settings.hook_sfx_volume is not None else 100.0) / 100.0),
                original_audio_volume=float((settings.original_audio_volume if settings.original_audio_volume is not None else 100.0) / 100.0),
                hardware_accel=settings.hardware_accel or "auto"
            )

            clip_status["status"] = "completed"
            clip_status["progress_percent"] = 100
            clip_status["download_url"] = f"/api/download-rendered/{out_filename}"
            clip_status["output_path"] = out_path

        except Exception as e:
            logger.error(f"Error rendering clip {idx} in batch {batch_id}: {e}")
            clip_status["status"] = "error"
            clip_status["error_message"] = str(e)
            clip_status["error"] = str(e)
            clip_status.pop("download_note", None)

        batch["current_clip_index"] = idx + 1

    # Generate ZIP bundle for the batch with title-based filenames and duplicate handling
    try:
        completed_clips = [c for c in batch["clips"] if c.get("status") == "completed" and c.get("download_url")]
        if completed_clips:
            zip_filename = f"xoraclips_{batch_id}.zip"
            zip_path = EXPORTS_DIR / zip_filename
            title_counts: Dict[str, int] = {}
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for c in completed_clips:
                    fname = c["download_url"].split("/")[-1]
                    fpath = EXPORTS_DIR / fname
                    if fpath.exists():
                        raw_title = (c.get("base_title") or c.get("title") or "").strip()
                        clean_title = re.sub(r'[\\/*?:"<>|]', "", raw_title) or f"clip_{c.get('clip_index', 1)}"
                        fn_pfx = re.sub(r'[\\/*?:"<>|]', "", settings.file_name_prefix or "")
                        fn_sfx = re.sub(r'[\\/*?:"<>|]', "", settings.file_name_suffix or "")
                        formatted_name = f"{fn_pfx}{clean_title}{fn_sfx}".strip() or clean_title
                        count = title_counts.get(formatted_name, 0)
                        title_counts[formatted_name] = count + 1
                        arc_name = f"{formatted_name}.mp4" if count == 0 else f"{formatted_name} ({count}).mp4"
                        zipf.write(fpath, arcname=arc_name)
            batch["zip_url"] = f"/api/download-batch-zip/{batch_id}"
        else:
            batch["zip_url"] = None
    except Exception as e:
        logger.warning(f"Failed to create batch zip: {e}")

    # Determine overall status and error messaging
    failed_clips = [c for c in batch["clips"] if c.get("status") == "error"]
    completed_clips = [c for c in batch["clips"] if c.get("status") == "completed"]

    if len(failed_clips) == len(batch["clips"]):
        batch["overall_status"] = "error"
        batch["error_message"] = f"All {len(batch['clips'])} clip(s) failed to render. Please review the error details."
    elif len(failed_clips) > 0:
        batch["overall_status"] = "completed"
        batch["warning_message"] = f"{len(failed_clips)} of {len(batch['clips'])} clips encountered errors."
    else:
        batch["overall_status"] = "completed"


class CaptionChunksRequest(BaseModel):
    transcript: List[Dict[str, Any]] = Field(default_factory=list)
    clip_start: float
    clip_end: float
    text_case: str = "uppercase"


@app.post("/api/caption-chunks")
def get_caption_chunks(request: CaptionChunksRequest):
    """
    The caption chunks a clip's export will burn in, for the browser preview.
    Uses the same function as generate_ass_file(), so preview == render.
    Times are relative to clip_start. Empty when the transcript has no words
    in this clip (or there is no transcript): the render then falls back to
    Whisper, which the preview cannot match.
    """
    chunks = caption_chunks_for_clip(
        request.transcript, request.clip_start, request.clip_end, request.text_case
    )
    return {"chunks": chunks, "source": "transcript" if chunks else "none"}


@app.post("/api/render-batch")
async def start_batch_render(request: RenderBatchRequest, background_tasks: BackgroundTasks):
    if not request.clips:
        raise HTTPException(status_code=400, detail="No clips provided for rendering")

    batch_id = f"batch_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    pfx = (request.settings.title_prefix or "") if request.settings else ""
    sfx = (request.settings.title_suffix or "") if request.settings else ""

    clips_status = []
    for idx, c in enumerate(request.clips):
        base_t = (c.get("custom_title") or c.get("title_suggestion") or c.get("title") or f"Clip {idx+1}").strip()
        full_t = f"{pfx}{base_t}{sfx}".strip() if (pfx or sfx) else base_t
        clips_status.append({
            "clip_index": idx,
            "title": full_t,
            "base_title": base_t,
            "status": "pending",
            "progress_percent": 0
        })

    RENDER_BATCHES[batch_id] = {
        "batch_id": batch_id,
        "total_clips": len(request.clips),
        "current_clip_index": 0,
        "overall_status": "running",
        "clips": clips_status,
        "zip_url": None
    }

    background_tasks.add_task(process_batch_rendering, batch_id, request)
    return {"batch_id": batch_id, "total_clips": len(request.clips)}


@app.get("/api/render-progress/{batch_id}")
async def get_render_progress(batch_id: str):
    if batch_id not in RENDER_BATCHES:
        raise HTTPException(status_code=404, detail="Batch not found")

    async def stream():
        while True:
            batch = RENDER_BATCHES.get(batch_id)
            if not batch:
                break
            yield f"data: {json.dumps(batch)}\n\n"
            if batch.get("overall_status") in ["completed", "error"]:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/api/download-batch-zip/{batch_id}")
def download_batch_zip(batch_id: str):
    clean_id = os.path.basename(batch_id)
    safe_name = f"xoraclips_{clean_id}.zip"
    file_path = EXPORTS_DIR / safe_name
    if not file_path.exists():
        # Attempt to package any completed clips for this batch on the fly
        job = RENDER_BATCHES.get(batch_id)
        if job and job.get("clips"):
            try:
                title_counts: Dict[str, int] = {}
                with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for c in job["clips"]:
                        c_out = c.get("output_path")
                        if not c_out and c.get("download_url"):
                            fname = c["download_url"].split("/")[-1]
                            c_out = str(EXPORTS_DIR / fname)
                        if c_out and os.path.exists(c_out):
                            raw_title = (c.get("title") or "").strip()
                            clean_title = re.sub(r'[\\/*?:"<>|]', "", raw_title) or os.path.splitext(os.path.basename(c_out))[0]
                            count = title_counts.get(clean_title, 0)
                            title_counts[clean_title] = count + 1
                            arc_name = f"{clean_title}.mp4" if count == 0 else f"{clean_title} ({count}).mp4"
                            zipf.write(c_out, arcname=arc_name)
            except Exception as e:
                logger.error(f"Error packaging batch zip on the fly: {e}")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Batch zip file not found")
    return FileResponse(file_path, media_type="application/zip", filename=safe_name)


@app.get("/api/hardware-accel")
def get_hardware_acceleration_status():
    """Returns detected GPU/CPU hardware acceleration options and recommendations."""
    support = detect_hardware_support()
    rec = support.get("recommended", "cpu")
    return {
        "status": "success",
        "active_default": ACTIVE_ENCODER_NAME,
        "recommended": rec,
        "support": support,
        "options": [
            {
                "id": "auto",
                "label": "Auto Detect",
                "sub": f"Recommended ({rec.upper()})",
                "available": True,
            },
            {
                "id": "nvenc",
                "label": "NVIDIA NVENC",
                "sub": "GeForce & RTX Hardware Acceleration",
                "available": support.get("nvenc", False),
            },
            {
                "id": "amf",
                "label": "AMD AMF",
                "sub": "Radeon RX & APU Hardware Acceleration",
                "available": support.get("amf", False),
            },
            {
                "id": "qsv",
                "label": "Intel QuickSync",
                "sub": "Intel Arc & UHD Hardware Acceleration",
                "available": support.get("qsv", False),
            },
            {
                "id": "cpu",
                "label": "CPU Software (libx264)",
                "sub": "Multi-threaded CPU (100% Universal)",
                "available": True,
            },
        ],
    }


# ----------------------------------------------------------------
# Temp storage: size and cleanup
# ----------------------------------------------------------------


