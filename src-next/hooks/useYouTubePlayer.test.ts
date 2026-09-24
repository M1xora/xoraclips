import { describe, expect, it } from 'vitest';
import { planMove } from './useYouTubePlayer';
import { PLAYER_STATE } from '../lib/youtubeApi';

const { PLAYING, PAUSED, BUFFERING, CUED, ENDED } = PLAYER_STATE;

describe('planMove (#40)', () => {
  it.each([PLAYING, PAUSED, BUFFERING])('seeks a video that has played (state %i)', (state) => {
    expect(planMove(state, 10, 154, null)).toBe('seek');
  });

  it.each([-1, CUED, ENDED])('never seeks a video that has not played (state %i): that would start it', (state) => {
    expect(planMove(state, 10, 154, null)).toBe('cue');
  });

  it('sends no cue to a fresh player already at the clip start', () => {
    // Created with playerVars.start = 154 for a clip at 154.6.
    expect(planMove(-1, 154, 154.6, null)).toBe('none');
  });

  it('sends no second cue for the same spot (a late cue would stop playback)', () => {
    expect(planMove(CUED, 154, 424, 424)).toBe('none');
    expect(planMove(CUED, 154, 470, 424)).toBe('cue');
  });
});
