import json
import time
import hashlib
from collections import OrderedDict
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.logging import get_logger
from app.prompts.system_prompts import ui_localization_prompt, currency_intent_prompt

logger = get_logger(__name__)


class _EmbeddingCache:
    def __init__(self, *, max_items: int, ttl_seconds: float):
        self.max_items = max(0, int(max_items))
        self.ttl_seconds = float(ttl_seconds)
        self._data: OrderedDict[str, tuple[float, List[float]]] = OrderedDict()

    def get(self, key: str) -> Optional[List[float]]:
        if not key or self.max_items <= 0:
            return None
        item = self._data.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at and expires_at < time.time():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: List[float]) -> None:
        if not key or self.max_items <= 0:
            return
        expires_at = 0.0
        if self.ttl_seconds > 0:
            expires_at = time.time() + self.ttl_seconds
        self._data[key] = (expires_at, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)


class _TextCache:
    def __init__(self, *, max_items: int, ttl_seconds: float):
        self.max_items = max(0, int(max_items))
        self.ttl_seconds = float(ttl_seconds)
        self._data: OrderedDict[str, tuple[float, Dict[str, str]]] = OrderedDict()

    def get(self, key: str) -> Optional[Dict[str, str]]:
        if not key or self.max_items <= 0:
            return None
        item = self._data.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at and expires_at < time.time():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: Dict[str, str]) -> None:
        if not key or self.max_items <= 0:
            return
        expires_at = 0.0
        if self.ttl_seconds > 0:
            expires_at = time.time() + self.ttl_seconds
        self._data[key] = (expires_at, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)


