"""
Everything that fetches from YouTube or on its behalf: video IDs, proxies,
video metadata and titles, and captions through seven tiers (Supadata,
youtube_transcript_api over proxy and direct, its CLI, yt-dlp), plus manual
subtitle parsing. Moved out of main.py unchanged (#60).
"""
import html
import json
import logging
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional
from urllib.parse import urlsplit

import requests
import yt_dlp
from fastapi import HTTPException
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import JSONFormatter
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig

try:
    from backend import youtube_errors
    from backend.video_engine import COOKIES_PATH, is_video_id
    from backend.youtube_errors import CaptionUnavailable, YouTubeBlocked
except ImportError:
    import youtube_errors
    from video_engine import COOKIES_PATH, is_video_id
    from youtube_errors import CaptionUnavailable, YouTubeBlocked

logger = logging.getLogger("xoraclips")


def parse_time_str(time_str: str) -> float:
    """Parses time string in formats like HH:MM:SS,mmm or MM:SS,mmm or HH:MM:SS or MM:SS to seconds."""
    time_str = time_str.strip().replace(',', '.')
    # Extract millisecond if present
    ms = 0.0
    if '.' in time_str:
        parts = time_str.split('.')
        time_str = parts[0]
        try:
            ms = float('0.' + parts[1])
        except ValueError:
            pass
            
    time_parts = time_str.split(':')
    try:
        if len(time_parts) == 3:
            return int(time_parts[0]) * 3600 + int(time_parts[1]) * 60 + int(time_parts[2]) + ms
        elif len(time_parts) == 2:
            return int(time_parts[0]) * 60 + int(time_parts[1]) + ms
        elif len(time_parts) == 1:
            return float(time_parts[0]) + ms
    except ValueError:
        return 0.0


def parse_manual_subtitles(content: str, default_duration: float = 0.0) -> List[dict]:
    # Normalize line endings
    content = content.replace('\r\n', '\n').strip()
    
    # 1. Try standard SRT parsing first
    # SRT block regex: index (optional), time range, text
    # e.g.,
    # 1
    # 00:00:01,000 --> 00:00:04,500
    # Hello
    srt_regex = r'(?:\d+\n)?(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\n(.*?)(?=\n\n|\n\d+\n|\Z)'
    srt_matches = re.findall(srt_regex, content, re.DOTALL)
    
    if srt_matches:
        results = []
        for start_str, end_str, text in srt_matches:
            start = parse_time_str(start_str)
            end = parse_time_str(end_str)
            cleaned_text = text.replace('\n', ' ').strip()
            results.append({
                "text": cleaned_text,
                "start": start,
                "duration": max(0.1, end - start)
            })
        if results:
            return results

    # 2. Try parsing line-by-line for timestamped lines
    # Patterns:
    # [00:12] Hello or 00:12 Hello
    # [01:02:15] Hello or 01:02:15 Hello
    # [00:12 - 00:15] Hello or 00:12 - 00:15 Hello
    # Let's match timestamp patterns at the start of the line or enclosed in brackets/parens
    line_time_range_regex = r'^[\[\(]?(\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?)\s*(?:-|-->|\s)\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?)[\]\)]?\s*(.*)'
    line_single_time_regex = r'^[\[\(]?(\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?)[\]\)]?\s*(.*)'
    
    lines = content.split('\n')
    results = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Match range first (e.g. 00:12 - 00:15 Text)
        m_range = re.match(line_time_range_regex, line)
        if m_range:
            start_str, end_str, text = m_range.groups()
            start = parse_time_str(start_str)
            end = parse_time_str(end_str)
            results.append({
                "text": text.strip(),
                "start": start,
                "duration": max(0.1, end - start)
            })
            continue
            
        # Match single timestamp (e.g. 00:12 Text)
        m_single = re.match(line_single_time_regex, line)
        if m_single:
            start_str, text = m_single.groups()
            start = parse_time_str(start_str)
            results.append({
                "text": text.strip(),
                "start": start,
                "duration": -1.0  # Will fill in later
            })
            continue

    if results:
        # Resolve duration for single timestamps
        # Set duration to the difference between next start and current start, or a default 3.0s
        for i in range(len(results)):
            if results[i]["duration"] == -1.0:
                if i < len(results) - 1:
                    next_start = results[i+1]["start"]
                    diff = next_start - results[i]["start"]
                    results[i]["duration"] = max(0.5, diff)
                else:
                    results[i]["duration"] = 3.0  # default for the last line
        return results

    # 3. Fallback: split text into paragraphs or sentences and distribute evenly across video duration
    duration_to_use = default_duration if default_duration > 0 else 60.0
    # Clean multiple newlines and split by sentences
    sentences = re.split(r'(?<=[.!?])\s+|\n+', content)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if sentences:
        num_sentences = len(sentences)
        sec_per_sentence = duration_to_use / num_sentences
        results = []
        for i, text in enumerate(sentences):
            start = i * sec_per_sentence
            results.append({
                "text": text,
                "start": round(start, 2),
                "duration": round(sec_per_sentence, 2)
            })
        return results
        
    return []


