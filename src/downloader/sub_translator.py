"""
StreamDown — Subtitle Auto-Translator Module.
Mendukung penerjemahan otomatis file WebVTT / SRT (misalnya English -> Bahasa Indonesia)
menggunakan multiple engine fallback (Bing, Google, Alibaba, Caiyun, MyMemory).
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("streamdown.sub_translator")

# Mapping kode bahasa untuk berbagai engine
LANG_MAP = {
    "id": {"generic": "id", "mymemory": "indonesian", "label": "Indonesian"},
    "ind": {"generic": "id", "mymemory": "indonesian", "label": "Indonesian"},
    "indonesian": {"generic": "id", "mymemory": "indonesian", "label": "Indonesian"},
    "en": {"generic": "en", "mymemory": "english", "label": "English"},
    "eng": {"generic": "en", "mymemory": "english", "label": "English"},
    "english": {"generic": "en", "mymemory": "english", "label": "English"},
}


def normalize_lang_code(code: str) -> str:
    c = (code or "id").strip().lower()
    if c in ["id", "ind", "indonesian"]:
        return "id"
    if c in ["en", "eng", "english"]:
        return "en"
    return c


def parse_vtt_cues(content: str) -> Tuple[str, List[Dict]]:
    """
    Mem-parse isi file WebVTT/SRT menjadi header string dan list dictionary cue.
    Setiap cue berisi: id, timestamp, text.
    """
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    
    header_lines = []
    cues = []
    i = 0
    
    # Ambil header WebVTT
    if lines and "WEBVTT" in lines[0].upper():
        while i < len(lines):
            header_lines.append(lines[i])
            if not lines[i].strip():
                i += 1
                break
            i += 1
            
    header = "\n".join(header_lines).strip()
    if not header:
        header = "WEBVTT\n"
    else:
        header = header + "\n\n"

    # Parse setiap blok cue
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        cue_id = ""
        timestamp = ""
        dialog_lines = []

        if "-->" in line:
            timestamp = line
            cue_id = str(len(cues) + 1)
            i += 1
        elif i + 1 < len(lines) and "-->" in lines[i + 1]:
            cue_id = line
            timestamp = lines[i + 1].strip()
            i += 2
        else:
            i += 1
            continue

        while i < len(lines) and lines[i].strip():
            dialog_lines.append(lines[i].strip())
            i += 1

        if timestamp:
            cues.append({
                "id": cue_id,
                "timestamp": timestamp,
                "text": "\n".join(dialog_lines)
            })

    return header, cues


def build_vtt_content(header: str, cues: List[Dict]) -> str:
    """
    Menyusun kembali teks WebVTT dari header dan list cues yang telah diterjemahkan.
    """
    out = [header.strip()]
    out.append("")
    for idx, cue in enumerate(cues, 1):
        c_id = cue.get("id") or str(idx)
        out.append(c_id)
        out.append(cue["timestamp"])
        out.append(cue["text"])
        out.append("")
    return "\n".join(out)


def translate_cues(
    cues: List[Dict],
    src_lang: str = "en",
    target_lang: str = "id",
    batch_size: int = 25,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> List[Dict]:
    """
    Menerjemahkan teks pada cues secara batch untuk efisiensi dan kecepatan.
    Menggunakan fallback multi-engine agar selalu berhasil.
    """
    import translators as ts

    src_norm = normalize_lang_code(src_lang)
    tgt_norm = normalize_lang_code(target_lang)

    engines = ["bing", "google", "alibaba", "caiyun"]
    translated_cues = [dict(c) for c in cues]
    delimiter = "\n<<<===>>>\n"
    total = len(cues)

    for start_idx in range(0, total, batch_size):
        end_idx = min(start_idx + batch_size, total)
        batch = cues[start_idx:end_idx]
        texts = [c["text"] for c in batch]

        # Cek apakah batch hanya whitespace / tag kosong
        if not any(t.strip() for t in texts):
            continue

        combined_text = delimiter.join(texts)
        translated_texts = None

        # 1. Coba multi-engine translators secara batch
        for engine in engines:
            try:
                res = ts.translate_text(
                    combined_text,
                    translator=engine,
                    from_language=src_norm,
                    to_language=tgt_norm,
                    timeout=14
                )
                parts = [p.strip() for p in res.split("<<<===>>>")]
                if len(parts) == len(texts):
                    translated_texts = parts
                    break
            except Exception as e_eng:
                logger.debug(f"Engine {engine} gagal untuk batch {start_idx}-{end_idx}: {e_eng}")
                continue

        # 2. Fallback per baris jika batch split gagal
        if not translated_texts or len(translated_texts) != len(texts):
            translated_texts = []
            for t in texts:
                if not t.strip():
                    translated_texts.append(t)
                    continue

                trans_single = None
                for engine in engines:
                    try:
                        trans_single = ts.translate_text(
                            t,
                            translator=engine,
                            from_language=src_norm,
                            to_language=tgt_norm,
                            timeout=8
                        )
                        if trans_single:
                            break
                    except Exception:
                        continue

                if not trans_single:
                    # Fallback ke MyMemory
                    try:
                        from deep_translator import MyMemoryTranslator
                        src_mem = LANG_MAP.get(src_norm, {}).get("mymemory", src_norm)
                        tgt_mem = LANG_MAP.get(tgt_norm, {}).get("mymemory", tgt_norm)
                        trans_single = MyMemoryTranslator(source=src_mem, target=tgt_mem).translate(t[:480])
                    except Exception:
                        trans_single = t

                translated_texts.append(trans_single or t)

        for idx, trans_text in enumerate(translated_texts):
            translated_cues[start_idx + idx]["text"] = trans_text

        if progress_callback:
            try:
                progress_callback(end_idx, total)
            except Exception:
                pass

    return translated_cues


def translate_subtitle_file(
    src_path: Path,
    dest_path: Path,
    src_lang: str = "en",
    target_lang: str = "id",
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> bool:
    """
    Menerjemahkan file subtitle (.vtt atau .srt) dari bahasa sumber ke bahasa tujuan.
    Menyimpan hasilnya ke dest_path dalam format WebVTT yang valid.
    """
    try:
        if not src_path.exists() or src_path.stat().st_size == 0:
            logger.warning(f"File subtitle sumber tidak ditemukan: {src_path}")
            return False

        content = src_path.read_text(encoding="utf-8", errors="replace")
        header, cues = parse_vtt_cues(content)

        if not cues:
            logger.warning(f"Tidak ada cue subtitle yang dapat dibaca dari {src_path}")
            return False

        logger.info(f"Menerjemahkan {len(cues)} cue subtitle dari {src_lang} ke {target_lang}...")
        translated_cues = translate_cues(
            cues=cues,
            src_lang=src_lang,
            target_lang=target_lang,
            batch_size=25,
            progress_callback=progress_callback
        )

        new_content = build_vtt_content(header, translated_cues)
        dest_path.write_text(new_content, encoding="utf-8")
        logger.info(f"Subtitle berhasil diterjemahkan dan disimpan: {dest_path.name}")
        return True

    except Exception as e:
        logger.error(f"Gagal memproses terjemahan subtitle {src_path}: {e}")
        return False
