from __future__ import annotations


def routing_decision_prompt(*, compact_prompt: bool) -> str:
    base_keys = (
        "workflow, execution_mode, needs_products, needs_knowledge, needs_clarification, "
        "store_overview_request, recommendation_mode_requested, knowledge_query, reason, confidence"
    )
    if compact_prompt:
        return (
            f"Return ONLY strict JSON with keys: {base_keys}.\n"
            "Allowed workflow values: catalog, knowledge, recommendation, smalltalk, off_topic, fallback.\n"
            "Allowed execution_mode values: component, agentic.\n"
            "Use catalog for product browse/search/filter requests.\n"
            "Use knowledge for company/store/contact/location/shipping/refund/payment/warranty questions.\n"
            "Use recommendation for suggestions or matching items.\n"
            "Use smalltalk for greetings or thanks only.\n"
            "Use off_topic for unrelated requests.\n"
            "Use fallback only when the request is genuinely unclear.\n"
            "For mixed requests, set the primary workflow and fill needs_products / needs_knowledge.\n"
            "Set knowledge_query to a short knowledge-only subquestion when there is a secondary knowledge need.\n"
            "Set recommendation_mode_requested to complementary_items only for 'what goes with this', 'what fits this', "
            "matching accessories, or a complementary part; otherwise use similar_items.\n"
            "Use agentic only for concrete SKU / inventory / detail chains.\n"
            "Confidence: 0.8-1.0 clear, 0.5-0.79 broad, <0.5 unclear."
        )

    return (
        f"Return ONLY strict JSON with keys: {base_keys}.\n"
        "Allowed workflow values: catalog, knowledge, recommendation, smalltalk, off_topic, fallback.\n"
        "Allowed execution_mode values: component, agentic.\n"
        "Allowed recommendation_mode_requested values: similar_items, complementary_items.\n"
        "Priority order:\n"
        "1. catalog for shopping, browse, filters, materials, colors, gauges, and product discovery.\n"
        "2. knowledge for company info, store overview, contact, support, location, buying in person, shipping, "
        "refund, payment, warranty, and policy/help.\n"
        "3. recommendation for suggestions or matching items.\n"
        "4. smalltalk for greetings or thanks.\n"
        "5. off_topic for unrelated requests.\n"
        "6. fallback only when unclear.\n"
        "Mixed requests: choose the primary workflow, set needs_products / needs_knowledge, and set knowledge_query "
        "to the secondary knowledge-only question when needed.\n"
        "Set store_overview_request=true only for company/store/business questions.\n"
        "Set recommendation_mode_requested to complementary_items only for 'what goes with this', 'what fits this', "
        "matching accessories, or a complementary part; otherwise use similar_items.\n"
        "Use agentic only for concrete multi-step SKU / inventory / detail lookup chains.\n"
        "Keep reason short and specific. Confidence: 0.8-1.0 clear, 0.5-0.79 broad, <0.5 unclear."
    )
