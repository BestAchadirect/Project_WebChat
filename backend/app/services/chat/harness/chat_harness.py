from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.schemas.chat import ChatResponse
from app.services.ai.llm_service import llm_service
from app.services.chat.harness.context import ChatHarnessContext, ChatHarnessDependencies
from app.services.chat.harness.executor import HarnessExecutionResult, run_execution
from app.services.chat.harness.finalizer import (
    HarnessFinalizedResult,
    run_error_finalization,
    run_finalization,
)
from app.services.chat.harness.router import HarnessRouteResult, run_routing
from app.services.chat.harness.support import build_initial_debug_meta
from app.services.chat.harness.trace import HarnessTrace
from app.services.chat.harness.understanding import HarnessUnderstandingResult, run_understanding
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities


@dataclass(frozen=True)
class ChatHarnessResult:
    response: ChatResponse
    trace: HarnessTrace


class ChatHarness:
    def __init__(
        self,
        *,
        service: Any,
        channel: str | None = None,
        dependencies: ChatHarnessDependencies,
    ) -> None:
        self.service = service
        self.channel = channel or "widget"
        self.dependencies = dependencies

    async def run(self, request: Any) -> ChatHarnessResult:
        context = await self.prepare_context(request)
        try:
            understanding_result = await self.understand(context)
            route_result = await self.route(context, understanding_result)
            execution_result = await self.execute(context, understanding_result, route_result)
            finalized_result = await self.finalize(context, route_result, execution_result)
        except Exception as exc:
            finalized_result = await self.finalize_error(context, exc)
        response = finalized_result.response
        context.trace.update_from_response(response)
        response.debug = dict(response.debug or {})
        response.debug["harness_trace"] = context.trace.to_dict()
        return ChatHarnessResult(response=response, trace=context.trace)

    async def prepare_context(self, request: Any) -> ChatHarnessContext:
        total_started = time.perf_counter()
        run_id = f"chat-{int(time.time() * 1000)}"
        trace = HarnessTrace(
            run_id=run_id,
            conversation_id=self._clean_optional(getattr(request, "conversation_id", None)),
            user_id=self._clean_optional(getattr(request, "user_id", None)),
            user_message=self._clean_optional(getattr(request, "message", None)),
        )
        config_fingerprint = self.service._config_fingerprint()
        debug_meta = build_initial_debug_meta(
            channel=self.channel,
            config_fingerprint=config_fingerprint,
        )
        debug_meta["run_id"] = run_id
        llm_service.begin_token_tracking()

        return ChatHarnessContext(
            service=self.service,
            request=request,
            channel=self.channel,
            trace=trace,
            run_id=run_id,
            user_text=str(getattr(request, "message", "") or ""),
            conversation_id_value=self._initial_conversation_id(request),
            total_started=total_started,
            spans=self.service._new_latency_spans(),
            capabilities=build_chat_runtime_capabilities(),
            debug_meta=debug_meta,
            step_started=total_started,
        )

    async def understand(self, context: ChatHarnessContext) -> HarnessUnderstandingResult:
        return await run_understanding(
            context=context,
            dependencies=self.dependencies,
        )

    async def route(
        self,
        context: ChatHarnessContext,
        understanding_result: HarnessUnderstandingResult,
    ) -> HarnessRouteResult:
        return await run_routing(
            context=context,
            dependencies=self.dependencies,
            understanding_result=understanding_result,
        )

    async def execute(
        self,
        context: ChatHarnessContext,
        understanding_result: HarnessUnderstandingResult,
        route_result: HarnessRouteResult,
    ) -> HarnessExecutionResult:
        return await run_execution(
            context=context,
            dependencies=self.dependencies,
            understanding_result=understanding_result,
            route_result=route_result,
        )

    async def finalize(
        self,
        context: ChatHarnessContext,
        route_result: HarnessRouteResult,
        execution_result: HarnessExecutionResult,
    ) -> HarnessFinalizedResult:
        return await run_finalization(
            context=context,
            route_result=route_result,
            execution_result=execution_result,
        )

    async def finalize_error(
        self,
        context: ChatHarnessContext,
        error: Exception,
    ) -> HarnessFinalizedResult:
        return await run_error_finalization(
            context=context,
            error=error,
        )

    @staticmethod
    def _clean_optional(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _initial_conversation_id(request: Any) -> int:
        raw_value = getattr(request, "conversation_id", None)
        if not raw_value:
            return 0
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return 0
