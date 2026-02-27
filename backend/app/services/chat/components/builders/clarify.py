from __future__ import annotations

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class ClarifyComponent(BaseComponent):
    component_type = ComponentType.CLARIFY

    async def build(self, context: ComponentContext) -> ChatComponent:
        reason = str(context.ambiguity_reason or "missing details")
        return ChatComponent(
            type=self.component_type,
            data={
                "message": "Please share more detail so I can match products accurately.",
                "reason": reason,
            },
        )

