from __future__ import annotations

from typing import Any, Dict, List

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.chat import KnowledgeSource, ProductCard
from app.services.llm_service import llm_service

logger = get_logger(__name__)


class VerifierService:
    def __init__(self, *, log_event) -> None:
        self._log_event = log_event

    async def verify(
        self,
        *,
        question: str,
        knowledge_sources: List[KnowledgeSource],
        product_cards: List[ProductCard],
        run_id: str,
    ) -> Dict[str, Any]:
        verifier_model = settings.RAG_VERIFY_MODEL or settings.OPENAI_MODEL

        max_verify_chunks = max(1, int(getattr(settings, "RAG_VERIFY_MAX_KNOWLEDGE_CHUNKS", 12)))
        provided_chunk_ids = {str(s.source_id) for s in knowledge_sources[:max_verify_chunks]}

        chunks_text = "\n\n".join(
            [
                (
                    f"ID: {s.source_id}\n"
                    f"TITLE: {s.title}\n"
                    f"CATEGORY: {s.category or ''}\n"
                    f"URL: {s.url or ''}\n"
                    f"TEXT: {(s.content_snippet or '')[: settings.RAG_MAX_CHUNK_CHARS_FOR_CONTEXT]}"
                )
                for s in knowledge_sources[:max_verify_chunks]
            ]
        )

        products_text = "\n".join(
            [
                f"- {p.name} (sku={p.sku}, price={p.price} {p.currency})"
                for p in product_cards[: min(5, len(product_cards))]
            ]
        )

        system_prompt = (
            "You are a STRICT VERIFIER for a RAG-based chatbot.\n\n"
            "Your job is NOT to simply decide yes/no.\n"
            "Your PRIMARY responsibility is to analyze a user question, decompose it into distinct topics,\n"
            "and determine which topics are answerable from the provided context and which are not.\n\n"
            "You must ALWAYS reason at the topic level.\n\n"
            "========================\n"
            "PROCESS (MANDATORY)\n"
            "========================\n\n"
            "STEP 1 - Decompose the question\n"
            "- Identify ALL distinct topics or requirements implied by the question.\n"
            "- Treat each topic independently.\n"
            "- Examples of topics: refunds, discounts, shipping costs, customs fees, payment methods, images, custom items, sterilized items.\n\n"
            "STEP 2 - Evaluate each topic against the context\n"
            "For EACH topic:\n"
            "- If the context EXPLICITLY contains sufficient information to answer it:\n"
            "  - Mark it as answerable\n"
            "  - List the supporting_chunk_ids that prove it\n"
            "- If the context does NOT contain sufficient information:\n"
            "  - Mark it as missing\n"
            "  - Write ONE clear clarification question for that topic\n\n"
            "STEP 3 - Populate structured results\n"
            "- Populate answerable_parts for EVERY topic that is supported\n"
            "- Populate missing_parts for EVERY topic that is not supported\n"
            "- missing_parts MUST be ordered by importance to the user:\n"
            "  1) refunds / returns / refused delivery\n"
            "  2) shipping costs / liabilities\n"
            "  3) payment fees or obligations\n"
            "  4) product availability or customization\n"
            "  5) images / marketing / low-risk items\n\n"
            "STEP 4 - Set global flags\n"
            "- answerable = true ONLY if there are NO missing_parts\n"
            "- answerable = false if ANY missing_parts exist\n"
            "- answer_type should reflect the dominant source of information:\n"
            "  - \"knowledge\", \"product\", or \"mixed\"\n\n"
            "========================\n"
            "STRICT RULES\n"
            "========================\n\n"
            "- supporting_chunk_ids MUST be a subset of the provided chunk IDs\n"
            "- NEVER invent policies or facts not present in the context\n"
            "- NEVER answer from general knowledge\n"
            "- NEVER merge topics together - keep them explicit\n"
            "- NEVER return BOTH answerable_parts AND missing_parts empty\n"
            "- If at least ONE topic is supported, answerable_parts MUST NOT be empty\n"
            "- If NO topics are supported, ALL topics must appear in missing_parts\n"
            "- If the question is multi-topic, partial answers are REQUIRED\n"
            "- The verifier must be strict but USEFUL\n\n"
            "========================\n"
            "OUTPUT FORMAT (STRICT)\n"
            "========================\n\n"
            "Return ONLY valid JSON with EXACTLY these keys:\n\n"
            "{\n"
            "  \"answerable\": boolean,\n"
            "  \"answer_type\": \"knowledge\" | \"product\" | \"mixed\",\n"
            "  \"supporting_chunk_ids\": string[],\n"
            "  \"missing_info_question\": string | null,\n"
            "  \"answerable_parts\": [\n"
            "    {\n"
            "      \"topic\": string,\n"
            "      \"supporting_chunk_ids\": string[]\n"
            "    }\n"
            "  ],\n"
            "  \"missing_parts\": [\n"
            "    {\n"
            "      \"topic\": string,\n"
            "      \"missing_info_question\": string\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Notes:\n"
            "- supporting_chunk_ids (top-level) should be the UNION of all answerable_parts chunk IDs\n"
            "- missing_info_question (top-level) should be ONE high-priority clarification question\n"
            "  derived from the FIRST item in missing_parts, or null if fully answerable\n"
        )

        user_prompt = (
            f"Question: {question}\n\n"
            f"Knowledge Chunks:\n{chunks_text or '[none]'}\n\n"
            f"Product Candidates:\n{products_text or '[none]'}\n"
        )

        def _normalize_decision(raw: Any) -> Dict[str, Any]:
            decision: Dict[str, Any] = raw if isinstance(raw, dict) else {}

            answer_type = (decision.get("answer_type") or "knowledge").lower()
            if answer_type not in {"knowledge", "product", "mixed"}:
                answer_type = "knowledge"

            answerable_parts = decision.get("answerable_parts")
            missing_parts = decision.get("missing_parts")
            if not isinstance(answerable_parts, list):
                answerable_parts = []
            if not isinstance(missing_parts, list):
                missing_parts = []

            normalized_answerable_parts: List[Dict[str, Any]] = []
            for p in answerable_parts:
                if not isinstance(p, dict):
                    continue
                topic = p.get("topic")
                ids = p.get("supporting_chunk_ids")
                if not isinstance(topic, str) or not topic.strip():
                    continue
                if not isinstance(ids, list):
                    ids = []
                filtered_ids = [str(x) for x in ids if str(x) in provided_chunk_ids]
                if not filtered_ids:
                    continue
                normalized_answerable_parts.append({"topic": topic.strip(), "supporting_chunk_ids": filtered_ids})

            normalized_missing_parts: List[Dict[str, Any]] = []
            for p in missing_parts:
                if not isinstance(p, dict):
                    continue
                topic = p.get("topic")
                mq = p.get("missing_info_question")
                if not isinstance(topic, str) or not topic.strip():
                    continue
                if not isinstance(mq, str) or not mq.strip():
                    continue
                normalized_missing_parts.append({"topic": topic.strip(), "missing_info_question": mq.strip()})

            supporting_union: List[str] = []
            seen_ids: set[str] = set()
            for p in normalized_answerable_parts:
                for cid in p.get("supporting_chunk_ids", []):
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        supporting_union.append(cid)

            if not normalized_answerable_parts and not normalized_missing_parts:
                normalized_missing_parts = [
                    {
                        "topic": "general",
                        "missing_info_question": (
                            "Which specific part should I answer first (refunds, shipping costs, payment fees, or discounts)?"
                        ),
                    }
                ]

            normalized_answerable = len(normalized_missing_parts) == 0
            top_missing_question = normalized_missing_parts[0]["missing_info_question"] if normalized_missing_parts else None

            return {
                "answerable": bool(normalized_answerable),
                "answer_type": answer_type,
                "supporting_chunk_ids": supporting_union,
                "missing_info_question": top_missing_question,
                "answerable_parts": normalized_answerable_parts,
                "missing_parts": normalized_missing_parts,
            }

        try:
            decision_raw = await llm_service.generate_chat_json(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=verifier_model,
                temperature=0.0,
                max_tokens=600,
                usage_kind="rag_verifier",
            )
            decision = _normalize_decision(decision_raw)
        except Exception as e:
            logger.error(f"Verifier failed: {e}")
            decision = _normalize_decision(
                {
                    "answerable": False,
                    "answer_type": "knowledge",
                    "supporting_chunk_ids": [],
                    "missing_info_question": None,
                    "answerable_parts": [],
                    "missing_parts": [
                        {
                            "topic": "general",
                            "missing_info_question": (
                                "Which specific part should I answer first (refunds, shipping costs, payment fees, or discounts)?"
                            ),
                        }
                    ],
                }
            )

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.verify",
            data={"decision": decision},
        )
        return decision
