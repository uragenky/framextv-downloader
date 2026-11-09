"""
Integrasi Google Drive API.
Mendukung auto-detect token lokal jika tersedia, atau dijalankan via Cloud Runner.
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger("gdrive_service")

# Lokasi token yang dicari secara fleksibel
POSSIBLE_TOKEN_PATHS = [
    os.path.join(os.getcwd(), "token.json"),
    os.path.expanduser("~/.google-mcp/tokens/personal.json"),
    os.path.expanduser("~/.config/gdrive/token.json")
]


class GDriveService:
    def __init__(self, token_path: Optional[str] = None):
        self.token_path = token_path
        if not self.token_path:
            for p in POSSIBLE_TOKEN_PATHS:
                if os.path.exists(p):
                    self.token_path = p
                    break
        self._service = None
        self._user_info = None

    def is_authenticated(self) -> bool:
        return bool(self.token_path and os.path.exists(self.token_path))

    def get_service(self):
        if self._service:
            return self._service

        if not self.is_authenticated():
            raise FileNotFoundError("Kredensial Google Drive belum terhubung.")

        with open(self.token_path, "r", encoding="utf-8") as f:
            token_data = json.load(f)

        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret")
        )

        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def get_user_info(self) -> Dict[str, Any]:
        """Mengambil nama dan email akun Google yang aktif."""
        if self._user_info:
            return self._user_info

        if not self.is_authenticated():
            return {
                "name": "Pengguna Google",
                "email": "Belum Terhubung",
                "photo": "",
                "quota": {}
            }

        try:
            srv = self.get_service()
            about = srv.about().get(fields="user(displayName, emailAddress, photoLink), storageQuota").execute()
            user = about.get("user", {})
            self._user_info = {
                "name": user.get("displayName", "Pengguna Google"),
                "email": user.get("emailAddress", "Terhubung"),
                "photo": user.get("photoLink", ""),
                "quota": about.get("storageQuota", {})
            }
            return self._user_info
        except Exception as e:
            logger.warning(f"Gagal mengambil user info via API: {e}")
            return {
                "name": "Pengguna Google",
                "email": "Terhubung",
                "photo": "",
                "quota": {}
            }

    def list_folders(self, limit: int = 40) -> List[Dict[str, str]]:
        """Mengambil daftar folder asli yang ada di Google Drive."""
        if not self.is_authenticated():
            return []
        try:
            srv = self.get_service()
            results = srv.files().list(
                q="mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                pageSize=limit,
                fields="files(id, name)",
                orderBy="name"
            ).execute()
            folders = results.get("files", [])
            return [{"id": f["id"], "name": f["name"]} for f in folders]
        except Exception as e:
            logger.error(f"Gagal mengambil daftar folder Google Drive: {e}")
            return []
