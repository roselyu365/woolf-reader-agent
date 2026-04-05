"""
tools.py
Claude API tool definitions and executor.
The agent calls these tools during ReAct reasoning.
"""

import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from retrieval import retrieve as _retrieve
from kb_client import get_or_create_collection

# ─── Tool Definitions (passed to Claude API) ────────────────────────────────

TOOLS = [
    {
        "name": "retrieve_knowledge",
        "description": (
            "Search the Woolf knowledge base for relevant passages, diary entries, "
            "historical context, or annotations. "
            "Collections: woolf_works (A Room of One's Own text), "
            "woolf_biography (diaries 1928-29, letters), "
            "woolf_contemporaries (Vita Sackville-West, Katherine Mansfield), "
            "woolf_historical (Bloomsbury, suffrage, WWI context), "
            "woolf_annotations (SparkNotes/GradeSaver study notes). "
            "Use 'all' to search everything. Use specific collections when you know "
            "where the answer lives."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What you are looking for. Be specific and conceptual, not just keyword-matching.",
                },
                "collections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Collections to search. Use ['all'] to search all, or specify e.g. ['woolf_works', 'woolf_biography']",
                    "default": ["all"],
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5, max 10)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "add_user_note",
        "description": (
            "Save a user's highlight, annotation, or personal reflection to their notes. "
            "Use this when the user marks a passage, writes a note, or asks you to remember something they said."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The text of the note or highlighted passage",
                },
                "session_id": {
                    "type": "string",
                    "description": "Current session identifier",
                },
                "woolf_related": {
                    "type": "boolean",
                    "description": "Whether this note is directly about Woolf's work (true) or a personal reflection (false)",
                    "default": True,
                },
                "passage_ref": {
                    "type": "string",
                    "description": "Optional: which passage or chapter this note refers to",
                },
            },
            "required": ["content", "session_id"],
        },
    },
    {
        "name": "search_conversation_memory",
        "description": (
            "Search summaries of past conversations with this user. "
            "Use when the user references something from a previous session, "
            "or when you want to recall what they found meaningful before."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What you are trying to recall from past conversations",
                },
                "session_id": {
                    "type": "string",
                    "description": "Current session ID — searches memories linked to this user",
                },
            },
            "required": ["query", "session_id"],
        },
    },
]


# OpenAI/Zhipu format tool definitions
TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        }
    }
    for t in TOOLS
]


# ─── Executor ────────────────────────────────────────────────────────────────

def execute_tool(
    tool_name: str,
    tool_input: dict,
    cited_ids: set | None = None,
) -> str:
    """
    Execute a tool call from Claude and return a string result.
    cited_ids: set of chunk_ids already cited this conversation (for MMR penalty).
    """
    cited_ids = cited_ids or set()

    if tool_name == "retrieve_knowledge":
        results = _retrieve(
            query=tool_input["query"],
            collections=tool_input.get("collections", ["all"]),
            top_k=min(tool_input.get("top_k", 5), 10),
            use_stepback=True,
            use_graph=True,
            cited_ids=cited_ids,
        )
        # Update cited_ids with returned results
        for r in results:
            cited_ids.add(r["chunk_id"])
        return _format_retrieve_results(results)

    elif tool_name == "add_user_note":
        return _add_user_note(tool_input)

    elif tool_name == "search_conversation_memory":
        return _search_conversation_memory(tool_input, cited_ids)

    else:
        raise ValueError(f"Unknown tool: {tool_name}")


def _format_retrieve_results(results: list[dict]) -> str:
    if not results:
        return "No relevant passages found."
    parts = []
    for i, r in enumerate(results, 1):
        collection = r["collection"].replace("woolf_", "").replace("_", " ")
        score = r.get("score", 0)
        via = " [via theme graph]" if r.get("via_graph") else ""
        parts.append(
            f"[{i}] ({collection}, relevance: {score:.2f}{via})\n{r['content']}"
        )
    return "\n\n---\n\n".join(parts)


def _add_user_note(tool_input: dict) -> str:
    try:
        col = get_or_create_collection("user_notes")
        note_id = f"note_{tool_input['session_id']}_{int(time.time())}"
        col.add(
            documents=[tool_input["content"]],
            ids=[note_id],
            metadatas=[{
                "session_id": tool_input["session_id"],
                "woolf_related": str(tool_input.get("woolf_related", True)),
                "passage_ref": tool_input.get("passage_ref", ""),
            }],
        )
        return f"Note saved: {tool_input['content'][:80]}..."
    except Exception as e:
        return f"Could not save note: {e}"


def _search_conversation_memory(tool_input: dict, cited_ids: set) -> str:
    results = _retrieve(
        query=tool_input["query"],
        collections=["conversation_memory"],
        top_k=3,
        use_stepback=False,
        use_graph=False,
        cited_ids=cited_ids,
    )
    # cited_ids passed for MMR penalty but NOT updated: memory results
    # should remain accessible on repeat queries, unlike knowledge chunks.
    if not results:
        return "No relevant conversation history found."
    return "\n\n---\n\n".join(r["content"] for r in results)
