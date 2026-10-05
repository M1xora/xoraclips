import { Component, type ErrorInfo, type ReactNode } from 'react';
import { ArrowClockwiseIcon, WarningOctagonIcon } from '@phosphor-icons/react';

interface Props {
  /** Shown in the fallback so the user knows which part failed. */
  section: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Keeps one failing section from blanking the whole page.
 *
 * Neither the old frontend nor src-next had a boundary, so a single render
 * error threw away an analysis that took minutes to produce. Each major
 * section gets its own, so a broken preview does not cost the results.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.section}] render failed:`, error, info.componentStack);
  }

  private reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <section
        role="alert"
        className="panel border-critical/40 p-5"
        aria-label={`${this.props.section} failed`}
      >
        <div className="flex items-start gap-3">
          <WarningOctagonIcon size={18} weight="fill" className="mt-0.5 shrink-0 text-critical-text" />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold text-critical-text">
              {this.props.section} tidak bisa ditampilkan
            </h2>
            <p className="mt-1 text-xs text-ink-dim">
              Bagian lain di halaman ini masih berfungsi. Hasil analisis kamu tidak hilang.
            </p>

            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-ink-faint hover:text-ink-dim">
                Detail teknis
              </summary>
              <pre className="mt-2 max-h-40 overflow-auto rounded-[--radius-control] bg-surface-2 p-2.5 font-mono text-[0.8rem] text-ink-dim">
                {error.message}
              </pre>
            </details>

            <button
              type="button"
              onClick={this.reset}
              className="pressable mt-3 inline-flex items-center gap-1.5 rounded-[--radius-control]
                border-2 border-hairline bg-surface-2 px-3 py-1.5 text-xs font-medium
                hover:bg-surface-3"
            >
              <ArrowClockwiseIcon size={13} />
              Coba muat ulang bagian ini
            </button>
          </div>
        </div>
      </section>
    );
  }
}
