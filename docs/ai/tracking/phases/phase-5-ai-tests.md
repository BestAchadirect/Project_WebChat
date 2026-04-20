# Phase 5: AI Tests

## Status
- Phase status: `pending`

## Goal
Add focused tests around the AI tool path so future changes do not push the system back toward brittle staged behavior.

## Primary Test Areas
- tool selection
- tool argument generation
- tool fallback behavior
- grounded answer behavior after tool usage
- clarify behavior when tools cannot answer confidently

## Candidate Test Locations
- `backend/tests/unit/chat/`
- `backend/tests/integration/chat/`
- `backend/tests/regression/`

## Tasks
- [ ] Add unit tests for agentic selection rules
- [ ] Add unit tests for tool argument parsing and validation
- [ ] Add integration tests for agentic-first success path
- [ ] Add integration tests for no-tool fallback to component path
- [ ] Add regression cases for grounded product and knowledge answers
- [ ] Add regression cases for clarify/error behavior after tool failure

## Exit Criteria
- Core tool-path behavior is covered
- Fallback behavior is covered
- Regressions can be caught without manual chat testing
