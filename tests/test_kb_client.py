import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add scripts directory to path before any imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

def test_collection_uses_cosine_metric():
    """get_or_create_collection must pass cosine metadata to ChromaDB."""
    sys.modules.pop('kb_client', None)  # Force clean import inside mock context

    mock_client = MagicMock()
    mock_col = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_col

    # Mock chromadb before importing kb_client
    with patch.dict('sys.modules', {'chromadb': MagicMock()}), \
         patch.dict('sys.modules', {'chromadb.utils': MagicMock()}), \
         patch.dict('sys.modules', {'chromadb.utils.embedding_functions': MagicMock()}), \
         patch("kb_client.get_client", return_value=mock_client), \
         patch("kb_client.get_embedding_function", return_value=MagicMock()):
        from kb_client import get_or_create_collection
        get_or_create_collection("test_collection")

    call_kwargs = mock_client.get_or_create_collection.call_args
    assert call_kwargs.kwargs.get("metadata") == {"hnsw:space": "cosine"}, \
        "Collection must use cosine space for distance-to-similarity conversion"
