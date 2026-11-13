# Feature Inventory — 2026-11-13

Status: **V** verified (evidence: test or exercised path) · **I** implemented-not-verified · **P** partial · **B** broken · **M** missing.

| Feature | Hub | Mobile | Web | Cloud | Status | Notes |
|---|---|---|---|---|---|---|
| Login/logout + roles | ✅ | ✅ (staff picker, no pw on device) | ✅ Supabase auth | — | V (tests) | device till user = identity only |
| Password reset (admin-approved) | ✅ | — | ✅ email reset | — | I | |
| Product CRUD + CSV/XLSX import + images | ✅ | read-only | ✅ create/edit | ✅ | V | dry-run import verified |
| Barcode scan | ✅ html5-qrcode | ✅ expo-camera | — | — | I | |
| Cart + qty + line bulk deals | ✅ | ✅ | ✅ | — | V (tests) | |
| Variant/pack (UOM) sales | ✅ picker | ✅ | ❌ | — | P | cloud ignores pack semantics |
| Checkout: cash + change | ✅ | ✅ | ✅ | — | V | |
| Split payments | ✅ single method field+UI | ✅ payments[] | ✅ payments[] | ✅ | P | hub `/api/checkout` writes ONE payment row only (split not exposed server-side) |
| M-Pesa/card labels | ✅ | ✅ | ✅ | ✅ | V | no STK integration |
| Credit sales | ✅ method flag | ✅ | ❌ | — | P | balance tracking not implemented anywhere |
| Invoice discount | ✅ | ✅ | ✅ | ✅ | V | |
| Promo codes | B→✅ fixed | ✅ client-validated | ❌ | — | V | hub now applies server-side |
| Held/parked sales | ✅ | ❌ | ❌ | — | I | |
| Receipt view/print | ✅ | ✅ sheet | ✅ | — | I | |
| Void sale + restock | ✅ admin | ❌ | ✅ admin | ✅ | V (tests) | |
| Returns | ✅ | ❌ | ❌ | ✅ movement | V (tests) | hub endpoint is session-auth, not device |
| Stock entries/adjustments | ✅ | ❌ | ✅ | ✅ | V | |
| Batch/expiry tracking | ✅ | ❌ | ❌ | ❌ | P | batches never decrement on sale |
| Suppliers | ✅ | ❌ | ❌ | ❌ | I | |
| Purchases/receiving | ✅ | ❌ | ❌ | ✅ event | I | |
| Expenses | ✅ | ❌ | ❌ | ❌ event stored | P | cloud doesn't project EXPENSE_POSTED |
| Low-stock + expiry alerts | ✅ | ❌ | ❌ | — | I | |
| Shifts open/close + reconciliation | ✅ history | ✅ | ❌ | ❌ | V→fixed | expected-cash bug fixed |
| Customers + credit link | ✅ list+create | ✅ | partial (name only) | ✅ | P | no balances/ledger |
| Price lists (retail/wholesale) | ✅ toggle | ✅ | ❌ | ❌ | P | wholesale not in cloud schema |
| Daily/top/VAT reports | ✅ | ✅ | ✅ | ✅ | I | |
| Devices pair/revoke/QR | ✅ | ✅ | ❌ | auto "Web till" | V (tests) | |
| Audit log | ✅ | — | — | table exists | I | cloud audit_logs unused |
| Backup download | ✅ | — | — | Supabase PITR | I | |
| Hub→cloud sync | ✅ manual+auto | — | — | ✅ | I | needs live verify |
| Cloud→hub pull | ✅ | — | — | ✅ | V→fixed | seq-collision fixed |
| Stock transfers | ❌ no tables | ✅ full lifecycle | ❌ | ✅ projected | P | hub can't see transfers |
| Multi-branch | single-branch rows | branch-tagged | ✅ picker+switch | ✅ | P | hub hardcodes branch 1 |
| Offline sales queue | n/a | ✅ outbox | ✅ localStorage | — | V (mobile), I (web) | |
| Conflict detection | table only | — | — | table only | M | no writers anywhere |
| Subscriptions/billing | tables only | — | — | table | M | |
| Loyalty | ❌ | ❌ | ❌ | ❌ | M | CHANGES.md nice-to-have |
| Cash in/out mid-shift | ❌ | ❌ | ❌ | ❌ | M | CHANGES.md §1 |
| Quotations | ❌ | ❌ | ❌ | ❌ | M | |
| Stock counts (stocktake) | adjustments only | ❌ | ❌ | ❌ | P | no count session flow |
| User permissions granularity | role only | — | role only | role only | P | |
| Web till | — | — | ✅ | ✅ | V→fixed | now emits events |
