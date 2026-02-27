from __future__ import annotations

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class ErrorComponent(BaseComponent):
    component_type = ComponentType.ERROR

    async def build(self, context: ComponentContext) -> ChatComponent:
        return ChatComponent(
            type=self.component_type,
            data={"message": str(context.error_message or "I could not process this request right now.")},
        )

