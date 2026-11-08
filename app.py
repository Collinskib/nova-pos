#!/usr/bin/env python3
"""POS & Inventory Management System — Flask + SQLite."""
import sqlite3, hashlib, secrets, json, os, uuid, urllib.request, socket
from datetime import datetime, date, timezone, timedelta
from functools import wraps
from flask import Flask, request, jsonify, session, render_template, redirect

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "pos.db")
app = Flask(__name__)
KEY_FILE = os.path.join(BASE, ".secret_key")
if os.path.exists(KEY_FILE):
    app.secret_key = open(KEY_FILE).read().strip()
else:
    app.secret_key = secrets.token_hex(16)
    open(KEY_FILE, "w").write(app.secret_key)  # persist so restarts don't kill sessions

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw TEXT, name TEXT, role TEXT DEFAULT 'cashier');
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS brands(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY, name TEXT UNIQUE, contact TEXT, phone TEXT, address TEXT);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, barcode TEXT UNIQUE, name TEXT, category_id INT, brand_id INT, price REAL, stock REAL DEFAULT 0, cost REAL DEFAULT 0, image TEXT, taxable INTEGER DEFAULT 1, discount_qty REAL DEFAULT 0, discount_pct REAL DEFAULT 0, expiry TEXT);
CREATE TABLE IF NOT EXISTS stock_entries(id INTEGER PRIMARY KEY, ref_no TEXT, product_id INT, qty REAL, kind TEXT, note TEXT, supplier_id INT, created TEXT);
CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY, invoice_no TEXT UNIQUE, total REAL, cash REAL, change_due REAL, vat REAL DEFAULT 0, discount REAL DEFAULT 0, user_id INT, status TEXT DEFAULT 'completed', created TEXT);
CREATE TABLE IF NOT EXISTS sale_items(id INTEGER PRIMARY KEY, sale_id INT, product_id INT, name TEXT, price REAL, qty REAL, total REAL);
CREATE TABLE IF NOT EXISTS held_sales(id INTEGER PRIMARY KEY, label TEXT, items TEXT, user_id INT, created TEXT);
CREATE TABLE IF NOT EXISTS reset_requests(id INTEGER PRIMARY KEY, username TEXT, user_id INT, status TEXT DEFAULT 'pending', created TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
"""

# ---------------------------------------------------------------------------
# BUILD.md implementation — forward-only migrations (spec §5.1 schema_versions)
# ---------------------------------------------------------------------------
MIGRATIONS = []
def mig(n, sql):
    MIGRATIONS.append((n, sql)); return sql

# 0001 — tenancy, devices, sync primitives, ledgers, audit (spec §5, §8, §10)
mig(1, """
CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS businesses(id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, name TEXT, status TEXT DEFAULT 'active', created_at TEXT);
CREATE TABLE IF NOT EXISTS branches(id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, business_id INT REFERENCES businesses(id), name TEXT, address TEXT, status TEXT DEFAULT 'active', created_at TEXT);
CREATE TABLE IF NOT EXISTS devices(id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, business_id INT, branch_id INT,
    device_name TEXT, device_type TEXT DEFAULT 'desktop', api_key_hash TEXT, active INTEGER DEFAULT 1,
    last_seen_at TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS pairing_tokens(token TEXT PRIMARY KEY, business_id INT, branch_id INT,
    created_by INT, expires_at TEXT, redeemed_by INT, redeemed_at TEXT);
CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY, at TEXT, actor TEXT, action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS sync_events(id INTEGER PRIMARY KEY, event_id TEXT UNIQUE, business_id INT, branch_id INT,
    device_id INT, device_sequence INT, event_type TEXT, schema_version INT DEFAULT 1, entity_id TEXT,
    device_created_at TEXT, payload TEXT, server_received_at TEXT, server_sequence INT);
CREATE TABLE IF NOT EXISTS sync_streams(branch_id INTEGER PRIMARY KEY, next_sequence INT DEFAULT 1);
CREATE TABLE IF NOT EXISTS sync_outbox(id INTEGER PRIMARY KEY, event_id TEXT UNIQUE, event_type TEXT,
    entity_id TEXT, payload TEXT, created_at TEXT, hub_acked INTEGER DEFAULT 0, cloud_acked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sync_cursors(device_id INTEGER PRIMARY KEY, last_sequence INT DEFAULT 0, updated_at TEXT);
CREATE TABLE IF NOT EXISTS sync_receipts(id INTEGER PRIMARY KEY, event_id TEXT, device_id INT, acked_at TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS sync_conflicts(id INTEGER PRIMARY KEY, event_id TEXT, device_id INT, reason TEXT, detail TEXT, resolved INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, sale_id INT, method TEXT DEFAULT 'cash', amount REAL, created TEXT);
CREATE TABLE IF NOT EXISTS receipt_counters(branch_id INTEGER PRIMARY KEY, next_no INT DEFAULT 1);
CREATE TABLE IF NOT EXISTS stock_movements(id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, business_id INT, branch_id INT,
    product_id INT, movement_type TEXT, quantity_delta REAL, reference_id TEXT, device_id INT, note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS returns(id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, sale_id INT, reason TEXT, total REAL,
    status TEXT DEFAULT 'posted', user_id INT, created_at TEXT);
CREATE TABLE IF NOT EXISTS return_items(id INTEGER PRIMARY KEY, return_id INT, product_id INT, name TEXT, qty REAL, total REAL);
CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, supplier_id INT, total REAL, note TEXT,
    status TEXT DEFAULT 'received', user_id INT, created_at TEXT);
CREATE TABLE IF NOT EXISTS purchase_items(id INTEGER PRIMARY KEY, purchase_id INT, product_id INT, qty REAL, cost REAL);
CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, category TEXT, amount REAL, note TEXT,
    user_id INT, created_at TEXT);
CREATE TABLE IF NOT EXISTS expense_categories(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY, business_id INT, plan TEXT, status TEXT DEFAULT 'trialing',
    seats INT, created_at TEXT, current_period_end TEXT);
CREATE TABLE IF NOT EXISTS subscription_events(id INTEGER PRIMARY KEY, subscription_id INT, event TEXT, detail TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_events_branch_seq ON sync_events(branch_id, server_sequence);
CREATE INDEX IF NOT EXISTS idx_movements_product ON stock_movements(business_id, branch_id, product_id);
""")
# 0002 — tenant + uuid columns on legacy tables (backfilled to default business/branch 1)
mig(2, """
ALTER TABLE sales ADD COLUMN sale_uuid TEXT;
ALTER TABLE sales ADD COLUMN business_id INT DEFAULT 1;
ALTER TABLE sales ADD COLUMN branch_id INT DEFAULT 1;
ALTER TABLE sales ADD COLUMN device_id INT;
ALTER TABLE products ADD COLUMN business_id INT DEFAULT 1;
ALTER TABLE stock_entries ADD COLUMN branch_id INT DEFAULT 1;
ALTER TABLE stock_entries ADD COLUMN movement_id INT;
UPDATE sales SET sale_uuid=lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-'||lower(hex(randomblob(2)))||'-'||lower(hex(randomblob(2)))||'-'||lower(hex(randomblob(6))) WHERE sale_uuid IS NULL;
INSERT OR IGNORE INTO receipt_counters(branch_id,next_no) VALUES(1,1);
""")
# 0003 — accountability: cashier identity on device-initiated sales
mig(3, """
ALTER TABLE sales ADD COLUMN cashier_name TEXT;
""")

DEFAULT_BUSINESS, DEFAULT_BRANCH = 1, 1

def apply_migrations(c):
    c.execute("CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    have = {r[0] for r in c.execute("SELECT version FROM schema_versions")}
    for n, sql in MIGRATIONS:
        if n in have: continue
        try:
            c.executescript(sql)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e): raise
        if n == 1 and not c.execute("SELECT 1 FROM businesses WHERE id=1").fetchone():
            c.execute("INSERT INTO businesses(id,uuid,name,created_at) VALUES(?,?,?,?)",
                      (1, str(uuid.uuid4()), "Nova Mart", datetime.now(timezone.utc).isoformat(timespec="seconds")))
            c.execute("INSERT INTO branches(id,uuid,business_id,name,address,created_at) VALUES(?,?,?,?,?,?)",
                      (1, str(uuid.uuid4()), 1, "Main Branch", "Moi Avenue, Nairobi", datetime.now(timezone.utc).isoformat(timespec="seconds")))
            c.execute("INSERT INTO sync_streams(branch_id,next_sequence) VALUES(1,1)")
        c.execute("INSERT INTO schema_versions(version,applied_at) VALUES(?,?)", (n, datetime.now(timezone.utc).isoformat(timespec="seconds")))
SEED_SETTINGS = {"store_name": "Nova Mart", "store_address": "Moi Avenue, Nairobi, Kenya", "store_phone": "+254 712 345 678", "tax_rate": "16", "currency": "KSh "}

def init_db():
    c = db()
    c.executescript(SCHEMA)
    for col, defn in [("discount_qty","REAL DEFAULT 0"),("discount_pct","REAL DEFAULT 0"),("expiry","TEXT")]:
        try: c.execute(f"ALTER TABLE products ADD COLUMN {col} {defn}")
        except sqlite3.OperationalError: pass
    try: c.execute("ALTER TABLE sales ADD COLUMN discount REAL DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: c.execute("ALTER TABLE users ADD COLUMN must_change INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    if not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        h = lambda p: hashlib.sha256(p.encode()).hexdigest()
        c.execute("INSERT INTO users(username,pw,name,role) VALUES(?,?,?,?)", ("admin", h("admin123"), "Store Admin", "admin"))
        c.execute("INSERT INTO users(username,pw,name,role) VALUES(?,?,?,?)", ("cashier", h("cashier123"), "Jane Cashier", "cashier"))
        cats, brands, sups = ["Beverages","Snacks","Dairy","Household","Personal Care"], ["Coca-Cola","Nestlé","Local Farm","Generic"], [("Metro Wholesale","Sam Diaz","555-0100","4 Depot Rd"),("FarmDirect","Ana Ruiz","555-0142","88 Field Ln")]
        for n in cats: c.execute("INSERT INTO categories(name) VALUES(?)", (n,))
        for n in brands: c.execute("INSERT INTO brands(name) VALUES(?)", (n,))
        for s in sups: c.execute("INSERT INTO suppliers(name,contact,phone,address) VALUES(?,?,?,?)", s)
        prods = [
            ("8901001","Cola 330ml",1,1,1.50,48,0.9),("8901002","Orange Juice 1L",1,2,3.20,30,2.1),
            ("8901003","Potato Chips 150g",2,4,1.80,64,1.0),("8901004","Chocolate Bar",2,2,2.10,45,1.3),
            ("8901005","Whole Milk 1L",3,3,2.40,25,1.7),("8901006","Greek Yogurt 500g",3,3,4.10,8,2.9),
            ("8901007","Dish Soap 750ml",4,4,3.60,15,2.2),("8901008","Paper Towels 6pk",4,4,5.90,6,3.8),
            ("8901009","Hand Sanitizer 250ml",5,4,2.90,40,1.6),("8901010","Shampoo 400ml",5,2,6.50,4,4.4)]
        for p in prods: c.execute("INSERT INTO products(barcode,name,category_id,brand_id,price,stock,cost) VALUES(?,?,?,?,?,?,?)", p)
        for k, v in SEED_SETTINGS.items(): c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, v))
    apply_migrations(c)
    c.commit(); c.close()

def need_login(f):
    @wraps(f)
    def w(*a, **k):
        if "uid" not in session: return jsonify({"error": "auth"}), 401
        return f(*a, **k)
    return w

def need_admin(f):
    @wraps(f)
    def w(*a, **k):
        if "uid" not in session: return jsonify({"error": "auth"}), 401
        if session.get("role") != "admin": return jsonify({"error": "admin only"}), 403
        return f(*a, **k)
    return w

def rows(c, q, p=()): return [dict(r) for r in c.execute(q, p).fetchall()]

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def audit(c, action, detail="", actor=None):
    actor = actor if actor is not None else session.get("name") or session.get("uid") or "system"
    c.execute("INSERT INTO audit_logs(at,actor,action,detail) VALUES(?,?,?,?)", (utcnow(), actor, action, detail))

def emit_event(c, event_type, entity_id, payload, device_id=None):
    """Durable event: accepted into sync_events (stream-ordered) + mirrored in
    sync_outbox for onward delivery (§8.1 envelope, §8.3 counter, §8.4 outbox)."""
    eid = str(uuid.uuid4())
    now = utcnow()
    seq = c.execute("UPDATE sync_streams SET next_sequence=next_sequence+1 WHERE branch_id=? RETURNING next_sequence-1",
                    (DEFAULT_BRANCH,)).fetchone()
    if not seq:
        c.execute("INSERT INTO sync_streams(branch_id,next_sequence) VALUES(?,2)", (DEFAULT_BRANCH,))
        seq = (1,)
    seq = seq[0]
    c.execute("""INSERT INTO sync_events(event_id,business_id,branch_id,device_id,device_sequence,event_type,
        schema_version,entity_id,device_created_at,payload,server_received_at,server_sequence)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (eid, DEFAULT_BUSINESS, DEFAULT_BRANCH, device_id, seq, event_type, 1, entity_id, now,
         json.dumps(payload), now, seq))
    c.execute("INSERT OR IGNORE INTO sync_outbox(event_id,event_type,entity_id,payload,created_at) VALUES(?,?,?,?,?)",
              (eid, event_type, entity_id, json.dumps(payload), now))
    return eid

def record_movement(c, product_id, delta, movement_type, reference_id=None, note="", device_id=None):
    mid = str(uuid.uuid4())
    c.execute("""INSERT INTO stock_movements(uuid,business_id,branch_id,product_id,movement_type,quantity_delta,
        reference_id,device_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (mid, DEFAULT_BUSINESS, DEFAULT_BRANCH, product_id, movement_type, delta, reference_id, device_id, note, utcnow()))
    return mid

def next_receipt(c):
    """Branch-scoped sequential receipt number (§7.3) — never timestamp-derived."""
    r = c.execute("UPDATE receipt_counters SET next_no=next_no+1 WHERE branch_id=? RETURNING next_no-1", (DEFAULT_BRANCH,)).fetchone()
    if not r:
        c.execute("INSERT INTO receipt_counters(branch_id,next_no) VALUES(?,2)", (DEFAULT_BRANCH,)); r = (1,)
    return f"INV-{r[0]:06d}"

def device_identity():
    """Resolve a registered, active device from its X-Device-Key credential (§10.2)."""
    key = request.headers.get("X-Device-Key", "")
    if not key: return None
    c = db()
    d = c.execute("SELECT * FROM devices WHERE api_key_hash=? AND active=1", (hashlib.sha256(key.encode()).hexdigest(),)).fetchone()
    if d:
        c.execute("UPDATE devices SET last_seen_at=? WHERE id=?", (utcnow(), d["id"])); c.commit()
        return dict(d)
    return None

def need_device(f):
    @wraps(f)
    def w(*a, **k):
        d = device_identity()
        if not d: return jsonify({"error": "unregistered_or_revoked_device"}), 401
        request.device = d
        return f(*a, **k)
    return w

@app.get("/")
def index():
    return render_template("login.html") if "uid" not in session else render_template("index.html")

if os.environ.get("POS_DEV_SHOTS"):  # screenshot helper — only active when env var is set
    @app.get("/devlogin/<page>")
    def devlogin(page):
        u = db().execute("SELECT * FROM users WHERE username='admin'").fetchone()
        session.update(uid=u["id"], name=u["name"], role=u["role"])
        return redirect("/#" + page)

@app.post("/api/login")
def login():
    d = request.json; h = hashlib.sha256(d["password"].encode()).hexdigest()
    c = db()
    u = c.execute("SELECT * FROM users WHERE username=? AND pw=?", (d["username"], h)).fetchone()
    if not u:
        audit(c, "auth.login_failed", d["username"], actor=d["username"]); c.commit(); c.close()
        return jsonify({"error": "Invalid username or password"}), 401
    session.update(uid=u["id"], name=u["name"], role=u["role"])
    audit(c, "auth.login", u["username"], actor=u["name"]); c.commit(); c.close()
    return jsonify({"ok": True, "name": u["name"], "role": u["role"], "must_change": bool(u["must_change"]) if "must_change" in u.keys() else False})

@app.post("/api/forgot")
def forgot():
    u = db().execute("SELECT id FROM users WHERE username=?", (request.json.get("username", "").strip(),)).fetchone()
    if u:
        c = db()
        c.execute("INSERT INTO reset_requests(username,user_id,created) VALUES(?,?,?)",
                  (request.json["username"].strip(), u["id"], datetime.now().isoformat(timespec="seconds")))
        c.commit()
    return jsonify({"ok": True})  # same response whether or not the user exists

@app.get("/api/resets")
@need_admin
def resets():
    return jsonify(rows(db(), """SELECT r.*, u.name, u.username uname FROM reset_requests r
        LEFT JOIN users u ON u.id=r.user_id WHERE r.status='pending' ORDER BY r.id DESC"""))

@app.post("/api/resets/<int:rid>/approve")
@need_admin
def reset_approve(rid):
    c = db()
    r = c.execute("SELECT * FROM reset_requests WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not r: return jsonify({"error": "not found"}), 404
    temp = "Nova-" + secrets.token_hex(3)
    c.execute("UPDATE users SET pw=?, must_change=1 WHERE id=?",
              (hashlib.sha256(temp.encode()).hexdigest(), r["user_id"]))
    c.execute("UPDATE reset_requests SET status='done' WHERE id=?", (rid,))
    audit(c, "user.password_reset", r["username"])
    c.commit(); return jsonify({"ok": True, "temp": temp})

@app.post("/api/resets/<int:rid>/dismiss")
@need_admin
def reset_dismiss(rid):
    c = db(); c.execute("UPDATE reset_requests SET status='dismissed' WHERE id=?", (rid,))
    c.commit(); return jsonify({"ok": True})

@app.post("/api/logout")
def logout(): session.clear(); return jsonify({"ok": True})

@app.get("/api/bootstrap")
@need_login
def bootstrap():
    c = db()
    return jsonify({
        "user": {"id": session["uid"], "name": session["name"], "role": session["role"],
                 "must_change": bool(c.execute("SELECT must_change FROM users WHERE id=?", (session["uid"],)).fetchone()["must_change"])},
        "settings": {r["k"]: r["v"] for r in c.execute("SELECT * FROM settings")},
        "categories": rows(c, "SELECT * FROM categories ORDER BY name"),
        "brands": rows(c, "SELECT * FROM brands ORDER BY name"),
        "suppliers": rows(c, "SELECT * FROM suppliers ORDER BY name"),
    })

# ---------- POS ----------
@app.get("/api/products")
@need_login
def products():
    q = f"%{request.args.get('q','')}%"
    c = db()
    return jsonify(rows(c, """SELECT p.*, c.name category, b.name brand FROM products p
        LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN brands b ON b.id=p.brand_id
        WHERE p.name LIKE ? OR p.barcode LIKE ? ORDER BY p.name""", (q, q)))

@app.post("/api/products")
@need_admin
def product_add():
    d = request.json; c = db()
    try:
        c.execute("INSERT INTO products(barcode,name,category_id,brand_id,price,stock,cost,taxable,discount_qty,discount_pct,expiry,image) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (d["barcode"], d["name"], d.get("category_id"), d.get("brand_id"), d["price"], d.get("stock",0), d.get("cost",0), d.get("taxable",1), d.get("discount_qty",0), d.get("discount_pct",0), d.get("expiry") or None, d.get("image") or None))
    except sqlite3.IntegrityError: return jsonify({"error": "Barcode already exists"}), 400
    pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    emit_event(c, "PRODUCT_CREATED", str(pid), {"product_id": pid, "product_uuid": str(uuid.uuid5(uuid.NAMESPACE_DNS, str(pid))), **{k: d.get(k) for k in ("barcode","name","price","stock","cost")}})
    audit(c, "product.created", d["name"])
    c.commit(); return jsonify({"ok": True})

@app.put("/api/products/<int:pid>")
@need_admin
def product_edit(pid):
    d = request.json; c = db()
    c.execute("UPDATE products SET barcode=?,name=?,category_id=?,brand_id=?,price=?,stock=?,cost=?,taxable=?,discount_qty=?,discount_pct=?,expiry=?,image=? WHERE id=?",
              (d["barcode"], d["name"], d.get("category_id"), d.get("brand_id"), d["price"], d["stock"], d.get("cost",0), d.get("taxable",1), d.get("discount_qty",0), d.get("discount_pct",0), d.get("expiry") or None, d.get("image") or None, pid))
    emit_event(c, "PRODUCT_UPDATED", str(pid), {"product_id": pid, **{k: d.get(k) for k in ("barcode","name","price","stock","cost")}})
    audit(c, "product.updated", d["name"])
    c.commit(); return jsonify({"ok": True})

@app.delete("/api/products/<int:pid>")
@need_admin
def product_del(pid):
    c = db()
    p = c.execute("SELECT name FROM products WHERE id=?", (pid,)).fetchone()
    c.execute("DELETE FROM products WHERE id=?", (pid,))
    emit_event(c, "PRODUCT_DELETED", str(pid), {"product_id": pid, "name": p["name"] if p else None})
    audit(c, "product.deleted", p["name"] if p else str(pid))
    c.commit(); return jsonify({"ok": True})

@app.post("/api/products/import")
@need_admin
def products_import():
    import csv, io, base64
    body = request.json or {}
    rows_in = body.get("rows")
    if body.get("xlsx_b64"):  # Excel file → rows via openpyxl (optional dep)
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(base64.b64decode(body["xlsx_b64"])), read_only=True)
            ws = wb.active; it = ws.iter_rows(values_only=True)
            hdr = [str(h or "").strip().lower() for h in next(it)]
            rows_in = [{hdr[i]: (str(v) if v is not None else "") for i, v in enumerate(r) if i < len(hdr)} for r in it]
        except ImportError:
            return jsonify({"error": "xlsx import needs openpyxl — save as CSV instead"}), 400
        except Exception as e:
            return jsonify({"error": f"couldn't read xlsx: {e}"}), 400
    if rows_in is None:
        rows_in = [dict(r) for r in csv.DictReader(io.StringIO(body.get("csv", "")))]
    dry = bool(body.get("dry_run"))
    c = db(); created = updated = skipped = 0; errors = []; plan = []
    def lk(table, name):
        name = (name or "").strip()
        if not name: return None
        r = c.execute(f"SELECT id FROM {table} WHERE name=?", (name,)).fetchone()
        if r: return r["id"]
        c.execute(f"INSERT INTO {table}(name) VALUES(?)", (name,))
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]
    for n, raw in enumerate(rows_in, 2):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        try:
            name, price = r.get("name", ""), float(r.get("price") or 0)
            if not name or price <= 0: raise ValueError("needs name & price")
            bc = r.get("barcode") or None
            vals = (bc, name, lk("categories", r.get("category")), lk("brands", r.get("brand")),
                    price, float(r.get("stock") or 0), float(r.get("cost") or 0),
                    0 if r.get("taxable", "1").lower() in ("0", "no", "false", "exempt") else 1,
                    float(r.get("discount_qty") or 0), float(r.get("discount_pct") or 0),
                    r.get("expiry") or None, r.get("image") or None)
            is_upd = bool(bc and c.execute("SELECT 1 FROM products WHERE barcode=?", (bc,)).fetchone())
            if dry:
                plan.append({"row": n, "name": name, "price": price, "barcode": bc or "",
                             "action": "update" if is_upd else "new"})
            elif is_upd:
                c.execute("""UPDATE products SET name=?,category_id=?,brand_id=?,price=?,stock=?,cost=?,taxable=?,discount_qty=?,discount_pct=?,expiry=?,image=COALESCE(?,image) WHERE barcode=?""",
                          (name, vals[2], vals[3], price, vals[5], vals[6], vals[7], vals[8], vals[9], vals[10], vals[11], bc))
                updated += 1
            else:
                c.execute("""INSERT INTO products(barcode,name,category_id,brand_id,price,stock,cost,taxable,discount_qty,discount_pct,expiry,image)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", vals)
                created += 1
        except Exception as e:
            skipped += 1; errors.append(f"row {n}: {e}")
            if dry: plan.append({"row": n, "name": r.get("name") or "—", "price": r.get("price") or "—",
                                 "barcode": r.get("barcode") or "", "action": "error", "msg": str(e)})
    if dry:
        c.rollback()   # lk() may have inserted lookup rows during preview — discard
        return jsonify({"plan": plan[:500], "valid": len(plan) - sum(1 for x in plan if x["action"] == "error"),
                        "errors": len([x for x in plan if x["action"] == "error"])})
    c.commit()
    return jsonify({"created": created, "updated": updated, "skipped": skipped, "errors": errors[:10]})

@app.post("/api/upload")
@need_admin
def upload():
    import base64, re
    m = re.match(r"data:(image/\w+);base64,(.*)", request.json.get("data", ""), re.S)
    if not m: return jsonify({"error": "Not an image file"}), 400
    ext = {"jpeg": "jpg", "png": "png", "gif": "gif", "webp": "webp", "svg+xml": "svg"}.get(m.group(1)[6:], "img")
    os.makedirs(os.path.join(BASE, "static", "uploads"), exist_ok=True)
    fn = f"static/uploads/{secrets.token_hex(8)}.{ext}"
    with open(os.path.join(BASE, fn), "wb") as f:
        f.write(base64.b64decode(m.group(2)))
    return jsonify({"url": "/" + fn})

@app.get("/api/image-search")
@need_login
def image_search():
    import urllib.request, urllib.parse
    q = request.args.get("q", "").strip()
    if not q: return jsonify([])
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {q}",
        "gsrlimit": 6, "gsrnamespace": 6, "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 400, "format": "json"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NovaPOS/1.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=8).read())
    except Exception:
        return jsonify([])
    out = []
    for pg in (data.get("query", {}).get("pages") or {}).values():
        ii = pg.get("imageinfo") or [{}]
        out.append(ii[0].get("thumburl") or ii[0].get("url"))
    return jsonify([u for u in out if u])

@app.get("/api/lookup")
@need_login
def lookup():  # barcode or name search for the till
    q = request.args.get("q", ""); c = db()
    r = c.execute("""SELECT p.*, c.name category, b.name brand FROM products p
        LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN brands b ON b.id=p.brand_id
        WHERE p.barcode=? OR p.name LIKE ? ORDER BY p.name LIMIT 20""", (q, f"%{q}%")).fetchall()
    return jsonify([dict(x) for x in r])

@app.post("/api/checkout")
@need_login
def checkout():
    d = request.json; items = d.get("items", [])
    if not items: return jsonify({"error": "Cart is empty"}), 400
    c = db()
    try:
        c.execute("BEGIN IMMEDIATE")
        rate = float(c.execute("SELECT v FROM settings WHERE k='tax_rate'").fetchone()["v"] or 0)
        vat = total = gross = 0.0
        for i in items:
            p2 = c.execute("SELECT taxable,discount_qty,discount_pct,stock,name FROM products WHERE id=?", (i["id"],)).fetchone()
            if not p2 or p2["stock"] < i["qty"]:
                c.execute("ROLLBACK"); return jsonify({"error": f"Not enough stock: {p2['name'] if p2 else i['id']}"}), 400
            gross += i["price"] * i["qty"]
            line = round(i["price"] * i["qty"] * (1 - (p2["discount_pct"] or 0) / 100 if p2["discount_qty"] and i["qty"] >= p2["discount_qty"] else 1), 2)
            i["line_total"] = line
            total += line
            if p2["taxable"]:
                vat += round(line * rate / (100 + rate), 2)  # VAT-inclusive pricing
        total = round(total, 2)
        cash = round(float(d.get("cash", total)), 2)
        if cash < total:
            c.execute("ROLLBACK"); return jsonify({"error": "Insufficient cash"}), 400
        suid = str(uuid.uuid4())
        inv = next_receipt(c)
        c.execute("""INSERT INTO sales(invoice_no,total,cash,change_due,vat,discount,user_id,status,created,
                     sale_uuid,business_id,branch_id) VALUES(?,?,?,?,?,?,?,'completed',?,?,?,?)""",
                  (inv, total, cash, round(cash - total, 2), round(vat, 2), round(gross - total, 2), session["uid"],
                   datetime.now().isoformat(timespec="seconds"), suid, DEFAULT_BUSINESS, DEFAULT_BRANCH))
        sid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        for i in items:
            c.execute("INSERT INTO sale_items(sale_id,product_id,name,price,qty,total) VALUES(?,?,?,?,?,?)",
                      (sid, i["id"], i["name"], i["price"], i["qty"], i["line_total"]))
            c.execute("UPDATE products SET stock=stock-? WHERE id=?", (i["qty"], i["id"]))
            record_movement(c, i["id"], -i["qty"], "SALE", suid, f"sale {inv}")
        c.execute("INSERT INTO payments(sale_id,method,amount,created) VALUES(?,?,?,?)",
                  (sid, d.get("method", "cash"), cash, datetime.now().isoformat(timespec="seconds")))
        emit_event(c, "SALE_CREATED", suid,
                   {"sale_uuid": suid, "invoice_no": inv, "total": total, "vat": round(vat, 2),
                    "discount": round(gross - total, 2), "cash": cash, "items": [
                        {"product_id": i["id"], "product_uuid": str(uuid.uuid5(uuid.NAMESPACE_DNS, str(i["id"]))),
                         "name": i["name"], "qty": i["qty"], "total": i["line_total"]} for i in items]})
        audit(c, "sale.completed", f"{inv} · {total}")
        c.execute("COMMIT")
    except sqlite3.Error:
        try: c.execute("ROLLBACK")
        except sqlite3.Error: pass
        raise
    finally: c.close()
    return jsonify({"ok": True, "invoice": inv, "total": total, "cash": cash, "change": round(cash - total, 2), "id": sid})

@app.get("/api/receipt/<int:sid>")
@need_login
def receipt(sid):
    c = db()
    s = c.execute("SELECT s.*, u.name cashier FROM sales s LEFT JOIN users u ON u.id=s.user_id WHERE s.id=?", (sid,)).fetchone()
    if not s: return jsonify({"error": "not found"}), 404
    return jsonify({"sale": dict(s), "items": rows(c, "SELECT * FROM sale_items WHERE sale_id=?", (sid,)),
                    "settings": {r["k"]: r["v"] for r in c.execute("SELECT * FROM settings")}})

# ---------- Orders / void ----------
@app.get("/api/sales")
@need_login
def sales_list():
    d = request.args.get("date", date.today().isoformat()); c = db()
    return jsonify(rows(c, """SELECT s.*, u.name cashier, dv.device_name device,
        (SELECT COUNT(*) FROM sale_items si WHERE si.sale_id=s.id) items
        FROM sales s LEFT JOIN users u ON u.id=s.user_id
        LEFT JOIN devices dv ON dv.id=s.device_id WHERE date(s.created)=? ORDER BY s.id DESC""", (d,)))

@app.post("/api/sales/<int:sid>/void")
@need_admin
def sale_void(sid):
    c = db()
    s = c.execute("SELECT * FROM sales WHERE id=? AND status='completed'", (sid,)).fetchone()
    if not s: return jsonify({"error": "Sale not found or already void"}), 400
    c.execute("UPDATE sales SET status='void' WHERE id=?", (sid,))
    for i in c.execute("SELECT product_id,qty FROM sale_items WHERE sale_id=?", (sid,)):
        c.execute("UPDATE products SET stock=stock+? WHERE id=?", (i["qty"], i["product_id"]))
        record_movement(c, i["product_id"], i["qty"], "SALE_RETURN", s["sale_uuid"], f"void {s['invoice_no']}")
    emit_event(c, "SALE_VOIDED", s["sale_uuid"], {"sale_uuid": s["sale_uuid"], "invoice_no": s["invoice_no"],
        "reason": request.json.get("reason", "") if request.is_json else ""})
    audit(c, "sale.voided", s["invoice_no"])
    c.commit(); return jsonify({"ok": True})

# ---------- Held (parked) sales ----------
@app.route("/api/held", methods=["GET", "POST"])
@need_login
def held():
    c = db()
    if request.method == "POST":
        d = request.json
        if not d.get("items"): return jsonify({"error": "Cart is empty"}), 400
        c.execute("INSERT INTO held_sales(label,items,user_id,created) VALUES(?,?,?,?)",
                  (d.get("label") or "Held sale", json.dumps(d["items"]), session["uid"], datetime.now().isoformat(timespec="seconds")))
        c.commit(); return jsonify({"ok": True})
    return jsonify(rows(c, """SELECT h.*, u.name cashier FROM held_sales h
        LEFT JOIN users u ON u.id=h.user_id ORDER BY h.id DESC"""))

@app.route("/api/held/<int:hid>", methods=["GET", "DELETE"])
@need_login
def held_one(hid):
    c = db()
    if request.method == "DELETE":
        c.execute("DELETE FROM held_sales WHERE id=?", (hid,)); c.commit(); return jsonify({"ok": True})
    r = c.execute("SELECT * FROM held_sales WHERE id=?", (hid,)).fetchone()
    if not r: return jsonify({"error": "not found"}), 404
    out = dict(r); out["items"] = json.loads(out["items"])
    return jsonify(out)

# ---------- Inventory ----------
@app.get("/api/stock")
@need_login
def stock_list():
    c = db()
    return jsonify({"entries": rows(c, """SELECT e.*, p.name product, p.barcode, s.name supplier FROM stock_entries e
        LEFT JOIN products p ON p.id=e.product_id LEFT JOIN suppliers s ON s.id=e.supplier_id ORDER BY e.id DESC LIMIT 100"""),
        "products": rows(c, "SELECT id,barcode,name,stock,price,cost FROM products ORDER BY name")})

@app.post("/api/stock")
@need_admin
def stock_add():
    d = request.json; c = db()
    qty = float(d["qty"]); kind = "in" if qty >= 0 else "adjust"
    ref = d.get("ref_no") or ("STK-" + datetime.now().strftime("%y%m%d%H%M%S"))
    mtype = "PURCHASE_RECEIVED" if qty >= 0 and d.get("supplier_id") else ("DAMAGE" if qty < 0 and "damage" in (d.get("note") or "").lower() else "STOCK_ADJUSTMENT")
    mid = record_movement(c, d["product_id"], qty, mtype, ref, d.get("note", ""))
    c.execute("INSERT INTO stock_entries(ref_no,product_id,qty,kind,note,supplier_id,created,branch_id,movement_id) VALUES(?,?,?,?,?,?,?,1,?)",
              (ref, d["product_id"], qty, kind, d.get("note",""), d.get("supplier_id"), datetime.now().isoformat(timespec="seconds"), mid))
    c.execute("UPDATE products SET stock=stock+? WHERE id=?", (qty, d["product_id"]))
    emit_event(c, "STOCK_MOVED", mid, {"movement_uuid": mid, "ref_no": ref, "product_id": d["product_id"],
                                     "quantity_delta": qty, "movement_type": mtype, "supplier_id": d.get("supplier_id")})
    audit(c, "stock.adjusted", f"{ref} · product {d['product_id']} · {qty:+g}")
    c.commit(); return jsonify({"ok": True, "ref_no": ref})

@app.get("/api/critical")
@need_login
def critical():
    lvl = float(request.args.get("level", 10))
    return jsonify(rows(db(), "SELECT id,barcode,name,stock,price FROM products WHERE stock<=? ORDER BY stock", (lvl,)))

# ---------- Lookups CRUD ----------
@app.route("/api/lookup/<kind>", methods=["GET", "POST", "DELETE"])
@need_login
def lookups(kind):
    table = {"categories": "categories", "brands": "brands", "suppliers": "suppliers"}.get(kind)
    if not table: return jsonify({"error": "bad kind"}), 400
    c = db()
    if request.method == "POST":
        d = request.json
        try:
            c.execute(f"INSERT INTO {table}(name{',contact,phone,address' if table=='suppliers' else ''}) VALUES(?{',?,?,?' if table=='suppliers' else ''})",
                      (d["name"],) if table != "suppliers" else (d["name"], d.get("contact",""), d.get("phone",""), d.get("address","")))
        except sqlite3.IntegrityError: return jsonify({"error": "Already exists"}), 400
        c.commit(); return jsonify({"ok": True})
    if request.method == "DELETE":
        if session.get("role") != "admin": return jsonify({"error": "admin only"}), 403
        c.execute(f"DELETE FROM {table} WHERE id=?", (request.args.get("id"),)); c.commit(); return jsonify({"ok": True})
    return jsonify(rows(c, f"SELECT * FROM {table} ORDER BY name"))

# ---------- Reports ----------
def _reports_payload(c, d):
    return {
        "daily": rows(c, """SELECT s.invoice_no, s.total, s.status, s.created, u.name cashier FROM sales s
            LEFT JOIN users u ON u.id=s.user_id WHERE date(s.created)=? ORDER BY s.id DESC""", (d,)),
        "top": rows(c, """SELECT si.name, SUM(si.qty) qty, SUM(si.total) revenue FROM sale_items si
            JOIN sales s ON s.id=si.sale_id WHERE s.status='completed' GROUP BY si.product_id ORDER BY qty DESC LIMIT 8"""),
        "totals": dict(c.execute("""SELECT COALESCE(SUM(total),0) total, COUNT(*) orders FROM sales
            WHERE date(created)=? AND status='completed'""", (d,)).fetchone()),
    }

@app.get("/api/reports")
@need_login
def reports():
    return jsonify(_reports_payload(db(), request.args.get("date", date.today().isoformat())))

def _dashboard_payload(c, t):
    return {
        "today": dict(c.execute("SELECT COALESCE(SUM(total),0) revenue, COUNT(*) orders FROM sales WHERE date(created)=? AND status='completed'", (t,)).fetchone()),
        "products": c.execute("SELECT COUNT(*) n FROM products").fetchone()["n"],
        "stock_value": dict(c.execute("SELECT COALESCE(SUM(stock*cost),0) v FROM products").fetchone()),
        "low_stock": rows(c, "SELECT id,name,stock,image FROM products WHERE stock<=10 ORDER BY stock LIMIT 6"),
        "expiring": rows(c, """SELECT id,name,expiry,stock,image FROM products WHERE expiry IS NOT NULL AND expiry!=''
            AND date(expiry)<=date('now','+30 days') ORDER BY expiry LIMIT 6"""),
        "recent": rows(c, """SELECT s.invoice_no,s.total,s.created,s.status,u.name cashier FROM sales s
            LEFT JOIN users u ON u.id=s.user_id ORDER BY s.id DESC LIMIT 6"""),
        "top": rows(c, """SELECT si.name, SUM(si.qty) qty, MAX(p.image) image FROM sale_items si
            JOIN sales s ON s.id=si.sale_id LEFT JOIN products p ON p.id=si.product_id
            WHERE s.status='completed' GROUP BY si.product_id ORDER BY qty DESC LIMIT 5"""),
    }

@app.get("/api/dashboard")
@need_login
def dashboard():
    return jsonify(_dashboard_payload(db(), date.today().isoformat()))

# ---------- Users & settings ----------
@app.route("/api/users", methods=["GET", "POST"])
@need_admin
def users():
    c = db()
    if request.method == "POST":
        d = request.json
        try:
            c.execute("INSERT INTO users(username,pw,name,role) VALUES(?,?,?,?)",
                      (d["username"], hashlib.sha256(d["password"].encode()).hexdigest(), d["name"], d.get("role", "cashier")))
        except sqlite3.IntegrityError: return jsonify({"error": "Username taken"}), 400
        audit(c, "user.created", f"{d['username']} ({d.get('role','cashier')})")
        c.commit(); return jsonify({"ok": True})
    return jsonify(rows(c, "SELECT id,username,name,role FROM users ORDER BY id"))

@app.delete("/api/users/<int:uid>")
@need_admin
def user_del(uid):
    if uid == session["uid"]: return jsonify({"error": "Can't delete yourself"}), 400
    c = db()
    u = c.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    c.execute("DELETE FROM users WHERE id=?", (uid,))
    audit(c, "user.deleted", u["username"] if u else str(uid))
    c.commit(); return jsonify({"ok": True})

@app.post("/api/users/<int:uid>/role")
@need_admin
def user_role(uid):
    role = (request.json or {}).get("role")
    if role not in ("admin", "cashier"): return jsonify({"error": "bad role"}), 400
    if uid == session.get("uid"): return jsonify({"error": "can't change your own role"}), 400
    c = db()
    if not c.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone(): return jsonify({"error": "not found"}), 404
    c.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
    audit(c, "user.role_changed", f"user {uid} → {role}")
    c.commit(); return jsonify({"ok": True})

@app.post("/api/users/<int:uid>/password")
@need_login
def user_pw(uid):
    if uid != session["uid"] and session.get("role") != "admin": return jsonify({"error": "forbidden"}), 403
    c = db(); c.execute("UPDATE users SET pw=?, must_change=0 WHERE id=?", (hashlib.sha256(request.json["password"].encode()).hexdigest(), uid))
    audit(c, "user.password_changed", f"user {uid}")
    c.commit(); return jsonify({"ok": True})

@app.route("/api/settings", methods=["GET", "PUT"])
@need_login
def settings():
    c = db()
    if request.method == "PUT":
        if session.get("role") != "admin": return jsonify({"error": "admin only"}), 403
        for k, v in request.json.items(): c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, str(v)))
        audit(c, "settings.updated", ",".join(request.json.keys()))
        c.commit()
    return jsonify({r["k"]: r["v"] for r in c.execute("SELECT * FROM settings")})

# ===========================================================================
# BUILD.md — devices, pairing, sync, purchases, expenses, returns, backup
# ===========================================================================
EVENT_TYPES = {"SALE_CREATED","SALE_VOIDED","STOCK_MOVED","PRODUCT_CREATED","PRODUCT_UPDATED",
               "PRODUCT_DELETED","RETURN_POSTED","PURCHASE_RECEIVED","EXPENSE_POSTED","TRANSFER_CREATED","TRANSFER_DISPATCH","TRANSFER_RECEIVE"}

def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return "127.0.0.1"

@app.get("/api/pair-qr")
@need_admin
def pair_qr():
    """Local QR PNG for the pairing payload — no external service needed (§10.2)."""
    try:
        import qrcode, qrcode.image.svg, io
        from flask import send_file
        img = qrcode.make(request.args.get("data", ""), image_factory=qrcode.image.svg.SvgImage)
        buf = io.BytesIO(); img.save(buf); buf.seek(0)
        return send_file(buf, mimetype="image/svg+xml")
    except ImportError:
        return "", 404

@app.get("/api/v1/ping")
def lan_ping():
    """Unauthenticated LAN discovery beacon for the mobile auto-detect scan."""
    return jsonify({"service": "nova-pos-hub", "version": 1})

@app.route("/api/devices", methods=["GET", "POST"])
@need_admin
def devices():
    c = db()
    if request.method == "POST":  # issue a short-lived pairing token (§10.2)
        tok = secrets.token_urlsafe(6).upper().replace("-","")[:8]
        exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(timespec="seconds")
        c.execute("INSERT INTO pairing_tokens(token,business_id,branch_id,created_by,expires_at) VALUES(?,?,?,?,?)",
                  (tok, DEFAULT_BUSINESS, DEFAULT_BRANCH, session["uid"], exp))
        audit(c, "device.pairing_issued", tok)
        c.commit(); return jsonify({"ok": True, "token": tok, "expires_at": exp, "hub_url": f"http://{lan_ip()}:5050"})
    return jsonify(rows(c, "SELECT id,uuid,device_name,device_type,active,last_seen_at,created_at FROM devices ORDER BY COALESCE(last_seen_at,'') DESC, id DESC"))

@app.post("/api/v1/devices/pair")
def device_pair():
    """Redeem a pairing token → registered device + revocable credential (§10.2)."""
    d = request.json or {}; c = db()
    t = c.execute("""SELECT * FROM pairing_tokens WHERE token=? AND redeemed_at IS NULL
                     AND expires_at > ?""", ((d.get("token") or "").strip().upper(), utcnow())).fetchone()
    if not t: return jsonify({"error": "invalid_or_expired_token"}), 400
    key = "dvk_" + secrets.token_urlsafe(24)
    c.execute("""INSERT INTO devices(uuid,business_id,branch_id,device_name,device_type,api_key_hash,created_at)
                 VALUES(?,?,?,?,?,?,?)""",
              (str(uuid.uuid4()), t["business_id"], t["branch_id"], d.get("device_name") or "Unnamed device",
               d.get("device_type") or "mobile", hashlib.sha256(key.encode()).hexdigest(), utcnow()))
    did = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("UPDATE pairing_tokens SET redeemed_by=?, redeemed_at=? WHERE token=?", (did, utcnow(), t["token"]))
    c.execute("INSERT INTO sync_cursors(device_id,last_sequence) VALUES(?,0)", (did,))
    audit(c, "device.paired", d.get("device_name") or did, actor="pairing")
    c.commit()
    return jsonify({"ok": True, "device_id": did, "device_key": key,
                    "business_id": t["business_id"], "branch_id": t["branch_id"]})

@app.get("/api/v1/devices/me")
@need_device
def device_me():
    d = request.device
    return jsonify({"id": d["id"], "uuid": d["uuid"], "device_name": d["device_name"],
                    "device_type": d["device_type"], "business_id": d["business_id"], "branch_id": d["branch_id"],
                    "last_seen_at": d["last_seen_at"]})

@app.post("/api/devices/<int:did>/revoke")
@need_admin
def device_revoke(did):
    c = db()
    c.execute("UPDATE devices SET active=0 WHERE id=?", (did,))
    audit(c, "device.revoked", f"device {did}")
    c.commit(); return jsonify({"ok": True})

IMG_CACHE = os.path.join(BASE, "static", "imgcache")
os.makedirs(IMG_CACHE, exist_ok=True)

def localize_image(url):
    """Cache a remote image under /static/imgcache so LAN devices fetch it locally.
    Requests thumbnail variants where the source supports it (mobile shows ~72px)."""
    if not url or not str(url).startswith("http"): return url
    import re
    src = re.sub(r"(\.org/wikipedia/[^?]*?/thumb/[^?]+?/)\d+px-", r"\g<1>160px-", url)  # Wikimedia thumbs → 160px
    name = hashlib.sha256(url.encode()).hexdigest()[:16]
    for f in os.listdir(IMG_CACHE):
        if f.startswith(name): return f"/static/imgcache/{f}"
    try:
        r = urllib.request.urlopen(src, timeout=8)
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
               "image/webp": ".webp", "image/svg+xml": ".svg"}.get(
               r.headers.get("Content-Type", "").split(";")[0], ".jpg")
        fname = name + ext
        open(os.path.join(IMG_CACHE, fname), "wb").write(r.read(500_000))  # cap ~500KB
        return f"/static/imgcache/{fname}"
    except Exception:
        return url  # cache later; mobile shows placeholder meanwhile

@app.get("/api/v1/products")
@need_device
def device_products():
    prods = rows(db(), "SELECT id,barcode,name,price,cost,stock,taxable,discount_qty,discount_pct,image FROM products ORDER BY name")
    for p in prods: p["image"] = localize_image(p["image"])
    return jsonify(prods)

def apply_sale_event(c, dev, e):
    """Project a pushed SALE_CREATED into local sales rows. Idempotent via
    sale_uuid — re-delivery and own-hub echoes are no-ops."""
    p = e.get("payload") or {}
    suid = str(p.get("sale_id") or p.get("sale_uuid") or e.get("entity_id") or "")
    if not suid or c.execute("SELECT 1 FROM sales WHERE sale_uuid=?", (suid,)).fetchone():
        return
    cents = p.get("total_cents") is not None
    f = lambda v: round((v or 0) / 100, 2) if cents else round(float(v or 0), 2)
    inv = p.get("receipt_no") or p.get("invoice_no") or "DEV-" + suid[:8]
    if c.execute("SELECT 1 FROM sales WHERE invoice_no=?", (inv,)).fetchone():
        inv += "-" + suid[:4]
    cname = p.get("cashier_name")
    uid = None
    if cname:
        u = c.execute("SELECT id FROM users WHERE name=? OR username=?", (cname, cname)).fetchone()
        uid = u["id"] if u else None
    c.execute("""INSERT INTO sales(invoice_no,total,cash,change_due,vat,discount,user_id,status,created,
                 sale_uuid,business_id,branch_id,device_id,cashier_name) VALUES(?,?,?,0,?,0,?,'completed',?,?,?,?,?,?)""",
              (inv, f(p.get("total_cents") or p.get("total")), f(p.get("total_cents") or p.get("total")),
               f(p.get("tax_cents") or p.get("vat")), uid,
               (e.get("device_created_at") or utcnow())[:19], suid, dev["business_id"], dev["branch_id"], dev["id"], cname))
    sid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    for i in p.get("items", []):
        lt = f(i.get("total_cents") if "total_cents" in i else i.get("total"))
        up = f(i.get("unit_price_cents") if "unit_price_cents" in i else (i.get("total") or 0) / max(i.get("qty") or 1, 1))
        c.execute("INSERT INTO sale_items(sale_id,product_id,name,price,qty,total) VALUES(?,?,?,?,?,?)",
                  (sid, str(i.get("product_id") or ""), i.get("name") or "item", up, i.get("qty") or 0, lt))

@app.get("/api/v1/users")
@need_device
def device_users():
    """Staff list for the mobile "who's on this till" picker — no passwords."""
    return jsonify(rows(db(), "SELECT id,username,name,role FROM users ORDER BY id"))

@app.get("/api/v1/dashboard")
@need_device
def device_dashboard():
    """Business-wide dashboard for admin till users — same payload as /api/dashboard."""
    return jsonify(_dashboard_payload(db(), date.today().isoformat()))

@app.get("/api/v1/reports")
@need_device
def device_reports():
    """Daily report for admin till users — same payload as /api/reports."""
    return jsonify(_reports_payload(db(), request.args.get("date", date.today().isoformat())))

@app.get("/api/v1/devices")
@need_device
def device_list_v1():
    """Registered device roster for admin till users — same query as /api/devices."""
    return jsonify(rows(db(), "SELECT id,uuid,device_name,device_type,active,last_seen_at,created_at FROM devices ORDER BY COALESCE(last_seen_at,'') DESC, id DESC"))

# ---------- Synchronization (§8) ----------
@app.post("/api/v1/sync/push")
@need_device
def sync_push():
    """Accept a batch of events idempotently. Dedupe by event_id (§8.2); allocate
    per-branch server_sequence under the locked stream counter (§8.3)."""
    dev = request.device; events = (request.json or {}).get("events", [])
    c = db(); accepted, dup, rejected = [], [], []
    try:
        c.execute("BEGIN IMMEDIATE")
        for e in events:
            eid = str(e.get("event_id") or "")
            if not eid or e.get("event_type") not in EVENT_TYPES:
                rejected.append({"event_id": eid, "reason": "bad_envelope"}); continue
            if c.execute("SELECT 1 FROM sync_events WHERE event_id=?", (eid,)).fetchone():
                c.execute("INSERT OR IGNORE INTO sync_receipts(event_id,device_id,acked_at,status) VALUES(?,?,?,?)",
                          (eid, dev["id"], utcnow(), "duplicate"))
                dup.append(eid); continue  # re-ack, never re-apply
            r = c.execute("UPDATE sync_streams SET next_sequence=next_sequence+1 WHERE branch_id=? RETURNING next_sequence-1",
                          (dev["branch_id"],)).fetchone()
            if not r:
                c.execute("INSERT INTO sync_streams(branch_id,next_sequence) VALUES(?,2)", (dev["branch_id"],)); r = (1,)
            c.execute("""INSERT INTO sync_events(event_id,business_id,branch_id,device_id,device_sequence,event_type,
                schema_version,entity_id,device_created_at,payload,server_received_at,server_sequence)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (eid, dev["business_id"], dev["branch_id"], dev["id"], e.get("device_sequence"),
                 e["event_type"], e.get("schema_version", 1), str(e.get("entity_id") or ""),
                 e.get("device_created_at"), json.dumps(e.get("payload") or {}), utcnow(), r[0]))
            c.execute("INSERT INTO sync_receipts(event_id,device_id,acked_at,status) VALUES(?,?,?,?)",
                      (eid, dev["id"], utcnow(), "accepted"))
            accepted.append({"event_id": eid, "server_sequence": r[0]})
            if e["event_type"] == "SALE_CREATED":
                apply_sale_event(c, dev, e)
        audit(c, "sync.push", f"device {dev['id']}: {len(accepted)} accepted, {len(dup)} dup, {len(rejected)} rejected",
              actor=f"device:{dev['id']}")
        c.execute("COMMIT")
    except sqlite3.Error:
        c.execute("ROLLBACK"); raise
    return jsonify({"ok": True, "accepted": accepted, "duplicates": dup, "rejected": rejected})

@app.get("/api/v1/sync/pull")
@need_device
def sync_pull():
    """Events after the caller's acknowledged sequence. Cursor advances only via
    /sync/ack after durable local storage — never here (§8.3)."""
    dev = request.device
    after = int(request.args.get("after_sequence", -1))
    if after < 0:
        after = db().execute("SELECT COALESCE(last_sequence,0) s FROM sync_cursors WHERE device_id=?", (dev["id"],)).fetchone()["s"]
    limit = min(int(request.args.get("limit", 200)), 1000)
    ev = rows(db(), """SELECT event_id,event_type,schema_version,entity_id,device_sequence,device_id,
        device_created_at,payload,server_received_at,server_sequence FROM sync_events
        WHERE branch_id=? AND server_sequence>? ORDER BY server_sequence LIMIT ?""", (dev["branch_id"], after, limit))
    latest = db().execute("SELECT COALESCE(MAX(server_sequence),0) s FROM sync_events WHERE branch_id=?",
                          (dev["branch_id"],)).fetchone()["s"]
    return jsonify({"events": ev, "latest_sequence": latest, "cursor": after})

@app.post("/api/v1/sync/ack")
@need_device
def sync_ack():
    """Caller confirms a batch was durably stored — advance its cursor (§8.3 step 7)."""
    dev = request.device; seq = int((request.json or {}).get("last_sequence", 0))
    c = db()
    c.execute("INSERT INTO sync_cursors(device_id,last_sequence,updated_at) VALUES(?,?,?) "
              "ON CONFLICT(device_id) DO UPDATE SET last_sequence=MAX(last_sequence,excluded.last_sequence), updated_at=excluded.updated_at",
              (dev["id"], seq, utcnow()))
    c.commit(); return jsonify({"ok": True, "cursor": seq})

@app.get("/api/v1/sync/status")
def sync_status():
    """Sync health for monitoring (§15). Device callers see their cursor; staff see the hub view."""
    c = db()
    dev = device_identity()
    pending = c.execute("SELECT COUNT(*) n FROM sync_outbox WHERE cloud_acked=0").fetchone()["n"]
    conflicts = c.execute("SELECT COUNT(*) n FROM sync_conflicts WHERE resolved=0").fetchone()["n"]
    latest = c.execute("SELECT COALESCE(MAX(server_sequence),0) s FROM sync_events").fetchone()["s"]
    out = {"latest_sequence": latest, "outbox_pending_cloud": pending, "open_conflicts": conflicts,
           "registered_devices": c.execute("SELECT COUNT(*) n FROM devices WHERE active=1").fetchone()["n"]}
    if dev:
        cur = c.execute("SELECT last_sequence FROM sync_cursors WHERE device_id=?", (dev["id"],)).fetchone()
        out["device_cursor"] = cur["last_sequence"] if cur else 0
        out["device_behind"] = latest - (cur["last_sequence"] if cur else 0)
    return jsonify(out)

@app.get("/api/v1/sync/conflicts")
def sync_conflicts_list():
    if not (device_identity() or "uid" in session): return jsonify({"error": "auth"}), 401
    return jsonify(rows(db(), "SELECT * FROM sync_conflicts WHERE resolved=0 ORDER BY id"))

# ---------- Purchases / expenses / returns (§11) ----------
@app.route("/api/v1/purchases", methods=["GET", "POST"])
@need_login
def purchases():
    c = db()
    if request.method == "POST":
        d = request.json; items = d.get("items", [])
        if not items: return jsonify({"error": "No items"}), 400
        puid = str(uuid.uuid4())
        total = round(sum(float(i["qty"]) * float(i.get("cost", 0)) for i in items), 2)
        c.execute("INSERT INTO purchases(uuid,supplier_id,total,note,user_id,created_at) VALUES(?,?,?,?,?,?)",
                  (puid, d.get("supplier_id"), round(total, 2), d.get("note", ""), session["uid"], utcnow()))
        pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        for i in items:
            qty, cost = float(i["qty"]), float(i.get("cost", 0))
            c.execute("INSERT INTO purchase_items(purchase_id,product_id,qty,cost) VALUES(?,?,?,?)", (pid, i["product_id"], qty, cost))
            c.execute("UPDATE products SET stock=stock+?, cost=? WHERE id=?", (qty, cost, i["product_id"]))
            record_movement(c, i["product_id"], qty, "PURCHASE_RECEIVED", puid, d.get("note", ""))
        emit_event(c, "PURCHASE_RECEIVED", puid, {"purchase_uuid": puid, "total": round(total, 2),
            "supplier_id": d.get("supplier_id"), "items": items})
        audit(c, "purchase.received", f"{puid} · {round(total,2)}")
        c.commit(); return jsonify({"ok": True, "purchase_uuid": puid, "total": round(total, 2)})
    return jsonify(rows(c, """SELECT p.*, s.name supplier, u.name cashier FROM purchases p
        LEFT JOIN suppliers s ON s.id=p.supplier_id LEFT JOIN users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT 100"""))

@app.route("/api/v1/expenses", methods=["GET", "POST"])
@need_login
def expenses():
    c = db()
    if request.method == "POST":
        d = request.json; euid = str(uuid.uuid4())
        c.execute("INSERT INTO expenses(uuid,category,amount,note,user_id,created_at) VALUES(?,?,?,?,?,?)",
                  (euid, d.get("category") or "General", float(d["amount"]), d.get("note", ""), session["uid"], utcnow()))
        emit_event(c, "EXPENSE_POSTED", euid, {"expense_uuid": euid, "category": d.get("category"),
                                             "amount": float(d["amount"])})
        audit(c, "expense.posted", f"{d.get('category')} · {d['amount']}")
        c.commit(); return jsonify({"ok": True, "expense_uuid": euid})
    return jsonify(rows(c, "SELECT e.*, u.name cashier FROM expenses e LEFT JOIN users u ON u.id=e.user_id ORDER BY e.id DESC LIMIT 100"))

@app.post("/api/v1/returns")
@need_login
def returns():
    """Post a return against a sale — reversal records only, originals untouched (§7.2)."""
    d = request.json; sid = d.get("sale_id"); items = d.get("items", [])
    if not sid or not items: return jsonify({"error": "sale_id and items required"}), 400
    c = db()
    s = c.execute("SELECT * FROM sales WHERE id=? AND status='completed'", (sid,)).fetchone()
    if not s: return jsonify({"error": "Sale not found"}), 400
    ruid = str(uuid.uuid4()); total = 0.0
    sold = {i["product_id"]: i for i in c.execute("SELECT * FROM sale_items WHERE sale_id=?", (sid,))}
    c.execute("INSERT INTO returns(uuid,sale_id,reason,total,user_id,created_at) VALUES(?,?,?,?,?,?)",
              (ruid, sid, d.get("reason", ""), 0, session["uid"], utcnow()))
    rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    for i in items:
        pid, qty = int(i["product_id"]), float(i["qty"])
        if pid not in sold or qty > sold[pid]["qty"]:
            return jsonify({"error": f"qty exceeds sold qty for product {pid}"}), 400
        lt = round(sold[pid]["price"] * qty, 2); total += lt
        c.execute("INSERT INTO return_items(return_id,product_id,name,qty,total) VALUES(?,?,?,?,?)",
                  (rid, pid, sold[pid]["name"], qty, lt))
        c.execute("UPDATE products SET stock=stock+? WHERE id=?", (qty, pid))
        record_movement(c, pid, qty, "SALE_RETURN", ruid, f"return of {s['invoice_no']}")
    c.execute("UPDATE returns SET total=? WHERE id=?", (round(total, 2), rid))
    emit_event(c, "RETURN_POSTED", ruid, {"return_uuid": ruid, "sale_uuid": s["sale_uuid"],
        "invoice_no": s["invoice_no"], "total": round(total, 2)})
    audit(c, "sale.returned", f"{s['invoice_no']} · {round(total,2)}")
    c.commit(); return jsonify({"ok": True, "return_uuid": ruid, "total": round(total, 2)})

# ---------- Hub → cloud forwarding (§8.5) ----------
CLOUD_URL = os.environ.get("CLOUD_API_URL", "http://127.0.0.1:5060").rstrip("/")
CLOUD_KEY = os.environ.get("CLOUD_API_KEY", "change-me")
CLOUD_BRANCH_UUID = os.environ.get("CLOUD_BRANCH_ID", "")

def _cloud(method, path, payload=None):
    req = urllib.request.Request(CLOUD_URL + path, method=method,
        headers={"X-Hub-Key": CLOUD_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, json.dumps(payload).encode() if payload is not None else None, timeout=15) as r:
        return json.loads(r.read() or b"{}")

@app.post("/api/admin/cloud-sync")
@need_admin
def cloud_sync():
    """Push unacked outbox events to the cloud API; mark cloud_acked only on
    accepted/duplicate responses — a timeout never loses an event (§8.6)."""
    if not CLOUD_BRANCH_UUID:
        return jsonify({"error": "CLOUD_BRANCH_ID not configured"}), 400
    c = db()
    pending = rows(c, "SELECT * FROM sync_outbox WHERE cloud_acked=0 ORDER BY id LIMIT 100")
    if not pending: return jsonify({"ok": True, "pushed": 0})
    events = [{"event_id": p["event_id"], "event_type": p["event_type"], "entity_id": p["entity_id"],
               "payload": json.loads(p["payload"]), "device_created_at": p["created_at"],
               "device_sequence": p["id"], "device_id": os.environ.get("CLOUD_DEVICE_ID"),
               "business_id": os.environ.get("CLOUD_BUSINESS_ID"), "branch_id": CLOUD_BRANCH_UUID}
              for p in pending]
    try:
        r = _cloud("POST", "/api/v1/sync/push", {"events": events})
    except Exception as e:
        return jsonify({"error": f"cloud_unreachable: {e}"}), 502
    done = {a["event_id"] for a in r.get("accepted", [])} | set(r.get("duplicates", []))
    for eid in done:
        c.execute("UPDATE sync_outbox SET cloud_acked=1 WHERE event_id=?", (eid,))
    audit(c, "sync.cloud_push", f"{len(done)}/{len(pending)} events")
    pulled = _cloud_pull(c)
    c.commit()
    return jsonify({"ok": True, "pulled": pulled, **{k: len(v) for k, v in
        {"pushed": done, "rejected": r.get("rejected", [])}.items()}})

def _cloud_pull(c):
    """Cloud→hub: fetch events after the hub's cloud cursor and accept them into
    the local stream (dedupe by event_id — hub-originated events echo back and
    are no-ops). Cursor advances only after durable local writes (§8.3/§8.5)."""
    cur = int((c.execute("SELECT v FROM settings WHERE k='cloud_pull_seq'").fetchone() or {"v": 0})["v"])
    try:
        r = _cloud("GET", f"/api/v1/sync/pull?branch_id={CLOUD_BRANCH_UUID}&after_sequence={cur}&limit=500")
    except Exception:
        return -1
    n = 0
    for e in r.get("events", []):
        ins = c.execute("""INSERT OR IGNORE INTO sync_events(event_id,business_id,branch_id,device_id,
            device_sequence,event_type,schema_version,entity_id,device_created_at,payload,
            server_received_at,server_sequence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (e["event_id"], DEFAULT_BUSINESS, DEFAULT_BRANCH, e.get("device_id"),
             e.get("device_sequence"), e["event_type"], e.get("schema_version", 1),
             e.get("entity_id"), e.get("device_created_at"), json.dumps(e.get("payload") or {}),
             e.get("server_received_at"), e["server_sequence"]))
        n += ins.rowcount or 0
        cur = max(cur, e["server_sequence"])
    c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES('cloud_pull_seq',?)", (str(cur),))
    return n

# ---------- Backup & diagnostics (§15) ----------
@app.get("/api/admin/backup")
@need_admin
def backup():
    import shutil, tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    src = db(); dst = sqlite3.connect(tmp.name); src.backup(dst); dst.close(); src.close()
    audit(db(), "admin.backup", tmp.name)
    from flask import send_file
    return send_file(tmp.name, as_attachment=True, download_name=f"pos-backup-{date.today().isoformat()}.db")

@app.get("/api/admin/audit")
@need_admin
def audit_list():
    return jsonify(rows(db(), "SELECT * FROM audit_logs ORDER BY id DESC LIMIT 300"))

def _auto_sync():
    """Background hub→cloud forwarder with retry/backoff (§8.6)."""
    import time
    delay = 30
    while True:
        try:
            with app.test_request_context():
                session["uid"], session["name"], session["role"] = 0, "auto-sync", "admin"
                cloud_sync()
            delay = 30
        except Exception:
            delay = min(delay * 2, 600)
        time.sleep(delay)

if __name__ == "__main__":
    init_db()
    if CLOUD_BRANCH_UUID and os.environ.get("POS_AUTOSYNC", "1") == "1":
        import threading; threading.Thread(target=_auto_sync, daemon=True).start()
    app.run(host="0.0.0.0", port=5050, debug=False)
