"""
reader_router.py
Reader device endpoints: chat + WebSocket with highlighted passage support.
Proactive trigger: pre-generates commentary N paragraphs ahead.
"""

import json
import asyncio
import threading
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, BackgroundTasks
from pydantic import BaseModel
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from agent import WoolfAgent
from persona import build_system_prompt
import openai

MODEL_FAST = os.getenv("ZHIPU_MODEL_FAST", "glm-4-flash")

_zhipu_client = openai.OpenAI(
    api_key=os.getenv("ZHIPU_API_KEY"),
    base_url=os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"),
)

router = APIRouter(prefix="/reader", tags=["reader"])

_RAW_DIR = Path(__file__).parent.parent / "data/raw"

# Supported books: slug → (filename, encoding, format_type)
BOOK_FILES = {
    # Chinese versions (primary)
    "daluo_weifuren": ("达洛维夫人.txt", "utf-16", "bilingual"),
    "yijian_fangjian": ("一间只属于自己的房间[lunarora.com].txt", "utf-16", "chinese"),
    "xie_xialai": ("写下来,痛苦就会过去[lunarora.com].txt", "utf-16", "chinese"),
    "sikao_dikang": ("思考就是我的抵抗[lunarora.com].txt", "utf-16", "chinese"),
    # English versions (kept for reference)
    "a_room_of_ones_own": ("a_room_of_ones_own.txt", "utf-8", "australia"),
    "mrs_dalloway": ("mrs_dalloway.txt", "utf-8", "gutenberg"),
    "three_guineas": ("three_guineas.txt", "utf-8", "australia"),
    "common_reader": ("common_reader.txt", "utf-8", "gutenberg"),
}

# Cache: book slug → paragraphs
_paragraphs_cache: dict[str, list[str]] = {}


def _strip_gutenberg(lines: list[str], filename: str) -> list[str]:
    """
    Strip Gutenberg headers and footers.
    Handles two formats:
    - Standard (mrs_dalloway): *** START OF *** / *** END OF *** markers,
      plus a bibliography block before the actual text.
    - Australia (a_room_of_ones_own): dashed separator line before text,
      'THE END' + 'Project Gutenberg Australia' footer.
    """
    if filename == "mrs_dalloway.txt":
        # Find start marker, then skip bibliography until first real prose paragraph
        start_idx = 0
        for i, line in enumerate(lines):
            if "*** START OF" in line:
                start_idx = i + 1
                break
        # Skip bibliography/front matter: find first line that looks like prose
        # (starts with a capital letter, not a title/all-caps line, not [Illustration])
        content_start = start_idx
        for i in range(start_idx, len(lines)):
            stripped = lines[i].strip()
            if (stripped and not stripped.startswith("[")
                    and not stripped.startswith("_")
                    and not stripped.isupper()
                    and not stripped.startswith("*")
                    and len(stripped) > 40):
                content_start = i
                break
        # Find end marker
        end_idx = len(lines)
        for i, line in enumerate(lines):
            if "*** END OF" in line:
                end_idx = i
                break
        return lines[content_start:end_idx]

    else:
        # Australia format: separator line → metadata block → chapter heading → prose
        start_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("---") and len(line.strip()) > 10:
                start_idx = i + 1
                break
        # Find content start: skip metadata + bracket blocks (multi-line footnotes)
        content_start = start_idx
        in_bracket = False
        for i in range(start_idx, len(lines)):
            stripped = lines[i].strip()
            if stripped.startswith("["):
                in_bracket = True
            if in_bracket:
                if stripped.endswith("]"):
                    in_bracket = False
                continue
            if (stripped
                    and not stripped.isupper()
                    and not any(stripped.startswith(p) for p in (
                        "Title:", "Author:", "eBook", "Project Gutenberg",
                        "Edition:", "Language:", "Character", "Date ", "This eBook",
                        "Copyright", "Production", "Italics", "Accented",
                    ))
                    and len(stripped) > 60):
                content_start = i
                break
        # Footer
        end_idx = len(lines)
        for i in range(len(lines) - 1, content_start, -1):
            stripped = lines[i].strip()
            if stripped in ("THE END", "Project Gutenberg Australia"):
                end_idx = i
                break
        return lines[content_start:end_idx]


