# Commerce Intent Schema

## Purpose
Define the current intent, task-detection, and attribute-filter contract used by the chat-commerce backend.

## Status
As of March 10, 2026, the primary `/chat/` path is component-pipeline driven.

LLM prompts still exist for targeted support tasks such as NLU fallback and localization, but product routing and response composition now live in the component runtime.

## Current Intent Surface

Primary supported intents:

- `browse_products`
- `search_specific`
- `compare_products`
- `recommend_products`
- `knowledge_query`
- `off_topic`

Special request classes handled through heuristics or routing rules:

- `store overview` requests normalize to `browse_products`
- `detail mode` is derived from requested fields and attribute/detail parsing, not treated as a separate top-level NLU enum yet
- `smalltalk` exists as a component-pipeline route, but it is not part of the main external NLU enum

Deferred transactional intents:

- `add_to_cart`
- `view_cart`
- `start_checkout`

These are intentionally out of scope for the current phase.

## Task / Intent Detection Stack

### Layer 1: Heuristic Fast Path

Source:

- `backend/app/services/chat/components/pipeline.py`
- `backend/app/services/chat/detail_query_parser.py`
- `backend/app/services/chat/commerce_intents.py`
- `backend/app/services/chat/routing_policy.py`

Current heuristic signals include:

- SKU detection
- requested detail fields such as `price`, `stock`, and `image`
- attribute-filter extraction
- compare phrases
- recommendation phrases
- store-overview phrases

This path drives the main request classification before retrieval and component selection.

### Layer 2: LLM NLU Fallback

Source:

- `backend/app/services/ai/llm_service.py`
- `backend/app/prompts/nlu.py`

This path is now auxiliary. It supports LLM-based structured parsing when explicitly used, but it is not the main `/chat/` routing path.

### Layer 3: Runtime Normalization

Source:

- `backend/app/services/chat/commerce_intents.py`
- `backend/app/services/chat/routing_policy.py`
- `backend/app/services/chat/result_policy.py`

Normalization rules currently include:

- forcing intent into the supported enum
- converting unsupported transactional intents to safe non-transactional behavior
- coercing invalid requested fields and attribute filters into safe defaults
- promoting compare/recommend/store-overview requests through deterministic rules

## Current Routing Model

### Component Pipeline

Source:

- `backend/app/services/chat/components/pipeline.py`

The component pipeline performs its own routing based on:

- smalltalk detection
- knowledge-intent detection
- recommendation detection
- compare detection
- store-overview detection
- parsed product filters and SKU tokens

It then selects backend retrieval behavior and output components.

## Current Attribute Filter Surface

Source:

- `backend/app/services/chat/detail_query_parser.py`
- `backend/app/services/catalog/product_search.py`

Currently supported product filters are:

- `category`
- `color`
- `crystal_color`
- `cz_color`
- `design`
- `gauge`
- `height`
- `jewelry_type`
- `length`
- `material`
- `opal_color`
- `outer_diameter`
- `packing_option`
- `pearl_color`
- `pincher_size`
- `quantity_in_bulk`
- `rack`
- `ring_size`
- `size`
- `size_in_pack`
- `threading`

Supported requested detail fields are:

- `price`
- `stock`
- `image`
- `attributes`
- `name`
- `sku`

## Service Ownership

### Product Search / Browse

Primary service:

- `backend/app/services/catalog/product_search.py`

Current retrieval modes:

- `structured_search(...)`
- `structured_count(...)`
- `smart_search(...)`
- `vector_search(...)`

### Product Detail

Primary runtime path:

- `backend/app/services/chat/unified_chat_runtime.py`
- `backend/app/services/chat/product_detail_resolver.py`
- `backend/app/services/chat/detail_response_builder.py`

Current note:

- detail handling is part of the component pipeline and resolver stack

### Recommendations

Primary service:

- `backend/app/services/chat/recommendation_service.py`

Current modes:

- similar-item ranking
- complementary-item ranking based on jewelry type and attachment compatibility

### FAQ / Knowledge

Primary services:

- `backend/app/services/chat/knowledge_context.py`
- `backend/app/services/knowledge/retrieval.py`
- `backend/app/services/knowledge/pipeline.py`

Current behavior:

- retrieve knowledge sources first
- generate grounded answer from retrieved source snippets
- fall back to grounded extractive answer if model output is empty

## Current Architectural Limitations

- `compare_products` is not fully implemented in the component pipeline path yet.
- Product detail is not yet a first-class component-path capability.
- Store overview is implemented as a deterministic browse extension, not a separate service contract.
- Strict no-match handling is still incomplete because product flows can fall back to vector search.

## Recommended Near-Term Schema Direction

1. Keep the current supported intent enum stable.
2. Do not add transactional intents until product discovery architecture is unified.
3. Promote `detail mode` into an explicit first-class routed capability in the component architecture.
4. Keep product-filter parsing deterministic and centralized in the parser layer.
5. Keep LLM usage focused on NLU fallback and grounded FAQ phrasing, not core routing logic.

## Related Files

- `backend/app/prompts/nlu.py`
- `backend/app/services/ai/llm_service.py`
- `backend/app/services/chat/commerce_intents.py`
- `backend/app/services/chat/routing_policy.py`
- `backend/app/services/chat/result_policy.py`
- `backend/app/services/chat/components/pipeline.py`
- `backend/app/services/catalog/product_search.py`
- `backend/app/services/chat/recommendation_service.py`
