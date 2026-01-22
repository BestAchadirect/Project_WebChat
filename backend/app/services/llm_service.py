import json
import time
import hashlib
from collections import OrderedDict
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.logging import get_logger
from app.prompts.system_prompts import ui_localization_prompt, unified_nlu_prompt

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
    
    async def run_nlu(
        self,
        *,
        user_message: str,
        history: Optional[List[Dict[str, str]]] = None,
        locale: Optional[str] = None,
        supported_currencies: Optional[List[str]] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return a unified NLU analysis for the user message (strict JSON)."""
        system_prompt = unified_nlu_prompt(supported_currencies)
        messages = [{"role": "system", "content": system_prompt}]
        if locale:
            messages.append({"role": "system", "content": f"Locale: {locale}"})
        
        if history:
            messages.extend(history)
            
        messages.append({"role": "user", "content": user_message})

        use_model = model or getattr(settings, "NLU_MODEL", None) or self.model
        token_limit = max_tokens or int(getattr(settings, "NLU_MAX_TOKENS", 250))

        try:
            return await self.generate_chat_json(
                messages=messages,
                model=use_model,
                temperature=0.0,
                max_tokens=token_limit,
            )
        except Exception as e:
            logger.error(f"NLU analysis failed: {e}")
            return {}

    async def translate_product_descriptions(
        self,
        *,
        descriptions: List[str],
        reply_language: str,
        model: Optional[str] = None,
    ) -> List[str]:
        """Translate a batch of product descriptions into the target language."""
        if not descriptions or not reply_language:
            return descriptions

        # Use a high-density JSON prompt for batch translation
        system = (
            f"You are a professional translator. Translate the provided list of English product descriptions into {reply_language}.\n"
            "Return ONLY a JSON object with a 'translations' key containing the list of translated strings.\n"
            "Keep technical terms (SKU, diameter, etc.) as is if appropriate for the destination language."
        )
        user = json.dumps({"descriptions": descriptions}, ensure_ascii=True)
        
        use_model = model or getattr(settings, "UI_LOCALIZATION_MODEL", None) or self.model
        
        try:
            data = await self.generate_chat_json(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                model=use_model,
                temperature=0.0,
                max_tokens=1000, # Allow more for batch
            )
            translated = data.get("translations", [])
            if isinstance(translated, list) and len(translated) == len(descriptions):
                return [str(t).strip() for t in translated]
            return descriptions
        except Exception as e:
            logger.error(f"Batch description translation failed: {e}")
            return descriptions

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

# Singleton instance
llm_service = LLMService()
