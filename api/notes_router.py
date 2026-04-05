"""
notes_router.py
User notes CRUD: save highlights, retrieve by session.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from kb_client import get_or_create_collection

router = APIRouter(prefix="/notes", tags=["notes"])


class NoteCreate(BaseModel):
    content: str
    session_id: str
    woolf_related: bool = True
    passage_ref: str = ""


@router.post("/add")
def add_note(note: NoteCreate):
    try:
        import time
        col = get_or_create_collection("user_notes")
        note_id = f"note_{note.session_id}_{int(time.time())}"
        col.add(
            documents=[note.content],
            ids=[note_id],
            metadatas=[{
                "session_id": note.session_id,
                "woolf_related": str(note.woolf_related),
                "passage_ref": note.passage_ref,
            }],
        )
        return {"status": "saved", "id": note_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}")
def get_notes(session_id: str):
    try:
        col = get_or_create_collection("user_notes")
        results = col.get(
            where={"session_id": session_id},
            include=["documents", "metadatas"],
        )
        notes = [
            {"content": doc, "metadata": meta}
            for doc, meta in zip(results["documents"], results["metadatas"])
        ]
        return {"session_id": session_id, "notes": notes}
    except Exception as e:
        return {"session_id": session_id, "notes": [], "error": str(e)}
