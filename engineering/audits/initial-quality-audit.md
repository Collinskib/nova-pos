# Initial Quality Audit — 2026-11-13

Evidence-based findings from the first code inspection. Severity: **C**ritical (data loss/money wrong), **H**igh (broken feature/security), **M**edium, **L**ow. Status: ✅ fixed+verified · 🔧 fix in progress · ⬜ open.

## Critical — data integrity / financial

| ID | Finding | Evidence | Status |
|---|---|---|---|
| BUG-1 | Device-pushed sales never adjusted hub stock, wrote no `stock_movements`, no `payments` rows | `apply_sale_event` inserted only `sales`+`sale_items` | ✅ |
| BUG-2 | Shift close `expected_cash` counted **all** sales totals, including M-Pesa/card/credit | `shift_close` summed `sales.total` for the device window | ✅ now cash-payments only |
| BUG-3 | `/api/checkout` trusted client-supplied `price`/`name` — arbitrary price tampering, wrong VAT/totals | request `items[].price` used directly | ✅ server prices from DB |
| BUG-4 | Web till `/api/web/sale` wrote rows with **no sync event** — invisible to hub `_cloud_pull` → stock/reports diverge between web till and hub | no `sync_events` insert; `_emit` unused by sale path | ✅ emits SALE_CREATED |
| BUG-5 | `sales.created` = `datetime.now()` (local naive) for hub sales vs UTC `device_created_at` for device sales → date-filtered reports/shift windows inconsistent; UI `tm()/td()` already render stored values as UTC | `checkout`/`held`/`users` writes | ✅ UTC now |
| BUG-6 | `_cloud_pull` wrote cloud events with the **cloud** `server_sequence` into the local stream — sequence-space collision; devices past that cursor never see cloud-originated events | `INSERT…server_sequence=e["server_sequence"]` | ✅ local seq allocated |
| BUG-7 | `cloud_api.push()`/`_emit` wrapped `apply_event` in `except: pass` — "accepted" events could silently never project | bare except | ✅ failures → `sync_conflicts` row |
| BUG-8 | `web_sale` / `web_sale_void` / `STOCK_MOVED` projector do read-modify-write on `stock_balances` → concurrent sales lose updates | GET→PATCH non-atomic | 🔧 `adjust_stock_balance` RPC written (0004) + wired; needs live apply |
| BUG-26 | Cloud `sync_events.event_id` dedupe | re-check: `0001_foundation.sql` already declares `event_id uuid not null unique` — PostgREST 409 handled in push() | ✅ schema-verified |
| BUG-14 | Web receipt `WEB-<epoch>` — two sales in the same second collide on `unique(branch_id, receipt_number)` | `cloud_api.py` web_sale | ✅ `rpc/alloc_sequence` counter |

## High — broken features / security

| ID | Finding | Status |
|---|---|---|
| BUG-9 | Mobile VAT hardcoded `0.16/1.16`; hub/web read `tax_rate` setting | ✅ mobile reads `tax_rate` from `/api/v1/settings` via refreshCatalog |
| BUG-25 | Promo codes stored on the sale but never validated/applied server-side on hub checkout (`promo_code` is decorative; the discount is whatever the cashier typed) | ✅ applied server-side |
| BUG-10 | `web_member_role` last-admin guard only fired for `role=="cashier"` — demotion to `manager` bypassed it; also self-demotion to manager allowed | ✅ guard for any non-admin role |
| BUG-17 | Hub accepts all event types but projected only `SALE_CREATED` | ✅ `apply_incoming_event` covers all types (push + cloud pull); TRANSFER_* stored for later |
| SEC-2 | `/api/v1/sync/status` unauthenticated — leaks outbox backlog, device count, stream head on LAN | ✅ device-or-session auth |
| SEC-3 | `POST /api/lookup/<kind>` allowed any logged-in user (cashier) to create categories/brands/suppliers while DELETE required admin | ✅ admin-gated POST |
| SEC-1 | Passwords hashed with unsalted SHA-256 | ✅ PBKDF2-60k + transparent re-hash on login; regression test |
| SEC-8 | `must_change` flag advisory only | ✅ `before_request` blocks all /api/* until password set |

## Medium / Low

| ID | Finding | Status |
|---|---|---|
| BUG-11 | `/api/forgot` → 500 KeyError when `username` key absent | ✅ |
| BUG-23 | `POST /api/promos` duplicate code → unhandled IntegrityError → 500 | ✅ |
| BUG-13 | `apply_sale_event` inserted `sale_items.product_id` as `str` (schema INT) | ✅ coerced int |
| BUG-16 | `web_sale` never checked stock availability | ✅ stock guard refuses when known balance insufficient |
| BUG-22 | Pairing token written to `audit_logs.detail` (`device.pairing_issued` logs the secret) | ✅ redacted |
| SEC-4 | `/api/upload` allows SVG → stored-XSS surface | ✅ SVG rejected on upload + not cached from remote |
| SEC-5 | `localize_image` fetches arbitrary admin-supplied URLs (SSRF-ish) | ⬜ low |
| BUG-18 | Several handlers never close `db()` connections (`products`, `resets`, `sync_pull`…) — works via GC, sloppy under load | ⬜ |
| SEC-9 | Committed Google OAuth `client_secret_*.json` remains in git history | ⬜ needs Google Cloud rotation |
| SEC-10 | CORS `*` on cloud API (Bearer-token API — low CSRF risk but noisy) | ⬜ |
| BUG-27 | `apply_sale_event` collision-fallback `inv += "-"+suid[:4]` produces `INV-x-1234` — fine, noted | — |

## Verified good

- `sync_push` dedupe + `BEGIN IMMEDIATE` sequence allocation (test proves 5× push → 1 event).
- `sync_ack` uses `MAX(last_sequence, …)` — cursor can't regress.
- Checkout rollback leaves zero partial writes (test proves).
- Pairing tokens: single-use, 10-min expiry, upper-cased.
- `forgot` returns identical response for unknown users (no enumeration).
- `user_del` blocks self-delete; `user_role` blocks self-role-change.
- Sales void is admin-gated and restores stock + records movements + emits event.
- `_auto_sync` retry/backoff, `cloud_acked` only after confirmed accept.
