import { useMemo } from 'react';
import {
  CheckCircleIcon,
  CircleNotchIcon,
  DownloadSimpleIcon,
  FileZipIcon,
  PlugsConnectedIcon,
  WarningCircleIcon,
  XIcon,
} from '@phosphor-icons/react';
import { Button } from '../../components/ui/Button';
import { Panel } from '../../components/ui/Panel';
import { friendlyError, type RecoveryAction } from './errorMessages';
import { downloadNoteText } from './downloadNote';
import { outputFileName } from './renderPayload';
import { useLanguage } from '../../i18n';
import type { BatchRenderProgress } from '../../lib/types';

interface RenderQueueProps {
  progress: BatchRenderProgress | null;
  lostContact: boolean;
  fileNamePrefix: string;
  fileNameSuffix: string;
  onReconnect: () => void;
  onDismiss: () => void;
  onRecover: (action: RecoveryAction) => void;
}

export function RenderQueue({
  progress,
  lostContact,
  fileNamePrefix,
  fileNameSuffix,
  onReconnect,
  onDismiss,
  onRecover,
}: RenderQueueProps) {
  const { t } = useLanguage();

  // Names are worked out once per render so duplicates number consistently.
  const names = useMemo(() => {
    const seen = new Map<string, number>();
    return (progress?.clips ?? []).map((c) =>
      outputFileName(c.base_title || c.title, fileNamePrefix, fileNameSuffix, seen),
    );
  }, [progress?.clips, fileNamePrefix, fileNameSuffix]);

  if (!progress) return null;

  const done = progress.clips.filter((c) => c.status === 'completed').length;
  const failed = progress.clips.filter((c) => c.status === 'error').length;
  const total = progress.total_clips || progress.clips.length || 1;
  const pct = Math.round((done / total) * 100);
  const finished = progress.overall_status !== 'running';

  return (
    <Panel
      title={t.render.queue}
      subtitle={
        finished
          ? failed > 0
            ? t.render.someFailed(failed, total)
            : t.render.allDone(done)
          : t.render.working(done + 1, total)
      }
      actions={
        <div className="flex items-center gap-1.5">
          {done > 0 && (
            <a
              href={progress.zip_url ?? `/api/download-batch-zip/${progress.batch_id}`}
              download
              className="pressable inline-flex h-7 items-center gap-1.5 rounded-[--radius-control]
                bg-accent px-2.5 text-xs font-semibold text-on-accent hover:bg-accent-bright"
            >
              <FileZipIcon size={13} />
              ZIP
            </a>
          )}
          {finished && (
            <button
              type="button"
              onClick={onDismiss}
              aria-label={t.common.dismiss}
              className="pressable grid size-7 place-items-center rounded-[--radius-control]
                text-ink-faint hover:bg-surface-2 hover:text-ink"
            >
              <XIcon size={13} weight="bold" />
            </button>
          )}
        </div>
      }
    >
      {lostContact && (
        <div className="mb-3 flex items-start gap-2.5 rounded-[--radius-control]
          border-2 border-caution/60 bg-caution/10 p-3">
          <PlugsConnectedIcon size={16} className="mt-0.5 shrink-0 text-caution" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium text-caution">{t.render.lostContact}</p>
            <p className="mt-1 text-xs text-ink-dim">{t.render.lostContactHint}</p>
            <Button variant="secondary" size="sm" className="mt-2" onClick={onReconnect}>
              {t.render.reconnect}
            </Button>
          </div>
        </div>
      )}

      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={t.render.queue}
      >
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>

      <ul className="mt-3 divide-y divide-hairline">
        {progress.clips.map((clip, i) => {
          const err =
            clip.status === 'error'
              ? friendlyError(clip.error_message || clip.error || '', t.render.errors)
              : null;
          const note = clip.status === 'downloading' ? downloadNoteText(clip.download_note, t) : null;

          return (
            <li key={`${clip.clip_index}-${clip.title}`} className="py-2.5">
              <div className="flex items-center gap-2.5">
                {clip.status === 'completed' ? (
                  <CheckCircleIcon size={15} weight="fill" className="shrink-0 text-positive" />
                ) : clip.status === 'error' ? (
                  <WarningCircleIcon size={15} weight="fill" className="shrink-0 text-critical-text" />
                ) : clip.status === 'pending' ? (
                  <span className="size-[15px] shrink-0 rounded-full border-2 border-hairline" />
                ) : (
                  <CircleNotchIcon size={15} className="shrink-0 animate-spin text-accent" />
                )}

                <span className="min-w-0 flex-1 truncate text-xs">{clip.title}</span>

                {clip.status === 'completed' && clip.download_url ? (
                  <a
                    href={`${clip.download_url}${clip.download_url.includes('?') ? '&' : '?'}title=${encodeURIComponent(names[i] ?? clip.title)}`}
                    download
                    className="pressable inline-flex items-center gap-1 rounded px-1.5 py-1
                      text-[0.8rem] text-teal-text hover:bg-surface-2"
                  >
                    <DownloadSimpleIcon size={12} />
                    MP4
                  </a>
                ) : (
                  <span className="tabular shrink-0 font-mono text-[0.8rem] text-ink-faint">
                    {clip.progress_percent}%
                  </span>
                )}
              </div>

              {note && (
                <p className="mt-1 pl-[25px] text-[0.8rem] text-ink-faint" role="status">
                  {note}
                </p>
              )}

              {err && (
                <div className="mt-1.5 pl-[25px]">
                  <p className="text-[0.8rem] text-critical-text">{err.message}</p>
                  {err.action && (
                    <Button
                      variant="secondary"
                      size="sm"
                      className="mt-1.5"
                      onClick={() => onRecover(err.action)}
                    >
                      {t.render.recover[err.action]}
                    </Button>
                  )}
                  <details className="mt-1.5">
                    <summary className="cursor-pointer text-[0.8rem] text-ink-faint hover:text-ink-dim">
                      {t.errors.technicalDetail}
                    </summary>
                    <pre className="mt-1 max-h-24 overflow-auto rounded bg-surface-2 p-2
                      font-mono text-[0.76rem] text-ink-dim">
                      {err.raw}
                    </pre>
                  </details>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
