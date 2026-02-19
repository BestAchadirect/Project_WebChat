from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.schemas.chat import KnowledgeSource, ProductCard
from app.services.agent_tools import SUPPORTED_TOOLS, AgentToolRegistry, agent_system_prompt
from app.services.llm_service import llm_service
from app.utils.debug_log import debug_log as _debug_log


@dataclass
class AgentRunResult:
    final_reply: str
    used_tools: bool
    product_carousel: List[ProductCard] = field(default_factory=list)
    sources: List[KnowledgeSource] = field(default_factory=list)
    follow_up_questions: List[str] = field(default_factory=list)
    carousel_msg: str = ""
    trace: List[Dict[str, Any]] = field(default_factory=list)


class AgentOrchestrator:
    def __init__(self, *, db, run_id: str, channel: str):
        self.db = db
        self.run_id = run_id
        self.channel = channel
        self.registry = AgentToolRegistry(db, run_id=run_id)
        self.max_rounds = max(1, int(getattr(settings, "AGENTIC_MAX_TOOL_ROUNDS", 4)))
        self.max_calls = max(1, int(getattr(settings, "AGENTIC_MAX_TOOL_CALLS", 6)))
        self.timeout_seconds = max(0.1, int(getattr(settings, "AGENTIC_TOOL_TIMEOUT_MS", 3500)) / 1000.0)
        self.max_result_items = max(1, int(getattr(settings, "AGENTIC_MAX_TOOL_RESULT_ITEMS", 10)))

    @staticmethod
    def _sanitize_for_trace(value: Any, *, depth: int = 2, max_str: int = 200) -> Any:
        if depth <= 0:
            if isinstance(value, str):
                return value[:max_str]
            return value
        if isinstance(value, dict):
            output: Dict[str, Any] = {}
            for key, item in value.items():
                output[str(key)] = AgentOrchestrator._sanitize_for_trace(
                    item,
                    depth=depth - 1,
                    max_str=max_str,
                )
            return output
        if isinstance(value, list):
            return [
                AgentOrchestrator._sanitize_for_trace(item, depth=depth - 1, max_str=max_str)
                for item in value[:10]
            ]
        if isinstance(value, str):
            return value[:max_str]
        return value

    @staticmethod
    def _result_count(value: Any) -> int:
        if isinstance(value, dict):
            items = value.get("items")
            if isinstance(items, list):
                return len(items)
            if value.get("found") is True:
                return 1
            return 0
        if isinstance(value, list):
            return len(value)
        return 0

    def _log_tool_event(self, *, tool_name: str, args: Dict[str, Any], status: str, duration_ms: int, result_count: int) -> None:
        _debug_log(
            {
                "sessionId": "debug-session",
                "runId": self.run_id,
                "hypothesisId": "AGENT",
                "location": "agent_orchestrator.tool_call",
                "message": "tool call",
                "data": {
                    "tool": tool_name,
                    "args": self._sanitize_for_trace(args),
                    "status": status,
                    "duration_ms": duration_ms,
                    "result_count": result_count,
                    "channel": self.channel,
                },
                "timestamp": int(time.time() * 1000),
            }
        )

    def _collect_products(self, tool_name: str, result: Dict[str, Any], products: Dict[str, ProductCard]) -> None:
        try:
            if tool_name == "search_products":
                items = result.get("items")
                if not isinstance(items, list):
                    return
                for item in items:
                    card = ProductCard.model_validate(item)
                    products[str(card.id)] = card
                return
            if tool_name == "get_product_details" and result.get("found"):
                payload = result.get("product")
                if not isinstance(payload, dict):
                    return
                card = ProductCard.model_validate(payload)
                products[str(card.id)] = card
        except Exception:
            return

    def _collect_sources(self, tool_name: str, result: Dict[str, Any], sources: Dict[str, KnowledgeSource]) -> None:
        if tool_name != "search_knowledge_base":
            return
        items = result.get("items")
        if not isinstance(items, list):
            return
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or f"kb_{index}")
            if source_id in sources:
                continue
            try:
                source = KnowledgeSource(
                    source_id=source_id,
                    title=str(item.get("title") or "Knowledge"),
                    content_snippet=str(item.get("snippet") or ""),
                    category=item.get("category"),
                    relevance=float(item.get("relevance") or 0.0),
                    url=item.get("url"),
                    distance=None,
                )
                sources[source_id] = source
            except Exception:
                continue

    async def _execute_one_tool(self, *, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name not in SUPPORTED_TOOLS:
            return {"error": f"Unsupported tool: {tool_name}"}
        return await asyncio.wait_for(
            self.registry.execute_tool(tool_name, args),
            timeout=self.timeout_seconds,
        )

    async def run(
        self,
        *,
        user_text: str,
        history: List[Dict[str, Any]],
        reply_language: str,
    ) -> Optional[AgentRunResult]:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": agent_system_prompt(reply_language)}
        ]
        for entry in history[-6:]:
            role = str(entry.get("role") or "").strip().lower()
            content = str(entry.get("content") or "").strip()
            if role not in {"user", "assistant", "system"} or not content:
                continue
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})

        tool_defs = self.registry.tool_definitions()
        model = str(getattr(settings, "AGENTIC_MODEL", "") or "").strip()
        if not model:
            model = str(getattr(settings, "RAG_ANSWER_MODEL", "") or settings.OPENAI_MODEL)

        used_tools = False
        tool_calls_total = 0
        last_assistant_text = ""
        trace: List[Dict[str, Any]] = []
        products: Dict[str, ProductCard] = {}
        sources: Dict[str, KnowledgeSource] = {}

        for round_index in range(self.max_rounds):
            llm_out = await llm_service.generate_chat_with_tools(
                messages=messages,
                tools=tool_defs,
                model=model,
                temperature=0.0,
                max_tokens=450,
                tool_choice="auto",
                usage_kind="agentic_tool_round",
            )
            assistant_content = str(llm_out.get("content") or "").strip()
            last_assistant_text = assistant_content or last_assistant_text
            tool_calls = list(llm_out.get("tool_calls") or [])

            if not tool_calls:
                if not assistant_content and not used_tools:
                    return None
                return AgentRunResult(
                    final_reply=assistant_content or last_assistant_text,
                    used_tools=used_tools,
                    product_carousel=list(products.values())[: self.max_result_items],
                    sources=list(sources.values())[: self.max_result_items],
                    trace=trace,
                )

            if tool_calls_total >= self.max_calls:
                break

            assistant_tool_calls = []
            for call in tool_calls:
                if tool_calls_total >= self.max_calls:
                    break
                call_id = str(call.get("id") or f"call_{round_index}_{tool_calls_total}")
                raw_arguments = str(call.get("raw_arguments") or "{}")
                tool_name = str(call.get("name") or "")
                assistant_tool_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": raw_arguments,
                        },
                    }
                )
                tool_calls_total += 1

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_content or "",
                    "tool_calls": assistant_tool_calls,
                }
            )

            for call in tool_calls:
                if len(trace) >= self.max_calls:
                    break
                call_id = str(call.get("id") or f"call_{round_index}_{len(trace)}")
                tool_name = str(call.get("name") or "")
                args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
                arg_error = call.get("argument_error")

                started = time.monotonic()
                status = "ok"
                result_payload: Dict[str, Any]
                if arg_error:
                    status = "invalid_arguments"
                    result_payload = {"error": f"Invalid arguments: {arg_error}"}
                else:
                    try:
                        result_payload = await self._execute_one_tool(tool_name=tool_name, args=args)
                    except asyncio.TimeoutError:
                        status = "timeout"
                        result_payload = {"error": f"Tool timeout for {tool_name}"}
                    except Exception as exc:
                        status = "error"
                        result_payload = {"error": str(exc)}
                    else:
                        if "error" in result_payload:
                            status = "error"

                duration_ms = int((time.monotonic() - started) * 1000)
                count = self._result_count(result_payload)
                self._log_tool_event(
                    tool_name=tool_name,
                    args=args,
                    status=status,
                    duration_ms=duration_ms,
                    result_count=count,
                )

                trace_entry = {
                    "tool": tool_name,
                    "status": status,
                    "duration_ms": duration_ms,
                    "result_count": count,
                    "args": self._sanitize_for_trace(args),
                }
                trace.append(trace_entry)
                if status == "ok":
                    used_tools = True
                    self._collect_products(tool_name, result_payload, products)
                    self._collect_sources(tool_name, result_payload, sources)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": json.dumps(result_payload, ensure_ascii=True),
                    }
                )

        if not used_tools:
            return None

        final_out = await llm_service.generate_chat_with_tools(
            messages=messages,
            tools=tool_defs,
            model=model,
            temperature=0.0,
            max_tokens=450,
            tool_choice="none",
            usage_kind="agentic_tool_finalize",
        )
        final_text = str(final_out.get("content") or "").strip() or last_assistant_text
        if not final_text:
            return None
        return AgentRunResult(
            final_reply=final_text,
            used_tools=True,
            product_carousel=list(products.values())[: self.max_result_items],
            sources=list(sources.values())[: self.max_result_items],
            trace=trace,
        )

