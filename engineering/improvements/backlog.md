# Engineering Backlog — prioritized (assignment §10 order)

## P1 — critical security / data integrity (cycle 1 — done this session)

- [x] BUG-3 server-side pricing on checkout
- [x] BUG-1 pushed-sale projector: stock + movements + payments
- [x] BUG-6 cloud-pull sequence-space collision
- [x] BUG-4 web till emits SALE_CREATED
- [x] BUG-2 shift expected = cash payments only
- [x] BUG-5 UTC writes on sales/ledger tables
- [x] BUG-7 projection failures → sync_conflicts, never silent
- [x] BUG-25 server-side promo validation
- [x] BUG-10 last-admin guard for all demotions
- [x] BUG-11/BUG-23 500s → 400s; BUG-22 token redaction; SEC-2/SEC-3 auth

## P1 remaining — needs live Supabase or product decision

- [x] BUG-8 atomic stock adjust — `adjust_stock_balance` RPC (migration 0004) applied to live Supabase; verified 90→91→90 roundtrip via PostgREST, `cloud_api.py` on the atomic path
- [x] BUG-26 `sync_events.event_id` UNIQUE — verified already present in `0001_foundation.sql`; 409 dedupe path exercised
- [x] SEC-1 PBKDF2-60k password hashing + transparent sha256→pbkdf2 re-hash on login (regression-tested)
- [ ] SEC-9 rotate Google OAuth secret + purge from history
- [x] BUG-9 mobile reads `tax_rate` from `/api/v1/settings` (synced in `refreshCatalog`)
- [x] BUG-16 web till stock guard — refuses sale when known balance insufficient (`web_sale`)

## P2 — broken/missing core workflows

- [x] BUG-17 hub projectors for STOCK_MOVED, PRODUCT_*, SALE_VOIDED, RETURN_POSTED, PURCHASE_RECEIVED, EXPENSE_POSTED (`apply_incoming_event`, applied on push + cloud pull; conflicts logged)
- [x] Split payments on hub `/api/checkout` (`payments[]` accepted, rows persisted, single `cash` back-compat kept)
- [x] Cash in/out mid-shift movements — `cash_movements` table (mig 11), `/api/v1/shifts/cash-move`, counted in expected_cash, mobile UI on sync screen
- [x] Credit-sale balance ledger — `customers.balance`, `credit_payments` charge/payment rows, `/api/customers/<id>/pay` + `/ledger`, credit requires registered customer
- [x] Batch FEFO decrement on sale — expiring batches deplete first on checkout
- [x] Conflict detection — `concurrent_product_edit` → `sync_conflicts`; `/api/sync/conflicts` list+resolve endpoints
- [ ] Hub multi-branch: everything hardcodes branch 1 — needs branch model first (ADR-6)

## P3 — UX / hardening

- [x] SEC-4 SVG dropped from upload allowlist + image cache
- [x] SEC-8 `must_change` enforced server-side (`before_request` blocks /api/*)
- [x] Login rate-limit (5 fails / 5 min per IP+username → 429)
- [x] Backup temp-file cleanup (`after_this_request` unlink) + audit connection close
- [ ] Connection hygiene: `with db()` context manager everywhere
- [ ] Empty/error/loading states sweep on web app.html; mobile till edge cases (very long names, huge qty, KES formatting)
- [ ] Receipt printer templates (80mm), Z-report print
- [ ] Playwright smoke for hub UI + web till; device-farm or Expo web for mobile screens

## P4 — feature gaps (product research)

- Loyalty points, salesperson commission, quotations, stocktake sessions, M-Pesa STK push, subscription enforcement, branch-level reporting consolidation, offline stock allowances (§6.4), supplier returns, barcode label printing.

_Research sources queued: Square/Shopify POS/Loyverse/Lightspeed feature docs, ERPNext POS (CHANGES.md baseline)._
