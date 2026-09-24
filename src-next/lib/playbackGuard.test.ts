import { describe, expect, it, vi } from 'vitest';
import { pauseOthers, registerPlayer } from './playbackGuard';

const player = () => ({ pauseVideo: vi.fn() });

describe('playbackGuard (#40)', () => {
  it('pauses the other players, not the one that started', () => {
    const source = player();
    const preview = player();
    const offA = registerPlayer(source);
    const offB = registerPlayer(preview);
    pauseOthers(preview);
    expect(source.pauseVideo).toHaveBeenCalledOnce();
    expect(preview.pauseVideo).not.toHaveBeenCalled();
    offA();
    offB();
  });

  it('forgets a player once it is removed', () => {
    const gone = player();
    const live = player();
    registerPlayer(gone)();
    const off = registerPlayer(live);
    pauseOthers(live);
    expect(gone.pauseVideo).not.toHaveBeenCalled();
    off();
  });

  it('survives a player that throws while being torn down', () => {
    const broken = { pauseVideo: () => { throw new Error('destroyed'); } };
    const ok = player();
    const offA = registerPlayer(broken);
    const offB = registerPlayer(ok);
    expect(() => pauseOthers(player())).not.toThrow();
    expect(ok.pauseVideo).toHaveBeenCalledOnce();
    offA();
    offB();
  });
});
