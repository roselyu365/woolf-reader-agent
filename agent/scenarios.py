"""
scenarios.py
Route each request to one of 4 reasoning paradigms based on session state.
"""

from enum import Enum


class Scenario(str, Enum):
    DISCOVERY = "discovery"       # 5-round first-open dialogue
    REACT = "react"               # Default: ReAct tool loop
    THEMATIC = "thematic"         # Plan-and-Execute for cross-work themes
    ANNOTATION = "annotation"     # RAG pipeline for highlighted passages


# Keywords that suggest a thematic/cross-work exploration question
_THEMATIC_SIGNALS = [
    "throughout", "whole book", "across", "all of", "theme of", "themes",
    "recurring", "pattern", "connect", "relationship between", "how does",
    "compare", "contrast", "everywhere", "keeps coming back",
]


def detect_scenario(
    message: str,
    session_state: dict,
    discovery_round: int,
    highlighted_passage: str | None = None,
) -> Scenario:
    """
    Determine which reasoning paradigm to use.

    Priority order:
    1. Discovery: new session OR active discovery (round 1-4)
    2. Annotation: user has highlighted a specific passage
    3. Thematic: message signals cross-work theme exploration
    4. ReAct: default for all other deep-reading questions
    """
    # 1. Highlighted passage → annotation takes priority over discovery
    # (Reader endpoint always provides a passage; discovery is for mobile onboarding only)
    if highlighted_passage and highlighted_passage.strip():
        return Scenario.ANNOTATION

    # 2. Discovery: new session OR active discovery (round 1-4), mobile only
    if session_state.get("is_new") or (0 < discovery_round < 5):
        return Scenario.DISCOVERY

    # 3. Thematic signals → Plan-and-Execute
    msg_lower = message.lower()
    if any(signal in msg_lower for signal in _THEMATIC_SIGNALS):
        return Scenario.THEMATIC

    # 4. Default: ReAct loop
    return Scenario.REACT
