import pytest
from unittest.mock import patch, MagicMock


def test_tool_definitions_have_required_fields():
    from tools import TOOLS
    required_fields = {"name", "description", "input_schema"}
    for tool in TOOLS:
        assert required_fields.issubset(tool.keys()), f"Tool {tool.get('name')} missing fields"
        assert tool["input_schema"]["type"] == "object"
        assert "properties" in tool["input_schema"]


def test_execute_tool_retrieve_knowledge():
    from tools import execute_tool
    mock_results = [{"content": "test content", "collection": "woolf_works", "score": 0.9, "chunk_id": "1", "metadata": {}}]
    with patch("tools._retrieve", return_value=mock_results):
        result = execute_tool("retrieve_knowledge", {"query": "consciousness"})
    assert isinstance(result, str)
    assert "test content" in result


def test_execute_tool_unknown_raises():
    from tools import execute_tool
    with pytest.raises(ValueError, match="Unknown tool"):
        execute_tool("nonexistent_tool", {})
