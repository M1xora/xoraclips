# Status: Alur Inti Selesai

Alur **Analyze, Studio, Render, Download** sudah berjalan penuh dan
terverifikasi dengan backend sungguhan.

| Pemeriksaan | Hasil |
|---|---|
| Vitest | 466 lolos, 35 berkas |
| Pytest (backend) | 691 lolos |
| `tsc --strict` | 0 error |
| Build | lolos |
| Lint | 0 error |
| Render sungguhan | MP4 1080x1920, 8 detik, 6,3 MB |

---

## Bukti render nyata

Payload dari kode baru dikirim ke backend yang benar-benar jalan:

```
POST /api/render-batch  ->  {"batch_id":"batch_...","total_clips":1}
SSE  17 event  ->  overall_status: completed
ffprobe  ->  width=1080  height=1920  duration=8.0
```

Video vertikal sungguhan, bukan sekadar "build sukses".

---

## Selesai sesi ini

**Subtitle per kata** (`features/studio/captions.ts`, `CaptionOverlay.tsx`)
7 gaya dengan warna asli dari versi lama. Memakai transkrip klip, bukan teks
contoh. Kata yang diucapkan diberi warna aksen dan sedikit diperbesar.
18 test, termasuk jaminan caption tidak terputus di tengah kalimat.

**Face tracking** (`hooks/useFaceBox.ts`)
Crop bergeser mengikuti posisi wajah. 10 test, termasuk bukti wajah
benar-benar masuk bingkai dan crop tidak pernah melewati tepi.
Versi lama memanggil endpoint ini lalu membuang hasilnya, jadi ini pertama
kalinya fitur tersebut terlihat.

**Panel Studio** (`features/studio/StudioPanel.tsx`)
Rasio, latar margin, face tracking, judul, subtitle lengkap, audio, watermark.

**Audio** BGM dan SFX dengan tarik-lepas, slider volume dan offset, penguat
suara asli. Kotak peringatan pemblokir versi lama diganti Toast.

**Watermark** gambar atau teks, ukuran, transparansi, 7 preset sudut, terlihat
langsung di pratinjau.

**Render massal** (`features/render/`)
Payload cocok persis dengan 38 field backend, tidak kurang tidak lebih, dengan
21 test yang membandingkannya langsung dengan `RenderSettingsModel`.
`transcript` diletakkan di level atas, tempat backend membacanya.

**Pemulihan error** kegagalan render dipetakan ke tombol yang benar-benar
bekerja: buka pengelola cookies, ganti ke encoder CPU, bersihkan berkas
sementara, matikan subtitle, coba lagi.

**Trimmer** (`features/trimmer/`) dengan tombol Terapkan tersendiri, sehingga
potongan tersimpan tanpa harus mengunduh. 18 test untuk aturan clamp.

**Cookies** (`features/cookies/`) hanya menampilkan status dan jumlah domain.
Isi cookie tidak pernah dimuat kembali ke halaman seperti versi lama.

---

## Selesai sesi ini (lanjutan)

**Tata letak streamer** (`StudioPanel.tsx`, `canvas.ts`, `ClipPreview.tsx`)
Split facecam dan PiP sudut, dengan diagram bentuk di tiap pilihan. Geometri
disalin dari `video_engine.py:1305-1445` ke `SPLIT_LAYOUT` dan `PIP_POS`,
dikunci 14 test. Pratinjau ikut berubah bentuk, jadi tidak berbohong seperti
bug rasio sebelumnya.

**Awalan/akhiran judul + durasi tampil** judul kini bisa dibungkus teks dan
dibatasi 5 atau 10 detik.

**Nama berkas** awalan dan akhiran, dengan contoh hasil yang memakai fungsi
`outputFileName` yang sama dengan antrean render dan backend.

**Kartu encoder** membaca `GET /api/hardware-accel` sungguhan. Encoder yang
tidak ada di mesin ditampilkan nonaktif, bukan ditawarkan lalu diam-diam
jatuh ke CPU. Di mesin ini: AMF tersedia, NVENC tidak.

**Audio terdengar di pratinjau** (`hooks/usePreviewAudio.ts`)
BGM dan SFX kini bisa didengar sambil mengatur slider. Mengikuti aturan
backend: BGM mulai dari offset, mengulang, dan meredup 1,5 detik di akhir
(`video_engine.py:1686-1694`); SFX sekali di frame pertama. 12 test untuk
rumus fade dan seek. Tombol suara hanya muncul kalau memang ada yang bisa
didengar, dan mati secara bawaan.

---

## Bukti render kedua

Render sungguhan memakai semua field yang tadinya tanpa UI:

