# Conversation State Design

## Purpose
Document how conversation context is currently handled, what has already been implemented, and what still remains before state becomes a default part of the chat architecture.

## Status
As of March 10, 2026, structured conversation state is implemented but not yet the default runtime behavior.

Current rollout state:

- state schema and persistence are implemented
- legacy runtime reads and writes structured state when enabled
- conversation state is still feature-flagged
- component pipeline parity is not complete yet

## Current State Handling

### Frontend Session Anchors

- `frontend-admin/src/components/chat/ChatWidget.tsx` persists user and conversation identifiers in `localStorage`
- widget session is rehydrated from `/chat/active` and `/chat/history/{conversation_id}`

### Backend Conversation Lifecycle

- `backend/app/services/chat/service.py` resolves and reuses active conversations
- `backend/app/api/routes/chat.py` exposes active-conversation and history endpoints

### Message Memory

- `backend/app/services/chat/persistence.py` stores user and assistant messages
- assistant messages can persist `product_data` alongside text
- recent history is still loaded for runtime reasoning and fallbacks

### Structured Conversation State

Source:

- `backend/app/models/chat.py`
- `backend/app/services/chat/conversation_state.py`
- `backend/app/services/chat/unified_chat_runtime.py`
- `backend/app/services/chat/persistence.py`

The `conversation.state` JSON column is now actively used when `CHAT_CONVERSATION_STATE_ENABLED=true`.

Implemented state fields:

```json
{
  "version": 1,
  "last_intent": "browse_products",
  "last_refined_query": "titanium belly rings",
  "last_attribute_filters": {
    "material": "titanium",
    "jewelry_type": "belly ring"
  },
  "last_requested_fields": ["price", "stock"],
  "last_product_ids": ["..."],
  "last_currency": "USD",
  "last_route": "browse_products",
  "updated_at": "2026-03-10T00:00:00Z"
}
```

## Implemented Runtime Behavior

### Write Points

Implemented in the legacy runtime:

1. after intent parsing
   - update `last_intent`, `last_refined_query`, `last_attribute_filters`
2. after retrieval / product selection
   - update `last_product_ids`, `last_route`
3. before final persistence
   - update `last_requested_fields`, `last_currency`, `updated_at`

### Read Behavior

Implemented today:

- merge previous filters into short follow-up turns such as `cheaper ones`, `same material`, `show more`
- safe state normalization and fallback on malformed JSON

Not fully implemented yet:

- reference resolution using `last_product_ids` for turns like `these`, `the first one`, `that one`
- recommendation seeding based on stored product context across both runtimes
- full component-pipeline state parity

## Current Guardrails

- compact JSON-only payload
- versioned schema
- additive evolution only
- message history remains fallback if state is unavailable or invalid
- no cart or checkout fields are included

## Current Gaps

- `CHAT_CONVERSATION_STATE_ENABLED` defaults to `false`
- state-aware behavior is strongest in the legacy runtime, not the component pipeline
- last-product reference disambiguation is still incomplete
- recommendation flows do not yet fully consume stored state as a first-class input

## Recommended Next Steps

1. finish product-reference resolution using `last_product_ids`
2. add conversation-state usage to the component pipeline
3. validate behavior with regression and live QA
4. enable state by default after parity and accuracy thresholds are met

## Explicit Non-Goals For This Phase

- add-to-cart actions
- cart viewing
- checkout execution
- order-management state

## Related Files

- `frontend-admin/src/components/chat/ChatWidget.tsx`
- `backend/app/api/routes/chat.py`
- `backend/app/models/chat.py`
- `backend/app/services/chat/service.py`
- `backend/app/services/chat/unified_chat_runtime.py`
- `backend/app/services/chat/conversation_state.py`
- `backend/app/services/chat/persistence.py`
