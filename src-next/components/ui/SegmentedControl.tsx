interface Option<T extends string> {
  value: T;
  label: string;
  sub?: string;
}

interface SegmentedControlProps<T extends string> {
  label: string;
  value: T;
  options: readonly Option<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
}

/**
 * Exclusive choice rendered as a radiogroup.
 *
 * The old UI built these from plain buttons, so a screen reader announced a
 * row of unrelated controls and arrow keys did nothing. Roles make the
 * grouping and the selected item explicit.
 */
export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
}: SegmentedControlProps<T>) {
  return (
    <div>
      <span className="text-xs font-medium text-ink-dim">{label}</span>
      <div
        role="radiogroup"
        aria-label={label}
        className="mt-1.5 inline-flex rounded-[--radius-control] border border-hairline bg-surface-2 p-0.5"
      >
        {options.map((opt) => {
          const active = opt.value === value;
          return (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={disabled}
              onClick={() => onChange(opt.value)}
              className={`pressable rounded-[calc(var(--radius-control)-2px)] px-3 py-1.5
                text-xs font-medium disabled:opacity-40
                ${active ? 'bg-accent text-on-accent' : 'text-ink-dim hover:text-ink'}`}
            >
              {opt.label}
              {opt.sub && <span className="ml-1 opacity-70">{opt.sub}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}
