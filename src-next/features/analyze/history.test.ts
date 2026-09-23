import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listHistory, removeFromHistory } from './analysisCache';

/** A minimal localStorage, since Vitest runs in Node by default. */
function fakeStorage() {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    key: (i: number) => [...map.keys()][i] ?? null,
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
    _map: map,
  };
}

const PREFIX = 'xoraclips_cache_';
// timeKey() swaps the cache prefix for this one, so the timestamp key is
// `xoraclips_ts_<id>`, not the time prefix plus the whole cache key.
const TIME = 'xoraclips_ts_';

function seed(store: ReturnType<typeof fakeStorage>, id: string, over: Record<string, unknown> = {}) {
  store.setItem(
    `${PREFIX}${id}`,
    JSON.stringify({
      video_id: id,
      title: `Video ${id}`,
      duration: 100,
      heatmap: [],
      summary: '',
      clips: [{ id: 'c1', title: 'a', start_time: 0, end_time: 5, virality_score: 1, key_quotes: [], transcript: '' }],
      ...over,
    }),
  );
}

let store: ReturnType<typeof fakeStorage>;

beforeEach(() => {
  store = fakeStorage();
  vi.stubGlobal('localStorage', store);
});

describe('listHistory', () => {
  it('is empty when nothing is cached', () => {
    expect(listHistory()).toEqual([]);
  });

  it('lists a cached analysis with its clip count', () => {
    seed(store, 'abc');
    const out = listHistory();
    expect(out).toHaveLength(1);
    expect(out[0].videoId).toBe('abc');
    expect(out[0].title).toBe('Video abc');
    expect(out[0].clipCount).toBe(1);
  });

  it('ignores keys that are not analysis caches', () => {
    seed(store, 'abc');
    store.setItem('xoraclips_language', 'id');
    store.setItem('unrelated', 'x');
    expect(listHistory()).toHaveLength(1);
  });

  it('skips a corrupt entry instead of losing the whole list', () => {
    seed(store, 'good');
    store.setItem(`${PREFIX}broken`, '{not json');
    const out = listHistory();
    expect(out).toHaveLength(1);
    expect(out[0].videoId).toBe('good');
  });

  it('skips an entry whose clips are missing', () => {
    store.setItem(`${PREFIX}x`, JSON.stringify({ video_id: 'x', title: 't' }));
    expect(listHistory()).toEqual([]);
  });

  it('sorts newest first', () => {
    seed(store, 'older');
    store.setItem(`${TIME}older`, '2024-01-01T00:00:00.000Z');
    seed(store, 'newer');
    store.setItem(`${TIME}newer`, '2025-06-01T00:00:00.000Z');

    expect(listHistory().map((e) => e.videoId)).toEqual(['newer', 'older']);
  });

  it('keeps entries that have no timestamp, at the end', () => {
    seed(store, 'dated');
    store.setItem(`${TIME}dated`, '2025-01-01T00:00:00.000Z');
    seed(store, 'undated');

    const out = listHistory();
    expect(out).toHaveLength(2);
    expect(out[0].videoId).toBe('dated');
    expect(out[1].savedAt).toBeNull();
  });

  it('falls back to the video id when there is no title', () => {
    seed(store, 'noTitle', { title: '' });
    expect(listHistory()[0].title).toBe('noTitle');
  });

  it('returns empty rather than throwing when storage is blocked', () => {
    vi.stubGlobal('localStorage', {
      get length(): number {
        throw new Error('blocked');
      },
      key: () => null,
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
    });
    expect(listHistory()).toEqual([]);
  });
});

describe('removeFromHistory', () => {
  it('drops the entry and its timestamp', () => {
    seed(store, 'gone');
    store.setItem(`${TIME}gone`, '2025-01-01T00:00:00.000Z');

    removeFromHistory(`${PREFIX}gone`);

    expect(listHistory()).toEqual([]);
    expect(store.getItem(`${TIME}gone`)).toBeNull();
  });

  it('leaves other entries alone', () => {
    seed(store, 'keep');
    seed(store, 'drop');
    removeFromHistory(`${PREFIX}drop`);
    expect(listHistory().map((e) => e.videoId)).toEqual(['keep']);
  });

  it('does nothing for a key that is not there', () => {
    seed(store, 'keep');
    expect(() => removeFromHistory(`${PREFIX}missing`)).not.toThrow();
    expect(listHistory()).toHaveLength(1);
  });
});
