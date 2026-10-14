# StreamDown

**FrameX Movie & TV Downloader** — Web application untuk mengunduh film, serial TV, dan anime dari FrameX ke file MP4 lokal dengan pilihan resolusi, subtitle, pratinjau judul/poster, dan Download Manager lokal terintegrasi.

## Fitur Unggulan

- **Navigasi Menu Terpisah (Tabs)** — Sistem tab modern di header:
  - **📥 Unduh Stream**: Area kerja input link, pratinjau judul, pemilihan episode, dan pemilihan provider.
  - **📁 File Tersimpan**: Menu Download Manager tersendiri lengkap dengan counter badge, pencarian/filter, download langsung, salin link, dan hapus file.
- **Download Non-Blocking (Tanpa Pindah Halaman)** — Saat tombol download diklik, halaman dan daftar episode **tidak hilang**:
  - Anda bisa langsung memilih episode berikutnya (`EP 2`, `EP 3`, dst.) dan langsung mendownload tanpa perlu cek link ulang dari awal.
  - Antrean unduhan aktif berjalan di bawah tombol download secara bersamaan dengan progress bar masing-masing.
- **Dukungan Penuh Serial TV & Anime** — Mendukung link anime (`framextv.xyz/anime/182255`) dan serial TV (`framextv.xyz/tv/209867`):
  - **Pemilih Season**: Beralih antar Season (Season 1, Season 2, Specials, dll.) secara instan.
  - **Grid Episode Interaktif**: Menampilkan seluruh tombol episode (`EP 1`, `EP 2`, ..., `EP 38`).
  - Penamaan file otomatis standar scene (contoh: `Frieren: Beyond Journey's End S01E01 [1080p].mp4`).
- **Multi-Provider Paralel Aktif** — Memindai seluruh server stream penyedia secara bersamaan (Grand Warden, Wizard, Healer, Archer, Bowler, Super Barbarian, dll.) dan menampilkan seluruh server yang aktif dan terbukti dapat diunduh (termasuk opsi Subtitle & Dubbing).
- **Resolver Master Playlist HLS** — Secara otomatis membaca dan mengurai HLS Master Playlist (`#EXT-X-STREAM-INF`) ke resolusi tertinggi (1080p Full HD) untuk pengunduhan segmen video TS yang utuh.
- **Pratinjau Film & Serial Lengkap** — Menampilkan poster resmi, judul asli, tahun rilis, rating, genre, dan sinopsis secara instan setelah link dicek.
- **Penamaan File Otomatis & Dinamis** — Nama file output otomatis disesuaikan dengan judul dan resolusi yang dipilih (contoh: `Fight Club (1999) [720p].mp4` atau `Frieren Beyond Journey's End Season 2 EP01 [1080p].mp4`), tetap dapat diedit secara manual.
- **Pilihan Resolusi Fleksibel** — Menampilkan semua sumber video aktif (1080p, 720p, 480p, MP4 direct / HLS stream) beserta server penyedia.
- **Pilihan Subtitle Terintegrasi** — Unduh subtitle dalam berbagai bahasa (otomatis dikonversi ke format `.srt` dan `.vtt`).
- **Progress Real-time** — Live progress bar via Server-Sent Events (SSE): persentase, kecepatan download, dan estimasi waktu selesai (ETA).
- **Remux Lossless Cepat** — Segmen HLS digabungkan ke format MP4 via FFmpeg tanpa proses re-encoding (`-c copy`), instan dan tanpa penurunan kualitas video.
- **Retry Otomatis** — Proteksi kegagalan unduh segmen dengan retry hingga 5x dan exponential backoff.
- **Dark Theme UI** — Antarmuka modern, responsif, dan elegan berbasis Tailwind CSS.

---

## Prasyarat

| Komponen | Kebutuhan | Keterangan |
|----------|:---------:|------------|
| Python   | 3.10+     | Runtime backend utama |
| Pip Packages | — | `fastapi`, `uvicorn`, `aiohttp` |
| FFmpeg   | 5.0+      | Otomatis diunduh oleh `run.sh` jika belum tersedia |

### Instalasi Dependensi Python

```bash
pip install fastapi uvicorn aiohttp
```

---

## Quick Start

```bash
# Masuk ke direktori
cd streamdown

# Jalankan server (FFmpeg static binary akan otomatis disiapkan)
chmod +x run.sh
./run.sh
```

Aplikasi dapat langsung diakses melalui browser di:  
**`http://localhost:8000`**

