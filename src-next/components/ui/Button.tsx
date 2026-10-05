import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { CircleNotchIcon } from '@phosphor-icons/react';

type Variant = 'primary' | 'secondary' | 'teal' | 'ghost' | 'danger' | 'brand';
type Size = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

/**
 * Variants.
 *
 * The previous set was five flat fills with no depth, so the primary action
 * and a destructive one carried the same visual weight, and secondary was
 * hard to tell from ghost. Three things fix that:
 *
 *   Hierarchy  primary gets a top highlight and a lifted shadow so it reads
 *              as raised; secondary keeps a border but no shadow; ghost has
 *              neither. The eye can rank them without reading the label.
 *   Depth      an inset top highlight plus a tinted (never black) shadow,
 *              which is what makes a fill look like a surface rather than a
 *              coloured rectangle.
 *   Feedback   hover lifts 1px, active presses 1px past rest and drops the
 *              shadow, so the click has somewhere to travel.
 *
 * Contrast is measured, not assumed: white on the blue fill is 4.65:1 in
 * dark and 5.85:1 in light, white on teal 5.19:1, white on red 5.30:1.
 */
const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-accent text-on-accent shadow-[inset_0_1px_0_rgb(255_255_255/.18),0_1px_2px_rgb(0_0_0/.28)] ' +
    'hover:bg-accent-bright hover:shadow-[inset_0_1px_0_rgb(255_255_255/.22),0_2px_6px_rgb(0_0_0/.3)] ' +
    'active:shadow-[inset_0_1px_2px_rgb(0_0_0/.22)]',
  secondary:
    'bg-surface-2 text-ink border border-hairline ' +
    'hover:bg-surface-3 hover:border-ink-faint/40',
  teal:
    'bg-teal text-on-teal shadow-[inset_0_1px_0_rgb(255_255_255/.16),0_1px_2px_rgb(0_0_0/.28)] ' +
    'hover:bg-teal-bright active:shadow-[inset_0_1px_2px_rgb(0_0_0/.22)]',
  ghost: 'bg-transparent text-ink-dim hover:bg-surface-2 hover:text-ink',
  danger:
    'bg-critical text-on-critical shadow-[inset_0_1px_0_rgb(255_255_255/.16),0_1px_2px_rgb(0_0_0/.28)] ' +
    'hover:bg-critical-bright active:shadow-[inset_0_1px_2px_rgb(0_0_0/.22)]',
  // Neo-brutal: 2px line and a hard offset shadow. Pressing slides the
  // button onto its shadow; pressable-btn already moves it 1px down,
  // the translate adds the rest so it lands 3px right and 3px down.
  brand:
    'bg-brand text-on-brand border-2 border-line shadow-brutal hover:bg-brand-bright ' +
    'active:shadow-none motion-safe:active:translate-x-[3px] motion-safe:active:translate-y-[2px]',
};

/**
 * Heights follow the 32/40/48 rule: 28px was below a comfortable click
 * target, and a tool used for hours should not ask for precision.
 */
const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-10 px-4 text-sm gap-2',
  lg: 'h-12 px-6 text-[0.95rem] gap-2',
};

/**
 * Button with loading and pressed states.
 *
 * `loading` also disables the button so a second submit cannot be fired
 * while a request is in flight.
 */
export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  children,
  className = '',
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`pressable-btn inline-flex shrink-0 items-center justify-center
        whitespace-nowrap rounded-[--radius-button] font-display font-semibold
        disabled:pointer-events-none disabled:opacity-40 disabled:shadow-none
        ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
    >
      {loading ? <CircleNotchIcon className="animate-spin" size={16} weight="bold" /> : icon}
      {children}
    </button>
  );
}
