"""
Studio uploads: background music, hook sound effect and watermark image,
and the endpoints that serve them back. The rules (types, sizes, names,
folder) are in uploads.py (#58).
"""
import asyncio
import logging
import os
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

try:
    from backend.uploads import (
        AUDIO_TYPES, CHUNK_BYTES, IMAGE_TYPES, MB, MULTIPART_OVERHEAD_BYTES, UPLOAD_KINDS, UPLOAD_PATHS,
        UploadKind, extension, media_type, saved_name, uploads_dir,
    )
except ImportError:
    from uploads import (
        AUDIO_TYPES, CHUNK_BYTES, IMAGE_TYPES, MB, MULTIPART_OVERHEAD_BYTES, UPLOAD_KINDS, UPLOAD_PATHS,
        UploadKind, extension, media_type, saved_name, uploads_dir,
    )

logger = logging.getLogger("xoraclips")
router = APIRouter()


def _too_large(upload: UploadKind) -> str:
    return f"File too large: {upload.kind} files can be at most {upload.max_bytes // MB} MB"


async def refuse_oversized_uploads(request: Request, call_next):
    """Middleware: an upload over its limit is refused from its Content-Length,
    before the body is read. By the time an endpoint runs, FastAPI has
    already received the whole file."""
    path = request.url.path
    root = request.scope.get("root_path") or ""
    if root and path.startswith(root):
        path = path[len(root):]   # behind a proxy prefix (uvicorn --root-path)
    upload = UPLOAD_PATHS.get(path)
    if upload is not None and request.method == "POST":
        length = request.headers.get("content-length")
        if length is None:
            return JSONResponse({"detail": "Content-Length required"}, status_code=411)
        if not (length.isascii() and length.isdigit()) or int(length) > upload.max_bytes + MULTIPART_OVERHEAD_BYTES:
            return JSONResponse({"detail": _too_large(upload)}, status_code=413)
    return await call_next(request)


class _TooLarge(Exception):
    pass


def _store(source, target: Path, max_bytes: int) -> int:
    """Copies an upload that FastAPI has already received (spooled) to the
    upload folder, counting as it goes; nothing is left behind on failure."""
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with open(target, "wb") as out:
            while chunk := source.read(CHUNK_BYTES):
                size += len(chunk)
                if size > max_bytes:
                    raise _TooLarge()
                out.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return size


async def _save_upload(file: UploadFile, upload: UploadKind) -> dict:
    """Checks, names and stores one upload, and describes it. The size is
    checked again here: the Content-Length check only saw the whole body."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    if extension(file.filename) not in upload.types:
        raise HTTPException(status_code=400,
                            detail=f"Unsupported {upload.kind} format. Allowed: {', '.join(upload.types)}")
    if file.size is not None and file.size > upload.max_bytes:
        raise HTTPException(status_code=413, detail=_too_large(upload))

    name = saved_name(file.filename, upload.prefix)
    try:
        size = await asyncio.to_thread(_store, file.file, uploads_dir() / name, upload.max_bytes)
    except _TooLarge:
        raise HTTPException(status_code=413, detail=_too_large(upload))
    except Exception as e:
        logger.error(f"Failed to upload {upload.label}: {e}")
        # The details (paths, OS errors) stay in the log.
        raise HTTPException(status_code=500, detail=f"Could not save the {upload.kind} file")
    return {
        "success": True,
        "filename": file.filename,
        "saved_name": name,
        # The saved name, not a server path: a render refers to uploads by name.
        "file_path": name,
        "url": f"{upload.url_base}{name}",
        "size_bytes": size,
    }


def _serve(file_name: str, types: dict, what: str):
    clean_name = os.path.basename(file_name)
    file_path = uploads_dir() / clean_name
    kind = media_type(clean_name, types)
    if kind is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return FileResponse(file_path, media_type=kind, filename=clean_name)


@router.post("/api/upload-bgm")
async def upload_bgm(file: UploadFile = File(...)):
    return await _save_upload(file, UPLOAD_KINDS["bgm"])


@router.get("/api/audio/{file_name}")
def get_audio_file(file_name: str):
    return _serve(file_name, AUDIO_TYPES, "Audio file")


@router.post("/api/upload-sfx")
async def upload_hook_sfx(file: UploadFile = File(...)):
    return await _save_upload(file, UPLOAD_KINDS["sfx"])


@router.post("/api/upload-watermark")
async def upload_watermark(file: UploadFile = File(...)):
    return await _save_upload(file, UPLOAD_KINDS["watermark"])


@router.get("/api/watermark/{file_name}")
def get_watermark_file(file_name: str):
    return _serve(file_name, IMAGE_TYPES, "Watermark file")