def _load_chinese_book(filename: str, format_type: str) -> list[str]:
    """
    Load and parse a Chinese UTF-16 book file.
    format_type: 'bilingual' (达洛维夫人) or 'chinese'
    """
    import re
    path = _RAW_DIR / filename
    text = path.read_text(encoding="utf-16")
    lines = text.splitlines()

    _has_chinese = re.compile(r'[\u4e00-\u9fff]')
    _metadata_keywords = ("ISBN", "出版", "定价", "版权", "印刷", "书号", "策划", "责任编辑",
                           "封面设计", "内容简介", "图书在版", "CIP", "www.", "http")

    if format_type == "bilingual":
        # Filter to only lines with Chinese characters, skip metadata/short lines
        content_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if not _has_chinese.search(stripped):
                continue
            if any(kw in stripped for kw in _metadata_keywords):
                continue
            if len(stripped) <= 15:
                continue
            content_lines.append(stripped)
    else:
        # chinese format: skip header until first long Chinese prose line
        content_start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if not _has_chinese.search(stripped):
                continue
            if any(kw in stripped for kw in _metadata_keywords):
                continue
            if len(stripped) > 30:
                content_start = i
                break
        content_lines = []
        for line in lines[content_start:]:
            stripped = line.strip()
            if not stripped:
                continue
            if any(kw in stripped for kw in _metadata_keywords):
                continue
            content_lines.append(stripped)

    # Split into sentences using Chinese punctuation
    sentences = []
    for line in content_lines:
        parts = re.split(r'(?<=[。！？])\s*', line)
        sentences.extend([s.strip() for s in parts if s.strip()])
    return sentences


def _load_paragraphs(book: str = "daluo_weifuren") -> list[str]:
    if book not in _paragraphs_cache:
        book_info = BOOK_FILES.get(book, BOOK_FILES["daluo_weifuren"])
        filename, encoding, format_type = book_info

        if encoding == "utf-16":
            sentences = _load_chinese_book(filename, format_type)
        else:
            path = _RAW_DIR / filename
            lines = path.read_text(encoding="utf-8").splitlines()
            content_lines = _strip_gutenberg(lines, filename)
            text = "\n".join(content_lines)
            import re
            paras = [p.strip() for p in text.split("\n\n") if p.strip()]
            sentences = []
            for para in paras:
                parts = re.split(r'(?<=[.!?"])\s+', para)
                sentences.extend([s.strip() for s in parts if s.strip()])

        _paragraphs_cache[book] = sentences
    return _paragraphs_cache[book]


@router.get("/text")
def get_text(book: str = "daluo_weifuren"):
    """返回正文段落列表，前端初始化时调一次。支持 ?book= 参数。"""
    if book not in BOOK_FILES:
        book = "daluo_weifuren"
    return {"book": book, "paragraphs": _load_paragraphs(book)}


# ── /suggest：给选中段落生成 3 个建议问题 ────────────────────

class SuggestRequest(BaseModel):
    session_id: str
    passage: str


@router.post("/suggest")
async def suggest_questions(req: SuggestRequest):
    """
    接收选中段落，即时生成 3 个建议问题（无 LLM，避免 thinking 模型延迟）。
    基于段落内容做简单规则匹配，配合 Woolf 主题问题。
    """
    passage = req.passage

    import re
    has_person = bool(re.search(r'[她他我你们]|克拉丽莎|达洛维|伍尔夫|彼得|赛普|雷齐亚', passage))
    has_place  = bool(re.search(r'[街道路公园花园室窗门房]|伦敦|威斯敏|公园', passage))
    has_memory = bool(re.search(r'[曾经记忆往昔]|想起|回忆|从前|那时', passage))
    has_feeling= bool(re.search(r'[感受体验恐惧喜悦痛苦孤独]|情绪|心里|内心', passage))

    q_pool = []
    if has_person:
        q_pool.append("这个人物在想什么？")
    if has_place:
        q_pool.append("这个场景有什么象征意义？")
    if has_memory:
        q_pool.append("这段回忆为何此刻浮现？")
    if has_feeling:
        q_pool.append("伍尔夫如何呈现这种情绪？")

    # 补充通用 Woolf 问题直到凑满 3 个
    universal = [
        "伍尔夫为什么这样写？",
        "这段和女性意识有什么关系？",
        "这里用了什么叙事手法？",
        "这段话的核心意象是什么？",
    ]
    for q in universal:
        if len(q_pool) >= 3:
            break
        if q not in q_pool:
            q_pool.append(q)

    return {"passage": passage, "questions": q_pool[:3]}


