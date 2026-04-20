from __future__ import annotations

from app.services.chat.routing.workflow_taxonomy import internal_workflow_values_prompt


def routing_intent_guidance(*, compact_prompt: bool) -> str:
    support_contact = (
        "Use company_info for store/company/contact/support/human-help questions.\n"
        "Use policy_info for shipping, returns, refund, payment, warranty, ordering, pricing, and similar help questions.\n"
        "Examples: 'I want to talk to a sales person', 'How do I contact support?'.\n"
        "For support/contact requests, set needs_knowledge=true and set knowledge_query to a short support question.\n"
    )
    if compact_prompt:
        return (
            "Use catalog_search for product browse/search/filter requests.\n"
            f"{support_contact}"
            "Use mixed when the request clearly needs both products and knowledge.\n"
            "Use smalltalk for greetings, thanks, and sign-offs.\n"
            "Use off_topic for unrelated requests or casual chat outside shopping/support.\n"
            "Use clarify only when the request is genuinely unclear.\n"
            "Set knowledge_query to a short knowledge-only subquestion when there is a secondary knowledge need.\n"
            "Confidence: 0.8-1.0 clear, 0.5-0.79 broad, <0.5 unclear.\n"
        )
    return (
        "Priority order:\n"
        "1. catalog_search for shopping, browse, filters, materials, colors, gauges, and product discovery.\n"
        "2. company_info for company info, store overview, contact, support, human help, and location.\n"
        "3. policy_info for shipping, refund, payment, warranty, ordering, pricing, and policy/help.\n"
        f"   {support_contact}"
        "4. mixed when the request clearly needs both products and knowledge.\n"
        "5. smalltalk for greetings, thanks, and sign-offs.\n"
        "6. off_topic for unrelated requests outside shopping/support.\n"
        "7. clarify only when unclear.\n"
        "Mixed requests: set needs_products / needs_knowledge and set knowledge_query to the secondary knowledge-only question when needed.\n"
        "Set store_overview_request=true only for company/store/business questions.\n"
        "Keep reason short and specific. Confidence: 0.8-1.0 clear, 0.5-0.79 broad, <0.5 unclear.\n"
    )


def routing_decision_prompt(*, compact_prompt: bool) -> str:
    base_keys = (
        "workflow, execution_mode, needs_products, needs_knowledge, needs_clarification, "
        "store_overview_request, knowledge_query, reason, confidence"
    )
    if compact_prompt:
        return (
            f"Return ONLY strict JSON with keys: {base_keys}.\n"
            "Allowed workflow values: catalog, knowledge, off_topic, fallback.\n"
            "Allowed execution_mode values: component, agentic.\n"
            f"{routing_intent_guidance(compact_prompt=True)}"
        )

    return (
        f"Return ONLY strict JSON with keys: {base_keys}.\n"
        "Allowed workflow values: catalog, knowledge, off_topic, fallback.\n"
        "Allowed execution_mode values: component, agentic.\n"
        f"{routing_intent_guidance(compact_prompt=False)}"
    )


def understanding_workflow_prompt() -> str:
    return (
        "Classify the user's request into the assistant's internal workflow taxonomy. "
        "Return strict JSON with keys: workflow_hypothesis, needs_products, needs_knowledge, "
        "store_overview_request, knowledge_query, reason, confidence. "
        f"Allowed workflow_hypothesis values: {internal_workflow_values_prompt()}. "
        f"{routing_intent_guidance(compact_prompt=True)}"
        "Use product_detail for one specific product or SKU asking about stock, price, image, or attributes. "
        "Use mixed when the request clearly needs both catalog and knowledge. "
        "Use clarify only when the request is genuinely unclear."
    )
