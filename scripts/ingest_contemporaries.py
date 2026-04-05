"""
ingest_contemporaries.py
第二视角知识库：
  - Vita Sackville-West：伍尔夫书信中写给/关于 Vita 的段落
  - Katherine Mansfield：伍尔夫日记中谈到 Mansfield 的段落

来源：The Letters of Virginia Woolf（Internet Archive）
策略：关键词过滤，抽取包含 "Vita"/"Mansfield" 的段落
"""

import re
import json
import httpx
from pathlib import Path
from bs4 import BeautifulSoup
from kb_client import get_or_create_collection, chunk_text
from theme_tagger import tag_chunks_batch

LOCAL_LETTERS = Path(__file__).parent.parent / "data/raw/letters.txt"
IA_LETTERS_URL = "https://archive.org/stream/lettersofvirgini01wool/lettersofvirgini01wool_djvu.txt"

VITA_KEYWORDS = ["Vita", "Sackville", "Orlando", "Knole", "Long Barn"]
MANSFIELD_KEYWORDS = ["Mansfield", "Katherine", "jealous", "rival", "competition"]


def fetch_letters() -> str:
    if LOCAL_LETTERS.exists():
        return LOCAL_LETTERS.read_text(encoding="utf-8", errors="replace")

    print("  Fetching letters from Internet Archive...")
    headers = {"User-Agent": "Mozilla/5.0 (research/educational use)"}
    try:
        resp = httpx.get(IA_LETTERS_URL, headers=headers, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  Warning: {e} — using sample entries")
        return _sample_entries()


def extract_by_keywords(text: str, keywords: list[str], window: int = 500) -> list[str]:
    """提取包含关键词的段落（前后 window 字符）"""
    results = []
    for kw in keywords:
        for m in re.finditer(re.escape(kw), text, re.IGNORECASE):
            start = max(0, m.start() - window)
            end = min(len(text), m.end() + window)
            snippet = text[start:end].strip()
            if len(snippet) > 100:
                results.append(snippet)
    # 去重（简单 overlap 检测）
    seen = []
    for r in results:
        if not any(r[:50] in s for s in seen):
            seen.append(r)
    return seen


def _sample_entries() -> str:
    return """
VITA

To Vita Sackville-West, 21 January 1926:
You make me feel that writing to you is writing into a warm room, whereas most
letters go into the cold. I want to tell you — and I say this knowing it sounds
excessive — that you have given me more than any woman has since my mother.
I think of you at Knole, among those rooms and centuries, and I am writing Orlando
for you. It will be your biography, your monument, your joke.

To Vita Sackville-West, 9 October 1927:
I am reading your poems and thinking about what it means to be a woman who owns
nothing she loves. Orlando will own everything. That is my gift to you.

MANSFIELD

From diary, 16 January 1923:
Katherine Mansfield died. I don't know why this should affect me so much — we
were never close, and yet I feel as if someone has taken something from the
world that I was measuring myself against. She was the only writer who seemed
to want what I want: not plot, not story, but the shimmer of the thing itself.
Now I am the only one left trying.

From diary, 22 March 1921:
Read Mansfield's new story. Damn her. She does it so easily — the exact
word, the precise feeling. And yet I think mine goes deeper. I think.
I am not sure. She makes me uncertain of everything I have done.
"""


def ingest_contemporaries(reset: bool = False):
    collection = get_or_create_collection("woolf_contemporaries", reset=reset)

    raw = fetch_letters()

    vita_snippets = extract_by_keywords(raw, VITA_KEYWORDS)
    mansfield_snippets = extract_by_keywords(raw, MANSFIELD_KEYWORDS)

    # 若抓取为空，用 sample
    if not vita_snippets and not mansfield_snippets:
        print("  No keywords found in fetched text, using sample entries")
        raw = _sample_entries()
        vita_snippets = extract_by_keywords(raw, VITA_KEYWORDS)
        mansfield_snippets = extract_by_keywords(raw, MANSFIELD_KEYWORDS)

    docs, ids, metas = [], [], []
    chunk_idx = 0

    for snippet in vita_snippets:
        for chunk in chunk_text(snippet, chunk_size=200, overlap=30):
            docs.append(chunk)
            ids.append(f"contemp_{chunk_idx}")
            metas.append({"person": "Vita Sackville-West", "source": "letters"})
            chunk_idx += 1

    for snippet in mansfield_snippets:
        for chunk in chunk_text(snippet, chunk_size=200, overlap=30):
            docs.append(chunk)
            ids.append(f"contemp_{chunk_idx}")
            metas.append({"person": "Katherine Mansfield", "source": "diary"})
            chunk_idx += 1

    if docs:
        print(f"  Tagging themes for {len(docs)} chunks...")
        themes_list = tag_chunks_batch(docs)
        for i, themes in enumerate(themes_list):
            metas[i]["themes"] = json.dumps(themes)
            metas[i]["themes_str"] = ",".join(themes)
        collection.add(documents=docs, ids=ids, metadatas=metas)

    print(f"  ✓ woolf_contemporaries: {len(docs)} chunks "
          f"(Vita: {len(vita_snippets)}, Mansfield: {len(mansfield_snippets)} raw snippets)")


if __name__ == "__main__":
    ingest_contemporaries(reset=True)
