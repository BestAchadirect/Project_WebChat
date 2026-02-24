import json
import time
import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
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


class TokenTracker:
    def __init__(self) -> None:
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_cached_prompt_tokens = 0
        self.calls: List[Dict[str, Any]] = []

    @staticmethod
    def _get_value(source: Any, key: str, default: Any = None) -> Any:
        if source is None:
            return default
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default)

    def add_usage(self, *, kind: str, model: str, usage: Any = None, cached: bool = False) -> None:
        prompt_tokens = int(self._get_value(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(self._get_value(usage, "completion_tokens", 0) or 0)
        total_tokens = self._get_value(usage, "total_tokens", None)
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens
        total_tokens = int(total_tokens or 0)

        details = self._get_value(usage, "prompt_tokens_details", None)
        cached_tokens = self._get_value(details, "cached_tokens", None)
        if cached_tokens is not None:
            cached_tokens = int(cached_tokens or 0)

        call: Dict[str, Any] = {
            "kind": kind,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
        if cached:
            call["cached"] = True
        if cached_tokens is not None:
            call["cached_prompt_tokens"] = cached_tokens

        self.calls.append(call)
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_tokens += total_tokens
        if cached_tokens is not None:
            self.total_cached_prompt_tokens += cached_tokens

    def summary(self) -> Dict[str, Any]:
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_prompt_tokens": self.total_cached_prompt_tokens,
            "by_call": list(self.calls),
        }


_token_tracker: ContextVar[Optional[TokenTracker]] = ContextVar("token_tracker", default=None)


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

    @contextmanager
    def track_tokens(self) -> TokenTracker:
        tracker = TokenTracker()
        token = _token_tracker.set(tracker)
        try:
            yield tracker
        finally:
            _token_tracker.reset(token)

    def begin_token_tracking(self) -> TokenTracker:
        tracker = TokenTracker()
        _token_tracker.set(tracker)
        return tracker

    def consume_token_usage(self) -> Optional[Dict[str, Any]]:
        tracker = _token_tracker.get()
        _token_tracker.set(None)
        if tracker is None:
            return None
        return tracker.summary()

    def _record_usage(self, *, kind: str, model: str, usage: Any = None, cached: bool = False) -> None:
        tracker = _token_tracker.get()
        if tracker is None:
            return
        tracker.add_usage(kind=kind, model=model, usage=usage, cached=cached)
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for a text."""
        try:
            cache_key = self._embedding_cache_key(text)
            cached = self._embedding_cache.get(cache_key)
            if cached is not None:
                self._record_usage(
                    kind="embedding_cache",
                    model=self.embedding_model,
                    usage=None,
                    cached=True,
                )
                return cached
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            self._record_usage(kind="embedding", model=self.embedding_model, usage=response.usage)
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
            self._record_usage(kind="embedding_batch", model=self.embedding_model, usage=response.usage)
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
        usage_kind: Optional[str] = None,
    ) -> str:
        """Generate a chat response using the LLM."""
        try:
            use_model = model or self.model
            response = await self.client.chat.completions.create(
                model=use_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            self._record_usage(
                kind=usage_kind or "chat_completion",
                model=use_model,
                usage=response.usage,
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
        usage_kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate strict JSON output using response_format=json_object."""
        use_model = model or self.model
        response = await self.client.chat.completions.create(
            model=use_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        self._record_usage(
            kind=usage_kind or "chat_json",
            model=use_model,
            usage=response.usage,
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    async def generate_chat_with_tools(
        self,
        messages: List[dict],
        *,
        tools: List[dict],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = 500,
        tool_choice: str = "auto",
        usage_kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a chat response that can invoke function tools."""
        use_model = model or self.model
        response = await self.client.chat.completions.create(
            model=use_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        self._record_usage(
            kind=usage_kind or "chat_with_tools",
            model=use_model,
            usage=response.usage,
        )

        message = response.choices[0].message
        raw_tool_calls = list(message.tool_calls or [])
        parsed_tool_calls: List[Dict[str, Any]] = []
        for tool_call in raw_tool_calls:
            raw_arguments = getattr(getattr(tool_call, "function", None), "arguments", "") or "{}"
            parsed_arguments: Dict[str, Any] = {}
            argument_error: Optional[str] = None
            try:
                loaded = json.loads(raw_arguments)
                if isinstance(loaded, dict):
                    parsed_arguments = loaded
                else:
                    argument_error = "tool arguments must decode to an object"
            except Exception as exc:
                argument_error = str(exc)
            parsed_tool_calls.append(
                {
                    "id": str(getattr(tool_call, "id", "")),
                    "name": str(getattr(getattr(tool_call, "function", None), "name", "")),
                    "arguments": parsed_arguments,
                    "raw_arguments": raw_arguments,
                    "argument_error": argument_error,
                }
            )

        return {
            "content": message.content or "",
            "tool_calls": parsed_tool_calls,
            "finish_reason": response.choices[0].finish_reason,
        }
    
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
                usage_kind="nlu",
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
                usage_kind="product_translation",
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

        use_model = model or getattr(settings, "UI_LOCALIZATION_MODEL", None) or self.model
        cache_key = self._ui_cache_key(reply_language, items)
        cached = self._ui_text_cache.get(cache_key)
        if cached is not None:
            self._record_usage(
                kind="ui_localization_cache",
                model=use_model,
                usage=None,
                cached=True,
            )
            return cached

        system = ui_localization_prompt(reply_language)
        user = f"Strings JSON:\n{json.dumps(items, ensure_ascii=True)}"
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
                usage_kind="ui_localization",
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
