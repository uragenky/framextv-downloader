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
import json
import shutil
import logging
import threading
import urllib.request
import urllib.parse
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable

import yt_dlp

from ..api.client import FrameXClient
from .sub_translator import translate_subtitle_file, normalize_subtitle_file

logger = logging.getLogger("local_downloader")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
BIN_DIR = BASE_DIR / "bin"
if BIN_DIR.exists():
    os.environ["PATH"] = f"{BIN_DIR}:{os.environ.get('PATH', '')}"
FFMPEG_BIN = BIN_DIR / "ffmpeg" if (BIN_DIR / "ffmpeg").exists() else Path("ffmpeg")
FFPROBE_BIN = BIN_DIR / "ffprobe" if (BIN_DIR / "ffprobe").exists() else Path("ffprobe")

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Pemetaan kode bahasa 2-huruf ke variasi 3-huruf / label audio untuk pencocokan audio asli
LANG_TOKENS_MAP = {
    "ko": ["kor", "ko", "korean"],
    "ja": ["jpn", "ja", "japanese"],
    "en": ["eng", "en", "english"],
    "zh": ["chi", "zho", "zh", "chinese", "mandarin", "cantonese"],
    "id": ["ind", "id", "indonesian"],
    "es": ["spa", "es", "spanish"],
    "fr": ["fra", "fre", "fr", "french"],
    "de": ["deu", "ger", "de", "german"],
    "it": ["ita", "it", "italian"],
    "th": ["tha", "th", "thai"],
    "ru": ["rus", "ru", "russian"],
    "pt": ["por", "pt", "portuguese"],
    "hi": ["hin", "hi", "hindi"],
    "tl": ["tgl", "fil", "tl", "tagalog", "filipino"],
    "vi": ["vie", "vi", "vietnamese"],
    "tr": ["tur", "tr", "turkish"],
    "ar": ["ara", "ar", "arabic"],
}


