from __future__ import annotations

from app.schemas.chat import ChatComponent
from app.services.chat.presentation import reply_tone
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.builders.contextual_copy import generate_contextual_component_message
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class ErrorComponent(BaseComponent):
    component_type = ComponentType.ERROR

    async def build(self, context: ComponentContext) -> ChatComponent:
        fallback = str(context.error_message or "").strip()
        if not fallback:
            fallback = await generate_contextual_component_message(
                kind="error",
                context=context,
            )
        if not fallback:
            fallback = reply_tone.pick_variant(
                user_text=context.user_text,
                key="error:default",
                variants=[
                    "I couldn't process this request right now.",
                    "Something went wrong while processing this request.",
                    "I hit an issue while handling that request. Please try again.",
                ],
            )
        return ChatComponent(
            type=self.component_type,
            data={"message": fallback},
        )
