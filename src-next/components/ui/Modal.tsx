import { useEffect, useId, useRef, type ReactNode } from 'react';
import { XIcon } from '@phosphor-icons/react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: 'md' | 'lg' | 'xl';
}

const SIZES = {
  md: 'max-w-lg',
  lg: 'max-w-3xl',
  xl: 'max-w-6xl',
} as const;

/**
 * Accessible modal dialog.
 *
 * The previous modals were plain divs: no role, no labelling, no focus
 * management and no Escape handling, so keyboard and screen-reader users
 * could not operate or leave them. This adds all four, plus a focus trap
 * and scroll lock.
 */
export function Modal({ open, onClose, title, children, footer, size = 'lg' }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const titleId = useId();

  // Escape to close, Tab cycles within the dialog.
  useEffect(() => {
    if (!open) return;

    restoreFocusRef.current = document.activeElement as HTMLElement | null;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;

      const focusables = panelRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusables || focusables.length === 0) return;

      const first = focusables[0];
      const last = focusables[focusables.length - 1];

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    // Move focus into the dialog once it is mounted.
    const raf = requestAnimationFrame(() => {
      panelRef.current
        ?.querySelector<HTMLElement>('button, input, textarea, select, [tabindex]')
        ?.focus();
    });

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = prevOverflow;
      cancelAnimationFrame(raf);
      restoreFocusRef.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[--z-modal] flex items-center justify-center p-4 sm:p-6"
      role="presentation"
    >
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`panel relative flex max-h-[90vh] w-full flex-col ${SIZES[size]}`}
      >
        <header className="flex items-center justify-between gap-4 border-b border-hairline px-5 py-4">
          <h2 id={titleId} className="font-display text-lg font-bold">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="pressable grid size-8 place-items-center rounded-[--radius-control] text-ink-dim hover:bg-surface-2 hover:text-ink"
          >
            <XIcon size={16} weight="bold" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>

        {footer && (
          <footer className="border-t border-hairline px-5 py-4">{footer}</footer>
        )}
      </div>
    </div>
  );
}
