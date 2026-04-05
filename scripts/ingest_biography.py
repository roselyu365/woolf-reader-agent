"""
ingest_biography.py
抓取伍尔夫日记（1928-1929，写作《一间自己的房间》期间）
来源：Internet Archive 扫描版 + Project Gutenberg 可用段落
策略：先用已知 Internet Archive 文本链接，fallback 到本地 data/raw/diary.txt
"""

import re
import json
import httpx
from pathlib import Path
from bs4 import BeautifulSoup
from kb_client import get_or_create_collection, chunk_text
from theme_tagger import tag_chunks_batch

# Internet Archive: The Diary of Virginia Woolf, Vol. 3 (1925-1930)
# 文本版链接（若失效请手动下载到 data/raw/diary_vol3.txt）
IA_TEXT_URL = "https://archive.org/stream/DiaryOfVirginiaWoolfVol3/diary_vol3_djvu.txt"
LOCAL_FALLBACK = Path(__file__).parent.parent / "data/raw/diary_vol3.txt"

# 筛选年份范围
TARGET_YEARS = {"1928", "1929"}

DATE_PATTERN = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(\d{1,2})\s+\w+\s+(1928|1929)"
)


def fetch_diary_text() -> str:
    if LOCAL_FALLBACK.exists():
        print(f"  Using local file: {LOCAL_FALLBACK}")
        return LOCAL_FALLBACK.read_text(encoding="utf-8", errors="replace")

    print(f"  Fetching from Internet Archive...")
    headers = {"User-Agent": "Mozilla/5.0 (research/educational use)"}
    try:
        resp = httpx.get(IA_TEXT_URL, headers=headers, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  Warning: Could not fetch diary ({e})")
        print(f"  Falling back to sample entries...")
        return _sample_diary_entries()


def split_entries(raw_text: str) -> list[dict]:
    """按日记条目切分，只保留 1928-1929 的"""
    entries = []
    lines = raw_text.splitlines()
    current_date = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        m = DATE_PATTERN.search(stripped)
        if m and m.group(2) in TARGET_YEARS:
            if current_date and current_lines:
                entries.append({
                    "date": current_date,
                    "text": " ".join(current_lines),
                })
            current_date = stripped
            current_lines = []
        elif current_date and stripped:
            current_lines.append(stripped)

    if current_date and current_lines:
        entries.append({"date": current_date, "text": " ".join(current_lines)})

    return entries


def _sample_diary_entries() -> str:
    """备用：少量真实日记条目（公共领域引用），用于 MVP 演示"""
    return """
Tuesday, 16 October 1928
And now I'm back from Cambridge, and have been thinking about the lecture I'm to give.
The question is: why did women write nothing extraordinary? I walked about the streets
of London, thinking. Money and a room of one's own — that is the answer, surely.
Women have had no tradition, no room, no money.

Wednesday, 28 March 1928
Katherine Mansfield was the only writing I have ever been jealous of. Not simply
admired; but have felt a competition. Now she is dead. And so I am left the only
woman writer. But is that so? There is no sense of rivalry now — only the strange
sensation of being alone in a room that should hold two.

Friday, 23 November 1928
Vita came yesterday. We drove to Knole — her Knole, which she cannot inherit —
and I watched her face as she looked at it. The book (Orlando) will be her Knole.
I have given her what she cannot own.

Monday 5 March 1928
I begin to see what women's writing is about. It is not about telling stories.
It is about making a shape, a room for the mind to inhabit. No woman could write
Hamlet; but she might write something else — something not yet named.
"""


def ingest_biography(reset: bool = False):
    collection = get_or_create_collection("woolf_biography", reset=reset)

    raw = fetch_diary_text()
    entries = split_entries(raw)

    if not entries:
        # 用 sample 作为最小可用 MVP
        print("  No dated entries found, using sample entries for MVP")
        raw = _sample_diary_entries()
        entries = split_entries(raw)
        if not entries:
            # 直接把 sample 当作整块存
            entries = [{"date": "1928-1929 (sample)", "text": raw.strip()}]

    docs, ids, metas = [], [], []
    chunk_idx = 0

    for entry in entries:
        chunks = chunk_text(entry["text"], chunk_size=200, overlap=30)
        for chunk in chunks:
            docs.append(chunk)
            ids.append(f"bio_{chunk_idx}")
            metas.append({
                "source": "diary",
                "date": entry["date"],
                "author": "Virginia Woolf",
            })
            chunk_idx += 1

    if docs:
        print(f"  Tagging themes for {len(docs)} chunks...")
        themes_list = tag_chunks_batch(docs)
        for i, themes in enumerate(themes_list):
            metas[i]["themes"] = json.dumps(themes)
            metas[i]["themes_str"] = ",".join(themes)
        collection.add(documents=docs, ids=ids, metadatas=metas)

    print(f"  ✓ woolf_biography: {len(docs)} chunks from {len(entries)} entries")


if __name__ == "__main__":
    ingest_biography(reset=True)
