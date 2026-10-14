"""StreamDown — FrameX API client.

Communicates with FrameX backend and AniList GraphQL to retrieve:
  - Stream sources across all active providers (HLS playlists / direct MP4s)
  - Subtitle tracks
  - Rich metadata (TMDB for movies/TV, AniList for anime)
  - Multi-provider parallel checking
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

import aiohttp

from .config import (
    ANILIST_GRAPHQL_ENDPOINT,
    DEFAULT_HEADERS,
    FRAMEX_ANIME_STREAM_ENDPOINT,
    FRAMEX_API_BASE,
    FRAMEX_DETAILS_ENDPOINT,
    FRAMEX_STREAM_ENDPOINT,
    SEGMENT_TIMEOUT,
)
from .parser import ParsedLink

log = logging.getLogger("streamdown.client")


# ── Data models ─────────────────────────────────────────────────────────────

@dataclass
class StreamSource:
    url: str
    quality: str
    stream_type: str                   # "hls" | "mp4"
    server: str
    provider: str = ""
    audio: str = ""                    # "sub" | "dub"
    headers: dict[str, str] = field(default_factory=dict)
    skip_proxy: bool = False

    @property
    def label(self) -> str:
        audio_tag = f" ({self.audio.upper()})" if self.audio else ""
        return f"[{self.server}] {self.quality}{audio_tag}"


@dataclass
class Subtitle:
    url: str
    label: str
    language: str
    fmt: str = "vtt"                   # "vtt" | "srt"
    is_default: bool = False

    @property
    def safe_language(self) -> str:
        """Sanitised language string for filenames."""
        return self.language.replace(" ", "_").replace("/", "-")


@dataclass
class SeasonInfo:
    season_number: int
    name: str
    episode_count: int


@dataclass
class MediaDetails:
    title: str = ""
    year: str = ""
    poster: str = ""
    backdrop: str = ""
    overview: str = ""
    rating: str = ""
    genres: list[str] = field(default_factory=list)
    total_episodes: int = 1
    format: str = "MOVIE"              # "TV" | "MOVIE"
    is_movie: bool = True
    status: str = ""
    seasons: list[SeasonInfo] = field(default_factory=list)


@dataclass
class MediaInfo:
    success: bool
    provider: str
    sources: list[StreamSource] = field(default_factory=list)
    subtitles: list[Subtitle] = field(default_factory=list)
    details: Optional[MediaDetails] = None
    needs_episode_selection: bool = False
    total_episodes: int = 1
    selected_season: Optional[int] = None
    selected_episode: Optional[int] = None
    error: Optional[str] = None


# ── AniList GraphQL (Anime Metadata) ────────────────────────────────────────

def _clean_html_text(raw: str) -> str:
    if not raw:
        return ""
    return re.sub(r"<[^>]+>", "", raw).replace("&quot;", '"').replace("&#039;", "'").strip()


async def fetch_anilist_details(
    session: aiohttp.ClientSession, anilist_id: str
) -> Optional[MediaDetails]:
    """Fetch anime metadata from AniList GraphQL API."""
    query = """
    query ($id: Int) {
      Media (id: $id, type: ANIME) {
        id
        title { english romaji native }
        episodes
        bannerImage
        coverImage { extraLarge large medium }
        description
        seasonYear
        startDate { year }
        averageScore
        genres
        format
        status
      }
    }
    """
    try:
        payload = {"query": query, "variables": {"id": int(anilist_id)}}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=8)
        async with session.post(
            ANILIST_GRAPHQL_ENDPOINT, json=payload, headers=headers, timeout=timeout
        ) as resp:
            if resp.status == 200:
                body = await resp.json()
                media = body.get("data", {}).get("Media")
                if not media:
                    return None
                t_obj = media.get("title", {})
                title = (
                    t_obj.get("english")
                    or t_obj.get("romaji")
                    or t_obj.get("native")
                    or f"Anime {anilist_id}"
                )
                episodes = media.get("episodes") or 1
                fmt = media.get("format") or "TV"
                is_movie = fmt == "MOVIE" or episodes == 1

                cover = media.get("coverImage", {})
                poster = cover.get("extraLarge") or cover.get("large") or cover.get("medium") or ""
                year_val = media.get("seasonYear") or media.get("startDate", {}).get("year") or ""
                score = media.get("averageScore")
                rating = f"{score / 10:.1f}" if score else ""

                return MediaDetails(
                    title=title,
                    year=str(year_val),
                    poster=poster,
                    backdrop=media.get("bannerImage") or "",
                    overview=_clean_html_text(media.get("description", "")),
                    rating=rating,
                    genres=media.get("genres") or [],
                    total_episodes=episodes,
                    format=fmt,
                    is_movie=is_movie,
                    status=media.get("status") or "",
                )
    except Exception as exc:
        log.warning("AniList fetch failed for %s: %s", anilist_id, exc)
    return None


# ── TMDB Metadata (Movies / TV) ─────────────────────────────────────────────

async def fetch_media_details(
    session: aiohttp.ClientSession,
    tmdb_id: str,
    media_type: str,
) -> Optional[MediaDetails]:
    """Fetch movie/TV details from FrameX TMDB proxy."""
    api_type = "tv" if media_type == "tv" else "movie"
    params = {"id": tmdb_id, "type": api_type}
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with session.get(FRAMEX_DETAILS_ENDPOINT, params=params, timeout=timeout) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("success"):
                    is_tv = media_type == "tv"
                    seasons_list: list[SeasonInfo] = []
                    total_eps = 1
                    if is_tv and "seasons" in data and isinstance(data["seasons"], list):
                        for s in data["seasons"]:
                            s_num = s.get("season_number")
                            ep_count = s.get("episode_count", 0)
                            if s_num is not None and ep_count > 0:
                                seasons_list.append(
                                    SeasonInfo(
                                        season_number=s_num,
                                        name=s.get("name") or f"Season {s_num}",
                                        episode_count=ep_count,
                                    )
                                )
                        # Sort: regular seasons (s_num > 0) in ascending order, specials (s_num == 0) last
                        seasons_list.sort(key=lambda x: (x.season_number == 0, x.season_number))
                        total_eps = sum(
                            s.episode_count
                            for s in seasons_list
                            if s.season_number > 0
                        ) or 1
                    return MediaDetails(
                        title=data.get("title", ""),
                        year=str(data.get("year", "")),
                        poster=data.get("poster", ""),
                        backdrop=data.get("backdrop", ""),
                        overview=data.get("overview", ""),
                        rating=str(data.get("rating", "")),
                        genres=data.get("genres", []) if isinstance(data.get("genres"), list) else [],
                        total_episodes=total_eps,
                        format="TV" if is_tv else "MOVIE",
                        is_movie=not is_tv,
                        seasons=seasons_list,
                    )
    except Exception as exc:
        log.warning("TMDB details fetch failed for %s (%s): %s", tmdb_id, media_type, exc)
    return None


# ── Multi-Provider Anime Stream Checker ─────────────────────────────────────

ANIME_PROVIDERS = [
    ("grand_warden", "sub"),
    ("wizard", "sub"),
    ("healer", "sub"),
    ("archer", "sub"),
    ("grand_warden_dub", "dub"),
    ("wizard_dub", "dub"),
]


async def _query_single_anime_provider(
    session: aiohttp.ClientSession,
    anilist_id: str,
    episode: int,
    provider_id: str,
    sub_type: str,
    sem: asyncio.Semaphore,
) -> Optional[dict]:
    """Query a single anime stream provider with semaphore and timeout."""
    async with sem:
        url = (
            f"{FRAMEX_ANIME_STREAM_ENDPOINT}"
            f"?id={anilist_id}&type=anime&sub_type={sub_type}&season=1&episode={episode}"
        )
        if provider_id:
            url += f"&provider={provider_id}"

        try:
            timeout = aiohttp.ClientTimeout(total=6)
            async with session.get(url, timeout=timeout) as resp:
                if resp.status == 200:
                    d = await resp.json()
                    if d.get("success") and d.get("sources"):
                        return d
        except Exception:
            pass
    return None


async def fetch_anime_streams(
    session: aiohttp.ClientSession,
    anilist_id: str,
    episode: int,
) -> tuple[list[StreamSource], list[Subtitle]]:
    """Query all active anime providers in parallel and aggregate sources."""
    sem = asyncio.Semaphore(3)

    # Always test auto-fallback first, plus designated providers
    targets = [("", "sub")] + ANIME_PROVIDERS
    tasks = [
        _query_single_anime_provider(session, anilist_id, episode, p, st, sem)
        for p, st in targets
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    sources: list[StreamSource] = []
    subtitles: list[Subtitle] = []
    seen_urls: set[str] = set()

    for r in results:
        if not isinstance(r, dict) or not r.get("sources"):
            continue
        server_name = r.get("server") or r.get("provider", "Anime Server")
        audio_type = r.get("audio", "sub")
        top_headers = r.get("headers", {})

        for s in r.get("sources", []):
            raw_url = s.get("url", "")
            if not raw_url:
                continue

            # Resolve relative URLs
            if raw_url.startswith("/"):
                full_url = f"{FRAMEX_API_BASE}{raw_url}"
            else:
                full_url = raw_url

            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            src_headers = dict(top_headers)
            if s.get("headers"):
                src_headers.update(s["headers"])

            src = StreamSource(
                url=full_url,
                quality=s.get("quality", "1080p"),
                stream_type=s.get("type", "hls"),
                server=s.get("server") or server_name,
                provider=r.get("provider", ""),
                audio=s.get("audio") or audio_type,
                headers=src_headers,
                skip_proxy=s.get("skipProxy", True),
            )
            sources.append(src)

            # Check subtitles attached to source
            for sub in s.get("subtitles", []):
                sub_url = sub.get("url", "")
                if sub_url and sub_url not in seen_urls:
                    seen_urls.add(sub_url)
                    if sub_url.startswith("/"):
                        sub_url = f"{FRAMEX_API_BASE}{sub_url}"
                    subtitles.append(
                        Subtitle(
                            url=sub_url,
                            label=sub.get("lang") or "Subtitle",
                            language=sub.get("lang") or "sub",
                            fmt="vtt",
                        )
                    )

        # Check top-level subtitles
        for sub in r.get("subtitles", []):
            sub_url = sub.get("url", "")
            if sub_url and sub_url not in seen_urls:
                seen_urls.add(sub_url)
                if sub_url.startswith("/"):
                    sub_url = f"{FRAMEX_API_BASE}{sub_url}"
                subtitles.append(
                    Subtitle(
                        url=sub_url,
                        label=sub.get("lang") or sub.get("label", "Subtitle"),
                        language=sub.get("lang") or "sub",
                        fmt="vtt",
                    )
                )

    return sources, subtitles


# ── Multi-Provider Movies & TV Stream Checker ───────────────────────────────

MOVIE_PROVIDERS = ["", "bowler", "super_barbarian", "goblin"]


async def _query_single_movie_provider(
    session: aiohttp.ClientSession,
    params: dict[str, str],
    provider: str,
    sem: asyncio.Semaphore,
) -> Optional[dict]:
    async with sem:
        p_copy = dict(params)
        if provider:
            p_copy["provider"] = provider
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with session.get(FRAMEX_STREAM_ENDPOINT, params=p_copy, timeout=timeout) as resp:
                if resp.status == 200:
                    d = await resp.json()
                    if d.get("success") and d.get("sources"):
                        return d
        except Exception:
            pass
    return None


async def fetch_movie_tv_streams(
    session: aiohttp.ClientSession,
    link: ParsedLink,
) -> tuple[list[StreamSource], list[Subtitle]]:
    """Query movie/TV providers in parallel and aggregate sources."""
    params: dict[str, str] = {"id": link.tmdb_id}
    if link.media_type == "tv":
        params["type"] = "tv"
        if link.season is not None:
            params["season"] = str(link.season)
        if link.episode is not None:
            params["episode"] = str(link.episode)
    else:
        params["type"] = "movie"

    sem = asyncio.Semaphore(2)
    tasks = [
        _query_single_movie_provider(session, params, p, sem)
        for p in MOVIE_PROVIDERS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    sources: list[StreamSource] = []
    subtitles: list[Subtitle] = []
    seen_urls: set[str] = set()

    for r in results:
        if not isinstance(r, dict) or not r.get("sources"):
            continue
        prov_name = r.get("provider", "default")
        for s in r.get("sources", []):
            url = s.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            if url.startswith("/"):
                url = f"{FRAMEX_API_BASE}{url}"

            sources.append(
                StreamSource(
                    url=url,
                    quality=s.get("quality", "unknown"),
                    stream_type=s.get("type", "hls"),
                    server=s.get("server", prov_name),
                    provider=prov_name,
                    skip_proxy=s.get("skipProxy", False),
                )
            )

        for sub in r.get("subtitles", []):
            sub_url = sub.get("url", "")
            if not sub_url or sub_url in seen_urls:
                continue
            seen_urls.add(sub_url)
            if sub_url.startswith("/"):
                sub_url = f"{FRAMEX_API_BASE}{sub_url}"
            subtitles.append(
                Subtitle(
                    url=sub_url,
                    label=sub.get("label", sub.get("language", "unknown")),
                    language=sub.get("language", sub.get("lang", "unknown")),
                    fmt=sub.get("format", "vtt"),
                    is_default=sub.get("isDefault", False),
                )
            )

    return sources, subtitles


# ── Main Entry Point ────────────────────────────────────────────────────────

async def fetch_media_info(link: ParsedLink) -> MediaInfo:
    """
    Fetch stream sources, subtitles, and metadata.
    Handles anime via AniList + multi-provider parallel checker.
    Handles movies/TV via TMDB + multi-provider checker.
    """
    timeout = aiohttp.ClientTimeout(total=SEGMENT_TIMEOUT)
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, timeout=timeout) as session:

        # ── ANIME FLOW ──────────────────────────────────────────────────────
        if link.media_type == "anime":
            details = await fetch_anilist_details(session, link.tmdb_id)
            total_eps = details.total_episodes if details else 1
            is_movie = details.is_movie if details else False

            # If user has NOT specified episode and it's a TV anime with >1 episode:
            # We return needs_episode_selection = True so the UI shows the episode picker!
            if link.episode is None and not is_movie and total_eps > 1:
                return MediaInfo(
                    success=True,
                    provider="anime",
                    details=details,
                    needs_episode_selection=True,
                    total_episodes=total_eps,
                )

            # Otherwise, resolve target episode (default 1)
            target_ep = link.episode or 1
            sources, subtitles = await fetch_anime_streams(session, link.tmdb_id, target_ep)

            if not sources:
                return MediaInfo(
                    success=False,
                    provider="anime",
                    details=details,
                    total_episodes=total_eps,
                    selected_episode=target_ep,
                    error=f"Tidak ditemukan stream aktif untuk Episode {target_ep}.",
                )

            return MediaInfo(
                success=True,
                provider="anime",
                sources=sources,
                subtitles=subtitles,
                details=details,
                needs_episode_selection=False,
                total_episodes=total_eps,
                selected_episode=target_ep,
            )

        # ── TV FLOW ─────────────────────────────────────────────────────────
        if link.media_type == "tv":
            details = await fetch_media_details(session, link.tmdb_id, "tv")

            # Determine target season:
            target_season = link.season
            if target_season is None:
                if details and details.seasons:
                    regular_seasons = [s for s in details.seasons if s.season_number > 0]
                    target_season = regular_seasons[0].season_number if regular_seasons else details.seasons[0].season_number
                else:
                    target_season = 1

            # Determine episode count for the selected season
            season_ep_count = 1
            if details and details.seasons:
                matched_season = next((s for s in details.seasons if s.season_number == target_season), None)
                if matched_season:
                    season_ep_count = matched_season.episode_count
                elif details.total_episodes:
                    season_ep_count = details.total_episodes
            elif details and details.total_episodes:
                season_ep_count = details.total_episodes

            # If user hasn't specified an episode and season has multiple episodes:
            if link.episode is None and season_ep_count > 1:
                return MediaInfo(
                    success=True,
                    provider="movie_tv",
                    details=details,
                    needs_episode_selection=True,
                    total_episodes=season_ep_count,
                    selected_season=target_season,
                    selected_episode=None,
                )

            # Target episode specified (or single-episode season)
            target_ep = link.episode or 1
            link.season = target_season
            link.episode = target_ep

            sources, subtitles = await fetch_movie_tv_streams(session, link)
            if not sources:
                return MediaInfo(
                    success=False,
                    provider="movie_tv",
                    details=details,
                    total_episodes=season_ep_count,
                    selected_season=target_season,
                    selected_episode=target_ep,
                    error=f"Tidak ditemukan stream aktif untuk Season {target_season} Episode {target_ep}.",
                )

            return MediaInfo(
                success=True,
                provider="movie_tv",
                sources=sources,
                subtitles=subtitles,
                details=details,
                needs_episode_selection=False,
                total_episodes=season_ep_count,
                selected_season=target_season,
                selected_episode=target_ep,
            )

        # ── MOVIE FLOW ──────────────────────────────────────────────────────
        details_req = fetch_media_details(session, link.tmdb_id, "movie")
        streams_req = fetch_movie_tv_streams(session, link)

        details, (sources, subtitles) = await asyncio.gather(details_req, streams_req)

        if not sources:
            return MediaInfo(
                success=False,
                provider="movie_tv",
                details=details,
                error="Tidak ditemukan sumber stream aktif pada server penyedia.",
            )

        return MediaInfo(
            success=True,
            provider="movie_tv",
            sources=sources,
            subtitles=subtitles,
            details=details,
        )
