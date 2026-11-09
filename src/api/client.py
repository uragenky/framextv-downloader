"""
Klien API frameXTV dengan dukungan Multi-Host Failover dan Otomatis Provider Fallback.
"""

import urllib.request
import urllib.parse
import json
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("framextv_client")

BACKEND_HOSTS = [
    "https://api.framextv.cc",
    "https://api.framextv.tech",
    "https://api.framextv.xyz",
    "https://api.framextv.pro"
]

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://framextv.cc/",
    "Origin": "https://framextv.cc"
}


class FrameXClient:
    def __init__(self, base_hosts: Optional[List[str]] = None):
        self.hosts = base_hosts or BACKEND_HOSTS
        self.active_host_index = 0

    @property
    def current_host(self) -> str:
        return self.hosts[self.active_host_index]

    def _rotate_host(self) -> str:
        self.active_host_index = (self.active_host_index + 1) % len(self.hosts)
        new_host = self.current_host
        logger.warning(f"[Failover] Berpindah ke backend host: {new_host}")
        return new_host

    def request(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15) -> Dict[str, Any]:
        """Melakukan HTTP GET request ke host yang aktif dengan rotasi otomatis jika gagal."""
        query_string = f"?{urllib.parse.urlencode(params)}" if params else ""
        last_error = None

        for _ in range(len(self.hosts)):
            url = f"{self.current_host}{path}{query_string}"
            try:
                req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        raw = resp.read().decode("utf-8", errors="ignore")
                        return json.loads(raw)
            except Exception as e:
                last_error = e
                logger.debug(f"Request ke {url} gagal: {e}. Mencoba host berikutnya...")
                self._rotate_host()

        raise RuntimeError(f"Semua backend host gagal dihubungi. Error terakhir: {last_error}")

    # ==========================================
    # Discovery & Pencarian
    # ==========================================

    def search(self, query: str, media_type: str = "movie", page: int = 1) -> List[Dict[str, Any]]:
        """Mencari film, serial TV, atau anime."""
        if media_type == "anime":
            res = self.request("/anime/api/search", {"q": query})
            return res.get("results") or res.get("items") or []
        else:
            res = self.request("/api/search", {"q": query, "type": media_type, "page": page})
            return res.get("results") or []

    def get_details(self, media_id: int | str, media_type: str = "movie") -> Dict[str, Any]:
        """Mengambil metadata lengkap (sinopsis, seasons, pemeran, dll.)."""
        if media_type == "anime":
            return self.request("/anime/api/details", {"id": media_id})
        else:
            return self.request("/api/details", {"id": media_id, "type": media_type})

    def get_providers(self, media_type: str = "movie") -> List[Dict[str, Any]]:
        """Mengambil daftar status server / extractor provider."""
        path = "/anime/api/providers" if media_type == "anime" else "/api/providers"
        res = self.request(path)
        return res.get("providers") or []

    # ==========================================
    # Stream Video Extraction & Subtitle
    # ==========================================

    def get_stream(
        self,
        media_type: str,
        media_id: int | str,
        season: int = 1,
        episode: int = 1,
        provider: Optional[str] = None,
        auto_fallback: bool = True
    ) -> Dict[str, Any]:
        """
        Mengambil direct stream playable link (.m3u8 HLS / MP4).
        Jika provider awal gagal dan auto_fallback=True, sistem otomatis mencoba provider lain yang 'available'.
        """
        params: Dict[str, Any] = {"id": str(media_id), "type": media_type}
        if media_type == "tv":
            params["season"] = str(season)
            params["episode"] = str(episode)
        elif media_type == "anime":
            params["season"] = str(season)
            params["episode"] = str(episode)
            params["sub_type"] = "sub"

        if provider:
            params["provider"] = provider

        stream_path = "/anime/api/stream" if media_type == "anime" else "/api/stream"

        try:
            res = self.request(stream_path, params)
            if res.get("success") and res.get("sources"):
                return res
        except Exception as e:
            logger.warning(f"Provider {provider or 'default'} gagal: {e}")

        # Fallback Pipeline jika provider gagal
        if auto_fallback:
            try:
                providers_list = self.get_providers(media_type)
                available = [
                    p["id"] for p in providers_list
                    if p.get("status") in ["available", "active"] and p.get("id") != provider
                ]
                for alt_prov in available:
                    logger.info(f"Mencoba provider alternatif: {alt_prov}")
                    params["provider"] = alt_prov
                    try:
                        res = self.request(stream_path, params)
                        if res.get("success") and res.get("sources"):
                            return res
                    except Exception:
                        continue
            except Exception as e_prov:
                logger.error(f"Gagal mengambil provider alternatif: {e_prov}")

        raise RuntimeError(f"Tidak dapat mengekstrak stream video yang aktif untuk ID {media_id}")

    def get_subtitles(
        self,
        media_id: int | str,
        media_type: str = "movie",
        season: int = 1,
        episode: int = 1
    ) -> List[Dict[str, Any]]:
        """Mengambil daftar subtitle (.vtt) yang tersedia."""
        params: Dict[str, Any] = {"id": str(media_id), "type": media_type}
        if media_type == "tv":
            params["season"] = str(season)
            params["episode"] = str(episode)

        res = self.request("/api/subtitles", params)
        return res.get("subtitles") or []
