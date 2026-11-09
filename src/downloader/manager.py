"""
StreamDown — Local Download Manager.
Handles downloading streams locally using yt-dlp, FFmpeg muxing,
subtitle embedding, and real-time progress tracking.
"""

from __future__ import annotations

import os
import re
import sys
import time
import uuid
import shutil
import logging
import threading
import urllib.request
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable

import yt_dlp

from ..api.client import FrameXClient
from .sub_translator import translate_subtitle_file

logger = logging.getLogger("local_downloader")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
BIN_DIR = BASE_DIR / "bin"
FFMPEG_BIN = BIN_DIR / "ffmpeg" if (BIN_DIR / "ffmpeg").exists() else Path("ffmpeg")

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_filename(filename: str) -> str:
    """Membersihkan karakter ilegal dari nama file."""
    clean = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "", filename)
    return clean.strip(". ")[:200]


def format_bytes(size: float) -> str:
    if not size or size <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def format_time(seconds: float) -> str:
    if not seconds or seconds < 0 or seconds > 86400:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


@dataclass
class DownloadTask:
    task_id: str
    media_id: str
    title: str
    media_type: str = "movie"      # "movie", "tv", "anime"
    season: int = 1
    episode: int = 1
    status: str = "queued"         # "queued", "resolving", "downloading", "embedding", "completed", "failed", "cancelled"
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed_bps: float = 0.0
    speed_str: str = "0 KB/s"
    eta_seconds: float = 0.0
    eta_str: str = "--:--"
    filename: str = ""
    output_file: str = ""
    subtitles_files: List[str] = field(default_factory=list)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    provider: str = ""
    is_cancelled: bool = False
    target_sub_lang: str = "id"
    auto_translate_sub: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "media_id": self.media_id,
            "title": self.title,
            "media_type": self.media_type,
            "season": self.season,
            "episode": self.episode,
            "status": self.status,
            "percent": round(self.percent, 1),
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "downloaded_str": format_bytes(self.downloaded_bytes),
            "total_str": format_bytes(self.total_bytes) if self.total_bytes > 0 else "Menghitung...",
            "speed_str": self.speed_str,
            "eta_str": self.eta_str,
            "filename": self.filename,
            "output_file": self.output_file,
            "subtitles_files": self.subtitles_files,
            "error": self.error,
            "provider": self.provider,
            "target_sub_lang": self.target_sub_lang,
            "auto_translate_sub": self.auto_translate_sub,
            "created_at": self.created_at,
        }


class DownloadCancelledError(Exception):
    pass


