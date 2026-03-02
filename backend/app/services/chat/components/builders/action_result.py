from __future__ import annotations

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class ActionResultComponent(BaseComponent):
    component_type = ComponentType.ACTION_RESULT

    async def build(self, context: ComponentContext) -> ChatComponent:
        debug = dict(context.debug or {})
        values = list(debug.get("attribute_list_values") or [])
        target = str(debug.get("attribute_list_target") or "").strip().lower()
        if values and target:
            label_map = {
                "material": "materials",
                "color": "colors",
                "gauge": "gauges",
                "threading": "threading options",
                "jewelry_type": "jewelry types",
            }
            label = label_map.get(target, f"{target} options")
            preview = ", ".join([str(item) for item in values[:12]])
            message = f"We currently sell these {label}: {preview}."
            return ChatComponent(
                type=self.component_type,
                data={
                    "status": "ok",
                    "message": message,
                    "attribute": target,
                    "values": values,
                    "count": len(values),
                },
            )
        return ChatComponent(
            type=self.component_type,
            data={"status": "ok", "message": "Action completed."},
        )
