from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.chat.harness.chat_harness import ChatHarness, ChatHarnessResult
    from app.services.chat.harness.context import ChatHarnessContext, ChatHarnessDependencies
    from app.services.chat.harness.dependencies import build_default_harness_dependencies
    from app.services.chat.harness.executor import HarnessExecutionResult
    from app.services.chat.harness.finalizer import HarnessFinalizedResult
    from app.services.chat.harness.router import HarnessRouteResult
    from app.services.chat.harness.trace import HarnessTrace
    from app.services.chat.harness.understanding import HarnessUnderstandingResult


__all__ = [
    "ChatHarness",
    "ChatHarnessContext",
    "ChatHarnessDependencies",
    "HarnessExecutionResult",
    "HarnessFinalizedResult",
    "HarnessRouteResult",
    "ChatHarnessResult",
    "HarnessTrace",
    "HarnessUnderstandingResult",
    "build_default_harness_dependencies",
]


def __getattr__(name: str) -> Any:
    if name in {"ChatHarness", "ChatHarnessResult"}:
        from app.services.chat.harness.chat_harness import ChatHarness, ChatHarnessResult

        return {"ChatHarness": ChatHarness, "ChatHarnessResult": ChatHarnessResult}[name]
    if name in {"ChatHarnessContext", "ChatHarnessDependencies"}:
        from app.services.chat.harness.context import ChatHarnessContext, ChatHarnessDependencies

        return {
            "ChatHarnessContext": ChatHarnessContext,
            "ChatHarnessDependencies": ChatHarnessDependencies,
        }[name]
    if name == "build_default_harness_dependencies":
        from app.services.chat.harness.dependencies import build_default_harness_dependencies

        return build_default_harness_dependencies
    if name == "HarnessExecutionResult":
        from app.services.chat.harness.executor import HarnessExecutionResult

        return HarnessExecutionResult
    if name == "HarnessFinalizedResult":
        from app.services.chat.harness.finalizer import HarnessFinalizedResult

        return HarnessFinalizedResult
    if name == "HarnessRouteResult":
        from app.services.chat.harness.router import HarnessRouteResult

        return HarnessRouteResult
    if name == "HarnessTrace":
        from app.services.chat.harness.trace import HarnessTrace

        return HarnessTrace
    if name == "HarnessUnderstandingResult":
        from app.services.chat.harness.understanding import HarnessUnderstandingResult

        return HarnessUnderstandingResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
