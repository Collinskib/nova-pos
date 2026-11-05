# Nova POS — Client Onboarding Guide

How to set up a new store for a client. Each client gets their own copy of the
app and their own database (single-store per deployment).

## 1. Deploy a fresh instance

```bash
cp -r pos-system pos-clientname
cd pos-clientname
rm pos.db .secret_key          # fresh database + fresh session key
~/.local/bin/uv run --with flask app.py
```

The app runs at http://127.0.0.1:5050.
To run multiple clients on one machine, change the port in `app.py`
(`app.run(..., port=5050)`) per instance — e.g. 5050, 5051, 5052.

## 2. Onboard the store (~10 minutes)

1. **Log in** as `admin / admin123`
2. **Change the admin password immediately** — Users → Password
3. **Rename the shop** — click the store name under the Nova POS logo in the
   sidebar, or Settings → Store name
4. **Settings** → address, phone, currency symbol, VAT rate (16% default for
   Kenya — set to 0 to disable)
5. **Create users** — Users → + New user
   - `admin` role: full access (products, stock, voids, settings, users)
   - `cashier` role: till only (POS, orders, own password)
6. **Load products** — Products → 📄 Import CSV
   - Export the client's price list from Excel as CSV
   - Columns: `barcode,name,price` (+ optional `category,brand,cost,stock,
     taxable,discount_qty,discount_pct,expiry,image`)
   - Existing barcodes update in place; new categories/brands auto-create
   - `taxable`: `0`/`no`/`exempt` for VAT-exempt items
   - Or add products one by one — each has an image picker (upload file or
     find online)
7. **Stock** — Inventory → + Stock entry per supplier delivery
8. **Done** — dashboard, reports, held sales, expiry alerts all live

## 3. Features to demo to the client

- Till: barcode/name search, product grid, cart with qty steppers
- Cash settlement with change calculation + printable receipt (16% VAT split)
- Bulk deals: "Buy 6+, save 5%" per product, auto-applied
- Park/Held sales for interruptions
- VAT-exempt products (uncheck VAT in the product form)
- Expiry tracking — dashboard "Expiring soon" card
- Stock valuation, low-stock alerts, top sellers, daily reports
- Admin-only voids (restores stock), user management, theme toggle
- Forgot password → admin approves in Users → Reset requests

## 4. Hosting options

- **Client's own laptop/PC** — run the command above; add to startup apps
- **Small VPS** — change `host="127.0.0.1"` to `"0.0.0.0"` in `app.py` and put
  nginx + HTTPS in front (never expose plain HTTP with real data)

Note: one install = one store. Multi-tenant (one install, many shops) would
need `store_id` on every table — possible later if a client wants a chain.

## 5. Demo accounts (fresh install only — delete or re-pw before handover)

- `admin / admin123`
- `cashier / cashier123`
