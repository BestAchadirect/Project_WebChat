from __future__ import annotations

from typing import Optional


def unified_nlu_prompt(supported_currencies: Optional[list[str]] = None) -> str:
    codes = f" Supported: {', '.join(sorted(set(supported_currencies)))}" if supported_currencies else ""
    return (
        "Return ONLY strict JSON: {\"language\": \"\", \"locale\": \"\", \"intent\": \"\", \"show_products\": bool, \"currency\": \"\", \"refined_query\": \"\", \"product_code\": \"\", \"requested_fields\": [], \"attribute_filters\": {}, \"wants_image\": bool}.\n"
        "1. Language: Detect primary language and BCP-47 locale.\n"
        "2. Intent: 'browse_products', 'search_specific', 'compare_products' (explicit compare requests), 'recommend_products' (asks for suggestions or similar options), 'knowledge_query' (policies, help, or bot identity), 'off_topic'.\n"
        "3. show_products: true if intent is browse/search/compare/recommend.\n"
        f"4. Currency: Detect ISO 4217 code if requested.{codes}\n"
        "5. refined_query: Rewrite the user's message into a standalone search query in English.\n"
        "6. product_code: Extract any specific SKU, Model Number, or Master Code if present (e.g., from 'find code ACCO' -> 'ACCO'). If none, return empty string.\n"
        "7. requested_fields: Return subset of ['price','stock','image','attributes','name','sku'] explicitly asked by user.\n"
        "8. attribute_filters: Extract concrete filters using catalog keys such as jewelry_type, material, color, gauge, threading, category, design, length, size, outer_diameter, opal_color, pearl_color, crystal_color, cz_color, ring_size, height, packing_option, size_in_pack, quantity_in_bulk, pincher_size, and rack. Never output source_id or source_raw_sku.\n"
    )
