import { useId, type InputHTMLAttributes, type ReactNode } from 'react';

interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  trailing?: ReactNode;
  required?: boolean;
}

/**
 * Labelled text input.
 *
 * Label sits above the control, helper text below, error below that, and the
 * error is wired to the input with aria-describedby. The old form used
 * placeholders as labels and showed errors as loose sibling spans.
 */
export function Field({
  label,
  hint,
  error,
  trailing,
  required,
  className = '',
  ...rest
}: FieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errId = `${id}-err`;

  return (
    <div className={className}>
      <label htmlFor={id} className="flex items-center gap-1.5 text-xs font-medium text-ink-dim">
        {label}
        {required && (
          <span className="rounded bg-critical/15 px-1 py-px font-mono text-[0.72rem] font-bold uppercase text-critical-text">
            required
          </span>
        )}
      </label>

      <div className="relative mt-1.5">
        <input
          {...rest}
          id={id}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errId : hint ? hintId : undefined}
          className={`h-9 w-full rounded-[--radius-control] border-2 bg-surface px-3 text-sm
            text-ink placeholder:text-ink-faint focus:shadow-brutal-sm
            ${error ? 'border-critical' : 'border-line'}
            ${trailing ? 'pr-20' : ''}`}
        />
        {trailing && (
          <div className="absolute inset-y-0 right-1.5 flex items-center">{trailing}</div>
        )}
      </div>

      {error ? (
        <p id={errId} role="alert" className="mt-1.5 text-xs text-critical-text">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="mt-1.5 text-xs text-ink-faint">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
