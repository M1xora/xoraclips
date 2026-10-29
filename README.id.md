# Xoraclips

[English](README.md) | [Bahasa Indonesia](README.id.md)

[![Versi](https://img.shields.io/badge/versi-0.9.5--beta-orange)](https://github.com/M1xora/xoraclips/releases)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178C6?logo=typescript&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)

> **Beta.** Alur intinya sudah berjalan dan dipakai merender video sungguhan,
> tapi pemasangannya baru diuji di komputer saya sendiri. Kalau ada yang tidak
> jalan, [laporkan lewat Issues](https://github.com/M1xora/xoraclips/issues) —
> itu yang paling membantu sekarang.

Mengubah video YouTube yang panjang jadi klip vertikal 1080x1920 siap unggah ke TikTok, Shorts, dan Reels. Tempel link, Gemini memilih bagian yang menarik, lalu tiap klip diatur di Studio sebelum dirender jadi MP4.

Dibuat untuk kreator solo dan channel kecil yang selama ini memotong klip manual dan ingin pass pertamanya dikerjakan otomatis. Aplikasi berjalan lokal di komputer sendiri.

**1.296 test** · **78 klip** dirender sungguhan · **ukuran install turun 74%** (1029 → 268 MB) · **60 pull request** direview dan di-merge

## Demo

Belum ada demo online — aplikasi jalan lokal dan butuh `ffmpeg` serta `yt-dlp` terpasang.

Tempel link, pilih target durasi, dapat klip berskor lengkap dengan caption siap posting:

![Mencari klip dalam video](docs/screenshot.png)

Lalu atur framing, judul, dan subtitle sebelum dirender:

![Clip Studio](docs/screenshot-studio.png)

## Fitur

- **Pemilihan klip oleh AI** — Gemini membaca transkrip dan mengembalikan klip beserta skor, judul hook (tiga pilihan per klip), dan caption berisi hashtag yang siap diposting. Target durasi: 15 detik, 30 detik, 60 detik, 2 menit, atau 3 menit.
- **Clip Studio** — rasio keluaran, latar margin hitam atau buram, tata letak split facecam dan PiP, judul, watermark, awalan dan akhiran nama berkas.
- **Face tracking** — crop mengikuti wajah pembicara, dengan kontrol manual kalau perlu dibantu.
- **Subtitle per kata** — 7 gaya, 8 font, ukuran dan posisi, diambil dari caption YouTube (Whisper hanya cadangan opsional).
- **Audio** — musik latar dan efek suara pembuka dengan volume serta offset, bisa langsung didengar di preview.
- **Render dan ekspor** — render massal dengan encoder hardware (NVENC, AMF, QSV) yang dideteksi per mesin, plus ekspor ke JSON, Markdown, SRT, dan timestamp chapter YouTube.

## Tech stack

**Frontend** — React 19, TypeScript (strict), Vite 8, Tailwind CSS v4, Vitest, ESLint.

**Backend** — Python 3.10+, FastAPI, yt-dlp, ffmpeg, OpenCV, google-genai (Gemini), youtube-transcript-api. OpenAI Whisper opsional.

## Cara menjalankan

### Prasyarat

- Node.js 18 atau lebih baru
- Python 3.10 atau lebih baru
- `ffmpeg` dan `yt-dlp` tersedia di PATH
- API key Gemini gratis dari [Google AI Studio](https://aistudio.google.com/) — diisi di aplikasi, bukan di file

Install ffmpeg dan yt-dlp:

```bash
# Windows
winget install Gyan.FFmpeg
winget install yt-dlp.yt-dlp

# macOS
brew install ffmpeg yt-dlp
```

### Langkah

1. Clone repository.

   ```bash
   git clone https://github.com/M1xora/xoraclips.git
   cd xoraclips
   ```

2. Install dependency.

   ```bash
   npm install
   python -m pip install -r backend/requirements.txt
   ```

3. Jalankan backend (terminal pertama).

   ```bash
   python -m uvicorn backend.main:app --port 8000
   ```

4. Jalankan frontend (terminal kedua).

   ```bash
   npm run dev-next
   ```

5. Buka `http://localhost:5174/preview.html`. Harus `localhost`, bukan `127.0.0.1` — player YouTube menolak origin lain.

Di Windows, `setup_and_run.bat` melakukan semua langkah di atas otomatis, lalu `start-xoraclips.bat` / `stop-xoraclips.bat` untuk menjalankan dan menghentikan kedua server.

Catatan setup lengkap, troubleshooting, dan cara memasang Whisper opsional ada di [docs/USAGE.md](docs/USAGE.md).

## Environment variables

Tidak ada API key di sisi server. Tiap pengguna mengisi key Gemini-nya sendiri di form aplikasi; key dikirim lewat header `X-Gemini-Api-Key`, dipakai hanya untuk request itu, dan tidak pernah disimpan atau masuk log.

Semua di bawah ini opsional. Copy `backend/.env.template` jadi `backend/.env` lalu isi seperlunya — template-nya tidak berisi nilai asli.

| Variable | Fungsinya |
|---|---|
| `MOCK_MODE` | `true` membuat analisis mengembalikan data contoh tanpa memanggil Gemini atau YouTube. Untuk test dan demo. |
| `ALLOWED_ORIGINS` | Daftar origin browser yang boleh membaca response API (CORS), dipisah koma. Default-nya port dev lokal. |
| `SUPADATA_API_KEYS` | Key Supadata untuk mengambil transkrip lewat IP residensial. Dipisah koma untuk rotasi bergantian. |
| `WEBSHARE_USERNAME` / `WEBSHARE_PASSWORD` | Kredensial rotating proxy Webshare, dipakai saat YouTube memblokir IP untuk request transkrip. |
| `WEBSHARE_LOCATIONS` / `WEBSHARE_RETRIES` | Daftar negara proxy dan jumlah percobaan ulang. |
| `WEBSHARE_PROXY` / `PROXY_URL` | URL proxy lengkap sebagai ganti pasangan username/password. |
| `REQUESTS_CA_BUNDLE` | Path ke CA bundle sendiri, untuk proxy kantor yang memeriksa SSL. |
| `EMOJI_FONT_PATH` | Path ke font emoji berwarna. Kalau kosong, dipakai `seguiemj.ttf` bawaan. |

## Testing

```bash
npm test                              # frontend — 481 test, 36 file (Vitest)
python -m pytest backend/tests -q     # backend — 815 test (pytest)
npm run typecheck-next                # tsc --strict
npm run lint-next                     # ESLint
npm run build-next                    # build produksi
```

Totalnya 1.296 test. CI menjalankan semuanya di tiap pull request.

## Struktur folder

```
backend/          FastAPI, ffmpeg, yt-dlp. Endpoint di routes_*.py, render di video_engine.py
backend/tests/    Suite pytest, dengan fixture transkrip dan jawaban Gemini sungguhan
src-next/         Frontend
  api/            Klien HTTP ke backend
  features/       Satu folder per fitur: analyze, studio, render, trimmer, player, export, …
  components/     Komponen UI bersama
  hooks/ lib/     Hook dan helper bersama
```

## Kontribusi saya

Proyek ini berangkat dari [cheat-clip-pro](https://github.com/galihjuansaputra/cheat-clip-pro) (lihat [Kredit](#kredit)). Proyek itu sudah mengerjakan tugas intinya — Gemini membaca transkrip untuk memilih klip, progress yang mengalir ke browser, crop yang mengikuti wajah, render batch — dan sampai sekarang masih jadi tulang punggungnya di sini.

Yang belum ada di sana adalah jaring pengaman: tidak ada test, tidak ada CI, dan logika yang menentukan di mana sebuah klip dimulai masih menyatu dengan kode yang berbicara ke ffmpeg. Ke situlah sebagian besar pekerjaan di fork ini pergi.

**Yang ditambahkan di sini:**

| Bagian | Yang ditambahkan |
|---|---|
| **Monolith yang dipecah** | Proyek asal menaruh analisisnya di satu router 1.764 baris; di sini 807 baris, dengan keputusan-keputusannya dipindah ke file kecil yang berdiri sendiri — di mana klip dimulai dan berakhir, kalimat mana yang jadi jangkarnya, bagaimana judul dibentuk, berapa klip yang muat di rentang yang dicari. Backend-nya 8.527 baris berbanding 11.088 baris di proyek asal, dengan fitur yang lebih banyak. |
| **Test suite, dari nol** | 815 test backend dan 481 test frontend, dijalankan CI di tiap pull request. Proyek asalnya tidak punya test maupun CI. Pemecahan di atas yang membuatnya mungkin: logika yang masih menyatu dengan ffmpeg dan HTTP tidak bisa dites, jadi harus dikeluarkan dulu. |
| **Klip yang berhenti di akhir kalimat** | Batas klip ditarik ke akhir kalimat terdekat, dan tiap klip menyimpan kalimat yang jadi jangkarnya, jadi klip tidak lagi terpotong di tengah kata. |
| **Kunci API milik pengguna sendiri** | Kunci Gemini hanya diambil dari header request — tidak pernah dari berkas di server, tidak disimpan, dan disensor sebelum apa pun sampai ke log. |
| **Error yang memberi tahu harus apa** | Limit Gemini, kuota habis, dan YouTube yang menolak transkrip masing-masing menghasilkan pesan khusus, bukan sekadar request gagal. |
| **Jumlah klip yang muat di videonya** | Proyek asal sudah punya cadangan dari bagian video paling ramai saat Gemini tidak mengembalikan apa pun. Yang ditambahkan di sini: tidak pernah meminta klip lebih banyak daripada yang muat di rentang yang benar-benar dicari, jadi klip cadangannya tidak bisa saling tumpang tindih. |
| **Tampilan yang ditulis ulang** | `src-next/` adalah build baru React 19 + TypeScript (strict): Studio, trimmer, player, dan format ekspornya. |

Dikerjakan sebagai repo satu maintainer dengan alur penuh Issue → Plan → Code → Review → Test → Merge: 70 issue ditutup lewat 60 pull request yang direview, dengan CI hijau di setiap merge.

## Yang saya pelajari

- **Render video itu soal kasus pinggiran.** Jalur normalnya cepat selesai; waktunya habis di klip yang terpotong di tengah kalimat, video tanpa transkrip, dan YouTube yang tiba-tiba minta login. Sebagian besar dari 815 test backend lahir dari salah satu masalah itu.
- **Bergantung pada API luar berarti harus siap saat API-nya down.** Gemini mengembalikan 503 saat ramai, jadi backend mencoba ulang dan turun ke rantai model cadangan, bukan menggagalkan seluruh analisis.
- **Test yang bikin saya berani refactor.** Logika murni — batas klip, timing caption, aturan judul — ditaruh di file sendiri tanpa React atau ffmpeg, jadi bisa dites langsung dan diubah tanpa was-was.
- **Mengukur lebih baik daripada menebak.** Ukuran install ternyata penghalang terbesar buat pengguna baru, jadi saya ukur lalu bikin Whisper opsional: ~737 MB dari total ~1029 MB pemasangan tidak lagi ikut terpasang.

## Keterbatasan

- **Belum dipaketkan.** Node, Python, ffmpeg, dan yt-dlp harus dipasang sendiri. Instalasinya baru diuji di komputer pengembang.
- **Timing subtitle masih bisa meleset.** Pergeseran yang terukur ke dua arah (-1,8 detik sampai +1,4 detik) dibanding caption YouTube, jadi satu setelan offset saja tidak akan menyelesaikannya. Belum terpecahkan.
- **Face tracking kadang perlu dibantu.** Facecam di pojok dan footage game yang gelap masih mengandalkan kontrol manual.
- **Masih beta.** Versi 0.9.5. Alur intinya jalan dan sudah merender video sungguhan, tapi belum dipakai dalam skala besar.

## Rencana pengembangan

- Membuat aplikasi lebih mudah dipasang untuk orang yang bukan developer.
- Memperbaiki pergeseran subtitle, yang masih butuh lebih banyak sample video untuk didiagnosis.

## Kredit

Dibangun di atas **[cheat-clip-pro](https://github.com/galihjuansaputra/cheat-clip-pro)** karya **[galihjuansaputra](https://github.com/galihjuansaputra)**, yang menurut README-nya dirilis dengan Lisensi MIT. Struktur awal proyek dan sebagian pipeline video di backend berasal dari sana; yang dibangun di atasnya ada di [Kontribusi saya](#kontribusi-saya).

Juga dibangun di atas: [yt-dlp](https://github.com/yt-dlp/yt-dlp), [FFmpeg](https://ffmpeg.org/), [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api), [OpenCV](https://opencv.org/), dan [Whisper](https://github.com/openai/whisper).

## Author

**M1xora** — [GitHub](https://github.com/M1xora)

Kode ini belum punya lisensi terbuka; semua hak dipertahankan. Hubungi lewat [Issues](https://github.com/M1xora/xoraclips/issues) dulu kalau ingin memakai atau menyebarkannya.
