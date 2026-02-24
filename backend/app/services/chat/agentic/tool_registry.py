from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.catalog.product_search import CatalogProductSearchService
from app.services.chat.agentic.tool_handlers import (
    ALLOWED_PRODUCT_FILTERS,
    normalize_product_filters,
    paginate_items,
    product_card_matches_filters,
)
from app.services.knowledge.retrieval import KnowledgeRetrievalService
from app.services.ai.llm_service import llm_service


TOOL_SEARCH_PRODUCTS = "search_products"
TOOL_GET_PRODUCT_DETAILS = "get_product_details"
TOOL_SEARCH_KNOWLEDGE_BASE = "search_knowledge_base"
TOOL_CHECK_INVENTORY_DB = "check_inventory_db"

SUPPORTED_TOOLS = {
    TOOL_SEARCH_PRODUCTS,
    TOOL_GET_PRODUCT_DETAILS,
    TOOL_SEARCH_KNOWLEDGE_BASE,
    TOOL_CHECK_INVENTORY_DB,
}

class SearchProductsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    query: str = Field(min_length=2, max_length=200)
    filters: Optional[Dict[str, Any]] = None
    page: int = Field(default=1, ge=1, le=20)
    page_size: int = Field(default=10, alias="pageSize", ge=1, le=20)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("query cannot be empty")
        return clean

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        invalid = [key for key in value.keys() if key not in ALLOWED_PRODUCT_FILTERS]
        if invalid:
            raise ValueError(f"unsupported filter keys: {', '.join(sorted(invalid))}")
        return value


class GetProductDetailsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=2, max_length=64)

    @field_validator("sku")
    @classmethod
    def validate_sku(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("sku cannot be empty")
        return clean


class SearchKnowledgeBaseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=200)
    category: Optional[str] = Field(default=None, max_length=128)
    limit: int = Field(default=5, ge=1, le=5)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("query cannot be empty")
        return clean

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        clean = value.strip()
        return clean or None


class CheckInventoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=2, max_length=64)

    @field_validator("sku")
    @classmethod
    def validate_sku(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("sku cannot be empty")
        return clean


def _no_op_log_event(*_: Any, **__: Any) -> None:
    return


class AgentToolRegistry:
    def __init__(self, db: AsyncSession, *, run_id: Optional[str] = None):
        self.db = db
        self.run_id = run_id
        self._catalog_search = CatalogProductSearchService(db=db)
        self._knowledge_retrieval = KnowledgeRetrievalService(db=db, log_event=_no_op_log_event)

    @staticmethod
    def tool_definitions() -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": TOOL_SEARCH_PRODUCTS,
                    "description": "Search products by query and optional filters. Returns paged product cards.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "minLength": 2, "maxLength": 200},
                            "filters": {"type": "object"},
                            "page": {"type": "integer", "minimum": 1, "maximum": 20},
                            "pageSize": {"type": "integer", "minimum": 1, "maximum": 20},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": TOOL_GET_PRODUCT_DETAILS,
                    "description": "Get full product details for a specific SKU.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sku": {"type": "string", "minLength": 2, "maxLength": 64},
                        },
                        "required": ["sku"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": TOOL_SEARCH_KNOWLEDGE_BASE,
                    "description": "Search policy and FAQ knowledge base by query.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "minLength": 2, "maxLength": 200},
                            "category": {"type": "string", "maxLength": 128},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": TOOL_CHECK_INVENTORY_DB,
                    "description": "Check stock status from database for a SKU.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sku": {"type": "string", "minLength": 2, "maxLength": 64},
                        },
                        "required": ["sku"],
                        "additionalProperties": False,
                    },
                },
            },
        ]

    @staticmethod
    def _normalize_filters(filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return normalize_product_filters(filters)

    async def search_products(self, args: SearchProductsArgs) -> Dict[str, Any]:
        page_size = args.page_size
        page = args.page
        filters = self._normalize_filters(args.filters)

        query_embedding = await llm_service.generate_embedding(args.query)
        max_items = max(1, int(getattr(settings, "AGENTIC_MAX_TOOL_RESULT_ITEMS", 10)))
        candidate_limit = min(400, max(max_items * 6, page * page_size * 4, 40))
        search_result = await self._catalog_search.vector_search(
            query_embedding=query_embedding,
            limit=candidate_limit,
            candidate_limit=candidate_limit,
        )
        if not search_result.cards:
            return {
                "items": [],
                "totalItems": 0,
                "page": page,
                "pageSize": page_size,
                "totalPages": 1,
            }

        filtered = [card for card in search_result.cards if product_card_matches_filters(card, filters)]
        page_items, total_items, safe_page, total_pages = paginate_items(
            filtered,
            page=page,
            page_size=page_size,
            max_items=max_items,
        )

        return {
            "items": [item.model_dump(mode="json") for item in page_items],
            "totalItems": total_items,
            "page": safe_page,
            "pageSize": page_size,
            "totalPages": total_pages,
        }

    async def get_product_details(self, args: GetProductDetailsArgs) -> Dict[str, Any]:
        card = await self._catalog_search.get_product_by_sku(args.sku)
        if not card:
            return {"found": False, "sku": args.sku}

        return {
            "found": True,
            "product": card.model_dump(mode="json"),
        }

    async def search_knowledge_base(self, args: SearchKnowledgeBaseArgs) -> Dict[str, Any]:
        query_embedding = await llm_service.generate_embedding(args.query)
        search_limit = max(args.limit, int(getattr(settings, "AGENTIC_MAX_TOOL_RESULT_ITEMS", 10)))
        sources = await self._knowledge_retrieval.search(
            query_text=args.query,
            query_embedding=query_embedding,
            category=args.category,
            limit=search_limit,
            run_id=self.run_id,
        )
        items: List[Dict[str, Any]] = []
        for source in sources:
            items.append(
                {
                    "source_id": source.source_id,
                    "title": source.title,
                    "snippet": source.content_snippet,
                    "url": source.url,
                    "category": source.category,
                    "relevance": source.relevance,
                }
            )
            if len(items) >= args.limit:
                break
        return {
            "items": items,
            "totalItems": len(items),
            "query": args.query,
            "category": args.category,
        }

    async def check_inventory_db(self, args: CheckInventoryArgs) -> Dict[str, Any]:
        return await self._catalog_search.get_inventory_snapshot(args.sku)

    async def execute_tool(self, tool_name: str, raw_arguments: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == TOOL_SEARCH_PRODUCTS:
            args = SearchProductsArgs.model_validate(raw_arguments)
            return await self.search_products(args)
        if tool_name == TOOL_GET_PRODUCT_DETAILS:
            args = GetProductDetailsArgs.model_validate(raw_arguments)
            return await self.get_product_details(args)
        if tool_name == TOOL_SEARCH_KNOWLEDGE_BASE:
            args = SearchKnowledgeBaseArgs.model_validate(raw_arguments)
            return await self.search_knowledge_base(args)
        if tool_name == TOOL_CHECK_INVENTORY_DB:
            args = CheckInventoryArgs.model_validate(raw_arguments)
            return await self.check_inventory_db(args)
        raise ValueError(f"Unsupported tool: {tool_name}")

    @staticmethod
    def is_tool_suitable(
        *,
        user_text: str,
        intent: str,
        sku_token: Optional[str],
    ) -> bool:
        text = (user_text or "").strip().lower()
        if not text:
            return False
        if sku_token:
            return True
        if intent in {"browse_products", "search_specific"}:
            return True
        inventory_keywords = ("in stock", "inventory", "availability", "available", "stock")
        if any(token in text for token in inventory_keywords):
            return True
        detail_keywords = ("details", "detail", "spec", "specs", "sku", "product code", "master code")
        if any(token in text for token in detail_keywords):
            return True
        return False


def agent_system_prompt(reply_language: str) -> str:
    return (
        "You are a read-only e-commerce assistant with tool access.\n"
        f"Respond in {reply_language}.\n"
        "Use tools when you need concrete product, inventory, or knowledge data.\n"
        "Never invent SKU details or stock status.\n"
        "If data is missing, state that clearly and ask a focused follow-up question.\n"
    )
