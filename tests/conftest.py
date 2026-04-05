import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add scripts and agent dirs to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock chromadb before any imports that depend on it (handles version mismatch)
sys.modules.setdefault("chromadb", MagicMock())
sys.modules.setdefault("chromadb.utils", MagicMock())
sys.modules.setdefault("chromadb.utils.embedding_functions", MagicMock())

# Mock sentence_transformers if not installed
sys.modules.setdefault("sentence_transformers", MagicMock())