def probe_audio_streams(file_path: Path) -> List[Dict[str, Any]]:
    """Membaca daftar track audio dari file video menggunakan ffprobe."""
    bin_probe = str(FFPROBE_BIN) if FFPROBE_BIN.exists() else "ffprobe"
    try:
        cmd = [
            bin_probe, "-v", "error",
            "-show_entries", "stream=index,codec_type,codec_name:stream_tags=language,title:stream_disposition=default",
            "-of", "json",
            str(file_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            audio_streams = []
            audio_idx = 0
            for s in data.get("streams", []):
                if s.get("codec_type") == "audio":
                    s["audio_index"] = audio_idx
                    audio_streams.append(s)
                    audio_idx += 1
            return audio_streams
    except Exception as e:
        logger.warning(f"Gagal ffprobe audio streams: {e}")
    return []


def find_original_audio_index(audio_streams: List[Dict[str, Any]], orig_lang: str) -> Optional[int]:
    """Mencari audio_index yang cocok dengan bahasa asli serial / film."""
    if not orig_lang or not audio_streams:
        return None
    orig_lang = orig_lang.lower().strip()
    match_tokens = LANG_TOKENS_MAP.get(orig_lang, [orig_lang])

    # 1. Cek language tag pada metadata stream
    for s in audio_streams:
        tags = s.get("tags") or {}
        lang_tag = (tags.get("language") or "").lower().strip()
        if lang_tag in match_tokens:
            return s["audio_index"]

    # 2. Cek title tag
    for s in audio_streams:
        tags = s.get("tags") or {}
        title_tag = (tags.get("title") or "").lower().strip()
        for tok in match_tokens:
            if tok in title_tag:
                return s["audio_index"]

    return None


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
    original_language: str = ""

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
            "original_language": self.original_language,
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
        # Bersihkan file temporary sisa crash/reboot sebelumnya
        self._cleanup_orphan_temps()

    def _cleanup_orphan_temps(self):
        try:
            for p in DOWNLOADS_DIR.glob(".tmp_*"):
                if p.is_file():
                    try: p.unlink()
                    except: pass
            for p in DOWNLOADS_DIR.glob(".embed_*"):
                if p.is_file():
                    try: p.unlink()
                    except: pass
        except Exception:
            pass

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
                if task.status in ["queued", "resolving", "downloading", "translating_sub", "embedding"]:
                    task.status = "cancelled"
                    task.error = "Download dibatalkan oleh pengguna."
                if task_id in self.queue:
                    self.queue.remove(task_id)
                return True
        return False

    def retry_task(self, task_id: str) -> bool:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            task.is_cancelled = False
            task.status = "queued"
            task.error = ""
            task.percent = 0.0
            task.downloaded_bytes = 0
            task.speed_str = "0 KB/s"
            task.eta_str = "--:--"
            if task_id not in self.queue:
                self.queue.append(task_id)
        self._ensure_worker()
        return True

    def cancel_all(self) -> int:
        count = 0
        with self.lock:
            for task_id in list(self.queue):
                task = self.tasks.get(task_id)
                if task:
                    task.is_cancelled = True
                    task.status = "cancelled"
                    task.error = "Download dibatalkan secara massal."
                    count += 1
            self.queue.clear()
            for task in self.tasks.values():
                if task.status in ["resolving", "downloading", "embedding", "translating_sub"]:
                    task.is_cancelled = True
                    task.status = "cancelled"
                    task.error = "Download dibatalkan secara massal."
                    count += 1
        return count

    def get_queue_summary(self) -> Dict[str, Any]:
        with self.lock:
            tasks_list = [t.to_dict() for t in sorted(self.tasks.values(), key=lambda x: x.created_at, reverse=True)]
            queued_count = sum(1 for t in self.tasks.values() if t.status == "queued")
            active_tasks = [t.to_dict() for t in self.tasks.values() if t.status in ["resolving", "downloading", "embedding", "translating_sub"]]
            return {
                "active": active_tasks[0] if active_tasks else None,
                "queued_count": queued_count,
                "total_count": len(self.tasks),
                "tasks": tasks_list
            }

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
        original_language: Optional[str] = None,
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
            original_language=original_language or "",
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

        # 1. Tentukan kandidat provider untuk fallback pipeline
        candidate_providers = []
        if task.provider:
            candidate_providers.append(task.provider)

        try:
            prov_list = self.client.get_providers(task.media_type)
            active_provs = [p["id"] for p in prov_list if p.get("status") in ["available", "active"]]
        except Exception as e_prov:
            logger.warning(f"Gagal mengambil provider list: {e_prov}")
            active_provs = []

        # Urutan prioritas server yang terbukti stabil
        priority_servers = ["giant", "battle_copter", "bowler", "executioner", "little_prince", "grand_warden", "sparky", "super_barbarian"]
        for p in priority_servers:
            if p in active_provs and p not in candidate_providers:
                candidate_providers.append(p)
        for p in active_provs:
            if p not in candidate_providers:
                candidate_providers.append(p)

        if not candidate_providers:
            candidate_providers = ["giant", "battle_copter", "bowler", "default"]

        final_filename = f"{task.filename}.mp4"
        final_mp4_path = DOWNLOADS_DIR / final_filename

        counter = 1
        base_name = task.filename
        while final_mp4_path.exists():
            final_filename = f"{base_name} ({counter}).mp4"
            final_mp4_path = DOWNLOADS_DIR / final_filename
            counter += 1

        temp_dl_path = DOWNLOADS_DIR / f".tmp_{task.task_id}_{final_filename}"

        # Pastikan bahasa asli media terdeteksi (misal 'ko' untuk drakor, 'ja' untuk anime)
        if not task.original_language and task.media_id:
            try:
                det = self.client.get_details(task.media_id, task.media_type)
                if det and det.get("original_language"):
                    task.original_language = det.get("original_language")
                    logger.info(f"[{task.filename}] Bahasa asli terdeteksi dari metadata: {task.original_language}")
            except Exception as e_det:
                logger.debug(f"Gagal deteksi original_language: {e_det}")

        # 2. Persiapan Subtitle Secara PARALEL di Background Thread
        sub_result = {
            "target_sub_path": None,
            "target_sub_lang": "ind" if task.target_sub_lang == "id" else "eng",
            "error": None,
            "done": False,
            "sub_progress": "",
        }

        def _sub_worker():
            try:
                subs_list = self.client.get_subtitles(
                    media_id=task.media_id,
                    media_type=task.media_type,
                    season=task.season,
                    episode=task.episode
                )
                if not subs_list:
                    return

                # Cek apakah subtitle bahasa Indonesia sudah tersedia langsung
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

                if direct_sub and direct_sub.get("url"):
                    vtt_name = f"{final_mp4_path.stem}.id.vtt"
                    vtt_file_path = DOWNLOADS_DIR / vtt_name
                    srt_name = f"{final_mp4_path.stem}.id.srt"
                    srt_file_path = DOWNLOADS_DIR / srt_name
                    req_sub = urllib.request.Request(direct_sub["url"], headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req_sub, timeout=12) as s_resp, open(vtt_file_path, "wb") as sf:
                        sf.write(s_resp.read())
                    normalize_subtitle_file(vtt_file_path, vtt_file_path, srt_file_path)
                    sub_result["target_sub_path"] = vtt_file_path
                    sub_result["target_sub_lang"] = "ind"
                    task.subtitles_files.append(vtt_name)
                    if srt_file_path.exists():
                        task.subtitles_files.append(srt_name)
                    logger.info(f"[{task.filename}] Subtitle Indonesia langsung siap & dinormalisasi (background paralel)")
                else:
                    # Ambil subtitle alternatif (utamakan English)
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

                    if not source_sub and subs_list:
                        source_sub = subs_list[0]

                    if source_sub and source_sub.get("url"):
                        src_sub_lang = source_sub.get("lang") or "en"
                        vtt_name = f"{final_mp4_path.stem}.{src_sub_lang}.vtt"
                        vtt_file_path = DOWNLOADS_DIR / vtt_name
                        req_sub = urllib.request.Request(source_sub["url"], headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req_sub, timeout=12) as s_resp, open(vtt_file_path, "wb") as sf:
                            sf.write(s_resp.read())
                        normalize_subtitle_file(vtt_file_path, vtt_file_path)
                        task.subtitles_files.append(vtt_name)
                        sub_result["target_sub_path"] = vtt_file_path
                        sub_result["target_sub_lang"] = "eng" if src_sub_lang in ["en", "eng"] else src_sub_lang

                        # Terjemahkan subtitle ke Indonesia secara simultan
                        if task.auto_translate_sub and task.target_sub_lang in ["id", "ind"] and src_sub_lang not in ["id", "ind"]:
                            translated_vtt_name = f"{final_mp4_path.stem}.id.vtt"
                            translated_vtt_path = DOWNLOADS_DIR / translated_vtt_name

                            def on_translate_progress(done: int, total: int):
                                sub_result["sub_progress"] = f"Sub {done}/{total}"

                            logger.info(f"[{task.filename}] Menerjemahkan subtitle di background simultan...")
                            trans_ok = translate_subtitle_file(
                                src_path=vtt_file_path,
                                dest_path=translated_vtt_path,
                                src_lang=src_sub_lang,
                                target_lang="id",
                                progress_callback=on_translate_progress
                            )
                            if trans_ok and translated_vtt_path.exists() and translated_vtt_path.stat().st_size > 0:
                                sub_result["target_sub_path"] = translated_vtt_path
                                sub_result["target_sub_lang"] = "ind"
                                task.subtitles_files.append(translated_vtt_name)
                                srt_candidate = translated_vtt_path.with_suffix(".srt")
                                if srt_candidate.exists():
                                    task.subtitles_files.append(srt_candidate.name)
                                logger.info(f"[{task.filename}] Terjemahan subtitle simultan tuntas!")
            except Exception as e_sub:
                logger.warning(f"[{task.filename}] Error memproses subtitle simultan: {e_sub}")
                sub_result["error"] = str(e_sub)
            finally:
                sub_result["done"] = True

        sub_thread = threading.Thread(target=_sub_worker, daemon=True)
        sub_thread.start()

        # 3. Progress Hook untuk yt-dlp
        def ytdl_progress_hook(d):
            if task.is_cancelled:
                raise DownloadCancelledError("Download dibatalkan oleh pengguna.")

            status = d.get("status")
            if status == "downloading":
                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                speed = d.get("speed", 0)
                eta = d.get("eta", 0)

                frag_index = d.get("fragment_index")
                frag_count = d.get("fragment_count")

                if frag_index and frag_count:
                    task.percent = min(99.0, (frag_index / frag_count) * 100.0)
                elif total > 0:
                    task.percent = min(99.0, (downloaded / total) * 100.0)

                task.downloaded_bytes = downloaded
                task.total_bytes = total
                task.speed_bps = speed or 0.0
                sub_indicator = f" [🌐 {sub_result['sub_progress']}]" if sub_result.get("sub_progress") and not sub_result.get("done") else ""
                task.speed_str = f"{format_bytes(speed)}/s{sub_indicator}" if speed else f"0 KB/s{sub_indicator}"
                task.eta_seconds = eta or 0.0
                task.eta_str = format_time(eta)

        download_success = False
        attempted_logs = []

        # 4. Iterasi Fallback Antar Server & Sumber Stream
        for prov_idx, prov in enumerate(candidate_providers):
            if task.is_cancelled:
                break

            task.status = "resolving"
            task.provider = prov
            task.speed_str = f"Mencoba server {prov} ({prov_idx + 1}/{len(candidate_providers)})..."
            logger.info(f"[{task.filename}] Mencoba server {prov} ({prov_idx + 1}/{len(candidate_providers)})")

            try:
                stream_data = self.client.get_stream(
                    media_type=task.media_type,
                    media_id=task.media_id,
                    season=task.season,
                    episode=task.episode,
                    provider=prov,
                    auto_fallback=False
                )
            except Exception as e_stream:
                logger.warning(f"Server {prov} gagal diambil stream: {e_stream}")
                attempted_logs.append(f"{prov}: {e_stream}")
                continue

            sources = stream_data.get("sources", [])
            if not sources or not stream_data.get("success"):
                attempted_logs.append(f"{prov}: tidak ada sources")
                continue

            for src_idx, source in enumerate(sources):
                if task.is_cancelled:
                    break

                stream_url = source.get("url")
                if not stream_url:
                    continue

                task.status = "downloading"
                quality = source.get("quality", "HD")
                task.speed_str = f"Menghubungkan {prov} ({quality})..."

                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "Referer": "https://framextv.cc/",
                    "Origin": "https://framextv.cc",
                }
                if "origin=" in stream_url or "ref=" in stream_url:
                    try:
                        parsed_u = urllib.parse.urlparse(stream_url)
                        qs = urllib.parse.parse_qs(parsed_u.query)
                        if "origin" in qs:
                            headers["Origin"] = qs["origin"][0]
                        if "ref" in qs or "referer" in qs:
                            headers["Referer"] = qs.get("ref", qs.get("referer", []))[0]
                    except Exception:
                        pass

                ydl_opts = {
                    "outtmpl": str(temp_dl_path),
                    "concurrent_fragment_downloads": 4,  # Aman dari CDN rate-limit & socket drops
                    "retries": 20,
                    "fragment_retries": 20,
                    "skip_unavailable_fragments": True,
                    "nocheckcertificate": True,
                    "quiet": True,
                    "no_warnings": True,
                    "progress_hooks": [ytdl_progress_hook],
                    "http_headers": headers,
                }
                if BIN_DIR.exists():
                    ydl_opts["ffmpeg_location"] = str(BIN_DIR)

                try:
                    if temp_dl_path.exists():
                        try: temp_dl_path.unlink()
                        except: pass

                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([stream_url])

                except DownloadCancelledError:
                    task.status = "cancelled"
                    task.error = "Download dibatalkan oleh pengguna."
                    if temp_dl_path.exists():
                        try: temp_dl_path.unlink()
                        except: pass
                    return
                except Exception as e_dl:
                    logger.warning(f"Server {prov} (source #{src_idx}) gagal unduh: {e_dl}. Mencoba server cadangan...")
                    attempted_logs.append(f"{prov} src#{src_idx}: {e_dl}")
                    if temp_dl_path.exists():
                        try: temp_dl_path.unlink()
                        except: pass
                    continue

                if temp_dl_path.exists() and temp_dl_path.stat().st_size > 1024 * 100:
                    download_success = True
                    task.provider = prov
                    logger.info(f"[{task.filename}] Berhasil download dari server {prov} ({quality})! Ukuran: {format_bytes(temp_dl_path.stat().st_size)}")
                    break

            if download_success:
                break

        if task.is_cancelled:
            task.status = "cancelled"
            task.error = "Download dibatalkan oleh pengguna."
            if temp_dl_path.exists():
                try: temp_dl_path.unlink()
                except: pass
            return

        if not download_success:
            unreleased_hint = ""
            try:
                s_info = self.client.get_season(task.media_id, task.season)
                for ep_item in s_info.get("episodes", []):
                    if ep_item.get("episode_number") == task.episode:
                        air_d = ep_item.get("air_date")
                        if air_d:
                            unreleased_hint = f" (Jadwal rilis: {air_d})"
                        break
            except Exception:
                pass

            task.status = "failed"
            if unreleased_hint:
                task.error = f"Episode belum tayang di server stream{unreleased_hint}."
            else:
                task.error = f"Semua server stream gagal ({len(candidate_providers)} server telah dicoba)."
            logger.error(f"Download gagal total untuk {task.filename}: {task.error}")
            if temp_dl_path.exists():
                try: temp_dl_path.unlink()
                except: pass
            return

        # 5. Tunggu proses subtitle/terjemahan background selesai (jika masih berjalan)
        if not sub_result.get("done"):
            task.status = "translating_sub"
            start_wait = time.time()
            max_sub_wait = 180  # Maksimal 3 menit toleransi terjemahan
            logger.info(f"[{task.filename}] Menunggu terjemahan subtitle background tuntas...")
            while not sub_result.get("done") and (time.time() - start_wait < max_sub_wait):
                if task.is_cancelled:
                    break
                prog = sub_result.get("sub_progress")
                task.speed_str = f"Menerjemahkan subtitle ({prog})..." if prog else "Menerjemahkan subtitle ke Indonesia..."
                time.sleep(0.5)

        target_sub_path = sub_result.get("target_sub_path")
        target_sub_lang = sub_result.get("target_sub_lang", "ind")
        has_sub = bool(target_sub_path and target_sub_path.exists())

        # 6. Analisis Track Audio (ffprobe) & Force Audio Asli (Original)
        task.status = "embedding"
        task.percent = 99.0
        task.speed_str = "Menanamkan subtitle & mengatur audio original..."

        audio_streams = probe_audio_streams(temp_dl_path)
        orig_audio_idx = find_original_audio_index(audio_streams, task.original_language)

        need_remux = has_sub or (len(audio_streams) > 1) or (orig_audio_idx is not None)
        embedded_success = False

        if need_remux and FFMPEG_BIN.exists():
            embedded_temp_path = DOWNLOADS_DIR / f".embed_{task.task_id}_{final_filename}"
            sub_title_label = "Indonesian" if target_sub_lang in ["id", "ind"] else "English"

            cmd = [
                str(FFMPEG_BIN), "-y",
                "-i", str(temp_dl_path),
            ]
            if has_sub:
                cmd.extend(["-i", str(target_sub_path)])

            # Map video track (hanya video utama)
            cmd.extend(["-map", "0:v:0"])

            # Map audio tracks & Force original audio sebagai stream audio ke-0 (default)
            if orig_audio_idx is not None and len(audio_streams) > 1:
                cmd.extend(["-map", f"0:a:{orig_audio_idx}"])
                for i in range(len(audio_streams)):
                    if i != orig_audio_idx:
                        cmd.extend(["-map", f"0:a:{i}"])
                cmd.extend(["-disposition:a:0", "default"])
                for i in range(1, len(audio_streams)):
                    cmd.extend([f"-disposition:a:{i}", "0"])
                logger.info(f"[{task.filename}] Audio asli ({task.original_language}) diposisikan sebagai audio default ke-0 (track {orig_audio_idx} -> 0)")
            elif len(audio_streams) > 0:
                cmd.extend(["-map", "0:a"])
                cmd.extend(["-disposition:a:0", "default"])
                for i in range(1, len(audio_streams)):
                    cmd.extend([f"-disposition:a:{i}", "0"])
            else:
                cmd.extend(["-map", "0:a?"])

            cmd.extend(["-c:v", "copy", "-c:a", "copy"])

            if has_sub:
                cmd.extend([
                    "-map", "1:s:0",
                    "-c:s", "mov_text",
                    "-metadata:s:s:0", f"language={target_sub_lang}",
                    "-metadata:s:s:0", f"title={sub_title_label}",
                    "-metadata:s:s:0", f"handler_name={sub_title_label}",
                    "-disposition:s:0", "default+forced",
                ])

            cmd.extend(["-movflags", "+faststart", str(embedded_temp_path)])

            try:
                proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
                if proc.returncode == 0 and embedded_temp_path.exists() and embedded_temp_path.stat().st_size > 1024 * 100:
                    if temp_dl_path.exists():
                        temp_dl_path.unlink()
                    embedded_temp_path.rename(final_mp4_path)
                    embedded_success = True
                    logger.info(f"[{task.filename}] Sukses remux FFmpeg (Subtitle: {has_sub}, Audio default: {task.original_language or 'auto'})")
            except Exception as e_embed:
                logger.warning(f"Gagal remux FFmpeg: {e_embed}")
            finally:
                if embedded_temp_path.exists():
                    try:
                        embedded_temp_path.unlink()
                    except Exception:
                        pass

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

    now = time.time()
    for entry in DOWNLOADS_DIR.iterdir():
        if entry.is_file() and not entry.name.startswith("."):
            stat = entry.stat()
            ext = entry.suffix.lstrip(".").lower()
            files.append({
                "filename": entry.name,
                "size_bytes": stat.st_size,
                "size_str": format_bytes(stat.st_size),
                "modified_at": stat.st_mtime,
                "is_recent": (now - stat.st_mtime) < 86400,  # Kurang dari 24 jam
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


def delete_local_files(filenames: List[str]) -> Dict[str, Any]:
    """Menghapus banyak file sekaligus secara aman."""
    deleted = []
    failed = []
    freed_bytes = 0

    for name in filenames:
        safe_name = os.path.basename(name)
        file_path = DOWNLOADS_DIR / safe_name
        if file_path.exists() and file_path.is_file():
            try:
                sz = file_path.stat().st_size
                file_path.unlink()
                deleted.append(safe_name)
                freed_bytes += sz
            except Exception as e:
                failed.append({"filename": safe_name, "error": str(e)})
        else:
            failed.append({"filename": safe_name, "error": "Berkas tidak ditemukan"})

    return {
        "success": True,
        "deleted_count": len(deleted),
        "deleted_files": deleted,
        "freed_bytes": freed_bytes,
        "freed_str": format_bytes(freed_bytes),
        "failed_count": len(failed),
        "failed_files": failed,
    }


def cleanup_subtitles() -> Dict[str, Any]:
    """Menghapus semua file subtitle (.vtt / .srt / .ass) sisa dari folder downloads/."""
    sub_filenames = []
    if DOWNLOADS_DIR.exists():
        for entry in DOWNLOADS_DIR.iterdir():
            if entry.is_file() and entry.suffix.lower() in [".vtt", ".srt", ".ass"]:
                sub_filenames.append(entry.name)
    return delete_local_files(sub_filenames)
