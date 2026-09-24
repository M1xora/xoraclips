import { useEffect, useRef, useState } from 'react';
import {
  ArrowSquareOutIcon,
  CheckCircleIcon,
  EyeIcon,
  EyeSlashIcon,
  FlaskIcon,
  SparkleIcon,
  TrashIcon,
  UploadSimpleIcon,
  WarningIcon,
} from '@phosphor-icons/react';
import { Button } from '../../components/ui/Button';
import { Field } from '../../components/ui/Field';
import { Panel } from '../../components/ui/Panel';
import { SegmentedControl } from '../../components/ui/SegmentedControl';
import { Slider } from '../../components/ui/Slider';
import { useLocalStorage, useLocalStorageString } from '../../hooks/useLocalStorage';
import { api, ApiError } from '../../api/client';
import type { AnalyzeRequest } from '../../hooks/useAnalyze';
import { durationOptions, type ClipDuration } from './clipDurations';
import { useLanguage } from '../../i18n';
import { useServerAiStatus } from '../../hooks/useServerAiStatus';
import { AI_STUDIO_KEY_URL, clearApiKey, loadApiKey, saveApiKey } from './apiKeyStore';

const FALLBACK_MODELS = [
  'gemini-2.5-flash',
  'gemini-2.5-flash-lite',
  'gemini-2.0-flash',
  'gemini-2.0-flash-lite',
  'gemini-2.5-pro',
];

/** Accepts raw seconds, MM:SS or HH:MM:SS. Returns null when unparseable. */
function parseTimeToSeconds(input: string): number | null {
  const raw = input.trim();
  if (!raw) return null;
  if (/^\d+(\.\d+)?$/.test(raw)) return Number(raw);

  const parts = raw.split(':');
  if (parts.length < 2 || parts.length > 3) return null;
  if (!parts.every((p) => /^\d+(\.\d+)?$/.test(p.trim()))) return null;

  const nums = parts.map((p) => Number(p.trim()));
  return nums.length === 3
    ? nums[0] * 3600 + nums[1] * 60 + nums[2]
    : nums[0] * 60 + nums[1];
}

interface AnalyzeFormProps {
  /** The key is not part of the payload: App reads it from apiKeyStore and sends it as a header. */
  onSubmit: (payload: AnalyzeRequest) => void;
  busy: boolean;
  onKeyCleared?: () => void;
}

/** `name` of the key input, so an error panel can focus it ("Change key"). */
export const API_KEY_INPUT_NAME = 'gemini-api-key';

/** Wait after typing/pasting before checking the key with Google. */
const KEY_CHECK_DELAY_MS = 600;
const MIN_KEY_LENGTH = 20;

type KeyCheck =
  | { key: string; state: 'valid'; models: string[] }
  | { key: string; state: 'invalid' | 'quota' | 'unknown' };

