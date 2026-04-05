"""
retrieval.py
统一检索模块：向量检索 + Step-back 深层查询 + GraphRAG 主题扩展 + MMR 排序

核心接口：
  retrieve(query, collections, top_k, use_stepback, use_graph)
"""

import os
import json
import asyncio
from typing import Optional
import anthropic
import networkx as nx
from kb_client import get_client, get_embedding_function, CHROMA_DB_PATH
from build_graph import load_graph, GRAPH_PATH

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL_FAST = os.getenv("CLAUDE_MODEL_FAST", "claude-haiku-4-5-20251001")

COLLECTIONS = [
    "woolf_works",
    "woolf_biography",
    "woolf_contemporaries",
    "woolf_historical",
    "woolf_annotations",
]

# 懒加载图
_graph: Optional[nx.Graph] = None


def _get_graph() -> Optional[nx.Graph]:
    global _graph
    if _graph is None and GRAPH_PATH.exists():
        _graph = load_graph()
    return _graph


# ─────────────────────────────────────────────
# Step 1: Step-back 深层查询扩展
# ─────────────────────────────────────────────

def stepback_expand(query: str) -> list[str]:
    """
    把表面问题扩展为 2-3 个深层查询
    例："你为什么写意识流" →
      ["伍尔夫对传统叙事结构的抗拒",
       "一战后英国文学对心理真实的追求",
       "伍尔夫自身意识体验与写作方式的关系"]
    """
    try:
        resp = client.messages.create(
            model=MODEL_FAST,
            max_tokens=200,
            system=(
                "你是一个文学研究助手。给定一个关于弗吉尼亚·伍尔夫的问题，"
                "生成 2-3 个更深层的搜索查询，用于检索回答该问题所需的底层知识。\n"
                "只输出 JSON 数组，例如：[\"查询1\", \"查询2\", \"查询3\"]"
            ),
            messages=[{"role": "user", "content": query}],
        )
        expanded = json.loads(resp.content[0].text.strip())
        return [query] + expanded  # 原始查询 + 扩展查询
    except Exception:
        return [query]  # 失败时只用原始查询


# ─────────────────────────────────────────────
# Step 2: 向量检索
# ─────────────────────────────────────────────

def vector_search(
    queries: list[str],
    collections: list[str],
    top_k_per_query: int = 3,
) -> list[dict]:
    """
    对多个查询并行检索多个 collection
    返回去重后的候选结果列表
    """
    chroma = get_client()
    target_collections = (
        COLLECTIONS if "all" in collections else
        [f"woolf_{c}" if not c.startswith("woolf_") else c for c in collections]
    )

    seen_ids = set()
    results = []

    for query in queries:
        for cname in target_collections:
            try:
                col = chroma.get_collection(cname)
                res = col.query(
                    query_texts=[query],
                    n_results=top_k_per_query,
                    include=["documents", "metadatas", "distances"],
                )
                for doc, meta, dist, doc_id in zip(
                    res["documents"][0],
                    res["metadatas"][0],
                    res["distances"][0],
                    res["ids"][0],  # ChromaDB always returns ids
                ):
                    chunk_id = doc_id  # Use actual document ID from ChromaDB
                    if chunk_id not in seen_ids:
                        seen_ids.add(chunk_id)
                        # 余弦距离转相似度（collection 建时需用 cosine metric）
                        similarity = max(0.0, 1.0 - dist)
                        results.append({
                            "content": doc,
                            "collection": cname,
                            "metadata": meta,
                            "score": similarity,
                            "chunk_id": chunk_id,  # Now matches graph node IDs
                        })
            except Exception:
                pass  # collection 不存在时跳过

    return results


# ─────────────────────────────────────────────
# Step 3: GraphRAG 主题扩展
# ─────────────────────────────────────────────

