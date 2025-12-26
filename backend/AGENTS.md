# Codex Working Rules (Repo)

You are a codebase editor inside VS Code. Make safe, minimal, correct changes.

## Required workflow (do this every time)
1) Understand the request.
2) BEFORE editing anything, scan the repo to find *all* impacted locations:
   - Use "Find All References" for symbols when possible.
   - Also use text search for strings/paths/config keys.
   - Include: code, configs, schemas, tests, docs, CI, migrations.
3) Produce an **Impact Report**:
   - Total files to change: N
   - Total edit locations (occurrences to modify): M
   - List each file path and why it must change.
4) Apply edits only to what’s listed in the Impact Report.
   - If you discover new impacted spots, STOP and update the Impact Report first.
5) Verify:
   - Re-search to ensure old names/behavior don’t remain.
   - Run/suggest relevant tests or lint/build.
6) Finish with a Final Summary including final N and M.

## Output format
Impact Report
Plan
Edits Applied
Verification
Final Summary