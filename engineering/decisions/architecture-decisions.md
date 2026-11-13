# Architecture decisions

## ADR-1: Event sourcing is the replication contract
All cross-node state changes travel as typed `sync_events` rows with globally
unique `event_id`s. Business records and their events are written in the same
transaction (hub: `emit_event`; mobile: `emit` in `repos.ts`; cloud/web:
`_emit`). Consumers dedupe by `event_id` and project into local tables.
**Consequence:** any write path that skips event emission (as web_sale did) is
a consistency bug by definition. New features must emit events.

## ADR-2: Sequence domains are local, never shared
The hub's `sync_streams` counter and the cloud's `alloc_sequence` are separate
number spaces. `_cloud_pull` re-sequences cloud events into the local counter —
importing foreign sequence values directly collides and hides events from LAN
devices (BUG-6). **Rule:** always allocate a local `server_sequence` when
importing events; preserve the foreign value in the payload (`_cloud_seq`).

## ADR-3: Prices are server-truth only
`/api/checkout` re-reads price, name, tax flag, stock, pack and bulk-deal data
from `products`. Client payloads carry intent (`id`, `qty`, `pack`,
`price_list`) never amounts. Same principle applied to `web_sale` (stock guard)
and is why sale-item prices must be re-derived in projectors.

## ADR-4: Money in minor units on mobile/cloud, floats on the hub
Mobile stores cents (`*_cents`), hub/web store floats. Projectors on both sides
normalize by presence of `*_cents` keys. New payloads should emit both where
cheap, or follow the emitting platform's convention and let projectors convert.

## ADR-5: Password storage — PBKDF2 with transparent upgrade
`users.pw` accepts `pbkdf2$iter$salt$hash` (new) and 64-hex sha256 (legacy).
Successful legacy logins re-hash silently. Device keys stay sha256 — they are
128-bit random tokens, not passwords, so a fast KDF is correct there.

## ADR-6: Single-branch hub (deferred multi-branch)
`DEFAULT_BUSINESS=1, DEFAULT_BRANCH=1` is hardcoded throughout `app.py` (stock
entries, emit_event, sales). Proper multi-branch needs: branch selection in
session, per-branch product/stock scoping, branch-aware reports, and cursor
streams per branch. Deferred — the Supabase schema is already branch-scoped so
the cloud side won't need rework, but hub work is a dedicated cycle.

## ADR-7: Conflicts are surfaced, never silent
Projection failures and unmapped references write `sync_conflicts` rows on
hub/mobile/cloud. Concurrent product edits (two writers, last-writer-wins
apply) also log conflicts with `concurrent_product_edit`. Admin resolution:
`GET/POST /api/sync/conflicts`. Silent `except: pass` on projection is banned.

## ADR-8: Web till offline = queue + retain failures
localStorage queue `shujaa_queue` retries while offline; deterministic server
rejections move to `shujaa_failed` (retained for manual review, never dropped
silently). The service worker only owns the app shell.

## Deferred
- Hub multi-branch (ADR-6)
- Loyalty points, stocktake sessions, M-Pesa STK push, receipt printer
  templates, salesperson commission — P4 backlog, need product prioritization.
- `sync_conflicts` resolution actions beyond mark-resolved (e.g. "keep local"
  vs "keep remote" apply) — needs product decision on merge UX.