### Kustomisasi Host & Port

```bash
STREAMDOWN_HOST=0.0.0.0 STREAMDOWN_PORT=3000 ./run.sh
```

---

## Cara Penggunaan

1. Buka `http://localhost:8000` di web browser.
2. Salin dan tempel link FrameX atau masukkan TMDB ID langsung:
   - Contoh Film: `https://framextv.xyz/watch/550` atau cukup `550`
   - Contoh TV: `https://framextv.xyz/tv/1399` (input Season & Episode akan otomatis muncul)
3. Klik tombol **Cek Link**.
4. Periksa kartu pratinjau: poster, judul, dan sinopsis film akan muncul untuk memastikan film yang dipilih sudah benar.
5. Pilih salah satu resolusi video (nama file akan otomatis ter-update dengan tag resolusi).
6. Centang subtitle yang ingin disertakan jika diperlukan.
7. Klik **Mulai Download Sekarang**.
8. Pantau progress bar secara real-time.
9. Setelah selesai, file akan tercantum di bagian **Download Manager** di bawah halaman untuk diunduh, disalin link-nya, atau dihapus jika sudah tidak dibutuhkan.

---

### Format Link yang Didukung

| Jenis Konten | Contoh Format Input |
|--------------|-------------------|
| Film | `https://framextv.xyz/watch/550` |
| Film | `https://framextv.xyz/movie/550` |
| Film | `https://framextv.xyz/embed/550` |
| Film | `550` (TMDB ID angka langsung) |
| Serial TV | `https://framextv.xyz/watch/1399/1/1` |
| Serial TV | `https://framextv.xyz/tv/1399` (pilih Season & Episode) |
| Serial TV | `https://framextv.xyz/embed/tv/1399/1/1` |
| Anime | `https://framextv.xyz/watch/anime/12345/1` |
| Anime | `https://framextv.xyz/anime/12345` |

---

## Struktur Direktori

```
streamdown/
├── app/
│   ├── __init__.py
│   ├── config.py            # Konfigurasi path, port, URL endpoint FrameX
│   ├── parser.py            # Regex parser URL FrameX & TMDB ID
│   ├── framex_client.py     # Klien async stream & metadata TMDB
│   ├── downloader.py        # Mesin unduh HLS/MP4 + remuxer FFmpeg
│   └── main.py              # Server FastAPI, API routes & static mount
├── static/
│   ├── index.html           # Web UI frontend (Tailwind CSS dark mode)
│   └── app.js               # Interaksi UI, SSE progress & Download Manager
├── bin/
│   ├── ffmpeg               # Binary static FFmpeg x64 (auto-download)
│   └── ffprobe              # Binary static FFprobe x64 (auto-download)
├── downloads/               # Direktori penyimpanan file lokal MP4 & SRT
├── run.sh                   # Script peluncur satu perintah
├── .gitignore
└── README.md
```

---

## API Endpoints

| Method | Endpoint | Deskripsi |
|:------:|----------|-----------|
| `GET`  | `/` | Halaman Web UI |
| `POST` | `/api/inspect` | Mengambil metadata judul, poster, resolusi, dan subtitle |
| `POST` | `/api/download` | Memulai background download task |
| `GET`  | `/api/progress/{task_id}` | Event stream SSE progress real-time |
| `POST` | `/api/cancel/{task_id}` | Membatalkan download yang sedang berjalan |
| `GET`  | `/api/downloads` | Mendapatkan daftar semua file tersimpan di folder downloads |
| `GET`  | `/api/files/{filename}` | Mengunduh file MP4 / SRT lokal |
| `DELETE` | `/api/files/{filename}` | Menghapus file lokal dari disk |
| `GET`  | `/api/health` | Status kesiapan server dan FFmpeg |

---

## Troubleshooting

| Gejala | Penyebab & Solusi |
|--------|------------------|
| *FFmpeg missing* | Jalankan `./run.sh`, skrip akan otomatis mengunduh binary resmi Linux-x64 ke folder `bin/` |
| *HTTP 502 / Error Cek Link* | Pastikan ID TMDB valid dan koneksi internet stabil |
| *Download gagal di tengah jalan* | Sistem otomatis mencoba ulang (retry 5x per segmen). Jika koneksi lambat, kurangi nilai `MAX_CONCURRENT_SEGMENTS` di `app/config.py` |
| *File tidak bisa dihapus* | Pastikan proses download untuk file tersebut sudah selesai atau dibatalkan |

---

## Lisensi

MIT License
