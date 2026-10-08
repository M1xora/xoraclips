import { WarningIcon } from '@phosphor-icons/react';
import type { AnalyzeNotice } from '../../hooks/useAnalyze';

interface AnalyzeNoticesProps {
  notices: AnalyzeNotice[];
}

/**
 * Warnings the backend sent during the analysis that still matter once it is
 * done (issue #101): part of the video was never analysed, or fewer clips were
 * asked for than requested.
 *
 * These arrive as ordinary progress events, which overwrite each other in well
 * under a second, so without this the user never sees them — the analysis just
 * looks like it covered the whole video. They sit above the results, where the
 * user is looking when the run finishes.
 */
export function AnalyzeNotices({ notices }: AnalyzeNoticesProps) {
  if (notices.length === 0) return null;

  return (
    <ul className="grid gap-2" aria-live="polite">
      {notices.map((notice) => (
        <li
          key={notice.stage}
          className="flex items-start gap-2 rounded-lg border border-hairline bg-surface-2 px-3 py-2.5 text-xs leading-relaxed text-ink-dim"
        >
          <WarningIcon size={14} className="mt-0.5 shrink-0 text-critical-text" />
          <span>
            <span className="font-medium text-ink">{notice.stage}</span> — {notice.detail}
          </span>
        </li>
      ))}
    </ul>
  );
}
