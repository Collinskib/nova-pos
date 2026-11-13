# Web Architecture (`web/`)

Static site, no build step. Served by `cloud_api.py` (`static_folder="web"`, SPA-ish 404 fallback) and by Vercel (`web/vercel.json`, cleanUrls).

## Pages

- `index.html` — marketing landing (light theme, Mauzo-inspired).
- `app.html` — the SaaS app: auth → onboarding → dashboard. Single file, ~800 lines.
- `blog/` — 10+ SEO articles + `index.html` + `_template.html`.
- `sw.js` — service worker: network-first HTML, cache-first assets, `localStorage` offline sales queue.
- `config.js` — `CONF.url` (Supabase), `CONF.anon` (public anon key), `CONF.api` (cloud API base — currently `https://shujaapos.onrender.com`).

## Auth & tenancy

- `supabase-js` v2 from CDN. Email sign-up (verify), sign-in, Google OAuth, `resetPasswordForEmail`.
- `/api/me` returns memberships; onboarding creates business + branch + admin membership.
- Data reads go **direct to PostgREST** with the anon key + RLS (`sb.from("sales"|"products"|"branches"|"devices")`).
- Mutations go through `cloud_api.py` `/api/web/*` with the user Bearer token — admin checks server-side (`_is_admin`), branch pick validated (`_pick_branch`).

## Web till

Cart → `POST /api/web/sale` {items, payments, discount, customer_name, client_ref} → sales + sale_items + payments + stock_balances decrement → receipt view + void (admin). Offline queue in `localStorage` replays with `client_ref` for idempotent retries.

## Known divergence (fixed in cycle 1)

`POST /api/web/sale` wrote rows directly **without emitting a `SALE_CREATED` sync event** — hub `_cloud_pull` never saw web-till sales, so local stock/reports diverged. Fixed: sale now writes through the event path.
