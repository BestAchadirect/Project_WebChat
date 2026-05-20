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
    TOOL_CHECK_INVENTORY_DB,
    TOOL_GET_PRODUCT_DETAILS,
    TOOL_SEARCH_KNOWLEDGE_BASE,
    TOOL_SEARCH_PRODUCTS,
    agent_system_prompt,
)
from app.services.ai.llm_service import llm_service
from app.services.chat.runtime.grounding import evaluate_catalog_grounding, evaluate_knowledge_grounding
from app.services.chat.runtime.search_plan import SearchPlan
from app.utils.debug_log import debug_log as _debug_log


_SEARCH_PRODUCT_FILTER_KEYS = {
    "min_price",
    "max_price",
    "stock_status",
    "category",
    "body_part",
    "feature",
    "presentation_type",
    "material",
    "jewelry_type",
    "color",
    "theme",
}


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

    @staticmethod
    def _search_plan_tool_guidance(request: AgentRunInput) -> str:
        plan = request.search_plan
        if plan is None:
            return ""
        try:
            payload = plan.to_debug_dict()
        except Exception:
            return ""

        workflow = str(payload.get("workflow") or "").strip().lower()
        sku_tokens = [
            str(item or "").strip()
            for item in list(payload.get("sku_tokens") or [])
            if str(item or "").strip()
        ]
        required_filters = dict(payload.get("required_filters") or {})
        semantic_terms = [
            str(item or "").strip()
            for item in list(payload.get("semantic_terms") or [])
            if str(item or "").strip()
        ]
        knowledge_topics = [
            str(item or "").strip()
            for item in list(payload.get("knowledge_topics") or [])
            if str(item or "").strip()
        ]

        lines = [
            "Tool guidance for this turn:",
            "Use read-only tools before answering supported product, inventory, policy, or FAQ facts.",
        ]
        if workflow in {"catalog", "mixed"}:
            if sku_tokens:
                lines.append(
                    f"- For SKU, product detail, or inventory questions, prefer {TOOL_GET_PRODUCT_DETAILS} "
                    f"or {TOOL_CHECK_INVENTORY_DB} before answering."
                )
            else:
                lines.append(f"- For product browsing or catalog search, call {TOOL_SEARCH_PRODUCTS}.")
            if required_filters:
                filter_hints = ", ".join(
                    f"{key}={value}"
                    for key, value in list(required_filters.items())[:6]
                    if str(key or "").strip() and str(value or "").strip()
                )
                if filter_hints:
                    lines.append(
                        f"- Required product filters from the planner: {filter_hints}. "
                        "Use these exact filter names in search_products filters."
                    )
                    lines.append(
                        "- Do not invent extra product filters. Keep softer descriptive terms in the query text."
                    )
            if semantic_terms:
                hints = ", ".join(semantic_terms[:4])
                if hints:
                    lines.append(f"- Product query terms: {hints}.")
        if workflow in {"knowledge", "mixed"} or knowledge_topics:
            lines.append(
                f"- For policies, FAQ, contact, shipping, returns, payment, or company info, "
                f"call {TOOL_SEARCH_KNOWLEDGE_BASE}."
            )
            if knowledge_topics:
                lines.append(f"- Knowledge search topic: {knowledge_topics[0]}.")
        lines.append("Do not answer supported product or policy facts from memory when a matching tool is available.")
        return "\n".join(lines)

    @staticmethod
    def _append_unique_text(target: List[str], value: Any) -> None:
        text = str(value or "").strip()
        if not text:
            return
        if text.lower() not in {item.lower() for item in target}:
            target.append(text)

    @staticmethod
    def _truncate_tool_text(value: Any, *, limit: int = 200) -> str:
        return str(value or "").strip()[:limit].strip()

    @staticmethod
    def _tool_args_from_search_plan(
        *,
        tool_name: str,
        args: Dict[str, Any],
        request: AgentRunInput,
    ) -> Dict[str, Any]:
        plan = request.search_plan
        normalized = dict(args or {})
        if plan is None:
            return normalized

        if tool_name == TOOL_SEARCH_PRODUCTS:
            required_filters = {
                str(key or "").strip().lower(): str(value or "").strip()
                for key, value in dict(plan.required_filters or {}).items()
                if str(key or "").strip() and str(value or "").strip()
            }
            tool_filters = {
                key: value
                for key, value in required_filters.items()
                if key in _SEARCH_PRODUCT_FILTER_KEYS
            }
            query_terms: List[str] = []
            for value in required_filters.values():
                AgentOrchestrator._append_unique_text(query_terms, value)
            for value in list(plan.semantic_terms or []):
                AgentOrchestrator._append_unique_text(query_terms, value)
            if plan.semantic_query:
                AgentOrchestrator._append_unique_text(query_terms, plan.semantic_query)
            query = " ".join(query_terms) or str(normalized.get("query") or request.user_text or "").strip()
            normalized["query"] = AgentOrchestrator._truncate_tool_text(query)
            if tool_filters:
                normalized["filters"] = tool_filters
            elif not isinstance(normalized.get("filters"), dict):
                normalized.pop("filters", None)
            try:
                normalized["page"] = max(1, int(normalized.get("page") or 1))
            except Exception:
                normalized["page"] = 1
            page_size = normalized.get("pageSize", normalized.get("page_size", 10))
            try:
                normalized["pageSize"] = max(1, min(int(page_size or 10), 20))
            except Exception:
                normalized["pageSize"] = 10
            normalized.pop("page_size", None)
            return normalized

        if tool_name == TOOL_SEARCH_KNOWLEDGE_BASE:
            topic = ""
            for raw_topic in list(plan.knowledge_topics or []):
                topic = str(raw_topic or "").strip()
                if topic:
                    break
            normalized["query"] = AgentOrchestrator._truncate_tool_text(
                topic or normalized.get("query") or request.user_text
            )
            normalized.pop("category", None)
            limit = normalized.get("limit", 5)
            try:
                normalized["limit"] = max(1, min(int(limit or 5), 5))
            except Exception:
                normalized["limit"] = 5
            return normalized

        if tool_name in {TOOL_GET_PRODUCT_DETAILS, TOOL_CHECK_INVENTORY_DB}:
            for sku in list(plan.sku_tokens or []):
                clean_sku = str(sku or "").strip()
                if clean_sku:
                    normalized["sku"] = clean_sku
                    break
            return normalized

        return normalized

    async def _execute_one_tool(self, *, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name not in SUPPORTED_TOOLS:
            return {"error": f"Unsupported tool: {tool_name}"}
        return await asyncio.wait_for(
            self.registry.execute_tool(tool_name, args),
            timeout=self.timeout_seconds,
        )

    async def _execute_tool_call(
        self,
        *,
        tool_name: str,
        args: Dict[str, Any],
        trace: List[Dict[str, Any]],
        products: Dict[str, ProductCard],
        sources: Dict[str, KnowledgeSource],
        selection_source: str,
        arg_error: Any = None,
    ) -> tuple[bool, Dict[str, Any]]:
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
        if selection_source != "llm":
            trace_entry["selection_source"] = selection_source
        trace.append(trace_entry)
        if status == "ok":
            self._merge_tool_artifacts(
                normalized=normalized_result,
                products=products,
                sources=sources,
            )
            return True, result_payload
        return False, result_payload

    @staticmethod
    def _planned_tool_names(request: AgentRunInput) -> List[str]:
        plan = request.search_plan
        if plan is None:
            return []
        try:
            groups = list(plan.expected_tool_groups() or [])
        except Exception:
            groups = []
        selected: List[str] = []
        for raw_group in groups:
            if isinstance(raw_group, (list, tuple, set)):
                group = [
                    str(tool_name or "").strip()
                    for tool_name in list(raw_group or [])
                    if str(tool_name or "").strip()
                ]
            else:
                group = [str(raw_group or "").strip()] if str(raw_group or "").strip() else []
            if not group:
                continue
            if TOOL_SEARCH_PRODUCTS in group:
                tool_name = TOOL_SEARCH_PRODUCTS
            elif TOOL_SEARCH_KNOWLEDGE_BASE in group:
                tool_name = TOOL_SEARCH_KNOWLEDGE_BASE
            else:
                tool_name = group[0]
            if tool_name and tool_name not in selected:
                selected.append(tool_name)
        return selected

    async def _run_search_plan_tool_fallback(
        self,
        *,
        request: AgentRunInput,
        trace: List[Dict[str, Any]],
        products: Dict[str, ProductCard],
        sources: Dict[str, KnowledgeSource],
        model: str,
    ) -> AgentRunResult | None:
        planned_tools = self._planned_tool_names(request)
        if not planned_tools:
            return None

        used_tools = False
        for tool_name in planned_tools:
            if len(trace) >= self.max_calls:
                break
            args = self._tool_args_from_search_plan(
                tool_name=tool_name,
                args={},
                request=request,
            )
            tool_used, _payload = await self._execute_tool_call(
                tool_name=tool_name,
                args=args,
                trace=trace,
                products=products,
                sources=sources,
                selection_source="search_plan_fallback",
            )
            used_tools = used_tools or tool_used

        if not used_tools:
            return AgentRunResult.empty(trace=trace)

        product_values = list(products.values())[: self.max_result_items]
        source_values = list(sources.values())[: self.max_result_items]
        final_text = await self._generate_final_tool_reply(
            request=request,
            products=product_values,
            sources=source_values,
            trace=trace,
            model=model,
        )
        if not final_text:
            return AgentRunResult.empty(trace=trace)
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

    @staticmethod
    async def _generate_final_tool_reply(
        *,
        request: AgentRunInput,
        products: List[ProductCard],
        sources: List[KnowledgeSource],
        trace: List[Dict[str, Any]],
        model: str,
    ) -> str:
        final_messages = [
            {
                "role": "system",
                "content": (
                    "You are a read-only e-commerce assistant. Write a concise, customer-facing answer "
                    "using only the provided tool result summary. Do not invent product, inventory, or policy facts. "
                    "If the summary is insufficient, say what is missing and ask one focused follow-up question. "
                    "Never use em dashes or en dashes."
                ),
            },
            {"role": "user", "content": request.user_text},
            {
                "role": "assistant",
                "content": AgentOrchestrator._tool_artifact_summary(
                    products=products,
                    sources=sources,
                    trace=trace,
                ),
            },
            {
                "role": "user",
                "content": "Answer the original customer question using only that tool result summary.",
            },
        ]
        try:
            generated = str(
                await llm_service.generate_chat_response(
                    messages=final_messages,
                    model=model,
                    temperature=0.0,
                    max_tokens=450,
                    usage_kind="agentic_tool_finalize",
                )
                or ""
            ).strip()
        except Exception:
            generated = ""
        return generated or AgentOrchestrator._deterministic_tool_reply(
            products=products,
            sources=sources,
            trace=trace,
        )

    @staticmethod
    def _deterministic_tool_reply(
        *,
        products: List[ProductCard],
        sources: List[KnowledgeSource],
        trace: List[Dict[str, Any]],
    ) -> str:
        if products:
            names = [
                str(getattr(card, "name", "") or getattr(card, "sku", "") or "").strip()
                for card in list(products or [])[:3]
            ]
            names = [name for name in names if name]
            if names:
                return f"I found {len(products)} matching product(s): {', '.join(names)}. Review the product cards for details."
            return f"I found {len(products)} matching product(s). Review the product cards for details."
        if sources:
            source = sources[0]
            title = str(getattr(source, "title", "") or "the help content").strip()
            snippet = str(getattr(source, "content_snippet", "") or "").strip()
            if snippet:
                return f"Here is what I found in {title}: {snippet[:900]}"
            return f"I found relevant information in {title}, but I need more detail to answer precisely."

        not_found_tools = [
            str(item.get("tool") or "").strip()
            for item in list(trace or [])
            if str(item.get("tool_status") or item.get("status") or "").strip().lower()
            in {"empty", "not_found"}
        ]
        if not_found_tools:
            return ""
        return ""

    @staticmethod
    def _tool_artifact_summary(
        *,
        products: List[ProductCard],
        sources: List[KnowledgeSource],
        trace: List[Dict[str, Any]],
    ) -> str:
        lines = ["Tool result summary:"]
        if products:
            lines.append("Products:")
            for card in list(products or [])[:8]:
                attrs = dict(getattr(card, "attributes", {}) or {})
                attr_text = ", ".join(
                    f"{key}={value}"
                    for key, value in list(attrs.items())[:6]
                    if str(key or "").strip() and str(value or "").strip()
                )
                lines.append(
                    " | ".join(
                        item
                        for item in [
                            f"sku={getattr(card, 'sku', '')}",
                            f"name={getattr(card, 'name', '')}",
                            f"price={getattr(card, 'price', '')} {getattr(card, 'currency', '')}",
                            f"stock={getattr(card, 'stock_status', '')}",
                            f"attributes={attr_text}" if attr_text else "",
                        ]
                        if str(item or "").strip()
                    )
                )
        if sources:
            lines.append("Knowledge sources:")
            for source in list(sources or [])[:6]:
                snippet = str(getattr(source, "content_snippet", "") or "").strip()
                lines.append(
                    " | ".join(
                        item
                        for item in [
                            f"title={getattr(source, 'title', '')}",
                            f"relevance={getattr(source, 'relevance', '')}",
                            f"snippet={snippet[:700]}",
                        ]
                        if str(item or "").strip()
                    )
                )
        if trace:
            lines.append("Tool calls:")
            for item in list(trace or [])[:8]:
                lines.append(
                    " | ".join(
                        part
                        for part in [
                            f"tool={item.get('tool')}",
                            f"status={item.get('tool_status') or item.get('status')}",
                            f"result_count={item.get('result_count')}",
                        ]
                        if str(part or "").strip()
                    )
                )
        if not products and not sources:
            lines.append("No product or knowledge artifacts were returned.")
        return "\n".join(lines)

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
        system_prompt = agent_system_prompt(request.reply_language)
        tool_guidance = self._search_plan_tool_guidance(request)
        if tool_guidance:
            system_prompt = f"{system_prompt}\n{tool_guidance}"
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
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
            try:
                llm_out = await llm_service.generate_chat_with_tools(
                    messages=messages,
                    tools=tool_defs,
                    model=model,
                    temperature=0.0,
                    max_tokens=450,
                    tool_choice="auto",
                    usage_kind="agentic_tool_round",
                )
            except Exception:
                fallback_result = await self._run_search_plan_tool_fallback(
                    request=request,
                    trace=trace,
                    products=products,
                    sources=sources,
                    model=model,
                )
                if fallback_result is not None:
                    return fallback_result
                raise
            assistant_content = str(llm_out.get("content") or "").strip()
            last_assistant_text = assistant_content or last_assistant_text
            tool_calls = list(llm_out.get("tool_calls") or [])

            if not tool_calls:
                if not assistant_content and not used_tools:
                    return AgentRunResult.empty(trace=trace)
                if used_tools:
                    final_reply = assistant_content or last_assistant_text
                    if not final_reply:
                        final_reply = await self._generate_final_tool_reply(
                            request=request,
                            products=list(products.values())[: self.max_result_items],
                            sources=list(sources.values())[: self.max_result_items],
                            trace=trace,
                            model=model,
                        )
                    product_values = list(products.values())[: self.max_result_items]
                    source_values = list(sources.values())[: self.max_result_items]
                    grounding = self._ground_agent_artifacts(
                        request=request,
                        products=product_values,
                        sources=source_values,
                        final_reply=final_reply,
                    )
                    return AgentRunResult.tool_success(
                        final_reply=final_reply,
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
                args = self._tool_args_from_search_plan(
                    tool_name=tool_name,
                    args=args,
                    request=request,
                )
                arg_error = call.get("argument_error")
                tool_used, result_payload = await self._execute_tool_call(
                    tool_name=tool_name,
                    args=args,
                    trace=trace,
                    products=products,
                    sources=sources,
                    selection_source="llm",
                    arg_error=arg_error,
                )
                if tool_used:
                    used_tools = True

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

        final_text = await self._generate_final_tool_reply(
            request=request,
            products=list(products.values())[: self.max_result_items],
            sources=list(sources.values())[: self.max_result_items],
            trace=trace,
            model=model,
        )
        final_text = final_text or last_assistant_text
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

