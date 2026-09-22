import { CheckCircleIcon, CircleNotchIcon, CircleIcon } from '@phosphor-icons/react';
import { Panel } from '../../components/ui/Panel';
import type { AnalyzeProgress as Progress } from '../../hooks/useAnalyze';
import { useLanguage } from '../../i18n';

interface AnalyzeProgressProps {
  progress: Progress;
  elapsedSeconds: number;
}

/**
 * Live progress for the analyze stream.
 *
 * Steps are derived from the event payload rather than kept in their own
 * state, so the display cannot drift out of sync with the backend.
 */
export function AnalyzeProgress({ progress, elapsedSeconds }: AnalyzeProgressProps) {
  const { t } = useLanguage();
  const steps = [t.progress.step1, t.progress.step2, t.progress.step3, t.progress.step4];

  return (
    <Panel
      title={t.progress.title}
      subtitle={progress.stage || t.progress.starting}
      actions={
        <span className="tabular font-mono text-xs text-ink-faint">{elapsedSeconds}s</span>
      }
    >
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3"
        role="progressbar"
        aria-valuenow={progress.overallProgress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={t.progress.overall}
      >
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500"
          style={{ width: `${progress.overallProgress}%` }}
        />
      </div>

      <ol className="mt-4 grid gap-2">
        {steps.map((label, i) => {
          const stepNum = i + 1;
          const done = progress.step > stepNum;
          const active = progress.step === stepNum;
          return (
            <li key={label} className="flex items-center gap-2.5 text-sm">
              {done ? (
                <CheckCircleIcon size={16} weight="fill" className="shrink-0 text-positive" />
              ) : active ? (
                <CircleNotchIcon size={16} className="shrink-0 animate-spin text-accent" />
              ) : (
                <CircleIcon size={16} className="shrink-0 text-ink-faint" />
              )}
              <span className={done || active ? 'text-ink' : 'text-ink-faint'}>{label}</span>
              {active && progress.stepProgress > 0 && (
                <span className="tabular ml-auto font-mono text-xs text-ink-faint">
                  {progress.stepProgress}%
                </span>
              )}
            </li>
          );
        })}
      </ol>

      {progress.detail && (
        <p className="mt-4 border-t border-hairline pt-3 text-xs text-ink-dim">
          {progress.detail}
        </p>
      )}
    </Panel>
  );
}
