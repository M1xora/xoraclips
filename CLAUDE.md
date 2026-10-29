# Xoraclips

Auto-clipper: analisis video YouTube dengan Gemini, pilih klip viral, edit di Studio, render ke MP4 vertikal 1080x1920.

- `src-next/`: frontend (React 19, TS strict, Vite, Tailwind v4). Semua pekerjaan frontend di sini.
- `backend/`: FastAPI + ffmpeg + yt-dlp + Whisper. **Jangan diubah tanpa persetujuan eksplisit di issue.**

## Perintah

| Perintah | Fungsi |
|---|---|
| `venv\Scripts\python -m uvicorn backend.main:app --port 8000` | Backend |
| `npm run dev-next` | Frontend baru, buka `http://localhost:5174/preview.html` (harus `localhost`) |
| `npm test` | Vitest |
| `npm run typecheck-next` | `tsc --strict` untuk `src-next/` |
| `npm run build-next` | Build `src-next/` |
| `npm run lint-next` | ESLint `src-next/` |

## Alur kerja wajib: Issue → Plan → Code → Review → Test → Merge

Setiap perubahan, sekecil apa pun, lewat alur ini. Tidak ada commit langsung ke `main`.

1. **Issue.** Pastikan ada issue GitHub untuk pekerjaan ini (`gh issue list`). Kalau belum ada, buat dengan `gh issue create` memakai format template (tujuan + kriteria selesai). Satu issue = satu PR.
2. **Plan.** Baca kode terkait, lalu tulis rencana sebagai komentar di issue (`gh issue comment`): file yang diubah, pendekatan, test yang ditambah, risiko. **Tunggu persetujuan user sebelum ngoding.** Kalau rencana menyentuh `backend/`, sebutkan terang-terangan.
3. **Code.** Dari `main` terbaru: `git switch main && git pull && git switch -c <tipe>/<nomor-issue>-<slug>`. Tipe: `feat`, `fix`, `chore`, `refactor`, `docs`. Commit kecil dengan pesan jelas.
4. **Review.** Jalankan `/code-review` pada perubahan, tangani temuannya, lalu buka PR dengan `gh pr create` (template PR terisi, badan berisi `Closes #<nomor>`).
5. **Test.** Sebelum push, jalankan lokal `npm test`, `npm run typecheck-next`, `npm run build-next`, `npm run lint-next`. Setelah push, pantau CI (`gh pr checks`) sampai hijau. Untuk perubahan render/Studio, buktikan dengan render sungguhan bila memungkinkan.
6. **Merge.** **User yang klik Merge** (squash). Claude tidak merge sendiri. Setelah merge: `git switch main && git pull`.

## Aturan lain

- Author commit adalah M1xora (git config). Claude hanya menambah baris `Co-Authored-By`.
- Jangan mengarang hasil test, benchmark, atau fitur. Kalau tidak bisa diverifikasi, bilang begitu.
- User berbahasa Indonesia dan suka jawaban singkat.
- Status fitur dan catatan teknis ada di `src-next/TODO.md`.
