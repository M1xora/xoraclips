"""
Studio uploads (background music, hook sound effect, watermark image):
which files are accepted and how they are served, where they are stored,
and how a render finds them again (#58). The endpoints are in
routes_uploads.py.

Uploads are capped: audio 50 MB, images 10 MB. A render refers to an upload
by its saved name only; a path from the request is never opened as is.
"""
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Dict, NamedTuple, Optional

try:
    from backend import video_engine
except ImportError:
    import video_engine

logger = logging.getLogger("xoraclips")

MB = 1024 * 1024

# Extension → media type. The one list for both accepting and serving files.
# SVG is not here: ffmpeg cannot overlay it (#58).
AUDIO_TYPES: Dict[str, str] = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".aac": "audio/aac", ".ogg": "audio/ogg", ".flac": "audio/flac",
}
IMAGE_TYPES: Dict[str, str] = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
}

MAX_NAME_CHARS = 80
CHUNK_BYTES = MB


class UploadKind(NamedTuple):
    """What differs between the uploads; everything else is shared (#48)."""
    prefix: str                 # start of the saved file name
    types: Dict[str, str]       # accepted extensions and their media types
    kind: str                   # "audio" or "image", for the error message
    url_base: str               # where the saved file is served
    label: str                  # for the log
    max_bytes: int


UPLOAD_KINDS = {
    "bgm": UploadKind("bgm_", AUDIO_TYPES, "audio", "/api/audio/", "BGM", 50 * MB),
    "sfx": UploadKind("sfx_", AUDIO_TYPES, "audio", "/api/audio/", "Hook SFX", 50 * MB),
    "watermark": UploadKind("wm_", IMAGE_TYPES, "image", "/api/watermark/", "watermark", 10 * MB),
}
UPLOAD_PATHS = {f"/api/upload-{name}": kind for name, kind in UPLOAD_KINDS.items()}
# Room for the multipart envelope around the file in a request body.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def uploads_dir() -> Path:
    """The upload folder, inside the temp folder that video_engine names.
    Created when a file is saved, not here: serving must not create it."""
    return video_engine.TEMP_DIR / "uploads"


def extension(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def saved_name(original: str, prefix: str) -> str:
    """A unique, safe, not too long file name that keeps the extension."""
    stem, ext = os.path.splitext(re.sub(r'[^a-zA-Z0-9_.-]', '_', original))
    return f"{prefix}{uuid.uuid4().hex[:8]}_{stem[:MAX_NAME_CHARS - len(ext)]}{ext.lower()}"


def media_type(name: str, types: Dict[str, str]) -> Optional[str]:
    return types.get(extension(name))


class MissingUpload(Exception):
    """A render setting names an upload that is not (any more) on the server."""


def resolve_upload(reference: Optional[str], kind: str) -> Optional[str]:
    """The stored file a render setting refers to; None when there is no
    reference. Only the last part of the reference counts (older app
    versions sent the full server path), and it must be an existing upload
    of this kind, else MissingUpload with a message for the user."""
    if not reference:
        return None
    upload = UPLOAD_KINDS[kind]
    name = re.split(r"[\\/]", reference)[-1]
    path = uploads_dir() / name
    try:
        found = name.startswith(upload.prefix) and extension(name) in upload.types and path.is_file()
    except OSError:
        found = False
    if found:
        return str(path)
    logger.warning(f"{upload.label} file {name!r} is not an upload of this kind on this server")
    raise MissingUpload(f"The {upload.label} file is no longer on the server (temp files may have been "
                        f"cleared). Upload it again in the Studio, then render.")
