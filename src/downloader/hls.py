"""
Downloader HLS Stream menggunakan yt-dlp dengan Multi-Threading.
"""

import subprocess
import os
import re
import urllib.request
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("hls_downloader")


def sanitize_filename(filename: str) -> str:
    """Membersihkan karakter ilegal dari nama file."""
    return re.sub(r'[\\/*?:"<>|]', "", filename).strip()


class HLSDownloader:
    def __init__(self, download_dir: str = "./downloads", concurrent_fragments: int = 2):
        self.download_dir = download_dir
        self.concurrent_fragments = concurrent_fragments
        os.makedirs(self.download_dir, exist_ok=True)

    def download_stream(
        self,
        stream_url: str,
        output_filename: str,
        headers: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Mengunduh stream HLS (.m3u8) dan menggabungkannya ke format .mp4.
        Mengembalikan path file hasil unduhan.
        """
        safe_name = sanitize_filename(output_filename)
        if not safe_name.endswith(".mp4"):
            safe_name += ".mp4"

        output_path = os.path.join(self.download_dir, safe_name)
        
        cmd = [
            "yt-dlp",
            "--concurrent-fragments", str(self.concurrent_fragments),
            "--no-check-certificates",
            "-o", output_path
        ]

        if headers:
            for k, v in headers.items():
                cmd.extend(["--add-header", f"{k}:{v}"])
        else:
            cmd.extend([
                "--add-header", "Referer:https://framextv.cc/",
                "--add-header", "Origin:https://framextv.cc"
            ])

        cmd.append(stream_url)

        logger.info(f"Menjalankan yt-dlp ke: {output_path}")
        result = subprocess.run(cmd)

        if result.returncode != 0:
            raise RuntimeError(f"Gagal mengunduh stream. Kode keluar yt-dlp: {result.returncode}")

        logger.info(f"Download tuntas: {output_path}")
        return output_path

    def download_subtitle(
        self,
        subtitles_list: List[Dict[str, Any]],
        base_output_path: str,
        preferred_langs: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        Mengunduh subtitle (.vtt) yang cocok dengan preferensi bahasa ke direktori yang sama dengan video.
        """
        if not subtitles_list:
            return None

        preferred = preferred_langs or ["id", "ind", "en", "eng"]
        target_sub = None

        for pref in preferred:
            for sub in subtitles_list:
                lang = (sub.get("lang") or "").lower()
                label = (sub.get("label") or "").lower()
                if pref == lang or pref in label:
                    target_sub = sub
                    break
            if target_sub:
                break

        if not target_sub:
            target_sub = subtitles_list[0]

        sub_url = target_sub.get("url")
        if not sub_url:
            return None

        sub_path = os.path.splitext(base_output_path)[0] + ".vtt"
        try:
            req = urllib.request.Request(sub_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp, open(sub_path, "wb") as f:
                f.write(resp.read())
            logger.info(f"Subtitle berhasil disimpan: {sub_path}")
            return sub_path
        except Exception as e:
            logger.warning(f"Gagal mengunduh subtitle dari {sub_url}: {e}")
            return None