class LLMService:
    """Service for interacting with OpenAI LLM and embeddings."""
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.OPENAI_MODEL
        self.embedding_model = settings.EMBEDDING_MODEL
        self._embedding_cache = _EmbeddingCache(
            max_items=int(getattr(settings, "EMBEDDING_CACHE_MAX_ITEMS", 512)),
            ttl_seconds=float(getattr(settings, "EMBEDDING_CACHE_TTL_SECONDS", 3600)),
        )
        self._ui_text_cache = _TextCache(
            max_items=int(getattr(settings, "UI_LOCALIZATION_CACHE_MAX_ITEMS", 256)),
            ttl_seconds=float(getattr(settings, "UI_LOCALIZATION_CACHE_TTL_SECONDS", 3600)),
        )

    def _embedding_cache_key(self, text: str) -> str:
        if text is None:
            text = ""
        payload = f"{self.embedding_model}:{text}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"{self.embedding_model}:{digest}"

    @staticmethod
    def _ui_cache_key(reply_language: str, items: Dict[str, str]) -> str:
        payload = json.dumps(
            {"lang": reply_language, "items": items},
            sort_keys=True,
            ensure_ascii=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"ui:{digest}"
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for a text."""
        try:
            cache_key = self._embedding_cache_key(text)
            cached = self._embedding_cache.get(cache_key)
            if cached is not None:
                return cached
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            embedding = response.data[0].embedding
            self._embedding_cache.set(cache_key, embedding)
            return embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise
    
    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=texts
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}")
            raise
    
    async def generate_chat_response(
        self,
        messages: List[dict],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> str:
        """Generate a chat response using the LLM."""
        try:
            response = await self.client.chat.completions.create(
                model=model or self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error generating chat response: {e}")
            raise

    async def generate_chat_json(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = 300,
    ) -> Dict[str, Any]:
        """Generate strict JSON output using response_format=json_object."""
        response = await self.client.chat.completions.create(
            model=model or self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
    
    async def plan_retrieval(
        self,
        *,
        user_message: str,
        locale: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return a retrieval plan for the user message (strict JSON)."""
        system_prompt = (
            "You are a retrieval planner for an e-commerce chatbot.\n"
            "Your job is to interpret the user message and return a STRICT JSON plan.\n\n"
            "Return JSON with keys:\n"
            "- task: one of [\"product_search\", \"shipping_region\", \"policy\", \"contact\", \"general\", \"mixed\"]\n"
            "- is_smalltalk: true/false (greeting/thanks/social)\n"
            "- is_meta_question: true/false (about the assistant, how it works, AI/human)\n"
            "- is_catalog_browse: true/false (asks to browse categories / what products you have)\n"
            "- kb_query: short query string for knowledge base lookup (empty if not needed)\n"
            "- product_query: short query string for product search (empty if not needed)\n"
            "- entities: object with keys like country, state, sku, jewelry_type, gauge, material, budget\n"
            "- needs_clarification: true/false\n"
            "- clarifying_question: string (required if needs_clarification)\n"
            "- confidence: number 0 to 1\n\n"
            "Rules:\n"
            "- If is_smalltalk=true, task must be general and needs_clarification=false.\n"
            "- If is_meta_question=true, task must be general and needs_clarification=false.\n"
            "- If is_catalog_browse=true, task should be product_search and needs_clarification=true with a short category question.\n"
            "- If the user asks about shipping region (e.g., \"sell in US\"), use task=shipping_region and kb_query about shipping/availability.\n"
            "- If the user wants recommendations or items, use task=product_search and product_query.\n"
            "- If the user asks about refunds, payment, MOQ, or policies, use task=policy and kb_query.\n"
            "- If the user asks for phone, email, or WhatsApp, use task=contact and kb_query.\n"
            "- Use task=mixed if both product and policy are clearly requested.\n"
            "- Do NOT echo the user message as clarifying_question.\n"
            "- Ask only ONE clarifying question if needed.\n"
        )

        messages = [{"role": "system", "content": system_prompt}]
        if locale:
            messages.append({"role": "system", "content": f"Locale: {locale}"})
        messages.append({"role": "user", "content": user_message})

        use_model = model or getattr(settings, "PLANNER_MODEL", None) or self.model
        token_limit = max_tokens or int(getattr(settings, "PLANNER_MAX_TOKENS", 200))

        data = await self.generate_chat_json(
            messages=messages,
            model=use_model,
            temperature=0.0,
            max_tokens=token_limit,
        )
        return data

    async def localize_ui_strings(
        self,
        *,
        items: Dict[str, str],
        reply_language: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, str]:
        if not items:
            return {}
        if not reply_language:
            return items

        cache_key = self._ui_cache_key(reply_language, items)
        cached = self._ui_text_cache.get(cache_key)
        if cached is not None:
            return cached

        system = ui_localization_prompt(reply_language)
        user = f"Strings JSON:\n{json.dumps(items, ensure_ascii=True)}"
        use_model = model or getattr(settings, "UI_LOCALIZATION_MODEL", None) or self.model
        token_limit = max_tokens or int(getattr(settings, "UI_LOCALIZATION_MAX_TOKENS", 220))
        temp = temperature
        if temp is None:
            temp = float(getattr(settings, "UI_LOCALIZATION_TEMPERATURE", 0.1))

        try:
            data = await self.generate_chat_json(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                model=use_model,
                temperature=float(temp),
                max_tokens=token_limit,
            )
        except Exception as e:
            logger.error(f"UI localization failed: {e}")
            return items

        if not isinstance(data, dict):
            return items

        localized: Dict[str, str] = {}
        for key, value in items.items():
            candidate = data.get(key)
            if isinstance(candidate, str) and candidate.strip():
                localized[key] = candidate.strip()
            else:
                localized[key] = value

        self._ui_text_cache.set(cache_key, localized)
        return localized

    async def detect_currency_intent(
        self,
        *,
        user_message: str,
        locale: Optional[str] = None,
        supported_currencies: Optional[List[str]] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        system_prompt = currency_intent_prompt(supported_currencies or [])
        messages = [{"role": "system", "content": system_prompt}]
        if locale:
            messages.append({"role": "system", "content": f"Locale: {locale}"})
        messages.append({"role": "user", "content": user_message})

        use_model = model or getattr(settings, "CURRENCY_INTENT_MODEL", None) or self.model
        token_limit = max_tokens or int(getattr(settings, "CURRENCY_INTENT_MAX_TOKENS", 80))

        try:
            return await self.generate_chat_json(
                messages=messages,
                model=use_model,
                temperature=0.0,
                max_tokens=token_limit,
            )
        except Exception as e:
            logger.error(f"Currency intent detection failed: {e}")
            return {}

# Singleton instance
llm_service = LLMService()
