from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.schemas.chat import KnowledgeSource, ProductCard
from app.services.chat.agentic.tool_registry import (
    SUPPORTED_TOOLS,
    AgentToolRegistry,
    NormalizedAgentToolResult,
    agent_system_prompt,
)
from app.services.ai.llm_service import llm_service
from app.services.chat.runtime.grounding import evaluate_catalog_grounding, evaluate_knowledge_grounding
from app.services.chat.runtime.search_plan import SearchPlan
from app.utils.debug_log import debug_log as _debug_log


class AgentRunOutcome(str, Enum):
    TOOL_SUCCESS = "tool_success"
    NO_TOOL_ANSWER = "no_tool_answer"
    EMPTY = "empty"


@dataclass
class AgentRunInput:
    user_text: str
    history: List[Dict[str, Any]] = field(default_factory=list)
    reply_language: str = "en-US"
    channel: str = ""
    run_id: str = ""
    search_plan: Optional[SearchPlan] = None


@dataclass
class AgentRunResult:
    final_reply: str = ""
    used_tools: bool = False
    product_carousel: List[ProductCard] = field(default_factory=list)
    sources: List[KnowledgeSource] = field(default_factory=list)
    follow_up_questions: List[str] = field(default_factory=list)
    carousel_msg: str = ""
    trace: List[Dict[str, Any]] = field(default_factory=list)
    grounding: Dict[str, Any] = field(default_factory=dict)
    outcome: AgentRunOutcome | str = ""
    fallback_reason: str = ""

    def __post_init__(self) -> None:
        final_reply = str(self.final_reply or "").strip()
        outcome_value = getattr(self.outcome, "value", self.outcome)
        if not outcome_value:
            if self.used_tools:
                self.outcome = AgentRunOutcome.TOOL_SUCCESS
            elif final_reply:
                self.outcome = AgentRunOutcome.NO_TOOL_ANSWER
            else:
                self.outcome = AgentRunOutcome.EMPTY
        else:
            self.outcome = AgentRunOutcome(str(outcome_value))
        if not self.fallback_reason:
            if self.outcome == AgentRunOutcome.NO_TOOL_ANSWER:
                self.fallback_reason = "no_tool_usage"
            elif self.outcome == AgentRunOutcome.EMPTY:
                self.fallback_reason = "empty_result"

    @classmethod
    def tool_success(
        cls,
        *,
        final_reply: str,
        product_carousel: Optional[List[ProductCard]] = None,
        sources: Optional[List[KnowledgeSource]] = None,
        follow_up_questions: Optional[List[str]] = None,
        carousel_msg: str = "",
        trace: Optional[List[Dict[str, Any]]] = None,
        grounding: Optional[Dict[str, Any]] = None,
    ) -> "AgentRunResult":
        return cls(
            final_reply=final_reply,
            used_tools=True,
            product_carousel=list(product_carousel or []),
            sources=list(sources or []),
            follow_up_questions=list(follow_up_questions or []),
            carousel_msg=carousel_msg,
            trace=list(trace or []),
            grounding=dict(grounding or {}),
            outcome=AgentRunOutcome.TOOL_SUCCESS,
            fallback_reason="",
        )

    @classmethod
    def no_tool_answer(
        cls,
        *,
        final_reply: str,
        trace: Optional[List[Dict[str, Any]]] = None,
        grounding: Optional[Dict[str, Any]] = None,
    ) -> "AgentRunResult":
        return cls(
            final_reply=final_reply,
            used_tools=False,
            trace=list(trace or []),
            grounding=dict(grounding or {}),
            outcome=AgentRunOutcome.NO_TOOL_ANSWER,
            fallback_reason="no_tool_usage",
        )

    @classmethod
    def empty(
        cls,
        *,
        trace: Optional[List[Dict[str, Any]]] = None,
        grounding: Optional[Dict[str, Any]] = None,
    ) -> "AgentRunResult":
        return cls(
            final_reply="",
            used_tools=False,
            trace=list(trace or []),
            grounding=dict(grounding or {}),
            outcome=AgentRunOutcome.EMPTY,
            fallback_reason="empty_result",
        )


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

    @staticmethod
    def _merge_tool_artifacts(
        *,
        normalized: NormalizedAgentToolResult,
        products: Dict[str, ProductCard],
        sources: Dict[str, KnowledgeSource],
    ) -> None:
        for card in list(normalized.products or []):
            products[str(card.id)] = card
        for source in list(normalized.sources or []):
            source_id = str(source.source_id or "").strip()
            if source_id and source_id not in sources:
                sources[source_id] = source

    @staticmethod
    def _ground_agent_artifacts(
        *,
        request: AgentRunInput,
        products: List[ProductCard],
        sources: List[KnowledgeSource],
        final_reply: str,
    ) -> Dict[str, Any]:
        plan = request.search_plan
        if plan is None:
            return {}
        payload: Dict[str, Any] = {"search_plan": plan.to_debug_dict()}
        if products:
            catalog_decision = evaluate_catalog_grounding(
                plan=plan,
                products=products,
            )
            payload["catalog"] = catalog_decision.to_debug_dict()
        if sources:
            knowledge_decision = evaluate_knowledge_grounding(
                plan=plan,
                sources=sources,
                answer=final_reply,
                min_relevance=float(getattr(settings, "CHAT_KNOWLEDGE_MIN_RELEVANCE", 0.55)),
            )
            payload["knowledge"] = knowledge_decision.to_debug_dict()
        if not products and not sources:
            payload["status"] = "weak"
            payload["safe_customer_action"] = "fallback"
            payload["reasons"] = ["agentic_no_artifacts"]
        return payload

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
        request: Optional[AgentRunInput] = None,
        user_text: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        reply_language: str = "en-US",
    ) -> AgentRunResult:
        request = request or AgentRunInput(
            user_text=user_text,
            history=list(history or []),
            reply_language=reply_language,
            channel=self.channel,
            run_id=self.run_id,
        )
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": agent_system_prompt(request.reply_language)}
        ]
        for entry in request.history[-6:]:
            role = str(entry.get("role") or "").strip().lower()
            content = str(entry.get("content") or "").strip()
            if role not in {"user", "assistant", "system"} or not content:
                continue
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": request.user_text})

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
                    return AgentRunResult.empty(trace=trace)
                if used_tools:
                    product_values = list(products.values())[: self.max_result_items]
                    source_values = list(sources.values())[: self.max_result_items]
                    grounding = self._ground_agent_artifacts(
                        request=request,
                        products=product_values,
                        sources=source_values,
                        final_reply=assistant_content or last_assistant_text,
                    )
                    return AgentRunResult.tool_success(
                        final_reply=assistant_content or last_assistant_text,
                        product_carousel=product_values,
                        sources=source_values,
                        trace=trace,
                        grounding=grounding,
                    )
                return AgentRunResult.no_tool_answer(
                    final_reply=assistant_content or last_assistant_text,
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
                normalized_result = self.registry.normalize_tool_result(
                    tool_name=tool_name,
                    result=result_payload,
                )
                count = int(normalized_result.result_count)
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
                    "tool_status": str(normalized_result.status or ""),
                    "duration_ms": duration_ms,
                    "result_count": count,
                    "args": self._sanitize_for_trace(args),
                }
                trace.append(trace_entry)
                if status == "ok":
                    used_tools = True
                    self._merge_tool_artifacts(
                        normalized=normalized_result,
                        products=products,
                        sources=sources,
                    )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": json.dumps(result_payload, ensure_ascii=True),
                    }
                )

        if not used_tools:
            return AgentRunResult.empty(trace=trace)

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
            return AgentRunResult.empty(trace=trace)
        product_values = list(products.values())[: self.max_result_items]
        source_values = list(sources.values())[: self.max_result_items]
        grounding = self._ground_agent_artifacts(
            request=request,
            products=product_values,
            sources=source_values,
            final_reply=final_text,
        )
        return AgentRunResult.tool_success(
            final_reply=final_text,
            product_carousel=product_values,
            sources=source_values,
            trace=trace,
            grounding=grounding,
        )

