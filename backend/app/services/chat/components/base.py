from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Set

from app.schemas.chat import ChatComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class BaseComponent(ABC):
    component_type: ComponentType
    required_fields: Set[str] = set()

    @abstractmethod
    async def build(self, context: ComponentContext) -> ChatComponent:
        raise NotImplementedError

