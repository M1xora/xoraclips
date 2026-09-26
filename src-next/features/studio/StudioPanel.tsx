import { useEffect, useRef, useState } from 'react';
import {
  ImageIcon,
  MusicNotesIcon,
  SpeakerHighIcon,
  TrashIcon,
  UploadSimpleIcon,
} from '@phosphor-icons/react';
import { Button } from '../../components/ui/Button';
import { Panel } from '../../components/ui/Panel';
import { SegmentedControl } from '../../components/ui/SegmentedControl';
import { Slider } from '../../components/ui/Slider';
import { Field } from '../../components/ui/Field';
import { CAPTION_STYLE_LABELS, CAPTION_THEMES } from './captions';
import { getCenterBounds, getMaxPositions } from './derive';
import { outputFileName } from '../render/renderPayload';
import { api, UploadTooLargeError } from '../../api/client';
import { useLanguage } from '../../i18n';
import type { StudioAction, StudioState } from './studioReducer';
import type {
  CaptionFont,
  CaptionStyle,
  FontSizeOption,
  HardwareAccelInfo,
  HardwareAccelOption,
  StreamerPreset,
  TextCaseOption,
  TitleDurationOption,
} from '../../lib/types';
import { titleChoices } from './titleChoices';

/**
 * Ratio choices, shown as a shape rather than a label.
 *
 * The original studio drew a small box in each ratio (index.css:1348-1351)
 * so the choice reads at a glance. Plain text buttons lost that.
 */
const RATIO_CARDS = [
  { value: '9:16' as const, w: 18, h: 32 },
  { value: '1:1' as const, w: 24, h: 24 },
  { value: '4:3' as const, w: 28, h: 21 },
  { value: '16:9' as const, w: 32, h: 18 },
];
/**
 * Streamer layouts, drawn as the shape they produce.
 *
 * These change the whole filtergraph (video_engine.py:1305-1445), not just a
 * setting, so the diagram is the honest way to show the difference.
 */
const STREAMER_CARDS: StreamerPreset[] = ['none', 'split_top_cam', 'pip_corner'];

const DURATIONS: TitleDurationOption[] = ['entire', '5s', '10s'];

const FONTS: CaptionFont[] = [
  'Outfit',
  'Montserrat',
  'Inter',
  'Impact',
  'Bebas Neue',
  'Anton',
  'Poppins',
  'Arial Black',
];
const STYLES = Object.keys(CAPTION_THEMES) as Exclude<CaptionStyle, 'none'>[];

interface StudioPanelProps {
  state: StudioState;
  dispatch: (action: StudioAction) => void;
  /** Lines the current title wraps to, which drives default positions. */
  titleLines: number;
  /** Title of the active clip, used to preview the output file name. */
  sampleTitle: string;
  /** The AI's own title for the active clip, shown as the placeholder. */
  aiTitle?: string;
  /** Custom title for the active clip, empty when it uses the AI one. */
  customTitle?: string;
  /** The AI's title options for the active clip, first = its default (#31). */
  titleOptions?: string[];
  onCustomTitleChange?: (value: string) => void;
  onError: (message: string) => void;
}

