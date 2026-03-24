from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import settings
from app.services.chat.components.pipeline_runtime.state import PipelineExecutionState
from app.services.chat.components.types import ComponentSource
from app.services.chat.parsing.llm_attribute_extractor import AttributeExtractionResult, enrich_product_attribute_filters
from app.services.chat.parsing import parser_rule_cache
from app.services.chat.parsing.detail_query_parser import DetailQueryParser
from app.services.chat.presentation import reply_tone
from app.services.chat.routing import routing_policy
from app.services.chat.runtime import alias_cache, conversation_state
from app.services.chat.text_normalization import normalize_user_text


@dataclass
class PipelineToneController:
    user_text: str
    active: bool
    recent: List[Dict[str, Any]]
    latest_key: str = ""
    latest_variant_id: int = -1
    latest_style: str = ""
    latest_anti_repeat: bool = False
    repeat_hit_count: int = 0
    filler_stripped_count: int = 0

    @classmethod
    def build(
            cls,
            *,
            user_text: str,
            channel: str,
            recent: Sequence[Dict[str, Any]],
        ) -> tuple["PipelineToneController", Dict[str, Any]]:
            tone_humanizer_enabled = bool(getattr(settings, "CHAT_TONE_HUMANIZER_ENABLED", True))
            tone_enabled_channels = {
                str(item or "").strip().lower()
                for item in str(getattr(settings, "CHAT_TONE_ENABLED_CHANNELS", "widget")).split(",")
                if str(item or "").strip()
            }
            tone_channel_allowed = not tone_enabled_channels or str(channel or "widget").strip().lower() in tone_enabled_channels
            tone_active = bool(tone_humanizer_enabled and tone_channel_allowed)
            return (
                cls(
                    user_text=str(user_text or ""),
                    active=tone_active,
                    recent=list(recent or []),
                ),
                {
                    "tone_humanizer_enabled": tone_humanizer_enabled,
                    "tone_channel_allowed": tone_channel_allowed,
                    "tone_active": tone_active,
                },
            )

    def pick(self, key: str, variants: Sequence[str], *, user_text_override: Optional[str] = None) -> str:
            decision = reply_tone.compose_variant(
                user_text=str(user_text_override if user_text_override is not None else self.user_text),
                key=key,
                variants=variants,
                recent=self.recent,
                anti_repeat_window=int(getattr(settings, "CHAT_TONE_ANTI_REPEAT_WINDOW", 4)),
                humanizer_enabled=self.active,
                max_sentences=int(getattr(settings, "CHAT_TONE_MAX_SENTENCES", 2)),
                max_chars=int(getattr(settings, "CHAT_TONE_MAX_CHARS", 220)),
            )
            self.recent = reply_tone.push_recent(
                self.recent,
                decision=decision,
                max_items=conversation_state.MAX_TONE_RECENT,
            )
            self.latest_key = str(decision.key or "")
            self.latest_variant_id = int(decision.variant_id)
            self.latest_style = str(decision.style or "")
            self.latest_anti_repeat = bool(decision.anti_repeat_applied)
            if decision.anti_repeat_applied:
                self.repeat_hit_count += 1
            if decision.filler_stripped:
                self.filler_stripped_count += 1
            return str(decision.text or "")

    def snapshot(self) -> Dict[str, Any]:
            return {
                "recent": list(self.recent),
                "key": self.latest_key,
                "variant_id": self.latest_variant_id,
                "style": self.latest_style,
                "anti_repeat_applied": bool(self.latest_anti_repeat),
                "repeat_hit": int(self.repeat_hit_count),
                "filler_stripped": int(self.filler_stripped_count),
            }


@dataclass
class PipelineRunSetup:
    normalized_text: str
    detail: Any
    conversation_state_enabled: bool
    state_working: Optional[Dict[str, Any]]
    sku_tokens: List[str]
    unique_sku_tokens: List[str]
    route_decision: routing_policy.WorkflowDecision
    workflow: str
    recommendation_requested: bool
    store_overview_request: bool
    knowledge_workflow: bool
    fallback_workflow: bool
    source: ComponentSource
    execution_state: PipelineExecutionState
    tone_controller: PipelineToneController
    llm_call_count: int = 0


