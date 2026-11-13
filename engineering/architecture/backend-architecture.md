# Backend Architecture — Hub (`app.py`) + Cloud API (`cloud_api.py`)

## Hub (`app.py`, ~1266 lines, Flask + SQLite)

- Single-file Flask app. `DB = BASE/pos.db`, `POS_DB` env override supported (tests patch `appmod.DB`).
- `db()` opens a fresh `sqlite3.connect` per call, `row_factory=Row`, `PRAGMA foreign_keys=ON`. Callers commit/close manually.
- `SCHEMA` creates the legacy tables; `MIGRATIONS`/`mig(n, sql)` + `apply_migrations()` run forward-only migrations tracked in `schema_versions` (currently 1–10).
- `init_db()` seeds users (`admin`/`admin123`, `cashier`/`cashier123`), demo categories/brands/suppliers/products, settings (`tax_rate=16`, `currency="KSh "`).

### Auth layers

- `need_login` — `session["uid"]` required (cookie session; `app.secret_key` persisted in `.secret_key` file).
- `need_admin` — login + `session["role"] == "admin"`.
- `need_device` — `X-Device-Key` → `devices.api_key_hash = sha256(key)` + `active=1`; bumps `last_seen_at`.
- Passwords: `sha256(password)` — **unsalted** (see security audit SEC-1).

### Money / identity

- Prices stored as REAL (floats) on the hub; minor units (cents) on mobile/cloud payloads (`*_cents` fields, converted in `apply_sale_event`).
- Receipts: `next_receipt()` → `INV-NNNNNN` from `receipt_counters` (branch-scoped, UPDATE…RETURNING under `BEGIN IMMEDIATE`).
- Events: `emit_event()` allocates `server_sequence` from `sync_streams` (per-branch UPDATE…RETURNING), writes `sync_events` + `sync_outbox` in caller's transaction.

### Key endpoints

- Session POS UI: `/api/bootstrap`, `/api/products` (CRUD), `/api/products/import` (CSV/XLSX dry-run+apply), `/api/lookup` (till search), `/api/checkout` (atomic, `BEGIN IMMEDIATE`), `/api/receipt`, `/api/sales` (+void, admin), `/api/held`, `/api/stock`, `/api/critical`, `/api/lookup/<kind>`, `/api/reports`, `/api/dashboard`, `/api/users`, `/api/settings`, `/api/promos`, `/api/customers`.
- Device API: `/api/v1/devices/pair|me`, `/api/v1/products`, `/api/v1/users`, `/api/v1/dashboard`, `/api/v1/reports`, `/api/v1/devices`, `/api/v1/shifts/*`, `/api/v1/customers`, `/api/v1/promos`, `/api/v1/sync/push|pull|ack|status|conflicts`, `/api/v1/purchases`, `/api/v1/expenses`, `/api/v1/returns` (last three are `need_login`, not device-auth).
- Admin: `/api/admin/cloud-sync`, `/api/admin/backup` (sqlite backup → file download), `/api/admin/audit`.
- Unauthenticated: `/`, `/api/login`, `/api/forgot`, `/api/v1/ping` (LAN beacon), `/api/v1/devices/pair` (token-gated).

### Event projection on ingest

`sync_push` → dedupe by `event_id` → allocate `server_sequence` → `sync_events` + `sync_receipts` → `apply_sale_event` **only for SALE_CREATED**. Other types are stored, never projected (documented gap).

## Cloud API (`cloud_api.py`, ~608 lines)

- `pg()` — minimal PostgREST client over `SUPABASE_URL/rest/v1` with the service-role key; returns `{"_error": code, "detail": …}` on HTTPError.
- `authed_user()` — verifies a user JWT via GoTrue `/auth/v1/user`.
- `need_hub` — `X-Hub-Key == CLOUD_API_KEY`.
- Tenant model: `businesses → branches`, `business_memberships` (role admin|manager|cashier), `branch_memberships`.
- `apply_event(e)` — projects events into cloud tables: `SALE_CREATED` (sales+sale_items+stock_movements), `STOCK_MOVED` (+`stock_balances` upsert), `PRODUCT_*`, `SALE_VOIDED`, `RETURN_POSTED`, `PURCHASE_RECEIVED`, `TRANSFER_*`. Wrapped in `except: pass` at call sites (see audit BUG-7).
- Sequence: `rpc/alloc_sequence` (migration 0002) — per-branch counter.
- Web till API: `/api/web/products`, `/api/web/sale` (+detail, +void), `/api/web/reports`, `/api/web/members` (+role/remove), `/api/web/product`, `/api/web/stock`, `/api/onboarding`, `/api/branches` (+update/delete), `/api/v1/auth/login`.
- CORS `*` on everything; serves `web/` statically with SPA-ish 404 fallback.
