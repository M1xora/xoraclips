"""
Issue #105: the split layout's cam box used a fixed zoom, so how much of the
box the face filled depended entirely on how big the facecam happened to be.

The numbers below are measured from the three sample videos, not invented:

    video                                   face width   filled the box
    Pelanggan Ini Mengirim Kepala Manusia      163 px          17%
    Malam Ketiga Mulai Sangat Mencekam         300 px          30%
    Paket Misterius Berisi Darah               499 px          51%

Three times apart. The crop now follows the face's own width, so all three
land in the same range, and the face sits far closer to the centre of the box.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import video_engine  # noqa: E402
from backend.video_engine import (  # noqa: E402
    SPLIT_CAM_H, SPLIT_CAM_W, SPLIT_CAM_ZOOM, build_ffmpeg_filtergraph, split_cam_crop_share,
)

SOURCE_W, SOURCE_H = 1920.0, 1080.0

# (name, cx, cy, face width as a share of the frame, face width in pixels)
SAMPLES = [
    ("pelanggan", 0.105, 0.853, 0.085, 163),
    ("malam", 0.787, 0.311, 0.156, 300),
    ("paket", 0.648, 0.849, 0.260, 499),
]


def crop_px(face_w: float, zoom=None):
    """The cam crop in pixels, the way the ffmpeg expression computes it."""
    share = split_cam_crop_share(face_w, zoom, source_w=SOURCE_W, source_h=SOURCE_H)
    w = min(SOURCE_W, SOURCE_H * SPLIT_CAM_W / SPLIT_CAM_H) * share
    h = min(SOURCE_H, SOURCE_W * SPLIT_CAM_H / SPLIT_CAM_W) * share
    return w, h


def face_position_in_box(cx, cy, face_w):
    """Where the face lands inside the cam box: 0.5 is dead centre."""
    w, h = crop_px(face_w)
    x = max(0.0, min(SOURCE_W - w, cx * SOURCE_W - w / 2))
    y = max(0.0, min(SOURCE_H - h, cy * SOURCE_H - h / 2))
    return (cx * SOURCE_W - x) / w, (cy * SOURCE_H - y) / h


# --- the crop follows the face ----------------------------------------------------------

def test_a_small_face_gets_a_tighter_crop_than_a_large_one():
    small, _ = crop_px(0.085)      # 163px face
    large, _ = crop_px(0.260)      # 499px face
    assert small < large, (small, large)


@pytest.mark.parametrize("name,cx,cy,face_w,face_px", SAMPLES)
def test_every_sample_fills_a_similar_share_of_the_box(name, cx, cy, face_w, face_px):
    """The point of the change: 17/30/51% becomes one consistent range."""
    w, _ = crop_px(face_w)
    assert 0.35 <= face_px / w <= 0.65, f"{name}: face fills {face_px / w:.0%} of the crop"


@pytest.mark.parametrize("name,cx,cy,face_w,face_px", SAMPLES)
def test_the_face_moves_closer_to_the_centre_than_the_old_fixed_zoom(name, cx, cy, face_w, face_px):
    old_w = min(SOURCE_W, SOURCE_H * SPLIT_CAM_W / SPLIT_CAM_H) * SPLIT_CAM_ZOOM
    old_h = min(SOURCE_H, SOURCE_W * SPLIT_CAM_H / SPLIT_CAM_W) * SPLIT_CAM_ZOOM
    ox = max(0.0, min(SOURCE_W - old_w, cx * SOURCE_W - old_w / 2))
    oy = max(0.0, min(SOURCE_H - old_h, cy * SOURCE_H - old_h / 2))
    was = abs((cx * SOURCE_W - ox) / old_w - 0.5) + abs((cy * SOURCE_H - oy) / old_h - 0.5)

    px, py = face_position_in_box(cx, cy, face_w)
    now = abs(px - 0.5) + abs(py - 0.5)
    assert now <= was, f"{name}: {was:.2f} -> {now:.2f}"


def test_the_measured_improvement_is_pinned():
    """The scores the factor and ceiling were chosen on (issue #105)."""
    total = sum(abs(p - 0.5) + abs(q - 0.5)
                for _, cx, cy, fw, _ in SAMPLES
                for p, q in [face_position_in_box(cx, cy, fw)])
    assert total == pytest.approx(0.23, abs=0.02), total


# --- the ceiling ------------------------------------------------------------------------

def test_a_large_face_does_not_fill_the_whole_frame():
    """Without a ceiling the crop has no room to slide, so the face stays put.

    Found while measuring: at factor 3 the 499px face gave a 1497x1065 crop on
    a 1080-tall frame, and that sample got *worse*, not better.
    """
    _, h = crop_px(0.6)
    assert h <= SOURCE_H * video_engine.SPLIT_CAM_MAX_SHARE + 1


def test_there_is_always_room_left_to_move_the_crop():
    for _, _, _, face_w, _ in SAMPLES:
        w, h = crop_px(face_w)
        assert w < SOURCE_W and h < SOURCE_H


# --- falling back -----------------------------------------------------------------------

def test_no_detected_face_keeps_the_old_behaviour_exactly():
    assert split_cam_crop_share(0.0) == SPLIT_CAM_ZOOM
    assert split_cam_crop_share(-1.0) == SPLIT_CAM_ZOOM


def test_a_filtergraph_without_a_face_box_is_unchanged():
    graph, _ = build_ffmpeg_filtergraph("9:16", "black", streamer_preset="split_top_cam")
    assert f"*{SPLIT_CAM_ZOOM:.4f}" in graph


def test_a_box_that_found_nothing_is_not_treated_as_a_face():
    """detect_speaker_face_box returns w=0.25 with found=False; that is a
    default, not a measurement, and must not size the crop."""
    graph, _ = build_ffmpeg_filtergraph(
        "9:16", "black", streamer_preset="split_top_cam",
        face_box={"found": False, "cx": 0.5, "cy": 0.35, "w": 0.25, "h": 0.25})
    assert f"*{SPLIT_CAM_ZOOM:.4f}" in graph


# --- the manual override ----------------------------------------------------------------

def test_a_manual_zoom_wins_over_the_detected_face():
    assert split_cam_crop_share(0.085, zoom=0.5) == 0.5


def test_a_manual_centre_wins_over_the_detected_face():
    graph, _ = build_ffmpeg_filtergraph(
        "9:16", "black", streamer_preset="split_top_cam",
        face_box={"found": True, "cx": 0.105, "cy": 0.853, "w": 0.085, "h": 0.152},
        cam_center_x=0.5, cam_center_y=0.5)
    cam = re.search(r"\[cam_raw\]crop=[^;]+", graph).group()
    assert "iw*0.500-ow/2" in cam and "ih*0.500-oh/2" in cam


@pytest.mark.parametrize("zoom,expected", [(-1.0, 0.05), (0.0, 0.05), (5.0, 1.0)])
def test_a_manual_zoom_out_of_range_is_clamped(zoom, expected):
    assert split_cam_crop_share(0.085, zoom=zoom) == expected


def test_a_manual_centre_out_of_range_is_clamped():
    graph, _ = build_ffmpeg_filtergraph(
        "9:16", "black", streamer_preset="split_top_cam", cam_center_x=9.0, cam_center_y=-9.0)
    cam = re.search(r"\[cam_raw\]crop=[^;]+", graph).group()
    assert "iw*1.000-ow/2" in cam and "ih*0.000-oh/2" in cam


# --- other sources ----------------------------------------------------------------------

def test_a_720p_source_crops_proportionally():
    """A face is a share of its own frame, so the same share on a smaller
    source must give a proportionally smaller crop, not the same pixels."""
    share_1080 = split_cam_crop_share(0.085, source_w=1920, source_h=1080)
    share_720 = split_cam_crop_share(0.085, source_w=1280, source_h=720)
    assert share_1080 == pytest.approx(share_720, abs=0.001)


def test_the_share_never_leaves_its_bounds():
    for face_w in (0.001, 0.01, 0.5, 0.9, 1.0, 2.0):
        share = split_cam_crop_share(face_w)
        assert 0.05 <= share <= 1.0, (face_w, share)
