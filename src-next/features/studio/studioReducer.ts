import type {
  AspectRatioOption,
  BackgroundStyle,
  CaptionFont,
  CaptionStyle,
  FontSizeOption,
  HardwareAccelOption,
  StreamerPreset,
  SubtitlePositionMode,
  TextCaseOption,
  TitleDurationOption,
  TitlePosition,
} from '../../lib/types';
import { getDefaultPositions, getDefaultWatermarkConfig, watermarkPreset } from './derive';

/**
 * Studio settings as one reducer.
 *
 * These fields are not independent. Changing the aspect ratio rewrites three
 * positions and clears a lock; turning captions off has to remember which
 * style to restore. Spread across separate useState calls (66 of them in the
 * original) those rules lived in event handlers and drifted apart. Here each
 * rule is one case, in one place.
 *
 * Transient UI state (which panel is open, what is being dragged) stays in
 * local useState. Putting it here would re-render every consumer on each
 * slider tick.
 */
export interface StudioState {
  // Frame
  aspectRatio: AspectRatioOption;
  backgroundStyle: BackgroundStyle;
  enableFaceTracking: boolean;
  streamerPreset: StreamerPreset;

  // Title
  titlePosition: TitlePosition;
  titlePrefix: string;
  titleSuffix: string;
  titleDuration: TitleDurationOption;
  titleFontSize: FontSizeOption;
  titleYPercent: number;
  /** True once the user moves the title themselves, which stops auto-repositioning. */
  isCustomTitleY: boolean;

  // Captions
  captionStyle: CaptionStyle;
  /** Remembers the style while captions are switched off. */
  lastActiveCaptionStyle: CaptionStyle;
  captionFont: CaptionFont;
  fontSize: FontSizeOption;
  textCase: TextCaseOption;
  subtitleYPercent: number;
  subtitlePositionMode: SubtitlePositionMode;
  subtitleCenterYPercent: number;

  // Audio
  bgmEnabled: boolean;
  bgmFilePath: string | null;
  bgmFileName: string | null;
  bgmUrl: string | null;
  bgmVolume: number;
  bgmStartOffset: number;

  hookSfxEnabled: boolean;
  hookSfxFilePath: string | null;
  hookSfxFileName: string | null;
  hookSfxUrl: string | null;
  hookSfxVolume: number;

  originalAudioVolume: number;

  // Watermark
  watermarkEnabled: boolean;
  watermarkType: 'image' | 'text';
  watermarkFilePath: string | null;
  watermarkFileName: string | null;
  watermarkUrl: string | null;
  watermarkText: string;
  watermarkSize: number;
  watermarkOpacity: number;
  watermarkX: number;
  watermarkY: number;

  // Output
  hardwareAccel: HardwareAccelOption;
  fileNamePrefix: string;
  fileNameSuffix: string;
}

export const initialStudioState: StudioState = {
  aspectRatio: '9:16',
  // Blurred by default: black bars waste the canvas, and the renderer fills
  // them with the clip's own blurred frames at no extra cost.
  backgroundStyle: 'blurred',
  enableFaceTracking: true,
  streamerPreset: 'none',

  titlePosition: 'auto',
  titlePrefix: '',
  titleSuffix: '',
  titleDuration: 'entire',
  titleFontSize: 'medium',
  titleYPercent: getDefaultPositions('9:16', 1).titleY,
  isCustomTitleY: false,

  captionStyle: 'viral_pop',
  lastActiveCaptionStyle: 'viral_pop',
  captionFont: 'Outfit',
  fontSize: 'medium',
  textCase: 'uppercase',
  subtitleYPercent: getDefaultPositions('9:16', 1).subtitleY,
  subtitlePositionMode: 'bottom',
  subtitleCenterYPercent: 50,

  bgmEnabled: false,
  bgmFilePath: null,
  bgmFileName: null,
  bgmUrl: null,
  bgmVolume: 25,
  bgmStartOffset: 0,

  hookSfxEnabled: false,
  hookSfxFilePath: null,
  hookSfxFileName: null,
  hookSfxUrl: null,
  hookSfxVolume: 100,

  originalAudioVolume: 100,

  watermarkEnabled: false,
  watermarkType: 'image',
  watermarkFilePath: null,
  watermarkFileName: null,
  watermarkUrl: null,
  watermarkText: '',
  watermarkSize: 20,
  watermarkOpacity: 80,
  watermarkX: 88,
  watermarkY: 8,

  hardwareAccel: 'auto',
  fileNamePrefix: '',
  fileNameSuffix: '',
};

export interface UploadedAsset {
  filePath: string;
  fileName: string;
  url: string;
}

export type StudioAction =
  | { type: 'setAspectRatio'; ratio: AspectRatioOption; titleLines: number }
  | { type: 'resetPositions'; titleLines: number }
  | { type: 'setTitleY'; value: number }
  | { type: 'setSubtitleY'; value: number }
  | { type: 'setSubtitleCenterY'; value: number }
  | { type: 'autoTitleY'; value: number }
  | { type: 'setCaptionsEnabled'; enabled: boolean }
  | { type: 'setCaptionStyle'; style: CaptionStyle }
  | { type: 'setWatermarkType'; watermarkType: 'image' | 'text' }
  | { type: 'applyWatermarkPreset'; corner: Parameters<typeof watermarkPreset>[0] }
  | { type: 'resetWatermark' }
  | { type: 'assetUploaded'; slot: 'bgm' | 'sfx' | 'watermark'; asset: UploadedAsset }
  | { type: 'assetRemoved'; slot: 'bgm' | 'sfx' | 'watermark' }
  | { type: 'set'; patch: Partial<StudioState> };

