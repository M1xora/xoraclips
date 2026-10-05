import type { ReactNode } from 'react';

type Tone = 'accent' | 'teal' | 'yellow' | 'pink' | 'sky';
type Size = 'sm' | 'md' | 'lg';

interface StickerProps {
  icon: ReactNode;
  tone?: Tone;
  size?: Size;
  /** Tilt it a few degrees, like a sticker slapped on by hand. */
  tilt?: boolean;
  className?: string;
}

/*
 * Every tone is a fill that stays the same in both modes, so the icon is
 * always dark (text-on-accent): 6.60:1 on orange is the weakest of them.
 */
const TONES: Record<Tone, string> = {
  accent: 'bg-accent',
  teal: 'bg-teal',
  yellow: 'bg-pop-yellow',
  pink: 'bg-pop-pink',
  sky: 'bg-pop-sky',
};

const SIZES: Record<Size, string> = {
  sm: 'size-8',
  md: 'size-10',
  lg: 'size-14',
};

/**
 * Round icon badge, the pop-art stand-in for an illustration.
 *
 * The app has no drawn artwork, so empty states and the brand mark use a
 * Phosphor icon in an outlined, coloured circle instead (#88). Decorative:
 * whatever it marks must also be said in text next to it.
 */
export function Sticker({ icon, tone = 'accent', size = 'md', tilt = false, className = '' }: StickerProps) {
  return (
    <span
      aria-hidden="true"
      className={`grid shrink-0 place-items-center rounded-full border-2 border-line
        text-on-accent shadow-brutal-sm ${TONES[tone]} ${SIZES[size]}
        ${tilt ? '-rotate-6' : ''} ${className}`}
    >
      {icon}
    </span>
  );
}
