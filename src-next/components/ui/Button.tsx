import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { CircleNotchIcon } from '@phosphor-icons/react';

type Variant = 'primary' | 'secondary' | 'teal' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

/**
 * Variants, drawn neo-brutal (#88).
 *
 * Every filled variant carries a 2px line and a hard offset shadow; pressing
 * drops the shadow and pressable-btn slides the button onto where it was, so
 * a click has somewhere to travel. Hierarchy comes from the fill and the
 * shadow size: primary is orange on the full shadow, secondary, teal and
 * danger sit on the small one, ghost has neither.
 *
 * Contrast is measured, not assumed: dark text on orange is 6.60:1, on green
 * 9.04:1, white on red 5.30:1. The orange fill itself is only 2.6:1 against
 * the light canvas, which is why the line border is part of every variant.
 */
const VARIANTS: Record<Variant, string> = {
  primary:
    'border-2 border-line bg-accent text-on-accent shadow-brutal hover:bg-accent-bright',
  secondary:
    'border-2 border-line bg-surface text-ink shadow-brutal-sm hover:bg-surface-2',
  teal:
    'border-2 border-line bg-teal text-on-teal shadow-brutal-sm hover:bg-teal-bright',
  ghost: 'border-2 border-transparent bg-transparent text-ink-dim hover:bg-surface-2 hover:text-ink',
  danger:
    'border-2 border-line bg-critical text-on-critical shadow-brutal-sm hover:bg-critical-bright',
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
        whitespace-nowrap rounded-[--radius-button] font-display font-bold
        active:shadow-none disabled:pointer-events-none disabled:border-dashed
        disabled:opacity-50 disabled:shadow-none
        ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
    >
      {loading ? <CircleNotchIcon className="animate-spin" size={16} weight="bold" /> : icon}
      {children}
    </button>
  );
}
