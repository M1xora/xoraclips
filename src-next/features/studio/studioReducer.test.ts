import { describe, expect, it } from 'vitest';
import { initialStudioState, studioReducer, type StudioState } from './studioReducer';
import { getDefaultPositions } from './derive';

function run(actions: Parameters<typeof studioReducer>[1][], from = initialStudioState): StudioState {
  return actions.reduce(studioReducer, from);
}

describe('aspect ratio changes', () => {
  it('rewrites all three positions at once', () => {
    const next = studioReducer(initialStudioState, {
      type: 'setAspectRatio',
      ratio: '16:9',
      titleLines: 1,
    });
    const d = getDefaultPositions('16:9', 1);
    expect(next.titleYPercent).toBe(d.titleY);
    expect(next.subtitleYPercent).toBe(d.subtitleY);
    expect(next.subtitleCenterYPercent).toBe(d.subCenterY);
  });

  it('releases the title lock, so defaults apply again', () => {
    const next = run([
      { type: 'setTitleY', value: 40 },
      { type: 'setAspectRatio', ratio: '4:3', titleLines: 2 },
    ]);
    expect(next.isCustomTitleY).toBe(false);
    expect(next.titleYPercent).toBe(getDefaultPositions('4:3', 2).titleY);
  });

  it('uses the line count it was given', () => {
    const one = studioReducer(initialStudioState, { type: 'setAspectRatio', ratio: '1:1', titleLines: 1 });
    const three = studioReducer(initialStudioState, { type: 'setAspectRatio', ratio: '1:1', titleLines: 3 });
    expect(one.titleYPercent).not.toBe(three.titleYPercent);
  });
});

describe('title position lock', () => {
  it('moving the title sets the lock', () => {
    expect(studioReducer(initialStudioState, { type: 'setTitleY', value: 25 }).isCustomTitleY).toBe(true);
  });

  it('auto repositioning applies while unlocked', () => {
    const next = studioReducer(initialStudioState, { type: 'autoTitleY', value: 30 });
    expect(next.titleYPercent).toBe(30);
  });

  it('auto repositioning is ignored once locked', () => {
    const next = run([
      { type: 'setTitleY', value: 25 },
      { type: 'autoTitleY', value: 30 },
    ]);
    expect(next.titleYPercent).toBe(25);
  });

  it('returns the same object when nothing changes, avoiding a re-render', () => {
    const next = studioReducer(initialStudioState, {
      type: 'autoTitleY',
      value: initialStudioState.titleYPercent,
    });
    expect(next).toBe(initialStudioState);
  });

  it('reset clears the lock', () => {
    const next = run([
      { type: 'setTitleY', value: 40 },
      { type: 'resetPositions', titleLines: 1 },
    ]);
    expect(next.isCustomTitleY).toBe(false);
    expect(next.titleYPercent).toBe(getDefaultPositions('9:16', 1).titleY);
  });
});

describe('caption visibility', () => {
  it('remembers the style when switched off', () => {
    const next = run([
      { type: 'setCaptionStyle', style: 'fire_red' },
      { type: 'setCaptionsEnabled', enabled: false },
    ]);
    expect(next.captionStyle).toBe('none');
    expect(next.lastActiveCaptionStyle).toBe('fire_red');
  });

  it('restores that style when switched back on', () => {
    const next = run([
      { type: 'setCaptionStyle', style: 'cyber_violet' },
      { type: 'setCaptionsEnabled', enabled: false },
      { type: 'setCaptionsEnabled', enabled: true },
    ]);
    expect(next.captionStyle).toBe('cyber_violet');
  });

  it('picking none from the grid is restorable too', () => {
    // The original only remembered the style via the dropdown, not via the
    // "none" card, so that path lost the previous choice.
    const next = run([
      { type: 'setCaptionStyle', style: 'golden_aura' },
      { type: 'setCaptionStyle', style: 'none' },
      { type: 'setCaptionsEnabled', enabled: true },
    ]);
    expect(next.captionStyle).toBe('golden_aura');
  });

  it('falls back to viral_pop when there is nothing to restore', () => {
    const next = run([
      { type: 'set', patch: { captionStyle: 'none', lastActiveCaptionStyle: 'none' } },
      { type: 'setCaptionsEnabled', enabled: true },
    ]);
    expect(next.captionStyle).toBe('viral_pop');
  });

  it('switching off twice does not overwrite the remembered style', () => {
    const next = run([
      { type: 'setCaptionStyle', style: 'beast_punch' },
      { type: 'setCaptionsEnabled', enabled: false },
      { type: 'setCaptionsEnabled', enabled: false },
    ]);
    expect(next.lastActiveCaptionStyle).toBe('beast_punch');
  });
});