# ── /annotated_paragraphs：返回有主动标注的段落索引 ──────────

@router.get("/annotated_paragraphs/{session_id}")
def get_annotated_paragraphs(session_id: str):
    """
    返回知识库中打了 has_proactive_insight=True 的段落 para_idx 列表。
    前端初始化时调一次，之后在这些位置显示主动气泡触发点。
    """
    try:
        from kb_client import get_client
        chroma = get_client()
        col = chroma.get_or_create_collection("woolf_works")
        results = col.get(
            where={"has_proactive_insight": True},
            include=["metadatas"],
        )
        para_ids = [
            m.get("para_idx")
            for m in results["metadatas"]
            if m.get("para_idx") is not None
        ]
    except Exception:
        para_ids = []  # ChromaDB not available, return empty

    return {"para_ids": para_ids}


_sessions: dict[str, WoolfAgent] = {}
# Buffer for proactive pre-generated responses: session_id → {para_idx: text}
_proactive_buffer: dict[str, dict[int, str]] = {}
_proactive_lock = threading.Lock()


def _get_or_create_agent(session_id: str) -> WoolfAgent:
    if session_id not in _sessions:
        _sessions[session_id] = WoolfAgent(session_id=session_id, endpoint="reader")
    return _sessions[session_id]


class ReaderChatRequest(BaseModel):
    session_id: str
    message: str
    highlighted_passage: str | None = None
    para_idx: int | None = None  # Current reading position


@router.post("/chat")
async def chat(req: ReaderChatRequest, background_tasks: BackgroundTasks):
    from fastapi.responses import StreamingResponse

    agent = _get_or_create_agent(req.session_id)

    async def generate():
        async for token in agent.chat_stream(req.message, req.highlighted_passage):
            yield f"data: {json.dumps({'text': token})}\n\n"
        yield "data: [DONE]\n\n"

        if req.para_idx is not None:
            asyncio.create_task(
                _pregenerate_proactive(req.session_id, req.para_idx)
            )

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/proactive/{session_id}/{para_idx}")
def get_proactive(session_id: str, para_idx: int):
    """Fetch pre-generated proactive commentary for a paragraph, if ready."""
    with _proactive_lock:
        text = _proactive_buffer.get(session_id, {}).pop(para_idx, None)
    return {"session_id": session_id, "para_idx": para_idx, "text": text}


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            session_id = payload.get("session_id", "default")
            message = payload.get("message", "")
            highlighted = payload.get("highlighted_passage")
            para_idx = payload.get("para_idx")

            agent = _get_or_create_agent(session_id)
            async for token in agent.chat_stream(message, highlighted):
                await websocket.send_text(json.dumps({"type": "token", "text": token}))
            await websocket.send_text(json.dumps({"type": "done"}))

            # Kick off proactive pre-gen in background
            if para_idx is not None:
                asyncio.create_task(
                    _pregenerate_proactive(session_id, int(para_idx))
                )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except RuntimeError:
            pass  # Socket already closed


async def _pregenerate_proactive(session_id: str, current_para: int, lookahead: int = 3):
    """
    Pre-generate commentary for paragraphs current+1 through current+lookahead.
    Stores results in _proactive_buffer.
    """
    agent = _get_or_create_agent(session_id)
    for offset in range(1, lookahead + 1):
        target_para = current_para + offset
        if session_id not in _proactive_buffer:
            _proactive_buffer[session_id] = {}
        if target_para in _proactive_buffer[session_id]:
            continue  # Already pre-generated

        # Lightweight commentary generation
        tokens = []
        async for token in agent._stream_claude(
            system=f"You are Virginia Woolf. Generate a brief, evocative 1-2 sentence aside "
                   f"that a reader might appreciate when they reach paragraph {target_para}. "
                   f"Quote your own work if relevant. Do not summarize.",
            messages=[{"role": "user", "content": f"Generate commentary for paragraph {target_para}"}],
            use_tools=False,
        ):
            tokens.append(token)
        with _proactive_lock:
            if session_id not in _proactive_buffer:
                _proactive_buffer[session_id] = {}
            if target_para not in _proactive_buffer[session_id]:
                _proactive_buffer[session_id][target_para] = "".join(tokens)
