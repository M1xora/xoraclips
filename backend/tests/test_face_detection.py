"""
Issue #53: OpenCV 5 has no CascadeClassifier, and face tracking used to fall
back to the centre for every clip without a word. The requirement now stays
below 5, and a missing classifier is logged once as a clear error.

Uses a fake cv2 module: CI does not install OpenCV.
"""
import re
import sys
import types
from pathlib import Path

import video_engine

REQUIREMENTS = Path(video_engine.__file__).with_name("requirements.txt")
DEFAULT_BOX = {"found": False, "cx": 0.5, "cy": 0.35, "w": 0.25, "h": 0.25}


def test_requirements_keep_opencv_below_5():
    line = next(l for l in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
                if l.strip().startswith("opencv-python"))
    assert re.search(r"<\s*5\b", line), line


def test_opencv_without_cascade_classifier_logs_one_clear_error(monkeypatch, tmp_path, caplog):
    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.__version__ = "5.0.0"
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    monkeypatch.setattr(video_engine, "_cascade_missing_logged", False)
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"not really a jpeg")

    with caplog.at_level("ERROR"):
        first = video_engine.detect_speaker_face_box(str(frame))
        second = video_engine.detect_speaker_face_box(str(frame))

    assert first == DEFAULT_BOX and second == DEFAULT_BOX
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1
    assert "Face tracking is OFF" in errors[0].getMessage()
    assert "OpenCV 5.0.0" in errors[0].getMessage()
    assert 'opencv-python>=4.8,<5' in errors[0].getMessage()
