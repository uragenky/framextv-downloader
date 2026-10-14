"""StreamDown — URL parser for FrameX links.

Supported input formats:
  - Full URL:  https://framextv.xyz/watch/550
               https://framextv.xyz/movie/550
               https://framextv.xyz/embed/550
               https://framextv.xyz/watch/1399/1/1
               https://framextv.xyz/tv/1399
               https://framextv.xyz/embed/tv/1399/1/1
               https://framextv.xyz/embed/movie/550
               https://framextv.xyz/watch/anime/12345/1
               https://framextv.xyz/anime/12345
  - Plain TMDB ID: 550
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedLink:
    media_type: str            # "movie" | "tv" | "anime"
    tmdb_id: str               # TMDB ID (or AniList ID for anime)
    season: Optional[int] = None
    episode: Optional[int] = None
    raw_input: str = ""

    @property
    def is_tv(self) -> bool:
        return self.media_type == "tv"

    @property
    def is_anime(self) -> bool:
        return self.media_type == "anime"

    @property
    def label(self) -> str:
        if self.is_tv:
            s = f" S{self.season:02d}" if self.season else ""
            e = f"E{self.episode:02d}" if self.episode else ""
            return f"TV {self.tmdb_id}{s}{e}"
        if self.is_anime:
            e = f" EP{self.episode}" if self.episode else ""
            return f"Anime {self.tmdb_id}{e}"
        return f"Movie {self.tmdb_id}"


# ── URL patterns ────────────────────────────────────────────────────────────
_FRAMEX_HOSTS = re.compile(
    r"^https?://(?:www\.)?(?:framextv\.(?:xyz|tech))"
)

# Path patterns (order matters — more specific first)
_PATH_PATTERNS: list[tuple[re.Pattern, str]] = [
    # /watch/anime/<id>/<ep>
    (re.compile(r"/(?:watch|embed)/anime/(\d+)/(\d+)"), "anime"),
    # /anime/<id>
    (re.compile(r"/(?:watch|embed|anime)/anime/(\d+)$"), "anime"),
    (re.compile(r"/anime/(\d+)$"), "anime"),
    # /embed/tv/<id>/<season>/<episode> or /tv/<id>/<season>/<episode>
    (re.compile(r"/(?:watch|embed|tv)/(?:tv/)?(\d+)/(\d+)/(\d+)"), "tv"),
    # /tv/<id>
    (re.compile(r"/(?:watch|embed|tv)/(?:tv/)?(\d+)$"), "tv_or_movie"),
    # /embed/movie/<id>
    (re.compile(r"/(?:watch|embed)/movie/(\d+)"), "movie"),
    # /movie/<id>
    (re.compile(r"/movie/(\d+)"), "movie"),
    # /watch/<id> or /embed/<id>  (assumed movie)
    (re.compile(r"/(?:watch|embed)/(\d+)$"), "movie"),
]


def parse_link(raw: str) -> ParsedLink:
    """Parse a FrameX URL or plain TMDB ID into a structured ParsedLink."""
    raw = raw.strip()
    if not raw:
        raise ValueError("Input kosong.")

    # ── Plain numeric ID (assumed movie) ────────────────────────────────
    if re.fullmatch(r"\d+", raw):
        return ParsedLink(media_type="movie", tmdb_id=raw, raw_input=raw)

    # ── Full URL ────────────────────────────────────────────────────────
    if not _FRAMEX_HOSTS.match(raw):
        raise ValueError(
            f"URL tidak dikenali. Gunakan link dari framextv.xyz atau TMDB ID langsung."
        )

    from urllib.parse import urlparse, parse_qs

    parsed_url = urlparse(raw)
    path = parsed_url.path.rstrip("/")
    qs = parse_qs(parsed_url.query)

    for pattern, kind in _PATH_PATTERNS:
        m = pattern.search(path)
        if not m:
            continue

        groups = m.groups()

        # Check query string overrides if present (?episode=1&season=1)
        qs_ep = int(qs["episode"][0]) if "episode" in qs and qs["episode"][0].isdigit() else None
        qs_season = int(qs["season"][0]) if "season" in qs and qs["season"][0].isdigit() else None

        if kind == "anime":
            ep = int(groups[1]) if len(groups) > 1 else qs_ep
            return ParsedLink(
                media_type="anime",
                tmdb_id=groups[0],
                episode=ep,
                raw_input=raw,
            )

        if kind == "tv":
            season = int(groups[1]) if len(groups) > 1 else qs_season
            episode = int(groups[2]) if len(groups) > 2 else qs_ep
            return ParsedLink(
                media_type="tv",
                tmdb_id=groups[0],
                season=season,
                episode=episode,
                raw_input=raw,
            )

        if kind == "tv_or_movie":
            # Heuristic: if path starts with /tv, treat as TV
            if "/tv" in path.lower() or qs_season is not None or qs_ep is not None:
                return ParsedLink(
                    media_type="tv",
                    tmdb_id=groups[0],
                    season=qs_season,
                    episode=qs_ep,
                    raw_input=raw,
                )
            # Otherwise movie
            return ParsedLink(
                media_type="movie", tmdb_id=groups[0], raw_input=raw
            )

        # movie
        return ParsedLink(
            media_type="movie", tmdb_id=groups[0], raw_input=raw
        )

    raise ValueError(
        f"Tidak dapat mengekstrak ID dari URL: {raw}"
    )
