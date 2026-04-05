import pytest
from unittest.mock import patch, MagicMock


def test_build_system_prompt_includes_identity():
    from persona import build_system_prompt
    prompt = build_system_prompt(session_id="s1", endpoint="mobile")
    assert "Virginia Woolf" in prompt
    assert "not performing" in prompt  # from identity field


def test_build_system_prompt_includes_forbidden_phrases_instruction():
    from persona import build_system_prompt
    prompt = build_system_prompt(session_id="s1", endpoint="reader")
    assert "I am an AI" in prompt  # forbidden phrases listed


def test_build_system_prompt_endpoint_context():
    from persona import build_system_prompt
    mobile_prompt = build_system_prompt(session_id="s1", endpoint="mobile")
    reader_prompt = build_system_prompt(session_id="s1", endpoint="reader")
    # Reader prompt should mention the reading context
    assert "reader" in reader_prompt.lower() or "reading" in reader_prompt.lower()
    # Prompts should be different for different endpoints
    assert mobile_prompt != reader_prompt


def test_should_auto_summarize():
    from persona import should_auto_summarize
    assert should_auto_summarize(round_count=5) is True
    assert should_auto_summarize(round_count=10) is True
    assert should_auto_summarize(round_count=4) is False
    assert should_auto_summarize(round_count=7) is False
