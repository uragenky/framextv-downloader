# 🎬 StreamDown — FrameX Movie, TV & Anime Downloader

Aplikasi modern untuk mencari dan mengunduh media (Film Bioskop, Serial TV Barat/Drakor, dan Anime) dari engine aggregator FrameX dengan **Dukungan Ganda**:
1. **📥 Download Langsung ke Komputer Lokal** lengkap dengan antrean real-time progress bar (kecepatan MB/s, persentase, ETA), penanaman subtitle otomatis (*Soft Subtitle* via FFmpeg), dan Download Manager lokal.
2. **🚀 1-Klik Cloud Runner (FrameX → Google Drive)** via GitHub Actions (kecepatan 1 Gbps datacenter) tanpa menyedot kuota internet atau beban laptop.

---

## 🌟 Fitur Utama

- 🔍 **Pencarian Multi-Media & Smart URL Resolver:**
  - Cari judul film, serial, atau anime langsung melalui search bar.
  - Dukungan paste URL FrameX langsung (contoh: `https://framextv.cc/tv/279246` atau `https://framextv.cc/watch/550`) atau TMDB ID angka.
- 📥 **Download Langsung ke Local (`downloads/`):**
  - Download video HLS / MP4 menggunakan engine paralel multi-thread (`yt-dlp` & FFmpeg static).
  - Floating live progress widget: memantau persentase unduhan, kecepatan download (MB/s), estimasi waktu selesai (ETA), dan status proses.
  - Tombol batal (*cancel*) sewaktu-waktu.
- 📁 **Download Manager Lokal (File Tersimpan):**
  - Akses riwayat unduhan lokal dengan badge counter file tersimpan di header.
  - Unduh langsung ke browser, salin tautan file, atau hapus file dari disk.
- 🌐 **Auto-Translate Subtitle Cerdas (English ➔ Bahasa Indonesia):**
  - Jika subtitle Bahasa Indonesia tidak disediakan oleh server provider, sistem secara otomatis mengunduh subtitle alternatif (misalnya Bahasa Inggris) dan menerjemahkannya cue demi cue ke Bahasa Indonesia dengan mempertahankan penanda waktu (timestamps) secara presisi.
  - Subtitle hasil terjemahan otomatis (`.id.vtt`) ditanamkan langsung sebagai track internal video `.mp4` (`mov_text`, language: `ind`), serta file `.id.vtt` dan `.en.vtt` tetap disimpan berdampingan di `downloads/`.
- 💬 **Subtitle Terembed Otomatis:**
  - Subtitle otomatis ditanamkan langsung ke dalam file video `.mp4` secara lossless via FFmpeg (`mov_text`).
  - File subtitle `.vtt` terpisah juga ikut disimpan di folder `downloads/`.
- 📦 **Batch Multi-Episode (Checkboxes):**
  - Centang beberapa episode sekaligus (misal Ep 1, 2, 3, 4, 5) untuk diproses bertahap baik untuk unduhan lokal maupun transfer cloud.
- ⚡ **1-Klik Cloud Runner (Google Drive):**
  - Opsi transfer langsung ke Google Drive via GitHub Actions tanpa membebani laptop.
- 📡 **Multi-Host Failover & Multi-Provider Fallback:**
  - Rotasi otomatis backend host (`api.framextv.cc`, `api.framextv.tech`, `api.framextv.xyz`, `api.framextv.pro`).
  - Auto-fallback provider jika server utama gagal (`bowler`, `super_barbarian`, `giant`, `sparky`, `royal_champion`, `titan`).
- 🛡️ **Auto-Connect Cloudflare WARP / DPI Bypass:**
  - Mendeteksi dan otomatis menyambungkan Cloudflare WARP jika terputus, mengatasi pemblokiran ISP / Connection Reset.

---

## 📋 Prasyarat

- **Python**: Versi 3.10 atau lebih baru
- **FFmpeg & FFprobe**: Versi static x64 otomatis diunduh oleh `run.sh` ke folder `bin/` jika belum tersedia
- **Koneksi Internet**: Jika menggunakan ISP di Indonesia yang memblokir domain streaming, aktifkan Cloudflare WARP (`warp-cli connect`)

---

## 🚀 Instalasi & Persiapan

```bash
# Clone repository
git clone git@github.com:uragenky/framextv-downloader.git streamdown
cd streamdown

# Install dependensi Python
pip install -r requirements.txt
```

---

## 💻 Cara Menjalankan

### 1. Mode Web Dashboard (Rekomendasi)