class PipelineSetupMixin:
    async def _prepare_pipeline_run(
            self,
            *,
            text: str,
            channel: str,
            conversation_id: int,
            route_decision_override: Optional[routing_policy.WorkflowDecision],
            routing_selection_source: str,
        ) -> PipelineRunSetup:
            normalized_text = normalize_user_text(text)

            alias_map = await alias_cache.get_alias_map(self.db)
            parser_rules = await parser_rule_cache.get_parser_rules(self.db)
            detail = DetailQueryParser.parse(
                user_text=text,
                nlu_data={},
                alias_map=alias_map,
                parser_rules=parser_rules,
            )

            conversation_state_enabled = bool(getattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", False))
            state_working: Optional[Dict[str, Any]] = None
            conversation_state_filter_merge_applied = False
            if conversation_state_enabled:
                state_working = await self._load_conversation_state(conversation_id=conversation_id)

            sku_tokens = routing_policy.extract_sku_tokens(text)
            unique_sku_tokens = [token for token in dict.fromkeys([str(item).strip() for item in sku_tokens]) if token]

            if conversation_state_enabled and state_working is not None:
                debug_state_version = int(
                    state_working.get("version", conversation_state.CONVERSATION_STATE_VERSION)
                )
                if conversation_state.should_merge_follow_up_filters(
                    user_text=text,
                    current_filters=detail.attribute_filters,
                    sku_token=unique_sku_tokens[0] if unique_sku_tokens else None,
                ):
                    merged_filters = conversation_state.merge_filters(
                        detail.attribute_filters,
                        state_working.get("last_attribute_filters", {}),
                    )
                    detail = replace(detail, attribute_filters=merged_filters)
                    conversation_state_filter_merge_applied = True
                tone_recent = reply_tone.normalize_recent(state_working.get("tone_recent"))
            else:
                debug_state_version = conversation_state.CONVERSATION_STATE_VERSION
                tone_recent = []

            route_decision = route_decision_override
            if route_decision is None:
                route_decision = routing_policy.WorkflowDecision(
                    workflow="fallback",
                    source=ComponentSource.ERROR,
                    needs_products=False,
                    needs_knowledge=False,
                    needs_clarification=True,
                    store_overview_request=False,
                    reason="missing_workflow_override",
                    confidence=0.0,
                )

            workflow = route_decision.workflow
            if list(getattr(detail, "semantic_hints", []) or []) or str(getattr(detail, "clarify_focus", "") or "").strip():
                attribute_enrichment = AttributeExtractionResult(
                    exact_filters={},
                    semantic_hints=[],
                    clarify_focus="",
                    debug={},
                )
            else:
                attribute_enrichment = await enrich_product_attribute_filters(
                    db=self.db,
                    user_text=text,
                    workflow=workflow,
                    existing_filters=detail.attribute_filters,
                    alias_map=alias_map,
                    parser_rules=parser_rules,
                )
            merged_attribute_filters = dict(detail.attribute_filters or {})
            for key, value in dict(attribute_enrichment.exact_filters or {}).items():
                merged_attribute_filters.setdefault(str(key), str(value))
            merged_semantic_hints: List[str] = []
            seen_semantic_hints: set[str] = set()
            for raw in list(getattr(detail, "semantic_hints", []) or []) + list(attribute_enrichment.semantic_hints or []):
                hint = str(raw or "").strip()
                if not hint or hint in seen_semantic_hints:
                    continue
                seen_semantic_hints.add(hint)
                merged_semantic_hints.append(hint)
            if (
                merged_attribute_filters != dict(detail.attribute_filters or {})
                or merged_semantic_hints != list(getattr(detail, "semantic_hints", []) or [])
                or str(attribute_enrichment.clarify_focus or "") != str(getattr(detail, "clarify_focus", "") or "")
            ):
                detail = replace(
                    detail,
                    attribute_filters=merged_attribute_filters,
                    semantic_hints=merged_semantic_hints,
                    clarify_focus=str(attribute_enrichment.clarify_focus or getattr(detail, "clarify_focus", "") or ""),
                )
            execution_state = self._build_execution_state(
                workflow=workflow,
                needs_products=bool(route_decision.needs_products),
                needs_knowledge=bool(route_decision.needs_knowledge),
                needs_clarification=bool(route_decision.needs_clarification),
                route_override_used=route_decision_override is not None,
                routing_selection_source=routing_selection_source,
                conversation_state_enabled=conversation_state_enabled,
                conversation_state_filter_merge_applied=conversation_state_filter_merge_applied,
                debug_state_version=debug_state_version,
                detail_requested_fields=detail.requested_fields,
                store_overview_request=route_decision.store_overview_request,
            )
            execution_state.debug_meta.update(dict(attribute_enrichment.debug or {}))
            if str(route_decision.knowledge_query or "").strip():
                execution_state.debug_meta["knowledge_query_from_router"] = str(route_decision.knowledge_query or "").strip()
            if int(attribute_enrichment.llm_call_count or 0) > 0:
                execution_state.external_call_counts["llm_attribute_interpretation"] = int(attribute_enrichment.llm_call_count or 0)
            tone_controller, tone_debug = PipelineToneController.build(
                user_text=text,
                channel=channel,
                recent=tone_recent,
            )
            execution_state.debug_meta.update(tone_debug)

            return PipelineRunSetup(
                normalized_text=normalized_text,
                detail=detail,
                conversation_state_enabled=conversation_state_enabled,
                state_working=state_working,
                sku_tokens=list(sku_tokens),
                unique_sku_tokens=list(unique_sku_tokens),
                route_decision=route_decision,
                workflow=workflow,
                recommendation_requested=workflow == "recommendation",
                store_overview_request=bool(route_decision.store_overview_request),
                knowledge_workflow=workflow == "knowledge",
                fallback_workflow=workflow == "fallback",
                source=route_decision.source,
                execution_state=execution_state,
                tone_controller=tone_controller,
                llm_call_count=int(attribute_enrichment.llm_call_count or 0),
            )
