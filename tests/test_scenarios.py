import pytest
from scenarios import detect_scenario, Scenario


def test_new_session_routes_to_discovery():
    scenario = detect_scenario(
        message="hello",
        session_state={"is_new": True, "has_reading_history": False},
        discovery_round=0,
    )
    assert scenario == Scenario.DISCOVERY


def test_active_discovery_stays_in_discovery():
    scenario = detect_scenario(
        message="I feel like I'm in a fog",
        session_state={"is_new": False, "has_reading_history": False},
        discovery_round=3,
    )
    assert scenario == Scenario.DISCOVERY


def test_highlighted_passage_routes_to_annotation():
    scenario = detect_scenario(
        message="what does this mean?",
        session_state={"is_new": False, "has_reading_history": True},
        discovery_round=5,
        highlighted_passage="A woman must have money and a room of her own",
    )
    assert scenario == Scenario.ANNOTATION


def test_thematic_question_routes_to_plan_execute():
    scenario = detect_scenario(
        message="How does the theme of money connect to women's freedom throughout the whole book?",
        session_state={"is_new": False, "has_reading_history": True},
        discovery_round=5,
    )
    assert scenario == Scenario.THEMATIC


def test_default_routes_to_react():
    scenario = detect_scenario(
        message="Why did you write in this style?",
        session_state={"is_new": False, "has_reading_history": True},
        discovery_round=5,
    )
    assert scenario == Scenario.REACT
