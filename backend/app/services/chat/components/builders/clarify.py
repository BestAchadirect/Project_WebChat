from __future__ import annotations

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class ClarifyComponent(BaseComponent):
    component_type = ComponentType.CLARIFY

    async def build(self, context: ComponentContext) -> ChatComponent:
        reason = str(context.ambiguity_reason or "missing details")
        message = "Please share more detail so I can match products accurately."
        if reason == "compare_requires_two_skus":
            message = "Please provide two SKU codes to compare, for example: `Compare SKU123 and SKU124`."
        elif reason == "compare_not_supported":
            message = "Compare view is currently unavailable. Share one SKU or product filters and I will show matching items."
        elif reason == "compare_missing_sku":
            missing = list((context.debug or {}).get("compare_missing_skus") or [])
            if missing:
                message = (
                    "I could not find these SKU(s): "
                    + ", ".join([str(item) for item in missing[:5]])
                    + ". Please check the codes and try again."
                )
            else:
                message = "I could not find one or more SKU codes to compare. Please verify the SKUs and try again."
        elif reason == "image_only_no_results":
            message = "No matching products currently have images. Ask for SKU/price/stock."
        elif reason == "image_request_missing_context":
            message = (
                "Sure, which product are you looking for? "
                "Share SKU or details like type, material, and gauge, and I can show images."
            )
        elif reason == "attribute_list_no_results":
            message = "I could not find matching attribute options for that filter. Try a broader product filter."
        return ChatComponent(
            type=self.component_type,
            data={
                "message": message,
                "reason": reason,
            },
        )
