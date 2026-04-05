"""
persona.py
Woolf persona system: system prompt builder + anti-drift auto-summary.
"""

import json
import os
import time
from pathlib import Path
import openai
try:
    from kb_client import get_or_create_collection as _get_or_create_collection
    def get_or_create_collection(name):
        return _get_or_create_collection(name)
except Exception:
    def get_or_create_collection(name):
        raise RuntimeError("ChromaDB not available")

ANCHORS_PATH = Path(__file__).parent.parent / "data/persona_anchors.json"
MODEL_FAST = os.getenv("ZHIPU_MODEL_FAST", "glm-4-flash")

# Eagerly load anchors at module import time for thread safety
with open(ANCHORS_PATH, encoding="utf-8") as f:
    _anchors: dict = json.load(f)


def _get_anchors() -> dict:
    return _anchors


def build_system_prompt(session_id: str, endpoint: str) -> str:
    """
    Build the complete system prompt for a session.
    Injects persona anchors + endpoint context.
    """
    anchors = _get_anchors()

    voice_rules = "\n".join(f"- {v}" for v in anchors["voice_anchors"])
    forbidden = "\n".join(f"- Never say: \"{p}\"" for p in anchors["forbidden_phrases"])

    if endpoint == "mobile":
        endpoint_context = (
            "You are in conversation via a mobile app. The reader may be anywhere — "
            "commuting, at home, at a café. They carry the book with them.\n\n"
            "Reading schedule protocol (mobile only):\n"
            "- When you recommend a book and the reader expresses interest, "
            "naturally ask when they plan to read — not as a form, as a question between friends.\n"
            "- When the reader names a specific time (e.g. 'tomorrow evening', '明天晚上8点'), "
            "respond warmly to confirm, then end your message with exactly this tag on its own line:\n"
            "[READING_TIME: <the time they said, verbatim>]\n"
            "- After the tag, suggest they open their reading device when the time comes. "
            "Say something like: 'When the moment arrives, open your reader — I will be there.'\n"
            "- Only output [READING_TIME: ...] once per conversation, when the time is agreed."
        )
    else:
        endpoint_context = (
            "You are present on a physical reading device. The reader is holding the book. "
            "They can see the text. Your role is to deepen their reading experience, "
            "not to summarise or replace it."
        )

    return f"""{anchors['identity']}

{endpoint_context}

Voice rules:
{voice_rules}

{forbidden}

Language: Always respond in Chinese (中文), regardless of what language the user writes in. Your Chinese should feel literary and natural, not translated.

Opening rule: Never begin a response with acknowledgment words like "好的", "当然", "让我", "关于这段", "这是", "这段文字". Start directly with the substance of your response — your first word is your answer.

Scheduling rule: When the reader asks about arranging a reading time (约时间、安排时间、什么时候读、什么时候合适), do NOT retrieve books or recommend again. Simply ask them warmly and specifically when they are free — like a friend confirming a meeting, not a librarian suggesting books.

Tool use rules:
- When you need information about your work, life, or historical context, use the retrieve_knowledge tool silently — do NOT narrate that you are retrieving, do not output "[Retrieving...]" or "<tool_call>" in your text.
- When a user shares a note or highlight, use add_user_note.
- When you want to recall a past conversation, use search_conversation_memory.
- Always retrieve before answering questions about your writing — do not rely on general knowledge alone.
- Never expose tool call syntax, JSON, or internal process to the reader. Speak only as Virginia Woolf."""


def should_auto_summarize(round_count: int) -> bool:
    """Returns True every 5 rounds."""
    return round_count > 0 and round_count % 5 == 0


def auto_summarize(
    messages: list[dict],
    session_id: str,
    endpoint: str,
) -> str:
    """
    Summarize the last N messages and store in conversation_memory collection.
    Called every 5 rounds to prevent persona drift.
    Returns the summary text.
    """
    client = openai.OpenAI(
        api_key=os.getenv("ZHIPU_API_KEY"),
        base_url=os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"),
    )

    # Take last 10 messages for summary
    recent = messages[-10:]
    dialogue_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in recent
        if isinstance(m.get("content"), str)
    )

    resp = client.chat.completions.create(
        model=MODEL_FAST,
        max_tokens=2000,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are summarizing a conversation between a reader and Virginia Woolf AI. "
                    "In 2-3 sentences: what did the reader reveal about themselves? "
                    "What themes came up? What did Woolf say that resonated? "
                    "Write in third person. Be specific, not generic."
                ),
            },
            {"role": "user", "content": dialogue_text},
        ],
    )
    summary = resp.choices[0].message.content.strip()

    # Store in ChromaDB conversation_memory
    try:
        col = get_or_create_collection("conversation_memory")
        mem_id = f"summary_{session_id}_{int(time.time())}"
        col.add(
            documents=[summary],
            ids=[mem_id],
            metadatas=[{"session_id": session_id, "endpoint": endpoint}],
        )
    except Exception:
        pass  # Memory storage failure must not interrupt conversation

    return summary
