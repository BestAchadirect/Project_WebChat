from __future__ import annotations

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class KnowledgeAnswerComponent(BaseComponent):
    component_type = ComponentType.KNOWLEDGE_ANSWER

    async def build(self, context: ComponentContext) -> ChatComponent:
        return ChatComponent(
            type=self.component_type,
            data={
                "answer": str(context.knowledge_answer or "").strip(),
                "source_count": len(context.knowledge_sources or []),
            },
        )

