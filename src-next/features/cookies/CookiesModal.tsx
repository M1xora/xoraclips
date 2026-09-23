import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircleIcon, CookieIcon, TrashIcon, UploadSimpleIcon } from '@phosphor-icons/react';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import { api, type CookieStatus } from '../../api/client';
import { formatBytes } from '../../lib/format';
import { useLanguage } from '../../i18n';

interface CookiesModalProps {
  open: boolean;
  onClose: () => void;
  onChanged: (hasCookies: boolean) => void;
}

/**
 * Saves the YouTube cookies yt-dlp uses to get past bot checks.
 *
 * GET /api/cookies returns the whole file (main.py:2767). The old modal put
 * that straight into a textarea, leaving live session cookies sitting in the
 * DOM every time it opened. Here only the status and the domain count are
 * shown; the contents are never read back into the page.
 */
export function CookiesModal({ open, onClose, onChanged }: CookiesModalProps) {
  const { t } = useLanguage();
  const [status, setStatus] = useState<CookieStatus | null>(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await api.cookies.status();
      setStatus(res);
      onChanged(res.exists);
    } catch {
      setStatus(null);
    }
  }, [onChanged]);

  // Opening starts clean: reset while rendering when `open` flips (#2).
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setMessage(null);
      setConfirmDelete(false);
    }
  }

  useEffect(() => {
    if (!open) return;
    let live = true;
    api.cookies
      .status()
      .then((res) => {
        if (!live) return;
        setStatus(res);
        onChanged(res.exists);
      })
      .catch(() => {
        if (live) setStatus(null);
      });
    return () => {
      live = false;
    };
  }, [open, onChanged]);

  const save = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      await api.cookies.save(text);
      setText(''); // Do not keep the cookies in component state.
      setMessage({ text: t.cookies.saved, ok: true });
      await refresh();
    } catch (err) {
      setMessage({
        text: err instanceof Error ? err.message : t.cookies.saveFailed,
        ok: false,
      });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api.cookies.remove();
      setMessage({ text: t.cookies.deleted, ok: true });
      setConfirmDelete(false);
      await refresh();
    } catch {
      setMessage({ text: t.cookies.saveFailed, ok: false });
    } finally {
      setBusy(false);
    }
  };

  const readFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => setText(String(e.target?.result ?? ''));
    reader.onerror = () => setMessage({ text: t.cookies.readFailed, ok: false });
    reader.readAsText(file);
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t.cookies.title}
      size="md"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t.common.close}
          </Button>
          <Button onClick={save} loading={busy} disabled={!text.trim()}>
            {t.cookies.save}
          </Button>
        </div>
      }
    >
      <p className="text-xs leading-relaxed text-ink-dim">{t.cookies.why}</p>

      {status?.exists ? (
        <div className="mt-3 rounded-[--radius-control] border border-positive/40
          bg-positive/10 p-3">
          <p className="flex items-center gap-1.5 text-xs font-medium text-positive">
            <CheckCircleIcon size={14} weight="fill" />
            {t.cookies.active(formatBytes(status.size))}
          </p>
          {status.sample_lines.length > 0 && (
            <p className="mt-1 text-[0.8rem] text-ink-dim">
              {t.cookies.domains(status.sample_lines.length)}
            </p>
          )}

          {confirmDelete ? (
            <div className="mt-2 flex gap-2">
              <Button variant="danger" size="sm" loading={busy} onClick={remove}>
                {t.cookies.confirmDelete}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
                {t.common.cancel}
              </Button>
            </div>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={() => setConfirmDelete(true)}
              icon={<TrashIcon size={13} />}
            >
              {t.cookies.delete}
            </Button>
          )}
        </div>
      ) : (
        <div className="mt-3 flex items-center gap-2 rounded-[--radius-control]
          border border-caution/40 bg-caution/10 p-3">
          <CookieIcon size={15} className="shrink-0 text-caution" />
          <p className="text-xs text-caution">{t.cookies.none}</p>
        </div>
      )}

      <div className="mt-4">
        <input
          ref={fileRef}
          type="file"
          accept=".txt"
          className="sr-only"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) readFile(f);
          }}
        />
        <Button
          variant="secondary"
          size="sm"
          onClick={() => fileRef.current?.click()}
          icon={<UploadSimpleIcon size={13} />}
        >
          {t.cookies.choose}
        </Button>

        <label htmlFor="cookie-text" className="mt-3 block text-xs font-medium text-ink-dim">
          {t.cookies.paste}
        </label>
        <textarea
          id="cookie-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          spellCheck={false}
          autoComplete="off"
          placeholder="# Netscape HTTP Cookie File"
          className="mt-1.5 w-full rounded-[--radius-control] border border-hairline
            bg-surface-2 p-2.5 font-mono text-[0.8rem] text-ink placeholder:text-ink-faint"
        />
      </div>

      {message && (
        <p
          role="status"
          className={`mt-2 text-xs ${message.ok ? 'text-positive' : 'text-critical-text'}`}
        >
          {message.text}
        </p>
      )}
    </Modal>
  );
}
