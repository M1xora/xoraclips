"""
YouTube cookies for yt-dlp: save, status (never the content) and delete.
Moved out of main.py unchanged (#60).
"""
import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

try:
    from backend.video_engine import COOKIES_PATH
except ImportError:
    from video_engine import COOKIES_PATH

logger = logging.getLogger("xoraclips")
router = APIRouter()


class CookiesSaveRequest(BaseModel):
    cookies: Optional[str] = None
    cookies_content: Optional[str] = None


@router.post("/api/cookies")
def save_youtube_cookies(req: CookiesSaveRequest):
    content = (req.cookies_content or req.cookies or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Cookies content cannot be empty")
    try:
        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        return {
            "success": True,
            "status": "saved",
            "exists": True,
            "has_cookies": True,
            "size": len(content)
        }
    except Exception as e:
        logger.error(f"Failed to save cookies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


_COOKIE_DOMAIN_RE = re.compile(r"\.?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


@router.get("/api/cookies")
def get_youtube_cookies_status():
    """Whether cookies are saved, their size and domains. Never their content:
    the cookies are a YouTube login (issue #45)."""
    if COOKIES_PATH.exists() and COOKIES_PATH.stat().st_size > 0:
        sample_lines = []
        try:
            with open(COOKIES_PATH, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#HttpOnly_"):
                        line = line[len("#HttpOnly_"):]
                    if not line or line.startswith("#"):
                        continue
                    # Only something shaped like a domain: a line pasted with
                    # spaces instead of tabs must not leak its values.
                    domain = line.split()[0]
                    if _COOKIE_DOMAIN_RE.fullmatch(domain) and domain not in sample_lines:
                        sample_lines.append(domain)
                    if len(sample_lines) >= 6:
                        break
        except Exception:
            pass
        return {
            "exists": True,
            "has_cookies": True,
            "size": COOKIES_PATH.stat().st_size,
            "sample_lines": sample_lines,
        }
    return {"exists": False, "has_cookies": False, "size": 0, "sample_lines": []}


@router.delete("/api/cookies")
def delete_youtube_cookies():
    if COOKIES_PATH.exists():
        try:
            COOKIES_PATH.unlink()
        except Exception:
            pass
    return {"success": True, "status": "deleted", "exists": False, "has_cookies": False}
