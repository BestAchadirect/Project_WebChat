from __future__ import annotations

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.builders.contextual_messages import generate_contextual_component_message
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class ClarifyComponent(BaseComponent):
    component_type = ComponentType.CLARIFY

    async def build(self, context: ComponentContext) -> ChatComponent:
        reason = str(context.ambiguity_reason or "missing_details")
        debug_meta = dict(context.debug or {})
        debug_reason = str(debug_meta.get("clarify_reason") or "").strip()
        if debug_reason:
            reason = debug_reason
        message = str(debug_meta.get("clarify_message") or "").strip()
        if not message:
            message = await generate_contextual_component_message(
                kind="clarify",
                context=context,
            )
        if not message:
            message = "What detail should I use to narrow this down?"
        return ChatComponent(
            type=self.component_type,
            data={
                "message": message,
                "reason": reason,
            },
        )
