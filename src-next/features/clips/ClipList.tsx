import { useMemo, useState } from 'react';
import { MagnifyingGlassIcon } from '@phosphor-icons/react';
import { ClipCard } from './ClipCard';
import { Sticker } from '../../components/ui/Sticker';
import type { ViralClip } from '../../lib/types';
import { useLanguage } from '../../i18n';

type Filter = 'all' | 'high' | 'mid' | 'marked';
type Sort = 'score' | 'time' | 'duration';

interface ClipListProps {
  clips: ViralClip[];
  marked: Record<string, boolean>;
  activeId: string | null;
  onToggleMark: (clip: ViralClip) => void;
  onSelect: (clip: ViralClip) => void;
  onPreview: (clip: ViralClip) => void;
  onTrim: (clip: ViralClip) => void;
  onCopy: (text: string, label: string) => void;
}

export function ClipList({
  clips,
  marked,
  activeId,
  onToggleMark,
  onSelect,
  onPreview,
  onTrim,
  onCopy,
}: ClipListProps) {
  const { t } = useLanguage();
  const [query, setQuery] = useState('');

  const filters: { value: Filter; label: string }[] = [
    { value: 'all', label: t.results.filterAll },
    { value: 'high', label: t.results.filterHigh },
    { value: 'mid', label: t.results.filterMid },
    { value: 'marked', label: t.results.filterMarked },
  ];

  const sorts: { value: Sort; label: string }[] = [
    { value: 'score', label: t.results.sortScore },
    { value: 'time', label: t.results.sortTime },
    { value: 'duration', label: t.results.sortDuration },
  ];
  const [filter, setFilter] = useState<Filter>('all');
  const [sort, setSort] = useState<Sort>('score');

  // Derived, not stored: filters cannot go stale against the clip list.
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();

    const filtered = clips.filter((c) => {
      if (q && !`${c.title} ${c.transcript ?? ''}`.toLowerCase().includes(q)) return false;
      if (filter === 'high') return c.virality_score >= 90;
      if (filter === 'mid') return c.virality_score < 90;
      if (filter === 'marked') return Boolean(marked[c.id]);
      return true;
    });

    const sorted = [...filtered];
    if (sort === 'score') sorted.sort((a, b) => b.virality_score - a.virality_score);
    if (sort === 'time') sorted.sort((a, b) => a.start_time - b.start_time);
    if (sort === 'duration') {
      sorted.sort((a, b) => b.end_time - b.start_time - (a.end_time - a.start_time));
    }
    return sorted;
  }, [clips, query, filter, sort, marked]);

  const markedCount = useMemo(
    () => clips.filter((c) => marked[c.id]).length,
    [clips, marked],
  );

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-40 flex-1">
          <MagnifyingGlassIcon
            size={14}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.results.searchPlaceholder}
            aria-label={t.results.searchPlaceholder}
            className="h-8 w-full rounded-[--radius-control] border-2 border-line bg-surface
              pl-8 pr-2.5 text-xs text-ink placeholder:text-ink-faint"
          />
        </div>

        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as Filter)}
          aria-label={t.results.filterLabel}
          className="h-8 rounded-[--radius-control] border-2 border-line bg-surface
            px-2 text-xs text-ink"
        >
          {filters.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>

        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
          aria-label={t.results.sortLabel}
          className="h-8 rounded-[--radius-control] border-2 border-line bg-surface
            px-2 text-xs text-ink"
        >
          {sorts.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

      <p className="tabular text-xs text-ink-faint">
        {t.results.showing(visible.length, clips.length)}
        {markedCount > 0 && ` · ${t.results.markedCount(markedCount)}`}
      </p>

      {visible.length === 0 ? (
        <div className="grid justify-items-center gap-3 rounded-[--radius-panel] border-2 border-dashed
          border-line bg-lavender-muted p-8 text-center">
          <Sticker icon={<MagnifyingGlassIcon size={22} weight="bold" />} tone="pink" size="lg" tilt />
          <p className="text-sm font-bold">{t.results.emptyTitle}</p>
          <p className="mt-1 text-xs text-ink-dim">{t.results.emptyHint}</p>
        </div>
      ) : (
        <div className="grid gap-2.5">
          {visible.map((clip, i) => (
            <ClipCard
              key={clip.id}
              clip={clip}
              index={i}
              marked={Boolean(marked[clip.id])}
              active={activeId === clip.id}
              onToggleMark={() => onToggleMark(clip)}
              onSelect={() => onSelect(clip)}
              onPreview={() => onPreview(clip)}
              onTrim={() => onTrim(clip)}
              onCopy={onCopy}
            />
          ))}
        </div>
      )}
    </div>
  );
}