def extract_video_id(url: str) -> Optional[str]:
    """Extracts the 11-character YouTube video ID from various URL formats including live streams, shorts, embed, watch?v=, youtu.be, etc."""
    if not url:
        return None
    trimmed = url.strip()
    # Direct 11-char ID
    if is_video_id(trimmed):
        return trimmed

    patterns = [
        # Standard query parameter: ?v=VIDEO_ID or &v=VIDEO_ID
        r"(?:[?&]v=)([a-zA-Z0-9_-]{11})",
        # Path-based formats: /live/VIDEO_ID, /shorts/VIDEO_ID, /embed/VIDEO_ID, /v/VIDEO_ID, youtu.be/VIDEO_ID
        r"(?:youtu\.be\/|(?:www\.|m\.)?youtube(?:-nocookie)?\.com\/(?:embed|v|shorts|live)\/)([a-zA-Z0-9_-]{11})",
        # General fallback matching any path or query prefix
        r"(?:v=|\/v\/|embed\/|shorts\/|live\/|youtu\.be\/|\/embed\/|\/watch\?v=|\/watch\?.+&v=)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, trimmed)
        if match:
            return match.group(1)

    return None


class TimeoutSession(requests.Session):
    """requests.Session that enforces a default timeout to avoid hanging indefinitely on slow proxies."""
    def __init__(self, timeout: float = 12.0):
        super().__init__()
        self._default_timeout = timeout

    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", self._default_timeout)
        return super().request(*args, **kwargs)


def get_proxy_url() -> Optional[str]:
    """Retrieves proxy URL from environment variables or synthesizes from Webshare credentials."""
    proxy = (
        os.environ.get("PROXY_URL")
        or os.environ.get("WEBSHARE_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("ALL_PROXY")
        or ""
    ).strip()
    if proxy:
        return proxy

    # Synthesize URL from explicit Webshare credentials if provided
    ws_user = os.environ.get("WEBSHARE_USERNAME", "").strip()
    ws_pass = os.environ.get("WEBSHARE_PASSWORD", "").strip()
    if ws_user and ws_pass:
        ws_locations_raw = os.environ.get("WEBSHARE_LOCATIONS", "").strip()
        loc_suffix = "".join(f"-{loc.strip().upper()}" for loc in ws_locations_raw.split(",") if loc.strip())
        user_clean = ws_user[:-7] if ws_user.endswith("-rotate") else ws_user
        return f"http://{user_clean}{loc_suffix}-rotate:{ws_pass}@p.webshare.io:80"

    return None


def get_youtube_transcript_proxy_config(custom_proxy: Optional[str] = None):
    """
    Constructs a ProxyConfig (WebshareProxyConfig or GenericProxyConfig)
    for YouTubeTranscriptApi per official recommendations:
    https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans-requestblocked-or-ipblocked-exception
    """
    ws_locations_raw = os.environ.get("WEBSHARE_LOCATIONS", "").strip()
    ws_locations = [loc.strip() for loc in ws_locations_raw.split(",") if loc.strip()] if ws_locations_raw else None
    try:
        ws_retries = int(os.environ.get("WEBSHARE_RETRIES", "5"))
    except ValueError:
        ws_retries = 5

    # 1. Explicit Webshare credentials from environment
    ws_user = os.environ.get("WEBSHARE_USERNAME", "").strip()
    ws_pass = os.environ.get("WEBSHARE_PASSWORD", "").strip()
    if not custom_proxy and ws_user and ws_pass:
        return WebshareProxyConfig(
            proxy_username=ws_user,
            proxy_password=ws_pass,
            filter_ip_locations=ws_locations,
            retries_when_blocked=ws_retries
        )

    # 2. Check full proxy URL (custom_proxy or from get_proxy_url())
    proxy_url = (custom_proxy or get_proxy_url() or "").strip()
    if not proxy_url:
        return None

    # Check if this proxy URL points to Webshare
    if "webshare.io" in proxy_url.lower():
        try:
            parsed = urlsplit(proxy_url)
            if parsed.username and parsed.password:
                domain = parsed.hostname or "p.webshare.io"
                port = parsed.port or 80
                return WebshareProxyConfig(
                    proxy_username=parsed.username,
                    proxy_password=parsed.password,
                    domain_name=domain,
                    proxy_port=port,
                    filter_ip_locations=ws_locations,
                    retries_when_blocked=ws_retries
                )
        except Exception as e:
            logger.warning(f"Failed parsing Webshare URL for WebshareProxyConfig: {e}")

    # 3. GenericProxyConfig fallback for non-Webshare proxies
    try:
        return GenericProxyConfig(http_url=proxy_url, https_url=proxy_url)
    except Exception as e:
        logger.warning(f"Failed creating GenericProxyConfig: {e}")
        return None


# ── Shared Cookie Jar & HTTP Session Factory ──────────────────────────────────
# Per https://github.com/jdepoix/youtube-transcript-api#overwriting-request-defaults
# Caching cookies across requests (consent screens, visitor tokens) and setting
# realistic browser headers minimizes automated bot blocks on YouTube.
_shared_cookie_jar = requests.cookies.RequestsCookieJar()


def create_http_client(timeout: float = 15.0) -> TimeoutSession:
    """Creates a requests.Session pre-configured with realistic browser headers,
    shared YouTube cookies (consent/tokens), and optional CA bundle per documentation:
    https://github.com/jdepoix/youtube-transcript-api#overwriting-request-defaults
    """
    session = TimeoutSession(timeout=timeout)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1"
    })
    # Inherit verified session cookies across requests
    session.cookies.update(_shared_cookie_jar)

    # SSL verification certificate override if defined
    ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if ca_bundle and os.path.exists(ca_bundle):
        session.verify = ca_bundle

    return session


