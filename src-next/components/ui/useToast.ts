import { useCallback, useEffect, useRef, useState } from 'react';
import type { ToastKind, ToastState } from './Toast';

/** Transient notice. One at a time, auto-dismissed. */
export function useToast(timeoutMs = 4000) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const timer = useRef<number | null>(null);

  const dismiss = useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = null;
    setToast(null);
  }, []);

  const show = useCallback(
    (message: string, kind: ToastKind = 'success') => {
      if (timer.current) window.clearTimeout(timer.current);
      setToast({ message, kind, id: Date.now() });
      timer.current = window.setTimeout(() => setToast(null), timeoutMs);
    },
    [timeoutMs],
  );

  // Clear the pending timer if the owner unmounts first.
  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  return { toast, show, dismiss };
}
