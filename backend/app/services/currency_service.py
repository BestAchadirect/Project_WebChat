import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

from app.core.config import settings
from app.schemas.chat import ProductCard


@dataclass(frozen=True)
class ConversionResult:
    amount: float
    currency: str


class CurrencyService:
    """
    Canonical storage currency is settings.BASE_CURRENCY (default USD).

    Rates are interpreted as: 1 BASE_CURRENCY = rate units of that currency.
    Example: BASE=USD, rates={"THB": 35.0} means 1 USD = 35 THB.
    """

    _CODE_ALIASES: Dict[str, str] = {
        "$": "USD",
        "usd": "USD",
        "dollar": "USD",
        "dollars": "USD",
        "€": "EUR",
        "eur": "EUR",
        "euro": "EUR",
        "euros": "EUR",
        "฿": "THB",
        "thb": "THB",
        "baht": "THB",
        "£": "GBP",
        "gbp": "GBP",
        "pound": "GBP",
        "pounds": "GBP",
        "¥": "JPY",
        "jpy": "JPY",
        "yen": "JPY",
        "aud": "AUD",
        "cad": "CAD",
        "sgd": "SGD",
    }

    def __init__(self) -> None:
        self.base_currency = (getattr(settings, "BASE_CURRENCY", "USD") or "USD").upper()
        self.rates = self._load_rates()

    def _load_rates(self) -> Dict[str, float]:
        raw = getattr(settings, "CURRENCY_RATES_JSON", "{}") or "{}"
        rates: Dict[str, float] = {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    if not isinstance(k, str):
                        continue
                    try:
                        rate = float(v)
                    except (TypeError, ValueError):
                        continue
                    if rate > 0:
                        rates[k.upper()] = rate
        except json.JSONDecodeError:
            rates = {}

        # Backward-compatible: if legacy THB_TO_USD_RATE is set to a non-default value,
        # we can derive USD->THB as the inverse (1 USD = 1 / (THB->USD)).
        if "THB" not in rates:
            thb_to_usd = getattr(settings, "THB_TO_USD_RATE", None)
            try:
                thb_to_usd_f = float(thb_to_usd) if thb_to_usd is not None else None
            except (TypeError, ValueError):
                thb_to_usd_f = None
            if thb_to_usd_f is not None and thb_to_usd_f not in (0.0, 1.0):
                rates["THB"] = 1.0 / thb_to_usd_f

        rates[self.base_currency] = 1.0
        return rates

    def supports(self, currency: str) -> bool:
        return currency.upper() in self.rates

    def convert(self, amount: float, *, from_currency: str, to_currency: str) -> ConversionResult:
        from_cur = (from_currency or self.base_currency).upper()
        to_cur = (to_currency or self.base_currency).upper()
        if from_cur == to_cur:
            return ConversionResult(amount=float(amount), currency=to_cur)

        if from_cur not in self.rates or to_cur not in self.rates:
            return ConversionResult(amount=float(amount), currency=from_cur)

        # Convert from -> base -> to
        # rates[c] is (1 base = rate[c] c)
        usd_amount = float(amount) / float(self.rates[from_cur]) if from_cur != self.base_currency else float(amount)
        out = usd_amount * float(self.rates[to_cur]) if to_cur != self.base_currency else usd_amount
        return ConversionResult(amount=out, currency=to_cur)

    def extract_requested_currency(self, text: str) -> Optional[str]:
        if not text:
            return None
        t = text.strip()
        tl = t.lower()

        # Prefer explicit phrasing: "in EUR", "to THB", "convert to USD"
        m = re.search(r"\b(?:in|to|as|convert to|convert)\s+([a-z]{3})\b", tl)
        if m:
            code = m.group(1).upper()
            if self.supports(code):
                return code

        # Word-based aliases ("baht", "dollars", etc.)
        for token, code in self._CODE_ALIASES.items():
            if token.isalpha() and re.search(rf"\b{re.escape(token)}\b", tl):
                if self.supports(code):
                    return code

        # Symbol-based aliases (€, ฿, £, ¥)
        for symbol in ["€", "฿", "£", "¥"]:
            if symbol in t:
                code = self._CODE_ALIASES.get(symbol)
                if code and self.supports(code):
                    return code

        # Any supported 3-letter currency code in text
        for code in self.rates.keys():
            if len(code) == 3 and re.search(rf"\b{re.escape(code.lower())}\b", tl):
                return code

        return None

    def convert_product_cards(self, cards: List[ProductCard], *, to_currency: str) -> List[ProductCard]:
        out: List[ProductCard] = []
        target = (to_currency or self.base_currency).upper()
        for c in cards or []:
            res = self.convert(float(c.price), from_currency=c.currency, to_currency=target)
            out.append(
                c.model_copy(
                    update={
                        "price": round(float(res.amount), 2),
                        "currency": res.currency,
                    }
                )
            )
        return out


currency_service = CurrencyService()

