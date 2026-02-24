# Frontend Codex Agent Rules (React)

You are editing the **frontend** (React). Make safe, minimal, correct changes and keep behavior consistent unless asked.

## Required workflow (always)
1) Understand the requested change and identify the impacted UI/UX behavior.
2) **Before editing anything**, scan to find all impacted locations:
   - Prefer **Find All References** for React components, hooks, functions, exported constants/types.
   - Also use text search for strings, routes, env keys, CSS classnames, API paths.
3) Produce an **Impact Report**:
   - **Total files to change (N)**
   - **Total edit locations / occurrences (M)** you intend to modify
   - List each file path + reason
4) Apply edits only to locations listed in the Impact Report.
   - If you discover new impacted locations, **STOP**, update the Impact Report (new N/M), then continue.
5) Verify:
   - Re-search for old identifiers/strings
   - Run/suggest relevant checks (lint/typecheck/tests/build)
6) Finish with **Final Summary** including final **N** and **M**.

## Output format (mandatory)
Impact Report  
Plan  
Edits Applied  
Verification  
Final Summary  

---

## Frontend architecture expectations
- Prefer **functional components** + hooks.
- Keep components small; extract logic into hooks/utilities when reused.
- Avoid breaking changes to props unless requested; if needed, update all call sites.
- Keep types consistent (TypeScript if used). If JS, add JSDoc for complex functions.

## Refactor rules (renames/signature changes)
When renaming a component/function/prop/API path:
- Update:
  - imports/exports
  - all call sites
  - route usage (React Router or custom router)
  - tests, stories, mocks
  - docs/readme if present
- Count both:
  - **reference count** (symbol references)
  - **string match count** (text search)
If they differ, explain why.

## API / backend integration rules
When changing API request/response shapes:
- Update:
  - API client module (fetch/axios)
  - request payload builders
  - response parsing
  - types/interfaces
  - UI components that render the changed fields
  - any mocks fixtures
- Ensure error states + loading states still work.

## UI behavior rules
- Preserve existing UX unless asked to change it.
- Any UI change must include:
  - loading state handling
  - empty state handling
  - error state handling
- Don't add heavy dependencies unless necessary; prefer existing libs.

## Styling rules
- Respect existing styling system (Tailwind/CSS modules/Styled Components).
- Avoid mixing styling approaches inside a single component.
- Keep classnames readable; extract repeated classnames into constants.

## Quality gates (Verification)
After edits, do these (or suggest exact commands if you can't run them):
- Lint: `npm run lint` or `yarn lint`
- Typecheck (if TS): `npm run typecheck` or `tsc -p . --noEmit`
- Tests: `npm test` (or your repo's command)
- Build: `npm run build`

## Safety rules
- Do not edit files outside `frontend-admin/` unless explicitly requested.
- Do not delete code unless it is dead and confirmed unused via references.
- Do not change env variable names without updating `.env.example` and usage sites.

## If requirements are ambiguous
Ask **one** focused question only when truly ambiguous. Otherwise proceed with best assumption and document it in the Plan.
