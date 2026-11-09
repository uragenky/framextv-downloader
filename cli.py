#!/usr/bin/env python3
"""
CLI Runner StreamDown: frameXTV to Local/Google Drive Stream Downloader.
"""

import argparse
import sys
import os

# Tambahkan path src ke pythonpath
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from src.api.client import FrameXClient
from src.downloader.hls import HLSDownloader, sanitize_filename


def handle_search(args, client: FrameXClient):
    print(f"\n🔎 Mencari '{args.query}' (Tipe: {args.type})...")
    results = client.search(args.query, media_type=args.type)
    if not results:
        print("❌ Tidak ditemukan hasil.")
        return

    print(f"✅ Ditemukan {len(results)} judul:")
    print("-" * 65)
    for i, item in enumerate(results[:10], 1):
        item_id = item.get("id")
        title = item.get("title") or item.get("name") or "Tanpa Judul"
        year = item.get("year") or item.get("releaseDate", "")[:4] or "-"
        print(f"{i:2d}. [{item_id}] {title} ({year})")
    print("-" * 65)


def handle_providers(args, client: FrameXClient):
    print("\n📡 Mengambil status extraction provider...")
    providers = client.get_providers(media_type=args.type)
    print(f"Total Provider: {len(providers)}")
    print(f"{'ID Provider':<20} | {'Nama Server':<25} | {'Status':<12}")
    print("-" * 65)
    for p in providers:
        print(f"{p.get('id'):<20} | {p.get('name'):<25} | {p.get('status'):<12}")


def handle_stream(args, client: FrameXClient):
    print(f"\n📡 Mengambil stream untuk ID {args.id} (Tipe: {args.type})...")
    data = client.get_stream(
        media_type=args.type,
        media_id=args.id,
        season=args.season,
        episode=args.episode,
        provider=args.provider
    )
    print(f"Provider: {data.get('provider')}")
    sources = data.get("sources", [])
    print(f"Ditemukan {len(sources)} source:")
    for s in sources:
        print(f" - [{s.get('quality', 'Auto')} - {s.get('type')}] {s.get('server')}:")
        print(f"   {s.get('url')}")


def handle_download(args, client: FrameXClient):
    # Jika input query berupa teks, cari dulu ID nya
    query = args.query
    media_id = None
    title = query
    year = ""

    if query.isdigit():
        media_id = int(query)
    else:
        print(f"\n🔎 Mencari judul '{query}'...")
        results = client.search(query, media_type=args.type)
        if not results:
            print("❌ Konten tidak ditemukan.")
            return
        target = results[0]
        media_id = target["id"]
        title = target.get("title") or target.get("name")
        year = target.get("year") or ""
        print(f"🎯 Memilih: {title} ({year}) [ID: {media_id}]")

    print(f"📡 Mengambil link stream video...")
    try:
        stream_data = client.get_stream(
            media_type=args.type,
            media_id=media_id,
            season=args.season,
            episode=args.episode,
            provider=args.provider
        )
    except Exception as e:
        print(f"❌ Gagal mendapatkan stream: {e}")
        return

    sources = stream_data.get("sources", [])
    if not sources:
        print("❌ Tidak ada URL stream yang tersedia.")
        return

    stream_url = sources[0]["url"]
    provider = stream_data.get("provider", "default")
    print(f"🚀 Stream aktif didapatkan dari server: [{provider}]")

    if args.type == "movie":
        filename = f"{title} ({year})" if year else title
    else:
        filename = f"{title} - S{args.season:02d}E{args.episode:02d}"

    downloader = HLSDownloader(download_dir=args.dest, concurrent_fragments=args.threads)
    print(f"📥 Mengunduh ke direktori: {args.dest}")
    out_file = downloader.download_stream(stream_url, filename)
    print(f"\n🎉 Selesai! File tersimpan di: {out_file}")

    # Subtitles
    if not args.no_subs:
        print("💬 Mengambil subtitle...")
        try:
            subs = client.get_subtitles(media_id, media_type=args.type, season=args.season, episode=args.episode)
            downloader.download_subtitle(subs, out_file)
        except Exception as e:
            print(f"⚠️ Subtitle tidak dapat diunduh: {e}")


def main():
    parser = argparse.ArgumentParser(description="StreamDown — CLI Bridge frameXTV to Local/Google Drive")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: search
    p_search = subparsers.add_parser("search", help="Cari film, serial, atau anime")
    p_search.add_argument("query", help="Kata kunci pencarian")
    p_search.add_argument("--type", choices=["movie", "tv", "anime"], default="movie", help="Tipe konten")

    # Subcommand: providers
    p_prov = subparsers.add_parser("providers", help="Cek status server/provider")
    p_prov.add_argument("--type", choices=["movie", "anime"], default="movie", help="Tipe kategori")

    # Subcommand: stream
    p_stream = subparsers.add_parser("stream", help="Dapatkan direct URL m3u8 stream")
    p_stream.add_argument("id", help="TMDB ID atau AniList ID")
    p_stream.add_argument("--type", choices=["movie", "tv", "anime"], default="movie")
    p_stream.add_argument("--season", type=int, default=1)
    p_stream.add_argument("--episode", type=int, default=1)
    p_stream.add_argument("--provider", help="Pilih provider tertentu")

    # Subcommand: download
    p_down = subparsers.add_parser("download", help="Download film / episode ke format mp4")
    p_down.add_argument("query", help="Judul atau TMDB ID")
    p_down.add_argument("--type", choices=["movie", "tv", "anime"], default="movie")
    p_down.add_argument("--season", type=int, default=1)
    p_down.add_argument("--episode", type=int, default=1)
    p_down.add_argument("--provider", help="Pilih provider tertentu")
    p_down.add_argument("--dest", default="./downloads", help="Direktori penyimpanan")
    p_down.add_argument("--threads", type=int, default=16, help="Jumlah thread paralel")
    p_down.add_argument("--no-subs", action="store_true", help="Jangan unduh subtitle")

    args = parser.parse_args()
    client = FrameXClient()

    if args.command == "search":
        handle_search(args, client)
    elif args.command == "providers":
        handle_providers(args, client)
    elif args.command == "stream":
        handle_stream(args, client)
    elif args.command == "download":
        handle_download(args, client)


if __name__ == "__main__":
    main()
