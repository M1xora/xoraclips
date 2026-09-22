import { useCallback, useEffect, useState } from 'react';
import {
  ArrowClockwiseIcon,
  BracketsCurlyIcon,
  ClockIcon,
  CopyIcon,
  DownloadSimpleIcon,
  FileTextIcon,
  HardDrivesIcon,
  SubtitlesIcon,
  TrashIcon,
} from '@phosphor-icons/react';
import { Button } from '../../components/ui/Button';
import { Panel } from '../../components/ui/Panel';
import { api, type TempStorageInfo } from '../../api/client';
import { useLanguage } from '../../i18n';
import { useRawDownload } from '../download/useRawDownload';
import {
  buildJson,
  buildMarkdown,
  buildSrt,
  clipTitle,
  downloadText,
  formatTimestamps,
  safeFileName,
  type TimestampFormat,
} from './exporters';
import type { AnalyzeResponse, ViralClip } from '../../lib/types';

interface ToolsPanelProps {
  result: AnalyzeResponse;
  /** The clip an SRT or a raw clip download applies to. */
  activeClip: ViralClip | null;
  videoUrl: string;
  onNotice: (message: string, tone?: 'info' | 'error') => void;
}

/**
 * Getting work out of the app: export files, copy timestamps, download the
 * untouched video, and see what the temp folder is holding.
 *
 * All four existed in the backend but had no way in from the new UI.
 */