Jalankan script `run.sh`:
```bash
chmod +x run.sh
./run.sh
```
Aplikasi web akan aktif di: **`http://localhost:5000`**

Untuk menjalankan di port lain:
```bash
STREAMDOWN_PORT=8888 ./run.sh
```

### 2. Integrasi WSL Dashboard

Jika Anda menggunakan WSL Dashboard (`~/dash` di port `4000`), StreamDown sudah terdaftar sebagai service `streamdown` di port `5000`:
- Buka dashboard di `http://localhost:4000`
- Kelola start, stop, restart, dan pantau log live StreamDown langsung dari browser.

### 3. Mode Antarmuka Baris Perintah (CLI)

StreamDown juga menyediakan CLI mandiri melalui `cli.py`:

```bash
# Cari judul
python3 cli.py search "Inception" --type movie
python3 cli.py search "The Remarried Empress" --type tv

# Cek status server provider
python3 cli.py providers --type movie

# Mengambil link stream m3u8 langsung
python3 cli.py stream 279246 --type tv --season 1 --episode 1

# Download langsung via terminal
python3 cli.py download "The Remarried Empress" --type tv --season 1 --episode 1 --dest ./downloads
```

---

## ☁️ Konfigurasi Cloud Runner (Opsional)

Jika ingin memanfaatkan fitur transfer cloud ke Google Drive via GitHub Actions:
1. Hubungkan repository GitHub Anda melalui modal **Setup Cloud** di header web.
2. Masukkan Personal Access Token (PAT) GitHub dengan scope `repo` & `workflow`.
3. Pasang GitHub Actions secret `GDRIVE_TOKEN_JSON` pada repository GitHub Anda yang berisi credential OAuth Google Drive Anda.
4. Klik tombol **Transfer ke Google Drive (Cloud Runner)** pada modal detail film/serial.

---

## 📁 Struktur Direktori

```
streamdown/
├── .github/
│   └── workflows/
│       └── transfer.yml     # Workflow GitHub Actions Cloud Runner
├── app.py                   # Server FastAPI, API routes & static mount
├── cli.py                   # Antarmuka CLI untuk pencarian & download
├── run.sh                   # Script peluncur satu perintah (auto WARP & FFmpeg)
├── requirements.txt         # Dependensi Python
├── config.example.json      # Contoh konfigurasi
├── bin/
│   ├── ffmpeg               # Binary static FFmpeg x64
│   └── ffprobe              # Binary static FFprobe x64
├── downloads/               # Direktori penyimpanan file lokal MP4 & VTT
├── scripts/
│   └── cloud_transfer.py    # Runner transfer GitHub Actions
├── src/
│   ├── api/
│   │   └── client.py        # Klien multi-host API FrameX
│   ├── downloader/
│   │   ├── hls.py           # Downloader stream HLS
│   │   ├── manager.py       # Download Manager lokal & task registry
│   │   └── sub_translator.py# Auto-translator subtitle (EN -> ID)
│   └── uploader/
│       └── gdrive.py        # Integrasi Google Drive
└── static/
    ├── index.html           # Web UI frontend (Tailwind CSS dark mode)
    └── js/
        └── app.js           # Frontend logic, SSE progress & modal manager
```

---

## 🛠️ Ringkasan API Endpoints

| Method | Endpoint | Deskripsi |
|:------:|----------|-----------|
| `GET`  | `/` | Halaman Web Dashboard |
| `GET`  | `/api/search?q={query}&type={type}` | Pencarian judul atau parse URL FrameX |
| `GET`  | `/api/details?id={id}&type={type}` | Mengambil metadata judul, season, cast, dsb. |
| `GET`  | `/api/stream?id={id}&type={type}&season={s}&episode={e}` | Mengambil link stream video |
| `POST` | `/api/download/local` | Memulai proses download lokal ke `downloads/` |
| `GET`  | `/api/download/progress/{task_id}` | Event stream SSE progress download lokal real-time |
| `POST` | `/api/download/cancel/{task_id}` | Membatalkan download yang sedang berjalan |
| `GET`  | `/api/downloads` | Daftar seluruh file yang tersimpan di folder downloads |
| `GET`  | `/api/files/{filename}` | Mengunduh file dari folder downloads |
| `DELETE` | `/api/files/{filename}` | Menghapus file lokal dari disk |
| `GET`  | `/api/gdrive/status` | Status autentikasi Google Drive |
| `GET`  | `/api/github/status` | Status konfigurasi GitHub Cloud Runner |
| `POST` | `/api/cloud-dispatch` | Memicu GitHub Actions Cloud Runner ke Google Drive |

---

## 📜 Lisensi

MIT License