def normalize_transcript(fetched_data) -> List[dict]:
    """Normalizes FetchedTranscript objects (using JSONFormatter or to_raw_data()),
    raw JSON strings, or dict lists into standard timestamped segment dictionaries.
    Per https://github.com/jdepoix/youtube-transcript-api#using-formatters
    """
    if not fetched_data:
        return []

    items = []
    if hasattr(fetched_data, "snippets") or hasattr(fetched_data, "to_raw_data"):
        try:
            formatter = JSONFormatter()
            json_str = formatter.format_transcript(fetched_data)
            items = json.loads(json_str)
        except Exception:
            items = fetched_data.to_raw_data() if hasattr(fetched_data, "to_raw_data") else list(fetched_data)
    elif isinstance(fetched_data, str):
        try:
            parsed = json.loads(fetched_data)
            items = parsed[0] if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], list) else parsed
        except Exception:
            return []
    elif isinstance(fetched_data, list):
        items = fetched_data
    else:
        try:
            items = list(fetched_data)
        except Exception:
            return []

    results = []
    for item in items:
        if isinstance(item, dict):
            text = html.unescape(str(item.get("text", ""))).strip()
            start = float(item.get("start", 0.0))
            dur = float(item.get("duration", 0.0))
        else:
            text = html.unescape(getattr(item, "text", "")).strip()
            start = float(getattr(item, "start", 0.0))
            dur = float(getattr(item, "duration", 0.0))

        if text:
            results.append({
                "text": text,
                "start": round(start, 2),
                "duration": max(0.1, round(dur, 2))
            })

    return results


def fetch_transcript_cli(
    video_id: str,
    priority_langs: List[str],
    proxy_url: Optional[str] = None,
    custom_proxy: Optional[str] = None,
    timeout: int = 20
) -> List[dict]:
    """Attempts subtitle extraction using youtube_transcript_api CLI subprocess.
    Provides an isolated process environment with independent network & proxy stack.
    Handles hyphenated video IDs (e.g. \"\\-abc\") per documentation:
    https://github.com/jdepoix/youtube-transcript-api#cli
    """
    escaped_id = f"\\{video_id}" if video_id.startswith("-") else video_id
    cmd = [sys.executable, "-m", "youtube_transcript_api", escaped_id, "--format", "json"]

    if priority_langs:
        cmd.extend(["--languages"] + priority_langs)

    ws_user = os.environ.get("WEBSHARE_USERNAME", "").strip()
    ws_pass = os.environ.get("WEBSHARE_PASSWORD", "").strip()
    effective_proxy = custom_proxy or proxy_url or get_proxy_url()

    if ws_user and ws_pass and not custom_proxy:
        cmd.extend(["--webshare-proxy-username", ws_user, "--webshare-proxy-password", ws_pass])
    elif effective_proxy:
        cmd.extend(["--http-proxy", effective_proxy, "--https-proxy", effective_proxy])

    logger.info(f"Executing CLI transcript extraction for {video_id}...")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        raw = None
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                raw = json.loads(proc.stdout)
            except ValueError:
                pass  # The CLI prints its errors to stdout with exit code 0 (issue #9).
        if raw is not None:
            items = raw[0] if isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], list) else raw
            result = normalize_transcript(items)
            if result:
                logger.info(f"Transcript fetched via CLI fallback: {len(result)} lines")
                return result
        elif youtube_errors.is_blocked_text(output):
            raise YouTubeBlocked(f"CLI: {_first_line(output)}")
        raise Exception(f"CLI returned {proc.returncode}: {_first_line(output) or 'no output'}")
    except Exception as e:
        logger.warning(f"CLI transcript extraction failed: {e}")
        raise


def _first_line(text: str) -> str:
    """The first non-empty line, for logs (CLI output starts with a blank line)."""
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "")


def get_youtube_oembed_title(video_id_or_url: str) -> Optional[str]:
    """Fetches video title directly from YouTube's public oEmbed API.
    Fast (<300ms), requires no authentication or cookies, and works reliably when yt-dlp is blocked."""
    video_id = extract_video_id(video_id_or_url) if ("youtube" in video_id_or_url or "youtu.be" in video_id_or_url or "/" in video_id_or_url) else video_id_or_url
    if not video_id:
        return None
    
    # 1. Try direct HTTP GET to oEmbed endpoint
    try:
        resp = requests.get(
            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json",
            timeout=5
        )
        if resp.status_code == 200:
            title = resp.json().get("title")
            if title and title.strip():
                return title.strip()
    except Exception as e:
        logger.warning(f"Direct oEmbed title fetch failed for {video_id}: {e}")

    # 2. Try via proxy if configured
    proxy = get_proxy_url()
    if proxy:
        try:
            resp = requests.get(
                f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json",
                proxies={"http": proxy, "https": proxy},
                timeout=5
            )
            if resp.status_code == 200:
                title = resp.json().get("title")
                if title and title.strip():
                    return title.strip()
        except Exception as e:
            logger.warning(f"Proxy oEmbed title fetch failed for {video_id}: {e}")

    # 3. Direct HTML title scraping fallback
    try:
        resp = requests.get(f"https://www.youtube.com/watch?v={video_id}", timeout=5)
        if resp.status_code == 200:
            m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', resp.text)
            if m and m.group(1).strip():
                return m.group(1).strip()
            m2 = re.search(r'<title>(.*?)(?:\s*-\s*YouTube)?</title>', resp.text)
            if m2 and m2.group(1).strip():
                return m2.group(1).strip()
    except Exception:
        pass

    return None


