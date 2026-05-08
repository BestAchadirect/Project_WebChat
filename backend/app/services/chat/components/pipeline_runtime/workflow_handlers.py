from __future__ import annotations

import time
from typing import Any, Dict

from app.services.chat.components.builders.contextual_messages import generate_contextual_reply
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.components.pipeline_runtime.workflow_catalog import PipelineWorkflowCatalogMixin
from app.services.chat.components.pipeline_runtime.workflow_knowledge import PipelineWorkflowKnowledgeMixin
from app.services.chat.components.types import ComponentSource, ComponentType


class PipelineWorkflowHandlersMixin(PipelineWorkflowCatalogMixin, PipelineWorkflowKnowledgeMixin):
    async def _handle_terminal_workflows(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            locale: str,
            workflow: str,
            internal_workflow: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> tuple[bool, int]:
            if workflow in {"general_talking", "off_topic"}:
                intent = str(getattr(state.decision, "intent", "") or debug_meta.get("response_intent") or "").strip().lower()
                response_policy = str(
                    getattr(state.decision, "response_policy", "") or debug_meta.get("response_policy") or ""
                ).strip().lower()
                internal = str(internal_workflow or getattr(state.decision, "internal_workflow", "") or "").strip().lower()
                if workflow == "general_talking" and (
                    intent == "knowledge_policy"
                    or internal in {"company_info", "policy_info"}
                    or response_policy == "answer_from_retrieved_data"
                ):
                    state.decision.ambiguity_reason = "knowledge_unavailable"
                    state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                    state.knowledge.answer = ""
                    state.retrieval.source = ComponentSource.ERROR
                    state.retrieval.result_count = 0
                    debug_meta["terminal_reply_blocked"] = True
                    debug_meta["terminal_reply_blocked_reason"] = "retrieval_required"
                    return True, 0
                terminal_kind = "default" if workflow == "general_talking" else "off_topic"
                usage_scope = (
                    "body jewelry products, stock, pricing, materials, sizes/gauge, and store policies/info"
                )
                if intent in {"general_talking", "product_information"} or internal == "general_talking":
                    terminal_kind = "default"
                if response_policy == "safe_redirect":
                    terminal_kind = "off_topic"
                llm_started = time.perf_counter()
                reply = await generate_contextual_reply(
                    kind=terminal_kind,
                    reply_language=str(locale or "en-US").strip() or "en-US",
                    payload={
                        "workflow": str(workflow or "").strip(),
                        "internal_workflow": internal,
                        "intent": intent,
                        "subintent": str(getattr(state.decision, "subintent", "") or debug_meta.get("response_subintent") or "").strip(),
                        "response_policy": response_policy,
                        "user_goal": str(getattr(state.decision, "user_goal", "") or debug_meta.get("response_user_goal") or "").strip(),
                        "locale": str(locale or "en-US").strip() or "en-US",
                        "user_text": str(text or "").strip(),
                        "assistant_scope": usage_scope,
                        "allowed_product_help": [
                            "find products by jewelry type",
                            "filter by material, color, gauge, or size",
                            "check stock, price, SKU, images, and product details",
                            "show matching product cards when the request needs product retrieval",
                        ],
                    },
                )
                spans["llm_answer_ms"] += (time.perf_counter() - llm_started) * 1000.0
                terminal_reply = reply or "I can help with body jewelry products and store support in this chat."
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY]
                state.knowledge.answer = ""
                state.retrieval.source = ComponentSource.ERROR
                state.retrieval.result_count = 0
                debug_meta["terminal_reply_text"] = terminal_reply
                if reply:
                    external_call_counts["llm_terminal_reply"] = int(external_call_counts.get("llm_terminal_reply", 0)) + 1
                    debug_meta["terminal_reply_source"] = "llm"
                    debug_meta["terminal_reply_kind"] = terminal_kind
                    return True, 1
                debug_meta["terminal_reply_source"] = "fallback"
                debug_meta["terminal_reply_kind"] = terminal_kind
                return True, 0

            return False, 0

    async def _handle_pre_catalog_workflows(
            self,
            *,
            state: PipelineWorkflowState,
            workflow: str,
            store_overview_request: bool,
            result_fetch_limit: int,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
        ) -> None:
            if workflow != "catalog":
                return
            if not store_overview_request:
                return
            overview_started = time.perf_counter()
            state.catalog.product_ids = await self._load_store_overview_product_ids(limit=result_fetch_limit)
            spans["db_product_lookup_ms"] += (time.perf_counter() - overview_started) * 1000.0
            state.retrieval.result_count = len(state.catalog.product_ids)
            state.retrieval.source = ComponentSource.SQL
            debug_meta["store_overview_candidate_count"] = int(state.retrieval.result_count)
