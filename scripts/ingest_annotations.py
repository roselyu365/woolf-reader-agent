"""
ingest_annotations.py
抓取《一间自己的房间》学术注释
来源：SparkNotes + GradeSaver（MVP 够用）
"""

import json
import httpx
from bs4 import BeautifulSoup
from kb_client import get_or_create_collection, chunk_text
from theme_tagger import tag_chunks_batch

SOURCES = [
    {
        "url": "https://www.sparknotes.com/lit/aroom/summary/",
        "label": "SparkNotes - Summary",
        "source": "sparknotes",
    },
    {
        "url": "https://www.sparknotes.com/lit/aroom/themes/",
        "label": "SparkNotes - Themes",
        "source": "sparknotes",
    },
    {
        "url": "https://www.gradesaver.com/a-room-of-ones-own/study-guide/summary",
        "label": "GradeSaver - Summary",
        "source": "gradesaver",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}


def fetch_page_text(url: str) -> str:
    resp = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # 去掉脚本/样式/导航
    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    # 取主内容区
    main = (
        soup.find("div", class_="studyGuideText")
        or soup.find("article")
        or soup.find("main")
        or soup.find("body")
    )
    return main.get_text(separator="\n") if main else ""


def ingest_annotations(reset: bool = False):
    collection = get_or_create_collection("woolf_annotations", reset=reset)

    docs, ids, metas = [], [], []
    chunk_idx = 0

    for src in SOURCES:
        print(f"  Fetching {src['label']}...")
        try:
            text = fetch_page_text(src["url"])
            if not text.strip():
                print(f"    (empty, skipping)")
                continue
            chunks = chunk_text(text, chunk_size=400, overlap=60)
            for chunk in chunks:
                docs.append(chunk)
                ids.append(f"annot_{chunk_idx}")
                metas.append({"source": src["source"], "label": src["label"]})
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

    print(f"  ✓ woolf_annotations: {len(docs)} chunks total")


if __name__ == "__main__":
    ingest_annotations(reset=True)
