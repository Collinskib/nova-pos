# ShujaaPOS — Progress Report

*Updated: Nov 8, 2026. Ask me anytime and I'll refresh this.*

## The product

**ShujaaPOS** — offline-first POS for Kenyan retail. Repo: `Collinskib/nova-pos` (local: `~/Documents/nova-pos`).

- **Hub** (`app.py`) — Flask + SQLite till/admin, `pos.db`
- **Mobile** (`mobile/`) — Expo SDK 58 app, pairs via QR/LAN, sells offline
- **Cloud bridge** (`cloud_api.py`) — Supabase ingest + auth/onboarding APIs, :5060
- **Web SaaS** (`web/`) — static app: landing + `/app` (login/dashboard) + `/blog`
- **Desktop** — `desktop.py` + `shujaa.spec` + CI builds all platforms

## Done — product features

- Rebranded Nova → **ShujaaPOS** everywhere (icon, app.json, spec, workflow)
- ERPNext gap list (`CHANGES.md`) — implemented: **till shifts + reconciliation, split payments, M-Pesa/card/credit, customers + credit sales, price lists (retail/wholesale), invoice discounts, promo codes, item variants, pack/UOM sales, batch/expiry tracking**
- Ported all of the above to the **hub** too (pay modal: method/customer/discount/promo; POS: wholesale toggle + variant/pack picker)
- Mobile: receipt sheet, paid/change display, customer on receipt, sign-out/re-pair, QR pairing fixed, admin tab (products/reports/users/devices), auto product sync incl. deletions
- Hub: sales auto-refresh, tab persistence on reload, local-time timestamps, devices sorted by last-seen, shift history card, batches card on Inventory
- Timestamps stored UTC, displayed local

## Done — SaaS/multi-tenant

- Supabase schema already had tenants (`businesses`, `branches`, `business_memberships`, RLS read policies) — verified live
- `cloud_api.py`: `GET /api/me`, `POST /api/onboarding` (store+branch+admin membership), `POST /api/branches` (admin-gated), JWT verify via GoTrue, CORS, serves `web/` statically
- `web/`: Supabase auth (email verify **done** by user, Google OAuth **configured** by user), onboarding flow, tenant dashboard (today's KPIs, sales, products, branches+add, devices)
- `web/config.js`: anon key set, `CONF.api` currently `localhost:5060` — swap when Render deploys

## Done — installers (CI: `.github/workflows/builds.yml`)

Tag-triggered (`v*`) + manual dispatch to save private-repo minutes:
- Windows `.exe`, Linux binary + **AppImage**, macOS `.app` **arm64 + Intel**, Android **APK** (debug-signed via expo prebuild)
- Fixes landed: dropped broken setup-android (SDK preinstalled), `npm ci --legacy-peer-deps` (react peer conflict), appimagetool moved to `AppImage/appimagetool`
- Local Linux binary verified: `dist/shujaa-pos` (23MB)

## Done — content/SEO

- **Skill**: `.devin/skills/shujaa-content` (editorial rules, clusters, article contract)
- `content-ideas.md` — 34 ideas in 5 clusters + signature Retail Report + month-1 schedule
- **Live articles** (humanized — no em dashes): `what-is-a-pos-system` (pillar + real screenshot), `pos-loses-internet`, `offline-pos-explained`, `cloud-vs-offline-pos`, `manage-stock-retail-shop-kenya`, `cash-control-till-reconciliation`, `split-payments-mpesa-card`
- `web/vercel.json` (cleanUrls), `robots.txt`, `sitemap.xml` — `YOURDOMAIN` placeholders

## Running services

- Hub: `http://127.0.0.1:5050` (LAN `192.168.18.10:5050`) — `admin/admin123`, `cashier/cashier123`
- Cloud API: `:5060` · Logs: `/tmp/pos.log`, `/tmp/cloud.log`, `/tmp/expo.log`

## TODO / open

- **Deploy**: web/ → Vercel (import repo, root=`web`, framework=Other); cloud_api.py → Render/Railway (needs Python host); swap `CONF.api` to deployed URL; replace `YOURDOMAIN` in robots/sitemap/canonicals
- **Rotate Google OAuth secret** — `client_secret_*.json` was committed to git history (untracked now, secret still in history → regenerate in Google Cloud Console)
- GitHub repo still named `nova-pos` (rename optional, redirects keep working)
- Articles left: interview/survey-dependent pieces (shop-owner quotes, price surveys, Retail Report) + more product-backed (`customer-credit-sales-tracking`, `sales-reports-numbers`, `product-variants-packs`, `staff-shifts-roles`)
- Release signing (Windows exe unsigned → SmartScreen; APK debug-signed; Mac unsigned → Gatekeeper)
- UptimeRobot keep-alive hack for Render free tier — optional
