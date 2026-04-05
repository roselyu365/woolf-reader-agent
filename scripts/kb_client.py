"""
ChromaDB 共用客户端，所有 ingest 脚本复用
"""

import os
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

load_dotenv()

CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "./kb/chroma")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

_client = None
_ef = None


def get_client() -> chromadb.Client:
    global _client
    if _client is None:
        Path(CHROMA_DB_PATH).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    return _client


def get_embedding_function():
    global _ef
    if _ef is None:
        _ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
    return _ef


# NOTE: All collections use cosine space so that retrieval.py can compute
# similarity = 1 - distance. If collections were created before this fix,
# they must be rebuilt: python build_kb.py --reset
def get_or_create_collection(name: str, reset: bool = False):
    client = get_client()
    ef = get_embedding_function()
    if reset:
        try:
            client.delete_collection(name)
            print(f"  Deleted existing collection: {name}")
        except Exception:
            pass
    return client.get_or_create_collection(
        name=name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


def chunk_text(text: str, chunk_size: int = 300, overlap: int = 50) -> list[str]:
    """按词切块，保留重叠"""
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return [c for c in chunks if len(c.split()) > 20]  # 过滤过短块
