"""
Server status (health, Supadata quota) and temp storage size and cleanup.
Moved out of main.py unchanged (#60).
"""
import logging
import os

from fastapi import APIRouter

try:
    from backend.secrets_guard import is_mock_mode
    from backend.video_engine import COOKIES_PATH, TEMP_DIR
    from backend.youtube_source import get_proxy_url, get_supadata_keys, get_supadata_usage_data
except ImportError:
    from secrets_guard import is_mock_mode
    from video_engine import COOKIES_PATH, TEMP_DIR
    from youtube_source import get_proxy_url, get_supadata_keys, get_supadata_usage_data

logger = logging.getLogger("xoraclips")
router = APIRouter()

# The backend folder (this file sits next to main.py).
_base_dir = os.path.dirname(os.path.abspath(__file__))


@router.get("/api/health")
def health_check(refresh: bool = False):
    is_vercel = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
    keys = get_supadata_keys()
    proxy = get_proxy_url()
    supadata_info = get_supadata_usage_data(force=refresh) if keys else {
        "total_keys": 0,
        "total_limit": 0,
        "total_used": 0,
        "total_remaining": 0,
        "usage_percent": 0.0,
        "active_keys": 0,
        "exhausted_keys": 0,
        "keys_detail": [],
        "status": "not_configured"
    }
    return {
        "status": "ok",
        "message": "XORACLIPS API is active",
        "is_vercel": is_vercel,
        "proxy_configured": bool(proxy),
        "mock_mode": is_mock_mode(),
        "supadata_keys_count": len(keys),
        "supadata": supadata_info
    }


@router.get("/api/supadata-usage")
def supadata_usage_endpoint(refresh: bool = False):
    """Returns real-time usage and remaining credit quota across all configured Supadata API keys."""
    return get_supadata_usage_data(force=refresh)


def _get_dir_size_and_count(dir_path) -> tuple[int, int]:
    from pathlib import Path
    p = Path(dir_path)
    total_bytes = 0
    total_files = 0
    if p.exists() and p.is_dir():
        for item in p.rglob("*"):
            if item.is_file():
                try:
                    total_bytes += item.stat().st_size
                    total_files += 1
                except Exception:
                    pass
    return total_files, total_bytes


@router.get("/api/temp-storage-info")
async def get_temp_storage_info():
    """Returns total files, bytes, and formatted size of temp download storage."""
    from pathlib import Path
    base_dir = Path(_base_dir)
    f1, b1 = _get_dir_size_and_count(TEMP_DIR)
    f2, b2 = _get_dir_size_and_count(base_dir / "temp")
    tot_files = f1 + f2
    tot_bytes = b1 + b2
    tot_mb = round(tot_bytes / (1024 * 1024), 2)
    formatted = f"{tot_mb} MB" if tot_mb < 1024 else f"{round(tot_mb / 1024, 2)} GB"
    return {
        "total_files": tot_files,
        "total_bytes": tot_bytes,
        "total_mb": tot_mb,
        "formatted_size": formatted
    }


@router.post("/api/clear-temp")
async def clear_temp_folder():
    """
    Clears all temporary downloaded video clips, audio slices, ASS files, and frames
    from TEMP_DIR and backend/temp. Re-creates empty directories.
    PROTECTED: cookies.txt and any cookie files are strictly PRESERVED and NEVER deleted.
    """
    import shutil
    from pathlib import Path
    base_dir = Path(_base_dir)
    cleared_files = 0
    cleared_bytes = 0

    PROTECTED_COOKIE_NAMES = {"cookies.txt", ".cookies", "youtube_cookies.txt", "cookie.txt"}

    def is_protected_cookie(p: Path) -> bool:
        if p.name.lower() in PROTECTED_COOKIE_NAMES:
            return True
        try:
            if COOKIES_PATH.exists() and p.resolve() == COOKIES_PATH.resolve():
                return True
        except Exception:
            pass
        return False

    target_dirs = [TEMP_DIR, base_dir / "temp"]
    for d in target_dirs:
        if d.exists() and d.is_dir():
            for item in list(d.iterdir()):
                try:
                    if is_protected_cookie(item):
                        logger.info(f"Preserving protected cookie file: {item}")
                        continue

                    if item.is_file() or item.is_symlink():
                        sz = item.stat().st_size
                        item.unlink()
                        cleared_files += 1
                        cleared_bytes += sz
                    elif item.is_dir():
                        has_cookie = False
                        for sub in list(item.rglob("*")):
                            if is_protected_cookie(sub):
                                has_cookie = True
                                logger.info(f"Preserving protected cookie file inside folder: {sub}")
                                continue
                            if sub.is_file() or sub.is_symlink():
                                try:
                                    cleared_files += 1
                                    cleared_bytes += sub.stat().st_size
                                    sub.unlink()
                                except Exception:
                                    pass
                        if not has_cookie:
                            shutil.rmtree(item, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"Could not delete temp item {item}: {e}")
        d.mkdir(parents=True, exist_ok=True)

    # Ensure frames directory inside TEMP_DIR exists
    (TEMP_DIR / "frames").mkdir(parents=True, exist_ok=True)

    cleared_mb = round(cleared_bytes / (1024 * 1024), 2)
    formatted = f"{cleared_mb} MB" if cleared_mb < 1024 else f"{round(cleared_mb / 1024, 2)} GB"
    cookies_present = bool(COOKIES_PATH.exists() and COOKIES_PATH.stat().st_size > 0)
    logger.info(f"Cleared temp folder: {cleared_files} files, {formatted} (Cookies preserved: {cookies_present})")
    return {
        "success": True,
        "cleared_files": cleared_files,
        "cleared_bytes": cleared_bytes,
        "cleared_mb": cleared_mb,
        "cookies_preserved": True,
        "has_cookies": cookies_present,
        "message": f"Successfully cleared {cleared_files} temporary files ({formatted}). Stored YouTube cookies preserved."
    }
