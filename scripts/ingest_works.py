"""
ingest_works.py
伍尔夫作品正文 → 按段落分块 → 存入 woolf_works collection

支持四本书：
  a_room_of_ones_own  《一间自己的房间》
  mrs_dalloway        《达洛维夫人》
  three_guineas       《三枚金币》
  common_reader       《普通读者》

每个 chunk 的 metadata 包含 para_idx，与 /reader/text 端点返回的段落索引一致，
使 has_proactive_insight 标注能准确对应前端显示的段落。
"""

import re
import sys
import json
import argparse
from pathlib import Path
from kb_client import get_or_create_collection, chunk_text
from theme_tagger import tag_chunks_batch

RAW_DIR = Path(__file__).parent.parent / "data/raw"

BOOK_FILES = {
    "a_room_of_ones_own": "a_room_of_ones_own.txt",
    "mrs_dalloway":       "mrs_dalloway.txt",
    "three_guineas":      "three_guineas.txt",
    "common_reader":      "common_reader.txt",
}

BOOK_TITLES = {
    "a_room_of_ones_own": "A Room of One's Own",
    "mrs_dalloway":       "Mrs. Dalloway",
    "three_guineas":      "Three Guineas",
    "common_reader":      "The Common Reader",
}


def _strip_gutenberg(lines: list[str], filename: str) -> list[str]:
    """
    去掉 Gutenberg 头尾，与 reader_router.py 逻辑完全一致，
    确保 para_idx 与前端显示段落对齐。
    """
    if filename in ("mrs_dalloway.txt", "common_reader.txt"):
        # 标准格式：*** START OF *** / *** END OF ***
        start_idx = 0
        for i, line in enumerate(lines):
            if "*** START OF" in line:
                start_idx = i + 1
                break
        # 跳过书目/版权页，找到第一段实际正文
        content_start = start_idx
        for i in range(start_idx, len(lines)):
            stripped = lines[i].strip()
            if (stripped
                    and not stripped.startswith("[")
                    and not stripped.startswith("_")
                    and not stripped.isupper()
                    and not stripped.startswith("*")
                    and len(stripped) > 40):
                content_start = i
                break
        end_idx = len(lines)
        for i, line in enumerate(lines):
            if "*** END OF" in line:
                end_idx = i
                break
        return lines[content_start:end_idx]

    else:
        # Australia 格式（a_room_of_ones_own, three_guineas）：--- 分隔线
        start_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("---") and len(line.strip()) > 10:
                start_idx = i + 1
                break
        end_idx = len(lines)
        for i in range(len(lines) - 1, start_idx, -1):
            stripped = lines[i].strip()
            if stripped in ("THE END", "Project Gutenberg Australia"):
                end_idx = i
                break
        return lines[start_idx:end_idx]


def load_paragraphs(book_slug: str) -> list[str]:
    """
    加载并返回段落列表，与 /reader/text 端点完全相同的处理逻辑。
    para_idx = 列表索引。
    """
    filename = BOOK_FILES[book_slug]
    path = RAW_DIR / filename
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    content_lines = _strip_gutenberg(lines, filename)
    text = "\n".join(content_lines)
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def ingest_one_book(book_slug: str, reset: bool = False):
    """把一本书的所有段落入库，para_idx 对应前端段落索引。"""
    collection = get_or_create_collection("woolf_works", reset=reset)
    title = BOOK_TITLES[book_slug]

    paragraphs = load_paragraphs(book_slug)
    print(f"  {title}: {len(paragraphs)} paragraphs")

    docs, ids, metas = [], [], []
    chunk_idx = 0

    for para_idx, para_text in enumerate(paragraphs):
        # 长段落进一步切块（保留 overlap），短段落直接作为一个 chunk
        chunks = chunk_text(para_text, chunk_size=300, overlap=50)
        if not chunks:
            chunks = [para_text] if para_text else []

        for chunk_in_para, chunk in enumerate(chunks):
            doc_id = f"{book_slug}_{chunk_idx}"
            # 检查是否已存在（--reset 时不需要）
            docs.append(chunk)
            ids.append(doc_id)
            metas.append({
                "book": title,
                "book_slug": book_slug,
                "para_idx": para_idx,          # ← 对应前端显示段落
                "chunk_in_para": chunk_in_para,
                "chunk_idx": chunk_idx,
            })
            chunk_idx += 1

    # 主题标注（需要 ANTHROPIC_API_KEY，失败时静默跳过）
    print(f"  Tagging themes for {len(docs)} chunks...")
    themes_list = tag_chunks_batch(docs)
    for i, themes in enumerate(themes_list):
        metas[i]["themes"] = json.dumps(themes)
        metas[i]["themes_str"] = ",".join(themes)

    # ChromaDB 批量写入（上限 5000/批）
    batch_size = 500
    for i in range(0, len(docs), batch_size):
        collection.add(
            documents=docs[i:i + batch_size],
            ids=ids[i:i + batch_size],
            metadatas=metas[i:i + batch_size],
        )

    print(f"  ✓ woolf_works: +{len(docs)} chunks ({title})")


def ingest_works(reset: bool = False, books: list[str] | None = None):
    """入口：默认灌入所有书，也可指定 books 列表。"""
    target_books = books or list(BOOK_FILES.keys())

    # reset 只在第一本时执行（清空 collection 一次）
    for i, slug in enumerate(target_books):
        ingest_one_book(slug, reset=(reset and i == 0))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest Woolf works into ChromaDB")
    parser.add_argument(
        "--books", nargs="+",
        choices=list(BOOK_FILES.keys()) + ["all"],
        default=["all"],
        help="Which books to ingest",
    )
    parser.add_argument("--reset", action="store_true", help="Delete and rebuild collection")
    args = parser.parse_args()

    books = None if "all" in args.books else args.books
    ingest_works(reset=args.reset, books=books)
