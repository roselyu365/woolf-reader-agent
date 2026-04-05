"""
agent.py
Main ReAct agent loop with Zhipu AI (OpenAI-compatible) tool_use.
Supports async streaming via async generator.
"""

import os
import json
import asyncio
import openai
from typing import AsyncGenerator

from tools import TOOLS, TOOLS_OPENAI, execute_tool
from persona import build_system_prompt, should_auto_summarize, auto_summarize
from scenarios import detect_scenario, Scenario
from dialogue_state import DiscoveryState, DialogueComplete

ZHIPU_BASE = os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
ZHIPU_KEY = os.getenv("ZHIPU_API_KEY")
MODEL_FAST = os.getenv("ZHIPU_MODEL_FAST", "glm-4-flash")
MODEL_MAIN = os.getenv("ZHIPU_MODEL_MAIN", "glm-4-plus")

MAX_TOOL_ROUNDS = 10  # Safety limit: allows up to 10 tool-use rounds per request


class WoolfAgent:
    def __init__(self, session_id: str, endpoint: str = "mobile"):
        self.session_id = session_id
        self.endpoint = endpoint
        self.client = openai.OpenAI(api_key=ZHIPU_KEY, base_url=ZHIPU_BASE)
        self.async_client = openai.AsyncOpenAI(api_key=ZHIPU_KEY, base_url=ZHIPU_BASE)
        self.messages: list[dict] = []
        self.cited_ids: set = set()
        self.round_count: int = 0
        self.discovery_state = DiscoveryState(session_id=session_id)
        self._is_new_session = True

    def _session_state(self) -> dict:
        return {
            "is_new": self._is_new_session,
            "has_reading_history": self.round_count > 0,
        }

    async def chat_stream(
        self,
        user_message: str,
        highlighted_passage: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Process a user message and yield text tokens as they stream.
        Handles scenario detection, tool loops, and auto-summary.
        """
        self._is_new_session = self.round_count == 0
        self.round_count += 1

        # Auto-summarize every 5 rounds
        if should_auto_summarize(self.round_count) and len(self.messages) > 0:
            auto_summarize(self.messages, self.session_id, self.endpoint)

        scenario = detect_scenario(
            message=user_message,
            session_state=self._session_state(),
            discovery_round=self.discovery_state.round,
            highlighted_passage=highlighted_passage,
        )

        if scenario == Scenario.DISCOVERY:
            async for token in self._run_discovery(user_message):
                yield token
        elif scenario == Scenario.ANNOTATION:
            async for token in self._run_annotation(user_message, highlighted_passage):
                yield token
        elif scenario == Scenario.THEMATIC:
            async for token in self._run_thematic(user_message):
                yield token
        else:
            async for token in self._run_react(user_message):
                yield token

    async def _run_discovery(self, user_message: str) -> AsyncGenerator[str, None]:
        """5-round discovery dialogue state machine."""
        state = self.discovery_state

        # Record user's answer if we're in an active round
        if state.is_active() and user_message.strip():
            state.record_answer(user_message)

        # Get next question or synthesis
        try:
            next_q = state.get_next_question()
        except DialogueComplete:
            # Discovery complete — fall through to ReAct
            async for token in self._run_react(user_message):
                yield token
            return

        system = build_system_prompt(self.session_id, self.endpoint)

        if next_q == "__synthesis__":
            # Round 5: synthesize with Zhipu
            synthesis_prompt = state.get_synthesis_prompt()
            async for token in self._stream_claude(
                system=system,
                messages=[{"role": "user", "content": synthesis_prompt}],
                use_tools=False,
            ):
                yield token
        else:
            # Rounds 1-4: LLM generates natural response + transition to next theme
            if state.round == 1:
                discovery_prompt = (
                    f"读者刚刚打开阅读应用，说：「{user_message}」\n\n"
                    f"请用你的声音自然开口，简短回应他们，然后引出这个话题：{next_q}\n"
                    f"不超过3-4句话。直接开口，不要任何开场白。"
                )
            else:
                discovery_prompt = (
                    f"读者刚才说：「{user_message}」\n\n"
                    f"先真诚回应他们说的（1-2句），然后自然过渡，引出下一个话题：{next_q}\n"
                    f"不超过3-4句话。过渡要自然，像真实对话，不像问卷。"
                )
            async for token in self._stream_claude(
                system=system,
                messages=[{"role": "user", "content": discovery_prompt}],
                use_tools=False,
                model=MODEL_FAST,
            ):
                yield token

    async def _run_react(self, user_message: str) -> AsyncGenerator[str, None]:
        """Standard ReAct loop: Reason → Act (tools) → Observe → repeat.
        First pass uses streaming for low latency; tool-call rounds use sync."""
        system = build_system_prompt(self.session_id, self.endpoint)
        self.messages.append({"role": "user", "content": user_message})

        tool_rounds = 0
        current_messages = self.messages.copy()

        while tool_rounds < MAX_TOOL_ROUNDS:
            if tool_rounds == 0:
                # First pass: streaming for immediate first token
                stream = await self.async_client.chat.completions.create(
                    model=MODEL_MAIN,
                    max_tokens=4000,
                    messages=[{"role": "system", "content": system}] + current_messages,
                    tools=TOOLS_OPENAI,
                    tool_choice="auto",
                    stream=True,
                )
                content_chunks: list[str] = []
                tool_call_chunks: dict = {}  # index → {id, name, arguments}
                finish_reason = None

                async for chunk in stream:
                    choice = chunk.choices[0]
                    finish_reason = choice.finish_reason or finish_reason
                    delta = choice.delta

                    if delta.content:
                        content_chunks.append(delta.content)
                        yield delta.content

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_call_chunks:
                                tool_call_chunks[idx] = {"id": tc.id or "", "name": "", "arguments": ""}
                            if tc.id:
                                tool_call_chunks[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_call_chunks[idx]["name"] += tc.function.name
                                if tc.function.arguments:
                                    tool_call_chunks[idx]["arguments"] += tc.function.arguments

                text_so_far = "".join(content_chunks)
                assembled_tool_calls = list(tool_call_chunks.values())

            else:
                # Subsequent passes (after tool use): sync call, no streaming needed
                resp = await asyncio.to_thread(
                    self.client.chat.completions.create,
                    model=MODEL_MAIN,
                    max_tokens=4000,
                    messages=[{"role": "system", "content": system}] + current_messages,
                    tools=TOOLS_OPENAI,
                    tool_choice="auto",
                )
                choice = resp.choices[0]
                finish_reason = choice.finish_reason
                msg = choice.message
                text_so_far = msg.content or ""
                assembled_tool_calls = [
                    {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                    for tc in (msg.tool_calls or [])
                ]

            # Build assistant message for history
            assistant_msg: dict = {"role": "assistant"}
            if assembled_tool_calls:
                assistant_msg["tool_calls"] = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in assembled_tool_calls
                ]
            if text_so_far:
                assistant_msg["content"] = text_so_far
            current_messages.append(assistant_msg)

            if not assembled_tool_calls:
                # Final answer (streaming already yielded it on first pass)
                self.messages.append({"role": "assistant", "content": text_so_far})
                if tool_rounds > 0:
                    # Only yield here for post-tool passes (first pass already streamed)
                    for char in text_so_far:
                        yield char
                break

            # Execute tool calls
            for tc in assembled_tool_calls:
                try:
                    tool_input = json.loads(tc["arguments"])
                except json.JSONDecodeError:
                    tool_input = {}
                result = execute_tool(tc["name"], tool_input, self.cited_ids)
                current_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
            tool_rounds += 1

        else:
            yield "\n\n[已达最大推理轮次]"

    async def _run_annotation(
        self, user_message: str, passage: str
    ) -> AsyncGenerator[str, None]:
        """Annotation: fast local retrieval (no stepback) + streaming.
        Falls back to passage-only if retrieval fails."""
        system = build_system_prompt(self.session_id, self.endpoint)

        # Fast local retrieval — skip stepback (no API call, pure ChromaDB)
        kb_context = ""
        try:
            results = await asyncio.to_thread(
                execute_tool,
                "retrieve_knowledge",
                {"query": user_message, "collections": ["all"], "top_k": 4,
                 "use_stepback": False},
                self.cited_ids,
            )
            kb_context = results
        except Exception:
            pass  # degrade gracefully: answer from passage only

        if kb_context:
            annotation_prompt = (
                f"读者选中了这段文字：\n\n「{passage}」\n\n"
                f"读者的问题：{user_message}\n\n"
                f"相关知识库内容（可引用）：\n{kb_context}\n\n"
                "以Virginia Woolf的口吻直接作答，紧扣选段，结合知识库内容，2-3句。"
                "禁止以'好的'、'当然'、'让我'、'这段'、'关于'等词开头。"
                "第一个字就是你的回答本身。"
            )
        else:
            annotation_prompt = (
                f"读者选中了这段文字：\n\n「{passage}」\n\n"
                f"读者的问题：{user_message}\n\n"
                "以Virginia Woolf的口吻直接作答，紧扣选段，2-3句。"
                "禁止以'好的'、'当然'、'让我'、'这段'、'关于'等词开头。"
                "第一个字就是你的回答本身。"
            )
        async for token in self._stream_claude(
            system=system,
            messages=[{"role": "user", "content": annotation_prompt}],
            use_tools=False,
            model=MODEL_FAST,
        ):
            yield token

    async def _run_thematic(self, user_message: str) -> AsyncGenerator[str, None]:
        """Plan-and-Execute for thematic exploration questions."""
        system = build_system_prompt(self.session_id, self.endpoint)
        plan_prompt = (
            f"Question: {user_message}\n\n"
            "Before answering, briefly identify 3 specific sub-questions that together "
            "would fully answer this. List them as: Q1: ... Q2: ... Q3: ..."
        )
        plan_resp = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=MODEL_MAIN,
            max_tokens=2000,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": plan_prompt},
            ],
        )
        plan_text = plan_resp.choices[0].message.content or ""

        # Execute — retrieve for each sub-question
        sub_contexts = []
        for line in plan_text.split("\n"):
            for prefix in ["Q1:", "Q2:", "Q3:"]:
                if line.startswith(prefix):
                    q = line[len(prefix):].strip()
                    ctx = execute_tool(
                        "retrieve_knowledge",
                        {"query": q, "collections": ["all"], "top_k": 3},
                        self.cited_ids,
                    )
                    sub_contexts.append(f"**{q}**\n{ctx}")

        if not sub_contexts:
            # Plan didn't follow Q1/Q2/Q3 format — fall back to ReAct
            async for token in self._run_react(user_message):
                yield token
            return

        # Synthesize
        synthesis_prompt = (
            f"Question: {user_message}\n\n"
            "Retrieved knowledge:\n\n" + "\n\n---\n\n".join(sub_contexts) + "\n\n"
            "Now answer the question as Virginia Woolf, weaving together the evidence "
            "from different sources. Show the connections."
        )
        async for token in self._stream_claude(
            system=system,
            messages=[{"role": "user", "content": synthesis_prompt}],
            use_tools=False,
        ):
            yield token

    async def _stream_claude(
        self,
        system: str,
        messages: list[dict],
        use_tools: bool = False,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """流式输出 — 使用 AsyncOpenAI streaming API，首 token 即时返回。"""
        kwargs: dict = dict(
            model=model or MODEL_MAIN,
            max_tokens=4000,
            messages=[{"role": "system", "content": system}] + messages,
            stream=True,
        )
        if use_tools:
            kwargs["tools"] = TOOLS_OPENAI
            kwargs["tool_choice"] = "auto"

        stream = await self.async_client.chat.completions.create(**kwargs)
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
