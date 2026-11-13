# Engineering Standards

- Match the file being edited: compact, idiomatic, no decorative comments; comments explain *why*.
- Money: keep `REAL`/floats inside the hub, `*_cents` integers on the wire (mobile/cloud payloads), `numeric(14,2)` in Postgres. Round at line level, then totals.
- Time: **all writes UTC ISO-8601** (`utcnow()`); display converts to local. Never write `datetime.now()` naive to `sales`/ledger tables.
- Events: every mutation emits its event in the **same transaction** as the business write; dedupe key is always `event_id`; cursors are `server_sequence`-only.
- Authz: server-side always — UI hiding is not a control. Admin ops → `need_admin`/`_is_admin`; device ops → `need_device`; no new unauthenticated endpoints without an audit note.
- Errors: JSON `{"error": "human-readable"}` + correct status; no bare `except: pass` on data paths — failed projections land in `sync_conflicts`.
- Secrets: `.env` only; never log tokens/keys (audit log redacts pairing tokens).
- Tests: pytest in `tests/`, monkeypatch `appmod.DB` to a tmp path, `appmod.init_db()`, `appmod.app.test_client()`. Every bug fix ships one.
- SQLite: `BEGIN IMMEDIATE` for multi-writer sequences (receipts, server_sequence).
