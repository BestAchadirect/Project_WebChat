from __future__ import annotations


def contextual_clarify_prompt(reply_language: str) -> str:
    return (
        f"You write one short clarification message for a shopping assistant in {reply_language}.\n"
        "Return ONLY strict JSON with key `message`.\n"
        "Write exactly one sentence.\n"
        "Use the user query and context to ask for the most useful missing detail.\n"
        "Be specific when context supports it.\n"
        "Do not mention internal system terms such as ambiguity_reason, clarify_reason, workflow, filters, or debug.\n"
        "Do not use bullet points, numbering, or multiple questions.\n"
        "Do not be generic unless the context truly lacks a better follow-up."
    )


def contextual_error_prompt(reply_language: str) -> str:
    return (
        f"You write one short recovery message for a shopping assistant in {reply_language}.\n"
        "Return ONLY strict JSON with key `message`.\n"
        "Write exactly one sentence.\n"
        "Acknowledge the issue briefly and guide the user on the next step.\n"
        "Do not expose internal errors, stack traces, or system terms.\n"
        "Do not blame external services.\n"
        "Keep the tone calm and direct."
    )
