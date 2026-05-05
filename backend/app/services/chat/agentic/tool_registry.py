from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.chat import KnowledgeSource, ProductCard
from app.services.catalog.product_search import CatalogProductSearchService
from app.services.chat.routing import routing_policy
from app.services.chat.agentic.tool_handlers import (
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


@dataclass(frozen=True)
class NormalizedAgentToolResult:
    tool_name: str
    status: str
    result_count: int = 0
    products: List[ProductCard] = field(default_factory=list)
    sources: List[KnowledgeSource] = field(default_factory=list)


class SearchProductFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_price: Optional[float] = Field(default=None, ge=0)
    max_price: Optional[float] = Field(default=None, ge=0)
    stock_status: Optional[str] = Field(default=None, min_length=1, max_length=64)
    category: Optional[str] = Field(default=None, min_length=1, max_length=128)
    body_part: Optional[str] = Field(default=None, min_length=1, max_length=128)
    feature: Optional[str] = Field(default=None, min_length=1, max_length=128)
    presentation_type: Optional[str] = Field(default=None, min_length=1, max_length=128)
    material: Optional[str] = Field(default=None, min_length=1, max_length=128)
    jewelry_type: Optional[str] = Field(default=None, min_length=1, max_length=128)
    color: Optional[str] = Field(default=None, min_length=1, max_length=128)
    theme: Optional[str] = Field(default=None, min_length=1, max_length=128)

    @field_validator(
        "stock_status",
        "category",
        "body_part",
        "feature",
        "presentation_type",
        "material",
        "jewelry_type",
        "color",
        "theme",
    )
    @classmethod
    def validate_text_filter(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        clean = value.strip()
        return clean or None

    @model_validator(mode="after")
    def validate_price_range(self) -> "SearchProductFilters":
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("min_price cannot be greater than max_price")
        return self

    def to_filter_map(self) -> Dict[str, Any]:
        return self.model_dump(mode="python", exclude_none=True)


class SearchProductsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    query: str = Field(min_length=2, max_length=200)
    filters: Optional[SearchProductFilters] = None
    page: int = Field(default=1, ge=1, le=20)
    page_size: int = Field(default=10, alias="pageSize", ge=1, le=20)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("query cannot be empty")
        return clean


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
                            "filters": {
                                "type": "object",
                                "properties": {
                                    "min_price": {"type": "number", "minimum": 0},
                                    "max_price": {"type": "number", "minimum": 0},
                                    "stock_status": {"type": "string", "maxLength": 64},
                                    "category": {"type": "string", "maxLength": 128},
                                    "body_part": {"type": "string", "maxLength": 128},
                                    "feature": {"type": "string", "maxLength": 128},
                                    "presentation_type": {"type": "string", "maxLength": 128},
                                    "material": {"type": "string", "maxLength": 128},
                                    "jewelry_type": {"type": "string", "maxLength": 128},
                                    "color": {"type": "string", "maxLength": 128},
                                    "theme": {"type": "string", "maxLength": 128},
                                },
                                "additionalProperties": False,
                            },
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

    @staticmethod
    def _tool_envelope(*, tool_name: str, status: str, source: str) -> Dict[str, Any]:
        return {
            "tool": tool_name,
            "status": status,
            "source": source,
        }

    @staticmethod
    def _product_payload(card: Any) -> Dict[str, Any]:
        if hasattr(card, "model_dump"):
            return card.model_dump(mode="json")
        return dict(card or {})

    @classmethod
    def _candidate_payload(cls, card: Any) -> Dict[str, Any]:
        return cls._product_payload(card)

    @staticmethod
    def _knowledge_payload(source: Any) -> Dict[str, Any]:
        return {
            "source_id": getattr(source, "source_id", None),
            "title": getattr(source, "title", None),
            "snippet": getattr(source, "content_snippet", None),
            "url": getattr(source, "url", None),
            "category": str(getattr(source, "category", "") or "").strip() or None,
            "relevance": getattr(source, "relevance", 0.0),
        }

    @staticmethod
    def _result_status(result: Dict[str, Any]) -> str:
        return str(result.get("status") or ("error" if "error" in result else "ok")).strip().lower()

    @staticmethod
    def _result_count(result: Any) -> int:
        if isinstance(result, dict):
            total_items = result.get("totalItems")
            if isinstance(total_items, int):
                return max(0, total_items)
            items = result.get("items")
            if isinstance(items, list):
                return len(items)
            if result.get("product") is not None:
                return 1
            candidates = result.get("candidates")
            if isinstance(candidates, list):
                return len(candidates)
            if result.get("found") is True:
                return 1
            return 0
        if isinstance(result, list):
            return len(result)
        return 0

    @staticmethod
    def _normalize_product_cards(items: Any) -> List[ProductCard]:
        normalized: List[ProductCard] = []
        if not isinstance(items, list):
            return normalized
        for item in items:
            try:
                normalized.append(item if isinstance(item, ProductCard) else ProductCard.model_validate(item))
            except Exception:
                continue
        return normalized

    @staticmethod
    def _normalize_knowledge_sources(items: Any) -> List[KnowledgeSource]:
        normalized: List[KnowledgeSource] = []
        if not isinstance(items, list):
            return normalized
        for index, item in enumerate(items, start=1):
            try:
                if isinstance(item, KnowledgeSource):
                    normalized.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                payload = dict(item)
                if "content_snippet" not in payload:
                    payload["content_snippet"] = str(payload.get("snippet") or "")
                if "source_id" not in payload or not str(payload.get("source_id") or "").strip():
                    payload["source_id"] = f"kb_{index}"
                if "title" not in payload or not str(payload.get("title") or "").strip():
                    payload["title"] = "Knowledge"
                if "relevance" not in payload:
                    payload["relevance"] = 0.0
                normalized.append(KnowledgeSource.model_validate(payload))
            except Exception:
                continue
        return normalized

    @classmethod
    def normalize_tool_result(cls, *, tool_name: str, result: Dict[str, Any]) -> NormalizedAgentToolResult:
        status = cls._result_status(result)
        result_count = cls._result_count(result)
        products: List[ProductCard] = []
        sources: List[KnowledgeSource] = []

        if tool_name == TOOL_SEARCH_PRODUCTS:
            products = cls._normalize_product_cards(result.get("items"))
        elif tool_name in {TOOL_GET_PRODUCT_DETAILS, TOOL_CHECK_INVENTORY_DB}:
            payload = result.get("product")
            if payload is not None:
                products = cls._normalize_product_cards([payload])
            elif isinstance(result.get("candidates"), list):
                products = cls._normalize_product_cards(result.get("candidates"))
        elif tool_name == TOOL_SEARCH_KNOWLEDGE_BASE:
            sources = cls._normalize_knowledge_sources(result.get("items"))

        return NormalizedAgentToolResult(
            tool_name=tool_name,
            status=status,
            result_count=result_count,
            products=products,
            sources=sources,
        )

    async def search_products(self, args: SearchProductsArgs) -> Dict[str, Any]:
        max_items = max(1, int(getattr(settings, "AGENTIC_MAX_TOOL_RESULT_ITEMS", 10)))
        page_size = min(args.page_size, max_items)
        page = args.page
        filters = self._normalize_filters(args.filters.to_filter_map() if args.filters is not None else None)

        query_embedding = await llm_service.generate_embedding(args.query)
        candidate_limit = min(400, max(max_items * 6, page * page_size * 4, 40))
        search_result = await self._catalog_search.vector_search(
            query_embedding=query_embedding,
            limit=candidate_limit,
            candidate_limit=candidate_limit,
        )
        if not search_result.cards:
            return {
                **self._tool_envelope(
                    tool_name=TOOL_SEARCH_PRODUCTS,
                    status="empty",
                    source="catalog_db",
                ),
                "query": args.query,
                "filters": dict(filters),
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
            **self._tool_envelope(
                tool_name=TOOL_SEARCH_PRODUCTS,
                status="ok" if total_items > 0 else "empty",
                source="catalog_db",
            ),
            "query": args.query,
            "filters": dict(filters),
            "items": [self._product_payload(item) for item in page_items],
            "totalItems": total_items,
            "page": safe_page,
            "pageSize": page_size,
            "totalPages": total_pages,
        }

    async def get_product_details(self, args: GetProductDetailsArgs) -> Dict[str, Any]:
        resolved = await self._catalog_search.resolve_product_reference(args.sku)
        status = str(resolved.get("status") or "")
        if status == "ambiguous":
            return {
                **self._tool_envelope(
                    tool_name=TOOL_GET_PRODUCT_DETAILS,
                    status="ambiguous",
                    source="catalog_db",
                ),
                "found": False,
                "ambiguous": True,
                "sku": args.sku,
                "matched_by": str(resolved.get("matched_by") or ""),
                "candidates": [
                    self._candidate_payload(card)
                    for card in list(resolved.get("candidates") or [])[:3]
                ],
            }
        card = resolved.get("product")
        if status != "resolved" or card is None:
            return {
                **self._tool_envelope(
                    tool_name=TOOL_GET_PRODUCT_DETAILS,
                    status="not_found",
                    source="catalog_db",
                ),
                "found": False,
                "ambiguous": False,
                "sku": args.sku,
                "matched_by": "",
                "candidates": [],
            }

        return {
            **self._tool_envelope(
                tool_name=TOOL_GET_PRODUCT_DETAILS,
                status="ok",
                source="catalog_db",
            ),
            "found": True,
            "ambiguous": False,
            "sku": args.sku,
            "matched_by": str(resolved.get("matched_by") or "direct_reference"),
            "product": self._product_payload(card),
            "candidates": [],
        }

    async def search_knowledge_base(self, args: SearchKnowledgeBaseArgs) -> Dict[str, Any]:
        query_embedding = await llm_service.generate_embedding(args.query)
        search_limit = max(args.limit, int(getattr(settings, "AGENTIC_MAX_TOOL_RESULT_ITEMS", 10)))
        clean_category = str(args.category or "").strip() or None
        sources = await self._knowledge_retrieval.search(
            query_text=args.query,
            query_embedding=query_embedding,
            category=args.category,
            limit=search_limit,
            run_id=self.run_id,
        )
        items: List[Dict[str, Any]] = []
        for source in sources:
            items.append(self._knowledge_payload(source))
            if len(items) >= args.limit:
                break
        return {
            **self._tool_envelope(
                tool_name=TOOL_SEARCH_KNOWLEDGE_BASE,
                status="ok" if items else "empty",
                source="knowledge_db",
            ),
            "items": items,
            "totalItems": len(items),
            "query": args.query,
            "category": clean_category,
            "limit": args.limit,
        }

    async def check_inventory_db(self, args: CheckInventoryArgs) -> Dict[str, Any]:
        exact = await self._catalog_search.get_inventory_snapshot(args.sku)
        if bool(exact.get("found")):
            return {
                **self._tool_envelope(
                    tool_name=TOOL_CHECK_INVENTORY_DB,
                    status="ok",
                    source=str(exact.get("source") or "db"),
                ),
                "ambiguous": False,
                "requested_sku": args.sku,
                "matched_by": "",
                "candidates": [],
                **dict(exact),
            }

        resolved = await self._catalog_search.resolve_product_reference(args.sku)
        status = str(resolved.get("status") or "")
        if status == "ambiguous":
            return {
                **self._tool_envelope(
                    tool_name=TOOL_CHECK_INVENTORY_DB,
                    status="ambiguous",
                    source="db",
                ),
                "found": False,
                "ambiguous": True,
                "sku": args.sku,
                "requested_sku": args.sku,
                "matched_by": str(resolved.get("matched_by") or ""),
                "candidates": [
                    self._candidate_payload(card)
                    for card in list(resolved.get("candidates") or [])[:3]
                ],
            }
        card = resolved.get("product")
        if status == "resolved" and card is not None:
            snapshot = await self._catalog_search.get_inventory_snapshot(str(getattr(card, "sku", "") or args.sku))
            return {
                **self._tool_envelope(
                    tool_name=TOOL_CHECK_INVENTORY_DB,
                    status="ok" if bool(snapshot.get("found")) else "not_found",
                    source=str(snapshot.get("source") or "db"),
                ),
                "ambiguous": False,
                "matched_by": str(resolved.get("matched_by") or ""),
                "requested_sku": args.sku,
                "candidates": [],
                **dict(snapshot),
            }
        return {
            **self._tool_envelope(
                tool_name=TOOL_CHECK_INVENTORY_DB,
                status="not_found",
                source=str(exact.get("source") or "db"),
            ),
            "ambiguous": False,
            "requested_sku": args.sku,
            "matched_by": "",
            "candidates": [],
            **dict(exact),
        }

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
        workflow: str,
        sku_token: Optional[str],
    ) -> bool:
        return routing_policy.is_agentic_tool_suitable(
            user_text=user_text,
            workflow=workflow,
            sku_token=sku_token,
        )


def agent_system_prompt(reply_language: str) -> str:
    return (
        "You are a read-only e-commerce assistant with tool access.\n"
        f"Respond in {reply_language}.\n"
        "Use tools when you need concrete product, inventory, or knowledge data.\n"
        "Never invent SKU details or stock status.\n"
        "If data is missing, state that clearly and ask a focused follow-up question.\n"
    )
