# Phase 4: Orchestration Contracts

## Status
- Phase status: `pending`

## Goal
Standardize the orchestrator input/output contract so behavior is easier to test, log, and evolve.

## Primary Files
- `backend/app/services/chat/runtime/unified_chat_runtime.py`
- `backend/app/services/chat/agentic/orchestrator.py`
- `backend/app/services/ai/llm_service.py`
- `backend/app/schemas/chat.py`

## Tasks
- [ ] Define the minimal orchestrator input contract
- [ ] Define the final-answer vs tool-call vs clarify/error output contract
- [ ] Ensure structured response generation remains consistent
- [ ] Ensure fallback reasons and traces are preserved
- [ ] Confirm component rendering still matches backend response contract

## Desired Input Shape
- user text
- short conversation history
- available tool definitions
- minimal runtime context

## Desired Output Shape
- structured final answer
- or tool calls followed by structured final answer
- or deterministic clarify/error fallback

## Exit Criteria
- The orchestration contract is consistent across the runtime
- Fallback handling is explicit
- Structured output remains the default response mode
