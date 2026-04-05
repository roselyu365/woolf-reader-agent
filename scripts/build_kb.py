"""
知识库构建主入口
运行顺序：works → biography → contemporaries → historical → annotations
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ingest_works import ingest_works
from ingest_biography import ingest_biography
from ingest_contemporaries import ingest_contemporaries
from ingest_historical import ingest_historical
from ingest_annotations import ingest_annotations
from build_graph import load_all_chunks, build_theme_graph, save_graph


def main():
    parser = argparse.ArgumentParser(description="Build Woolf knowledge base")
    parser.add_argument(
        "--collections",
        nargs="+",
        choices=["works", "biography", "contemporaries", "historical", "annotations", "all"],
        default=["all"],
        help="Which collections to build",
    )
    parser.add_argument("--reset", action="store_true", help="Delete and rebuild collection")
    args = parser.parse_args()

    target = set(args.collections)
    build_all = "all" in target

    print("=== Woolf KB Builder ===\n")

    if build_all or "works" in target:
        print("[1/5] Ingesting works (all 4 books)...")
        ingest_works(reset=args.reset)

    if build_all or "biography" in target:
        print("[2/5] Ingesting biography (diaries + letters)...")
        ingest_biography(reset=args.reset)

    if build_all or "contemporaries" in target:
        print("[3/5] Ingesting contemporaries (Vita + Mansfield)...")
        ingest_contemporaries(reset=args.reset)

    if build_all or "historical" in target:
        print("[4/5] Ingesting historical context...")
        ingest_historical(reset=args.reset)

    if build_all or "annotations" in target:
        print("[5/5] Ingesting annotations...")
        ingest_annotations(reset=args.reset)

    print("[6/6] Building theme graph (GraphRAG)...")
    chunks = load_all_chunks()
    G = build_theme_graph(chunks)
    save_graph(G)

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
