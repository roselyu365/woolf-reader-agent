"""
mobile_router.py
Mobile app endpoints: single-turn chat + WebSocket streaming.
"""

import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))

from agent import WoolfAgent

router = APIRouter(prefix="/mobile", tags=["mobile"])

# In-memory session store (replace with Redis for production)
_sessions: dict[str, WoolfAgent] = {}

# 当前约定的书目（单设备场景，全局一个值即可）
_scheduled_book: str = "daluo_weifuren"  # 默认达洛维夫人中文版


def _get_or_create_agent(session_id: str) -> WoolfAgent:
    if session_id not in _sessions:
        _sessions[session_id] = WoolfAgent(session_id=session_id, endpoint="mobile")
    return _sessions[session_id]


class ChatRequest(BaseModel):
    session_id: str
    message: str


class SetBookRequest(BaseModel):
    book: str  # e.g. "mrs_dalloway" | "a_room_of_ones_own"


@router.post("/set_book")
def set_book(req: SetBookRequest):
    global _scheduled_book
    _scheduled_book = req.book
    return {"book": _scheduled_book}


@router.get("/scheduled_book")
def get_scheduled_book():
    return {"book": _scheduled_book}


@router.post("/chat")
async def chat(req: ChatRequest):
    agent = _get_or_create_agent(req.session_id)
    tokens = []
    async for token in agent.chat_stream(req.message):
        tokens.append(token)
    return {"session_id": req.session_id, "response": "".join(tokens)}


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            session_id = payload.get("session_id", "default")
            message = payload.get("message", "")

            agent = _get_or_create_agent(session_id)
            async for token in agent.chat_stream(message):
                await websocket.send_text(json.dumps({"type": "token", "text": token}))
            await websocket.send_text(json.dumps({"type": "done"}))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except RuntimeError:
            pass  # Socket already closed
