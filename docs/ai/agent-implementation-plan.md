# AI Agent Implementation Plan

## Purpose
This document is execution guidance for AI coding agents working on the chat system.

It is not a product roadmap and not a generic architecture essay.
It defines what to optimize for in the current phase, what not to build, and the implementation order.

Tracking files for implementation status live in:
- `docs/ai/tracking/project-status.md`
- `docs/ai/tracking/phases/`
- `docs/ai/tracking/sprints/`

Use the tracking docs this way:
- `project-status.md`: current dashboard, including active vs inactive sprint state
- `phases/`: project-level stage model
- `sprints/`: execution packages and sprint task lists

This file is the stable implementation guide.
It should define direction, priorities, and decision rules, but it should not manage sprint status directly.

## Current Scope
- Magento-only product direction
- Single-store direction
- Read-only AI assistant
- Product discovery
- Product recommendation
- FAQ / policy answering
- Structured frontend rendering

## Explicit Non-Goals
Do not spend implementation time on these now unless explicitly requested:
- Multi-tenant support
- Support for non-Magento store platforms
- Order lookup
- Customer/account tools
- Cart tools
- Ticket handoff / support workflow
- Generic platform abstraction layers

## Source of Truth Direction
- Current upstream product source: Klevu API
- Future upstream product source: Magento API
- Serving layer for AI tools: local database

AI orchestration should not depend on live external APIs at chat-time unless there is no other option.
The target shape is:

1. External system syncs into local storage
2. Backend services read local data
3. AI tools call backend services
4. LLM orchestrates tool usage

## Current Architecture Reality
The current system is hybrid.

The main behavior path is still staged and spread across:
- `backend/app/services/chat/harness/`
- `backend/app/services/chat/routing/understanding.py`
- `backend/app/services/chat/routing/decision_engine.py`
- `backend/app/services/chat/components/pipeline_runtime/`

A real tool-calling path already exists in:
- `backend/app/services/chat/agentic/tool_registry.py`
- `backend/app/services/chat/agentic/orchestrator.py`
- `backend/app/services/ai/llm_service.py`

The strongest reusable read-only services are:
- `backend/app/services/catalog/product_search.py`
- `backend/app/services/knowledge/retrieval.py`

## Target Runtime Shape
Move toward this runtime model:

1. Thin deterministic pre-checks
2. LLM decides whether to answer directly or use read-only tools
3. Tool calls execute against local services and local DB
4. Tool results are turned into structured chat components
5. Deterministic fallback handles failure and clarification

The main rule:
Do not keep expanding staged workflow branching when a tool-backed orchestration path can handle the request.

## Design Principles

### 1. Tools over brittle routing
Prefer tool invocation over adding more keyword branches or workflow-specific if/else logic.

### 2. Local services over transport code
Business logic belongs in service modules, not API route files and not UI code.

### 3. Read-only first
All AI implementation in this phase should remain read-only.

### 4. Local DB is the serving layer
Do not design the assistant around direct per-turn Magento API access.

### 5. Magento-centric, not platform-generic
Do not introduce tenant/platform abstraction unless a second real platform exists.

### 6. Structured output by default
Frontend-facing answers should continue to use structured components, not free-text-only payloads.

## Implementation Priorities

### Priority 1: Make one orchestration path primary
Reduce split ownership across:
- understanding
- decision engine
- unified runtime
- component pipeline
- optional agentic path

Implementation intent:
- keep deterministic pre-checks and guardrails
- make tool-based orchestration the primary path for supported read-only requests
- keep component pipeline mainly as response composition and rendering support

### Priority 2: Promote the existing read-only tools
Current tool seed:
- `search_products`
- `get_product_details`
- `search_knowledge_base`
- `check_inventory_db`

Implementation intent:
- route more supported catalog/knowledge turns through these tools
- avoid adding new staged branches if an existing tool can answer the request
- improve tool argument quality before adding more tools

### Priority 3: Shrink routing to a thin gate
Routing should only do work that is clearly useful before orchestration, such as:
- empty input detection
- obvious off-topic handling
- obvious SKU/detail fast path hints
- high-risk clarification gates when necessary
- hard runtime fallback

Routing should not try to own the full answer strategy.

### Priority 4: Standardize orchestration I/O
Target orchestration contract:
- input:
  - user text
  - short conversation history
  - available tool definitions
  - minimal runtime context
- output:
  - final structured answer
  - or tool calls followed by structured answer
  - or deterministic clarify/error fallback

### Priority 5: Add focused AI-path tests
Add tests for:
- tool selection
- tool argument generation
- tool fallback behavior
- grounded answer behavior after tool usage
- clarify behavior when tools cannot support a confident answer

Do not prioritize broad UI/admin cleanup before these tests exist.

## Practical File Guidance

### Primary files to change first
- `backend/app/services/chat/harness/`
- `backend/app/services/chat/agentic/orchestrator.py`
- `backend/app/services/chat/agentic/tool_registry.py`
- `backend/app/services/chat/routing/understanding.py`
- `backend/app/services/chat/routing/decision_engine.py`
- `backend/app/services/chat/components/pipeline_runtime/core.py`

### Files to preserve as stable infrastructure where possible
- `backend/app/services/ai/llm_service.py`
- `backend/app/services/catalog/product_search.py`
- `backend/app/services/knowledge/retrieval.py`
- `backend/app/schemas/chat.py`
- `backend/app/services/chat/runtime/persistence.py`

## Things To Avoid
- Do not add multi-tenant abstractions
- Do not add generic store-platform abstraction layers
- Do not add order/account/ticket logic in this phase
- Do not keep increasing config and feature-flag complexity unless removing existing complexity
- Do not move core business logic into route handlers
- Do not make the chat runtime dependent on direct external API reads per request

## Expected Refactor Direction

### Short term
- agentic/tool path becomes default for supported read-only requests
- staged runtime becomes thinner
- component pipeline becomes more presentation-oriented

### Medium term
- Klevu-backed local data remains current source
- future Magento sync swaps the upstream source without changing internal tool contracts

## Definition of Done for This Phase
This phase is successful when all of these are true:

1. Supported read-only product and knowledge requests primarily use tool orchestration
2. Deterministic routing logic is smaller and easier to reason about
3. The assistant still returns structured frontend components
4. Tool-path behavior is covered by focused tests
5. No new multi-tenant or platform-generic architecture was introduced

## Decision Rule for AI Coding Agents
When choosing between:
- adding more workflow-specific branching
- or strengthening the read-only tool path

choose the read-only tool path unless a deterministic guardrail is clearly safer or simpler.

## Notes for Future Phases
Future phases may add:
- Magento API sync into local DB
- richer product tools
- later, sensitive commerce tools

Those are not part of this phase.

This phase is strictly about making the AI logic cleaner, less brittle, and more tool-first.
