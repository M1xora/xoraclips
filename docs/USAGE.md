# Xoraclips — Panduan Pemakaian

[← README (English)](../README.md) | [← README (Bahasa Indonesia)](../README.id.md)

> Halaman ini berbahasa Indonesia.

[![Versi](https://img.shields.io/badge/versi-0.9.0--beta-orange)](https://github.com/M1xora/xoraclips/releases)

> **Status: beta.** Alur intinya sudah berjalan penuh dan dipakai merender
> video sungguhan, tapi pemasangannya belum diuji di banyak komputer. Kalau
> ada yang tidak jalan, [laporkan lewat Issues](https://github.com/M1xora/xoraclips/issues)
> — itu justru yang paling membantu sekarang.

Xoraclips mengubah video YouTube panjang jadi klip vertikal 1080x1920 yang siap diunggah ke TikTok, Shorts, atau Reels. Tempel link YouTube, AI Gemini memilih bagian yang paling menarik, lalu klip itu bisa diatur di Clip Studio sebelum dirender jadi MP4.

Aplikasi berjalan lokal di komputer sendiri: backend FastAPI mengurus unduhan, transkrip, dan render ffmpeg; frontend React jadi tempat mengatur dan melihat pratinjau.

## Fitur

- Analisis video YouTube dengan Gemini, hasilnya daftar klip beserta judul dan skor.
- Pilihan target durasi klip: 15s, 30s, 60s, 2 menit, atau 3 menit.
- Clip Studio: rasio dan crop, latar buram, tata letak split facecam dan PiP, judul, awalan/akhiran nama berkas.
- Face tracking: crop mengikuti posisi wajah pembicara.
- Subtitle per kata dengan beberapa gaya dan pilihan font, diambil dari caption YouTube.
- Audio: musik latar dan SFX dengan atur volume serta offset, bisa didengar di pratinjau.
- Watermark berupa gambar atau teks dengan preset posisi.
- Trimmer untuk memotong ulang awal/akhir klip.
- Render massal lalu unduh semua hasil dalam satu file ZIP.
- Pilihan encoder hardware (NVENC, AMF, QSV) atau CPU, dibaca dari mesin yang dipakai.
- Pengelola cookies YouTube untuk video yang minta login.

## Teknologi

**Frontend** — React 19, TypeScript, Vite, Tailwind CSS v4, Vitest, ESLint.

**Backend** — Python + FastAPI, yt-dlp, ffmpeg, OpenCV, google-genai (Gemini), youtube-transcript-api.

Subtitle otomatis (OpenAI Whisper) opsional, tidak ikut terpasang secara default. Lihat [Subtitle otomatis (opsional)](#subtitle-otomatis-opsional).

## Instalasi

### Windows (otomatis)

Klik dua kali `setup_and_run.bat`. Skrip ini memeriksa dan memasang Git, Node.js, Python, FFmpeg, dan yt-dlp lewat `winget`, membuat `venv`, memasang semua dependency, lalu menjalankan aplikasi.

### Manual (semua OS)

Prasyarat:

- Node.js 18 atau lebih baru
- Python 3.10 atau lebih baru
- ffmpeg dan yt-dlp tersedia di PATH

Windows:

```powershell
winget install Gyan.FFmpeg
winget install yt-dlp.yt-dlp
```

macOS:

```bash
brew install ffmpeg yt-dlp
```

Clone repo lalu pasang dependency project:

```bash
git clone https://github.com/M1xora/xoraclips.git
cd xoraclips
npm install
python -m pip install -r backend/requirements.txt
```

Di macOS pakai `python3` sebagai ganti `python`.

### Subtitle otomatis (opsional)

Pemasangan di atas **tidak** menyertakan Whisper, pembuat subtitle otomatis.
Alasannya ukuran: Whisper menarik `torch` dan paket pendukungnya, sekitar
**737 MB dari total 1 GB** pemasangan.

Tanpa Whisper, aplikasi tetap berjalan penuh:

| Video YouTube | Subtitle |
|---|---|
| Punya caption (paling banyak) | Tetap ada, diambil dari caption YouTube |
| Tidak punya caption | Klip tetap jadi, tapi **tanpa subtitle** |

Studio akan memberi tahu kalau Whisper belum terpasang, jadi Anda tidak perlu
menebak.

Kalau Anda sering memotong video yang tidak punya caption, pasang dengan:

```bash
python -m pip install -r backend/requirements-whisper.txt
```

Saat pertama dipakai, Whisper juga mengunduh modelnya sendiri (sekitar 145 MB).

### Update

```bash
git pull
npm install
python -m pip install -r backend/requirements.txt
```

## Menjalankan Project

Butuh dua terminal.

Backend:

```bash
python -m uvicorn backend.main:app --port 8000
```

Frontend:

```bash
npm run dev-next
```

Buka `http://localhost:5174/preview.html`. Harus `localhost`, bukan `127.0.0.1`, karena pemutar YouTube menolak origin lain.

Di Windows, setelah setup pertama bisa pakai `start-xoraclips.bat` untuk menjalankan keduanya dan `stop-xoraclips.bat` untuk menghentikannya.

### Perintah lain

| Perintah | Fungsi |
|---|---|
| `npm test` | Test frontend (Vitest) |
| `npm run typecheck-next` | Typecheck `src-next/` |
| `npm run build-next` | Build produksi `src-next/` |
| `npm run lint-next` | ESLint `src-next/` |
| `python -m pytest backend/tests -q` | Test backend |

## Struktur Project

```
backend/      FastAPI, ffmpeg, yt-dlp, Whisper. Endpoint di routes_*.py, render di video_engine.py
src-next/     Frontend. Kode dikelompokkan per fitur di features/
```

Di `src-next/`: `api/` klien HTTP ke backend, `features/` satu folder per fitur (analyze, studio, render, trimmer, cookies, export, download, player, clips), `components/` komponen UI bersama, `hooks/`, `lib/`, `styles/`, `i18n/`.

## Catatan

- **API key Gemini.** Key diisi sendiri oleh pengguna di form aplikasi, dikirim lewat header `X-Gemini-Api-Key`. Tidak ada key di sisi server, dan key tidak pernah ditulis ke log. Ambil key gratis di [Google AI Studio](https://aistudio.google.com/).
- **Mock mode.** Set `MOCK_MODE=1` di `.env` untuk mencoba aplikasi dengan data contoh tanpa key. Status ini terlihat di aplikasi.
- **Render gagal / "file not found".** Biasanya ffmpeg atau yt-dlp belum ada di PATH. Pasang lalu buka ulang terminal.
- **"Sign in to confirm you're not a bot".** YouTube minta login. Ekspor cookies YouTube dari browser (misalnya dengan ekstensi *Get cookies.txt locally*), lalu tempel di panel Cookies di aplikasi.
- **CORS.** Backend hanya menerima `http://localhost:5174` dan `http://127.0.0.1:5174`. Ubah lewat env `ALLOWED_ORIGINS` kalau pakai port lain.
- **Hak cipta.** Kode ini belum punya lisensi terbuka. Hak cipta ada pada
  pemiliknya, dan hak pemakaian belum diberikan ke siapa pun. Kalau Anda ingin
  memakai, mengubah, atau menyebarkannya, hubungi dulu lewat
  [Issues](https://github.com/M1xora/xoraclips/issues).