def fetch_video_metadata(url: str, custom_proxy: Optional[str] = None):
    """Fetches video title, duration, and viewer retention heatmap using yt-dlp with oEmbed title fallback."""
    is_vercel = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
    proxy = custom_proxy or get_proxy_url()
    video_id = extract_video_id(url)
    target_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else url
    
    attempts = [proxy, None] if (is_vercel and proxy) else [None, proxy] if proxy else [None]
    
    for attempt_proxy in attempts:
        ydl_opts = {
            'skip_download': True,
            'youtube_include_dash_manifest': False,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'proxy': attempt_proxy,
            'socket_timeout': 10
        }
        if COOKIES_PATH.exists() and COOKIES_PATH.stat().st_size > 0:
            ydl_opts['cookiefile'] = str(COOKIES_PATH)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=False)
                if not info:
                    raise Exception("yt-dlp returned empty info dict")
                title = info.get('title')
                if not title or title.lower() == 'unknown youtube video':
                    if video_id:
                        title = get_youtube_oembed_title(video_id) or title
                return {
                    "title": title or 'Unknown YouTube Video',
                    "channel": info.get('channel') or info.get('uploader') or info.get('creator') or '',
                    "duration": float(info.get('duration') or 0.0),
                    "heatmap": info.get('heatmap') or [],
                    "is_live": bool(info.get('is_live') or False),
                    "live_status": info.get('live_status') or 'not_live'
                }
        except Exception as e:
            logger.warning(f"yt-dlp metadata extraction failed (proxy={'yes' if attempt_proxy else 'no'}): {e}")
            if not attempt_proxy and youtube_errors.is_blocked_exception(e):
                youtube_errors.block_memory.remember()  # issue #9

    # Fallback: parse video ID and retrieve title from oEmbed API directly
    if video_id:
        fallback_title = get_youtube_oembed_title(video_id) or f"YouTube Video ({video_id})"
        return {
            "title": fallback_title,
            "channel": "",
            "duration": 0.0,
            "heatmap": [],
            "is_live": False,
            "live_status": "not_live"
        }
    raise HTTPException(status_code=400, detail="Failed to retrieve YouTube video details from URL.")


_supadata_key_index = 0


def get_supadata_keys() -> List[str]:
    """Retrieves list of Supadata API keys from environment variables."""
    raw = os.environ.get("SUPADATA_API_KEYS") or os.environ.get("SUPADATA_API_KEY") or ""
    keys = re.findall(r'sd_[a-zA-Z0-9]+', raw)
    if not keys:
        keys = [k.strip('\"\' ') for k in re.split(r'[,\s\n]+', raw) if k.strip('\"\' ')]
    return keys


def fetch_transcript_supadata(video_id: str, error_collector: Optional[List[str]] = None) -> List[dict]:
    """Fetches transcript from Supadata API, rotating through available keys if rate limits/quotas occur."""
    global _supadata_key_index
    keys = get_supadata_keys()
    if not keys:
        if error_collector is not None:
            error_collector.append("Supadata API: No keys configured (SUPADATA_API_KEYS is empty in .env)")
        return []

    start_idx = _supadata_key_index % len(keys)
    rotated_keys = keys[start_idx:] + keys[:start_idx]
    _supadata_key_index = (_supadata_key_index + 1) % len(keys)

    quota_exhausted_count = 0
    not_found = False
    last_error = ""

    for key in rotated_keys:
        masked_key = f"{key[:7]}...{key[-4:]}" if len(key) >= 11 else "***"
        try:
            logger.info(f"Attempting Supadata transcript fetch with key {masked_key}")
            response = requests.get(
                "https://api.supadata.ai/v1/youtube/transcript",
                headers={"x-api-key": key},
                params={"videoId": video_id},
                timeout=12
            )
            if response.status_code == 200:
                data = response.json()
                content = data.get("content") or []
                if content:
                    result = []
                    for seg in content:
                        text = seg.get("text", "").strip()
                        if text:
                            start = float(seg.get("offset", 0)) / 1000.0
                            dur = float(seg.get("duration", 0)) / 1000.0
                            result.append({"text": text, "start": start, "duration": dur})
                    if result:
                        logger.info(f"Successfully retrieved {len(result)} transcript lines via Supadata ({masked_key})")
                        global _supadata_usage_cache
                        _supadata_usage_cache["timestamp"] = 0
                        return result
            elif response.status_code in (429, 402):
                quota_exhausted_count += 1
                logger.warning(f"Supadata key {masked_key} returned status {response.status_code} (quota/limit). Rotating to next key...")
                continue
            elif response.status_code == 404:
                not_found = True
                last_error = "HTTP 404 (No subtitles found for this video on YouTube)"
                logger.warning(f"Supadata key {masked_key} returned status 404: No subtitles found")
                break
            else:
                last_error = f"HTTP {response.status_code}: {response.text[:100]}"
                logger.warning(f"Supadata key {masked_key} returned status {response.status_code}: {response.text[:100]}")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Supadata request with key {masked_key} failed: {e}")
            continue

    if error_collector is not None:
        if quota_exhausted_count == len(keys):
            error_collector.append(f"Supadata API: All {len(keys)} configured API keys exhausted (HTTP 429/402 Monthly Quota Exceeded)")
        elif not_found:
            error_collector.append(f"Supadata API: {last_error}")
        elif last_error:
            error_collector.append(f"Supadata API: Requests failed across all keys ({last_error})")
        else:
            error_collector.append("Supadata API: Transcript content was empty")

    return []


_supadata_usage_cache = {
    "data": None,
    "timestamp": 0
}


_CACHE_TTL_SECONDS = 30


