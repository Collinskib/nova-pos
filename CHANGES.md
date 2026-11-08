# Nova POS — ERPNext-inspired feature backlog

Gaps found comparing against the ERPNext POS module (`erpnext/selling/page/point_of_sale` + POS Invoice). Ordered by priority for this project (Kenya, single-branch, multi-till, offline-capable).

## 1. Shifts & cash control
- [ ] **POS Opening entry** — cashier declares opening float when starting a shift on a till
- [ ] **POS Closing entry** — end-of-shift cash count, system diffs expected vs actual per till/day
- [ ] **Cash in/out movements** — petty cash in and out of the drawer mid-shift

## 2. Payments
- [ ] **Split payments** — part cash / part other on one sale (schema already has `payments` rows)
- [ ] **M-Pesa / mobile-money payment method** — labeled method first; STK push integration later
- [ ] **Credit sales** — invoice now, pay later, with outstanding-balance tracking (needs §3)

## 3. Customers
- [ ] **Customer records** — walk-in default + named customers, contact info
- [ ] **Sale → customer link** — history per customer (needed for credit + loyalty)

## 4. Pricing
- [ ] **Price lists** — e.g. retail vs wholesale, per customer or branch
- [ ] **Invoice-level discounts** — ad-hoc %-off or fixed-amount off the whole bill (we only have per-product bulk-deal rules)
- [ ] **Promotions / coupons** — buy-X-get-Y, promo codes

## 5. Items & stock
- [ ] **Item variants** — size/color matrices sharing one base product
- [ ] **Alternate UOMs** — sell by piece or by crate/carton with conversion
- [ ] **Serial/batch numbers** — track batches for expiring stock & returns (we have expiry dates only)

## 6. Nice-to-haves
- [ ] Loyalty points program
- [ ] Salesperson commission tracking
- [ ] Quotations → sale conversion
- [ ] Per-user POS permission granularity
- [ ] Rounding rules on totals
- [ ] M-Pesa STK push (real integration)

## Working order
1. Shift open/close + cash reconciliation
2. Split payments + M-Pesa method
3. Customers → credit sales
