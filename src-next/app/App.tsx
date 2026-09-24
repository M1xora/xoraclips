import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import {
  ArrowSquareOutIcon,
  CookieIcon,
  FilmStripIcon,
  KeyIcon,
  WarningCircleIcon,
} from '@phosphor-icons/react';
import { AnalyzeForm, API_KEY_INPUT_NAME } from '../features/analyze/AnalyzeForm';
import { analyzeErrorView, focusApiKeyField } from '../features/analyze/analyzeErrors';
import { AI_STUDIO_KEY_URL, currentApiKey } from '../features/analyze/apiKeyStore';
import { AnalyzeProgress } from '../features/analyze/AnalyzeProgress';
import { cacheKey, readCache, writeCache } from '../features/analyze/analysisCache';
import { HistoryPanel } from '../features/analyze/HistoryPanel';
import type { HistoryEntry } from '../features/analyze/analysisCache';
import { ClipList } from '../features/clips/ClipList';
import { VideoPlayer } from '../features/player/VideoPlayer';
import { ClipPreview } from '../features/player/ClipPreview';
import { StudioPanel } from '../features/studio/StudioPanel';
import { initialStudioState, studioReducer } from '../features/studio/studioReducer';
import {
  formatTitleSmart,
  getCenterBounds,
  getDefaultPositions,
  getMaxPositions,
} from '../features/studio/derive';
import { RenderQueue } from '../features/render/RenderQueue';
import { useBatchRender } from '../features/render/useBatchRender';
import { buildRenderPayload } from '../features/render/renderPayload';
import type { RecoveryAction } from '../features/render/errorMessages';
import { ToolsPanel } from '../features/export/ToolsPanel';
import { TrimmerModal } from '../features/trimmer/TrimmerModal';
import { CookiesModal } from '../features/cookies/CookiesModal';
import { updateCachedResult } from '../features/analyze/analysisCache';
import {
  effectiveTitle,
  loadMarks,
  saveMarks,
  withClipIds,
  type MarkMap,
} from '../features/clips/clipIdentity';
import { Button } from '../components/ui/Button';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { Panel } from '../components/ui/Panel';
import { ThemeToggle } from '../components/ui/ThemeToggle';
import { Toast } from '../components/ui/Toast';
import { useToast } from '../components/ui/useToast';
import { api } from '../api/client';
import { useAnalyze, type AnalyzeRequest } from '../hooks/useAnalyze';
import { useTheme } from '../hooks/useTheme';
import { useLanguage } from '../i18n';
import type { AnalyzeResponse, ViralClip } from '../lib/types';

