from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _json_safe(value.model_dump(mode="json"))
        except Exception:
            return str(value)
    return str(value)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _nested_text(payload: dict[str, Any], *keys: str) -> str:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return _clean_text(current)


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    clean: list[str] = []
    for item in list(value or []):
        text = _clean_text(item)
        if text:
            clean.append(text)
    return clean


def _clean_string_groups(value: Any) -> list[list[str]]:
    if not isinstance(value, (list, tuple)):
        return []
    groups: list[list[str]] = []
    for item in list(value or []):
        group = _clean_string_list(item)
        if group:
            groups.append(group)
    return groups


@dataclass
class HarnessTrace:
    run_id: str
    conversation_id: str | None = None
    user_id: str | None = None
    user_message: str | None = None

    intent: str | None = None
    route: str | None = None
    workflow: str | None = None
    execution_mode: str | None = None

    tools_called: list[str] = field(default_factory=list)
    retrieved_products: int = 0
    retrieved_sources: int = 0

    grounding_status: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None

    clarification_required: bool = False
    clarification_reason: str | None = None

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    timings_ms: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_tool_call(self, name: str) -> None:
        tool_name = _clean_text(name)
        if tool_name and tool_name not in self.tools_called:
            self.tools_called.append(tool_name)

    def add_error(self, message: str) -> None:
        error = _clean_text(message)
        if error and error not in self.errors:
            self.errors.append(error)

    def add_warning(self, message: str) -> None:
        warning = _clean_text(message)
        if warning and warning not in self.warnings:
            self.warnings.append(warning)

    def set_timing(self, step: str, ms: float) -> None:
        clean_step = _clean_text(step)
        if not clean_step:
            return
        try:
            elapsed = max(0.0, float(ms or 0.0))
        except (TypeError, ValueError):
            elapsed = 0.0
        self.timings_ms[clean_step] = round(elapsed, 3)

    def update_from_debug(self, debug: dict[str, Any] | None) -> None:
        if not isinstance(debug, dict):
            return

        self.run_id = _first_text(debug.get("run_id"), self.run_id)
        routing = debug.get("routing") if isinstance(debug.get("routing"), dict) else {}
        routing_snapshot = (
            debug.get("routing_snapshot") if isinstance(debug.get("routing_snapshot"), dict) else {}
        )
        decision_state = debug.get("decision_state") if isinstance(debug.get("decision_state"), dict) else {}

        route = _first_text(
            debug.get("workflow"),
            routing.get("workflow"),
            routing_snapshot.get("workflow"),
            self.route,
        )
        if route:
            self.route = route

        workflow = _first_text(
            debug.get("internal_workflow"),
            decision_state.get("internal_workflow"),
            debug.get("understanding_workflow_hypothesis"),
            self.workflow,
        )
        if workflow:
            self.workflow = workflow

        intent = _first_text(
            debug.get("understanding_intent"),
            decision_state.get("intent"),
            self.intent,
        )
        if intent:
            self.intent = intent

        agentic = debug.get("agentic") if isinstance(debug.get("agentic"), dict) else {}
        fallback_used = bool(
            agentic.get("fallback_to_component")
            or debug.get("runtime_failure_reason")
            or debug.get("clarification_loop_fallback_used")
            or _clean_text(debug.get("component_mode")).lower() == "error"
            or _clean_text(route).lower() == "fallback"
        )
        if fallback_used:
            self.fallback_used = True
            self.execution_mode = "fallback"
        else:
            execution_mode = _first_text(
                debug.get("execution_mode"),
                routing.get("execution_mode"),
                routing_snapshot.get("execution_mode"),
                self.execution_mode,
            )
            if execution_mode:
                self.execution_mode = execution_mode

        fallback_reason = _first_text(
            agentic.get("fallback_reason"),
            agentic.get("failure_reason"),
            debug.get("runtime_failure_reason"),
            debug.get("routing_failure_reason"),
            debug.get("component_pipeline_error"),
            self.fallback_reason,
        )
        if fallback_reason:
            self.fallback_reason = fallback_reason

        clarification_required = bool(
            debug.get("workflow_needs_clarification")
            or routing.get("needs_clarification")
            or debug.get("clarify_reason")
            or debug.get("clarify_message")
            or debug.get("clarify_questions")
        )
        if clarification_required:
            self.clarification_required = True
            clarification_reason = _first_text(
                debug.get("clarify_reason"),
                decision_state.get("missing_slot"),
                debug.get("understanding_missing_slot"),
                self.clarification_reason,
            )
            if clarification_reason:
                self.clarification_reason = clarification_reason

        grounding_status = _first_text(
            debug.get("grounding_status"),
            debug.get("knowledge_grounding_status"),
            debug.get("mixed_intent_knowledge_grounding_status"),
            _nested_text(agentic, "grounding", "catalog", "status"),
            _nested_text(agentic, "grounding", "knowledge", "status"),
            _nested_text(agentic, "grounding", "status"),
            self.grounding_status,
        )
        if grounding_status:
            self.grounding_status = grounding_status

        self.retrieved_products = max(
            self.retrieved_products,
            _coerce_int(debug.get("product_result_count")),
            len(list(debug.get("catalog_query_product_ids") or []))
            if isinstance(debug.get("catalog_query_product_ids"), list)
            else 0,
            _coerce_int(debug.get("grounding_filtered_product_count")),
        )
        self.retrieved_sources = max(
            self.retrieved_sources,
            _coerce_int(debug.get("knowledge_source_count_after_selector")),
            _coerce_int(debug.get("company_info_source_count_after_selector")),
            _coerce_int(debug.get("knowledge_source_count_before_selector")),
            _coerce_int(debug.get("company_info_source_count_before_selector")),
        )

        self._set_tool_events(agentic.get("trace") if isinstance(agentic.get("trace"), list) else [])

        for key in ("agentic_error", "component_pipeline_error", "latency_error"):
            value = _clean_text(debug.get(key))
            if value:
                self.add_error(value)
        for key in (
            "alias_cache_error",
            "parser_rule_cache_error",
            "catalog_searchable_attribute_error",
            "conversation_existing_attribute_filter_error",
        ):
            value = _clean_text(debug.get(key))
            if value:
                self.add_warning(f"{key}: {value}")

        for key in (
            "workflow_path",
            "component_mode",
            "component_source",
            "routing_selection_source",
            "grounding_safe_action",
            "knowledge_grounding_safe_action",
        ):
            value = debug.get(key)
            if value not in (None, ""):
                self.metadata[key] = value
        if agentic:
            selection_blockers = (
                agentic.get("selection_blockers")
                if isinstance(agentic.get("selection_blockers"), list)
                else []
            )
            expected_tools = _clean_string_list(agentic.get("expected_tools"))
            expected_tool_groups = _clean_string_groups(agentic.get("expected_tool_groups"))
            actual_tools = _clean_string_list(agentic.get("actual_tools"))
            missing_expected_tools = _clean_string_list(agentic.get("missing_expected_tools"))
            agentic_selection = {
                "selected": bool(agentic.get("selected", False)),
                "feature_enabled": bool(agentic.get("feature_enabled", False)),
                "channel_allowed": bool(agentic.get("channel_allowed", False)),
                "route_supported": bool(agentic.get("route_supported", False)),
                "tool_suitable": bool(agentic.get("tool_suitable", False)),
                "tool_first_candidate": bool(agentic.get("tool_first_candidate", False)),
                "selection_blockers": [
                    _clean_text(item)
                    for item in list(selection_blockers or [])
                    if _clean_text(item)
                ],
            }
            if expected_tools or actual_tools or missing_expected_tools:
                agentic_selection.update(
                    {
                        "expected_tools": expected_tools,
                        "expected_tool_groups": expected_tool_groups,
                        "actual_tools": actual_tools,
                        "missing_expected_tools": missing_expected_tools,
                        "expected_tool_missing": bool(agentic.get("expected_tool_missing", False)),
                    }
                )
                self.metadata["agentic_tool_expectations"] = {
                    "expected_tools": expected_tools,
                    "expected_tool_groups": expected_tool_groups,
                    "actual_tools": actual_tools,
                    "missing_expected_tools": missing_expected_tools,
                    "expected_tool_missing": bool(agentic.get("expected_tool_missing", False)),
                }
            self.metadata["agentic_selection"] = agentic_selection

    def update_from_response(self, response: Any) -> None:
        if response is None:
            return
        conversation_id = _clean_text(getattr(response, "conversation_id", ""))
        if conversation_id:
            self.conversation_id = conversation_id

        debug = getattr(response, "debug", None)
        if isinstance(debug, dict):
            self.update_from_debug(debug)

        routing = getattr(response, "routing", None)
        route = _clean_text(getattr(routing, "workflow", ""))
        if route:
            self.route = route
        if not self.fallback_used:
            execution_mode = _clean_text(getattr(routing, "execution_mode", ""))
            if execution_mode:
                self.execution_mode = execution_mode

        meta = getattr(response, "meta", None)
        if isinstance(meta, dict):
            product_result_count = _coerce_int(meta.get("product_result_count"))
        else:
            product_result_count = _coerce_int(getattr(meta, "product_result_count", 0))
        products = list(getattr(response, "product_carousel", []) or [])
        sources = list(getattr(response, "sources", []) or [])
        self.retrieved_products = max(self.retrieved_products, product_result_count, len(products))
        self.retrieved_sources = max(self.retrieved_sources, len(sources))

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(
            {
                "run_id": self.run_id,
                "conversation_id": self.conversation_id,
                "user_id": self.user_id,
                "user_message": self.user_message,
                "intent": self.intent,
                "route": self.route,
                "workflow": self.workflow,
                "execution_mode": self.execution_mode,
                "tools_called": list(self.tools_called),
                "retrieved_products": int(self.retrieved_products or 0),
                "retrieved_sources": int(self.retrieved_sources or 0),
                "grounding_status": self.grounding_status,
                "fallback_used": bool(self.fallback_used),
                "fallback_reason": self.fallback_reason,
                "clarification_required": bool(self.clarification_required),
                "clarification_reason": self.clarification_reason,
                "errors": list(self.errors),
                "warnings": list(self.warnings),
                "timings_ms": dict(self.timings_ms),
                "metadata": dict(self.metadata),
            }
        )

    def _set_tool_events(self, events: Iterable[Any]) -> None:
        normalized_events: list[dict[str, Any]] = []
        for raw in list(events or []):
            if not isinstance(raw, dict):
                continue
            tool_name = _first_text(raw.get("tool"), raw.get("name"))
            if not tool_name:
                continue
            self.add_tool_call(tool_name)
            normalized_events.append(
                {
                    "tool": tool_name,
                    "status": _clean_text(raw.get("status")),
                    "tool_status": _clean_text(raw.get("tool_status")),
                    "duration_ms": _coerce_int(raw.get("duration_ms")),
                    "result_count": _coerce_int(raw.get("result_count")),
                }
            )
        if normalized_events:
            self.metadata["tool_events"] = normalized_events


def attach_harness_trace(
    *,
    debug_meta: dict[str, Any],
    trace: HarnessTrace | None,
    response: Any = None,
) -> None:
    if trace is None:
        return
    trace.update_from_debug(debug_meta)
    if response is not None:
        trace.update_from_response(response)
    debug_meta["harness_trace"] = trace.to_dict()
