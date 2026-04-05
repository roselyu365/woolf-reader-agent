"""
dialogue_state.py
5-round discovery dialogue state machine.
Always runs on first session. No fallback. No skipping.
"""

import json
from pathlib import Path
from dataclasses import dataclass, field

ANCHORS_PATH = Path(__file__).parent.parent / "data/persona_anchors.json"


class DialogueComplete(Exception):
    """Raised when get_next_question() is called after all 5 rounds are complete."""
    pass


def _load_questions() -> list[dict]:
    with open(ANCHORS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["discovery_questions"]


@dataclass
class DiscoveryState:
    session_id: str
    round: int = 0
    answers: list[str] = field(default_factory=list)
    _questions: list[dict] = field(default_factory=_load_questions, repr=False)

    def is_active(self) -> bool:
        """True if dialogue has started but not finished (rounds 1-4)."""
        return 0 < self.round < 5

    def is_complete(self) -> bool:
        """True after round 5 question is issued."""
        return self.round >= 5

    def get_next_question(self) -> str:
        """
        Advance to next round and return the question text.
        For round 5, returns a synthesis instruction (internal use).
        Raises DialogueComplete if called after completion.
        """
        if self.is_complete():
            raise DialogueComplete("Discovery dialogue already complete")

        self.round += 1
        q = self._questions[self.round - 1]

        if q.get("synthesis"):
            # Round 5 is synthesis — no question to ask, handled in agent
            return "__synthesis__"
        return q["theme"]

    def record_answer(self, answer: str) -> None:
        """Store user's answer for the current round."""
        if self.round == 0:
            raise RuntimeError("Cannot record answer before first question is issued")
        if len(self.answers) >= self.round:
            raise RuntimeError(f"Answer for round {self.round} already recorded")
        self.answers.append(answer)

    def get_synthesis_prompt(self) -> str:
        """
        Build the synthesis prompt injected into Claude for round 5.
        Includes all previous answers.
        """
        if not self.is_complete():
            raise RuntimeError(
                f"Cannot synthesize before dialogue completes (round={self.round})"
            )
        q5 = self._questions[4]
        answers_text = "\n".join(
            f"第{i+1}轮读者说：「{ans}」" for i, ans in enumerate(self.answers)
        )
        return (
            f"{q5['instruction']}\n\n"
            f"读者在四轮对话中透露的内容：\n{answers_text}"
        )

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "round": self.round,
            "answers": self.answers,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DiscoveryState":
        state = cls(session_id=data["session_id"])
        state.round = data["round"]
        state.answers = data["answers"]
        return state
