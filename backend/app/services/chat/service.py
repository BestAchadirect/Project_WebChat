from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chat import AppUser, Conversation, Message
from app.models.qa_log import QALog
from app.schemas.chat import (
    ChatComponent,
    ChatRequest,
    ChatResponse,
    ChatResponseMeta,
    ProductCard,
)
from app.services.catalog.product_search import CatalogProductSearchService
from app.services.chat.agentic.orchestrator import AgentOrchestrator, AgentRunResult
from app.services.chat.components.cache import component_cache
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.presentation import component_contract, public_response
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities
from app.services.chat.runtime import conversation_state, persistence, unified_chat_runtime
from app.services.chat.retrieval import follow_up_policy
from app.services.chat.routing import routing_policy
from app.services.chat.routing.contracts import DecisionState
from app.services.chat.observability import runtime_metrics
from app.services.knowledge.retrieval import KnowledgeRetrievalService
from app.utils.debug_log import debug_log as _debug_log


class EmbeddingSkippedReason(str, Enum):
    NOT_NEEDED = "not_needed"
    STRUCTURED_RESULTS_FOUND = "structured_results_found"
    BUDGET_EXCEEDED = "budget_exceeded"
    DISABLED_BY_ROUTE = "disabled_by_route"


class ExternalBudgetExceededReason(str, Enum):
    EXTERNAL_CALL_BUDGET = "external_call_budget"
    EXTERNAL_TIMEOUT = "external_timeout"
    EXTERNAL_CONNECTIVITY = "external_connectivity"
    LLM_CALL_CAP = "llm_call_cap"


