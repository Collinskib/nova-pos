# Synchronization Architecture

## Event envelope (docs/sync-protocol.md §8.1)

```json
{"event_id": "uuid", "business_id": 1, "branch_id": 1, "device_id": 5,
 "device_sequence": 123, "event_type": "SALE_CREATED", "schema_version": 1,
 "entity_id": "uuid", "device_created_at": "…Z", "payload": {}}
```

Server adds `server_received_at` + `server_sequence` (per-branch counter) and writes a `sync_receipts` row.

## Flows

### Mobile → Hub (`mobile/src/sync/engine.ts`)

1. Push `sync_outbox` (local, `cloud_acked=0`) → hub `/api/v1/sync/push`. Accepted+duplicates marked acked; timeout = retry with same IDs. 401/403 → "repair" state (re-pair needed).
2. Pull hub `/api/v1/sync/pull?after_sequence=<cursor>` → `sync_inbox` (deduped by `event_id`) → `applyEvent` → cursor advances locally → `POST /api/v1/sync/ack`.
3. Catalog refresh (`/api/v1/products`) every cycle — authoritative re-seed so product churn reaches devices even if event pull fails.
4. Loop with 3 s base + exponential backoff to 120 s + jitter.

### Hub → Cloud (`/api/admin/cloud-sync` or `_auto_sync` thread)

1. Push `sync_outbox WHERE cloud_acked=0` (≤100) → cloud `/api/v1/sync/push`. `cloud_acked=1` only on accepted/duplicate — timeouts never lose events.
2. Pull cloud `/api/v1/sync/pull?branch_id=<uuid>&after_sequence=<settings.cloud_pull_seq>` → `INSERT OR IGNORE` into local `sync_events`, cursor in `settings.cloud_pull_seq`.

### Rules enforced (verified)

- Dedupe by `event_id`; re-push is a no-op re-ack.
- `server_sequence` is the pull cursor — never timestamps.
- Cursor only advances via `ack` after durable local writes.
- Hub↔cloud acks tracked separately (`hub_acked`/`cloud_acked`).
- Atomic emission: business write + `sync_events` + `sync_outbox` commit in one transaction (checkout, void, stock, product, purchase, expense, return).

## Event types

`SALE_CREATED`, `SALE_VOIDED`, `STOCK_MOVED`, `PRODUCT_CREATED`, `PRODUCT_UPDATED`, `PRODUCT_DELETED`, `RETURN_POSTED`, `PURCHASE_RECEIVED`, `EXPENSE_POSTED`, `TRANSFER_CREATED`, `TRANSFER_DISPATCH`, `TRANSFER_RECEIVE`.

## Projection coverage (the honest picture)

| Event | Hub applies on push | Cloud applies | Mobile applies on pull |
|---|---|---|---|
| SALE_CREATED | ✅ (sales + items; **stock/payments added in cycle 1**) | ✅ sales + items + movements | stored only |
| STOCK_MOVED | ❌ stored only | ✅ movements + balances | ❌ |
| PRODUCT_* | ❌ (devices refresh catalog instead) | ✅ upsert | ✅ upsert/delete |
| SALE_VOIDED | ❌ | ✅ status=void | ❌ |
| RETURN_POSTED | ❌ | ✅ movements | ❌ |
| PURCHASE_RECEIVED | ❌ | ✅ movements | ❌ |
| EXPENSE_POSTED | ❌ | ❌ | ❌ |
| TRANSFER_* | ❌ (no transfers tables on hub) | ✅ full lifecycle | ✅ full lifecycle |

## Sequence-space hazard (fixed in cycle 1)

`_cloud_pull` used to write cloud events into the local `sync_events` stream **keeping the cloud `server_sequence`** — colliding with the local `sync_streams` counter domain. Any cloud event with a sequence below a device's cursor was invisible to that device forever. Fixed: pulled events are stored under a newly allocated local `server_sequence` (payload keeps the original).
