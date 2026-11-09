#!/usr/bin/env python3
"""
Script Cloud Runner untuk GitHub Actions (1 Gbps Cloud-to-Cloud).
Mendukung Batch Multi-Episode untuk Series/Anime beserta Subtitle terembed.
Dilengkapi Socket Timeout, Retry Limit, dan Automatic Provider Fallback.
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import subprocess
import re
import time
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TITLE = os.environ.get("INPUT_TITLE", "Pokemon").strip()
MEDIA_TYPE = os.environ.get("INPUT_TYPE", "tv").strip()
SEASON = int(os.environ.get("INPUT_SEASON", 1))
EPISODES_STR = os.environ.get("INPUT_EPISODES", "1").strip()
FOLDER_NAME = os.environ.get("INPUT_FOLDER", "frameXTV_Downloads").strip()
TOKEN_JSON_STR = os.environ.get("GDRIVE_TOKEN_JSON", "")

if not TOKEN_JSON_STR:
    print("❌ ERROR: Secret GDRIVE_TOKEN_JSON belum disetel di GitHub Secrets!")
    sys.exit(1)

try:
    token_data = json.loads(TOKEN_JSON_STR)
except Exception as e:
    print(f"❌ ERROR: Format GDRIVE_TOKEN_JSON tidak valid: {e}")
    sys.exit(1)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Referer': 'https://framextv.cc/',
    'Origin': 'https://framextv.cc'
}

def clean_filename(s):
    return re.sub(r'[\\/*?:"<>|]', "", s).strip()

def parse_episodes(ep_str):
    episodes = set()
    for part in str(ep_str).split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            try:
                start, end = part.split('-')
                episodes.update(range(int(start), int(end) + 1))
            except Exception:
                pass
        elif part.isdigit():
            episodes.add(int(part))
    return sorted(list(episodes)) if episodes else [1]

episodes_list = parse_episodes(EPISODES_STR)

print("=" * 65)
print("🚀 GITHUB ACTIONS CLOUD RUNNER (1 Gbps Datacenter — Resilient Batch)")
print(f"🎬 Judul        : {TITLE}")
print(f"📺 Tipe         : {MEDIA_TYPE.upper()}")
if MEDIA_TYPE != "movie":
    print(f"📅 Season       : {SEASON}")
    print(f"🔢 Episode List : {episodes_list} (Total: {len(episodes_list)} episode)")
print(f"📁 Folder Drive : {FOLDER_NAME}")
print("=" * 65)

# 1. Cari Konten di frameXTV
search_path = "/anime/api/search" if MEDIA_TYPE == "anime" else "/api/search"
search_url = f"https://api.framextv.cc{search_path}?q={urllib.parse.quote(TITLE)}"
if MEDIA_TYPE != "anime":
    search_url += f"&type={MEDIA_TYPE}&page=1"

print(f"\n🔎 Mencari konten: {search_url}...")
req = urllib.request.Request(search_url, headers=HEADERS)
with urllib.request.urlopen(req) as resp:
    search_res = json.loads(resp.read().decode('utf-8'))

results = search_res.get('results') or search_res.get('items') or []
if not results:
    print(f"❌ Tidak ditemukan hasil untuk '{TITLE}'")
    sys.exit(1)

target = results[0]
media_id = target['id']
resolved_title = target.get('title') or target.get('name') or TITLE
year = target.get('year', '')
print(f"🎯 Konten Ditemukan: {resolved_title} ({year}) [ID: {media_id}]")

# Ambil daftar provider cadangan jika perlu fallback
FALLBACK_PROVIDERS = ["bowler", "super_barbarian", "giant", "sparky", "royal_champion", "titan"]

# 2. Inisialisasi Google Drive API
print("\n☁️ Menghubungkan ke Google Drive API...")
creds = Credentials(
    token=token_data.get('token'),
    refresh_token=token_data.get('refresh_token'),
    token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
    client_id=token_data.get('client_id'),
    client_secret=token_data.get('client_secret')
)

service = build('drive', 'v3', credentials=creds, cache_discovery=False)

clean_folder = FOLDER_NAME.strip("/").split("/")[-1]
res = service.files().list(
    q=f"mimeType = 'application/vnd.google-apps.folder' and name = '{clean_folder}' and trashed = false",
    fields="files(id, name)"
).execute()
folders = res.get('files', [])

if folders:
    folder_id = folders[0]['id']
else:
    f_meta = {'name': clean_folder, 'mimeType': 'application/vnd.google-apps.folder'}
    folder_id = service.files().create(body=f_meta, fields='id').execute().get('id')

print(f"📁 Target Folder ID: {folder_id} ({clean_folder})\n")

def fetch_stream_with_fallback(ep_num=None):
    """Mencari stream aktif dengan auto-fallback provider jika provider utama gagal."""
    providers_to_try = [None] + FALLBACK_PROVIDERS

    for prov in providers_to_try:
        if MEDIA_TYPE == "movie":
            stream_url_api = f"https://api.framextv.cc/api/stream?type=movie&id={media_id}"
        elif MEDIA_TYPE == "tv":
            stream_url_api = f"https://api.framextv.cc/api/stream?type=tv&id={media_id}&season={SEASON}&episode={ep_num}"
        else: # anime
            stream_url_api = f"https://api.framextv.cc/anime/api/stream?id={media_id}&type=anime&season={SEASON}&episode={ep_num}&sub_type=sub"

        if prov:
            stream_url_api += f"&provider={prov}"

        try:
            req_stream = urllib.request.Request(stream_url_api, headers=HEADERS)
            with urllib.request.urlopen(req_stream, timeout=12) as resp_stream:
                stream_data = json.loads(resp_stream.read().decode('utf-8'))
                sources = stream_data.get('sources', [])
                if stream_data.get('success') and sources:
                    return sources[0]['url'], stream_data.get('provider', prov or 'default')
        except Exception:
            continue

    return None, None

def download_video_resilient(source_url, output_local):
    """Download HLS stream dengan socket timeout dan max retry agar tidak pernah hang."""
    cmd = [
        "yt-dlp",
        "--add-header", "Referer:https://framextv.cc/",
        "--add-header", "Origin:https://framextv.cc",
        "--concurrent-fragments", "16",
        "--socket-timeout", "15",
        "--retries", "5",
        "--fragment-retries", "5",
        "--skip-unavailable-fragments",
        "--no-check-certificates",
        "-o", output_local,
        source_url
    ]

    try:
        # Timeout maksimal 300 detik (5 menit) per video di Azure 1 Gbps
        p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        return p.returncode == 0 and os.path.exists(output_local) and os.path.getsize(output_local) > 1024*1024
    except subprocess.TimeoutExpired:
        print("⚠️ yt-dlp timeout setelah 5 menit. Menghentikan stream ini...")
        return False
    except Exception as e:
        print(f"⚠️ Error yt-dlp: {e}")
        return False

# Fungsi transfer tunggal
def process_single_item(ep_num=None):
    if MEDIA_TYPE == "movie":
        file_name = clean_filename(f"{resolved_title} ({year}).mp4" if year else f"{resolved_title}.mp4")
        item_label = f"{resolved_title}"
    elif MEDIA_TYPE == "tv":
        file_name = clean_filename(f"{resolved_title} - S{SEASON:02d}E{ep_num:02d}.mp4")
        item_label = f"{resolved_title} S{SEASON:02d}E{ep_num:02d}"
    else: # anime
        file_name = clean_filename(f"{resolved_title} - Episode {ep_num:02d}.mp4")
        item_label = f"{resolved_title} Ep {ep_num:02d}"

    print(f"📡 [{item_label}] Mencari stream video aktif...")
    source_url, provider = fetch_stream_with_fallback(ep_num)

    if not source_url:
        print(f"❌ Tidak ada stream yang dapat diakses untuk {item_label}.")
        return None

    print(f"   Server aktif: [{provider}]")

    output_local = os.path.join("/tmp", file_name)
    print(f"📥 Menyedot video 1 Gbps...")

    success = download_video_resilient(source_url, output_local)
    if not success:
        # Coba fallback ke provider lain jika pertama kali gagal
        print(f"🔄 Mencoba ulang dengan server alternatif...")
        for alt_prov in [p for p in FALLBACK_PROVIDERS if p != provider]:
            alt_url, alt_name = fetch_stream_with_fallback(ep_num)
            if alt_url and alt_url != source_url:
                print(f"   Mencoba server: [{alt_name}]...")
                if download_video_resilient(alt_url, output_local):
                    success = True
                    break

    if not success or not os.path.exists(output_local):
        print(f"❌ Gagal download video untuk {item_label}.")
        return None

    file_size_mb = os.path.getsize(output_local) / (1024 * 1024)
    print(f"   Video terdownload: {file_size_mb:.1f} MB")

    # Subtitle
    sub_local = None
    try:
        sub_api = f"https://api.framextv.cc/api/subtitles?id={media_id}&type={MEDIA_TYPE}"
        if MEDIA_TYPE == "tv":
            sub_api += f"&season={SEASON}&episode={ep_num}"
        req_sub = urllib.request.Request(sub_api, headers=HEADERS)
        with urllib.request.urlopen(req_sub, timeout=12) as r:
            subs = json.loads(r.read().decode('utf-8')).get('subtitles', [])
            target_sub = None
            for lang_code in ['id', 'ind', 'en', 'eng']:
                for s in subs:
                    s_lang = (s.get('lang') or '').lower()
                    s_label = (s.get('label') or '').lower()
                    if lang_code == s_lang or lang_code in s_label:
                        target_sub = s
                        break
                if target_sub:
                    break
            if not target_sub and subs:
                target_sub = subs[0]

            if target_sub and target_sub.get('url'):
                sub_url = target_sub['url']
                sub_local = os.path.splitext(output_local)[0] + ".vtt"
                sub_download_req = urllib.request.Request(sub_url, headers=HEADERS)
                with urllib.request.urlopen(sub_download_req, timeout=15) as s_resp:
                    sub_bytes = s_resp.read()
                    with open(sub_local, 'wb') as sf:
                        sf.write(sub_bytes)
                print(f"   Subtitle ({target_sub.get('lang')}) terdownload: {len(sub_bytes)} bytes")

                # Embed subtitle ke MP4 via ffmpeg
                embedded_output = os.path.splitext(output_local)[0] + "_subbed.mp4"
                ff_cmd = [
                    "ffmpeg", "-y",
                    "-i", output_local,
                    "-i", sub_local,
                    "-c:v", "copy",
                    "-c:a", "copy",
                    "-c:s", "mov_text",
                    "-metadata:s:s:0", f"language={target_sub.get('lang', 'eng')}",
                    embedded_output
                ]
                ff_res = subprocess.run(ff_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
                if ff_res.returncode == 0 and os.path.exists(embedded_output):
                    os.replace(embedded_output, output_local)
                    print(f"   Subtitle sukses ditanamkan ke dalam video MP4!")
    except Exception as e_sub:
        print(f"   Catatan subtitle: {e_sub}")

    # Upload ke Google Drive
    print(f"⬆️ Mengunggah {file_name} ke Google Drive...")
    file_meta = {'name': file_name, 'parents': [folder_id]}
    media = MediaFileUpload(output_local, mimetype='video/mp4', chunksize=10*1024*1024, resumable=True)
    req_up = service.files().create(body=file_meta, media_body=media, fields='id, name, webViewLink')

    res_up = None
    upload_attempts = 0
    while res_up is None and upload_attempts < 10:
        try:
            status, res_up = req_up.next_chunk()
        except Exception as e_chunk:
            upload_attempts += 1
            time.sleep(2)

    view_link = res_up.get('webViewLink', '') if res_up else ''
    print(f"✅ Selesai diunggah! Link: {view_link}")

    # Upload file .vtt terpisah jika ada
    if sub_local and os.path.exists(sub_local):
        try:
            sub_meta = {'name': os.path.basename(sub_local), 'parents': [folder_id]}
            s_media = MediaFileUpload(sub_local, mimetype='text/vtt')
            service.files().create(body=sub_meta, media_body=s_media).execute()
        except Exception:
            pass

    # Cleanup disk local
    try:
        os.remove(output_local)
    except Exception:
        pass
    if sub_local and os.path.exists(sub_local):
        try:
            os.remove(sub_local)
        except Exception:
            pass

    return view_link

# Eksekusi Loop Batch
successful_links = []
if MEDIA_TYPE == "movie":
    link = process_single_item()
    if link:
        successful_links.append((resolved_title, link))
else:
    for idx, ep in enumerate(episodes_list, 1):
        print(f"\n--- [{idx}/{len(episodes_list)}] Memproses Episode {ep} ---")
        link = process_single_item(ep_num=ep)
        if link:
            successful_links.append((f"Episode {ep}", link))
        else:
            print(f"⚠️ Melewati Episode {ep} karena gagal, lanjut ke episode berikutnya...")

print("\n" + "=" * 65)
print(f"🎉 BATCH TRANSFER SELESAI! ({len(successful_links)}/{len(episodes_list) if MEDIA_TYPE != 'movie' else 1} Berhasil)")
for item_name, link in successful_links:
    print(f" • {item_name}: {link}")
print("=" * 65)
