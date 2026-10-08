import { WarningIcon } from '@phosphor-icons/react';
import type { AnalyzeNotice } from '../../hooks/useAnalyze';
import { formatTimecode } from '../../lib/format';
import { useLanguage } from '../../i18n';

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
 *
 * The backend sends both an English sentence and the numbers behind it. The
 * numbers are preferred, so the one message that asks the user to do something
 * is written in their own language; the sentence is the fallback for a stage
 * that carries no numbers.
 *
 * `role="alert"` rather than a live region: the list is mounted already
 * populated, and a live region inserted with its content in the same commit is
 * generally not announced. This follows the same shape as the API-key warning
 * in AnalyzeForm.
 */
export function AnalyzeNotices({ notices }: AnalyzeNoticesProps) {
  const { t } = useLanguage();
  if (notices.length === 0) return null;

  const title = (notice: AnalyzeNotice) => {
    if (notice.stage === 'Transcript Limit') return t.notices.transcriptLimit;
    if (notice.stage === 'Clip Count') return t.notices.clipCount;
    return notice.stage;
  };

  const body = (notice: AnalyzeNotice) => {
    if (notice.cutAt !== undefined && notice.unreadSeconds !== undefined) {
      return t.notices.transcriptLimitDetail(
        formatTimecode(notice.cutAt),
        formatTimecode(notice.unreadSeconds),
      );
    }
    return notice.detail;
  };

  return (
    <ul className="grid gap-2">
      {notices.map((notice) => (
        <li
          key={notice.stage}
          role="alert"
          className="flex items-start gap-2 rounded-[--radius-control] border-2 border-hairline bg-surface-2 p-3 text-sm"
        >
          <WarningIcon size={16} className="mt-0.5 shrink-0 text-critical-text" />
          <span>
            <strong className="font-semibold">{title(notice)}</strong>{' '}
            <span className="text-ink-dim">{body(notice)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