```
settings: split_top_cam, 1:1, title_prefix, title_suffix,
          title_duration 5s, file_name_prefix/suffix, hardware_accel cpu

-> overall_status: completed
-> ffprobe   1080x1920, 8 detik
-> judul     "BAGIAN 1: Uji Coba Fitur | Klip"
-> zip       "Shorts_Uji Coba Fitur_1080p.mp4"
```

Nama berkas di zip sama persis dengan yang ditampilkan kolom contoh di UI.
Pengukuran piksel pada frame hasil: tepi kiri dan kanan di x=60 dan x=1020,
sama dengan `SPLIT_LAYOUT['1:1'].x = 60`.

---

## Yang masih terbuka

**1. Latar putih: ditutup**

Keputusan user: pakai blurred saja, tidak perlu putih. `backgroundStyle`
sekarang bawaannya `'blurred'`, bukan `'black'`, jadi bilah kosong terisi
frame klip yang diburamkan tanpa perlu diatur dulu. `video_engine.py` tidak
diubah.

**2. Facecam di pratinjau berupa gambar diam: diterima**

Keputusan user: pratinjau dibiarkan begini, yang penting hasil unduhan benar
(muka di atas, gameplay di bawah). Satu iframe YouTube tidak bisa tampil di
dua kotak sekaligus, jadi kotak facecam memakai frame klip yang di-crop ke
wajah. Geometrinya benar, isinya diam. Hasil render sudah diverifikasi.

**3. Split di 9:16 hanya mengisi separuh kanvas**

Bukan bug baru, memang begitu di `video_engine.py:1356-1369`: dua kotak
540x960 di kanvas 1080x1920, sisanya bilah. Terverifikasi lewat render
sungguhan, tepi video jatuh di x=810.

Karena 9:16 adalah rasio bawaan, UI sekarang memberi peringatan plus tombol
"Ganti ke 1:1" saat kombinasi itu dipilih. 5 test mengunci fakta bahwa 1:1
adalah rasio terbaik untuk split (89% kanvas) dan 9:16 yang terburuk (50%).

**4. Rename judul per klip: diperbaiki**

Ditemukan saat audit ulang, bukan dari daftar. `customTitles` dideklarasikan
tanpa setter (`const [customTitles] = useState({})`), jadi selamanya kosong:
backend mendukungnya, payload mengirimnya, `effectiveTitle` menanganinya,
tapi tidak ada yang bisa mengisinya. Fitur mati tanpa error.

Bug kedua yang menempel: `titleRender` memanggil `effectiveTitle(clip, {})`
dengan objek kosong, jadi andaikan pengisian itu jalan pun, pratinjau dan
jumlah baris tetap memakai judul AI, bukan judul gantinya.

Keduanya diperbaiki. Terverifikasi lewat render sungguhan: mengirim
`custom_title: "JUDUL GANTIAN SAYA"` menghasilkan judul dan nama berkas
"JUDUL GANTIAN SAYA", bukan "JUDUL AI ASLI".

**5. Ekspor, unduhan mentah, riwayat: selesai**

`features/export/` dan `features/download/`, dipasang sebagai satu panel di
bawah Studio, plus panel riwayat di atas sebelum ada hasil.

| Fitur | Bukti |
|---|---|
| Ekspor JSON & Markdown | 30 test, termasuk urutan klip dan JSON yang valid |
| Ekspor SRT per klip / penuh | ffprobe mengenalinya sebagai `subrip`, ffmpeg mengubahnya ke ASS dengan waktu utuh |
| Salin timestamp 3 format | Termasuk chapter YouTube yang wajib mulai 00:00 |
| Unduh video/klip mentah | Render sungguhan: 1920x1080, 6,02 detik, tanpa judul/subtitle |
| Info penyimpanan + bersihkan | Endpoint nyata, 24,72 MB / 17 berkas saat diuji |
| Riwayat analisis | 12 test, dibaca dari cache yang memang sudah ada |

Riwayat tidak menyimpan apa pun yang baru. Cache analisis sudah memuat tiap
hasil beserta waktunya, jadi riwayat hanya membacanya. Membuka dari riwayat
tidak memanggil Gemini.

Satu hal yang menempel: sebelum ini tidak ada jalan kembali dari hasil ke
formulir, jadi panel riwayat akan tak terjangkau seumur sesi. Ditambahkan
tombol "Riwayat & analisis baru" di header daftar klip.

**6. Belum dibangun**

`/api/supadata-usage` dan `/api/health`. Keduanya tidak pernah dipakai app
lama juga.

---

## Cara menjalankan

```
venv/Scripts/python -m uvicorn backend.main:app --port 8000
npx vite --config vite.preview.config.ts     # http://127.0.0.1:5174/preview.html

npx vitest run
npx tsc -p tsconfig.next.json --noEmit
```

Aplikasi lama tetap utuh: `npx vite` di port 5173.
