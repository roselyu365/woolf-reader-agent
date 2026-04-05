"""
Smoke tests — verify the system wires together correctly.
These mock the Claude API to avoid actual API calls.
"""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))


def test_health_endpoint():
    """FastAPI /health returns 200 and correct JSON."""
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock

    # Must mock chromadb and sentence_transformers before importing main
    with patch.dict("sys.modules", {
        "chromadb": MagicMock(),
        "chromadb.utils": MagicMock(),
        "chromadb.utils.embedding_functions": MagicMock(),
        "sentence_transformers": MagicMock(),
        "anthropic": MagicMock(),
    }):
        # Need to reload persona since it imports at module level
        import importlib
        if "persona" in sys.modules:
            del sys.modules["persona"]
        if "api.main" in sys.modules:
            del sys.modules["api.main"]

        sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
        import api.main as main_module
        client = TestClient(main_module.app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_scenario_detection_full_pipeline():
    """All 4 scenarios can be detected without errors."""
    from scenarios import detect_scenario, Scenario
    assert detect_scenario("hi", {"is_new": True, "has_reading_history": False}, 0) == Scenario.DISCOVERY
    assert detect_scenario("what does this mean?", {"is_new": False, "has_reading_history": True}, 5, "a passage") == Scenario.ANNOTATION
    assert detect_scenario("how does theme of money connect throughout the book?", {"is_new": False, "has_reading_history": True}, 5) == Scenario.THEMATIC
    assert detect_scenario("why did you write this?", {"is_new": False, "has_reading_history": True}, 5) == Scenario.REACT


def test_persona_anchors_file_loads():
    import json
    anchors_path = Path(__file__).parent.parent / "data/persona_anchors.json"
    assert anchors_path.exists(), "persona_anchors.json must exist"
    data = json.loads(anchors_path.read_text())
    assert "identity" in data
    assert "discovery_questions" in data
    assert len(data["discovery_questions"]) == 5


def test_discovery_state_full_5_rounds():
    from dialogue_state import DiscoveryState
    state = DiscoveryState(session_id="smoke_test")
    for i in range(4):
        q = state.get_next_question()
        assert q != "__synthesis__"
        state.record_answer(f"answer {i}")
    q5 = state.get_next_question()
    assert q5 == "__synthesis__"
    assert state.is_complete()
    synthesis = state.get_synthesis_prompt()
    assert len(synthesis) > 50
