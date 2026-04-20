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
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> tuple[bool, int]:
            if workflow == "off_topic":
                llm_started = time.perf_counter()
                reply = await generate_contextual_reply(
                    kind=workflow,
                    reply_language=str(locale or "en-US").strip() or "en-US",
                    payload={
                        "workflow": str(workflow or "").strip(),
                        "locale": str(locale or "en-US").strip() or "en-US",
                        "user_text": str(text or "").strip(),
                        "assistant_scope": "body jewelry products, stock, pricing, materials, sizes/gauge, and store policies/info",
                    },
                )
                spans["llm_answer_ms"] += (time.perf_counter() - llm_started) * 1000.0
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
                state.knowledge.answer = reply or "I can help with body jewelry products and store support in this chat."
                state.retrieval.source = ComponentSource.ERROR
                state.retrieval.result_count = 0
                if reply:
                    external_call_counts["llm_terminal_reply"] = int(external_call_counts.get("llm_terminal_reply", 0)) + 1
                    debug_meta["terminal_reply_source"] = "llm"
                    return True, 1
                debug_meta["terminal_reply_source"] = "fallback"
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
            featured_started = time.perf_counter()
            state.catalog.product_ids = await self._load_featured_product_ids(limit=result_fetch_limit)
            spans["db_product_lookup_ms"] += (time.perf_counter() - featured_started) * 1000.0
            state.retrieval.result_count = len(state.catalog.product_ids)
            state.retrieval.source = ComponentSource.SQL
            debug_meta["store_overview_candidate_count"] = int(state.retrieval.result_count)