def check_single_supadata_key(key: str, index: int) -> dict:
    masked = f"{key[:7]}...{key[-4:]}" if len(key) >= 11 else "***"
    try:
        resp = requests.get(
            "https://api.supadata.ai/v1/me",
            headers={"x-api-key": key},
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            max_credits = int(data.get("maxCredits", 100))
            used_credits = int(data.get("usedCredits", 0))
            remaining = max(0, max_credits - used_credits)
            status = "exhausted" if remaining == 0 else "active"
            return {
                "index": index,
                "masked_key": masked,
                "status": status,
                "max_credits": max_credits,
                "used_credits": used_credits,
                "remaining_credits": remaining,
                "plan": data.get("plan", "Free (100/mo)")
            }
        elif resp.status_code in (429, 402):
            return {
                "index": index,
                "masked_key": masked,
                "status": "exhausted",
                "max_credits": 100,
                "used_credits": 100,
                "remaining_credits": 0,
                "plan": "Limit Exceeded"
            }
        else:
            return {
                "index": index,
                "masked_key": masked,
                "status": "error",
                "max_credits": 100,
                "used_credits": 0,
                "remaining_credits": 100,
                "plan": f"HTTP {resp.status_code}"
            }
    except Exception as e:
        logger.warning(f"Error checking Supadata key {masked}: {e}")
        return {
            "index": index,
            "masked_key": masked,
            "status": "error",
            "max_credits": 100,
            "used_credits": 0,
            "remaining_credits": 100,
            "plan": "Timeout/Error"
        }


def get_supadata_usage_data(force: bool = False) -> dict:
    """Aggregates quota metrics across all configured Supadata API keys in parallel with 30s cache."""
    global _supadata_usage_cache
    now = time.time()
    if not force and _supadata_usage_cache["data"] and (now - _supadata_usage_cache["timestamp"] < _CACHE_TTL_SECONDS):
        cached_res = dict(_supadata_usage_cache["data"])
        cached_res["cached"] = True
        return cached_res

    keys = get_supadata_keys()
    if not keys:
        empty_res = {
            "total_keys": 0,
            "total_limit": 0,
            "total_used": 0,
            "total_remaining": 0,
            "usage_percent": 0.0,
            "active_keys": 0,
            "exhausted_keys": 0,
            "keys_detail": [],
            "cached": False,
            "timestamp": now
        }
        _supadata_usage_cache = {"data": empty_res, "timestamp": now}
        return empty_res

    with ThreadPoolExecutor(max_workers=min(len(keys), 12)) as executor:
        futures = [executor.submit(check_single_supadata_key, k, i + 1) for i, k in enumerate(keys)]
        details = [f.result() for f in futures]

    total_limit = sum(k["max_credits"] for k in details)
    total_used = sum(k["used_credits"] for k in details)
    total_remaining = sum(k["remaining_credits"] for k in details)
    active_count = sum(1 for k in details if k["remaining_credits"] > 0)
    exhausted_count = sum(1 for k in details if k["remaining_credits"] == 0 and k["status"] != "error")
    usage_percent = round((total_used / total_limit * 100.0), 1) if total_limit > 0 else 0.0

    res = {
        "total_keys": len(keys),
        "total_limit": total_limit,
        "total_used": total_used,
        "total_remaining": total_remaining,
        "usage_percent": usage_percent,
        "active_keys": active_count,
        "exhausted_keys": exhausted_count,
        "keys_detail": details,
        "cached": False,
        "timestamp": now
    }
    _supadata_usage_cache = {"data": res, "timestamp": now}
    return res


def fetch_transcript_ytdlp(video_id: str, proxy: Optional[str] = None) -> List[dict]:
    """Attempts to extract captions using yt-dlp's player response directly (free, no quota used).
    Can be run direct (proxy=None) or routed through a proxy."""
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'proxy': proxy,
        'socket_timeout': 10
    }
    if COOKIES_PATH.exists() and COOKIES_PATH.stat().st_size > 0:
        ydl_opts['cookiefile'] = str(COOKIES_PATH)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except Exception as e:
        if youtube_errors.is_blocked_exception(e):
            raise YouTubeBlocked(f"yt-dlp: {_first_line(str(e))}")
        logger.warning(f"yt-dlp subtitle extraction failed (proxy={'yes' if proxy else 'no'}): {e}")
        return []
    if not info:
        return []

    candidates = ytdlp_caption_candidates(info.get('subtitles') or {}, info.get('automatic_captions') or {})
    proxies_dict = {'http': proxy, 'https': proxy} if proxy else None
    attempts = [proxies_dict, None] if proxy else [None]
    for lang, is_auto, url in candidates:
        for p in attempts:
            try:
                r = requests.get(url, proxies=p, timeout=8)
            except Exception as e:
                logger.warning(f"yt-dlp caption request failed (lang={lang}): {e}")
                continue
            content_type = r.headers.get('content-type', '')
            body = r.text if 'html' in content_type.lower() else ''
            if youtube_errors.is_blocked_response(r.status_code, content_type, body):
                raise YouTubeBlocked(f"yt-dlp caption {lang}: HTTP {r.status_code}")
            if r.status_code != 200:
                logger.warning(f"yt-dlp caption {lang} answered HTTP {r.status_code}")
                continue
            try:
                events = r.json().get('events', [])
            except ValueError:
                logger.warning(f"yt-dlp caption {lang} was not JSON")
                continue
            result = []
            for ev in events:
                segs = ev.get('segs', [])
                text = ''.join(s.get('utf8', '') for s in segs).strip()
                if text:
                    start = ev.get('tStartMs', 0) / 1000.0
                    dur = ev.get('dDurationMs', 0) / 1000.0
                    result.append({'text': text, 'start': start, 'duration': dur})
            if result:
                logger.info(f"Transcript fetched via yt-dlp (lang={lang}, auto={is_auto}, proxy={'yes' if p else 'no'})")
                return result
    return []


YTDLP_MAX_CAPTION_REQUESTS = 3


def ytdlp_caption_candidates(subtitles: dict, auto_captions: dict, limit: int = YTDLP_MAX_CAPTION_REQUESTS) -> List[tuple]:
    """
    At most `limit` caption tracks to download, as (lang, is_auto, json3 url).
    Order: human-made id, en, then one human-made track in any other language;
    then auto-captions in the video's own language (`*-orig`), id, en. Not
    every translated language (a video can list 159),
    because each one is a request and requests prolong a block (issue #9).
    """
    def base(lang: str) -> str:
        return lang.split('-')[0].lower()

    def json3(formats) -> Optional[str]:
        return next((f.get('url') for f in (formats or []) if f.get('ext') == 'json3' and f.get('url')), None)

    wanted = []
    for target in ('id', 'en'):
        wanted += [(lang, False) for lang in subtitles if base(lang) == target]
    wanted += [(lang, False) for lang in subtitles if base(lang) not in ('id', 'en', 'live_chat')][:1]
    wanted += [(lang, True) for lang in auto_captions if lang.endswith('-orig')][:1]
    for target in ('id', 'en'):
        wanted += [(lang, True) for lang in auto_captions if lang == target]

    picked, seen_urls = [], set()
    for lang, is_auto in wanted:
        url = json3((auto_captions if is_auto else subtitles).get(lang))
        if url and url not in seen_urls:
            seen_urls.add(url)
            picked.append((lang, is_auto, url))
        if len(picked) >= limit:
            break
    return picked


