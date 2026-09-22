import type { ReactNode } from 'react';

interface PanelProps {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * Bordered content group.
 *
 * Uses <section> with a heading rather than a bare div, so the page outline
 * is navigable. Separation comes from a 1px border, not a drop shadow.
 */
export function Panel({ title, subtitle, actions, children, className = '' }: PanelProps) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-hairline px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="font-display text-sm font-semibold">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-faint">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}
