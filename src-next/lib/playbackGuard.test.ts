import { afterEach, describe, expect, it, vi } from 'vitest';
import { pauseOthers, registerPlayer } from './playbackGuard';

const offs: (() => void)[] = [];
afterEach(() => {
  // The registry is module-level: clean up even when an assertion failed.
  while (offs.length) offs.pop()?.();
});

function player(muted = false) {
  const p = { pauseVideo: vi.fn(), isMuted: () => muted };
  offs.push(registerPlayer(p));
  return p;
}

describe('playbackGuard (#40)', () => {
  it('a player with sound pauses the others with sound', () => {
    const source = player();
    const preview = player();
    pauseOthers(preview);
    expect(source.pauseVideo).toHaveBeenCalledOnce();
    expect(preview.pauseVideo).not.toHaveBeenCalled();
  });

  it('a muted player starting pauses nothing', () => {
    const source = player();
    const preview = player(true);
    pauseOthers(preview);
    expect(source.pauseVideo).not.toHaveBeenCalled();
  });

  it('a muted player is not paused by one with sound', () => {
    const preview = player(true);
    const source = player();
    pauseOthers(source);
    expect(preview.pauseVideo).not.toHaveBeenCalled();
  });

  it('forgets a player once it is removed', () => {
    const gone = { pauseVideo: vi.fn(), isMuted: () => false };
    registerPlayer(gone)();
    pauseOthers(player());
    expect(gone.pauseVideo).not.toHaveBeenCalled();
  });

  it('survives a player that throws while being torn down', () => {
    offs.push(registerPlayer({ pauseVideo: () => { throw new Error('destroyed'); } }));
    const ok = player();
    expect(() => pauseOthers({ pauseVideo: vi.fn() })).not.toThrow();
    expect(ok.pauseVideo).toHaveBeenCalledOnce();
  });
});
