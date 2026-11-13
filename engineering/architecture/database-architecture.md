# Database Architecture

## Local (hub): SQLite `pos.db`

39 tables (verified via `sqlite_master`). Three generations of schema:

**Core POS (base `SCHEMA`)**: `users`, `categories`, `brands`, `suppliers`, `products`, `stock_entries`, `sales`, `sale_items`, `held_sales`, `reset_requests`, `settings`.

**Sync/tenancy (mig 1–2)**: `schema_versions`, `businesses`, `branches`, `devices`, `pairing_tokens`, `audit_logs`, `sync_events`, `sync_streams`, `sync_outbox`, `sync_cursors`, `sync_receipts`, `sync_conflicts`, `payments`, `receipt_counters`, `stock_movements`, `returns`, `return_items`, `purchases`, `purchase_items`, `expenses`, `expense_categories`, `subscriptions`, `subscription_events`. Tenant/uuid columns added to `sales`, `products`, `stock_entries` (default business/branch = 1).

**Feature migrations (3–10)**: `sales.cashier_name` (3), `shifts` (4), `customers` + `sales.customer_name` (5), `products.price_wholesale` (6), `promos` + `sales.promo_code` (7), `products.parent_id/variant_label` (8), `products.pack_size/pack_price` (9), `batches` (10).

### Integrity notes

- `products.barcode UNIQUE`, `sales.invoice_no UNIQUE`, `sync_events.event_id UNIQUE`, `sync_outbox.event_id UNIQUE`.
- `products.stock`, `sales.total`, money columns are `REAL` (float) on the hub — mobile/cloud use integer cents in transit (`*_cents`), converted at the edge.
- `products.stock` is a denormalized balance; `stock_movements` is the ledger. They can drift — the audit found pushed device sales wrote no movements and no stock update (fixed).
- `sales.created` mixed local-naive (`datetime.now()`) and UTC (`device_created_at`) values before the cycle-1 fix.
- No `ON DELETE` cascades declared; deletion is hard-delete for products, soft-delete for sales (`status='void'`), `active=0` for devices/promos.

## Mobile: expo-sqlite (per device)

`products` (id TEXT = hub product id as string, `*_cents` money), `sales`, `sale_items`, `payments`, `stock_movements`, `stock_balances`, `transfers`, `transfer_items`, `sync_outbox`, `sync_inbox`, `sync_cursors`, `sync_receipts`, `device_state` (kv: `device_seq`, `receipt_seq`). Receipt numbers `MOB-NNNNNN` device-scoped.

## Cloud: Supabase Postgres (`supabase/migrations/`)

`businesses`, `branches`, `profiles`, `business_memberships`, `branch_memberships`, `devices`, `products`, `sales`, `sale_items`, `payments`, `stock_movements`, `stock_balances`, `stock_transfers`, `stock_transfer_items`, `sync_events`, `sync_stream_counters`, `sync_device_cursors`, `sync_conflicts`, `audit_logs`, `subscriptions` (+ mig 0002 `alloc_sequence` RPC, 0003 `sales.customer_name`, `sales.client_ref`).

- All IDs `uuid` with `gen_random_uuid()`; composite FKs `(id, business_id)`/`(business_id, branch_id)` enforce tenant consistency.
- `sales` unique `(branch_id, receipt_number)`.
- RLS enabled on all tenant tables — **read policies only** (`tenant_read_*` scoped to `business_memberships`); all writes go through `cloud_api.py` with the service key. That is by design and documented in `docs/deployment.md`.
- **No unique constraint on `sync_events.event_id` visible in 0001** — dedupe relies on the API's read-then-insert check (race window: two simultaneous pushes of the same event could both insert; see audit BUG-26).
- `stock_balances` updated by read-modify-write from `cloud_api.py` — concurrent writers can lose updates (audit BUG-8).
