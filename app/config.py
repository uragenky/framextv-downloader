"""StreamDown — Configuration."""

import os
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
BIN_DIR = BASE_DIR / "bin"
FFMPEG_BIN = BIN_DIR / "ffmpeg"
FFPROBE_BIN = BIN_DIR / "ffprobe"
DOWNLOADS_DIR = BASE_DIR / "downloads"
STATIC_DIR = BASE_DIR / "static"

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# ── Server ──────────────────────────────────────────────────────────────────
HOST = os.getenv("STREAMDOWN_HOST", "0.0.0.0")
PORT = int(os.getenv("STREAMDOWN_PORT", "8000"))

# ── FrameX API ──────────────────────────────────────────────────────────────
FRAMEX_API_BASE = "https://api.framextv.tech"
FRAMEX_STREAM_ENDPOINT = f"{FRAMEX_API_BASE}/api/stream"
FRAMEX_DETAILS_ENDPOINT = f"{FRAMEX_API_BASE}/api/details"
FRAMEX_ANIME_BASE = f"{FRAMEX_API_BASE}/anime"
FRAMEX_ANIME_STREAM_ENDPOINT = f"{FRAMEX_ANIME_BASE}/api/stream"
FRAMEX_ANIME_PROVIDERS_ENDPOINT = f"{FRAMEX_ANIME_BASE}/api/providers"
ANILIST_GRAPHQL_ENDPOINT = "https://graphql.anilist.co"
FRAMEX_SITE = "https://framextv.xyz"

# ── HTTP headers required by CDN workers ────────────────────────────────────
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.rivestream.app/",
    "Origin": "https://www.rivestream.app",
}

# ── Downloader tuning ──────────────────────────────────────────────────────
MAX_CONCURRENT_SEGMENTS = 10       # parallel segment downloads
SEGMENT_RETRY_LIMIT = 5           # retries per segment
SEGMENT_RETRY_BACKOFF_BASE = 1.5  # exponential backoff base (seconds)
SEGMENT_TIMEOUT = 30              # per-segment HTTP timeout (seconds)
