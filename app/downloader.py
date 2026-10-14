"""StreamDown — Async HLS downloader + direct MP4 streamer + FFmpeg muxer.

Handles two source types:
  - HLS (m3u8): downloads all TS segments concurrently, concatenates via
    FFmpeg concat demuxer, remuxes to MP4 losslessly.
  - MP4 (direct): streams file directly to disk in chunks with live progress.

Provides real-time progress via shared in-memory task registry.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin

import aiohttp

from .config import (
    DEFAULT_HEADERS,
    DOWNLOADS_DIR,
    FFMPEG_BIN,
    MAX_CONCURRENT_SEGMENTS,
    SEGMENT_RETRY_BACKOFF_BASE,
    SEGMENT_RETRY_LIMIT,
    SEGMENT_TIMEOUT,
)
from .framex_client import StreamSource, Subtitle

log = logging.getLogger("streamdown.downloader")


# ── Progress state ──────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    FETCHING_PLAYLIST = "fetching_playlist"
    DOWNLOADING = "downloading"
    MERGING = "merging"
    DOWNLOADING_SUBTITLES = "downloading_subtitles"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadProgress:
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    total_segments: int = 0
    downloaded_segments: int = 0
    bytes_downloaded: int = 0
    speed_bps: float = 0.0
    eta_seconds: float = 0.0
    percent: float = 0.0
    output_file: str = ""
    subtitle_files: list[str] = field(default_factory=list)
    error: str = ""
    filename: str = ""


# ── Active tasks registry ──────────────────────────────────────────────────

_tasks: dict[str, DownloadProgress] = {}
_cancel_events: dict[str, asyncio.Event] = {}


def get_progress(task_id: str) -> Optional[DownloadProgress]:
    return _tasks.get(task_id)


def cancel_task(task_id: str) -> bool:
    ev = _cancel_events.get(task_id)
    if ev:
        ev.set()
        return True
    return False


def list_tasks() -> list[DownloadProgress]:
    return list(_tasks.values())


# ── Helpers ─────────────────────────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name.strip(". ")[:200]


def _safe_output_path(base_name: str, ext: str = "mp4") -> Path:
    """Return a non-conflicting output path inside downloads dir."""
    path = DOWNLOADS_DIR / f"{base_name}.{ext}"
    counter = 1
    while path.exists():
        path = DOWNLOADS_DIR / f"{base_name}_{counter}.{ext}"
        counter += 1
    return path


def _parse_m3u8_segments(playlist_text: str, playlist_url: str) -> list[str]:
    """Extract absolute segment URLs from an m3u8 playlist."""
    segments: list[str] = []
    for line in playlist_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("http://") or line.startswith("https://"):
            segments.append(line)
        else:
            segments.append(urljoin(playlist_url, line))
    return segments


def _build_headers_for_source(source: StreamSource) -> dict:
    """Return appropriate HTTP headers based on source configuration and URL host."""
    headers = dict(DEFAULT_HEADERS)
    if "api.framextv.tech" in source.url or "framextv.tech" in source.url:
        headers["Referer"] = "https://vidlink.pro/"
        headers["Origin"] = "https://vidlink.pro"
    if source.headers:
        headers.update(source.headers)
    return headers


async def _resolve_media_playlist(
    session: aiohttp.ClientSession, url: str
) -> tuple[str, str]:
    """Resolve an HLS master playlist down to a media playlist containing TS segments."""
    curr_url = url
    for _ in range(3):
        async with session.get(curr_url) as resp:
            resp.raise_for_status()
            text = await resp.text()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if any("#EXT-X-STREAM-INF" in l for l in lines):
            child_uri = None
            for i, l in enumerate(lines):
                if l.startswith("#EXT-X-STREAM-INF"):
                    child_uri = lines[i + 1]
                    break
            if child_uri:
                curr_url = urljoin(curr_url, child_uri)
                continue
        return curr_url, text
    return curr_url, text


def _vtt_to_srt(vtt: str) -> str:
    """Convert WebVTT content to SRT format."""
    lines = vtt.split("\n")
    out_lines: list[str] = []
    counter = 0
    i = 0
    # Skip WEBVTT header and STYLE/NOTE blocks
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("WEBVTT") or line.startswith("NOTE") or line.startswith("STYLE"):
            while i < len(lines) and lines[i].strip():
                i += 1
            i += 1
            continue
        break

    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            counter += 1
            ts_line = line.replace(".", ",")
            ts_line = re.sub(r"\s+(?:position|align|line|size):[^\s]+", "", ts_line)
            out_lines.append(str(counter))
            out_lines.append(ts_line)
            i += 1
            while i < len(lines) and lines[i].strip():
                out_lines.append(lines[i].rstrip())
                i += 1
            out_lines.append("")
        else:
            i += 1
    return "\n".join(out_lines)


# ── Segment downloader (HLS) ────────────────────────────────────────────────

async def _download_segment(
    session: aiohttp.ClientSession,
    url: str,
    dest: Path,
    semaphore: asyncio.Semaphore,
    cancel_event: asyncio.Event,
) -> int:
    """Download a single HLS segment with retry. Returns bytes written."""
    async with semaphore:
        for attempt in range(1, SEGMENT_RETRY_LIMIT + 1):
            if cancel_event.is_set():
                raise asyncio.CancelledError("Task cancelled")
            try:
                timeout = aiohttp.ClientTimeout(total=SEGMENT_TIMEOUT)
                async with session.get(url, timeout=timeout) as resp:
                    resp.raise_for_status()
                    data = await resp.read()
                    dest.write_bytes(data)
                    return len(data)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt == SEGMENT_RETRY_LIMIT:
                    raise RuntimeError(
                        f"Segment download failed after {SEGMENT_RETRY_LIMIT} "
                        f"attempts: {url[:80]}… — {exc}"
                    ) from exc
                wait = SEGMENT_RETRY_BACKOFF_BASE ** attempt
                log.warning(
                    "Segment retry %d/%d in %.1fs: %s",
                    attempt, SEGMENT_RETRY_LIMIT, wait, str(exc)[:100],
                )
                await asyncio.sleep(wait)
    return 0


# ── Subtitle downloader ─────────────────────────────────────────────────────

async def _download_subtitle_file(
    session: aiohttp.ClientSession,
    subtitle: Subtitle,
    base_name: str,
) -> Optional[str]:
    """Download subtitle, save as VTT and SRT. Returns SRT filename or None."""
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with session.get(subtitle.url, timeout=timeout) as resp:
            if resp.status != 200:
                log.warning("Subtitle HTTP %s: %s", resp.status, subtitle.label)
                return None
            content = await resp.text(errors="replace")
    except Exception as exc:
        log.warning("Subtitle download error (%s): %s", subtitle.label, exc)
        return None

    lang = _sanitize_filename(subtitle.safe_language)

    vtt_path = DOWNLOADS_DIR / f"{base_name}.{lang}.vtt"
    vtt_path.write_text(content, encoding="utf-8")

    srt_content = _vtt_to_srt(content) if subtitle.fmt == "vtt" else content
    srt_name = f"{base_name}.{lang}.srt"
    srt_path = DOWNLOADS_DIR / srt_name
    srt_path.write_text(srt_content, encoding="utf-8")

    return srt_name


# ── MP4 direct streaming pipeline ──────────────────────────────────────────

async def _stream_mp4_direct(
    source: StreamSource,
    progress: DownloadProgress,
    safe_name: str,
    cancel_event: asyncio.Event,
) -> Path:
    """Stream a direct MP4 URL to disk with live progress. Returns output path."""
    headers = _build_headers_for_source(source)
    output_path = _safe_output_path(safe_name, "mp4")

    progress.status = TaskStatus.DOWNLOADING
    start_time = time.monotonic()
    total_bytes = 0
    content_length = 0

    CHUNK = 1024 * 256  # 256 KB per chunk

    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=60)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        async with session.get(source.url) as resp:
            resp.raise_for_status()
            content_length = int(resp.headers.get("Content-Length", 0))
            # Use 1000 virtual segments to track progress
            progress.total_segments = max(1, content_length // CHUNK) if content_length else 100

            with output_path.open("wb") as f:
                async for chunk in resp.content.iter_chunked(CHUNK):
                    if cancel_event.is_set():
                        raise asyncio.CancelledError("Cancelled")
                    f.write(chunk)
                    total_bytes += len(chunk)
                    elapsed = time.monotonic() - start_time
                    progress.bytes_downloaded = total_bytes
                    progress.downloaded_segments = min(
                        progress.total_segments,
                        total_bytes // CHUNK,
                    )
                    progress.speed_bps = total_bytes / elapsed if elapsed > 0 else 0
                    if content_length > 0:
                        progress.percent = round(total_bytes / content_length * 100, 1)
                        remaining_bytes = content_length - total_bytes
                        progress.eta_seconds = round(
                            remaining_bytes / progress.speed_bps, 1
                        ) if progress.speed_bps > 0 else 0
                    else:
                        progress.percent = min(99.0, total_bytes / (1024 * 1024 * 10))

    return output_path


# ── HLS pipeline ────────────────────────────────────────────────────────────

async def _stream_hls(
    source: StreamSource,
    progress: DownloadProgress,
    safe_name: str,
    cancel_event: asyncio.Event,
    tmp_dir: Path,
) -> Path:
    """Full HLS segment download + FFmpeg remux pipeline. Returns output path."""
    headers = _build_headers_for_source(source)

    # ── 1. Fetch & resolve playlist (handles Master & Media playlists) ───────
    progress.status = TaskStatus.FETCHING_PLAYLIST
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        media_url, playlist_text = await _resolve_media_playlist(session, source.url)

    segment_urls = _parse_m3u8_segments(playlist_text, media_url)
    if not segment_urls:
        raise RuntimeError("Playlist kosong: tidak ada segmen video ditemukan.")

    progress.total_segments = len(segment_urls)
    progress.status = TaskStatus.DOWNLOADING

    # ── 2. Download segments concurrently ───────────────────────────────
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEGMENTS)
    start_time = time.monotonic()
    completed_count = 0
    total_bytes = 0
    lock = asyncio.Lock()

    async def _dl_one(idx: int, url: str):
        nonlocal completed_count, total_bytes
        seg_path = tmp_dir / f"seg_{idx:06d}.ts"
        nbytes = await _download_segment(
            session_dl, url, seg_path, semaphore, cancel_event
        )
        async with lock:
            completed_count += 1
            total_bytes += nbytes
            elapsed = time.monotonic() - start_time
            progress.downloaded_segments = completed_count
            progress.bytes_downloaded = total_bytes
            progress.percent = round(
                completed_count / progress.total_segments * 100, 1
            )
            progress.speed_bps = total_bytes / elapsed if elapsed > 0 else 0
            remaining = progress.total_segments - completed_count
            avg_time = elapsed / completed_count if completed_count > 0 else 0
            progress.eta_seconds = round(remaining * avg_time, 1)

    async with aiohttp.ClientSession(headers=headers) as session_dl:
        seg_tasks = [_dl_one(i, url) for i, url in enumerate(segment_urls)]
        await asyncio.gather(*seg_tasks)

    if cancel_event.is_set():
        raise asyncio.CancelledError("Cancelled")

    # ── 3. Build concat list ────────────────────────────────────────────
    concat_list = tmp_dir / "concat.txt"
    lines = []
    for i in range(len(segment_urls)):
        seg_file = tmp_dir / f"seg_{i:06d}.ts"
        if seg_file.exists():
            escaped = str(seg_file).replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
    concat_list.write_text("\n".join(lines), encoding="utf-8")

    # ── 4. FFmpeg remux ─────────────────────────────────────────────────
    progress.status = TaskStatus.MERGING
    output_mp4 = _safe_output_path(safe_name, "mp4")

    cmd = [
        str(FFMPEG_BIN),
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_mp4),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        err_msg = stderr.decode(errors="replace")[-600:]
        raise RuntimeError(f"FFmpeg remux gagal (code {proc.returncode}): {err_msg}")

    return output_mp4


# ── Public entry point ─────────────────────────────────────────────────────

async def run_download_task(
    source: StreamSource,
    subtitles: list[Subtitle],
    filename_base: str,
) -> str:
    """Register a background download task and return its task_id."""
    task_id = uuid.uuid4().hex[:12]
    safe_name = _sanitize_filename(filename_base)
    progress = DownloadProgress(task_id=task_id, status=TaskStatus.PENDING, filename=safe_name)
    _tasks[task_id] = progress
    cancel_event = asyncio.Event()
    _cancel_events[task_id] = cancel_event

    asyncio.create_task(
        _run_download_bg(task_id, source, subtitles, safe_name, cancel_event)
    )
    return task_id


async def _run_download_bg(
    task_id: str,
    source: StreamSource,
    subtitles: list[Subtitle],
    safe_name: str,
    cancel_event: asyncio.Event,
):
    """Background task: orchestrates download and subtitle pipeline."""
    progress = _tasks[task_id]
    tmp_dir = Path(tempfile.mkdtemp(prefix="streamdown_"))

    try:
        # ── Route based on source type ──────────────────────────────────
        is_mp4 = source.stream_type.lower() == "mp4" or (
            source.url.split("?")[0].endswith(".mp4")
        )

        if is_mp4:
            output_path = await _stream_mp4_direct(
                source, progress, safe_name, cancel_event
            )
        else:
            output_path = await _stream_hls(
                source, progress, safe_name, cancel_event, tmp_dir
            )

        progress.output_file = output_path.name

        # ── Download subtitles ──────────────────────────────────────────
        if subtitles:
            progress.status = TaskStatus.DOWNLOADING_SUBTITLES
            headers = _build_headers_for_source(source)
            async with aiohttp.ClientSession(headers=headers) as sub_session:
                sub_tasks = [
                    _download_subtitle_file(sub_session, sub, safe_name)
                    for sub in subtitles
                ]
                results = await asyncio.gather(*sub_tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, str):
                        progress.subtitle_files.append(r)

        # ── Done ────────────────────────────────────────────────────────
        progress.status = TaskStatus.COMPLETED
        progress.percent = 100.0

    except asyncio.CancelledError:
        progress.status = TaskStatus.CANCELLED
        progress.error = "Download dibatalkan."
    except Exception as exc:
        log.exception("Download background task failed")
        progress.status = TaskStatus.FAILED
        progress.error = str(exc)
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
        _cancel_events.pop(task_id, None)
