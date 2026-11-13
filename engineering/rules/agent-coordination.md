# Agent Coordination

Single-CLI reality: this workspace has one agent (me) executing all roles. Specialist work is done as **separated workflows** with role-specific checklists, not parallel agents. "Independent verification" = a second pass that re-runs tests and re-reads diffs with fresh eyes after implementation, never self-approval alone.

## Roles → workflows

| Role | How it's executed |
|---|---|
| Chief Engineering | Owns this backlog, priorities, cross-platform impact review before any change lands |
| Product Research | `engineering/improvements/` — every proposal needs problem/user/value/acceptance criteria before scheduling |
| QA & Testing | Every fix ships a failing-first regression test in `tests/`; matrix in `engineering/testing/` |
| Web Engineer | `web/` + `/api/web/*` in `cloud_api.py` |
| Mobile Engineer | `mobile/` — TypeScript changes must keep `npx tsc --noEmit` clean |
| Desktop/Hub Engineer | `app.py`, `desktop.py`, migrations |
| UI/UX | Rendered-page review via screenshots, not just code |
| Verification | Re-run full suite + targeted reproduction against the diff; checklist in `rules/definition-of-done.md` |

## Conflict prevention

- One file subsystem in flight at a time for `app.py`/`cloud_api.py` (single-file apps).
- Any change touching event payloads, schema, or API contracts requires the integration-map check: who consumes this?
- Commits: conventional prefix + declarative subject (repo style).

## Prioritization order (assignment §10)

1. Critical security → 2. Data corruption/loss → 3. Financial/inventory math → 4. Broken core workflows → 5. Sync failures → 6. Serious usability → 7. Performance → 8. Missing essentials → 9. Enhancements → 10. Polish.
