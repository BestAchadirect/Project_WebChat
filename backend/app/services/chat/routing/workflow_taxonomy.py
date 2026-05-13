from __future__ import annotations

INTERNAL_WORKFLOWS = {
    "catalog_search",
    "product_detail",
    "compare_products",
    "company_info",
    "policy_info",
    "mixed",
    "smalltalk",
    "general_talking",
    "off_topic",
    "clarify",
}

INTERNAL_WORKFLOW_PROMPT_ORDER = (
    "catalog_search",
    "product_detail",
    "compare_products",
    "company_info",
    "policy_info",
    "mixed",
    "smalltalk",
    "general_talking",
    "off_topic",
    "clarify",
)


def internal_workflow_values_prompt() -> str:
    return ", ".join(INTERNAL_WORKFLOW_PROMPT_ORDER)
