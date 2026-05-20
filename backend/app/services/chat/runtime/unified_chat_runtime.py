from __future__ import annotations

"""Compatibility entrypoint for chat processing.

The orchestration flow now lives in ``app.services.chat.harness``. This module
keeps the historical ``unified_chat_runtime.process_chat`` import path stable
for ChatService, tests, and external tooling during the harness migration.

Do not add new runtime logic here. Add orchestration changes under
``app.services.chat.harness`` and keep this module as a thin delegation shim.
"""

from typing import Optional

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat.harness.chat_harness import ChatHarness
from app.services.chat.harness.dependencies import build_default_harness_dependencies

__all__ = ["process_chat"]

_COMPATIBILITY_METADATA = {
    "import_path": "app.services.chat.runtime.unified_chat_runtime.process_chat",
    "role": "historical chat runtime entrypoint",
    "migration_target": "app.services.chat.harness.chat_harness.ChatHarness",
    "removal_condition": "after one release cycle and external import audit completion",
}


async def process_chat(self, req: ChatRequest, channel: Optional[str] = None) -> ChatResponse:
    result = await ChatHarness(
        service=self,
        channel=channel,
        dependencies=build_default_harness_dependencies(),
    ).run(req)
    return result.response
