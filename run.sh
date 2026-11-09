#!/usr/bin/env bash
# StreamDown — One-command launcher
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Check FFmpeg binary ─────────────────────────────────────────────────────
if [ ! -x "$SCRIPT_DIR/bin/ffmpeg" ]; then
    echo "[StreamDown] FFmpeg binary not found at bin/ffmpeg"
    echo "[StreamDown] Downloading FFmpeg static build..."
    mkdir -p "$SCRIPT_DIR/bin"
    curl -L -o /tmp/ffmpeg.tar.xz \
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
    tar -xf /tmp/ffmpeg.tar.xz -C /tmp/
    cp /tmp/ffmpeg-master-latest-linux64-gpl/bin/ffmpeg "$SCRIPT_DIR/bin/ffmpeg"
    cp /tmp/ffmpeg-master-latest-linux64-gpl/bin/ffprobe "$SCRIPT_DIR/bin/ffprobe"
    chmod +x "$SCRIPT_DIR/bin/ffmpeg" "$SCRIPT_DIR/bin/ffprobe"
    rm -rf /tmp/ffmpeg.tar.xz /tmp/ffmpeg-master-latest-linux64-gpl
    echo "[StreamDown] FFmpeg installed successfully."
fi

# ── Check Cloudflare WARP (Bypass ISP / DPI Blocking) ──────────────────────
if command -v powershell.exe >/dev/null 2>&1; then
    WARP_STATUS=$(powershell.exe -Command "warp-cli status" 2>/dev/null || true)
    if echo "$WARP_STATUS" | grep -qi "Disconnected"; then
        echo "[StreamDown] Cloudflare WARP terdeteksi Disconnected. Menyambungkan..."
        powershell.exe -Command "warp-cli --accept-tos connect" >/dev/null 2>&1 || true
        sleep 2
    fi
fi

# ── Ensure downloads directory exists ────────────────────────────────────────
mkdir -p "$SCRIPT_DIR/downloads"

# ── Resolve host and port from env or defaults ──────────────────────────────
HOST="${STREAMDOWN_HOST:-0.0.0.0}"
PORT="${STREAMDOWN_PORT:-5000}"

echo ""
echo "  ┌──────────────────────────────────────────┐"
echo "  │             StreamDown v2.0               │"
echo "  │     FrameX Movie/TV/Anime Downloader      │"
echo "  ├──────────────────────────────────────────┤"
echo "  │  Server : http://${HOST}:${PORT}              │"
echo "  │  FFmpeg : $(bin/ffmpeg -version 2>/dev/null | head -n1 | cut -d' ' -f3 || echo 'N/A')  │"
echo "  │  Output : downloads/                      │"
echo "  └──────────────────────────────────────────┘"
echo ""

# ── Start server ─────────────────────────────────────────────────────────────
exec python3 -m uvicorn app:app \
    --host "$HOST" \
    --port "$PORT" \
    --log-level info
