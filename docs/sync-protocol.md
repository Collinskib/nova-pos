# Sync protocol (BUILD.md §8) — implemented subset

The hub (this Flask app) accepts durable business events and distributes
them back to devices. Event flow: device outbox → hub `sync_events`
(stream-ordered) → device pull.

## Envelope (§8.1)

```json
{"event_id": "uuid", "business_id": 1, "branch_id": 1, "device_id": 5,
 "device_sequence": 123, "event_type": "SALE_CREATED", "schema_version": 1,
 "entity_id": "uuid", "device_created_at": "…Z", "payload": {}}
```

Server adds `server_received_at`, `server_sequence` (per-branch, allocated
under a locked `sync_streams` counter row — §8.3), and writes a
`sync_receipts` row.

## Endpoints (all device-authenticated via `X-Device-Key`)

| Route | Behaviour |
|---|---|
| `POST /api/devices` (admin session) | issue a 10-min one-use pairing token |
| `POST /api/v1/devices/pair` | redeem token → `{device_id, device_key}` |
| `GET  /api/v1/devices/me` | device self-info |
| `POST /api/devices/{id}/revoke` (admin) | block future sync access |
| `POST /api/v1/sync/push` | `{events:[…]}` → `{accepted,duplicates,rejected}`; re-pushing an `event_id` re-acks without re-applying |
| `GET  /api/v1/sync/pull?after_sequence=&limit=` | ordered events after cursor (or caller's stored cursor) |
| `POST /api/v1/sync/ack` | `{last_sequence}` — advance caller's cursor **only after durable local storage** |
| `GET  /api/v1/sync/status` | stream head, outbox backlog, open conflicts, device lag |
| `GET  /api/v1/sync/conflicts` | unresolved conflicts |

## Rules enforced

- Dedupe by `event_id`; duplicate delivery is a no-op.
- `server_sequence` is the only pull cursor — never timestamps.
- Cursor advances via `ack` only, after the batch is stored.
- Hub-ack vs cloud-ack tracked separately (`sync_outbox.hub_acked/cloud_acked`).
- Local writes emit events atomically: sale, void, stock movement, product,
  purchase, expense, return are committed in the same transaction as their
  `sync_events`/`sync_outbox` rows.

## Local event sources

`SALE_CREATED`, `SALE_VOIDED`, `STOCK_MOVED`, `PRODUCT_CREATED`,
`PRODUCT_UPDATED`, `PRODUCT_DELETED`, `RETURN_POSTED`,
`PURCHASE_RECEIVED`, `EXPENSE_POSTED`, `TRANSFER_DISPATCH`,
`TRANSFER_RECEIVE` (reserved).

## Not yet implemented (needs Phase 5 + hardware)

- Cloud API / Supabase ingestion and RLS (SQL in `supabase/migrations/`).
- LAN discovery, QR rendering, LAN TLS; conflict auto-resolution policies.
- Stock transfer lifecycle endpoints; offline stock allowances (§6.4).
