# Daily progress

## Cycle 1 — checkout integrity + sync convergence (verified)

17/17 tests pass (`tests/test_app.py`, `.test-venv`). `tsc --noEmit` clean on mobile.

| Fix | Where | Status |
|---|---|---|
| Checkout re-reads price/name/tax/stock server-side; client prices never trusted | `app.py` | verified |
| Wholesale price list + pack pricing honored (`price_list`, `pack` flags wired through UI) | `app.py`, `templates/index.html` | verified |
| Bulk deal (`discount_qty`/`discount_pct`) applied server-side | `app.py` | verified |
| Promo codes validated (active, min spend) and applied; duplicate code rejected cleanly | `app.py` | verified |
| Split payments persisted as `payments` rows; credit needs no tender; underpayment rejected atomically | `app.py` | verified |
| UTC timestamps on sales/payments/held/stock entries (`utcts()`) | `app.py` | verified |
| `apply_sale_event` now decrements hub stock + ledger + writes payment rows (was: sales only) | `app.py` | verified |
| `apply_incoming_event` projector: voids, stock moves, product CRUD, returns, purchases, expenses — applied on push AND cloud pull; failures logged to `sync_conflicts` | `app.py` | verified |
| `_cloud_pull` re-sequences cloud events into the local counter domain (LAN devices were previously blind to cloud/web events) | `app.py` | verified |
| `cloud_sync` entity_id coerced to uuid (was inserting "INV-…" into uuid column → push failure) | `app.py` | verified |
| Shift close expected-cash counts cash payments only (was all sale totals) | `app.py` | verified |
| `/api/v1/sync/status` requires auth; `POST /api/lookup/*` requires admin; pairing token no longer logged to audit | `app.py` | verified |
| `/api/v1/settings` endpoint (tax_rate/currency) for till devices | `app.py` | verified |
| Web till `web_sale` writes through the event store (`_emit` + `alloc_sequence` receipt), stock guard, idempotent via `client_ref` | `cloud_api.py` | implemented — needs live Supabase to verify |
| `SALE_CREATED` projector: payments rows, `subtotal`/`customer_name`/`client_ref`, balance deltas | `cloud_api.py` | implemented — needs live Supabase |
| RETURN/void/STOCK_MOVED update `stock_balances` via atomic `adjust_stock_balance` RPC (migration 0004); read-modify-write fallback removed races | `cloud_api.py`, `supabase/migrations/0004_*.sql` | implemented — needs live Supabase |
| Projection failures logged to `sync_conflicts` (were swallowed) | `cloud_api.py` | implemented |
| `web_sale_void` emits `SALE_VOIDED` so hubs void local copies | `cloud_api.py` | implemented |
| `web_member_role` guards all demotions (was cashier-only — managers could orphan the last admin) | `cloud_api.py` | implemented |
| Mobile VAT uses hub `tax_rate` setting (was hardcoded 16%); rate synced in `refreshCatalog` | `mobile/` | verified (tsc) |

## Verification evidence
- New regression tests: tampered price/name/taxable, wholesale, pack, bulk discount, split payments, credit, underpayment rollback, promo validation + duplicate, pairing-token single-use, UTC timestamp.
- Manual smoke: `/api/v1/settings` returns `tax_rate: 16.0`; `/api/v1/sync/status` → 401 unauthenticated; cashier `POST /api/lookup/suppliers` → 403.
- `test_return_restocks_and_ledgers` fixed — it asserted the client-supplied price (10.0) which is no longer trusted.

## Cycle 2 — security hardening + P2 workflows (verified)

22/22 tests pass; `tsc --noEmit` clean; web `app.html` JS parses.