export function StudioPanel({
  state,
  dispatch,
  titleLines,
  sampleTitle,
  aiTitle,
  customTitle = '',
  titleOptions,
  onCustomTitleChange,
  onError,
}: StudioPanelProps) {
  const { t } = useLanguage();
  const choices = titleChoices(titleOptions, customTitle);
  const max = getMaxPositions(state.aspectRatio, titleLines);
  const centre = getCenterBounds(state.aspectRatio);

  const sizeOptions: { value: FontSizeOption; label: string }[] = [
    { value: 'small', label: t.studio.sizeSmall },
    { value: 'medium', label: t.studio.sizeMedium },
    { value: 'big', label: t.studio.sizeBig },
  ];
  const caseOptions: { value: TextCaseOption; label: string }[] = [
    { value: 'uppercase', label: t.studio.caseUpper },
    { value: 'capitalize', label: t.studio.caseCapital },
    { value: 'lowercase', label: t.studio.caseLower },
  ];

  return (
    <div className="grid gap-4">
      <Panel title={t.studio.frame}>
        <div className="grid gap-4">
          <div>
            <span className="text-xs font-medium text-ink-dim">{t.studio.aspectRatio}</span>
            <div
              role="radiogroup"
              aria-label={t.studio.aspectRatio}
              className="mt-1.5 grid grid-cols-2 gap-1.5 xl:grid-cols-4"
            >
              {RATIO_CARDS.map((card) => {
                const active = state.aspectRatio === card.value;
                const names: Record<string, [string, string]> = {
                  '9:16': [t.studio.ratio916, t.studio.ratio916Sub],
                  '1:1': [t.studio.ratio11, t.studio.ratio11Sub],
                  '4:3': [t.studio.ratio43, t.studio.ratio43Sub],
                  '16:9': [t.studio.ratio169, t.studio.ratio169Sub],
                };
                const [name, sub] = names[card.value];

                return (
                  <button
                    key={card.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() =>
                      dispatch({ type: 'setAspectRatio', ratio: card.value, titleLines })
                    }
                    className={`pressable flex flex-col items-center gap-1.5 rounded-[--radius-control]
                      border px-2 py-2.5
                      ${
                        active
                          ? 'border-accent bg-accent-muted'
                          : 'border-hairline bg-surface-2 hover:bg-surface-3'
                      }`}
                  >
                    {/* The shape itself carries the meaning. */}
                    <span
                      aria-hidden="true"
                      className={`rounded-sm border ${
                        active ? 'border-accent bg-accent' : 'border-dashed border-ink-faint'
                      }`}
                      style={{ width: card.w, height: card.h }}
                    />
                    <span className="text-[0.8rem] font-semibold leading-none">{name}</span>
                    <span className="text-[0.76rem] leading-tight text-ink-faint">{sub}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <SegmentedControl
              label={t.studio.background}
              value={state.backgroundStyle}
              options={[
                { value: 'black' as const, label: t.studio.backgroundBlack },
                { value: 'blurred' as const, label: t.studio.backgroundBlurred },
              ]}
              onChange={(v) => dispatch({ type: 'set', patch: { backgroundStyle: v } })}
              disabled={state.aspectRatio === '9:16'}
            />
            <p className="mt-1.5 text-[0.8rem] text-ink-faint">
              {state.aspectRatio === '9:16'
                ? t.studio.backgroundFullBleed
                : t.studio.backgroundHint}
            </p>
          </div>

          {/* Face tracking only shifts the crop at 9:16; every other ratio is
              centre-cropped by the backend (video_engine.py:1449-1455). The
              streamer presets detect a face whatever the ratio, so the toggle
              is meaningless there and the hint says so instead. */}
          {state.streamerPreset !== 'none' ? (
            <p className="text-[0.8rem] text-ink-faint">{t.studio.streamerUsesFace}</p>
          ) : (
            state.aspectRatio === '9:16' && (
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={state.enableFaceTracking}
                  onChange={(e) =>
                    dispatch({ type: 'set', patch: { enableFaceTracking: e.target.checked } })
                  }
                  className="size-4 accent-accent"
                />
                {t.studio.faceTracking}
              </label>
            )
          )}

          <div>
            <span className="text-xs font-medium text-ink-dim">{t.studio.streamerGroup}</span>
            <div
              role="radiogroup"
              aria-label={t.studio.streamerGroup}
              className="mt-1.5 grid grid-cols-3 gap-1.5"
            >
              {STREAMER_CARDS.map((preset) => {
                const active = state.streamerPreset === preset;
                const names: Record<StreamerPreset, [string, string]> = {
                  none: [t.studio.streamerNone, t.studio.streamerNoneSub],
                  split_top_cam: [t.studio.streamerSplit, t.studio.streamerSplitSub],
                  pip_corner: [t.studio.streamerPip, t.studio.streamerPipSub],
                };
                const [name, sub] = names[preset];

                return (
                  <button
                    key={preset}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => dispatch({ type: 'set', patch: { streamerPreset: preset } })}
                    className={`pressable flex flex-col items-center gap-1.5
                      rounded-[--radius-control] border px-2 py-2.5
                      ${
                        active
                          ? 'border-accent bg-accent-muted'
                          : 'border-hairline bg-surface-2 hover:bg-surface-3'
                      }`}
                  >
                    <StreamerShape preset={preset} active={active} />
                    <span className="text-[0.8rem] font-semibold leading-none">{name}</span>
                    <span className="text-[0.76rem] leading-tight text-ink-faint">{sub}</span>
                  </button>
                );
              })}
            </div>
            <p className="mt-1.5 text-[0.8rem] text-ink-faint">
              {state.streamerPreset === 'none'
                ? t.studio.streamerHint
                : t.studio.streamerBestRatio}
            </p>

            {/* 9:16 split stacks two 540px boxes in a 1080px canvas, so the
                video covers half of it and the rest is bar (video_engine.py
                :1356-1369). Verified on a real render: the edge lands at
                x=810. Worth saying, since 9:16 is the default ratio. */}
            {state.streamerPreset === 'split_top_cam' && state.aspectRatio === '9:16' && (
              <div className="mt-2 flex flex-wrap items-center gap-2 rounded-[--radius-control]
                border border-caution/40 bg-caution/10 px-2.5 py-2">
                <p className="min-w-0 flex-1 text-[0.8rem] text-ink">
                  {t.studio.streamerRatioWarn}
                </p>
                <button
                  type="button"
                  onClick={() =>
                    dispatch({ type: 'setAspectRatio', ratio: '1:1', titleLines })
                  }
                  className="pressable shrink-0 rounded border border-hairline bg-surface-2
                    px-2 py-1 text-[0.8rem] font-semibold hover:bg-surface-3"
                >
                  {t.studio.streamerSwitchTo11}
                </button>
              </div>
            )}
          </div>
        </div>
      </Panel>

      <Panel title={t.studio.titleGroup}>
        <div className="grid gap-4">
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={state.titlePosition !== 'none'}
              onChange={(e) =>
                dispatch({
                  type: 'set',
                  patch: { titlePosition: e.target.checked ? 'auto' : 'none' },
                })
              }
              className="size-4 accent-accent"
            />
            {t.studio.titleShow}
          </label>

          {state.titlePosition !== 'none' && (
            <>
              <SegmentedControl
                label={t.studio.titleSize}
                value={state.titleFontSize}
                options={sizeOptions}
                onChange={(v) => dispatch({ type: 'set', patch: { titleFontSize: v } })}
              />
              <Slider
                label={t.studio.titlePosition}
                value={state.titleYPercent}
                min={4}
                max={max.maxTitleY}
                step={0.5}
                unit="%"
                onChange={(v) => dispatch({ type: 'setTitleY', value: v })}
              />

              <SegmentedControl
                label={t.studio.titleDuration}
                value={state.titleDuration}
                options={DURATIONS.map((d) => ({
                  value: d,
                  label:
                    d === 'entire'
                      ? t.studio.durationEntire
                      : d === '5s'
                        ? t.studio.duration5s
                        : t.studio.duration10s,
                }))}
                onChange={(v) => dispatch({ type: 'set', patch: { titleDuration: v } })}
              />

              {/* Per-clip rename. The backend reads custom_title before
                  title_suggestion (main.py:2274), so this wins for this clip
                  while the prefix and suffix below still apply to all. */}
              {onCustomTitleChange && (
                <div>
                  <Field
                    label={t.studio.clipTitle}
                    value={customTitle}
                    placeholder={aiTitle || ''}
                    disabled={!aiTitle}
                    onChange={(e) => onCustomTitleChange(e.target.value)}
                    hint={aiTitle ? t.studio.clipTitleHint : t.studio.clipTitleNoClip}
                  />
                  {/* The AI's other titles, one click away and no new request (#31). */}
                  {choices.length > 0 && (
                    <div className="mt-2" role="group" aria-label={t.studio.clipTitleOptions}>
                      <p className="mb-1 text-[0.8rem] font-medium text-ink-dim">{t.studio.clipTitleOptions}</p>
                      <div className="flex flex-col gap-1">
                        {choices.map((choice) => (
                          <button
                            key={choice.text}
                            type="button"
                            aria-pressed={choice.active}
                            onClick={() => onCustomTitleChange(choice.value)}
                            className={`pressable rounded-[--radius-control] border px-2.5 py-1.5 text-left text-xs
                              ${choice.active
                                ? 'border-accent bg-accent/10 font-semibold text-ink'
                                : 'border-hairline text-ink-dim hover:bg-surface-2 hover:text-ink'}`}
                          >
                            {choice.text}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {choices.length === 0 && customTitle.trim() !== '' && (
                    <button
                      type="button"
                      onClick={() => onCustomTitleChange('')}
                      className="pressable mt-1.5 text-[0.8rem] font-semibold text-ink-dim
                        underline hover:text-ink"
                    >
                      {t.studio.clipTitleReset}
                    </button>
                  )}
                </div>
              )}

              {/* The backend wraps every clip's own title in these
                  (main.py:2281-2282), so they apply to the whole batch. */}
              <div className="grid gap-3 sm:grid-cols-2">
                <Field
                  label={t.studio.titlePrefix}
                  value={state.titlePrefix}
                  placeholder={t.studio.titlePrefixPlaceholder}
                  onChange={(e) =>
                    dispatch({ type: 'set', patch: { titlePrefix: e.target.value } })
                  }
                />
                <Field
                  label={t.studio.titleSuffix}
                  value={state.titleSuffix}
                  placeholder={t.studio.titleSuffixPlaceholder}
                  onChange={(e) =>
                    dispatch({ type: 'set', patch: { titleSuffix: e.target.value } })
                  }
                />
              </div>
              <p className="-mt-1 text-[0.8rem] text-ink-faint">{t.studio.titleAffixHint}</p>
            </>
          )}
        </div>
      </Panel>

      <Panel title={t.studio.captions}>
        <div className="grid gap-4">
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={state.captionStyle !== 'none'}
              onChange={(e) => dispatch({ type: 'setCaptionsEnabled', enabled: e.target.checked })}
              className="size-4 accent-accent"
            />
            {t.studio.captionsOn}
          </label>

          {state.captionStyle !== 'none' && (
            <>
              <div>
                <span className="text-xs font-medium text-ink-dim">{t.studio.captionStyle}</span>
                <div className="mt-1.5 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
                  {STYLES.map((s) => (
                    <button
                      key={s}
                      type="button"
                      aria-pressed={state.captionStyle === s}
                      onClick={() => dispatch({ type: 'setCaptionStyle', style: s })}
                      className={`pressable rounded-[--radius-control] border px-2 py-2 text-[0.8rem]
                        font-semibold
                        ${
                          state.captionStyle === s
                            ? 'border-accent bg-surface-3'
                            : 'border-hairline bg-surface-2 hover:bg-surface-3'
                        }`}
                      style={{ color: CAPTION_THEMES[s].accent }}
                    >
                      {CAPTION_STYLE_LABELS[s]}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label htmlFor="caption-font" className="text-xs font-medium text-ink-dim">
                  {t.studio.captionFont}
                </label>
                <select
                  id="caption-font"
                  value={state.captionFont}
                  onChange={(e) =>
                    dispatch({ type: 'set', patch: { captionFont: e.target.value as CaptionFont } })
                  }
                  className="mt-1.5 h-9 w-full rounded-[--radius-control] border border-hairline
                    bg-surface-2 px-2.5 text-sm text-ink"
                >
                  {FONTS.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>

              <SegmentedControl
                label={t.studio.captionSize}
                value={state.fontSize}
                options={sizeOptions}
                onChange={(v) => dispatch({ type: 'set', patch: { fontSize: v } })}
              />

              <SegmentedControl
                label={t.studio.captionCase}
                value={state.textCase}
                options={caseOptions}
                onChange={(v) => dispatch({ type: 'set', patch: { textCase: v } })}
              />

              <SegmentedControl
                label={t.studio.captionPosition}
                value={state.subtitlePositionMode}
                options={[
                  { value: 'bottom' as const, label: t.studio.positionBottom },
                  { value: 'center' as const, label: t.studio.positionCenter },
                ]}
                onChange={(v) => dispatch({ type: 'set', patch: { subtitlePositionMode: v } })}
              />

              {state.subtitlePositionMode === 'bottom' ? (
                <Slider
                  label={t.studio.subtitleBottom}
                  value={state.subtitleYPercent}
                  min={5}
                  max={max.maxSubY}
                  step={0.5}
                  unit="%"
                  onChange={(v) => dispatch({ type: 'setSubtitleY', value: v })}
                />
              ) : (
                <Slider
                  label={t.studio.subtitleCenter}
                  value={state.subtitleCenterYPercent}
                  min={centre.min}
                  max={centre.max}
                  step={0.5}
                  unit="%"
                  onChange={(v) => dispatch({ type: 'setSubtitleCenterY', value: v })}
                />
              )}
            </>
          )}
        </div>
      </Panel>


      <Panel title={t.studio.watermark}>
        <div className="grid gap-4">
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={state.watermarkEnabled}
              onChange={(e) =>
                dispatch({ type: 'set', patch: { watermarkEnabled: e.target.checked } })
              }
              className="size-4 accent-accent"
            />
            {t.studio.watermarkOn}
          </label>

          {state.watermarkEnabled && (
            <>
              <SegmentedControl
                label={t.studio.watermarkType}
                value={state.watermarkType}
                options={[
                  { value: 'image' as const, label: t.studio.watermarkImage },
                  { value: 'text' as const, label: t.studio.watermarkText },
                ]}
                onChange={(v) => dispatch({ type: 'setWatermarkType', watermarkType: v })}
              />

              {state.watermarkType === 'image' ? (
                <WatermarkUpload
                  fileName={state.watermarkFileName}
                  dispatch={dispatch}
                  onError={onError}
                />
              ) : (
                <div>
                  <label htmlFor="wm-text" className="text-xs font-medium text-ink-dim">
                    {t.studio.watermarkTextLabel}
                  </label>
                  <input
                    id="wm-text"
                    value={state.watermarkText}
                    onChange={(e) =>
                      dispatch({ type: 'set', patch: { watermarkText: e.target.value } })
                    }
                    placeholder="@channel"
                    className="mt-1.5 h-9 w-full rounded-[--radius-control] border border-hairline
                      bg-surface-2 px-3 text-sm text-ink placeholder:text-ink-faint"
                  />
                </div>
              )}

              <Slider
                label={t.studio.watermarkSize}
                value={state.watermarkSize}
                min={0}
                max={500}
                unit="%"
                presets={[
                  { label: '10', value: 10 },
                  { label: '20', value: 20 },
                  { label: '50', value: 50 },
                ]}
                onChange={(v) => dispatch({ type: 'set', patch: { watermarkSize: v } })}
              />

              <Slider
                label={t.studio.watermarkOpacity}
                value={state.watermarkOpacity}
                min={10}
                max={100}
                step={5}
                unit="%"
                onChange={(v) => dispatch({ type: 'set', patch: { watermarkOpacity: v } })}
              />

              <div>
                <span className="text-xs font-medium text-ink-dim">
                  {t.studio.watermarkPosition}
                </span>
                <div className="mt-1.5 grid w-28 grid-cols-3 gap-1">
                  {(['tl', 'tc', 'tr', null, 'c', null, 'bl', 'bc', 'br'] as const).map(
                    (corner, i) =>
                      corner ? (
                        <button
                          key={corner}
                          type="button"
                          aria-label={t.studio.watermarkCorner[corner]}
                          onClick={() => dispatch({ type: 'applyWatermarkPreset', corner })}
                          className="pressable aspect-square rounded border border-hairline
                            bg-surface-2 hover:bg-surface-3"
                        />
                      ) : (
                        <span key={`gap-${i}`} />
                      ),
                  )}
                </div>
              </div>

              <Button
                variant="ghost"
                size="sm"
                onClick={() => dispatch({ type: 'resetWatermark' })}
              >
                {t.studio.watermarkReset}
              </Button>
            </>
          )}
        </div>
      </Panel>

      <Panel title={t.studio.audio}>
        <div className="grid gap-5">
          <AssetSlot
            slot="bgm"
            icon={<MusicNotesIcon size={14} />}
            label={t.studio.bgm}
            fileName={state.bgmFileName}
            dispatch={dispatch}
            onError={onError}
          />
          {state.bgmFilePath && (
            <>
              <Slider
                label={t.studio.volume}
                value={state.bgmVolume}
                min={0}
                max={100}
                unit="%"
                presets={[
                  { label: '10', value: 10 },
                  { label: '25', value: 25 },
                  { label: '50', value: 50 },
                ]}
                onChange={(v) => dispatch({ type: 'set', patch: { bgmVolume: v } })}
              />
              <Slider
                label={t.studio.startAt}
                value={state.bgmStartOffset}
                min={0}
                max={180}
                step={0.5}
                unit="s"
                onChange={(v) => dispatch({ type: 'set', patch: { bgmStartOffset: v } })}
              />
            </>
          )}

          <AssetSlot
            slot="sfx"
            icon={<SpeakerHighIcon size={14} />}
            label={t.studio.sfx}
            fileName={state.hookSfxFileName}
            dispatch={dispatch}
            onError={onError}
          />
          {state.hookSfxFilePath && (
            <Slider
              label={t.studio.volume}
              value={state.hookSfxVolume}
              min={0}
              max={150}
              step={5}
              unit="%"
              onChange={(v) => dispatch({ type: 'set', patch: { hookSfxVolume: v } })}
            />
          )}

          <Slider
            label={t.studio.voiceBoost}
            value={state.originalAudioVolume}
            min={0}
            max={200}
            step={5}
            unit="%"
            presets={[
              { label: '100', value: 100 },
              { label: '150', value: 150 },
            ]}
            onChange={(v) => dispatch({ type: 'set', patch: { originalAudioVolume: v } })}
          />
        </div>
      </Panel>

      <Panel title={t.studio.fileNameGroup}>
        <div className="grid gap-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label={t.studio.fileNamePrefix}
              value={state.fileNamePrefix}
              placeholder={t.studio.fileNamePrefixPlaceholder}
              onChange={(e) => dispatch({ type: 'set', patch: { fileNamePrefix: e.target.value } })}
            />
            <Field
              label={t.studio.fileNameSuffix}
              value={state.fileNameSuffix}
              placeholder={t.studio.fileNameSuffixPlaceholder}
              onChange={(e) => dispatch({ type: 'set', patch: { fileNameSuffix: e.target.value } })}
            />
          </div>

          {/* Same helper the render queue and the backend use, so what is
              shown here is the name the file actually gets. */}
          <div>
            <span className="text-xs font-medium text-ink-dim">{t.studio.fileNamePreview}</span>
            <p className="mt-1 break-all font-mono text-[0.8rem] text-ink">
              {outputFileName(
                sampleTitle,
                state.fileNamePrefix,
                state.fileNameSuffix,
                new Map(),
              )}
            </p>
          </div>

          <p className="text-[0.8rem] text-ink-faint">{t.studio.fileNameHint}</p>
        </div>
      </Panel>

      <Panel title={t.studio.hardwareGroup}>
        <HardwarePicker
          value={state.hardwareAccel}
          onChange={(v) => dispatch({ type: 'set', patch: { hardwareAccel: v } })}
        />
      </Panel>
    </div>
  );
}

/**
 * A 18x32 diagram of what each streamer preset produces.
 *
 * Standard is one block, split is two stacked halves, pip is a block with a
 * small box in the top-right corner, which is where the backend puts it
 * (x=736 of 1080, video_engine.py:1379).
 */
function StreamerShape({ preset, active }: { preset: StreamerPreset; active: boolean }) {
  const line = active ? 'border-accent' : 'border-ink-faint';
  const fill = active ? 'bg-accent' : 'bg-ink-faint/40';

  if (preset === 'split_top_cam') {
    return (
      <span
        aria-hidden="true"
        className={`flex flex-col gap-px overflow-hidden rounded-sm border ${line}`}
        style={{ width: 18, height: 32 }}
      >
        <span className={`flex-1 ${fill}`} />
        <span className={`flex-1 ${active ? 'bg-accent/40' : 'bg-ink-faint/15'}`} />
      </span>
    );
  }

  if (preset === 'pip_corner') {
    return (
      <span
        aria-hidden="true"
        className={`relative overflow-hidden rounded-sm border ${line} ${
          active ? 'bg-accent/40' : 'bg-ink-faint/15'
        }`}
        style={{ width: 18, height: 32 }}
      >
        <span className={`absolute right-px top-px rounded-px ${fill}`} style={{ width: 7, height: 5 }} />
      </span>
    );
  }

  return (
    <span
      aria-hidden="true"
      className={`rounded-sm border ${line} ${fill}`}
      style={{ width: 18, height: 32 }}
    />
  );
}

interface HardwarePickerProps {
  value: HardwareAccelOption;
  onChange: (value: HardwareAccelOption) => void;
}

/**
 * Encoder choice, backed by what the machine actually has.
 *
 * The options come from GET /api/hardware-accel, which probes ffmpeg, so an
 * encoder the machine lacks is shown disabled rather than offered and then
 * silently falling back to CPU. If the probe fails the choice still works,
 * because the backend resolves an unavailable selection to CPU anyway
 * (video_engine.py resolve_encoder).
 */
function HardwarePicker({ value, onChange }: HardwarePickerProps) {
  const { t } = useLanguage();
  const [info, setInfo] = useState<HardwareAccelInfo | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const ac = new AbortController();

    api
      .hardwareAccel(ac.signal)
      .then(setInfo)
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setFailed(true);
      });

    return () => ac.abort();
  }, []);

  // Fall back to the full list so the control is usable even without a probe.
  const options =
    info?.options ??
    (['auto', 'nvenc', 'amf', 'qsv', 'cpu'] as const).map((id) => ({
      id,
      label: id === 'auto' ? 'Auto' : id.toUpperCase(),
      sub: '',
      available: true,
    }));

  if (!info && !failed) {
    return <p className="text-xs text-ink-faint">{t.studio.hardwareDetecting}</p>;
  }

  return (
    <div className="grid gap-2">
      <div role="radiogroup" aria-label={t.studio.hardwareGroup} className="grid gap-1.5">
        {options.map((opt) => {
          const active = value === opt.id;
          const off = !opt.available;

          return (
            <button
              key={opt.id}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={off}
              onClick={() => onChange(opt.id)}
              className={`pressable flex items-center justify-between gap-3 rounded-[--radius-control]
                border px-3 py-2 text-left
                ${
                  active
                    ? 'border-accent bg-accent-muted'
                    : 'border-hairline bg-surface-2 hover:bg-surface-3'
                }
                ${off ? 'cursor-not-allowed opacity-45 hover:bg-surface-2' : ''}`}
            >
              <span className="min-w-0">
                <span className="block text-xs font-semibold">{opt.label}</span>
                <span className="block truncate text-[0.76rem] text-ink-faint">
                  {off ? t.studio.hardwareUnavailable : opt.sub}
                </span>
              </span>

              {info && info.recommended === opt.id && opt.available && (
                <span className="shrink-0 rounded bg-accent-muted px-1.5 py-px text-[0.72rem] font-bold uppercase text-ink">
                  {t.studio.hardwareRecommended}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <p className="text-[0.8rem] text-ink-faint">
        {failed ? t.studio.hardwareFailed : t.studio.hardwareHint}
      </p>
    </div>
  );
}

interface WatermarkUploadProps {
  fileName: string | null;
  dispatch: (action: StudioAction) => void;
  onError: (message: string) => void;
}

/** Image upload for the watermark. */
function WatermarkUpload({ fileName, dispatch, onError }: WatermarkUploadProps) {
  const { t } = useLanguage();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const upload = async (file: File) => {
    setBusy(true);
    try {
      const res = await api.uploads.watermark(file);
      dispatch({
        type: 'assetUploaded',
        slot: 'watermark',
        asset: { filePath: res.file_path, fileName: res.filename, url: res.url },
      });
    } catch (err) {
      onError(
        err instanceof UploadTooLargeError
          ? err.message
          : `${t.studio.uploadFailed}: ${err instanceof Error ? err.message : ''}`,
      );
    } finally {
      setBusy(false);
    }
  };

  if (fileName) {
    return (
      <div className="flex items-center gap-2 rounded-[--radius-control] border
        border-hairline bg-surface-2 px-2.5 py-2">
        <ImageIcon size={14} className="shrink-0 text-ink-faint" />
        <span className="min-w-0 flex-1 truncate text-xs">{fileName}</span>
        <button
          type="button"
          onClick={() => dispatch({ type: 'assetRemoved', slot: 'watermark' })}
          aria-label={t.studio.remove}
          className="pressable grid size-6 place-items-center rounded text-ink-faint
            hover:bg-surface-3 hover:text-critical-text"
        >
          <TrashIcon size={13} />
        </button>
      </div>
    );
  }

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void upload(f);
        }}
      />
      <Button
        type="button"
        variant="secondary"
        size="sm"
        loading={busy}
        onClick={() => inputRef.current?.click()}
        icon={<UploadSimpleIcon size={13} />}
      >
        {busy ? t.studio.uploading : t.studio.uploadImage}
      </Button>
    </div>
  );
}

interface AssetSlotProps {
  slot: 'bgm' | 'sfx';
  icon: React.ReactNode;
  label: string;
  fileName: string | null;
  dispatch: (action: StudioAction) => void;
  onError: (message: string) => void;
}

/** Upload control for one audio asset, with drag and drop. */
function AssetSlot({ slot, icon, label, fileName, dispatch, onError }: AssetSlotProps) {
  const { t } = useLanguage();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);

  const upload = async (file: File) => {
    setBusy(true);
    try {
      const res = slot === 'bgm' ? await api.uploads.bgm(file) : await api.uploads.sfx(file);
      dispatch({
        type: 'assetUploaded',
        slot,
        asset: { filePath: res.file_path, fileName: res.filename, url: res.url },
      });
    } catch (err) {
      // The old UI used window.alert here, which blocks the page.
      onError(
        err instanceof UploadTooLargeError
          ? err.message
          : `${t.studio.uploadFailed}: ${err instanceof Error ? err.message : ''}`,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <span className="flex items-center gap-1.5 text-xs font-medium text-ink-dim">
        {icon}
        {label}
      </span>

      {fileName ? (
        <div className="mt-1.5 flex items-center gap-2 rounded-[--radius-control] border
          border-hairline bg-surface-2 px-2.5 py-2">
          <span className="min-w-0 flex-1 truncate text-xs">{fileName}</span>
          <button
            type="button"
            onClick={() => dispatch({ type: 'assetRemoved', slot })}
            aria-label={t.studio.remove}
            className="pressable grid size-6 place-items-center rounded text-ink-faint
              hover:bg-surface-3 hover:text-critical-text"
          >
            <TrashIcon size={13} />
          </button>
        </div>
      ) : (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const f = e.dataTransfer.files?.[0];
            if (f) void upload(f);
          }}
          className={`mt-1.5 rounded-[--radius-control] border border-dashed p-3 text-center
            ${dragging ? 'border-accent bg-surface-3' : 'border-hairline'}`}
        >
          <input
            ref={inputRef}
            type="file"
            accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac"
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void upload(f);
            }}
          />
          <Button
            type="button"
            variant="secondary"
            size="sm"
            loading={busy}
            onClick={() => inputRef.current?.click()}
            icon={<UploadSimpleIcon size={13} />}
          >
            {busy ? t.studio.uploading : dragging ? t.studio.dropHere : t.studio.uploadAudio}
          </Button>
        </div>
      )}
    </div>
  );
}