export function App() {
  const { theme, toggle } = useTheme();
  const { language, setLanguage, t } = useLanguage();
  const { analyze, status, progress, error, errorCode, errorRetryAt } = useAnalyze();
  const { toast, show, dismiss } = useToast();

  // The result lives here rather than in useAnalyze so a cache hit and a
  // fresh run feed the same state, and trims can write back into it.
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [marked, setMarked] = useState<MarkMap>({});
  const [activeId, setActiveId] = useState<string | null>(null);
  const [autoPlayClip, setAutoPlayClip] = useState(false);
  // Preview sound is off by default: a clip that starts making noise on its
  // own is worse than one the user turns up.
  const [previewSound, setPreviewSound] = useState(false);
  const [studio, dispatchStudio] = useReducer(studioReducer, initialStudioState);
  // Per-clip title overrides, keyed by clip id. The backend reads this as
  // custom_title (main.py:2274), ahead of the AI's own suggestion.
  const [customTitles, setCustomTitles] = useState<Record<string, string>>({});
  const render = useBatchRender();
  const [trimClip, setTrimClip] = useState<ViralClip | null>(null);
  const [cookiesOpen, setCookiesOpen] = useState(false);
  const [hasCookies, setHasCookies] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [lastRequest, setLastRequest] = useState<AnalyzeRequest | null>(null);
  const activeCacheKey = useRef<string | null>(null);
  // Bumped so the history list re-reads localStorage after an analysis.
  const [historyToken, setHistoryToken] = useState(0);

  const busy = status === 'running';

  // A new run starts the clock from zero. Reset while rendering when `busy`
  // flips, rather than in the effect (#2); the effect only ticks.
  const [wasBusy, setWasBusy] = useState(busy);
  if (busy !== wasBusy) {
    setWasBusy(busy);
    if (busy) setElapsed(0);
  }

  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => setElapsed((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [busy]);

  // Marks are per video and migrate off the old start_end keys on read.
  // Reloaded while rendering when the video or its clips change (#2).
  const videoId = result?.video_id;
  const clips = result?.clips;
  const [marksSource, setMarksSource] = useState<{ videoId?: string; clips?: ViralClip[] }>({});
  if (marksSource.videoId !== videoId || marksSource.clips !== clips) {
    setMarksSource({ videoId, clips });
    setMarked(videoId && clips ? loadMarks(videoId, clips) : {});
  }

  const toggleMark = useCallback(
    (clip: ViralClip) => {
      if (!videoId) return;
      setMarked((prev) => {
        const next = { ...prev };
        if (next[clip.id]) delete next[clip.id];
        else next[clip.id] = true;
        saveMarks(videoId, next);
        return next;
      });
    },
    [videoId],
  );

  const copy = useCallback(
    async (text: string, label: string) => {
      try {
        await navigator.clipboard.writeText(text);
        show(label);
      } catch {
        show(t.results.copyFailed, 'error');
      }
    },
    [show, t.results.copyFailed],
  );

  const runAnalysis = useCallback(
    async (payload: AnalyzeRequest) => {
      setLastRequest(payload);
      setActiveId(null);

      // Re-analysing spends Gemini quota, so a cache hit short-circuits.
      const videoId = extractVideoId(payload.url);
      const key = cacheKey(videoId, payload);
      activeCacheKey.current = key;

      const cached = readCache(key);
      if (cached) {
        setResult(cached);
        setHistoryToken((n) => n + 1);
        show(t.results.clipsFound(cached.clips.length));
        return;
      }

      // The user's key travels as a header, never inside the payload or the cache.
      const fresh = await analyze(payload, currentApiKey());
      if (!fresh) return;

      const withIds = withClipIds(fresh);
      setResult(withIds);
      writeCache(key, withIds);
      setHistoryToken((n) => n + 1);
    },
    [analyze, show, t.results],
  );

  // Reopening a cached analysis. The clips already carry their ids, so marks
  // and custom titles line up with what was saved.
  const openFromHistory = useCallback(
    (entry: HistoryEntry) => {
      const cached = readCache(entry.key);
      if (!cached) return;
      activeCacheKey.current = entry.key;
      setActiveId(null);
      setResult(cached);
      show(t.results.historyRestored);
    },
    [show, t.results.historyRestored],
  );

  // Closing a result is the only route back to the history list, so without
  // this the panel would be unreachable for the rest of the session.
  const closeResult = useCallback(() => {
    setResult(null);
    setActiveId(null);
    setHistoryToken((n) => n + 1);
  }, []);

  const clipCount = useMemo(() => result?.clips.length ?? 0, [result]);

  const activeClip = useMemo(
    () => result?.clips.find((c) => c.id === activeId) ?? null,
    [result?.clips, activeId],
  );

  // Title wrapping decides the line count, which drives the default
  // positions and the font size. Derived, never stored.
  // Prefix and suffix are part of the title the renderer draws, wraps and
  // checks for emoji (main.py:2480-2484), so they are here too.
  const titleRender = useMemo(() => {
    const base = activeClip ? effectiveTitle(activeClip, customTitles) : '';
    const raw = base ? `${studio.titlePrefix}${base}${studio.titleSuffix}`.trim() : '';
    return formatTitleSmart(raw, studio.textCase, studio.titleFontSize);
  }, [activeClip, customTitles, studio.titlePrefix, studio.titleSuffix, studio.textCase, studio.titleFontSize]);

  // Re-apply the default title position when the line count changes, unless
  // the user has moved it themselves.
  useEffect(() => {
    if (!activeClip) return;
    dispatchStudio({ type: 'autoTitleY', value: defaultTitleY(studio.aspectRatio, titleRender.lineCount) });
  }, [activeClip, studio.aspectRatio, titleRender.lineCount]);

  /**
   * Positions clamped to the ceiling that applies right now.
   *
   * The stored values are raw on purpose, so moving a slider and coming back
   * to a ratio remembers where it was. But the ceiling moves: a bigger title
   * font wraps to more lines, which lowers maxTitleY. A value set under the
   * old ceiling then sits above the new one.
   *
   * The backend already clamps (video_engine.py:774), so the render was
   * never wrong. The preview did not, so it drew the title somewhere the
   * export would not put it. These derived values keep both in step.
   */
  const safePos = useMemo(() => {
    const m = getMaxPositions(studio.aspectRatio, titleRender.lineCount);
    const c = getCenterBounds(studio.aspectRatio);
    return {
      titleY: Math.min(studio.titleYPercent, m.maxTitleY),
      subtitleY: Math.min(studio.subtitleYPercent, m.maxSubY),
      subtitleCenterY: Math.min(Math.max(studio.subtitleCenterYPercent, c.min), c.max),
    };
  }, [
    studio.aspectRatio,
    studio.titleYPercent,
    studio.subtitleYPercent,
    studio.subtitleCenterYPercent,
    titleRender.lineCount,
  ]);

  const selectedClips = useMemo(
    () => (result?.clips ?? []).filter((c) => marked[c.id]),
    [result?.clips, marked],
  );

  // Writes the new bounds back into the result and the cache, so a trim
  // survives a refresh. The old app only did this as a download side effect.
  const applyTrim = useCallback(
    (adjusted: ViralClip) => {
      setResult((prev) => {
        if (!prev) return prev;
        const next = {
          ...prev,
          clips: prev.clips.map((c) => (c.id === adjusted.id ? adjusted : c)),
        };
        updateCachedResult(activeCacheKey.current, next);
        return next;
      });
      show(t.trimmer.applied);
    },
    [show, t.trimmer.applied],
  );

  const startRender = useCallback(() => {
    if (!result || selectedClips.length === 0) {
      show(t.render.selectFirst, 'info');
      return;
    }
    void render.start(buildRenderPayload(result, selectedClips, studio, customTitles));
  }, [result, selectedClips, studio, customTitles, render, show, t.render.selectFirst]);

  // Each recovery button maps to something the user can actually do here.
  const recover = useCallback(
    (action: RecoveryAction) => {
      if (action === 'encoder') {
        dispatchStudio({ type: 'set', patch: { hardwareAccel: 'cpu' } });
        show(t.render.recover.encoder);
      } else if (action === 'captions') {
        dispatchStudio({ type: 'setCaptionsEnabled', enabled: false });
        show(t.render.recover.captions);
      } else if (action === 'clearTemp') {
        void api.temp
          .clear()
          .then(() => show(t.render.recover.clearTemp))
          .catch(() => show(t.studio.uploadFailed, 'error'));
      } else if (action === 'retry') {
        startRender();
      } else if (action === 'cookies') {
        setCookiesOpen(true);
      }
    },
    [show, t.render.recover, t.studio.uploadFailed, startRender],
  );

  const errorView = error
    ? analyzeErrorView(errorCode, error, t, {
        retryAt: errorRetryAt,
        locale: language === 'id' ? 'id-ID' : 'en-US',
      })
    : null;

  return (
    <div className="min-h-[100dvh] bg-canvas">
      <header className="sticky top-0 z-[--z-sticky] border-b border-hairline bg-canvas/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-3 px-4">
          <FilmStripIcon size={20} weight="duotone" className="shrink-0 text-accent" />
          <span className="font-display text-sm font-semibold tracking-tight">{t.app.name}</span>

          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setCookiesOpen(true)}
              icon={<CookieIcon size={14} weight={hasCookies ? 'fill' : 'regular'} />}
              className={hasCookies ? 'text-positive' : undefined}
            >
              {t.nav.cookies}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setLanguage(language === 'id' ? 'en' : 'id')}
              aria-label={t.nav.language}
            >
              {language === 'id' ? 'ID' : 'EN'}
            </Button>
            <ThemeToggle theme={theme} onToggle={toggle} />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-4 py-6">
        <ErrorBoundary section={t.form.urlLabel}>
          <AnalyzeForm
            onSubmit={runAnalysis}
            busy={busy}
            onKeyCleared={() => show(t.form.apiKeyCleared)}
          />
        </ErrorBoundary>

        {busy && (
          <div className="mt-4">
            <AnalyzeProgress progress={progress} elapsedSeconds={elapsed} />
          </div>
        )}

        {/* Shown before a result; closeResult brings it back afterwards. */}
        {!result && !busy && (
          <ErrorBoundary section={t.results.historyTitle}>
            <div className="mt-4">
              <HistoryPanel refreshToken={historyToken} onOpen={openFromHistory} />
            </div>
          </ErrorBoundary>
        )}

        {status === 'error' && error && (
          <div className="mt-4">
            <Panel>
              <div className="flex items-start gap-3">
                <WarningCircleIcon
                  size={18}
                  weight="fill"
                  className="mt-0.5 shrink-0 text-critical-text"
                />
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-medium text-critical-text">
                    {t.errors.analysisFailed}
                  </h2>
                  <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-ink-dim">
                    {errorView?.message}
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {errorView?.keyProblem && (
                      <Button
                        size="sm"
                        icon={<KeyIcon size={14} />}
                        onClick={() => focusApiKeyField(API_KEY_INPUT_NAME)}
                      >
                        {t.errors.changeKey}
                      </Button>
                    )}
                    {lastRequest && (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => void runAnalysis(lastRequest)}
                      >
                        {t.errors.tryAgain}
                      </Button>
                    )}
                    {errorView?.keyProblem && (
                      <a
                        href={AI_STUDIO_KEY_URL}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-xs font-medium text-teal-text underline underline-offset-2"
                      >
                        {t.errors.getKey}
                        <ArrowSquareOutIcon size={12} />
                      </a>
                    )}
                  </div>
                </div>
              </div>
            </Panel>
          </div>
        )}

        {result && (
          <div className="mt-6 grid items-start gap-4 lg:grid-cols-[minmax(320px,400px)_1fr]">
            <div className="grid content-start gap-4">
              <ErrorBoundary section={t.player.sourceVideo}>
                <Panel title={result.title} subtitle={result.channel ?? undefined}>
                  <VideoPlayer
                    result={result}
                    activeClip={activeClip}
                    seekToClip={autoPlayClip}
                    heatmapLabel={t.player.heatmap}
                    heatmapEmptyLabel={t.player.heatmapEmpty}
                    onPlayed={() => undefined}
                  />
                  {result.summary && (
                    <p className="mt-3 text-xs leading-relaxed text-ink-dim">{result.summary}</p>
                  )}
                </Panel>
              </ErrorBoundary>


            </div>

            <ErrorBoundary section={t.results.clipsFound(clipCount)}>
              {/* The list scrolls inside itself, so picking a clip further
                  down does not scroll the player and preview out of view. */}
              <div className="top-[4.5rem] lg:sticky lg:max-h-[calc(100dvh-6rem)]
                lg:overflow-y-auto lg:pr-1">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <h2 className="font-display text-sm font-semibold">
                    {t.results.clipsFound(clipCount)}
                  </h2>
                  <button
                    type="button"
                    onClick={closeResult}
                    className="pressable shrink-0 text-[0.8rem] font-semibold text-ink-dim
                      underline hover:text-ink"
                  >
                    {t.results.historyBack}
                  </button>
                </div>
                <ClipList
                  clips={result.clips}
                  marked={marked}
                  activeId={activeId}
                  onToggleMark={toggleMark}
                  onSelect={(c) => setActiveId(c.id)}
                  onPreview={(c) => {
                    setActiveId(c.id);
                    setAutoPlayClip(true);
                  }}
                  onTrim={(c) => setTrimClip(c)}
                  onCopy={copy}
                />
              </div>
            </ErrorBoundary>
          </div>
        )}


        {result && (
          <ErrorBoundary section={t.studio.title}>
            <section className="mt-6">
              <h2 className="mb-3 font-display text-sm font-semibold">{t.studio.title}</h2>

              <div className="grid items-start gap-5 xl:grid-cols-[1fr_368px]">
                <div className="min-w-0">
                  <StudioPanel
                    state={studio}
                    dispatch={dispatchStudio}
                    titleLines={titleRender.lineCount}
                    sampleTitle={
                      activeClip ? effectiveTitle(activeClip, customTitles) : t.studio.fileNameGroup
                    }
                    aiTitle={activeClip?.title_suggestion ?? activeClip?.title}
                    customTitle={activeClip ? (customTitles[activeClip.id] ?? '') : ''}
                    titleOptions={activeClip?.title_options}
                    onCustomTitleChange={
                      activeClip
                        ? (value) =>
                            setCustomTitles((prev) => {
                              const next = { ...prev };
                              // An empty box means "use the AI title", so the
                              // key is removed rather than stored blank.
                              if (value.trim() === '') delete next[activeClip.id];
                              else next[activeClip.id] = value;
                              return next;
                            })
                        : undefined
                    }
                    onError={(msg) => show(msg, 'error')}
                  />

                  <div className="mt-4 flex flex-wrap items-center gap-3">
                    <Button
                      size="lg"
                      loading={render.status === 'starting'}
                      disabled={selectedClips.length === 0 || render.status === 'running'}
                      onClick={startRender}
                    >
                      {t.render.start}
                    </Button>
                    <span className="text-xs text-ink-dim">
                      {selectedClips.length > 0
                        ? t.render.selectedCount(selectedClips.length)
                        : t.render.selectFirst}
                    </span>
                  </div>

                  {render.progress && (
                    <div className="mt-4">
                      <RenderQueue
                        progress={render.progress}
                        lostContact={render.lostContact}
                        fileNamePrefix={studio.fileNamePrefix}
                        fileNameSuffix={studio.fileNameSuffix}
                        onReconnect={() => render.reconnect()}
                        onDismiss={render.dismiss}
                        onRecover={recover}
                      />
                    </div>
                  )}
                </div>

                {/* Sticky, so the preview stays in view while the controls
                    scroll. Without this every tweak means scrolling back up. */}
                {/* min-w-0: a grid item is otherwise as wide as its content, so the
                    preview could never shrink to fit a phone (#20). */}
                <aside className="top-[4.5rem] min-w-0 xl:sticky">
                  <Panel title={t.player.clipPreview} subtitle={t.player.clipPreviewHint}>
                    {activeClip ? (
                      <ClipPreview
                        key={activeClip.id}
                        videoId={result.video_id}
                        clip={activeClip}
                        transcript={result.transcript}
                        aspectRatio={studio.aspectRatio}
                        streamerPreset={studio.streamerPreset}
                        bgmUrl={studio.bgmUrl}
                        bgmEnabled={studio.bgmEnabled}
                        bgmVolume={studio.bgmVolume}
                        bgmStartOffset={studio.bgmStartOffset}
                        sfxUrl={studio.hookSfxUrl}
                        sfxEnabled={studio.hookSfxEnabled}
                        sfxVolume={studio.hookSfxVolume}
                        soundOn={previewSound}
                        onToggleSound={() => setPreviewSound((v) => !v)}
                        soundLabel={t.player.previewSound}
                        backgroundStyle={studio.backgroundStyle}
                        enableFaceTracking={studio.enableFaceTracking}
                        title={studio.titlePosition === 'none' ? undefined : titleRender.formatted}
                        titleYPercent={safePos.titleY}
                        titleFontSize={studio.titleFontSize}
                        watermarkEnabled={studio.watermarkEnabled}
                        watermarkType={studio.watermarkType}
                        watermarkUrl={studio.watermarkUrl}
                        watermarkText={studio.watermarkText}
                        watermarkSize={studio.watermarkSize}
                        watermarkOpacity={studio.watermarkOpacity}
                        watermarkX={studio.watermarkX}
                        watermarkY={studio.watermarkY}
                        captionStyle={studio.captionStyle}
                        captionFont={studio.captionFont}
                        fontSize={studio.fontSize}
                        textCase={studio.textCase}
                        subtitlePositionMode={studio.subtitlePositionMode}
                        subtitleYPercent={safePos.subtitleY}
                        subtitleCenterYPercent={safePos.subtitleCenterY}
                        autoPlay={autoPlayClip}
                        label={t.player.playPause}
                        faceTrackingLabel={t.studio.faceTrackingOn}
                      />
                    ) : (
                      <div className="grid place-items-center rounded-[--radius-control]
                        border border-dashed border-hairline py-12 text-center">
                        <p className="text-xs text-ink-dim">{t.player.noClipSelected}</p>
                      </div>
                    )}
                  </Panel>
                </aside>
              </div>
            </section>
          </ErrorBoundary>
        )}

        {result && (
          <ErrorBoundary section={t.tools.title}>
            <section className="mt-6">
              <ToolsPanel
                result={result}
                activeClip={activeClip}
                videoUrl={lastRequest?.url ?? `https://www.youtube.com/watch?v=${result.video_id}`}
                onNotice={(msg, tone) => show(msg, tone ?? 'info')}
              />
            </section>
          </ErrorBoundary>
        )}
      </main>

      <CookiesModal
        open={cookiesOpen}
        onClose={() => setCookiesOpen(false)}
        onChanged={setHasCookies}
      />

      {/* Mounted only while trimming, so it never sees a null clip. */}
      {trimClip && result && (
        <TrimmerModal
          open
          clip={trimClip}
          videoId={result.video_id}
          videoDuration={result.duration}
          onApply={applyTrim}
          onClose={() => setTrimClip(null)}
        />
      )}

      <Toast toast={toast} onDismiss={dismiss} />
    </div>
  );
}

/** Default title position for a ratio and line count. */
function defaultTitleY(ratio: Parameters<typeof getDefaultPositions>[0], lines: number): number {
  return getDefaultPositions(ratio, lines).titleY;
}

/** Pulls the 11-character video id out of the usual YouTube URL shapes. */
function extractVideoId(url: string): string {
  const trimmed = url.trim();
  if (/^[a-zA-Z0-9_-]{11}$/.test(trimmed)) return trimmed;

  const patterns = [
    /[?&]v=([a-zA-Z0-9_-]{11})/,
    /youtu\.be\/([a-zA-Z0-9_-]{11})/,
    /\/(?:embed|v|shorts|live)\/([a-zA-Z0-9_-]{11})/,
  ];
  for (const re of patterns) {
    const m = trimmed.match(re);
    if (m) return m[1];
  }
  return '';
}