class ChatService:
    """Chat orchestration (workflow routing -> retrieval -> response)."""
    _last_cache_stats_log_ts: float = 0.0

    def __init__(self, db: AsyncSession):
        self.db = db
        self._catalog_search = CatalogProductSearchService(db=self.db)
        self._knowledge_retrieval = KnowledgeRetrievalService(db=self.db, log_event=self._log_event)

    @staticmethod
    def _feature_flags_snapshot() -> Dict[str, Any]:
        return runtime_metrics.feature_flags_snapshot()
    @classmethod
    def _config_fingerprint(cls) -> Dict[str, Any]:
        snapshot = cls._feature_flags_snapshot()
        serialized = json.dumps(snapshot, sort_keys=True, ensure_ascii=True)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        return {"hash": digest, "flags": snapshot}

    @staticmethod
    def _estimated_tokens(value: str) -> int:
        return runtime_metrics.estimated_tokens(value)
    @classmethod
    def _trim_history_for_llm(cls, history: List[Dict[str, Any]], max_tokens: int) -> List[Dict[str, Any]]:
        return runtime_metrics.trim_history_for_llm(history=history, max_tokens=max_tokens)
    def _log_cache_stats_if_needed(self, *, run_id: str, debug_meta: Dict[str, Any]) -> None:
        capabilities = build_chat_runtime_capabilities()
        interval = max(5, int(capabilities.chat_cache_log_interval_seconds))
        now = time.time()
        if now - float(self.__class__._last_cache_stats_log_ts or 0.0) < interval:
            return
        self.__class__._last_cache_stats_log_ts = now
        structured_stats = self._catalog_search.structured_cache_stats()
        debug_meta["structured_query_cache_stats"] = structured_stats
        self._log_event(
            run_id=run_id,
            location="chat_service.cache.stats",
            data={
                "structured_query_cache": structured_stats,
            },
        )

    @staticmethod
    def _new_latency_spans() -> Dict[str, Any]:
        return runtime_metrics.new_latency_spans()
    @staticmethod
    def _add_latency_span(spans: Dict[str, Any], key: str, elapsed_ms: float) -> None:
        runtime_metrics.add_latency_span(spans, key, elapsed_ms)
    def _merge_catalog_metrics_into_spans(self, spans: Dict[str, Any]) -> None:
        runtime_metrics.merge_catalog_metrics_into_spans(spans=spans, catalog_search=self._catalog_search)
    def _build_latency_payload(
        self,
        *,
        spans: Dict[str, Any],
        total_started: float,
        detail_mode_triggered: bool,
        token_usage: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return runtime_metrics.build_latency_payload(
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_triggered,
            token_usage=token_usage,
        )
    async def _finalize_with_latency(
        self,
        *,
        conversation_id: int,
        user_text: str,
        response: ChatResponse,
        token_usage: Optional[Dict[str, Any]],
        channel: Optional[str],
        run_id: str,
        debug_meta: Dict[str, Any],
        spans: Dict[str, Any],
        total_started: float,
        detail_mode_triggered: bool,
        conversation_state: Optional[Dict[str, Any]] = None,
    ) -> ChatResponse:
        retrieval_meta = debug_meta.get("retrieval_gate") if isinstance(debug_meta, dict) else None
        route = str(
            getattr(getattr(response, "routing", None), "workflow", "")
            or (debug_meta.get("workflow") if isinstance(debug_meta, dict) else "")
            or ""
        )
        response_products = component_contract.product_cards_from_response(response)
        raw_follow_ups = component_contract.follow_up_questions_from_response(response)
        filtered_follow_ups = self._filter_follow_up_questions(
            questions=raw_follow_ups,
            user_text=user_text,
            route=route,
            has_products=bool(response_products),
            retrieval_gate=retrieval_meta if isinstance(retrieval_meta, dict) else None,
            limit=5,
        )
        if raw_follow_ups != filtered_follow_ups and isinstance(debug_meta, dict):
            debug_meta["follow_up_filter"] = {
                "before_count": len(raw_follow_ups),
                "after_count": len(filtered_follow_ups),
            }
        component_contract.upsert_quick_replies_component(
            response,
            filtered_follow_ups,
            actions_by_label=dict(debug_meta.get("quick_reply_actions") or {}) if isinstance(debug_meta, dict) else None,
        )

        latency_payload = self._build_latency_payload(
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_triggered,
            token_usage=token_usage if isinstance(token_usage, dict) else None,
        )
        debug_meta["latency_spans"] = latency_payload
        debug_payload = public_response.sanitize_debug_payload(debug_meta)
        response.debug = dict(response.debug or {})
        response.debug.update(debug_payload)
        response.debug["latency_spans"] = latency_payload
        self._log_event(
            run_id=run_id,
            location="chat_service.latency_spans",
            data=latency_payload,
        )
        finalize_kwargs = {
            "conversation_id": conversation_id,
            "user_text": user_text,
            "response": response,
            "token_usage": token_usage,
            "channel": channel,
        }
        if conversation_state is not None:
            finalize_kwargs["conversation_state"] = conversation_state
        return await self._finalize_response(**finalize_kwargs)

    def _log_latency_error(
        self,
        *,
        run_id: str,
        debug_meta: Dict[str, Any],
        spans: Dict[str, Any],
        total_started: float,
        detail_mode_triggered: bool,
        token_usage: Optional[Dict[str, Any]],
        error: Exception,
    ) -> None:
        latency_payload = self._build_latency_payload(
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_triggered,
            token_usage=token_usage if isinstance(token_usage, dict) else None,
        )
        debug_meta["latency_spans"] = latency_payload
        debug_meta["latency_error"] = str(error)
        self._log_event(
            run_id=run_id,
            location="chat_service.latency_spans.error",
            data={
                "latency_spans": latency_payload,
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        return follow_up_policy.normalize_text(text)
    @classmethod
    def _is_follow_up_relevant(
        cls,
        *,
        question: str,
        user_text: str,
        route: str,
        has_products: bool,
        use_products: bool,
        use_knowledge: bool,
        is_policy_like: bool,
    ) -> bool:
        return follow_up_policy.is_follow_up_relevant(
            question=question,
            user_text=user_text,
            route=route,
            has_products=has_products,
            use_products=use_products,
            use_knowledge=use_knowledge,
            is_policy_like=is_policy_like,
        )
    @classmethod
    def _filter_follow_up_questions(
        cls,
        *,
        questions: List[str],
        user_text: str,
        route: str,
        has_products: bool,
        retrieval_gate: Optional[Dict[str, Any]],
        limit: int = 5,
    ) -> List[str]:
        return follow_up_policy.filter_follow_up_questions(
            questions=questions,
            user_text=user_text,
            route=route,
            has_products=has_products,
            retrieval_gate=retrieval_gate,
            limit=limit,
        )

    def _log_event(self, *, run_id: str, location: str, data: Dict[str, Any]) -> None:
        _debug_log(
            {
                "sessionId": "debug-session",
                "runId": run_id,
                "hypothesisId": "RAG",
                "location": location,
                "message": location,
                "data": data,
                "timestamp": int(time.time() * 1000),
            }
        )

    @staticmethod
    def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
        if not dt:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def is_conversation_active(self, conversation: Optional[Conversation]) -> bool:
        if conversation is None:
            return False

        now = datetime.now(timezone.utc)
        started_at = self._ensure_utc(conversation.started_at)
        last_message_at = self._ensure_utc(conversation.last_message_at) or started_at

        idle_minutes = int(getattr(settings, "CONVERSATION_IDLE_TIMEOUT_MINUTES", 30) or 0)
        hard_cap_hours = int(getattr(settings, "CONVERSATION_HARD_CAP_HOURS", 24) or 0)

        if idle_minutes > 0 and last_message_at:
            if last_message_at < (now - timedelta(minutes=idle_minutes)):
                return False

        if hard_cap_hours > 0 and started_at:
            if started_at < (now - timedelta(hours=hard_cap_hours)):
                return False

        return True

    @staticmethod
    def _is_agentic_channel_enabled(channel: Optional[str]) -> bool:
        return routing_policy.is_agentic_channel_enabled(channel=channel)

    def _is_agentic_tool_suitable(
        self,
        *,
        user_text: str,
        workflow: str,
        sku_token: Optional[str],
    ) -> bool:
        return routing_policy.is_agentic_tool_suitable(
            user_text=user_text,
            workflow=workflow,
            sku_token=sku_token,
        )

    def _new_agent_orchestrator(self, *, run_id: str, channel: str) -> AgentOrchestrator:
        return AgentOrchestrator(
            db=self.db,
            run_id=run_id,
            channel=channel,
        )

    async def get_user(self, user_id: str) -> Optional[AppUser]:
        stmt = select(AppUser).where(AppUser.id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_conversation_for_user(
        self,
        user: AppUser,
        conversation_id: int,
    ) -> Optional[Conversation]:
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_conversation(
        self,
        user: AppUser,
        conversation_id: Optional[int] = None,
    ) -> Optional[Conversation]:
        if conversation_id:
            conversation = await self.get_conversation_for_user(user, conversation_id)
            if self.is_conversation_active(conversation):
                return conversation

        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.last_message_at.desc(), Conversation.id.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        latest = result.scalar_one_or_none()
        if self.is_conversation_active(latest):
            return latest
        return None

    async def get_or_create_user(
        self,
        user_id: str,
        name: str | None = None,
        email: str | None = None,
    ) -> AppUser:
        stmt = select(AppUser).where(AppUser.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            # Best-effort update
            if name and not user.customer_name:
                user.customer_name = name
            if email and not user.email:
                user.email = email
            self.db.add(user)
            await self.db.commit()
            return user

        user = AppUser(id=user_id, customer_name=name, email=email)
        self.db.add(user)
        try:
            await self.db.commit()
            await self.db.refresh(user)
            return user
        except IntegrityError:
            # Concurrent requests can race on first insert; fetch the winner row.
            await self.db.rollback()
            retry = await self.db.execute(stmt)
            existing = retry.scalar_one_or_none()
            if existing is None:
                raise
            if name and not existing.customer_name:
                existing.customer_name = name
            if email and not existing.email:
                existing.email = email
            self.db.add(existing)
            await self.db.commit()
            return existing

    async def get_or_create_conversation(
        self,
        user: AppUser,
        conversation_id: Optional[int],
    ) -> Conversation:
        if conversation_id:
            stmt = select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
            )
            result = await self.db.execute(stmt)
            existing = result.scalar_one_or_none()
            if self.is_conversation_active(existing):
                return existing

        conversation = Conversation(user_id=user.id)
        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def save_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        product_data: List[ProductCard] | None = None,
        token_usage: Dict[str, Any] | None = None,
        commit: bool = True,
        touch_conversation: bool = True,
    ) -> Message:
        return await persistence.save_message(
            db=self.db,
            conversation_id=conversation_id,
            role=role,
            content=content,
            product_data=product_data,
            token_usage=token_usage,
            commit=commit,
            touch_conversation=touch_conversation,
        )
    async def _finalize_response(
        self,
        *,
        conversation_id: int,
        user_text: str,
        response: ChatResponse,
        token_usage: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
        conversation_state: Optional[Dict[str, Any]] = None,
    ) -> ChatResponse:
        return await persistence.finalize_response(
            db=self.db,
            conversation_id=conversation_id,
            user_text=user_text,
            response=response,
            token_usage=token_usage,
            channel=channel,
            conversation_state=conversation_state,
        )
    async def submit_feedback(self, *, qa_log_id: UUID, feedback: int) -> Optional[QALog]:
        return await persistence.submit_feedback(db=self.db, qa_log_id=qa_log_id, feedback=feedback)
    async def get_history(self, conversation_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        return await persistence.get_history(db=self.db, conversation_id=conversation_id, limit=limit)
    async def get_conversation_state(self, conversation_id: int) -> Dict[str, Any]:
        if not conversation_id:
            return conversation_state.load_state(None)
        stmt = select(Conversation.state).where(Conversation.id == int(conversation_id)).limit(1)
        result = await self.db.execute(stmt)
        row = result.first()
        raw_state = row[0] if row else None
        return conversation_state.load_state(raw_state)
    async def _run_component_pipeline(
        self,
        *,
        request: ChatRequest,
        conversation_id: int,
        run_id: str,
        route_decision_override: Optional[routing_policy.WorkflowDecision] = None,
        detail_override: Any | None = None,
        llm_call_count_override: int = 0,
        routing_selection_source: str = "",
        internal_workflow_override: str = "",
        decision_state_override: Optional[DecisionState] = None,
        channel: str = "widget",
    ):
        pipeline = ComponentPipeline(
            db=self.db,
            catalog_search=self._catalog_search,
            knowledge_retrieval=self._knowledge_retrieval,
            component_cache=component_cache,
        )
        return await pipeline.run(
            request=request,
            conversation_id=conversation_id,
            run_id=run_id,
            route_decision_override=route_decision_override,
            detail_override=detail_override,
            llm_call_count_override=llm_call_count_override,
            routing_selection_source=routing_selection_source,
            internal_workflow_override=internal_workflow_override,
            decision_state_override=decision_state_override,
            channel=channel,
        )

    async def _run_agentic_workflow(
        self,
        *,
        user_text: str,
        conversation_id: int,
        run_id: str,
        channel: str,
        reply_language: str,
    ) -> Optional[AgentRunResult]:
        history = await self.get_history(conversation_id=conversation_id, limit=8)
        orchestrator = self._new_agent_orchestrator(run_id=run_id, channel=channel)
        return await orchestrator.run(
            user_text=user_text,
            history=history,
            reply_language=reply_language,
        )


    async def process_chat(self, req: ChatRequest, channel: Optional[str] = None) -> ChatResponse:
        return await unified_chat_runtime.process_chat(self, req, channel)