def fetch_transcript(
    video_id: str,
    custom_proxy: Optional[str] = None,
    on_progress: Optional[Callable[[str, str, int], None]] = None
) -> List[dict]:
    """
    Fetches captions through the tiers below. Raises CaptionUnavailable with a
    short code when there are none; the per-tier details go to the log.

    The first sign that YouTube is refusing us stops every remaining tier and
    is remembered for a while (youtube_errors.block_memory), because each
    further request makes the block last longer (issue #9).
    """
    attempt_history: List[str] = []
    try:
        return _fetch_transcript_tiers(video_id, custom_proxy, on_progress, attempt_history)
    except YouTubeBlocked as blocked:
        if blocked.retry_after:
            logger.info(f"YouTube block remembered: not contacting YouTube for another {blocked.retry_after}s")
            raise
        attempt_history.append(f"BLOCKED -> {blocked.detail}")
        # A proxy the user sent with this request says nothing about the
        # server's own address: stop this analysis, but do not lock everyone out.
        if not custom_proxy:
            blocked.retry_after = youtube_errors.block_memory.remember()
        logger.warning(
            f"YouTube is refusing caption requests for {video_id}. Stopped the remaining tiers"
            + (f"; staying away for {blocked.retry_after}s." if blocked.retry_after else " (user proxy: not remembered).")
            + "\n  " + "\n  ".join(attempt_history)
        )
        raise


def _stop_if_remembered() -> None:
    """Raises YouTubeBlocked while a block is remembered, before any YouTube request."""
    remaining = youtube_errors.block_memory.remaining()
    if remaining:
        raise YouTubeBlocked("remembered block", retry_after=remaining)


def _stop_if_blocked(error: BaseException, tier: str) -> None:
    """Re-raises a block as YouTubeBlocked so no further tier runs; ignores other errors."""
    if isinstance(error, YouTubeBlocked):
        raise error
    if youtube_errors.is_blocked_exception(error):
        raise YouTubeBlocked(f"{tier}: {type(error).__name__} ({_first_line(str(error))[:150]})") from error


