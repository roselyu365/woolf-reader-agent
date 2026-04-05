import pytest
from dialogue_state import DiscoveryState, DialogueComplete


def test_initial_state():
    state = DiscoveryState(session_id="test123")
    assert state.round == 0
    assert state.is_complete() is False
    assert state.is_active() is False


def test_first_question_starts_dialogue():
    state = DiscoveryState(session_id="test123")
    question = state.get_next_question()
    assert state.round == 1
    assert state.is_active() is True
    assert "dined well" in question  # quotes from persona_anchors


def test_record_answer_advances_round():
    state = DiscoveryState(session_id="test123")
    state.get_next_question()  # round 1
    state.record_answer("I am feeling depleted but curious")
    state.get_next_question()  # round 2
    assert state.round == 2
    assert len(state.answers) == 1


def test_five_rounds_completes():
    state = DiscoveryState(session_id="test123")
    for i in range(4):
        state.get_next_question()
        state.record_answer(f"answer {i}")
    state.get_next_question()  # round 5 — synthesis
    assert state.round == 5
    assert state.is_complete() is True
    assert state.is_active() is False  # round 5: complete but not active


def test_synthesis_prompt_contains_answers():
    state = DiscoveryState(session_id="test123")
    for i in range(4):
        state.get_next_question()
        state.record_answer(f"user said: {i}")
    state.get_next_question()  # round 5 — must call before synthesis
    synthesis = state.get_synthesis_prompt()
    assert "user said: 0" in synthesis
    assert "user said: 3" in synthesis
    assert "synthesize" in synthesis.lower()


def test_overage_raises_dialogue_complete():
    """Test that calling get_next_question() 6 times raises DialogueComplete."""
    state = DiscoveryState(session_id="test123")
    for i in range(4):
        state.get_next_question()
        state.record_answer(f"answer {i}")
    state.get_next_question()  # round 5
    with pytest.raises(DialogueComplete):
        state.get_next_question()  # 6th call — should raise


def test_record_answer_before_question_raises():
    """Test that record_answer() before first question raises RuntimeError."""
    state = DiscoveryState(session_id="test123")
    with pytest.raises(RuntimeError, match="Cannot record answer before first question"):
        state.record_answer("premature answer")


def test_record_answer_twice_same_round_raises():
    """Test that record_answer() twice for same round raises RuntimeError."""
    state = DiscoveryState(session_id="test123")
    state.get_next_question()  # round 1
    state.record_answer("answer 1")
    with pytest.raises(RuntimeError, match="Answer for round 1 already recorded"):
        state.record_answer("answer 1 again")


def test_get_synthesis_prompt_before_complete_raises():
    """Test that get_synthesis_prompt() before round 5 raises RuntimeError."""
    state = DiscoveryState(session_id="test123")
    state.get_next_question()  # round 1
    state.record_answer("answer 1")
    with pytest.raises(RuntimeError, match="Cannot synthesize before dialogue completes"):
        state.get_synthesis_prompt()
