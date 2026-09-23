import { useEffect, useRef, useState } from 'react';
import { FlaskIcon, SparkleIcon, UploadSimpleIcon, WarningIcon } from '@phosphor-icons/react';
import { Button } from '../../components/ui/Button';
import { Field } from '../../components/ui/Field';
import { Panel } from '../../components/ui/Panel';
import { SegmentedControl } from '../../components/ui/SegmentedControl';
import { Slider } from '../../components/ui/Slider';
import { useLocalStorage, useLocalStorageString } from '../../hooks/useLocalStorage';
import { api } from '../../api/client';
import type { AnalyzeRequest } from '../../hooks/useAnalyze';
import { useLanguage } from '../../i18n';
import { useServerAiStatus } from '../../hooks/useServerAiStatus';

const FALLBACK_MODELS = [
  'gemini-2.5-flash',
  'gemini-2.5-flash-lite',
  'gemini-2.0-flash',
  'gemini-2.0-flash-lite',
  'gemini-2.5-pro',
];

/** Accepts raw seconds, MM:SS or HH:MM:SS. Returns null when unparseable. */
export function parseTimeToSeconds(input: string): number | null {
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
  onSubmit: (payload: AnalyzeRequest) => void;
  busy: boolean;
}

export function AnalyzeForm({ onSubmit, busy }: AnalyzeFormProps) {
  const { t } = useLanguage();
  const [url, setUrl] = useState('');
  // The Gemini key lives only on the server (issue #8); ask whether it is set.
  const aiStatus = useServerAiStatus();
  const aiBlocked = aiStatus === 'notConfigured';
  const [model, setModel] = useLocalStorageString(
    'cheat_clip_selected_model',
    'gemini-2.5-flash',
  );
  const [clipCount, setClipCount] = useLocalStorage('cheat_clip_target_clip_count', 10);

  const [duration, setDuration] = useState<'15s' | '30s' | '60s'>('30s');
  const [prompt, setPrompt] = useState('');
  const [rangeType, setRangeType] = useState<'entire' | 'custom'>('entire');
  const [rangeStart, setRangeStart] = useState('');
  const [rangeEnd, setRangeEnd] = useState('');
  const [subtitleSource, setSubtitleSource] = useState<'youtube' | 'manual'>('youtube');
  const [subtitleText, setSubtitleText] = useState('');
  const [subtitleName, setSubtitleName] = useState('');

  const [models, setModels] = useState<string[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const fileRef = useRef<HTMLInputElement>(null);

  // The server's key decides which models exist; ask once it is known to be set.
  useEffect(() => {
    if (aiStatus !== 'ready') return;
    const controller = new AbortController();
    api
      .listModels(controller.signal)
      .then((res) => setModels(res.models ?? []))
      .catch(() => {
        // Keep the fallback list.
      });
    return () => controller.abort();
  }, [aiStatus]);

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

  const durations = [
    { value: '15s' as const, label: '15s', sub: t.form.durationHook },
    { value: '30s' as const, label: '30s', sub: t.form.durationShorts },
    { value: '60s' as const, label: '60s', sub: t.form.durationStory },
  ];
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
            disabled={aiBlocked}
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
            {aiStatus === 'notConfigured' && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-[--radius-control] border border-hairline
                  bg-surface-2 p-3 text-sm text-critical-text"
              >
                <WarningIcon size={16} className="mt-0.5 shrink-0" />
                <span>{t.form.aiNotConfigured}</span>
              </div>
            )}
            {aiStatus === 'mock' && (
              <div className="flex items-start gap-2 rounded-[--radius-control] border border-hairline bg-surface-2 p-3 text-sm">
                <FlaskIcon size={16} className="mt-0.5 shrink-0 text-teal-text" />
                <span>
                  <strong className="font-semibold">{t.form.mockMode}</strong>{' '}
                  <span className="text-ink-dim">{t.form.mockModeHint}</span>
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
