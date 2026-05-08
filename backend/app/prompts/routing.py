from __future__ import annotations

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
    )


def routing_decision_prompt(*, compact_prompt: bool) -> str:
    base_keys = (
        "workflow, execution_mode, needs_products, needs_knowledge, needs_clarification, "
        "store_overview_request, knowledge_query, reason, confidence"
    )
    if compact_prompt:
        return (
            f"Return ONLY strict JSON with keys: {base_keys}.\n"
            "Allowed workflow values: catalog, knowledge, general_talking, off_topic, fallback.\n"
            "Allowed execution_mode values: component, agentic.\n"
            f"{routing_intent_guidance(compact_prompt=True)}"
        )

    return (
        f"Return ONLY strict JSON with keys: {base_keys}.\n"
        "Allowed workflow values: catalog, knowledge, general_talking, off_topic, fallback.\n"
        "Allowed execution_mode values: component, agentic.\n"
        f"{routing_intent_guidance(compact_prompt=False)}"
    )


def understanding_workflow_prompt() -> str:
    return (
        "Classify the user's request using the assistant response-intent contract. "
        "Return ONLY strict JSON with keys: intent, subintent, needs_products, needs_knowledge, "
        "product_query, knowledge_query, user_goal, response_policy, clarify_question, "
        "pending_task_type, missing_slot, store_overview_request, reason, confidence. "
        "Allowed intent values: product_information, knowledge_policy, general_talking, off_topic, clarify. "
        "Allowed response_policy values: answer_from_retrieved_data, answer_from_allowed_capabilities, "
        "friendly_scoped_reply, safe_redirect, ask_clarifying_question. "
        "Use product_information when the user wants product search, product details, product availability, "
        "price, stock, images, SKU details, or asks what product help the assistant can provide. "
        "Use product_information for broad shopping/discovery requests even when the product is vague, "
        "such as asking to see something nice, cheaper options, alternatives, or a product follow-up that "
        "depends on the previous product cards. In those cases keep needs_products=true and ask a focused "
        "clarifying question if a product anchor is missing. "
        "Set needs_products=true only when product database retrieval is needed; for capability questions about "
        "products, set needs_products=false and response_policy=answer_from_allowed_capabilities. "
        "Use knowledge_policy for any company knowledge-base question: company/contact/support, sales contact, "
        "human help, showroom/location/hours, shipping, returns, refund, payment, ordering, minimum order, "
        "samples, custom manufacturing, marketing assets or watermark-free images, website/currency help, "
        "stock or out-of-stock policy, product capability FAQ, trust/references/compliance, language support, "
        "taxes, discounts, product care, or store policy. "
        "Do not label contact, support, sales, human help, showroom, location, or answerable FAQ questions as "
        "general_talking. These should use knowledge_policy so the answer can be grounded in the knowledge base. "
        "Set needs_knowledge=true when knowledge-base retrieval is needed and set knowledge_query to the "
        "clean knowledge-only question. "
        "Use general_talking for greetings, thanks, assistant identity, or lightweight in-scope conversation "
        "that does not need retrieval, including short reactions such as 'really?' when no store/product "
        "retrieval is needed. "
        "Use off_topic for unrelated requests outside shopping/support or unsafe boundary-violating requests. "
        "Coding, homework, weather, travel, medical, legal, finance, entertainment, and other non-store tasks "
        "are off_topic; do not ask for missing details for those tasks. "
        "Use clarify only when the assistant genuinely cannot determine whether the user needs products, "
        "knowledge, general talking, or off-topic redirection. Do not use clarify for an incomplete product "
        "task; keep intent=product_information, needs_products=true, response_policy=ask_clarifying_question, "
        "and provide clarify_question. Do not use clarify for an incomplete knowledge-base task; keep "
        "intent=knowledge_policy, needs_knowledge=true, response_policy=ask_clarifying_question, and provide "
        "clarify_question. "
        "Apply these rules in any user language. Contact/support/location questions in any language are "
        "knowledge_policy, not product_information. "
        "When intent=clarify because one detail is missing from an otherwise understood task, set "
        "pending_task_type to a short task key, set missing_slot to the missing field, and set "
        "clarify_question to the exact customer question to ask. For product-specific questions without "
        "a product/SKU, use missing_slot=product_anchor. Leave pending_task_type and missing_slot empty "
        "when there is no resumable task. "
        "Never invent company facts, contact details, prices, stock, policies, or product facts. "
        "For mixed product plus policy messages, set both needs_products=true and needs_knowledge=true, "
        "with product_query containing only the product part and knowledge_query containing only the policy part. "
        "If the user asks about samples before buying a specific product family, this is mixed: product_query "
        "is the product family and knowledge_query is the sample policy question. "
        "Confidence: 0.8-1.0 clear, 0.5-0.79 broad, <0.5 unclear."
    )
