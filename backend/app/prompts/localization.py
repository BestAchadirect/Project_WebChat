from __future__ import annotations


def ui_localization_prompt(reply_language: str) -> str:
    return (
        f"Translate provided English JSON values into {reply_language}.\n"
        "Never use em dashes or en dashes; use commas, periods, parentheses, or ASCII hyphens instead.\n"
        "Return ONLY strict JSON. Preserve formatting, keys, and technical terms (SKU, URL) exactly."
    )
