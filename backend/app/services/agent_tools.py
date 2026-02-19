from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.product import Product, ProductEmbedding, StockStatus
from app.schemas.chat import ProductCard
from app.services.eav_service import eav_service
from app.services.knowledge_pipeline import KnowledgePipeline
from app.services.llm_service import llm_service


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

ALLOWED_PRODUCT_FILTERS = {
    "min_price",
    "max_price",
    "stock_status",
    "category",
    "material",
    "jewelry_type",
    "color",
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
        self._knowledge_pipeline = KnowledgePipeline(db=db, log_event=_no_op_log_event)

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
    def _merge_product_attrs(
        base_attrs: Optional[Dict[str, Any]],
        eav_attrs: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        attrs = dict(base_attrs or {})
        if eav_attrs:
            for key, value in eav_attrs.items():
                if value is None:
                    continue
                attrs[key] = value
        return attrs

    @staticmethod
    def _normalize_filters(filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        payload = dict(filters or {})
        clean: Dict[str, Any] = {}

        for key, value in payload.items():
            if key not in ALLOWED_PRODUCT_FILTERS:
                continue
            if value is None:
                continue
            if isinstance(value, str):
                trimmed = value.strip()
                if not trimmed:
                    continue
                clean[key] = trimmed
            else:
                clean[key] = value
        return clean

    @staticmethod
    def _matches_filters(card: ProductCard, filters: Dict[str, Any]) -> bool:
        if not filters:
            return True

        attributes = card.attributes or {}
        min_price = filters.get("min_price")
        max_price = filters.get("max_price")
        stock_status = filters.get("stock_status")
        category = filters.get("category")
        material = filters.get("material")
        jewelry_type = filters.get("jewelry_type")
        color = filters.get("color")

        if min_price is not None:
            try:
                if float(card.price) < float(min_price):
                    return False
            except Exception:
                return False
        if max_price is not None:
            try:
                if float(card.price) > float(max_price):
                    return False
            except Exception:
                return False

        if stock_status is not None:
            desired = str(stock_status).strip().lower()
            actual = str(card.stock_status or "").strip().lower()
            if desired and desired != actual:
                return False

        for key, expected in (
            ("category", category),
            ("material", material),
            ("jewelry_type", jewelry_type),
            ("color", color),
        ):
            if expected is None:
                continue
            actual = str(attributes.get(key) or "").strip().lower()
            if actual != str(expected).strip().lower():
                return False

        return True

    def _product_to_card(
        self,
        *,
        product: Product,
        eav_attrs: Optional[Dict[str, Any]] = None,
    ) -> ProductCard:
        attrs = self._merge_product_attrs(product.attributes, eav_attrs)
        return ProductCard(
            id=product.id,
            object_id=product.object_id,
            sku=product.sku,
            legacy_sku=product.legacy_sku or [],
            name=product.name,
            description=product.description,
            price=product.price,
            currency=product.currency,
            stock_status=product.stock_status,
            image_url=product.image_url,
            product_url=product.product_url,
            attributes=attrs,
        )

    async def _vector_search_products(
        self,
        *,
        query_embedding: List[float],
        limit: int,
    ) -> List[Tuple[Product, float]]:
        distance_col = ProductEmbedding.embedding.cosine_distance(query_embedding).label("distance")
        model = getattr(settings, "PRODUCT_EMBEDDING_MODEL", settings.EMBEDDING_MODEL)

        subq = (
            select(
                ProductEmbedding.product_id.label("product_id"),
                distance_col,
            )
            .join(Product, Product.id == ProductEmbedding.product_id)
            .where(Product.is_active.is_(True))
            .where(or_(ProductEmbedding.model.is_(None), ProductEmbedding.model == model))
            .order_by(distance_col)
            .limit(limit)
            .subquery()
        )
        stmt = (
            select(Product, subq.c.distance)
            .join(subq, Product.id == subq.c.product_id)
            .order_by(
                case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                subq.c.distance,
            )
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        return [(product, float(distance)) for product, distance in rows]

    async def search_products(self, args: SearchProductsArgs) -> Dict[str, Any]:
        page_size = args.page_size
        page = args.page
        filters = self._normalize_filters(args.filters)

        query_embedding = await llm_service.generate_embedding(args.query)
        max_items = max(1, int(getattr(settings, "AGENTIC_MAX_TOOL_RESULT_ITEMS", 10)))
        candidate_limit = min(400, max(max_items * 6, page * page_size * 4, 40))
        rows = await self._vector_search_products(query_embedding=query_embedding, limit=candidate_limit)

        if not rows:
            return {
                "items": [],
                "totalItems": 0,
                "page": page,
                "pageSize": page_size,
                "totalPages": 1,
            }

        product_ids = [product.id for product, _distance in rows]
        attr_map = await eav_service.get_product_attributes(self.db, product_ids)
        cards: List[ProductCard] = [
            self._product_to_card(product=product, eav_attrs=attr_map.get(product.id))
            for product, _distance in rows
        ]
        filtered = [card for card in cards if self._matches_filters(card, filters)]

        total_items = len(filtered)
        total_pages = max(1, ((total_items - 1) // page_size) + 1) if total_items > 0 else 1
        safe_page = min(page, total_pages)
        start = (safe_page - 1) * page_size
        end = start + page_size

        page_items = filtered[start:end]
        if len(page_items) > max_items:
            page_items = page_items[:max_items]

        return {
            "items": [item.model_dump(mode="json") for item in page_items],
            "totalItems": total_items,
            "page": safe_page,
            "pageSize": page_size,
            "totalPages": total_pages,
        }

    async def get_product_details(self, args: GetProductDetailsArgs) -> Dict[str, Any]:
        stmt = (
            select(Product)
            .where(func.lower(Product.sku) == args.sku.lower())
            .where(Product.is_active.is_(True))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        product = result.scalar_one_or_none()
        if not product:
            return {"found": False, "sku": args.sku}

        attr_map = await eav_service.get_product_attributes(self.db, [product.id])
        card = self._product_to_card(product=product, eav_attrs=attr_map.get(product.id))
        return {
            "found": True,
            "product": card.model_dump(mode="json"),
        }

    async def search_knowledge_base(self, args: SearchKnowledgeBaseArgs) -> Dict[str, Any]:
        query_embedding = await llm_service.generate_embedding(args.query)
        search_limit = max(args.limit, int(getattr(settings, "AGENTIC_MAX_TOOL_RESULT_ITEMS", 10)))
        sources, _best = await self._knowledge_pipeline.search_knowledge(
            query_text=args.query,
            query_embedding=query_embedding,
            limit=search_limit,
            must_tags=None,
            boost_tags=None,
            run_id=self.run_id,
        )
        items: List[Dict[str, Any]] = []
        for source in sources:
            if args.category and (source.category or "").strip().lower() != args.category.strip().lower():
                continue
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
        stmt = (
            select(Product)
            .where(func.lower(Product.sku) == args.sku.lower())
            .where(Product.is_active.is_(True))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        product = result.scalar_one_or_none()
        if not product:
            return {
                "found": False,
                "sku": args.sku,
                "source": "db",
            }
        last_sync = product.last_stock_sync_at
        if isinstance(last_sync, datetime):
            last_sync_str = last_sync.isoformat()
        else:
            last_sync_str = None
        return {
            "found": True,
            "sku": product.sku,
            "stock_status": getattr(product.stock_status, "value", str(product.stock_status)),
            "last_stock_sync_at": last_sync_str,
            "source": "db",
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
