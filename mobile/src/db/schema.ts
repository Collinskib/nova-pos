// Versioned forward-only migrations (BUILD.md §5.1) — integer cents for money (§4.4).
export const MIGRATIONS: string[] = [
// v1 — core catalog + tenancy mirrors
`CREATE TABLE businesses(id TEXT PRIMARY KEY, name TEXT, status TEXT);
CREATE TABLE branches(id TEXT PRIMARY KEY, business_id TEXT, name TEXT, address TEXT);
CREATE TABLE devices(id TEXT PRIMARY KEY, uuid TEXT, business_id TEXT, branch_id TEXT, device_name TEXT, device_type TEXT, active INTEGER DEFAULT 1);
CREATE TABLE products(id TEXT PRIMARY KEY, business_id TEXT, barcode TEXT, name TEXT, price_cents INTEGER, cost_cents INTEGER, stock REAL DEFAULT 0, taxable INTEGER DEFAULT 1, discount_qty REAL, discount_pct REAL, image TEXT, updated_at TEXT);
CREATE TABLE categories(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE product_categories(product_id TEXT, category_id INTEGER);
CREATE INDEX idx_products_name ON products(name);
CREATE INDEX idx_products_barcode ON products(barcode);`,
// v2 — sales + ledger
`CREATE TABLE sales(id TEXT PRIMARY KEY, receipt_no TEXT UNIQUE, business_id TEXT, branch_id TEXT, device_id TEXT, user_id TEXT, subtotal_cents INTEGER, discount_cents INTEGER, tax_cents INTEGER, total_cents INTEGER, status TEXT DEFAULT 'completed', created_at TEXT, server_seq INTEGER);
CREATE TABLE sale_items(id TEXT PRIMARY KEY, sale_id TEXT REFERENCES sales(id), product_id TEXT, name TEXT, qty REAL, unit_price_cents INTEGER, total_cents INTEGER);
CREATE TABLE payments(id TEXT PRIMARY KEY, sale_id TEXT REFERENCES sales(id), method TEXT, amount_cents INTEGER, created_at TEXT);
CREATE TABLE stock_movements(id TEXT PRIMARY KEY, business_id TEXT, branch_id TEXT, product_id TEXT, movement_type TEXT, quantity_delta REAL, reference_id TEXT, note TEXT, created_at TEXT);
CREATE TABLE stock_balances(business_id TEXT, branch_id TEXT, product_id TEXT, on_hand REAL, PRIMARY KEY(business_id, branch_id, product_id));
CREATE INDEX idx_movements_product ON stock_movements(branch_id, product_id);`,
// v3 — transfers + returns + purchases + expenses
`CREATE TABLE transfers(id TEXT PRIMARY KEY, business_id TEXT, from_branch_id TEXT, to_branch_id TEXT, status TEXT, note TEXT, created_at TEXT, dispatched_at TEXT, received_at TEXT);
CREATE TABLE transfer_items(id TEXT PRIMARY KEY, transfer_id TEXT REFERENCES transfers(id), product_id TEXT, qty_sent REAL, qty_received REAL DEFAULT 0, qty_damaged REAL DEFAULT 0);
CREATE TABLE returns(id TEXT PRIMARY KEY, sale_id TEXT, reason TEXT, total_cents INTEGER, status TEXT DEFAULT 'posted', created_at TEXT);
CREATE TABLE return_items(id TEXT PRIMARY KEY, return_id TEXT, product_id TEXT, qty REAL, total_cents INTEGER);
CREATE TABLE purchases(id TEXT PRIMARY KEY, supplier_id TEXT, total_cents INTEGER, status TEXT, note TEXT, created_at TEXT);
CREATE TABLE purchase_items(id TEXT PRIMARY KEY, purchase_id TEXT, product_id TEXT, qty REAL, cost_cents INTEGER);
CREATE TABLE expenses(id TEXT PRIMARY KEY, category TEXT, amount_cents INTEGER, note TEXT, created_at TEXT);`,
// v4 — sync primitives (§8.4)
`CREATE TABLE sync_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE, business_id TEXT, branch_id TEXT, device_id TEXT, device_sequence INTEGER, event_type TEXT, schema_version INTEGER DEFAULT 1, entity_id TEXT, device_created_at TEXT, payload TEXT, hub_acked INTEGER DEFAULT 0, cloud_acked INTEGER DEFAULT 0, retries INTEGER DEFAULT 0, last_error TEXT);
CREATE TABLE sync_inbox(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE, server_sequence INTEGER, event_type TEXT, entity_id TEXT, payload TEXT, applied INTEGER DEFAULT 0, received_at TEXT);
CREATE TABLE sync_cursors(destination TEXT PRIMARY KEY, last_sequence INTEGER DEFAULT 0, updated_at TEXT);
CREATE TABLE sync_receipts(event_id TEXT, destination TEXT, acked_at TEXT, status TEXT, PRIMARY KEY(event_id, destination));
CREATE TABLE sync_conflicts(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT, reason TEXT, detail TEXT, resolved INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE device_state(k TEXT PRIMARY KEY, v TEXT);`,
`ALTER TABLE sales ADD COLUMN cashier_name TEXT;`,
];
