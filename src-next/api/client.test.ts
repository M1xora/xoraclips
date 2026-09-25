import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, UploadTooLargeError } from './client';

function fileOf(megabytes: number, name: string): File {
  const file = new File(['x'], name);
  Object.defineProperty(file, 'size', { value: megabytes * 1024 * 1024 });
  return file;
}

describe('upload limits (#58)', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('a watermark over 10 MB fails before it is sent', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const err = await api.uploads.watermark(fileOf(11, 'logo.png')).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(UploadTooLargeError);
    expect((err as Error).message).toContain('Maksimum 10 MB');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('music up to 50 MB is sent, over it fails', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ success: true })));
    vi.stubGlobal('fetch', fetchMock);
    await api.uploads.bgm(fileOf(11, 'lagu.mp3'));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const err = await api.uploads.bgm(fileOf(51, 'lagu.mp3')).catch((e: unknown) => e);
    expect((err as Error).message).toContain('Maksimum 50 MB');
  });
});
