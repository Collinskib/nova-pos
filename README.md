# Mauzo POS

Offline-first point-of-sale for Kenyan retail — a local Flask till, an Expo mobile app, and a Supabase-backed cloud dashboard. Sell with no internet; everything syncs when you're back online.

## What it is

| Piece | Path | What it does |
|---|---|---|
| **Hub** | `app.py` | Local POS — sales, inventory, reports, devices, staff. SQLite, runs offline on any machine |
| **Mobile till** | `mobile/` | Expo/React Native app — pairs over LAN, sells offline, syncs to the hub |
| **Cloud bridge** | `cloud_api.py` | Ingests hub events into Supabase (multi-tenant Postgres) |
| **Web app** | `web/` | Static SaaS site — sign up (email verify / Google), create a store, dashboard for sales/products/branches |
| **Desktop app** | `desktop.py` | PyInstaller-packaged offline app — Windows `.exe`, Linux binary + AppImage, macOS `.app` (Intel + M-series) |

## Features

- **Till** — barcode scan (camera + hardware), cart, qty deals, variants/packs picker, retail/wholesale price lists
- **Payments** — cash, M-Pesa, card, **split payments**, **credit sales**, change tracking
- **Customers** — walk-in + named customers, created at checkout
- **Pricing** — invoice-level discounts, **promo codes** with min-spend, wholesale prices per product
- **Stock** — movements ledger, suppliers, low-stock alerts, **batch/expiry tracking**, stock counts
- **Shifts** — opening float → closing count with expected-vs-counted reconciliation
- **Sync** — event-based hub↔device↔cloud replication with outbox, dedupe, conflict handling
- **Staff** — admin/cashier roles, per-device till user, role toggling, audit log
- **Reports** — daily sales, top sellers, VAT breakdown, printable receipts & Z-reports

## Run it

### Hub (desktop POS)

```bash
python3 -m venv .venv && .venv/bin/pip install flask waitress qrcode[pil]
.venv/bin/python app.py          # → http://127.0.0.1:5050
```

Logins (change in Users): `admin`/`admin123`, `cashier`/`cashier123`

### Mobile app

```bash
cd mobile && npm install && npx expo start --lan
```

Open in Expo Go (`exp://<your-ip>:8081`), pair via QR from the hub's Devices tab.

### Web app (SaaS)

```bash
cd web && python3 -m http.server 8080   # → http://localhost:8080
```

Sign up → verify email → create your store. Supabase handles auth + multi-tenant data.

### Cloud bridge

```bash
set -a && source .env && set +a && .venv/bin/python cloud_api.py   # → :5060
```

## Installers (CI-built)

Every push to `master` builds all platforms — **Actions → builds → Artifacts**:

- `mauzo-pos-windows-latest` → `.exe`
- `mauzo-pos-ubuntu-latest` → binary **and** AppImage (all distros)
- `mauzo-pos-macos-latest` → `.app` (Apple Silicon) · `mauzo-pos-macos-13` → `.app` (Intel)
- `mauzo-pos-android` → sideloadable APK

Local build: `pip install pyinstaller && pyinstaller mauzo.spec`

## Repo layout

```
app.py              hub — Flask + SQLite, migrations via mig()
cloud_api.py        Supabase bridge — sync ingest + onboarding/branches APIs
templates/          hub UI (vanilla JS SPA)
mobile/             Expo app — local SQLite mirror, sync engine
web/                static SaaS app — Supabase auth + PostgREST/RLS
desktop.py          packaged-app launcher (pywebview → browser fallback)
mauzo.spec          PyInstaller spec
supabase/migrations cloud schema — tenants, products, sales, events, RLS
CHANGES.md          ERPNext feature-gap roadmap (implemented items ticked)
```

## Multi-tenancy

Cloud schema is tenant-scoped: `businesses → branches → devices/sales/products`. RLS policies restrict every table to members; the hub carries `business_id`/`branch_id` on all records so local and cloud data line up.

## Security notes

- The service-role key lives only in `.env` (gitignored) — never in the web app; the web app uses the **anon** key + RLS
- Device APIs are authenticated via `X-Device-Key` issued at pairing; hub sessions are staff logins
- Change the seeded passwords before going live
