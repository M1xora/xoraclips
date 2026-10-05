import { useCallback, useMemo, useState } from 'react';
import { ClockCounterClockwiseIcon, TrashIcon } from '@phosphor-icons/react';
import { Panel } from '../../components/ui/Panel';
import { useLanguage } from '../../i18n';
import { listHistory, removeFromHistory, type HistoryEntry } from './analysisCache';

interface HistoryPanelProps {
  /** Bumped by the caller after an analysis, to re-read the list. */
  refreshToken: number;
  onOpen: (entry: HistoryEntry) => void;
}

/**
 * Past analyses, read straight out of the cache.
 *
 * Every analysis is already cached to avoid spending Gemini quota twice, but
 * until now there was no way to reach an older one: the only route back was
 * pasting the same URL with the same settings. This lists what is there.
 */
export function HistoryPanel({ refreshToken, onOpen }: HistoryPanelProps) {
  const { t } = useLanguage();
  const [query, setQuery] = useState('');
  const [entries, setEntries] = useState(listHistory);

  // Re-read when an analysis finishes (a new token, checked while rendering)
  // or an entry is dropped (in the handler).
  const [seenToken, setSeenToken] = useState(refreshToken);
  if (refreshToken !== seenToken) {
    setSeenToken(refreshToken);
    setEntries(listHistory());
  }

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter(
      (e) => e.title.toLowerCase().includes(q) || e.videoId.toLowerCase().includes(q),
    );
  }, [entries, query]);

  const drop = useCallback((key: string) => {
    removeFromHistory(key);
    setEntries(listHistory());
  }, []);

  if (entries.length === 0) {
    return (
      <Panel title={t.results.historyTitle} className="border-2 border-line">
        <div className="flex items-center gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-full border-2 border-line bg-lavender-muted text-ink">
            <ClockCounterClockwiseIcon size={18} weight="bold" />
          </span>
          <p className="text-xs text-ink-faint">{t.results.historyEmpty}</p>
        </div>
      </Panel>
    );
  }

  return (
    <Panel title={t.results.historyTitle} subtitle={t.results.historyHint} className="border-2 border-line">
      <div className="grid gap-2">
        {/* Only worth searching once the list is long enough to scroll. */}
        {entries.length > 4 && (
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.results.historySearch}
            aria-label={t.results.historySearch}
            className="h-8 w-full rounded-[--radius-control] border border-hairline bg-surface-2
              px-2.5 text-xs text-ink placeholder:text-ink-faint"
          />
        )}

        {shown.length === 0 ? (
          <p className="text-xs text-ink-faint">{t.results.historyNoMatch}</p>
        ) : (
          <ul className="grid max-h-72 gap-1.5 overflow-y-auto">
            {shown.map((e) => (
              <li
                key={e.key}
                className="flex items-center gap-2 rounded-[--radius-control] border
                  border-hairline bg-surface-2 px-2.5 py-2"
              >
                <ClockCounterClockwiseIcon size={14} className="shrink-0 text-ink-dim" />

                <button
                  type="button"
                  onClick={() => onOpen(e)}
                  className="pressable min-w-0 flex-1 text-left"
                  title={t.results.historyOpen}
                >
                  <span className="block truncate text-xs font-medium">{e.title}</span>
                  <span className="block truncate text-[0.76rem] text-ink-faint">
                    {t.results.historyClips(e.clipCount)}
                    {e.savedAt ? ` · ${new Date(e.savedAt).toLocaleDateString()}` : ''}
                  </span>
                </button>

                <button
                  type="button"
                  onClick={() => drop(e.key)}
                  aria-label={t.results.historyRemove}
                  title={t.results.historyRemove}
                  className="pressable grid size-7 shrink-0 place-items-center rounded
                    text-ink-faint hover:bg-surface-3 hover:text-critical-text"
                >
                  <TrashIcon size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}