export function ToolsPanel({ result, activeClip, videoUrl, onNotice }: ToolsPanelProps) {
  const { t } = useLanguage();
  const raw = useRawDownload((msg) => onNotice(msg, 'error'));

  const base = safeFileName(result.title || result.video_id, result.video_id);
  const hasTranscript = (result.transcript?.length ?? 0) > 0;

  const copy = useCallback(
    async (format: TimestampFormat) => {
      try {
        await navigator.clipboard.writeText(formatTimestamps(result.clips, format));
        onNotice(t.tools.copied);
      } catch {
        onNotice(t.tools.copyFailed, 'error');
      }
    },
    [result.clips, onNotice, t.tools],
  );

  const srtForClip = useCallback(() => {
    if (!hasTranscript) return onNotice(t.tools.noTranscript, 'error');
    if (!activeClip) return onNotice(t.tools.pickClipForSrt, 'error');
    const name = safeFileName(clipTitle(activeClip), 'clip');
    downloadText(buildSrt(result.transcript ?? [], activeClip), `${name}.srt`, 'text/plain');
  }, [hasTranscript, activeClip, result.transcript, onNotice, t.tools]);

  return (
    <Panel title={t.tools.title}>
      <div className="grid gap-5">
        {/* ------------------------------------------------------- export */}
        <div>
          <span className="text-xs font-medium text-ink-dim">{t.tools.exportGroup}</span>
          <div className="mt-1.5 grid gap-1.5 sm:grid-cols-3">
            <ToolButton
              icon={<BracketsCurlyIcon size={14} />}
              label={t.tools.exportJson}
              sub={t.tools.exportJsonSub}
              onClick={() =>
                downloadText(buildJson(result), `${base}.json`, 'application/json')
              }
            />
            <ToolButton
              icon={<FileTextIcon size={14} />}
              label={t.tools.exportMarkdown}
              sub={t.tools.exportMarkdownSub}
              onClick={() =>
                downloadText(buildMarkdown(result), `${base}.md`, 'text/markdown')
              }
            />
            <ToolButton
              icon={<SubtitlesIcon size={14} />}
              label={t.tools.exportSrt}
              sub={t.tools.exportSrtSub}
              disabled={!hasTranscript || !activeClip}
              onClick={srtForClip}
            />
          </div>

          {hasTranscript ? (
            <button
              type="button"
              onClick={() =>
                downloadText(buildSrt(result.transcript ?? []), `${base}.srt`, 'text/plain')
              }
              className="pressable mt-1.5 text-[0.8rem] font-semibold text-ink-dim underline
                hover:text-ink"
            >
              {t.tools.exportSrtAll}
            </button>
          ) : (
            <p className="mt-1.5 text-[0.8rem] text-ink-faint">{t.tools.noTranscript}</p>
          )}
        </div>

        {/* --------------------------------------------------------- copy */}
        <div>
          <span className="text-xs font-medium text-ink-dim">{t.tools.copyGroup}</span>
          <div className="mt-1.5 grid gap-1.5 sm:grid-cols-3">
            <ToolButton
              icon={<ClockIcon size={14} />}
              label={t.tools.copyPlain}
              sub="00:10 - 00:30"
              onClick={() => void copy('plain')}
            />
            <ToolButton
              icon={<CopyIcon size={14} />}
              label={t.tools.copyTitled}
              sub="00:10 - 00:30 | Judul"
              onClick={() => void copy('titled')}
            />
            <ToolButton
              icon={<CopyIcon size={14} />}
              label={t.tools.copyChapters}
              sub="00:10 Judul"
              onClick={() => void copy('chapters')}
            />
          </div>
        </div>

        {/* ----------------------------------------------------- raw file */}
        <div>
          <span className="text-xs font-medium text-ink-dim">{t.tools.downloadGroup}</span>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Button
              size="sm"
              variant="secondary"
              disabled={raw.busy}
              onClick={() => void raw.startVideo(videoUrl, result.video_id, result.title)}
            >
              <DownloadSimpleIcon size={14} />
              {t.tools.downloadVideo}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={raw.busy || !activeClip}
              onClick={() =>
                activeClip &&
                void raw.startClip(videoUrl, result.video_id, activeClip, clipTitle(activeClip))
              }
            >
              <DownloadSimpleIcon size={14} />
              {t.tools.downloadClip}
            </Button>
          </div>

          <p className="mt-1.5 text-[0.8rem] text-ink-faint">{t.tools.downloadHint}</p>

          {raw.job && (
            <div className="mt-2 rounded-[--radius-control] border border-hairline bg-surface-2 p-2.5">
              {raw.job.status === 'ready' && raw.job.download_url ? (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 flex-1 truncate text-xs">{raw.job.filename}</span>
                  <a
                    href={raw.job.download_url}
                    download
                    onClick={() => raw.dismiss()}
                    className="pressable shrink-0 rounded-[--radius-control] bg-accent px-2.5 py-1
                      text-[0.8rem] font-semibold text-on-accent"
                  >
                    {t.tools.downloadSave}
                  </a>
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between gap-2 text-[0.8rem]">
                    <span className="text-ink-dim">{t.tools.downloading}</span>
                    <span className="tabular font-mono text-ink-dim">
                      {Math.round(raw.job.progress_percent)}%
                      {raw.job.speed ? ` · ${raw.job.speed}` : ''}
                      {raw.job.eta ? ` · ${raw.job.eta}` : ''}
                    </span>
                  </div>
                  <div className="mt-1.5 h-1 overflow-hidden rounded bg-surface-3">
                    <div
                      className="h-full bg-accent transition-[width]"
                      style={{ width: `${Math.min(100, raw.job.progress_percent)}%` }}
                    />
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* ------------------------------------------------------ storage */}
        <StorageRow onNotice={onNotice} />
      </div>
    </Panel>
  );
}

interface ToolButtonProps {
  icon: React.ReactNode;
  label: string;
  sub: string;
  disabled?: boolean;
  onClick: () => void;
}

function ToolButton({ icon, label, sub, disabled, onClick }: ToolButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="pressable flex items-center gap-2 rounded-[--radius-control] border
        border-hairline bg-surface-2 px-2.5 py-2 text-left hover:bg-surface-3
        disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-surface-2"
    >
      <span className="shrink-0 text-ink-dim">{icon}</span>
      <span className="min-w-0">
        <span className="block text-xs font-semibold">{label}</span>
        <span className="block truncate text-[0.76rem] text-ink-faint">{sub}</span>
      </span>
    </button>
  );
}

/**
 * How much the temp folder is holding, and a way to empty it.
 *
 * Worth surfacing because a full disk is one of the render failures the error
 * map points at, and until now the only cure was a button in a toast.
 */
function StorageRow({ onNotice }: { onNotice: (m: string, tone?: 'info' | 'error') => void }) {
  const { t } = useLanguage();
  const [info, setInfo] = useState<TempStorageInfo | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.temp
      .info()
      .then(setInfo)
      .catch(() => setInfo(null));
  }, []);

  useEffect(load, [load]);

  const clear = useCallback(async () => {
    setBusy(true);
    try {
      const res = await api.temp.clear();
      onNotice(
        res.cleared_files > 0 ? t.tools.storageCleared(res.cleared_files) : t.tools.storageEmpty,
      );
      load();
    } catch (err) {
      onNotice(err instanceof Error ? err.message : t.tools.downloadFailed, 'error');
    } finally {
      setBusy(false);
    }
  }, [onNotice, t.tools, load]);

  if (!info) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-[--radius-control]
      border border-hairline bg-surface-2 px-2.5 py-2">
      <span className="flex items-center gap-2 text-xs">
        <HardDrivesIcon size={14} className="text-ink-dim" />
        <span className="font-medium">{t.tools.storageGroup}</span>
        <span className="text-ink-faint">
          {info.formatted_size} · {t.tools.storageFiles(info.total_files)}
        </span>
      </span>

      <span className="flex items-center gap-1">
        <button
          type="button"
          onClick={load}
          className="pressable grid size-7 place-items-center rounded text-ink-dim
            hover:bg-surface-3 hover:text-ink"
          aria-label={t.tools.storageGroup}
        >
          <ArrowClockwiseIcon size={13} />
        </button>
        <Button size="sm" variant="secondary" loading={busy} onClick={() => void clear()}>
          <TrashIcon size={13} />
          {t.tools.storageClear}
        </Button>
      </span>
    </div>
  );
}
