"""
Issue #53: OpenCV 5 has no CascadeClassifier, and face tracking used to fall
back to the centre for every clip without a word. The requirement now stays
below 5, and a missing classifier (or a missing OpenCV) is logged once as a
clear error.

Uses a fake cv2 module: CI does not install OpenCV.
"""
import re
import sys
import types
from pathlib import Path

import pytest

import video_engine

REQUIREMENTS = Path(video_engine.__file__).with_name("requirements.txt")
DEFAULT_BOX = {"found": False, "cx": 0.5, "cy": 0.35, "w": 0.25, "h": 0.25}


def opencv_requirement():
    return next(l.strip() for l in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
                if l.strip().startswith("opencv-python"))


def test_requirements_keep_opencv_below_5():
    assert re.search(r"<\s*5\b", opencv_requirement())


@pytest.fixture
def frame(monkeypatch, tmp_path):
    """A frame file and a cascade file that exist, and a fresh log-once flag."""
    cascade = tmp_path / "cascade.xml"
    cascade.write_text("<opencv_storage/>", encoding="utf-8")
    monkeypatch.setattr(video_engine, "CASCADE_PATH", cascade)
    monkeypatch.setattr(video_engine, "_face_tracking_off_logged", False)
    path = tmp_path / "frame.jpg"
    path.write_bytes(b"not really a jpeg")
    return str(path)


def errors(caplog):
    return [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]


def test_opencv_without_cascade_classifier_logs_one_clear_error(monkeypatch, frame, caplog):
    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.__version__ = "5.0.0"
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)

    with caplog.at_level("ERROR"):
        assert video_engine.detect_speaker_face_box(frame) == DEFAULT_BOX
        assert video_engine.detect_speaker_face_box(frame) == DEFAULT_BOX

    [message] = errors(caplog)
    assert "Face tracking is OFF" in message
    assert "OpenCV 5.0.0 has no CascadeClassifier" in message
    # The fix names the exact requirement, read from requirements.txt.
    assert f'pip install "{opencv_requirement()}"' in message


def test_opencv_not_installed_logs_one_clear_error(monkeypatch, frame, caplog):
    monkeypatch.setitem(sys.modules, "cv2", None)  # makes `import cv2` raise ImportError

    with caplog.at_level("ERROR"):
        assert video_engine.detect_speaker_face_box(frame) == DEFAULT_BOX
        assert video_engine.detect_speaker_face_box(frame) == DEFAULT_BOX

    [message] = errors(caplog)
    assert "OpenCV is not installed" in message