class LocalDownloadManager:
    _instance: Optional[LocalDownloadManager] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_manager()
        return cls._instance

    def _init_manager(self):
        self.tasks: Dict[str, DownloadTask] = {}
        self.lock = threading.Lock()
        self.client = FrameXClient()
        self.queue: List[str] = []
        self.is_worker_running = False

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        with self.lock:
            return self.tasks.get(task_id)

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self.lock:
            return [t.to_dict() for t in sorted(self.tasks.values(), key=lambda x: x.created_at, reverse=True)]

    def cancel_task(self, task_id: str) -> bool:
        with self.lock:
            task = self.tasks.get(task_id)
            if task:
                task.is_cancelled = True
                if task.status in ["queued", "resolving", "downloading"]:
                    task.status = "cancelled"
                    task.error = "Download dibatalkan oleh pengguna."
                return True
        return False

    def create_task(
        self,
        media_id: str,
        title: str,
        media_type: str = "movie",
        season: int = 1,
        episode: int = 1,
        provider: Optional[str] = None,
        custom_filename: str = "",
        target_sub_lang: str = "id",
        auto_translate_sub: bool = True,
    ) -> DownloadTask:
        task_id = uuid.uuid4().hex[:10]
        
        # Build clean filename
        if custom_filename:
            clean_name = sanitize_filename(custom_filename)
        else:
            if media_type == "movie":
                clean_name = sanitize_filename(f"{title}")
            elif media_type == "tv":
                clean_name = sanitize_filename(f"{title} S{season:02d}E{episode:02d}")
            else:
                clean_name = sanitize_filename(f"{title} Ep {episode:02d}")

        task = DownloadTask(
            task_id=task_id,
            media_id=str(media_id),
            title=title,
            media_type=media_type,
            season=season,
            episode=episode,
            filename=clean_name,
            provider=provider or "",
            status="queued",
            target_sub_lang=target_sub_lang,
            auto_translate_sub=auto_translate_sub,
        )

        with self.lock:
            self.tasks[task_id] = task
            self.queue.append(task_id)

        self._ensure_worker()
        return task

    def _ensure_worker(self):
        if not self.is_worker_running:
            self.is_worker_running = True
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()

    def _worker_loop(self):
        while True:
            task_id = None
            with self.lock:
                if self.queue:
                    task_id = self.queue.pop(0)
                else:
                    self.is_worker_running = False
                    break

            if task_id:
                task = self.get_task(task_id)
                if task and not task.is_cancelled:
                    try:
                        self._process_download(task)
                    except Exception as e:
                        logger.exception(f"Error processing task {task_id}: {e}")
                        task.status = "failed"
                        task.error = str(e)

    def _process_download(self, task: DownloadTask):
        logger.info(f"Mulai mendownload: {task.title} (ID: {task.task_id})")
        task.status = "resolving"

        # 1. Ambil URL stream aktif
        try:
            stream_data = self.client.get_stream(
                media_type=task.media_type,
                media_id=task.media_id,
                season=task.season,
                episode=task.episode,
                provider=task.provider or None,
                auto_fallback=True
            )
        except Exception as e:
            task.status = "failed"
            task.error = f"Gagal mengekstrak link stream: {e}"
            return

        sources = stream_data.get("sources", [])
        if not sources or not stream_data.get("success"):
            task.status = "failed"
            task.error = "Tidak ada server stream video yang aktif."
            return

        stream_url = sources[0]["url"]
        task.provider = stream_data.get("provider", "default")
        quality = sources[0].get("quality", "HD")

        if task.is_cancelled:
            task.status = "cancelled"
            return

        # Output file paths
        final_filename = f"{task.filename}.mp4"
        final_mp4_path = DOWNLOADS_DIR / final_filename
        
        # Hindari overwrite file dengan menambah counter jika nama sudah ada
        counter = 1
        base_name = task.filename
        while final_mp4_path.exists():
            final_filename = f"{base_name} ({counter}).mp4"
            final_mp4_path = DOWNLOADS_DIR / final_filename
            counter += 1

        temp_dl_path = DOWNLOADS_DIR / f".tmp_{task.task_id}_{final_filename}"
        task.status = "downloading"

        # 2. Download menggunakan yt-dlp dengan progress hook
        def ytdl_progress_hook(d):
            if task.is_cancelled:
                raise DownloadCancelledError("Download dibatalkan oleh pengguna.")

            status = d.get("status")
            if status == "downloading":
                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                speed = d.get("speed", 0)
                eta = d.get("eta", 0)

                # Fragments progress jika HLS
                frag_index = d.get("fragment_index")
                frag_count = d.get("fragment_count")

                if frag_index and frag_count:
                    task.percent = min(99.0, (frag_index / frag_count) * 100.0)
                elif total > 0:
                    task.percent = min(99.0, (downloaded / total) * 100.0)

                task.downloaded_bytes = downloaded
                task.total_bytes = total
                task.speed_bps = speed or 0.0
                task.speed_str = f"{format_bytes(speed)}/s" if speed else "0 KB/s"
                task.eta_seconds = eta or 0.0
                task.eta_str = format_time(eta)

        ydl_opts = {
            "outtmpl": str(temp_dl_path),
            "concurrent_fragment_downloads": 16,
            "retries": 10,
            "fragment_retries": 10,
            "skip_unavailable_fragments": True,
            "nocheckcertificate": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [ytdl_progress_hook],
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Referer": "https://framextv.cc/",
                "Origin": "https://framextv.cc",
            },
        }

        if FFMPEG_BIN.exists():
            ydl_opts["ffmpeg_location"] = str(FFMPEG_BIN.parent)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([stream_url])
        except DownloadCancelledError:
            task.status = "cancelled"
            task.error = "Download dibatalkan."
            if temp_dl_path.exists():
                temp_dl_path.unlink()
            return
        except Exception as e:
            task.status = "failed"
            task.error = f"Gagal mengunduh stream video: {e}"
            if temp_dl_path.exists():
                temp_dl_path.unlink()
            return

        if not temp_dl_path.exists() or temp_dl_path.stat().st_size < 1024 * 100:
            task.status = "failed"
            task.error = "File hasil unduhan kosong atau rusak."
            if temp_dl_path.exists():
                temp_dl_path.unlink()
            return

        # 3. Subtitles Processing
        task.status = "embedding"
        task.percent = 99.0
        subs_list = []
        try:
            subs_list = self.client.get_subtitles(
                media_id=task.media_id,
                media_type=task.media_type,
                season=task.season,
                episode=task.episode
            )
        except Exception as e_sub:
            logger.warning(f"Gagal mengambil daftar subtitle: {e_sub}")

        target_sub_path = None
        target_sub_lang = "ind" if task.target_sub_lang == "id" else "eng"
        if subs_list:
            # 3a. Cek apakah subtitle bahasa Indonesia sudah tersedia langsung dari provider
            preferred_target = ["id", "ind", "indonesian"]
            direct_sub = None
            for pref in preferred_target:
                for sub in subs_list:
                    lang = (sub.get("lang") or sub.get("language") or "").lower()
                    label = (sub.get("label") or "").lower()
                    if pref == lang or pref in label:
                        direct_sub = sub
                        break
                if direct_sub:
                    break

            if direct_sub:
                # Subtitle Indonesia tersedia langsung!
                sub_url = direct_sub.get("url")
                if sub_url:
                    vtt_name = f"{final_mp4_path.stem}.id.vtt"
                    vtt_file_path = DOWNLOADS_DIR / vtt_name
                    try:
                        req_sub = urllib.request.Request(sub_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req_sub, timeout=12) as s_resp, open(vtt_file_path, "wb") as sf:
                            sf.write(s_resp.read())
                        target_sub_path = vtt_file_path
                        target_sub_lang = "ind"
                        task.subtitles_files.append(vtt_name)
                        logger.info(f"Subtitle Indonesia langsung disimpan: {vtt_name}")
                    except Exception as e_sub_dl:
                        logger.warning(f"Gagal unduh file subtitle Indonesia: {e_sub_dl}")
            else:
                # 3b. Subtitle Indonesia tidak tersedia. Cari subtitle alternatif (utamakan English)
                source_candidates = ["en", "eng", "english"]
                source_sub = None
                for pref in source_candidates:
                    for sub in subs_list:
                        lang = (sub.get("lang") or sub.get("language") or "").lower()
                        label = (sub.get("label") or "").lower()
                        if pref == lang or pref in label:
                            source_sub = sub
                            break
                    if source_sub:
                        break

                if not source_sub:
                    source_sub = subs_list[0]

                sub_url = source_sub.get("url")
                if sub_url:
                    src_sub_lang = source_sub.get("lang") or "en"
                    vtt_name = f"{final_mp4_path.stem}.{src_sub_lang}.vtt"
                    vtt_file_path = DOWNLOADS_DIR / vtt_name
                    try:
                        req_sub = urllib.request.Request(sub_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req_sub, timeout=12) as s_resp, open(vtt_file_path, "wb") as sf:
                            sf.write(s_resp.read())
                        task.subtitles_files.append(vtt_name)
                        target_sub_path = vtt_file_path
                        target_sub_lang = "eng" if src_sub_lang in ["en", "eng"] else src_sub_lang
                        logger.info(f"Subtitle alternatif ({src_sub_lang}) disimpan: {vtt_name}")

                        # 3c. Auto-Translate jika target bahasa adalah Bahasa Indonesia
                        if task.auto_translate_sub and task.target_sub_lang in ["id", "ind"] and src_sub_lang not in ["id", "ind"]:
                            task.status = "translating_sub"
                            task.speed_str = "Menerjemahkan subtitle ke Indonesia..."
                            translated_vtt_name = f"{final_mp4_path.stem}.id.vtt"
                            translated_vtt_path = DOWNLOADS_DIR / translated_vtt_name

                            def on_translate_progress(done: int, total: int):
                                task.speed_str = f"Menerjemahkan sub ({done}/{total})..."
                                task.percent = min(99.0 + (done / total * 0.9), 99.9)

                            logger.info(f"Menerjemahkan subtitle otomatis: {vtt_name} -> {translated_vtt_name}")
                            trans_ok = translate_subtitle_file(
                                src_path=vtt_file_path,
                                dest_path=translated_vtt_path,
                                src_lang=src_sub_lang,
                                target_lang="id",
                                progress_callback=on_translate_progress
                            )
                            if trans_ok and translated_vtt_path.exists() and translated_vtt_path.stat().st_size > 0:
                                target_sub_path = translated_vtt_path
                                target_sub_lang = "ind"
                                task.subtitles_files.append(translated_vtt_name)
                                logger.info(f"Auto-translate sukses! Track MP4 akan menggunakan: {translated_vtt_name}")
                    except Exception as e_sub_dl:
                        logger.warning(f"Gagal mengunduh/menerjemahkan subtitle: {e_sub_dl}")

        # 4. Embed subtitle jika tersedia via FFmpeg
        task.status = "embedding"
        task.speed_str = "Menanamkan subtitle ke MP4..."
        task.percent = 99.5
        embedded_success = False
        if target_sub_path and target_sub_path.exists() and FFMPEG_BIN.exists():
            embedded_temp_path = DOWNLOADS_DIR / f".embed_{task.task_id}_{final_filename}"
            import subprocess
            cmd = [
                str(FFMPEG_BIN), "-y",
                "-i", str(temp_dl_path),
                "-i", str(target_sub_path),
                "-c", "copy",
                "-c:s", "mov_text",
                "-metadata:s:s:0", f"language={target_sub_lang}",
                "-movflags", "+faststart",
                str(embedded_temp_path)
            ]
            try:
                proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
                if proc.returncode == 0 and embedded_temp_path.exists() and embedded_temp_path.stat().st_size > 1024 * 100:
                    if temp_dl_path.exists():
                        temp_dl_path.unlink()
                    embedded_temp_path.rename(final_mp4_path)
                    embedded_success = True
                    logger.info(f"Subtitle berhasil diembed ke {final_filename}")
            except Exception as e_embed:
                logger.warning(f"Gagal embed subtitle via FFmpeg: {e_embed}")
            finally:
                if embedded_temp_path.exists():
                    try: embedded_temp_path.unlink()
                    except: pass

        if not embedded_success:
            temp_dl_path.rename(final_mp4_path)

        task.status = "completed"
        task.percent = 100.0
        task.output_file = final_mp4_path.name
        task.downloaded_bytes = final_mp4_path.stat().st_size
        task.total_bytes = task.downloaded_bytes
        task.speed_str = "Selesai"
        task.eta_str = "00:00"
        logger.info(f"Download tuntas berhasil: {final_mp4_path.name} ({format_bytes(task.downloaded_bytes)})")


# Helper functions for filesystem listing
def list_local_downloads() -> List[Dict[str, Any]]:
    files = []
    if not DOWNLOADS_DIR.exists():
        return files

    for entry in DOWNLOADS_DIR.iterdir():
        if entry.is_file() and not entry.name.startswith("."):
            stat = entry.stat()
            ext = entry.suffix.lstrip(".").lower()
            files.append({
                "filename": entry.name,
                "size_bytes": stat.st_size,
                "size_str": format_bytes(stat.st_size),
                "modified_at": stat.st_mtime,
                "ext": ext,
                "url": f"/api/files/{entry.name}",
            })
    files.sort(key=lambda x: x["modified_at"], reverse=True)
    return files


def delete_local_file(filename: str) -> bool:
    safe_name = os.path.basename(filename)
    file_path = DOWNLOADS_DIR / safe_name
    if file_path.exists() and file_path.is_file():
        file_path.unlink()
        return True
    return False
