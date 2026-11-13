# Mobile Architecture (`mobile/`)

Expo SDK 58, React Native 0.88, TypeScript, expo-router, expo-sqlite, zustand, expo-secure-store, expo-camera.

## Layout

- `app/(auth)/login.tsx`, `pair.tsx` — staff picker + QR pairing flow.
- `app/(app)/` — `pos.tsx` (till), `sales.tsx`, `dashboard.tsx`, `products.tsx`, `reports.tsx`, `users.tsx`, `devices.tsx`, `admin.tsx`, `transfers.tsx`, `sync.tsx`.
- `src/db/` — `schema.ts`, `database.ts` (tx/all/one/run helpers), `repos.ts` (all business writes).
- `src/sync/engine.ts` — outbox push → inbox pull/apply → catalog refresh loop.
- `src/lib/api.ts` — `hub.*` typed calls (`X-Device-Key`, 8 s timeout), `creds` in SecureStore.
- `src/store/store.ts` — zustand UI state (hubUp, pending, syncState, lastSync).

## Offline behaviour

- Checkout is a single `tx()`: sale + items + stock_movements + `products.stock` + `stock_balances` + payments + `SALE_CREATED` event in `sync_outbox`.
- Offline stock policy: refuse the sale if the local mirror shows insufficient stock (no negative stock).
- Receipt numbers `MOB-NNNNNN` from `device_state.receipt_seq`.
- VAT **hardcoded 16% inclusive** (`t * 0.16 / 1.16`, scaled down by invoice discount) — independent of hub `tax_rate` setting (see audit BUG-9).
- Promos fetched from hub `/api/v1/promos`, validated client-side; result sent as `discount_cents` + `promo_code`.
- Transfers: full DRAFT → DISPATCHED → IN_TRANSIT/RECEIVED lifecycle local-first with TRANSFER_* events.

## Pairing

`pair.tsx` scans hub QR (from `/api/pair-qr` → `Devices` tab, payload = pairing token + hub URL) → `POST /api/v1/devices/pair` → `device_key` in SecureStore + `hub_url`. `creds.clear()` signs out/re-pairs.
