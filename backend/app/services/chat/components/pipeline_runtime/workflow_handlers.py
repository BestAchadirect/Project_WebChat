from __future__ import annotations

import time
from typing import Any, Callable, Dict, Sequence

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
            workflow: str,
            detail: Any,
            unique_sku_tokens: Sequence[str],
            result_fetch_limit: int,
            conversation_id: int,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
            tone_pick: Callable[[str, Sequence[str]], str],
        ) -> bool:
            if workflow == "smalltalk":
                state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
                state.knowledge_answer = tone_pick(
                    "smalltalk:redirect",
                    [
                        "Hi. Tell me what body jewelry you need, like type, material, gauge, or SKU.",
                        "Happy to help. Share the product type, material, gauge, or SKU and I will narrow it down.",
                        "Sure, tell me what you're looking for and I can find options by type, material, or SKU.",
                    ],
                )
                state.retrieval_source = ComponentSource.TOOL
                return True

            if workflow == "off_topic":
                state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
                state.knowledge_answer = self._compose_off_topic_reply(
                    user_text=text,
                    pick_text=lambda key, variants: tone_pick(key, variants),
                )
                state.retrieval_source = ComponentSource.ERROR
                state.result_count = 0
                return True

            return False

    async def _handle_pre_catalog_workflows(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            workflow: str,
            detail: Any,
            store_overview_request: bool,
            unique_sku_tokens: Sequence[str],
            result_fetch_limit: int,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
        ) -> None:
            if store_overview_request:
                featured_started = time.perf_counter()
                state.product_ids = await self._load_featured_product_ids(limit=result_fetch_limit)
                spans["db_product_lookup_ms"] += (time.perf_counter() - featured_started) * 1000.0
                state.result_count = len(state.product_ids)
                state.retrieval_source = ComponentSource.SQL
                debug_meta["store_overview_candidate_count"] = int(state.result_count)
