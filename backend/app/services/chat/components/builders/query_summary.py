from __future__ import annotations

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class QuerySummaryComponent(BaseComponent):
    component_type = ComponentType.QUERY_SUMMARY

    async def build(self, context: ComponentContext) -> ChatComponent:
        return ChatComponent(
            type=self.component_type,
            data={"text": str(context.query_summary or context.user_text or "").strip()},
        )

