# ShujaaPOS — System Overview

*Verified against source on 2026-11-13. Describes what exists, not what is planned.*

## Components

| Component | Path | Stack | Role |
|---|---|---|---|
| **Hub** | `app.py` | Python 3.12, Flask, SQLite (`pos.db`), vanilla-JS SPA in `templates/` + `static/pos.css` | Local till + admin + LAN sync server. Port 5050. |
| **Mobile till** | `mobile/` | Expo SDK 58 / React Native 0.88, expo-sqlite, zustand, expo-router | Pairs to hub over LAN, sells offline, syncs via events. |
| **Cloud API** | `cloud_api.py` | Python, Flask, Supabase PostgREST (service-role key, server-side only) | Event ingestion, web till API, SaaS onboarding/members/branches. Port 5060, deployed on Render. |
| **Web app** | `web/` | Static HTML/JS, `@supabase/supabase-js` v2 (anon key), service worker | Landing + `/app` dashboard + web till + `/blog`. Served by cloud_api and Vercel. |
| **Desktop** | `desktop.py`, `shujaa.spec` | PyInstaller + pywebview (browser fallback) | Wraps the hub as an installable app. CI builds all OSes. |
| **Cloud DB** | `supabase/migrations/` | Supabase Postgres + GoTrue + RLS | Multi-tenant store of record in the cloud. |

## Trust & identity boundaries

- **Hub sessions**: Flask cookie session for staff (`users` table, role admin|cashier). Login at `/api/login`.
- **Device credential**: `X-Device-Key` (`dvk_*`), SHA-256-hashed in `devices.api_key_hash`. Issued at pairing via one-use 8-char token valid 10 min. Revocable (`devices.active=0`).
- **Hub→cloud**: `X-Hub-Key` shared secret (`CLOUD_API_KEY` in `.env`).
- **Web→cloud**: Supabase GoTrue JWT (user Bearer token) verified per request via `/auth/v1/user`.
- **Service-role key**: only in `.env`, used by `cloud_api.py` → PostgREST. Never shipped to clients.
- **Anon key**: in `web/config.js` (public by design; RLS is the boundary).

## Data flow

```
Mobile till ──(LAN, X-Device-Key)──> Hub /api/v1/sync/push|pull|ack
    ^                                     │
    └──── catalog /api/v1/products ◄──────┤
                                          │ X-Hub-Key
                                          ▼
   Web till (JWT) ──> Cloud API ──> Supabase PostgREST (RLS on anon reads)
                          ▲
   Web dashboard reads Supabase directly via anon key + RLS
```

- Local writes emit durable events atomically (`sync_events` + `sync_outbox` in the same txn).
- Dedupe by `event_id` everywhere. `server_sequence` per branch is the only cursor; ack advances it only after durable local storage.
- Hub→cloud: `POST /api/admin/cloud-sync` (or `_auto_sync` background thread when `POS_AUTOSYNC=1`) pushes `sync_outbox` and pulls cloud events back (`_cloud_pull`, cursor in `settings.cloud_pull_seq`).

## Ports & processes

| Service | Port | Start |
|---|---|---|
| Hub | 5050 | `.venv/bin/python app.py` (dev); `waitress-serve` (prod) |
| Cloud API | 5060 | `.venv/bin/python cloud_api.py` (needs `.env`) |
| Web static | 8080 | `python3 -m http.server` in `web/` (dev only) |
| Mobile | — | `cd mobile && npx expo start --lan` |

## Known structural limits (audited, see audits/initial-quality-audit.md)

- Hub ingest applies **only `SALE_CREATED`**; every other pushed event type is stored but never projected (`apply_sale_event` is the only projector).
- Hub's pushed-sale projector did not update stock/movements/payments (fixed in cycle 1).
- `_cloud_pull` re-sequences cloud events with the **cloud's** `server_sequence` into the local stream — two sequence spaces collide; devices can miss events (fixed in cycle 1 by allocating a local sequence on ingest).
- Web till `/api/web/sale` wrote rows directly with **no sync event** — invisible to hubs pulling cloud events (fixed in cycle 1).
- `sync_conflicts` tables exist on both sides but nothing writes conflicts — detection is a declared-but-absent feature.
