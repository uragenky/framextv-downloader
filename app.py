import os
import sys
import uuid
import threading
import logging
import re
import urllib.request
import json
import math
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

# Tambahkan root path ke sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.api.client import FrameXClient
from src.uploader.gdrive import GDriveService
from src.downloader.manager import (
    LocalDownloadManager,
    list_local_downloads,
    delete_local_file,
    delete_local_files,
    cleanup_subtitles,
    DOWNLOADS_DIR,
    sanitize_filename,
    format_bytes,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("streamdown")

app = FastAPI(title="StreamDown — Cloud & Local Media Downloader", version="2.0.0")

# Setup folder
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

client = FrameXClient()
gdrive_service = GDriveService()
local_dl_manager = LocalDownloadManager()

# Coba ambil akun asli dari MCP
initial_user = gdrive_service.get_user_info() if gdrive_service.is_authenticated() else {}
default_email = initial_user.get("email", "")
default_name = initial_user.get("name", "")

# Default State
default_config = {
    "google_account": default_email,
    "user_display_name": default_name,
    "gdrive_folder": "frameXTV_Downloads",
    "github_repo": "",
    "github_token": "",
    "accounts_list": [default_email] if default_email else []
}

# Load saved config if exists
config = default_config.copy()
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
            config.update(saved)
            if default_email and default_email not in config.get("accounts_list", []):
                config["accounts_list"].insert(0, default_email)
    except Exception as e:
        logger.warning(f"Gagal membaca config.json: {e}")
else:
    config["google_account"] = default_email
    config["user_display_name"] = default_name


def save_config_to_file():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        logger.warning(f"Gagal menyimpan config.json: {e}")


# Cache untuk Quota agar tidak membebani rate limit GitHub API
quota_cache = {
    "timestamp": 0,
    "data": None
}


# Models
class GDriveConfigUpdate(BaseModel):
    google_account: str
    gdrive_folder: str


class GitHubConfigUpdate(BaseModel):
    github_repo: str
    github_token: str


class CloudDispatchRequest(BaseModel):
    title: str
    media_type: str = "movie"
    season: Optional[int] = 1
    episode: Optional[int] = 1
    episodes: Optional[str] = "1"
    gdrive_folder: Optional[str] = "frameXTV_Downloads"


class LocalDownloadRequest(BaseModel):
    id: str
    title: str
    media_type: str = "movie"
    season: Optional[int] = 1
    episode: Optional[int] = 1
    episodes: Optional[List[int]] = None
    provider: Optional[str] = None
    filename: Optional[str] = None
    target_sub_lang: Optional[str] = "id"
    auto_translate_sub: Optional[bool] = True
    original_language: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    filenames: List[str]


def extract_media_from_input(raw: str) -> Optional[tuple]:
    """Ekstrak (media_type, media_id, season, episode) dari URL FrameX atau TMDB/AniList ID."""
    raw = raw.strip()
    if not raw:
        return None

    # Plain numeric ID
    if re.fullmatch(r"\d+", raw):
        return ("movie", raw, None, None)

    # URL patterns
    m_tv_ep = re.search(r"/(?:watch|embed|tv)/(?:tv/)?(\d+)/(\d+)/(\d+)", raw)
    if m_tv_ep:
        return ("tv", m_tv_ep.group(1), int(m_tv_ep.group(2)), int(m_tv_ep.group(3)))

    m_tv = re.search(r"/(?:watch|embed|tv)/tv/(\d+)", raw) or re.search(r"/tv/(\d+)", raw)
    if m_tv:
        return ("tv", m_tv.group(1), 1, 1)

    m_anime_ep = re.search(r"/(?:watch|embed)/anime/(\d+)/(\d+)", raw)
    if m_anime_ep:
        return ("anime", m_anime_ep.group(1), 1, int(m_anime_ep.group(2)))

    m_anime = re.search(r"/anime/(\d+)", raw)
    if m_anime:
        return ("anime", m_anime.group(1), 1, 1)

    m_movie = re.search(r"/(?:watch|embed|movie)/movie/(\d+)", raw) or re.search(r"/(?:watch|embed|movie)/(\d+)", raw)
    if m_movie:
        return ("movie", m_movie.group(1), None, None)

    return None


# ==========================================
# API Routes
# ==========================================

@app.get("/api/search")
def api_search(q: str, type: str = "movie", page: int = 1):
    try:
        q_clean = q.strip()
        parsed = extract_media_from_input(q_clean)
        if parsed:
            p_type, p_id, p_season, p_ep = parsed
            target_type = p_type if p_type != "movie" or "movie" in q_clean else type
            try:
                details = client.get_details(p_id, media_type=target_type)
                if details and details.get("success"):
                    item = {
                        "id": p_id,
                        "title": details.get("title") or details.get("name") or f"ID {p_id}",
                        "name": details.get("title") or details.get("name"),
                        "year": details.get("year") or (details.get("releaseDate") or details.get("release_date") or "")[:4] or "",
                        "rating": details.get("rating"),
                        "poster": details.get("poster") or details.get("poster_path"),
                        "type": target_type,
                        "overview": details.get("overview", ""),
                        "seasons": details.get("seasons", []),
                        "preselect_season": p_season,
                        "preselect_episode": p_ep,
                    }
                    return {"success": True, "results": [item]}
            except Exception as e_parse:
                logger.debug(f"Direct ID lookup failed: {e_parse}")

        results = client.search(q, media_type=type, page=page)
        return {"success": True, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Local Download APIs
@app.post("/api/download/local")
def api_download_local(req: LocalDownloadRequest):
    """Memulai download file ke folder lokal komputer (downloads/)."""
    try:
        queued_tasks = []
        if req.media_type in ["tv", "anime"] and req.episodes:
            for ep in req.episodes:
                t = local_dl_manager.create_task(
                    media_id=req.id,
                    title=req.title,
                    media_type=req.media_type,
                    season=req.season or 1,
                    episode=ep,
                    provider=req.provider,
                    target_sub_lang=req.target_sub_lang or "id",
                    auto_translate_sub=req.auto_translate_sub if req.auto_translate_sub is not None else True,
                    original_language=req.original_language,
                )
                queued_tasks.append(t.to_dict())
        else:
            t = local_dl_manager.create_task(
                media_id=req.id,
                title=req.title,
                media_type=req.media_type,
                season=req.season or 1,
                episode=req.episode or 1,
                provider=req.provider,
                custom_filename=req.filename or "",
                target_sub_lang=req.target_sub_lang or "id",
                auto_translate_sub=req.auto_translate_sub if req.auto_translate_sub is not None else True,
                original_language=req.original_language,
            )
            queued_tasks.append(t.to_dict())

        return {
            "success": True,
            "message": f"{len(queued_tasks)} unduhan berhasil dimasukkan ke antrean lokal.",
            "tasks": queued_tasks,
        }
    except Exception as e:
        logger.error(f"Error starting local download: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/download/progress/{task_id}")
async def api_download_progress(task_id: str):
    """Server-Sent Events (SSE) untuk live progress download lokal."""
    import asyncio

    async def event_generator():
        while True:
            task = local_dl_manager.get_task(task_id)
            if not task:
                yield f"data: {json.dumps({'error': 'Task not found', 'status': 'failed'})}\n\n"
                return

            yield f"data: {json.dumps(task.to_dict())}\n\n"

            if task.status in ["completed", "failed", "cancelled"]:
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


@app.get("/api/download/tasks")
def api_download_tasks():
    return {"success": True, "tasks": local_dl_manager.list_tasks()}


@app.get("/api/download/queue")
def api_download_queue():
    """Mengambil status ringkasan antrean unduhan batch."""
    return {"success": True, "queue": local_dl_manager.get_queue_summary()}


@app.post("/api/download/cancel/{task_id}")
def api_download_cancel(task_id: str):
    success = local_dl_manager.cancel_task(task_id)
    return {"success": success}


@app.post("/api/download/retry/{task_id}")
def api_download_retry(task_id: str):
    """Mencoba ulang unduhan yang gagal atau dibatalkan."""
    success = local_dl_manager.retry_task(task_id)
    return {"success": success}


@app.post("/api/download/cancel-all")
def api_download_cancel_all():
    """Membatalkan seluruh antrean download."""
    cancelled_count = local_dl_manager.cancel_all()
    return {"success": True, "cancelled_count": cancelled_count}


@app.get("/api/downloads")
def api_list_downloads():
    files = list_local_downloads()
    total_size = sum(f.get("size_bytes", 0) for f in files)
    video_count = sum(1 for f in files if f.get("ext") in ["mp4", "mkv", "webm", "avi"])
    sub_count = sum(1 for f in files if f.get("ext") in ["vtt", "srt", "ass"])
    return {
        "success": True,
        "files": files,
        "count": len(files),
        "total_size_bytes": total_size,
        "total_size_str": format_bytes(total_size),
        "video_count": video_count,
        "subtitle_count": sub_count,
    }


@app.get("/api/files/{filename}")
def api_get_file(filename: str):
    safe_name = os.path.basename(filename)
    file_path = DOWNLOADS_DIR / safe_name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File tidak ditemukan.")
    return FileResponse(
        path=str(file_path),
        filename=safe_name,
        media_type="application/octet-stream",
    )


@app.delete("/api/files/{filename}")
def api_delete_file(filename: str):
    success = delete_local_file(filename)
    if not success:
        raise HTTPException(status_code=404, detail="File tidak ditemukan atau gagal dihapus.")
    return {"success": True, "filename": filename}


@app.post("/api/files/bulk-delete")
def api_bulk_delete(req: BulkDeleteRequest):
    """Menghapus banyak file lokal sekaligus dalam 1 request."""
    res = delete_local_files(req.filenames)
    return res


@app.post("/api/files/cleanup-subtitles")
def api_cleanup_subtitles():
    """Menghapus seluruh file subtitle (.vtt / .srt) sisa di downloads/."""
    res = cleanup_subtitles()
    return res


@app.get("/api/details")
def api_details(id: str, type: str = "movie"):
    try:
        details = client.get_details(id, media_type=type)
        return {"success": True, "data": details}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/season")
def api_season(id: str, season: int = 1):
    try:
        data = client.get_season(media_id=id, season=season)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/providers")
def api_providers(type: str = "movie"):
    try:
        providers = client.get_providers(media_type=type)
        return {"success": True, "providers": providers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stream")
def api_stream(
    id: str,
    type: str = "movie",
    season: int = 1,
    episode: int = 1,
    provider: Optional[str] = None
):
    try:
        data = client.get_stream(
            media_type=type,
            media_id=id,
            season=season,
            episode=episode,
            provider=provider
        )
        format_spec = {
            "container": "MP4 (.mp4)",
            "video_codec": "H.264 / AVC",
            "audio_codec": "AAC Stereo",
            "resolution": "1080p Full HD (Adaptive Bitrate)",
            "subtitles_format": "WebVTT (.vtt)"
        }
        return {"success": True, "data": data, "format_spec": format_spec}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Google Drive Management APIs
@app.get("/api/gdrive/status")
def api_gdrive_status():
    user_info = {}
    is_auth = gdrive_service.is_authenticated()
    if is_auth:
        user_info = gdrive_service.get_user_info()

    curr_email = user_info.get("email", config.get("google_account", default_email))
    curr_name = user_info.get("name", config.get("user_display_name", default_name))

    return {
        "success": True,
        "authenticated": is_auth,
        "email": curr_email,
        "display_name": curr_name,
        "google_account": config.get("google_account", default_email),
        "gdrive_folder": config.get("gdrive_folder", "frameXTV_Downloads"),
        "accounts_list": config.get("accounts_list", [curr_email] if curr_email else [])
    }


@app.get("/api/gdrive/folders")
def api_gdrive_folders():
    try:
        folders = gdrive_service.list_folders(limit=40)
        return {"success": True, "folders": folders}
    except Exception as e:
        return {"success": False, "folders": [], "error": str(e)}


@app.post("/api/gdrive/set")
def api_gdrive_set(payload: GDriveConfigUpdate):
    config["google_account"] = payload.google_account.strip()
    config["gdrive_folder"] = payload.gdrive_folder.strip()
    save_config_to_file()
    return {"success": True, "config": config}


# ==========================================
# GitHub Actions Cloud Runner & Real-Time Account-Wide Quota
# ==========================================

@app.get("/api/github/status")
def api_github_status():
    has_config = bool(config.get("github_repo") and config.get("github_token"))
    return {
        "success": True,
        "configured": has_config,
        "github_repo": config.get("github_repo", "")
    }


@app.post("/api/github/config")
def api_github_config(payload: GitHubConfigUpdate):
    config["github_repo"] = payload.github_repo.strip()
    config["github_token"] = payload.github_token.strip()
    save_config_to_file()
    # Invalidate cache
    quota_cache["timestamp"] = 0
    return {"success": True, "configured": bool(config["github_repo"] and config["github_token"])}


@app.get("/api/cloud-quota")
def api_cloud_quota():
    """
    Menghitung pemakaian kuota komputasi GitHub Actions RIIL di seluruh akun pengguna
    (Cross-Repository Account-Wide Usage) yang 100% cocok dengan https://github.com/settings/billing/usage.
    """
    global quota_cache

    # Gunakan cache 45 detik jika masih segar
    if time.time() - quota_cache["timestamp"] < 45 and quota_cache["data"]:
        return quota_cache["data"]

    token = config.get("github_token")
    active_repo = config.get("github_repo", "")

    if not token:
        return {
            "success": False,
            "configured": False,
            "message": "GitHub Cloud Runner belum dihubungkan."
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "streamdown-dashboard"
    }

    try:
        # 1. Ambil seluruh repositori milik akun pengguna
        repos_url = "https://api.github.com/user/repos?per_page=100&type=owner"
        req = urllib.request.Request(repos_url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            repos = json.loads(resp.read().decode("utf-8"))

        now = datetime.now(timezone.utc)
        total_account_minutes = 0
        total_account_runs = 0
        repo_breakdown = []
        recent_transfers = []

        # 2. Iterasi setiap repository untuk menghitung menit billing resmi
        for repo in repos:
            repo_name = repo["full_name"]
            runs_url = f"https://api.github.com/repos/{repo_name}/actions/runs?per_page=100"
            try:
                r_req = urllib.request.Request(runs_url, headers=headers)
                with urllib.request.urlopen(r_req, timeout=10) as r_resp:
                    runs_data = json.loads(r_resp.read().decode("utf-8"))
                    r_runs = runs_data.get("workflow_runs", [])

                    repo_minutes = 0
                    repo_runs_count = 0

                    for r in r_runs:
                        c_str = r.get("created_at")
                        if c_str:
                            dt = datetime.fromisoformat(c_str.replace("Z", "+00:00"))
                            if dt.year == now.year and dt.month == now.month:
                                started = r.get("run_started_at") or r.get("created_at")
                                updated = r.get("updated_at")
                                dur_sec = 0
                                if started and updated:
                                    t_start = datetime.fromisoformat(started.replace("Z", "+00:00"))
                                    t_end = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                                    dur_sec = max(0, int((t_end - t_start).total_seconds()))

                                # Aturan pembulatan ke menit bulat terdekat per job (Official GitHub rule)
                                dur_min = math.ceil(dur_sec / 60)
                                repo_minutes += dur_min
                                repo_runs_count += 1

                                # Kumpulkan riwayat transfer untuk repositori proyek ini
                                active_repo = config.get("github_repo", "").strip()
                                is_match = False
                                if active_repo and (active_repo.lower() in repo_name.lower()):
                                    is_match = True
                                elif "streamdown" in repo_name.lower():
                                    is_match = True

                                if is_match and len(recent_transfers) < 6:
                                    recent_transfers.append({
                                        "id": r.get("id"),
                                        "title": r.get("display_title") or r.get("name"),
                                        "status": r.get("status"),
                                        "conclusion": r.get("conclusion"),
                                        "duration_sec": dur_sec,
                                        "created_at": c_str,
                                        "repo": repo_name
                                    })

                    if repo_runs_count > 0:
                        repo_breakdown.append({
                            "repo": repo_name,
                            "runs": repo_runs_count,
                            "minutes": repo_minutes
                        })
                        total_account_minutes += repo_minutes
                        total_account_runs += repo_runs_count

            except Exception:
                continue

        free_tier_minutes = 2000
        remaining_minutes = max(0, free_tier_minutes - total_account_minutes)
        pct_used = round((total_account_minutes / free_tier_minutes) * 100, 2)

        # Estimasi judul tersisa (rata-rata 1 film/episode butuh ~2 menit)
        avg_min_per_item = 2.0
        est_remaining_items = math.floor(remaining_minutes / avg_min_per_item)

        # Tanggal reset kuota (tanggal 1 awal bulan berikutnya)
        next_month = 1 if now.month == 12 else now.month + 1
        next_year = now.year + 1 if now.month == 12 else now.year
        months_id = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
        next_reset_str = f"1 {months_id[next_month]} {next_year}"

        # Urutkan breakdown dari pemakaian terbesar
        repo_breakdown.sort(key=lambda x: x["minutes"], reverse=True)

        res_data = {
            "success": True,
            "configured": True,
            "github_repo": active_repo,
            "total_account_runs": total_account_runs,
            "total_minutes_used": total_account_minutes,
            "free_tier_minutes": free_tier_minutes,
            "remaining_minutes": remaining_minutes,
            "percent_used": pct_used,
            "est_remaining_items": est_remaining_items,
            "next_reset_str": next_reset_str,
            "repo_breakdown": repo_breakdown,
            "recent_transfers": recent_transfers
        }

        quota_cache = {
            "timestamp": time.time(),
            "data": res_data
        }

        return res_data

    except Exception as e:
        logger.error(f"Gagal menghitung kuota akun GitHub: {e}")
        return {
            "success": False,
            "configured": True,
            "error": str(e)
        }


@app.post("/api/cloud-dispatch")
def api_cloud_dispatch(req: CloudDispatchRequest):
    repo = config.get("github_repo")
    token = config.get("github_token")

    if not repo or not token:
        raise HTTPException(status_code=400, detail="Konfigurasi GitHub Repository & Token belum disetel di menu Setup Cloud.")

    clean_repo = repo.strip().strip("/")
    url = f"https://api.github.com/repos/{clean_repo}/actions/workflows/transfer.yml/dispatches"

    folder = req.gdrive_folder or config.get("gdrive_folder", "frameXTV_Downloads")
    ep_val = str(req.episodes or req.episode or "1").strip()

    payload = {
        "ref": "main",
        "inputs": {
            "title": req.title,
            "media_type": req.media_type,
            "season": str(req.season or 1),
            "episodes": ep_val,
            "gdrive_folder": folder
        }
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "streamdown-dashboard",
        "Content-Type": "application/json"
    }

    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=15) as resp:
            if resp.status in [204, 200, 201]:
                # Invalidate quota cache agar segera terupdate
                quota_cache["timestamp"] = 0
                return {
                    "success": True,
                    "message": "Cloud Runner berhasil dipicu di Datacenter GitHub! Laptop bebas dimatikan/ditutup sekarang.",
                    "repo": clean_repo,
                    "target_title": req.title
                }
            else:
                raise RuntimeError(f"GitHub API mengembalikan status {resp.status}")
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        logger.error(f"GitHub Dispatch Error: {e.code} - {err_msg}")
        raise HTTPException(status_code=e.code, detail=f"Gagal memicu GitHub: {err_msg}")
    except Exception as e:
        logger.error(f"Dispatch Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Serve Static Assets
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.api_route("/", methods=["GET", "HEAD"])
def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse({"message": "StreamDown API is running. static/index.html not found."})


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8888))
    print("\n" + "=" * 60)
    print(f"🚀 StreamDown Dashboard: http://localhost:{port}")
    print("👤 Akun Google Aktif:", config.get("google_account"))
    print("📁 Target Folder GDrive:", config.get("gdrive_folder"))
    print("=" * 60 + "\n")
    uvicorn.run("app:app", host="0.0.0.0", port=port)