export function AnalyzeForm({ onSubmit, busy, onKeyCleared }: AnalyzeFormProps) {
  const { t } = useLanguage();
  const [url, setUrl] = useState('');
  // Mock mode (server .env) needs no key; otherwise the user's own key is required.
  const aiStatus = useServerAiStatus();
  const isMock = aiStatus === 'mock';
  // Only demand a key once the server is known not to be in mock mode; a
  // quick submit while /api/health is still loading is judged by the server.
  const keyRequired = aiStatus === 'normal';

  // The user's Gemini key (issue #12): typed here, sent only as a header.
  const [initialKey] = useState(() => loadApiKey());
  const [apiKey, setApiKey] = useState(initialKey.key);
  const [rememberKey, setRememberKey] = useState(initialKey.remember);
  const [showKey, setShowKey] = useState(false);
  const [keyCheck, setKeyCheck] = useState<KeyCheck | null>(null);
  const [model, setModel] = useLocalStorageString(
    'xoraclips_selected_model',
    'gemini-2.5-flash',
  );
  const [clipCount, setClipCount] = useLocalStorage('xoraclips_target_clip_count', 10);

  const [duration, setDuration] = useState<ClipDuration>('30s');
  const [prompt, setPrompt] = useState('');
  const [rangeType, setRangeType] = useState<'entire' | 'custom'>('entire');
  const [rangeStart, setRangeStart] = useState('');
  const [rangeEnd, setRangeEnd] = useState('');
  const [subtitleSource, setSubtitleSource] = useState<'youtube' | 'manual'>('youtube');
  const [subtitleText, setSubtitleText] = useState('');
  const [subtitleName, setSubtitleName] = useState('');

  const [errors, setErrors] = useState<Record<string, string>>({});
  const fileRef = useRef<HTMLInputElement>(null);

  const trimmedKey = apiKey.trim();

  // Check the key shortly after it is pasted: the model list request doubles
  // as a key check, so a wrong key shows up here instead of after a failed
  // analysis.
  useEffect(() => {
    if (isMock || trimmedKey.length < MIN_KEY_LENGTH) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api
        .listModels(trimmedKey, controller.signal)
        .then((res) => setKeyCheck({ key: trimmedKey, state: 'valid', models: res.models ?? [] }))
        .catch((err) => {
          if (controller.signal.aborted) return;
          const code = err instanceof ApiError ? err.code : undefined;
          const state = code === 'key_invalid' ? 'invalid' : code === 'key_quota' ? 'quota' : 'unknown';
          setKeyCheck({ key: trimmedKey, state });
        });
    }, KEY_CHECK_DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [trimmedKey, isMock]);

  // Only a check of the key currently in the field counts.
  const check = keyCheck && keyCheck.key === trimmedKey ? keyCheck : null;
  const keyStatus: 'idle' | 'checking' | KeyCheck['state'] =
    isMock || trimmedKey.length < MIN_KEY_LENGTH ? 'idle' : check ? check.state : 'checking';
  const models = check?.state === 'valid' ? check.models : [];

  const changeKey = (value: string) => {
    setApiKey(value);
    saveApiKey(value, rememberKey);
    if (errors.apiKey) {
      setErrors((prev) => {
        const next = { ...prev };
        delete next.apiKey;
        return next;
      });
    }
  };

  const changeRemember = (remember: boolean) => {
    setRememberKey(remember);
    saveApiKey(apiKey, remember);
  };

  const deleteSavedKey = () => {
    clearApiKey();
    setApiKey('');
    setKeyCheck(null);
    onKeyCleared?.();
  };

  const handleFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      setSubtitleText(String(e.target?.result ?? ''));
      setSubtitleName(file.name);
    };
    reader.onerror = () =>
      setErrors((p) => ({ ...p, subtitles: t.form.subtitleReadFailed }));
    reader.readAsText(file);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const next: Record<string, string> = {};

    if (!url.trim()) next.url = t.form.urlRequired;
    if (keyRequired && !trimmedKey) next.apiKey = t.form.apiKeyRequired;
    // Google already said no to this key: don't spend a run (and YouTube quota) on it.
    else if (keyStatus === 'invalid') next.apiKey = t.form.apiKeyInvalid;

    let startSecs: number | undefined;
    let endSecs: number | undefined;
    if (rangeType === 'custom') {
      const s = parseTimeToSeconds(rangeStart);
      const en = parseTimeToSeconds(rangeEnd);
      if (s === null) next.rangeStart = t.form.rangeFormat;
      if (en === null) next.rangeEnd = t.form.rangeFormat;
      if (s !== null && en !== null && en <= s) next.rangeEnd = t.form.rangeOrder;
      startSecs = s ?? undefined;
      endSecs = en ?? undefined;
    }

    if (subtitleSource === 'manual' && !subtitleText.trim()) {
      next.subtitles = t.form.subtitleRequired;
    }

    setErrors(next);
    if (Object.keys(next).length > 0) return;

    onSubmit({
      url: url.trim(),
      duration,
      model,
      custom_prompt: prompt.trim() || undefined,
      range_start: startSecs,
      range_end: endSecs,
      subtitles: subtitleSource === 'manual' ? subtitleText : undefined,
      subtitles_filename: subtitleSource === 'manual' ? subtitleName : undefined,
      target_clip_count: clipCount,
    });
  };

  const modelOptions = models.length > 0 ? models : FALLBACK_MODELS;

  const durations = durationOptions(t);
  const subtitleSources = [
    { value: 'youtube' as const, label: t.form.subtitleFromYoutube },
    { value: 'manual' as const, label: t.form.subtitleUpload },
  ];
  const rangeTypes = [
    { value: 'entire' as const, label: t.form.rangeEntire },
    { value: 'custom' as const, label: t.form.rangeCustom },
  ];

  return (
    <form onSubmit={submit} noValidate className="grid gap-4">
      <Panel>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
          <Field
            label={t.form.urlLabel}
            type="url"
            inputMode="url"
            placeholder={t.form.urlPlaceholder}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            error={errors.url}
            hint={t.form.urlHint}
            disabled={busy}
            className="flex-1"
          />
          <Button
            type="submit"
            size="lg"
            loading={busy}
            icon={<SparkleIcon size={16} weight="fill" />}
            className="sm:mt-6"
          >
            {busy ? t.form.submitBusy : t.form.submit}
          </Button>
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={t.form.engine}>
          <div className="grid gap-4">
            {!isMock && (
              <div className="grid gap-2">
                <Field
                  label={t.form.apiKeyLabel}
                  name={API_KEY_INPUT_NAME}
                  required
                  type={showKey ? 'text' : 'password'}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={t.form.apiKeyPlaceholder}
                  value={apiKey}
                  onChange={(e) => changeKey(e.target.value)}
                  error={errors.apiKey}
                  hint={t.form.apiKeyPrivacy}
                  disabled={busy}
                  trailing={
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowKey((v) => !v)}
                      icon={showKey ? <EyeSlashIcon size={14} /> : <EyeIcon size={14} />}
                      aria-label={showKey ? t.form.apiKeyHide : t.form.apiKeyShow}
                    />
                  }
                />

                <KeyStatus status={keyStatus} modelCount={models.length} />

                <div className="flex flex-wrap items-center justify-between gap-2">
                  <label
                    className="flex items-center gap-2 text-xs text-ink-dim"
                    title={t.form.apiKeyRememberHint}
                  >
                    <input
                      type="checkbox"
                      checked={rememberKey}
                      disabled={busy}
                      onChange={(e) => changeRemember(e.target.checked)}
                    />
                    {t.form.apiKeyRemember}
                  </label>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={busy || !apiKey}
                    onClick={deleteSavedKey}
                    icon={<TrashIcon size={14} />}
                  >
                    {t.form.apiKeyClear}
                  </Button>
                </div>

                <details
                  className="rounded-[--radius-control] border border-hairline bg-surface-2 p-3 text-xs"
                  open={!trimmedKey}
                >
                  <summary className="cursor-pointer font-medium text-ink">
                    {t.form.apiKeyGuideTitle}
                  </summary>
                  <ol className="mt-2 list-decimal space-y-1 pl-5 text-ink-dim">
                    <li>{t.form.apiKeyGuideStep1}</li>
                    <li>{t.form.apiKeyGuideStep2}</li>
                    <li>{t.form.apiKeyGuideStep3}</li>
                    <li>{t.form.apiKeyGuideStep4}</li>
                  </ol>
                  <a
                    href={AI_STUDIO_KEY_URL}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 inline-flex items-center gap-1 font-medium text-teal-text underline underline-offset-2"
                  >
                    {t.form.apiKeyGuideLink}
                    <ArrowSquareOutIcon size={12} />
                  </a>
                </details>
              </div>
            )}
            {aiStatus === 'mock' && (
              <div className="flex items-start gap-2 rounded-[--radius-control] border border-hairline bg-surface-2 p-3 text-sm">
                <FlaskIcon size={16} className="mt-0.5 shrink-0 text-teal-text" />
                <span>
                  <strong className="font-semibold">{t.form.mockMode}</strong>{' '}
                  <span className="text-ink-dim">
                    {t.form.mockModeHint} {t.form.apiKeyNotNeededMock}
                  </span>
                </span>
              </div>
            )}

            <div>
              <label htmlFor="model-select" className="text-xs font-medium text-ink-dim">
                {t.form.modelLabel}
              </label>
              <select
                id="model-select"
                value={model}
                disabled={busy}
                onChange={(e) => setModel(e.target.value)}
                className="mt-1.5 h-9 w-full rounded-[--radius-control] border border-hairline
                  bg-surface-2 px-2.5 text-sm text-ink"
              >
                {modelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
              <p className="mt-1.5 text-xs text-ink-faint">
                {models.length > 0 ? t.form.modelLive(models.length) : t.form.modelFallback}
              </p>
            </div>
          </div>
        </Panel>

        <Panel title={t.form.clipSettings}>
          <div className="grid gap-4">
            <SegmentedControl
              label={t.form.durationLabel}
              value={duration}
              options={durations}
              onChange={setDuration}
              disabled={busy}
              // Five lengths (#34): the hints do not fit a 360px phone.
              hideSubsOnPhone
            />

            <Slider
              label={t.form.clipCountLabel(clipCount)}
              value={clipCount}
              min={1}
              max={50}
              presets={[
                { label: '5', value: 5 },
                { label: '10', value: 10 },
                { label: '20', value: 20 },
                { label: '35', value: 35 },
              ]}
              onChange={setClipCount}
              disabled={busy}
            />

            <Field
              label={t.form.focusLabel}
              placeholder={t.form.focusPlaceholder}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={busy}
            />
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={t.form.subtitles}>
          <div className="grid gap-3">
            <SegmentedControl
              label={t.form.subtitleSource}
              value={subtitleSource}
              options={subtitleSources}
              onChange={setSubtitleSource}
              disabled={busy}
            />

            {subtitleSource === 'manual' && (
              <div>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".srt,.txt"
                  className="sr-only"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) handleFile(f);
                  }}
                />
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={busy}
                  onClick={() => fileRef.current?.click()}
                  icon={<UploadSimpleIcon size={14} />}
                >
                  {t.form.subtitleChoose}
                </Button>
                {subtitleName && (
                  <p className="mt-2 truncate text-xs text-ink-dim">{subtitleName}</p>
                )}
                {errors.subtitles && (
                  <p role="alert" className="mt-2 text-xs text-critical-text">
                    {errors.subtitles}
                  </p>
                )}
              </div>
            )}
          </div>
        </Panel>

        <Panel title={t.form.range}>
          <div className="grid gap-3">
            <SegmentedControl
              label={t.form.rangeScope}
              value={rangeType}
              options={rangeTypes}
              onChange={setRangeType}
              disabled={busy}
            />

            {rangeType === 'custom' && (
              <div className="grid grid-cols-2 gap-3">
                <Field
                  label={t.form.rangeStart}
                  placeholder="29:00"
                  value={rangeStart}
                  onChange={(e) => setRangeStart(e.target.value)}
                  error={errors.rangeStart}
                  disabled={busy}
                />
                <Field
                  label={t.form.rangeEnd}
                  placeholder="31:15"
                  value={rangeEnd}
                  onChange={(e) => setRangeEnd(e.target.value)}
                  error={errors.rangeEnd}
                  disabled={busy}
                />
              </div>
            )}
          </div>
        </Panel>
      </div>
    </form>
  );
}

/** One line under the key field: checking, valid, rejected, or out of quota. */
function KeyStatus({
  status,
  modelCount,
}: {
  status: 'idle' | 'checking' | 'valid' | 'invalid' | 'quota' | 'unknown';
  modelCount: number;
}) {
  const { t } = useLanguage();
  if (status === 'idle' || status === 'unknown') return null;
  if (status === 'checking') {
    return (
      <p className="text-xs text-ink-faint" aria-live="polite">
        {t.form.apiKeyChecking}
      </p>
    );
  }
  if (status === 'valid') {
    return (
      <p className="flex items-center gap-1.5 text-xs text-teal-text" aria-live="polite">
        <CheckCircleIcon size={14} weight="fill" />
        {t.form.apiKeyValid(modelCount)}
      </p>
    );
  }
  return (
    <p role="alert" className="flex items-start gap-1.5 text-xs text-critical-text">
      <WarningIcon size={14} className="mt-px shrink-0" />
      {status === 'invalid' ? t.form.apiKeyInvalid : t.form.apiKeyQuota}
    </p>
  );
}
