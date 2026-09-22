import { MoonIcon, SunIcon } from '@phosphor-icons/react';
import type { Theme } from '../../hooks/useTheme';

interface ThemeToggleProps {
  theme: Theme;
  onToggle: () => void;
}

/**
 * Two-state theme switch.
 *
 * Labelled and pressable by keyboard, which the old UI's icon-only controls
 * were not. aria-pressed tells a screen reader which mode is active.
 */
export function ThemeToggle({ theme, onToggle }: ThemeToggleProps) {
  const isDark = theme === 'dark';
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={isDark}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      className="pressable grid size-8 place-items-center rounded-[--radius-control]
        border border-hairline bg-surface-2 text-ink-dim hover:bg-surface-3 hover:text-ink"
    >
      {isDark ? <MoonIcon size={15} weight="fill" /> : <SunIcon size={15} weight="fill" />}
    </button>
  );
}
