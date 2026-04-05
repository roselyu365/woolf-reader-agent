"""
build_graph.py
从 ChromaDB 读取所有 chunk 的主题标签，构建主题图，保存到 kb/theme_graph.json

运行时机：所有 ingest 脚本跑完后执行一次
  python build_graph.py
"""

import json
from pathlib import Path
import networkx as nx
from kb_client import get_client, CHROMA_DB_PATH

COLLECTIONS = [
    "woolf_works",
    "woolf_biography",
    "woolf_contemporaries",
    "woolf_historical",
    "woolf_annotations",
]

GRAPH_PATH = Path(__file__).parent.parent / "kb/theme_graph.json"


def load_all_chunks() -> list[dict]:
    """从所有 collection 读取 chunk id 和 themes"""
    client = get_client()
    all_chunks = []

    for cname in COLLECTIONS:
        try:
            col = client.get_collection(cname)
            results = col.get(include=["metadatas"])
            ids = results["ids"]
            metas = results["metadatas"]
            for chunk_id, meta in zip(ids, metas):
                themes_raw = meta.get("themes", "[]")
                try:
                    themes = json.loads(themes_raw)
                except Exception:
                    themes = []
                if themes:
                    all_chunks.append({
                        "id": chunk_id,
                        "collection": cname,
                        "themes": themes,
                    })
            print(f"  Loaded {len(ids)} chunks from {cname}")
        except Exception as e:
            print(f"  Warning: could not load {cname}: {e}")

    return all_chunks


def build_theme_graph(chunks: list[dict]) -> nx.Graph:
    """
    节点 = chunk_id
    边 = 两个 chunk 共享至少一个主题
    边权重 = 共享主题数量
    """
    G = nx.Graph()

    # 添加所有节点
    for chunk in chunks:
        G.add_node(chunk["id"],
                   collection=chunk["collection"],
                   themes=chunk["themes"])

    # 按主题分组，同主题内两两连边（避免 O(n²) 全量比较）
    theme_to_chunks: dict[str, list[str]] = {}
    for chunk in chunks:
        for theme in chunk["themes"]:
            theme_to_chunks.setdefault(theme, []).append(chunk["id"])

    edge_count = 0
    for theme, chunk_ids in theme_to_chunks.items():
        # 同主题内两两连边，最多取前50个（防止超热主题造成超密图）
        ids = chunk_ids[:50]
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                if G.has_edge(a, b):
                    # 增加边权重
                    G[a][b]["weight"] += 1
                    G[a][b]["shared_themes"].append(theme)
                else:
                    G.add_edge(a, b, weight=1, shared_themes=[theme])
                    edge_count += 1

    print(f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    return G


def save_graph(G: nx.Graph):
    """保存为 JSON（node-link 格式）"""
    GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(G)
    GRAPH_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"  ✓ Theme graph saved to {GRAPH_PATH}")


def load_graph() -> nx.Graph:
    """从 JSON 加载图（查询时调用）"""
    if not GRAPH_PATH.exists():
        raise FileNotFoundError(f"Theme graph not found at {GRAPH_PATH}. Run build_graph.py first.")
    data = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    return nx.node_link_graph(data)


def mark_proactive_passages(G: nx.Graph, degree_threshold: int = 3) -> int:
    """
    图里度数 >= degree_threshold 的节点，说明它与多个 collection 的内容主题相交，
    解读价值高 → 写回 ChromaDB metadata，打 has_proactive_insight=True 标记。

    返回标记的节点数量。
    """
    client = get_client()
    marked = 0

    for node_id, degree in G.degree():
        if degree < degree_threshold:
            continue

        node_data = dict(G.nodes[node_id])
        cname = node_data.get("collection")
        if not cname:
            continue

        try:
            col = client.get_collection(cname)
            # 保留原有 metadata，追加标记字段
            node_data["has_proactive_insight"] = True
            col.update(ids=[node_id], metadatas=[node_data])
            marked += 1
        except Exception as e:
            print(f"  Warning: could not mark {node_id}: {e}")

    return marked


if __name__ == "__main__":
    print("=== Building Theme Graph ===\n")
    print("Loading chunks from ChromaDB...")
    chunks = load_all_chunks()
    print(f"\nTotal tagged chunks: {len(chunks)}")

    print("\nBuilding graph...")
    G = build_theme_graph(chunks)

    print("\nSaving graph...")
    save_graph(G)

    print("\nMarking proactive passages (degree >= 3)...")
    n = mark_proactive_passages(G, degree_threshold=3)
    print(f"  ✓ Marked {n} passages with has_proactive_insight=True")

    print("\n=== Done ===")