describe('watermark', () => {
  it('switching type loads that type defaults', () => {
    const next = studioReducer(initialStudioState, { type: 'setWatermarkType', watermarkType: 'text' });
    expect(next.watermarkX).toBe(50);
    expect(next.watermarkY).toBe(92);
  });

  it('seeds a placeholder handle for text mode', () => {
    expect(
      studioReducer(initialStudioState, { type: 'setWatermarkType', watermarkType: 'text' }).watermarkText,
    ).toBe('@channel');
  });

  it('keeps text the user already typed', () => {
    const next = run([
      { type: 'set', patch: { watermarkText: '@mychannel' } },
      { type: 'setWatermarkType', watermarkType: 'text' },
    ]);
    expect(next.watermarkText).toBe('@mychannel');
  });

  it('corner presets account for the current size', () => {
    const small = run([
      { type: 'set', patch: { watermarkSize: 20 } },
      { type: 'applyWatermarkPreset', corner: 'tl' },
    ]);
    const large = run([
      { type: 'set', patch: { watermarkSize: 80 } },
      { type: 'applyWatermarkPreset', corner: 'tl' },
    ]);
    expect(small.watermarkX).not.toBe(large.watermarkX);
  });

  it('upload switches the watermark on', () => {
    const next = studioReducer(initialStudioState, {
      type: 'assetUploaded',
      slot: 'watermark',
      asset: { filePath: '/tmp/logo.png', fileName: 'logo.png', url: '/api/watermark/logo.png' },
    });
    expect(next.watermarkEnabled).toBe(true);
    expect(next.watermarkFilePath).toBe('/tmp/logo.png');
  });

  it('removal switches it off again', () => {
    // The original left the toggle on with no file behind it.
    const next = run([
      {
        type: 'assetUploaded',
        slot: 'watermark',
        asset: { filePath: '/tmp/logo.png', fileName: 'logo.png', url: '/u' },
      },
      { type: 'assetRemoved', slot: 'watermark' },
    ]);
    expect(next.watermarkEnabled).toBe(false);
    expect(next.watermarkFilePath).toBeNull();
  });
});

describe('audio assets', () => {
  it.each(['bgm', 'sfx'] as const)('%s upload enables and removal disables', (slot) => {
    const uploaded = studioReducer(initialStudioState, {
      type: 'assetUploaded',
      slot,
      asset: { filePath: '/tmp/a.mp3', fileName: 'a.mp3', url: '/api/audio/a.mp3' },
    });
    const key = slot === 'bgm' ? 'bgmEnabled' : 'hookSfxEnabled';
    expect(uploaded[key]).toBe(true);

    const removed = studioReducer(uploaded, { type: 'assetRemoved', slot });
    expect(removed[key]).toBe(false);
  });

  it('keeps the two audio slots independent', () => {
    const next = run([
      {
        type: 'assetUploaded',
        slot: 'bgm',
        asset: { filePath: '/b.mp3', fileName: 'b.mp3', url: '/b' },
      },
      {
        type: 'assetUploaded',
        slot: 'sfx',
        asset: { filePath: '/s.mp3', fileName: 's.mp3', url: '/s' },
      },
      { type: 'assetRemoved', slot: 'bgm' },
    ]);
    expect(next.bgmEnabled).toBe(false);
    expect(next.hookSfxEnabled).toBe(true);
    expect(next.hookSfxFilePath).toBe('/s.mp3');
  });
});

describe('defaults', () => {
  it('start inside their own ceilings', () => {
    const d = getDefaultPositions('9:16', 1);
    expect(initialStudioState.titleYPercent).toBe(d.titleY);
    expect(initialStudioState.subtitleYPercent).toBe(d.subtitleY);
  });

  it('never mutate the previous state object', () => {
    const before = { ...initialStudioState };
    studioReducer(initialStudioState, { type: 'setTitleY', value: 99 });
    expect(initialStudioState).toEqual(before);
  });
});
