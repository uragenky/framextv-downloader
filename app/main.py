"""StreamDown — FastAPI server and API routes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import DOWNLOADS_DIR, HOST, PORT, STATIC_DIR, FFMPEG_BIN
from .parser import parse_link, ParsedLink
from .framex_client import fetch_media_info, MediaInfo, MediaDetails, StreamSource, Subtitle
from .downloader import (
    DownloadProgress,
    TaskStatus,
    get_progress,
    cancel_task,
    list_tasks,
    run_download_task,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("streamdown.main")

app = FastAPI(title="StreamDown", version="1.0.0")

# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Request/Response models ────────────────────────────────────────────────

class SeasonModel(BaseModel):
    season_number: int
    name: str
    episode_count: int


class MediaDetailsModel(BaseModel):
    title: str = ""
    year: str = ""
    poster: str = ""
    backdrop: str = ""
    overview: str = ""
    rating: str = ""
    genres: list[str] = []
    total_episodes: int = 1
    format: str = "MOVIE"
    is_movie: bool = True
    seasons: list[SeasonModel] = []


class InspectRequest(BaseModel):
    url: str
    season: Optional[int] = None
    episode: Optional[int] = None


class InspectResponse(BaseModel):
    success: bool
    media_type: str = ""
    tmdb_id: str = ""
    provider: str = ""
    sources: list[dict] = []
    subtitles: list[dict] = []
    details: Optional[MediaDetailsModel] = None
    default_title: str = ""
    needs_episode_selection: bool = False
    total_episodes: int = 1
    selected_season: Optional[int] = None
    selected_episode: Optional[int] = None
    error: str = ""


class DownloadRequest(BaseModel):
    url: str
    source_index: int = 0
    subtitle_indices: list[int] = []
    filename: str = ""
    season: Optional[int] = None
    episode: Optional[int] = None


class DownloadResponse(BaseModel):
    task_id: str


class ProgressResponse(BaseModel):
    task_id: str
    status: str
    total_segments: int = 0
    downloaded_segments: int = 0
    bytes_downloaded: int = 0
    speed_bps: float = 0.0
    eta_seconds: float = 0.0
    percent: float = 0.0
    output_file: str = ""
    subtitle_files: list[str] = []
    error: str = ""
    filename: str = ""


# ── Helpers ─────────────────────────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name.strip(". ")[:200]


def _build_default_title(
    link: ParsedLink,
    details: Optional[MediaDetails],
    season: Optional[int] = None,
    episode: Optional[int] = None,
) -> str:
    s_val = season if season is not None else link.season
    ep = episode if episode is not None else link.episode
    if details and details.title:
        title = details.title
        if link.is_tv:
            s_str = f" S{s_val:02d}" if s_val is not None else ""
            e_str = f"E{ep:02d}" if ep is not None else ""
            return f"{title}{s_str}{e_str}"
        if link.is_anime:
            e = f" EP{ep:02d}" if ep is not None else ""
            return f"{title}{e}"
        y = f" ({details.year})" if details.year else ""
        return f"{title}{y}"
    return link.label


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.post("/api/inspect", response_model=InspectResponse)
async def api_inspect(req: InspectRequest):
    """Parse a FrameX URL and return available sources, subtitles, and TMDB/AniList metadata."""
    try:
        link = parse_link(req.url)
    except ValueError as exc:
        return InspectResponse(success=False, error=str(exc))

    if req.season is not None:
        link.season = req.season
        if link.media_type == "movie":
            link.media_type = "tv"
    if req.episode is not None:
        link.episode = req.episode
        if link.media_type == "movie":
            link.media_type = "tv"

    info = await fetch_media_info(link)

    details_model = None
    if info.details:
        details_model = MediaDetailsModel(
            title=info.details.title,
            year=info.details.year,
            poster=info.details.poster,
            backdrop=info.details.backdrop,
            overview=info.details.overview,
            rating=info.details.rating,
            genres=info.details.genres,
            total_episodes=info.details.total_episodes,
            format=info.details.format,
            is_movie=info.details.is_movie,
            seasons=[
                SeasonModel(
                    season_number=s.season_number,
                    name=s.name,
                    episode_count=s.episode_count,
                )
                for s in info.details.seasons
            ],
        )

    if not info.success:
        return InspectResponse(
            success=False,
            media_type=link.media_type,
            tmdb_id=link.tmdb_id,
            details=details_model,
            error=info.error or "Gagal mengambil data stream.",
        )

    default_title = _build_default_title(
        link, info.details, info.selected_season, info.selected_episode
    )

    return InspectResponse(
        success=True,
        media_type=link.media_type,
        tmdb_id=link.tmdb_id,
        provider=info.provider,
        sources=[
            {
                "index": i,
                "quality": s.quality,
                "type": s.stream_type,
                "server": s.server,
                "provider": s.provider,
                "audio": s.audio,
                "label": s.label,
                "url": s.url,
            }
            for i, s in enumerate(info.sources)
        ],
        subtitles=[
            {
                "index": i,
                "label": sub.label,
                "language": sub.language,
                "format": sub.fmt,
                "is_default": sub.is_default,
            }
            for i, sub in enumerate(info.subtitles)
        ],
        details=details_model,
        default_title=default_title,
        needs_episode_selection=info.needs_episode_selection,
        total_episodes=info.total_episodes,
        selected_season=info.selected_season,
        selected_episode=info.selected_episode,
    )


@app.post("/api/download", response_model=DownloadResponse)
async def api_download(req: DownloadRequest):
    """Start a background download task."""
    try:
        link = parse_link(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if req.season is not None and link.media_type != "anime":
        link.season = req.season
        if link.media_type == "movie":
            link.media_type = "tv"
    if req.episode is not None:
        link.episode = req.episode
        if link.media_type == "movie":
            link.media_type = "tv"

    info = await fetch_media_info(link)

    if not info.success:
        raise HTTPException(
            status_code=502,
            detail=info.error or "Gagal mengambil data stream.",
        )

    if req.source_index < 0 or req.source_index >= len(info.sources):
        raise HTTPException(status_code=400, detail="Invalid source index.")

    source = info.sources[req.source_index]

    subs: list[Subtitle] = []
    for idx in req.subtitle_indices:
        if 0 <= idx < len(info.subtitles):
            subs.append(info.subtitles[idx])

    if req.filename.strip():
        filename = _sanitize_filename(req.filename.strip())
    else:
        title_base = _build_default_title(link, info.details, link.season, link.episode)
        filename = _sanitize_filename(f"{title_base} [{source.quality}]")

    task_id = await run_download_task(source, subs, filename)

    return DownloadResponse(task_id=task_id)


@app.get("/api/progress/{task_id}")
async def api_progress_sse(task_id: str):
    """Server-Sent Events stream for real-time progress updates."""

    async def event_generator():
        while True:
            progress = get_progress(task_id)
            if progress is None:
                yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
                return

            data = {
                "task_id": progress.task_id,
                "status": progress.status.value,
                "total_segments": progress.total_segments,
                "downloaded_segments": progress.downloaded_segments,
                "bytes_downloaded": progress.bytes_downloaded,
                "speed_bps": round(progress.speed_bps, 0),
                "eta_seconds": progress.eta_seconds,
                "percent": progress.percent,
                "output_file": progress.output_file,
                "subtitle_files": progress.subtitle_files,
                "error": progress.error,
                "filename": progress.filename,
            }
            yield f"data: {json.dumps(data)}\n\n"

            if progress.status in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            ):
                return

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/cancel/{task_id}")
async def api_cancel(task_id: str):
    success = cancel_task(task_id)
    return {"success": success}


@app.get("/api/tasks")
async def api_tasks():
    tasks = list_tasks()
    return [
        {
            "task_id": t.task_id,
            "status": t.status.value,
            "percent": t.percent,
            "filename": t.filename,
            "output_file": t.output_file,
        }
        for t in tasks
    ]


@app.get("/api/downloads")
async def api_list_downloads():
    """List all completed files stored in downloads/ folder."""
    files = []
    if DOWNLOADS_DIR.exists():
        for entry in DOWNLOADS_DIR.iterdir():
            if entry.is_file() and not entry.name.startswith("."):
                stat = entry.stat()
                ext = entry.suffix.lstrip(".").lower()
                files.append({
                    "filename": entry.name,
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "ext": ext,
                    "url": f"/api/files/{entry.name}",
                })
    files.sort(key=lambda x: x["modified_at"], reverse=True)
    return files


@app.delete("/api/files/{filename}")
async def api_delete_file(filename: str):
    """Delete a file from the downloads folder."""
    file_path = (DOWNLOADS_DIR / filename).resolve()
    if not str(file_path).startswith(str(DOWNLOADS_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Akses ditolak.")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File tidak ditemukan.")
    try:
        file_path.unlink()
        log.info("File deleted: %s", filename)
        return {"success": True, "filename": filename}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal menghapus file: {exc}")


@app.get("/api/files/{filename}")
async def api_download_file(filename: str):
    """Serve a completed download file."""
    file_path = DOWNLOADS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    if not str(file_path.resolve()).startswith(str(DOWNLOADS_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied.")
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/octet-stream",
    )


@app.get("/api/health")
async def health():
    ffmpeg_ok = FFMPEG_BIN.exists() and os.access(str(FFMPEG_BIN), os.X_OK)
    return {
        "status": "ok",
        "ffmpeg": "ready" if ffmpeg_ok else "missing",
        "downloads_dir": str(DOWNLOADS_DIR),
    }


# ── Entry point ─────────────────────────────────────────────────────────────

def main():
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