export function studioReducer(state: StudioState, action: StudioAction): StudioState {
  switch (action.type) {
    // Changing the frame invalidates every position, and releases the lock
    // so the title follows the new ratio's defaults again.
    case 'setAspectRatio': {
      const d = getDefaultPositions(action.ratio, action.titleLines);
      return {
        ...state,
        aspectRatio: action.ratio,
        titleYPercent: d.titleY,
        subtitleYPercent: d.subtitleY,
        subtitleCenterYPercent: d.subCenterY,
        isCustomTitleY: false,
      };
    }

    case 'resetPositions': {
      const d = getDefaultPositions(state.aspectRatio, action.titleLines);
      return {
        ...state,
        titleYPercent: d.titleY,
        subtitleYPercent: d.subtitleY,
        subtitleCenterYPercent: d.subCenterY,
        isCustomTitleY: false,
      };
    }

    // A deliberate move locks the title in place.
    case 'setTitleY':
      return { ...state, titleYPercent: action.value, isCustomTitleY: true };

    // Follow-up from the line count changing. Ignored once the user has
    // taken control, which is what isCustomTitleY guards.
    case 'autoTitleY':
      return state.isCustomTitleY || state.titleYPercent === action.value
        ? state
        : { ...state, titleYPercent: action.value };

    case 'setSubtitleY':
      return { ...state, subtitleYPercent: action.value };

    case 'setSubtitleCenterY':
      return { ...state, subtitleCenterYPercent: action.value };

    // Turning captions off stores the style so it can be restored.
    case 'setCaptionsEnabled': {
      if (action.enabled) {
        const restored =
          state.lastActiveCaptionStyle !== 'none' ? state.lastActiveCaptionStyle : 'viral_pop';
        return { ...state, captionStyle: restored };
      }
      return {
        ...state,
        lastActiveCaptionStyle: state.captionStyle !== 'none' ? state.captionStyle : state.lastActiveCaptionStyle,
        captionStyle: 'none',
      };
    }

    // Picking "none" from the style grid should also be restorable, which
    // the original missed for that one control.
    case 'setCaptionStyle':
      return action.style === 'none'
        ? {
            ...state,
            lastActiveCaptionStyle:
              state.captionStyle !== 'none' ? state.captionStyle : state.lastActiveCaptionStyle,
            captionStyle: 'none',
          }
        : { ...state, captionStyle: action.style, lastActiveCaptionStyle: action.style };

    case 'setWatermarkType': {
      const d = getDefaultWatermarkConfig(action.watermarkType);
      return {
        ...state,
        watermarkType: action.watermarkType,
        watermarkSize: d.size,
        watermarkOpacity: d.opacity,
        watermarkX: d.x,
        watermarkY: d.y,
        watermarkText:
          action.watermarkType === 'text' && !state.watermarkText.trim()
            ? '@channel'
            : state.watermarkText,
      };
    }

    case 'applyWatermarkPreset': {
      const { x, y } = watermarkPreset(action.corner, state.watermarkSize);
      return { ...state, watermarkX: x, watermarkY: y };
    }

    case 'resetWatermark': {
      const d = getDefaultWatermarkConfig(state.watermarkType);
      return {
        ...state,
        watermarkSize: d.size,
        watermarkOpacity: d.opacity,
        watermarkX: d.x,
        watermarkY: d.y,
      };
    }

    // A successful upload enables its own toggle: the user just chose a file.
    case 'assetUploaded': {
      const { filePath, fileName, url } = action.asset;
      if (action.slot === 'bgm') {
        return { ...state, bgmEnabled: true, bgmFilePath: filePath, bgmFileName: fileName, bgmUrl: url };
      }
      if (action.slot === 'sfx') {
        return {
          ...state,
          hookSfxEnabled: true,
          hookSfxFilePath: filePath,
          hookSfxFileName: fileName,
          hookSfxUrl: url,
        };
      }
      return {
        ...state,
        watermarkEnabled: true,
        watermarkFilePath: filePath,
        watermarkFileName: fileName,
        watermarkUrl: url,
      };
    }

    // Removing the file also clears the toggle. The original left the
    // watermark switched on with nothing to draw.
    case 'assetRemoved': {
      if (action.slot === 'bgm') {
        return { ...state, bgmEnabled: false, bgmFilePath: null, bgmFileName: null, bgmUrl: null };
      }
      if (action.slot === 'sfx') {
        return {
          ...state,
          hookSfxEnabled: false,
          hookSfxFilePath: null,
          hookSfxFileName: null,
          hookSfxUrl: null,
        };
      }
      return {
        ...state,
        watermarkEnabled: false,
        watermarkFilePath: null,
        watermarkFileName: null,
        watermarkUrl: null,
      };
    }

    case 'set':
      return { ...state, ...action.patch };
  }
}
