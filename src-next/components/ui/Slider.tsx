import { useId } from 'react';

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  presets?: readonly { label: string; value: number }[];
  onChange: (value: number) => void;
  disabled?: boolean;
}

/**
 * Slider paired with a number input.
 *
 * Both controls share one label via aria-labelledby, so a screen reader does
 * not announce two unrelated fields. Typed values are clamped on change,
 * which the old inputs did not do.
 */
export function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  unit,
  presets,
  onChange,
  disabled,
}: SliderProps) {
  const labelId = useId();

  const clamp = (n: number) => Math.min(max, Math.max(min, n));

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span id={labelId} className="text-xs font-medium text-ink-dim">
          {label}
        </span>
        <input
          type="number"
          aria-labelledby={labelId}
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onChange={(e) => {
            const n = Number(e.target.value);
            if (!Number.isNaN(n)) onChange(clamp(n));
          }}
          className="tabular h-6 w-16 rounded-[--radius-control] border border-hairline
            bg-surface-2 px-1.5 text-right text-xs text-ink disabled:opacity-40"
        />
      </div>

      <input
        type="range"
        aria-labelledby={labelId}
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 h-1.5 w-full cursor-pointer appearance-none rounded-full
          bg-surface-3 accent-accent disabled:opacity-40"
      />

      {presets && (
        <div className="mt-2 flex flex-wrap gap-1">
          {presets.map((p) => (
            <button
              key={p.label}
              type="button"
              disabled={disabled}
              onClick={() => onChange(clamp(p.value))}
              className={`pressable rounded px-1.5 py-0.5 text-[0.8rem] disabled:opacity-40
                ${
                  value === p.value
                    ? 'bg-accent-muted text-ink'
                    : 'text-ink-faint hover:bg-surface-2 hover:text-ink-dim'
                }`}
            >
              {p.label}
              {unit}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