def _fetch_transcript_tiers(
    video_id: str,
    custom_proxy: Optional[str],
    on_progress: Optional[Callable[[str, str, int], None]],
    attempt_history: List[str],
) -> List[dict]:
    """Retrieves subtitles using a comprehensive multi-tier fallback pipeline:
      Tier 1: Supadata API (if keys configured) — cloud residential rotation
      Tier 2: YouTubeTranscriptApi Python API (Proxy + Shared Session + Browser Headers + Translation fallback)
      Tier 3: YouTubeTranscriptApi CLI Subprocess (Proxy)
      Tier 4: yt-dlp Native Extraction (Proxy)
      Tier 5: Direct YouTubeTranscriptApi Python API (Direct, Shared Session + Browser Headers)
      Tier 6: Direct YouTubeTranscriptApi CLI Subprocess (Direct)
      Tier 7: Direct yt-dlp Native Extraction (Direct)
    If all tiers fail, raises CaptionUnavailable with full diagnostics for the log.
    """
    def notify(stage: str, detail: str, pct: int):
        if on_progress:
            try:
                on_progress(stage, detail, pct)
            except Exception:
                pass

    priority_langs = ['id', 'en', 'es', 'pt', 'fr', 'de', 'ja', 'ko', 'zh-Hans', 'zh-Hant', 'ar', 'hi', 'ru']
    keys = get_supadata_keys()
    proxy_url = custom_proxy or get_proxy_url()
    proxy_cfg = get_youtube_transcript_proxy_config(custom_proxy)

    # ── Tier 1: Supadata API (if keys configured) ─────────────────────────────
    if keys:
        logger.info(f"[Tier 1] Attempting transcript retrieval via Supadata API ({len(keys)} keys configured)...")
        notify("Tier 1/7: Supadata Cloud API", f"Trying Method 1/7: Supadata Cloud API ({len(keys)} keys rotation)...", 30)
        supadata_data = fetch_transcript_supadata(video_id, error_collector=attempt_history)
        if supadata_data:
            return normalize_transcript(supadata_data)
        logger.info("[Tier 1] Supadata API unsuccessful — proceeding to proxy fallback tiers...")
    else:
        attempt_history.append("Tier 1 (Supadata API): Not configured (no keys in SUPADATA_API_KEYS)")

    # ── Remembered block: YouTube refused us recently, do not knock again ──
    _stop_if_remembered()

    # ── Proxy Tiers (Tier 2 - 4) ──────────────────────────────────────────────
    if proxy_cfg or proxy_url:
        masked_proxy = proxy_url.split('@')[-1] if (proxy_url and '@' in proxy_url) else (proxy_url or "Configured Proxy")
        logger.info(f"[Tier 2-4] Attempting proxy fallback pipeline ({masked_proxy})...")

        # ── Tier 2: YouTubeTranscriptApi Python API with Proxy & Shared Session ───
        notify("Tier 2/7: Proxy Python API", f"Trying Method 2/7: YouTubeTranscriptApi via rotating proxy ({masked_proxy})...", 45)
        try:
            client = create_http_client(timeout=15.0)
            proxy_api = YouTubeTranscriptApi(proxy_config=proxy_cfg, http_client=client)

            # 2a. Direct language match
            try:
                data = proxy_api.fetch(video_id, languages=priority_langs)
                res = normalize_transcript(data)
                if res:
                    _shared_cookie_jar.update(client.cookies)
                    logger.info(f"[Tier 2a] Transcript fetched via proxy Python API direct: {len(res)} lines")
                    return res
            except Exception as direct_err:
                _stop_if_blocked(direct_err, "Tier 2a")
                logger.info(f"[Tier 2a] Proxy direct language fetch missed: {direct_err}")

            # 2b. List all transcripts & try fetching manual, then auto
            try:
                transcripts = list(proxy_api.list(video_id))
                manual = [t for t in transcripts if not getattr(t, 'is_generated', False)]
                generated = [t for t in transcripts if getattr(t, 'is_generated', False)]
                for t in (manual + generated):
                    try:
                        data = t.fetch()
                        res = normalize_transcript(data)
                        if res:
                            _shared_cookie_jar.update(client.cookies)
                            logger.info(f"[Tier 2b] Transcript fetched via proxy Python API list ({t.language}): {len(res)} lines")
                            return res
                    except Exception as track_err:
                        _stop_if_blocked(track_err, "Tier 2b")
                        continue

                # 2c. Translation fallback: translate any translatable track to 'id' or 'en'
                for t in transcripts:
                    if getattr(t, 'is_translatable', False):
                        for target_lang in ['id', 'en']:
                            try:
                                notify("Tier 2/7: Translating Captions", f"Translating available {t.language} track to {target_lang} via proxy...", 52)
                                translated = t.translate(target_lang)
                                data = translated.fetch()
                                res = normalize_transcript(data)
                                if res:
                                    _shared_cookie_jar.update(client.cookies)
                                    logger.info(f"[Tier 2c] Transcript translated via proxy Python API ({t.language} -> {target_lang}): {len(res)} lines")
                                    return res
                            except Exception as tr_err:
                                _stop_if_blocked(tr_err, "Tier 2c")
                                continue

                attempt_history.append(f"Tier 2 (Proxy Python API): No accessible track in {len(transcripts)} tracks")
            except Exception as list_err:
                _stop_if_blocked(list_err, "Tier 2")
                err_type = type(list_err).__name__
                err_msg = str(list_err).strip().split('\n')[0]
                attempt_history.append(f"Tier 2 (Proxy Python API): {err_type} ({err_msg})")
        except Exception as init_err:
            _stop_if_blocked(init_err, "Tier 2")
            attempt_history.append(f"Tier 2 (Proxy Python API setup): {type(init_err).__name__} ({init_err})")

        # ── Tier 3: YouTubeTranscriptApi CLI Subprocess with Proxy ───────────────
        _stop_if_remembered()
        notify("Tier 3/7: Proxy CLI Subprocess", "Trying Method 3/7: Isolated CLI subprocess via proxy...", 60)
        try:
            cli_data = fetch_transcript_cli(
                video_id,
                priority_langs,
                proxy_url=proxy_url,
                custom_proxy=custom_proxy,
                timeout=20
            )
            if cli_data:
                logger.info(f"[Tier 3] Transcript fetched via proxy CLI subprocess: {len(cli_data)} lines")
                return cli_data
        except Exception as cli_err:
            _stop_if_blocked(cli_err, "Tier 3")
            attempt_history.append(f"Tier 3 (Proxy CLI Subprocess): {type(cli_err).__name__} ({str(cli_err)[:150]})")

        # ── Tier 4: yt-dlp Native Extraction with Proxy ──────────────────────────
        _stop_if_remembered()
        notify("Tier 4/7: Proxy yt-dlp Native", "Trying Method 4/7: yt-dlp native caption extraction via proxy...", 70)
        try:
            ytdlp_proxy_data = fetch_transcript_ytdlp(video_id, proxy=proxy_url)
            if ytdlp_proxy_data:
                res = normalize_transcript(ytdlp_proxy_data)
                if res:
                    logger.info(f"[Tier 4] Transcript fetched via proxy yt-dlp: {len(res)} lines")
                    return res
            attempt_history.append("Tier 4 (Proxy yt-dlp): No subtitle streams found or extraction empty")
        except Exception as ytdlp_err:
            _stop_if_blocked(ytdlp_err, "Tier 4")
            attempt_history.append(f"Tier 4 (Proxy yt-dlp): {type(ytdlp_err).__name__} ({str(ytdlp_err)[:150]})")

    else:
        attempt_history.append("Tier 2-4 (Proxy Fallbacks): No proxy configured in .env (WEBSHARE_PROXY, WEBSHARE_USERNAME, or PROXY_URL)")

    # ── Direct Tiers (Tier 5 - 7: Localhost / Residential IP fallback) ─────────
    logger.info("[Tier 5-7] Attempting direct YouTube retrieval (no proxy)...")

    # ── Tier 5: Direct YouTubeTranscriptApi Python API ────────────────────────
    _stop_if_remembered()
    notify("Tier 5/7: Direct YouTube API", "Trying Method 5/7: Direct YouTubeTranscriptApi (localhost / residential)...", 80)
    try:
        direct_client = create_http_client(timeout=10.0)
        direct_api = YouTubeTranscriptApi(http_client=direct_client)

        try:
            data = direct_api.fetch(video_id, languages=priority_langs)
            res = normalize_transcript(data)
            if res:
                _shared_cookie_jar.update(direct_client.cookies)
                logger.info(f"[Tier 5a] Transcript fetched via direct Python API: {len(res)} lines")
                return res
        except Exception as direct_err:
            _stop_if_blocked(direct_err, "Tier 5a")

        try:
            all_transcripts = list(direct_api.list(video_id))
            manual = [t for t in all_transcripts if not getattr(t, 'is_generated', False)]
            generated = [t for t in all_transcripts if getattr(t, 'is_generated', False)]
            for transcript in (manual + generated):
                try:
                    data = transcript.fetch()
                    res = normalize_transcript(data)
                    if res:
                        _shared_cookie_jar.update(direct_client.cookies)
                        logger.info(f"[Tier 5b] Transcript fetched via direct list ({transcript.language}): {len(res)} lines")
                        return res
                except Exception as track_err:
                    _stop_if_blocked(track_err, "Tier 5b")
                    continue

            # Direct translation fallback
            for t in all_transcripts:
                if getattr(t, 'is_translatable', False):
                    for target_lang in ['id', 'en']:
                        try:
                            notify("Tier 5/7: Translating Captions", f"Translating available {t.language} track to {target_lang} directly...", 84)
                            translated = t.translate(target_lang)
                            data = translated.fetch()
                            res = normalize_transcript(data)
                            if res:
                                _shared_cookie_jar.update(direct_client.cookies)
                                logger.info(f"[Tier 5c] Transcript translated via direct list ({t.language} -> {target_lang}): {len(res)} lines")
                                return res
                        except Exception as tr_err:
                            _stop_if_blocked(tr_err, "Tier 5c")
                            continue

            attempt_history.append(f"Tier 5 (Direct Python API): No accessible track in {len(all_transcripts)} tracks")
        except Exception as list_err:
            _stop_if_blocked(list_err, "Tier 5")
            err_type = type(list_err).__name__
            err_msg = str(list_err).strip().split('\n')[0]
            attempt_history.append(f"Tier 5 (Direct Python API): {err_type} ({err_msg})")
    except Exception as api_err:
        _stop_if_blocked(api_err, "Tier 5")
        attempt_history.append(f"Tier 5 (Direct Python API setup): {type(api_err).__name__} ({str(api_err)[:150]})")

    # ── Tier 6: Direct YouTubeTranscriptApi CLI Subprocess ────────────────────
    _stop_if_remembered()
    notify("Tier 6/7: Direct CLI Subprocess", "Trying Method 6/7: Direct isolated CLI subprocess...", 88)
    try:
        direct_cli_data = fetch_transcript_cli(video_id, priority_langs, proxy_url=None, timeout=15)
        if direct_cli_data:
            logger.info(f"[Tier 6] Transcript fetched via direct CLI subprocess: {len(direct_cli_data)} lines")
            return direct_cli_data
    except Exception as cli_err:
        _stop_if_blocked(cli_err, "Tier 6")
        attempt_history.append(f"Tier 6 (Direct CLI Subprocess): {type(cli_err).__name__} ({str(cli_err)[:150]})")

    # ── Tier 7: Direct yt-dlp Native Extraction ──────────────────────────────
    _stop_if_remembered()
    notify("Tier 7/7: Direct yt-dlp Native", "Trying Method 7/7: Direct yt-dlp native caption extraction...", 94)
    try:
        direct_ytdlp_data = fetch_transcript_ytdlp(video_id, proxy=None)
        if direct_ytdlp_data:
            res = normalize_transcript(direct_ytdlp_data)
            if res:
                logger.info(f"[Tier 7] Transcript fetched via direct yt-dlp: {len(res)} lines")
                return res
        attempt_history.append("Tier 7 (Direct yt-dlp): No subtitle streams found")
    except Exception as ytdlp_err:
        _stop_if_blocked(ytdlp_err, "Tier 7")
        attempt_history.append(f"Tier 7 (Direct yt-dlp): {type(ytdlp_err).__name__} ({str(ytdlp_err)[:150]})")

    # ── All Tiers Exhausted: Construct Comprehensive Diagnostic Error ─────────
    combined_history = " ".join(attempt_history)
    root_cause = []
    code = youtube_errors.CAPTIONS_UNAVAILABLE
    if "TranscriptsDisabled" in combined_history:
        root_cause.append("Subtitles are disabled for this video by the creator.")
        code = youtube_errors.CAPTIONS_DISABLED
    elif "AgeRestricted" in combined_history:
        root_cause.append("Video is age-restricted and requires YouTube authentication.")
        code = youtube_errors.AGE_RESTRICTED
    elif "VideoUnavailable" in combined_history:
        root_cause.append("Video is private or unavailable.")
        code = youtube_errors.VIDEO_UNAVAILABLE

    error_lines = [
        f"Unable to retrieve subtitles for YouTube video ID '{video_id}'."
    ]
    if root_cause:
        error_lines.append(f"Probable Cause: {' '.join(root_cause)}")

    error_lines.append("\nMethods attempted and diagnostic results:")
    for h in attempt_history:
        error_lines.append(f"  • {h}")

    error_lines.append("\nRecommended solutions:")
    if not (proxy_cfg or proxy_url):
        error_lines.append("  1. Configure a proxy in backend/.env (e.g. WEBSHARE_USERNAME & WEBSHARE_PASSWORD, or WEBSHARE_PROXY / PROXY_URL) to bypass datacenter IP bans.")
    else:
        error_lines.append("  1. Verify your proxy quota/credentials in backend/.env or rotate your residential proxy IP.")
    error_lines.append("  2. If using Supadata, configure SUPADATA_API_KEYS in backend/.env for residential cloud extraction.")
    error_lines.append("  3. Upload custom subtitles manually (.srt or .txt file) using the 'Upload Custom Subtitle' setting above.")

    full_error_detail = "\n".join(error_lines)
    logger.error(f"Subtitle retrieval exhausted all {len(attempt_history)} methods:\n{full_error_detail}")
    raise CaptionUnavailable(code, full_error_detail)
