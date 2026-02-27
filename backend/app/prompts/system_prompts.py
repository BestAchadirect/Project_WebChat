from __future__ import annotations
from typing import Optional

def unified_nlu_prompt(supported_currencies: Optional[list[str]] = None) -> str:
    codes = f" Supported: {', '.join(sorted(set(supported_currencies)))}" if supported_currencies else ""
    return (
        "Return ONLY strict JSON: {\"language\": \"\", \"locale\": \"\", \"intent\": \"\", \"show_products\": bool, \"currency\": \"\", \"refined_query\": \"\", \"product_code\": \"\", \"requested_fields\": [], \"attribute_filters\": {}, \"wants_image\": bool}.\n"
        "1. Language: Detect primary language and BCP-47 locale.\n"
        "2. Intent: 'browse_products', 'search_specific', 'knowledge_query' (policies, help, or bot identity), 'off_topic'.\n"
        "3. show_products: true if intent is browse/search.\n"
        f"4. Currency: Detect ISO 4217 code if requested.{codes}\n"
        "5. refined_query: Rewrite the user's message into a standalone search query in English.\n"
        "6. product_code: Extract any specific SKU, Model Number, or Master Code if present (e.g., from 'find code ACCO' -> 'ACCO'). If none, return empty string.\n"
        "7. requested_fields: Return subset of ['price','stock','image','attributes','name','sku'] explicitly asked by user.\n"
        "8. attribute_filters: Extract concrete filters (e.g., jewelry_type, material, color, gauge, threading).\n"
        "9. wants_image: true when user asks for image/photo/picture."
    )

def rag_answer_prompt(reply_language: str) -> str:
    return (
        f"You are AchaDirect's helpful AI wholesale assistant. Reply in {reply_language}.\n"
        "Return ONLY strict JSON: {\"reply\": \"\", \"carousel_hint\": \"\", \"recommended_questions\": []}.\n"
        "MAX 2 SENTENCES TOTAL for both fields combined.\n"
        "- Policy/Knowledge: Use context to answer. If match found, be helpful.\n"
        "- Products: Use product TYPE/CATEGORY (e.g., 'Earring', 'Belly Clip') to refer to items. Summarize in {reply_language}.\n"
        "- NO TECH SPECS: Avoid SKUs, model names (like 'blcp541'), or technical codes in the 'reply' text. Focus on what it is.\n"
        "- Translation: You ARE capable of translating English product data from context into {reply_language}.\n"
        "- recommended_questions: List 3-5 short, relevant follow-up questions the user might ask next (e.g., ['Shipping costs?', 'View Cart', 'Material info']). Context-aware.\n"
        "- carousel_hint: If products were found, provide a brief call-to-action (e.g., 'Check them out below!'). Otherwise, leave empty.\n"
        "- Missing/None: If no match found, politely guide to catalog or email sales@achadirect.com.\n"
        "- NO unsolicited advice."
    )

def ui_localization_prompt(reply_language: str) -> str:
    return (
        f"Translate provided English JSON values into {reply_language}.\n"
        "Return ONLY strict JSON. Preserve formatting, keys, and technical terms (SKU, URL) exactly."
    )
