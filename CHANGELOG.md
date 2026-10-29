# Changelog

Semua perubahan penting dicatat di sini.

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/),
dan versinya mengikuti [Semantic Versioning](https://semver.org/lang/id/).

## [0.9.5] - 2026-10-29

Rilis perapian menjelang repo dibuka ke publik. Empat perbaikan yang semuanya
berangkat dari pengukuran, satu penambahan pada ekspor, dan pembersihan sisa
frontend lama.

**Masih beta.** Keterbatasan di v0.9.0 belum berubah: pemasangan baru diuji di
komputer pengembang, dan timing subtitle masih bisa meleset.

### Ditambahkan

- Ekspor JSON ikut memuat data analisis, bukan hanya waktu klip: ketiga pilihan
  judul dari AI, alasan sebuah klip dibuka di titik itu, dan kalimat yang jadi
  jangkar batas klip. (#129)
- README dua bahasa dengan tangkapan layar, bagian kontribusi, dan kredit ke
  proyek yang jadi titik awal. (#131, #135)

### Diperbaiki

- Transkrip video panjang: satu batas baris untuk semua durasi. Sebelumnya
  batasnya 800 baris untuk video satu jam ke bawah dan 2500 di atasnya,
  sehingga video 59 menit hanya menyimpan 48% transkripnya sementara video 61
  menit menyimpan seluruhnya — selisih dua menit durasi, tiga kali lipat
  jatah. (#122)
- Unduhan caption diberi waktu yang cukup. Timeout 8 detik memotong request
  yang sebenarnya akan berhasil; pada video 4,4 jam dengan trek caption 3,3 MB,
  request yang sehat butuh 0,6 sampai 30,5 detik. Pemotongan itu memicu
  permintaan beruntun, dan permintaan beruntun itulah yang memancing 429 asli
  dari YouTube. (#118)
- Saat kuota per menit habis, analisis menunggu alih-alih langsung jatuh ke
  model terlemah di rantai cadangan. (#125)
- `title_options` ditulis sebelum `title` yang menyalinnya. Model menulis JSON
  berurutan, jadi saat mengisi `title` di posisi 6, `title_options` di posisi
  15 belum ada: instruksinya mustahil dipenuhi. (#127)

### Dihapus

- **Lisensi MIT dicabut.** Berkas `LICENSE` dihapus dan semua hak ditahan
  pemilik. MIT tidak pernah dibahas di issue mana pun dan kemungkinan terpilih
  sebagai bawaan saat repo dibuat, bukan keputusan sadar. Pemakaian,
  penyalinan, atau penyebaran ulang perlu izin lebih dulu lewat GitHub Issues.
  Hak yang sudah diberikan MIT pada v0.9.0 tidak bisa ditarik untuk salinan
  yang sudah terlanjur diterima, tapi rilis ini dan seterusnya tidak lagi
  memberikannya. (#116)
- Frontend lama `src/` beserta perkakas yang melayaninya. Tidak ada yang
  mengimpornya dari `src-next/`, backend, maupun test, dan CI tidak pernah
  menjalankannya. Isinya tetap tersimpan di riwayat git. (#133)

## [0.9.0] - 2026-10-09

Rilis beta pertama. Alur inti sudah berjalan penuh dan terbukti: analisis
video, pemilihan klip, pengaturan di Studio, render, lalu unduh.

**Status beta.** Pemasangan belum diuji di komputer lain selain milik
pengembang. Kalau Anda menemukan masalah, laporkan lewat GitHub Issues.

### Ditambahkan

**Analisis**
- Analisis video YouTube dengan Gemini: daftar klip beserta judul, skor, dan
  ringkasan.
- Pilihan target durasi klip: 15 detik, 30 detik, 60 detik, 2 menit, 3 menit.
- Awal dan akhir klip diselaraskan ke tepi baris transkrip dan akhir kalimat,
  jadi klip tidak terpotong di tengah kalimat.
- Judul hook maksimal 7 kata dengan tiga variasi per klip.
- Caption dan hashtag siap unggah, dengan tombol salin.
- Peringatan saat transkrip terlalu panjang dan sebagian video tidak ikut
  dianalisis.
- Riwayat analisis tersimpan, bisa dibuka ulang tanpa memakai kuota Gemini.

**Clip Studio**
- Rasio keluaran 9:16, 1:1, 4:3, 16:9 dengan pratinjau bentuknya.
- Latar hitam atau buram untuk mengisi bagian kosong.
- Tata letak streamer: split facecam dan PiP sudut.
- Face tracking: crop mengikuti posisi wajah pembicara, dengan kontrol manual
  untuk ukuran dan posisi.
- Subtitle per kata dengan 7 gaya dan 8 pilihan font.
- Judul dengan posisi, ukuran, awalan, akhiran, dan batas durasi tampil.
- Watermark gambar atau teks dengan preset posisi.
- Musik latar dan SFX dengan atur volume serta offset, bisa didengar langsung
  di pratinjau.
- Trimmer untuk memotong ulang awal dan akhir klip.

**Render**
- Render massal ke MP4 vertikal 1080x1920, lalu unduh semuanya dalam satu ZIP.
- Pilihan encoder hardware (NVENC, AMF, QSV) atau CPU, dibaca dari mesin yang
  dipakai.
- Progres render dikirim langsung ke browser.
- Render yang sedang jalan tersambung ulang otomatis setelah browser
  di-refresh.
- Tombol pemulihan saat render gagal: ganti encoder, bersihkan berkas
  sementara, matikan subtitle, buka pengelola cookies, atau coba lagi.

**Lain-lain**
- Pengelola cookies YouTube untuk video yang meminta login.
- Dua bahasa: Indonesia dan Inggris.
- Mode terang dan gelap.
- Kunci Gemini dimasukkan lewat form, dikirim sebagai header, tidak pernah
  disimpan di server maupun masuk ke log.

### Diubah

- Subtitle otomatis (Whisper) jadi opsional. Pemasangan turun dari 1.030 MB
  menjadi **268 MB**. Video YouTube yang punya caption tetap dapat subtitle
  seperti biasa; untuk video tanpa caption, Studio memberi tahu cara memasang
  Whisper. (#112)

### Diperbaiki

- Render dengan cookies tidak lagi gagal dengan pesan "The page needs to be
  reloaded". (#78)
- Pratinjau memakai frame asli dari video, bukan thumbnail YouTube. (#55)
- Caption klip tidak lagi kemasukan kata dari kalimat sebelum atau sesudah
  klip. (#52)
- Pratinjau memakai font dan ukuran subtitle yang sama persis dengan hasil
  render. (#25)
- Klip 2 dan 3 menit yang terlalu pendek diperpanjang sampai durasi minimum.
  (#39)
- Pembuatan ZIP tidak lagi memblokir server. (#81)
- Error ffmpeg yang sebenarnya dilaporkan saat unduhan klip gagal. (#93)

### Keamanan

- CORS dibatasi hanya untuk aplikasi sendiri. (#46)
- Endpoint frame dan deteksi wajah hanya menerima ID video YouTube yang sah.
  (#43)
- Unduhan mentah hanya dari ID YouTube yang sah, dengan pengecekan waktu. (#79)
- Ukuran dan tipe berkas yang diunggah dibatasi. (#80)
- Status cookies ditampilkan tanpa pernah memuat ulang isinya ke halaman. (#46)

### Diketahui belum selesai

- Hasil render menumpuk di `backend/exports` tanpa cara melihat atau
  menghapusnya dari aplikasi. (#108)
- Untuk video panjang, bagian akhir bisa tidak ikut dianalisis. (#103)
- Pemasangan belum diuji di komputer selain milik pengembang. (#111)

[0.9.5]: https://github.com/M1xora/xoraclips/compare/v0.9.0...v0.9.5
[0.9.0]: https://github.com/M1xora/xoraclips/releases/tag/v0.9.0
