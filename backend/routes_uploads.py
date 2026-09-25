"""
Studio uploads: background music, hook sound effect and watermark image,
and the endpoints that serve them back. Moved out of main.py unchanged (#60).
"""
import logging
import os
import re
import uuid
from typing import NamedTuple, Tuple

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

try:
    from backend import video_engine
except ImportError:
    import video_engine

logger = logging.getLogger("xoraclips")
router = APIRouter()


UPLOADS_DIR = video_engine.TEMP_DIR / "uploads"


UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


AUDIO_UPLOAD_TYPES = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")


IMAGE_UPLOAD_TYPES = (".png", ".jpg", ".jpeg", ".webp", ".svg")


class UploadKind(NamedTuple):
    """What differs between the uploads; everything else is _save_upload (#48)."""
    prefix: str                 # start of the saved file name
    allowed: Tuple[str, ...]    # accepted extensions
    kind: str                   # "audio" or "image", for the error message
    url_base: str               # where the saved file is served
    label: str                  # for the log


UPLOAD_KINDS = {
    "bgm": UploadKind("bgm_", AUDIO_UPLOAD_TYPES, "audio", "/api/audio/", "BGM"),
    "sfx": UploadKind("sfx_", AUDIO_UPLOAD_TYPES, "audio", "/api/audio/", "Hook SFX"),
    "watermark": UploadKind("wm_", IMAGE_UPLOAD_TYPES, "image", "/api/watermark/", "watermark"),
}


async def _save_upload(file: UploadFile, upload: UploadKind) -> dict:
    """Checks, names and stores one upload in UPLOADS_DIR, and describes it."""
    prefix, allowed, kind, url_base, label = upload
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported {kind} format. Allowed: {', '.join(allowed)}")

    clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', file.filename)
    unique_name = f"{prefix}{uuid.uuid4().hex[:8]}_{clean_name}"
    save_path = UPLOADS_DIR / unique_name

    try:
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)
        return {
            "success": True,
            "filename": file.filename,
            "saved_name": unique_name,
            "file_path": str(save_path),
            "url": f"{url_base}{unique_name}",
            "size_bytes": len(content)
        }
    except Exception as e:
        logger.error(f"Failed to upload {label}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/upload-bgm")
async def upload_bgm(file: UploadFile = File(...)):
    return await _save_upload(file, UPLOAD_KINDS["bgm"])


@router.get("/api/audio/{file_name}")
def get_audio_file(file_name: str):
    clean_name = os.path.basename(file_name)
    file_path = UPLOADS_DIR / clean_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    media_type = "audio/mpeg" if clean_name.endswith(".mp3") else "audio/wav" if clean_name.endswith(".wav") else "application/octet-stream"
    return FileResponse(file_path, media_type=media_type, filename=clean_name)


@router.post("/api/upload-sfx")
async def upload_hook_sfx(file: UploadFile = File(...)):
    return await _save_upload(file, UPLOAD_KINDS["sfx"])


@router.post("/api/upload-watermark")
async def upload_watermark(file: UploadFile = File(...)):
    return await _save_upload(file, UPLOAD_KINDS["watermark"])


@router.get("/api/watermark/{file_name}")
def get_watermark_file(file_name: str):
    clean_name = os.path.basename(file_name)
    file_path = UPLOADS_DIR / clean_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Watermark file not found")
    media_type = "image/png" if clean_name.endswith(".png") else "image/jpeg" if (clean_name.endswith(".jpg") or clean_name.endswith(".jpeg")) else "image/webp"
    return FileResponse(file_path, media_type=media_type, filename=clean_name)
