"""
ingest_historical.py
抓取 Wikipedia 历史背景段落 → 存入 woolf_historical
覆盖：1920s 英国 / 布卢姆斯伯里派 / 剑桥女权历史 / 女性参政
"""

import json
import httpx
from pathlib import Path
from bs4 import BeautifulSoup
from kb_client import get_or_create_collection, chunk_text
from theme_tagger import tag_chunks_batch

WIKI_PAGES = [
    ("Bloomsbury_Group",             "Bloomsbury Group"),
    ("Women%27s_suffrage_in_the_United_Kingdom", "Women's suffrage in the UK"),
    ("Interwar_period",              "Interwar period in Britain"),
    ("Cambridge_University",         "Cambridge and women's education"),
    ("Virginia_Woolf",               "Virginia Woolf biography"),
]

WIKI_API = "https://en.wikipedia.org/w/api.php"

# Pre-fetched local files (fallback if Wikipedia API unavailable)
LOCAL_WIKI_FILES = {
    "Bloomsbury Group": Path(__file__).parent.parent / "data/raw/bloomsbury_group.txt",
    "Women's suffrage in the UK": Path(__file__).parent.parent / "data/raw/womens_suffrage_uk.txt",
    "Virginia Woolf biography": Path(__file__).parent.parent / "data/raw/virginia_woolf_biography.txt",
}


def fetch_wiki_sections(page_title: str, label: str) -> str:
    # Try local file first
    if label in LOCAL_WIKI_FILES and LOCAL_WIKI_FILES[label].exists():
        return LOCAL_WIKI_FILES[label].read_text(encoding="utf-8")

    params = {
        "action": "query",
        "titles": page_title,
        "prop": "extracts",
        "explaintext": True,
        "exsectionformat": "plain",
        "format": "json",
    }
    headers = {"User-Agent": "WoolfReaderAgent/1.0 (educational use)"}
    resp = httpx.get(WIKI_API, params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        return page.get("extract", "")
    return ""


def ingest_historical(reset: bool = False):
    collection = get_or_create_collection("woolf_historical", reset=reset)

    docs, ids, metas = [], [], []
    chunk_idx = 0

    for page_id, label in WIKI_PAGES:
        print(f"  Loading: {label}...")
        try:
            text = fetch_wiki_sections(page_id, label)
            if not text:
                print(f"    (empty, skipping)")
                continue
            chunks = chunk_text(text, chunk_size=400, overlap=60)
            for chunk in chunks:
                docs.append(chunk)
                ids.append(f"hist_{chunk_idx}")
                metas.append({"topic": label, "source": "wikipedia"})
                chunk_idx += 1
            print(f"    → {len(chunks)} chunks")
        except Exception as e:
            print(f"    Warning: {e}")

    if docs:
        print(f"  Tagging themes for {len(docs)} chunks...")
        themes_list = tag_chunks_batch(docs)
        for i, themes in enumerate(themes_list):
            metas[i]["themes"] = json.dumps(themes)
            metas[i]["themes_str"] = ",".join(themes)
        collection.add(documents=docs, ids=ids, metadatas=metas)

    print(f"  ✓ woolf_historical: {len(docs)} chunks total")


if __name__ == "__main__":
    ingest_historical(reset=True)