| Fix | Where | Status |
|---|---|---|
| PBKDF2-60k password hashing; legacy sha256 rows transparently re-hash on login | `app.py` | verified (test) |
| Login rate-limit: 5 failures / 5 min per IP+username → 429 | `app.py` | verified (test) |
| `must_change` enforced server-side — all /api/* blocked until password set | `app.py` | verified (test) |
| SVG dropped from upload allowlist + remote image cache | `app.py` | verified |
| Cash in/out mid-shift: `cash_movements` (mig 11), `/api/v1/shifts/cash-move`, counted in expected_cash, mobile UI on Sync screen | `app.py`, `mobile/` | verified (test) |
| Credit ledger: `customers.balance`, `credit_payments` charge/payment, `/api/customers/<id>/pay` + `/ledger`; credit requires a registered customer | `app.py` | verified (test) |
| FEFO batch decrement on checkout (expiring batches first) | `app.py` | verified (live probe) |
| Concurrent product edits → `sync_conflicts`; `/api/sync/conflicts` list + resolve | `app.py` | implemented |
| Mobile inbound projectors: SALE_CREATED/VOIDED, STOCK_MOVED, RETURN_POSTED, PURCHASE_RECEIVED, EXPENSE_POSTED — sale rows, payments, stock + balances; unmapped products → conflicts | `mobile/src/sync/engine.ts` | verified (tsc) |
| Web offline queue: server-rejected sales retained in `shujaa_failed` with review/discard UI (were silently dropped) | `web/app.html` | verified (js check) |
| Backup temp file cleaned after send; audit connection closed | `app.py` | verified |

## Cycle 3 — live end-to-end sync verification (verified against real Supabase)

Stood up `cloud_api.py` :5060 + hub :5050 with `.env`, verified against the live project:

- **Migration 0004 applied** via Management API (`adjust_stock_balance` RPC live; stale `SUPABASE_DB_URL` password noted).
- **hub→cloud push**: PRODUCT_CREATED + SALE_CREATED projected → products/sales/items/payments/movements/balances all land; replay deduped by event_id.
- **web→cloud**: `/api/web/sale` → sale + items + payments + sync_events row + balance decrement; `client_ref` replay → `dup:true`; receipt `WEB-000730` via alloc_sequence.
- **cloud→hub pull**: WEB-000734 projected into local `sales` + `sale_items` + `payments`, product stock 50→49 — full round trip works.
- **Catalog backfill**: cloud `products`/`stock_balances` were empty (seeded hub products predate sync) — pushed PRODUCT_CREATED for all 11 + seeded balances; web till now has a real catalog.
- **Historical evidence of old bug**: 4 cloud sales with zero items — silent projection failure, now logged to `sync_conflicts` instead.

Two bugs found & fixed during verification:
- `_emit` never set `entity_id` → web-originated events were silently skipped by `apply_sale_event` (`entity_id` now = sale uuid; doubles as `sales.id` so voids propagate).
- `cloud_sync` returned early when outbox empty → `_cloud_pull` never ran between pushes; hub only saw cloud events when it had something to send.
- `app.py` never loaded `.env` (no dotenv) → autosync silently never started; tiny built-in loader added.

Test residue: WEB-000730 predates the entity_id fix (NULL entity) so it never projects — hub/cloud cola stock differ by 2 on synthetic data.

## Blocked on external
- Google OAuth secret rotation (SEC-9) — needs Google Cloud console.
- Production deploys (Vercel web, cloud hosting, `CONF.api`/`YOURDOMAIN`) — needs approval.
- `SUPABASE_DB_URL` password stale — direct psql unavailable; Management API works.
- Real-device verification of the Expo till — needs a physical device/emulator.

## Cycle 4 — real-hardware + emulator mobile verification (Nov 13)

Device targets: physical phone (Expo Go, LAN) and Android emulator `shujaa` (Pixel 6, API 35) via adb reverse → hub `localhost:5050`.

**Bugs found & fixed live on device:**

| Finding | Fix | Verified |
|---|---|---|
| Products seed INSERT: 17 cols / 18 placeholders — pairing crashed post-success | `repos.ts` placeholder count | pair → seed → till on emulator |
| Device sales never relayed to cloud — `sync_outbox` only held hub-originated events | hub enqueues accepted device events for cloud push | MOB-000010–16 in Supabase |
| `_cloud` 15s timeout killed a 31-event push mid-flight | raised to 120s | `unacked: 0` after autosync |
| Cloud projector read only float money → mobile `_cents` events wrote total 0.0 | `_amt()` dialect normalizer | all 6 cloud sales corrected |
| Mobile decoded hub `payload` JSON *string* as object → `EXT-*` zero-total shells + product forks | `payloadOf()` boundary decode + normalized inbox + repair v4 (EXT-* shells, orphan rows, uuid forks, negative payments) | Today/Sales show real receipts/totals |
| Negative split-tender rows persisted (mobile emit + hub + cloud projectors) | guard `amt<=0 && method!='credit'` on all three emit/project paths | MOB-000015 shows single cash row |
| Pull projectors (STOCK_MOVED, sale items, returns/purchases) matched only raw event id → silent stock skips | `productKey()` (int id / uuid5 / barcode) everywhere | catalog deduplicated, stock converged |
| No open-shift gate — sales posted with no till session | POS amber banner → Sync tab (best-effort, offline-safe) | banner verified on emulator |
| Cart qty could exceed stock until checkout error | clamp `addToCart`/`setQty` at `stock` | tsc |
| `businesses` RLS: enabled, zero policies — members saw nothing | migration 0005 read policy | member reads `Emu` |
| Pair-code GBoard mangling | `autoCorrect=false`, `autoCapitalize=characters`, `visible-password`, deep-link prefill (token/hub params) | paired via `shujaa-pos://pair` intent |
| Mobile had no signup/onboarding (dead-end "no membership") | signup mode + onboarding card → `/api/onboarding` on `shujaapos.onrender.com` | full flow on emulator |
| Desktop hub had no cloud sign-in | `/api/cloud_login`: Supabase token verify + membership check + local provisioning | real token: 403 non-member → 200 member |
| Google OAuth on mobile | `expo-web-browser` round-trip + deep-link listener fallback + redirect allow-list (`shujaa-pos://**`, `exp://**`) | Google page + project redirect verified; **real-account return-to-app still pending** |

**Regression:** 30 Flask tests pass (incl. cloud_login invalid/non-member/provisioning + payment guards); `tsc --noEmit` clean throughout; lockfile consistent (expo-web-browser 58.0.8).

**Still blocked on external:** Google OAuth return-to-app needs a real Google account; SEC-9 secret rotation needs Google Cloud console; `SUPABASE_DB_URL` direct-psql password stale (Management API works).
