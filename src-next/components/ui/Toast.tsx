import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircleIcon, InfoIcon, WarningCircleIcon, XIcon } from '@phosphor-icons/react';

export type ToastKind = 'success' | 'error' | 'info';

export interface ToastState {
  message: string;
  kind: ToastKind;
  /** Changes on every show() so repeat messages restart the timer. */
  id: number;
}

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

const ICONS = {
  success: CheckCircleIcon,
  error: WarningCircleIcon,
  info: InfoIcon,
} as const;

const TONES = {
  success: 'text-positive',
  error: 'text-critical-text',
  info: 'text-teal-text',
} as const;

interface ToastProps {
  toast: ToastState | null;
  onDismiss: () => void;
}

export function Toast({ toast, onDismiss }: ToastProps) {
  if (!toast) return null;
  const Icon = ICONS[toast.kind];

  return (
    <div
      role="status"
      aria-live="polite"
      className="panel fixed bottom-4 left-1/2 z-[--z-toast] flex -translate-x-1/2
        items-center gap-2.5 py-2.5 pl-3 pr-2"
    >
      <Icon size={16} weight="fill" className={`shrink-0 ${TONES[toast.kind]}`} />
      <span className="text-xs">{toast.message}</span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className="pressable grid size-6 place-items-center rounded text-ink-faint hover:text-ink"
      >
        <XIcon size={12} weight="bold" />
      </button>
    </div>
  );
}
