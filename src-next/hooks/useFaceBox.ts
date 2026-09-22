import { useEffect, useState } from 'react';
import { api, type FaceBox } from '../api/client';

/**
 * Where the speaker's face sits in the frame.
 *
 * The old frontend called this endpoint and threw the answer away
 * (`const [, setFaceBox]`, ClipStudioSection.tsx:253), so face tracking
 * never showed in the preview even though the backend supported it. Here the
 * result actually drives the crop.
 *
 * Returns null while loading, when tracking is off, or when no face is found,
 * and the caller falls back to a centre crop.
 */
export function useFaceBox(
  videoId: string,
  timestamp: number,
  enabled: boolean,
): { box: FaceBox | null; loading: boolean } {
  const [box, setBox] = useState<FaceBox | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled || !videoId) {
      setBox(null);
      return;
    }

    const controller = new AbortController();
    setLoading(true);

    api
      .detectFace(videoId, timestamp, undefined, controller.signal)
      .then((res) => {
        if (controller.signal.aborted) return;
        // `found` false means the detector ran and saw nothing, which is
        // different from an error: keep the centre crop.
        setBox(res.found ? res : null);
      })
      .catch(() => {
        if (!controller.signal.aborted) setBox(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [videoId, timestamp, enabled]);

  return { box, loading };
}

/**
 * Horizontal offset, in percent, that brings the face into the crop.
 *
 * `cx` is the face centre across the full 16:9 source. Shifting the source
 * so that point lands in the middle of a narrower frame is a translation of
 * (0.5 - cx) of the source width. The result is clamped so the crop cannot
 * slide past the edge and expose empty space.
 */
export function faceOffsetPercent(
  box: FaceBox | null,
  frameW: number,
  sourceW: number,
): number {
  if (!box || !box.found || sourceW <= frameW) return 0;

  const shiftPx = (0.5 - box.cx) * sourceW;
  const maxShiftPx = (sourceW - frameW) / 2;
  const clamped = Math.max(-maxShiftPx, Math.min(maxShiftPx, shiftPx));

  return (clamped / sourceW) * 100;
}