def graph_expand(initial_results: list[dict], max_expand: int = 3) -> list[dict]:
    """
    对 top 结果，通过主题图找到相连但未被检索到的段落
    """
    G = _get_graph()
    if G is None:
        return []

    chroma = get_client()
    expanded = []
    seen_ids = {r["chunk_id"] for r in initial_results}

    # 只扩展 top-3
    for result in initial_results[:3]:
        node_id = str(result["chunk_id"])
        if not G.has_node(node_id):
            continue

        # 取权重最高的邻居（共享主题最多的）
        neighbors = sorted(
            G.neighbors(node_id),
            key=lambda n: G[node_id][n].get("weight", 1),
            reverse=True,
        )[:max_expand]

        for neighbor_id in neighbors:
            if neighbor_id in seen_ids:
                continue
            seen_ids.add(neighbor_id)

            # 从 ID 反查 collection 和内容
            node_data = G.nodes.get(neighbor_id, {})
            cname = node_data.get("collection")
            if not cname:
                continue
            try:
                col = chroma.get_collection(cname)
                res = col.get(ids=[neighbor_id], include=["documents", "metadatas"])
                if res["documents"]:
                    shared = G[node_id][neighbor_id].get("shared_themes", [])
                    expanded.append({
                        "content": res["documents"][0],
                        "collection": cname,
                        "metadata": res["metadatas"][0],
                        "score": 0.5,  # 图扩展的基础分（低于直接检索）
                        "chunk_id": neighbor_id,
                        "via_graph": True,
                        "shared_themes": shared,
                    })
            except Exception:
                pass

    return expanded


# ─────────────────────────────────────────────
# Step 4: MMR 多样性排序
# ─────────────────────────────────────────────

def mmr_rerank(
    candidates: list[dict],
    top_k: int = 5,
    lambda_param: float = 0.6,
) -> list[dict]:
    """
    Maximal Marginal Relevance：平衡相关性与多样性
    lambda_param: 越高越偏向相关性，越低越偏向多样性
    """
    if not candidates:
        return []

    # 用 collection 作为多样性维度（同 collection 的结果互相"相似"）
    selected = []
    remaining = candidates.copy()

    while remaining and len(selected) < top_k:
        if not selected:
            # 第一个直接选相关性最高的
            best = max(remaining, key=lambda x: x["score"])
        else:
            # MMR 打分
            def mmr_score(candidate):
                relevance = candidate["score"]
                # 与已选结果的最大相似度（用 collection 相同作为简化的相似度指标）
                max_sim = max(
                    (1.0 if s["collection"] == candidate["collection"] else 0.3)
                    for s in selected
                )
                return lambda_param * relevance - (1 - lambda_param) * max_sim

            best = max(remaining, key=mmr_score)

        selected.append(best)
        remaining.remove(best)

    return selected


# ─────────────────────────────────────────────
# 主接口
# ─────────────────────────────────────────────

def retrieve(
    query: str,
    collections: list[str] = ["all"],
    top_k: int = 5,
    use_stepback: bool = True,
    use_graph: bool = True,
    cited_ids: Optional[set] = None,  # 本轮已引用的 chunk_id，降权
) -> list[dict]:
    """
    统一检索入口

    Args:
        query: 用户问题
        collections: 要检索的 collection（["all"] 或具体名称列表）
        top_k: 最终返回结果数
        use_stepback: 是否做深层查询扩展
        use_graph: 是否做主题图扩展
        cited_ids: 本轮已引用的 chunk，降权 0.3

    Returns:
        排序后的 top_k 结果列表
    """
    cited_ids = cited_ids or set()

    # Step 1: 查询扩展
    queries = stepback_expand(query) if use_stepback else [query]

    # Step 2: 向量检索
    initial = vector_search(queries, collections, top_k_per_query=3)

    # Step 3: GraphRAG 扩展
    graph_results = graph_expand(initial, max_expand=3) if use_graph else []

    # 合并
    all_candidates = initial + graph_results

    # 已引用段落降权
    for c in all_candidates:
        if c["chunk_id"] in cited_ids:
            c["score"] = max(0.0, c["score"] - 0.3)

    # Step 4: MMR 排序
    return mmr_rerank(all_candidates, top_k=top_k, lambda_param=0.6)
