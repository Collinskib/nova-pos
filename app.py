#!/usr/bin/env python3
"""POS & Inventory Management System — Flask + SQLite."""
import sqlite3, hashlib, secrets, json, os, re, uuid, urllib.request, urllib.error, socket, time
from datetime import datetime, date, timezone, timedelta
from functools import wraps
from flask import Flask, request, jsonify, session, render_template, redirect

BASE = os.path.dirname(os.path.abspath(__file__))
def _load_dotenv(path=os.path.join(BASE, ".env")):
    """Tiny .env loader so autosync/config work when app.py isn't wrapped by dotenv."""
    if not os.path.exists(path): return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
_load_dotenv()
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

mig(4, """
CREATE TABLE IF NOT EXISTS shifts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id INTEGER, cashier_name TEXT, business_id INTEGER, branch_id INTEGER,
  opened_at TEXT NOT NULL, closed_at TEXT,
  opening_float REAL DEFAULT 0, closing_count REAL,
  expected_cash REAL, difference REAL, status TEXT DEFAULT 'OPEN');
""")

mig(5, """
CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, created_at TEXT);
ALTER TABLE sales ADD COLUMN customer_name TEXT;
""")

mig(6, """
ALTER TABLE products ADD COLUMN price_wholesale REAL;
""")

mig(7, """
CREATE TABLE IF NOT EXISTS promos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, kind TEXT, value REAL,
  min_total REAL DEFAULT 0, active INTEGER DEFAULT 1, created_at TEXT);
ALTER TABLE sales ADD COLUMN promo_code TEXT;
""")

mig(8, """
ALTER TABLE products ADD COLUMN parent_id INTEGER;
ALTER TABLE products ADD COLUMN variant_label TEXT;
""")

mig(9, """
ALTER TABLE products ADD COLUMN pack_size INTEGER DEFAULT 0;
ALTER TABLE products ADD COLUMN pack_price REAL;
""")

mig(10, """
CREATE TABLE IF NOT EXISTS batches(
  id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER, batch_no TEXT,
  qty REAL, expiry TEXT, created_at TEXT);
""")

# 0011 — cash drawer movements (petty cash in/out mid-shift) + credit ledger
mig(11, """
CREATE TABLE IF NOT EXISTS cash_movements(
  id INTEGER PRIMARY KEY AUTOINCREMENT, shift_id INTEGER, device_id INTEGER,
  kind TEXT, amount REAL, note TEXT, user_name TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS credit_payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT UNIQUE, customer_id INTEGER,
  sale_id INTEGER, kind TEXT, amount REAL, note TEXT, created_at TEXT);
ALTER TABLE customers ADD COLUMN balance REAL DEFAULT 0;
ALTER TABLE sales ADD COLUMN customer_id INTEGER;
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
                      (1, str(uuid.uuid4()), "Shujaa Mart", datetime.now(timezone.utc).isoformat(timespec="seconds")))
            c.execute("INSERT INTO branches(id,uuid,business_id,name,address,created_at) VALUES(?,?,?,?,?,?)",
                      (1, str(uuid.uuid4()), 1, "Main Branch", "Moi Avenue, Nairobi", datetime.now(timezone.utc).isoformat(timespec="seconds")))
            c.execute("INSERT INTO sync_streams(branch_id,next_sequence) VALUES(1,1)")
        c.execute("INSERT INTO schema_versions(version,applied_at) VALUES(?,?)", (n, datetime.now(timezone.utc).isoformat(timespec="seconds")))
SEED_SETTINGS = {"store_name": "Shujaa Mart", "store_address": "Moi Avenue, Nairobi, Kenya", "store_phone": "+254 712 345 678", "tax_rate": "16", "currency": "KSh "}

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
        h = _pw_hash
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

def utcts():
    """Naive UTC timestamp for ledger rows — the UI renders stored values as UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

# ---------- password hashing (pbkdf2; legacy sha256 upgraded on login) ----------
def _pw_hash(pw):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 60_000).hex()
    return f"pbkdf2$60000${salt}${h}"

def _pw_ok(pw, stored):
    """Verify against pbkdf2 (new) or legacy sha256. Returns (ok, needs_upgrade)."""
    if (stored or "").startswith("pbkdf2$"):
        try: _, it, salt, h = stored.split("$")
        except ValueError: return False, False
        mine = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it)).hex()
        return secrets.compare_digest(mine, h), False
    return secrets.compare_digest(hashlib.sha256(pw.encode()).hexdigest(), stored or ""), True

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

def _sb_public():
    """Supabase URL + publishable anon key for browser-side auth (same project as web/mobile)."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    anon = os.environ.get("SUPABASE_ANON_KEY", "")
    if not anon:
        cfg = os.path.join(BASE, "web", "config.js")
        if os.path.exists(cfg):
            m = re.search(r'anon:\s*"([^"]+)"', open(cfg).read())
            anon = m.group(1) if m else ""
    return url, anon

@app.get("/")
def index():
    if "uid" in session: return render_template("index.html")
    url, anon = _sb_public()
    return render_template("login.html", sb_url=url, sb_anon=anon)

def _sb_api(path, token=None, params=None):
    url, anon = _sb_public()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or anon
    req = urllib.request.Request(url + path,
        headers={"apikey": key, "Authorization": f"Bearer {token or key}"})
    if params: req.full_url += "?" + params
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None

@app.post("/api/cloud_login")
def cloud_login():
    """Exchange a Supabase web session (Google/email sign-in on this page) for a hub session.
    The cloud user must hold a membership for this hub's business; first login auto-provisions
    a local staff row so sales/audit keep a real users.id."""
    tok = (request.json or {}).get("access_token", "")
    if not tok: return jsonify({"error": "no session token"}), 400
    st, user = _sb_api("/auth/v1/user", token=tok)
    if st != 200 or not user: return jsonify({"error": "invalid or expired cloud session"}), 401
    uid, email = user["id"], user.get("email") or user.get("phone") or user["id"]
    bid = os.environ.get("CLOUD_BUSINESS_ID", "")
    role = "cashier"
    if bid:
        st, ms = _sb_api("/rest/v1/business_memberships",
            params=f"user_id=eq.{uid}&business_id=eq.{bid}&select=role")
        if st != 200 or not ms:
            return jsonify({"error": "This account isn't a member of this hub's business"}), 403
        role = ms[0].get("role") or "cashier"
    c = db()
    uname = "cloud:" + email
    u = c.execute("SELECT * FROM users WHERE username=?", (uname,)).fetchone()
    if not u:
        c.execute("INSERT INTO users(username,pw,name,role,must_change) VALUES(?,?,?,?,0)",
                  (uname, _pw_hash(secrets.token_urlsafe(24)),
                   user.get("user_metadata", {}).get("full_name") or email.split("@")[0],
                   "admin" if role in ("admin", "owner") else "cashier"))
        c.commit()
        u = c.execute("SELECT * FROM users WHERE username=?", (uname,)).fetchone()
        audit(c, "auth.user_provisioned", uname, actor="cloud")
    session.update(uid=u["id"], name=u["name"], role=u["role"], must_change=False)
    audit(c, "auth.cloud_login", email, actor=u["name"]); c.commit(); c.close()
    return jsonify({"ok": True, "name": u["name"], "role": u["role"]})

if os.environ.get("POS_DEV_SHOTS"):  # screenshot helper — only active when env var is set
    @app.get("/devlogin/<page>")
    def devlogin(page):
        u = db().execute("SELECT * FROM users WHERE username='admin'").fetchone()
        session.update(uid=u["id"], name=u["name"], role=u["role"])
        return redirect("/#" + page)

_login_fails = {}  # (ip, username) → [count, first_ts] — in-memory brute-force throttle
@app.post("/api/login")
def login():
    d = request.json
    key = (request.remote_addr or "?", d.get("username", ""))
    now = time.time()
    cnt, first = _login_fails.get(key, (0, now))
    if now - first > 300: cnt, first = 0, now          # 5-minute window
    if cnt >= 5:
        return jsonify({"error": "Too many attempts — try again shortly"}), 429
    c = db()
    u = c.execute("SELECT * FROM users WHERE username=?", (d["username"],)).fetchone()
    ok, upgrade = _pw_ok(d["password"], u["pw"]) if u else (False, False)
    if not ok:
        _login_fails[key] = (cnt + 1, first)
        audit(c, "auth.login_failed", d["username"], actor=d["username"]); c.commit(); c.close()
        return jsonify({"error": "Invalid username or password"}), 401
    _login_fails.pop(key, None)
    if upgrade:  # transparent sha256 → pbkdf2 migration on first successful login
        c.execute("UPDATE users SET pw=? WHERE id=?", (_pw_hash(d["password"]), u["id"]))
    session.update(uid=u["id"], name=u["name"], role=u["role"], must_change=bool(u["must_change"]))
    audit(c, "auth.login", u["username"], actor=u["name"]); c.commit(); c.close()
    return jsonify({"ok": True, "name": u["name"], "role": u["role"], "must_change": bool(u["must_change"]) if "must_change" in u.keys() else False})

@app.before_request
def _force_password_change():
    """A must_change user may only reach their own password endpoint + logout."""
    if not session.get("uid") or not session.get("must_change"): return
    allowed = ("user_pw", "logout", "bootstrap", "static")
    if request.endpoint in allowed or (request.path.startswith("/static")): return
    if request.path.startswith("/api/"):
        return jsonify({"error": "password_change_required"}), 403

@app.post("/api/forgot")
def forgot():
    uname = (request.json or {}).get("username", "").strip()
    u = db().execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
    if u:
        c = db()
        c.execute("INSERT INTO reset_requests(username,user_id,created) VALUES(?,?,?)",
                  (uname, u["id"], utcts()))
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
    temp = "Shujaa-" + secrets.token_hex(3)
    c.execute("UPDATE users SET pw=?, must_change=1 WHERE id=?",
              (_pw_hash(temp), r["user_id"]))
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
        c.execute("INSERT INTO products(barcode,name,category_id,brand_id,price,price_wholesale,stock,cost,taxable,discount_qty,discount_pct,expiry,image,parent_id,variant_label,pack_size,pack_price) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (d["barcode"], d["name"], d.get("category_id"), d.get("brand_id"), d["price"], d.get("price_wholesale"), d.get("stock",0), d.get("cost",0), d.get("taxable",1), d.get("discount_qty",0), d.get("discount_pct",0), d.get("expiry") or None, d.get("image") or None, d.get("parent_id") or None, d.get("variant_label") or None, d.get("pack_size") or 0, d.get("pack_price")))
    except sqlite3.IntegrityError: return jsonify({"error": "Barcode already exists"}), 400
    pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    emit_event(c, "PRODUCT_CREATED", str(pid), {"product_id": pid, "product_uuid": str(uuid.uuid5(uuid.NAMESPACE_DNS, str(pid))), **{k: d.get(k) for k in ("barcode","name","price","price_wholesale","stock","cost","parent_id","variant_label","pack_size","pack_price")}})
    audit(c, "product.created", d["name"])
    c.commit(); return jsonify({"ok": True})

@app.put("/api/products/<int:pid>")
@need_admin
def product_edit(pid):
    d = request.json; c = db()
    c.execute("UPDATE products SET barcode=?,name=?,category_id=?,brand_id=?,price=?,price_wholesale=?,stock=?,cost=?,taxable=?,discount_qty=?,discount_pct=?,expiry=?,image=?,parent_id=?,variant_label=?,pack_size=?,pack_price=? WHERE id=?",
              (d["barcode"], d["name"], d.get("category_id"), d.get("brand_id"), d["price"], d.get("price_wholesale"), d["stock"], d.get("cost",0), d.get("taxable",1), d.get("discount_qty",0), d.get("discount_pct",0), d.get("expiry") or None, d.get("image") or None, d.get("parent_id") or None, d.get("variant_label") or None, d.get("pack_size") or 0, d.get("pack_price"), pid))
    emit_event(c, "PRODUCT_UPDATED", str(pid), {"product_id": pid, **{k: d.get(k) for k in ("barcode","name","price","price_wholesale","stock","cost","parent_id","variant_label","pack_size","pack_price")}})
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
    if m.group(1) == "image/svg+xml":  # svg can carry scripts — never stored same-origin
        return jsonify({"error": "SVG not allowed"}), 400
    ext = {"jpeg": "jpg", "png": "png", "gif": "gif", "webp": "webp"}.get(m.group(1)[6:], "img")
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
        req = urllib.request.Request(url, headers={"User-Agent": "ShujaaPOS/1.0"})
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
        WHERE p.barcode=? OR p.name LIKE ? OR p.parent_id IN (SELECT id FROM products WHERE barcode=? OR name LIKE ?)
        ORDER BY p.name LIMIT 20""", (q, f"%{q}%", q, f"%{q}%")).fetchall()
    return jsonify([dict(x) for x in r])

@app.post("/api/checkout")
@need_login
def checkout():
    """Atomic sale. Prices, names, tax flags and bulk deals are re-read from the
    products table — client-sent prices are never trusted (till staff could
    otherwise charge any amount). Promos are validated and applied here."""
    d = request.json; items = d.get("items", [])
    if not items: return jsonify({"error": "Cart is empty"}), 400
    c = db()
    try:
        c.execute("BEGIN IMMEDIATE")
        rate = float(c.execute("SELECT v FROM settings WHERE k='tax_rate'").fetchone()["v"] or 0)
        wholesale = d.get("price_list") == "wholesale"
        vat = total = gross = 0.0
        lines = []
        for i in items:
            p2 = c.execute("SELECT * FROM products WHERE id=?", (i.get("id"),)).fetchone()
            qty = float(i.get("qty") or 0)
            if not p2 or p2["stock"] < qty or qty <= 0:
                c.execute("ROLLBACK")
                return jsonify({"error": f"Not enough stock: {p2['name'] if p2 else i.get('id')}"}), 400
            if i.get("pack") and (p2["pack_size"] or 0) > 1:
                unit = round((p2["pack_price"] if p2["pack_price"] is not None else p2["price"] * p2["pack_size"]) / p2["pack_size"], 2)
                suffix = f" · pack ×{p2['pack_size']}"
            elif wholesale and p2["price_wholesale"] is not None:
                unit, suffix = float(p2["price_wholesale"]), ""
            else:
                unit, suffix = float(p2["price"]), ""
            name = p2["name"] + (f" · {p2['variant_label']}" if p2["variant_label"] else "") + suffix
            gross += unit * qty
            line = round(unit * qty * (1 - (p2["discount_pct"] or 0) / 100 if p2["discount_qty"] and qty >= p2["discount_qty"] else 1), 2)
            total += line
            if p2["taxable"]:
                vat += round(line * rate / (100 + rate), 2)  # VAT-inclusive pricing
            lines.append({"id": p2["id"], "name": name, "price": unit, "qty": qty, "line_total": line})
        total = round(total, 2)
        promo_amt = 0.0
        code = (d.get("promo_code") or "").strip().upper()
        if code:
            pr = c.execute("SELECT * FROM promos WHERE code=? AND active=1", (code,)).fetchone()
            if not pr:
                c.execute("ROLLBACK"); return jsonify({"error": f"Promo code {code} is invalid or inactive"}), 400
            if total < float(pr["min_total"] or 0):
                c.execute("ROLLBACK"); return jsonify({"error": f"Promo {code} needs a minimum spend of {pr['min_total']}"}), 400
            promo_amt = round(total * float(pr["value"]) / 100, 2) if pr["kind"] == "pct" else round(min(float(pr["value"]), total), 2)
        inv_disc = round(float(d.get("discount") or 0) + promo_amt, 2)
        eff = round(max(0.0, total - inv_disc), 2)
        pays = []
        if isinstance(d.get("payments"), list) and d["payments"]:
            pays = [{"method": str(p.get("method") or "cash"), "amount": round(float(p.get("amount") or 0), 2)}
                    for p in d["payments"]
                    if float(p.get("amount") or 0) > 0 or str(p.get("method")) == "credit"]
        if not pays:
            pays = [{"method": d.get("method", "cash"), "amount": round(float(d.get("cash", eff)), 2)}]
        cash = round(sum(p["amount"] for p in pays), 2)
        on_credit = any(p["method"] == "credit" for p in pays)
        if cash < eff and not on_credit:
            c.execute("ROLLBACK"); return jsonify({"error": "Insufficient cash"}), 400
        # credit amount owed = the shortfall a credit line covers
        credit_amt = round(max(0.0, eff - sum(p["amount"] for p in pays if p["method"] != "credit")), 2) if on_credit else 0.0
        cid = d.get("customer_id")
        if not cid and d.get("customer_name"):
            cust = c.execute("SELECT id FROM customers WHERE name=?", (d["customer_name"],)).fetchone()
            cid = cust["id"] if cust else None
        if credit_amt > 0:
            if not cid:
                c.execute("ROLLBACK"); return jsonify({"error": "Credit sales need a registered customer"}), 400
            if not c.execute("SELECT 1 FROM customers WHERE id=?", (cid,)).fetchone():
                c.execute("ROLLBACK"); return jsonify({"error": "Unknown customer"}), 400
        suid = str(uuid.uuid4())
        inv = next_receipt(c)
        ur = c.execute("SELECT name FROM users WHERE id=?", (session["uid"],)).fetchone()
        c.execute("""INSERT INTO sales(invoice_no,total,cash,change_due,vat,discount,user_id,status,created,
                     sale_uuid,business_id,branch_id,customer_name,cashier_name,promo_code,customer_id)
                     VALUES(?,?,?,?,?,?,?,'completed',?,?,?,?,?,?,?,?)""",
                  (inv, eff, cash, round(max(0.0, cash - eff), 2), round(vat, 2), round(gross - eff, 2), session["uid"],
                   utcts(), suid, DEFAULT_BUSINESS, DEFAULT_BRANCH,
                   d.get("customer_name"), ur["name"] if ur else None, code or None, cid))
        sid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        for i in lines:
            c.execute("INSERT INTO sale_items(sale_id,product_id,name,price,qty,total) VALUES(?,?,?,?,?,?)",
                      (sid, i["id"], i["name"], i["price"], i["qty"], i["line_total"]))
            c.execute("UPDATE products SET stock=stock-? WHERE id=?", (i["qty"], i["id"]))
            # FEFO: deplete expiring batches first so the ledger matches the shelf
            left = i["qty"]
            for b in c.execute("""SELECT id,qty FROM batches WHERE product_id=? AND qty>0
                                  ORDER BY COALESCE(expiry,'9999'), id""", (i["id"],)).fetchall():
                if left <= 0: break
                take = min(left, b["qty"])
                c.execute("UPDATE batches SET qty=qty-? WHERE id=?", (take, b["id"]))
                left -= take
            record_movement(c, i["id"], -i["qty"], "SALE", suid, f"sale {inv}")
        for p in pays:  # the credit row reflects the actual amount owed, not client claims
            amt = credit_amt if p["method"] == "credit" else p["amount"]
            c.execute("INSERT INTO payments(sale_id,method,amount,created) VALUES(?,?,?,?)",
                      (sid, p["method"], amt, utcts()))
        if credit_amt > 0:  # ledger the debt against the customer
            c.execute("INSERT INTO credit_payments(uuid,customer_id,sale_id,kind,amount,note,created_at) VALUES(?,?,?,?,?,?,?)",
                      (str(uuid.uuid4()), cid, sid, "charge", credit_amt, inv, utcts()))
            c.execute("UPDATE customers SET balance=balance+? WHERE id=?", (credit_amt, cid))
        emit_event(c, "SALE_CREATED", suid,
                   {"sale_uuid": suid, "invoice_no": inv, "subtotal": total, "total": eff, "vat": round(vat, 2),
                    "discount": round(gross - eff, 2), "cash": cash, "method": pays[0]["method"],
                    "payments": pays,
                    "customer_name": d.get("customer_name"), "promo_code": code or None, "items": [
                        {"product_id": i["id"], "product_uuid": str(uuid.uuid5(uuid.NAMESPACE_DNS, str(i["id"]))),
                         "name": i["name"], "qty": i["qty"], "total": i["line_total"]} for i in lines]})
        audit(c, "sale.completed", f"{inv} · {eff}")
        c.execute("COMMIT")
    except sqlite3.Error:
        try: c.execute("ROLLBACK")
        except sqlite3.Error: pass
        raise
    finally: c.close()
    return jsonify({"ok": True, "invoice": inv, "total": eff, "cash": cash, "change": round(max(0.0, cash - eff), 2), "id": sid})

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
                  (d.get("label") or "Held sale", json.dumps(d["items"]), session["uid"], utcts()))
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
        "products": rows(c, "SELECT id,barcode,name,stock,price,cost FROM products ORDER BY name"),
        "batches": rows(c, "SELECT b.*, p.name product FROM batches b LEFT JOIN products p ON p.id=b.product_id ORDER BY b.id DESC LIMIT 50")})

@app.post("/api/stock")
@need_admin
def stock_add():
    d = request.json; c = db()
    qty = float(d["qty"]); kind = "in" if qty >= 0 else "adjust"
    ref = d.get("ref_no") or ("STK-" + datetime.now().strftime("%y%m%d%H%M%S"))
    mtype = "PURCHASE_RECEIVED" if qty >= 0 and d.get("supplier_id") else ("DAMAGE" if qty < 0 and "damage" in (d.get("note") or "").lower() else "STOCK_ADJUSTMENT")
    mid = record_movement(c, d["product_id"], qty, mtype, ref, d.get("note", ""))
    c.execute("INSERT INTO stock_entries(ref_no,product_id,qty,kind,note,supplier_id,created,branch_id,movement_id) VALUES(?,?,?,?,?,?,?,1,?)",
              (ref, d["product_id"], qty, kind, d.get("note",""), d.get("supplier_id"), utcts(), mid))
    c.execute("UPDATE products SET stock=stock+? WHERE id=?", (qty, d["product_id"]))
    if qty > 0 and (d.get("batch_no") or "").strip():
        c.execute("INSERT INTO batches(product_id,batch_no,qty,expiry,created_at) VALUES(?,?,?,?,?)",
                  (d["product_id"], d["batch_no"].strip(), qty, d.get("expiry") or None,
                   datetime.now().isoformat(timespec="seconds")))
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
        if session.get("role") != "admin": return jsonify({"error": "admin only"}), 403
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
                      (d["username"], _pw_hash(d["password"]), d["name"], d.get("role", "cashier")))
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
    c = db(); c.execute("UPDATE users SET pw=?, must_change=0 WHERE id=?", (_pw_hash(request.json["password"]), uid))
    if uid == session.get("uid"): session["must_change"] = False
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
        audit(c, "device.pairing_issued", f"…{tok[-2:]}")  # never log the secret itself
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
        if r.headers.get("Content-Type", "").split(";")[0] == "image/svg+xml":
            return url  # scriptable format — don't cache/serve it from our origin
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
               "image/webp": ".webp"}.get(
               r.headers.get("Content-Type", "").split(";")[0], ".jpg")
        fname = name + ext
        open(os.path.join(IMG_CACHE, fname), "wb").write(r.read(500_000))  # cap ~500KB
        return f"/static/imgcache/{fname}"
    except Exception:
        return url  # cache later; mobile shows placeholder meanwhile

@app.get("/api/v1/products")
@need_device
def device_products():
    prods = rows(db(), "SELECT id,barcode,name,price,price_wholesale,cost,stock,taxable,discount_qty,discount_pct,image,parent_id,variant_label,pack_size,pack_price FROM products ORDER BY name")
    for p in prods: p["image"] = localize_image(p["image"])
    return jsonify(prods)

def _product_ref_map(c):
    """Wire product references → local product ids. Devices carry the hub's
    integer id as a string; cloud/web entities carry uuid5(str(id))."""
    out = {}
    for r in c.execute("SELECT id FROM products"):
        out[str(r["id"])] = r["id"]
        out[str(uuid.uuid5(uuid.NAMESPACE_DNS, str(r["id"])))] = r["id"]
    return out

def _conflict(c, e, reason, detail):
    """An accepted event that can't be projected is a conflict, never a silent skip."""
    c.execute("INSERT INTO sync_conflicts(event_id,device_id,reason,detail,created_at) VALUES(?,?,?,?,?)",
              (e.get("event_id"), e.get("device_id"), reason, json.dumps(detail), utcnow()))

def apply_sale_event(c, dev, e):
    """Project a pushed SALE_CREATED into local sales rows — including the stock
    decrement, the ledger movement and the payment rows. Idempotent via
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
    cname = p.get("cashier_name") or dev.get("device_name")  # till user first, device as fallback
    uid = None
    if cname:
        u = c.execute("SELECT id FROM users WHERE name=? OR username=?", (cname, cname)).fetchone()
        uid = u["id"] if u else None
    tot = f(p.get("total_cents") or p.get("total"))
    paid = f(p["paid_cents"]) if p.get("paid_cents") is not None else tot
    c.execute("""INSERT INTO sales(invoice_no,total,cash,change_due,vat,discount,user_id,status,created,
                 sale_uuid,business_id,branch_id,device_id,cashier_name,customer_name,promo_code)
                 VALUES(?,?,?,?,?,?,?,'completed',?,?,?,?,?,?,?,?)""",
              (inv, tot, paid, round(max(0, paid - tot), 2),
               f(p.get("tax_cents") or p.get("vat")), f(p.get("discount_cents") or 0), uid,
               (e.get("device_created_at") or utcnow())[:19], suid, dev["business_id"], dev["branch_id"], dev["id"], cname,
               p.get("customer_name"), p.get("promo_code")))
    sid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    pmap = _product_ref_map(c)
    for i in p.get("items", []):
        lt = f(i.get("total_cents") if "total_cents" in i else i.get("total"))
        up = f(i.get("unit_price_cents") if "unit_price_cents" in i else (i.get("total") or 0) / max(i.get("qty") or 1, 1))
        pid = pmap.get(str(i.get("product_id") or i.get("product_uuid") or ""))
        c.execute("INSERT INTO sale_items(sale_id,product_id,name,price,qty,total) VALUES(?,?,?,?,?,?)",
                  (sid, pid, i.get("name") or "item", up, i.get("qty") or 0, lt))
        if pid and (i.get("qty") or 0) > 0:   # the device already debited its mirror — debit ours + ledger
            c.execute("UPDATE products SET stock=stock-? WHERE id=?", (i["qty"], pid))
            record_movement(c, pid, -i["qty"], "SALE", suid, f"sale {inv}", dev.get("id"))
    pays = p.get("payments") or [{"method": p.get("method") or "cash", "amount": paid}]
    for pay in pays:
        amt = round((pay.get("amount_cents") or 0) / 100, 2) if "amount_cents" in pay else round(float(pay.get("amount") or 0), 2)
        if amt <= 0 and str(pay.get("method")) != "credit":
            continue   # split-payment UI can emit negative/zero remainder rows — not real tenders
        c.execute("INSERT INTO payments(sale_id,method,amount,created) VALUES(?,?,?,?)",
                  (sid, str(pay.get("method") or "cash"), amt, utcts()))

def apply_incoming_event(c, dev, e):
    """Projector for events arriving via /sync/push or _cloud_pull. Any type the
    hub can represent is applied; the rest stay durable in sync_events."""
    t, p = e["event_type"], e.get("payload") or {}
    if t == "SALE_CREATED":
        return apply_sale_event(c, dev, e)
    if t == "SALE_VOIDED":
        suid = str(p.get("sale_uuid") or e.get("entity_id") or "")
        s = c.execute("SELECT * FROM sales WHERE sale_uuid=? AND status='completed'", (suid,)).fetchone()
        if not s: return
        c.execute("UPDATE sales SET status='void' WHERE id=?", (s["id"],))
        for i in c.execute("SELECT product_id,qty FROM sale_items WHERE sale_id=?", (s["id"],)):
            if i["product_id"]:
                c.execute("UPDATE products SET stock=stock+? WHERE id=?", (i["qty"], i["product_id"]))
                record_movement(c, i["product_id"], i["qty"], "SALE_RETURN", suid, f"void {s['invoice_no']}", dev.get("id"))
    elif t == "STOCK_MOVED":
        pid = _product_ref_map(c).get(str(p.get("product_id") or p.get("product_uuid") or ""))
        if not pid: return _conflict(c, e, "unmapped_product", {"product_id": p.get("product_id"), "product_uuid": p.get("product_uuid")})
        qty = float(p.get("quantity_delta") or 0)
        c.execute("UPDATE products SET stock=stock+? WHERE id=?", (qty, pid))
        record_movement(c, pid, qty, p.get("movement_type") or "STOCK_ADJUSTMENT",
                        str(p.get("movement_uuid") or e.get("entity_id") or ""), p.get("note") or p.get("ref_no") or "", dev.get("id"))
    elif t in ("PRODUCT_CREATED", "PRODUCT_UPDATED"):
        # concurrent-edit detection: another writer already touched this entity
        # after this event was created → flag, still apply (last-writer-wins).
        if t == "PRODUCT_UPDATED":
            newer = c.execute("""SELECT 1 FROM sync_events WHERE event_type='PRODUCT_UPDATED'
                AND entity_id=? AND CAST(device_id AS TEXT) != ? AND device_created_at > ? LIMIT 1""",
                (str(e.get("entity_id") or ""), str(e.get("device_id") or ""),
                 e.get("device_created_at") or "")).fetchone()
            if newer:
                _conflict(c, e, "concurrent_product_edit",
                          {"entity_id": e.get("entity_id"), "name": p.get("name")})
        bc = (p.get("barcode") or "").strip() or None
        row = c.execute("SELECT id FROM products WHERE barcode=?", (bc,)).fetchone() if bc else None
        if not row:
            pid = _product_ref_map(c).get(str(p.get("product_id") or p.get("product_uuid") or ""))
            row = c.execute("SELECT id FROM products WHERE id=?", (pid,)).fetchone() if pid else None
        vals = {k: p.get(k) for k in ("name", "price", "price_wholesale", "cost", "taxable") if p.get(k) is not None}
        if row and vals:
            c.execute("UPDATE products SET " + ", ".join(f"{k}=?" for k in vals) + " WHERE id=?",
                      tuple(vals.values()) + (row["id"],))
        elif not row and (bc or p.get("name")):
            c.execute("INSERT INTO products(barcode,name,price,price_wholesale,cost,taxable,stock) VALUES(?,?,?,?,?,?,?)",
                      (bc, p.get("name") or "Unnamed", float(p.get("price") or 0), p.get("price_wholesale"),
                       float(p.get("cost") or 0), int(p.get("taxable", 1)), float(p.get("stock") or 0)))
    elif t == "PRODUCT_DELETED":
        pid = _product_ref_map(c).get(str(p.get("product_id") or e.get("entity_id") or ""))
        if pid: c.execute("DELETE FROM products WHERE id=?", (pid,))
    elif t == "RETURN_POSTED":
        ruid = str(p.get("return_uuid") or e.get("entity_id") or "")
        if not ruid or c.execute("SELECT 1 FROM returns WHERE uuid=?", (ruid,)).fetchone(): return
        s = c.execute("SELECT * FROM sales WHERE sale_uuid=?", (str(p.get("sale_uuid") or ""),)).fetchone()
        if not s: return _conflict(c, e, "return_sale_missing", {"sale_uuid": p.get("sale_uuid")})
        pmap = _product_ref_map(c); total = 0.0
        c.execute("INSERT INTO returns(uuid,sale_id,reason,total,user_id,created_at) VALUES(?,?,?,?,?,?)",
                  (ruid, s["id"], p.get("reason", ""), 0, None, utcnow()))
        rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        for i in p.get("items", []):
            pid = pmap.get(str(i.get("product_id") or i.get("product_uuid") or ""))
            if not pid: continue
            qty = float(i.get("qty") or 0); lt = round(float(i.get("total") or 0), 2); total += lt
            c.execute("INSERT INTO return_items(return_id,product_id,name,qty,total) VALUES(?,?,?,?,?)",
                      (rid, pid, i.get("name") or "item", qty, lt))
            c.execute("UPDATE products SET stock=stock+? WHERE id=?", (qty, pid))
            record_movement(c, pid, qty, "SALE_RETURN", ruid, "remote return", dev.get("id"))
        c.execute("UPDATE returns SET total=? WHERE id=?", (round(total, 2), rid))
    elif t == "PURCHASE_RECEIVED":
        puid = str(p.get("purchase_uuid") or e.get("entity_id") or "")
        if not puid or c.execute("SELECT 1 FROM purchases WHERE uuid=?", (puid,)).fetchone(): return
        c.execute("INSERT INTO purchases(uuid,supplier_id,total,note,user_id,created_at) VALUES(?,?,?,?,?,?)",
                  (puid, None, float(p.get("total") or 0), "remote", None, utcnow()))
        puh = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        pmap = _product_ref_map(c)
        for i in p.get("items", []):
            pid = pmap.get(str(i.get("product_id") or i.get("product_uuid") or ""))
            if not pid: continue
            qty, cost = float(i.get("qty") or 0), float(i.get("cost") or 0)
            c.execute("INSERT INTO purchase_items(purchase_id,product_id,qty,cost) VALUES(?,?,?,?)", (puh, pid, qty, cost))
            c.execute("UPDATE products SET stock=stock+?, cost=? WHERE id=?", (qty, cost, pid))
            record_movement(c, pid, qty, "PURCHASE_RECEIVED", puid, "remote purchase", dev.get("id"))
    elif t == "EXPENSE_POSTED":
        euid = str(p.get("expense_uuid") or e.get("entity_id") or "")
        if not euid or c.execute("SELECT 1 FROM expenses WHERE uuid=?", (euid,)).fetchone(): return
        c.execute("INSERT INTO expenses(uuid,category,amount,note,user_id,created_at) VALUES(?,?,?,?,?,?)",
                  (euid, p.get("category") or "General", float(p.get("amount") or 0), p.get("note", ""), None, utcnow()))
    # TRANSFER_*: hub has no transfer tables — events stay durable in sync_events

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

# ---------- Shifts (till open/close + cash reconciliation) ----------
@app.get("/api/shifts")
@need_admin
def shifts_admin():
    return jsonify(rows(db(), """SELECT s.*, d.device_name FROM shifts s
        LEFT JOIN devices d ON d.id=s.device_id ORDER BY s.id DESC LIMIT 50"""))

@app.get("/api/v1/shifts")
@need_device
def shift_list():
    return jsonify(rows(db(), "SELECT * FROM shifts WHERE device_id=? ORDER BY id DESC LIMIT 30", (request.device["id"],)))

@app.get("/api/v1/shifts/current")
@need_device
def shift_current():
    s = db().execute("SELECT * FROM shifts WHERE device_id=? AND status='OPEN' ORDER BY id DESC LIMIT 1",
                     (request.device["id"],)).fetchone()
    return jsonify({"shift": dict(s) if s else None})

@app.post("/api/v1/shifts/open")
@need_device
def shift_open():
    d = request.device; c = db(); j = request.json or {}
    if c.execute("SELECT 1 FROM shifts WHERE device_id=? AND status='OPEN'", (d["id"],)).fetchone():
        return jsonify({"error": "shift already open"}), 400
    fl = float(j.get("float") or 0)
    c.execute("""INSERT INTO shifts(device_id,cashier_name,business_id,branch_id,opened_at,opening_float,status)
                 VALUES(?,?,?,?,?,?,'OPEN')""",
              (d["id"], j.get("cashier_name") or d["device_name"], d["business_id"], d["branch_id"], utcnow(), fl))
    audit(c, "shift.opened", f"{d['device_name']} float {fl}")
    c.commit(); return jsonify({"ok": True})

@app.post("/api/v1/shifts/close")
@need_device
def shift_close():
    d = request.device; c = db(); j = request.json or {}
    s = c.execute("SELECT * FROM shifts WHERE device_id=? AND status='OPEN' ORDER BY id DESC LIMIT 1",
                  (d["id"],)).fetchone()
    if not s: return jsonify({"error": "no open shift"}), 400
    count = float(j.get("count") or 0)
    cash_moves = c.execute(
        """SELECT COALESCE(SUM(CASE kind WHEN 'in' THEN amount ELSE -amount END),0) t
           FROM cash_movements WHERE shift_id=?""", (s["id"],)).fetchone()["t"] or 0
    expected = round((s["opening_float"] or 0) + cash_moves + (c.execute(
        """SELECT COALESCE(SUM(p.amount),0) t FROM payments p JOIN sales s2 ON s2.id=p.sale_id
           WHERE p.method='cash' AND s2.status='completed' AND s2.device_id=? AND s2.created>=?""",
        (d["id"], s["opened_at"])).fetchone()["t"] or 0), 2)
    diff = round(count - expected, 2)
    c.execute("""UPDATE shifts SET closed_at=?,closing_count=?,expected_cash=?,difference=?,status='CLOSED' WHERE id=?""",
              (utcnow(), count, expected, diff, s["id"]))
    audit(c, "shift.closed", f"{d['device_name']} expected {expected} counted {count} diff {diff}")
    c.commit()
    return jsonify({"ok": True, "expected": expected, "counted": count, "difference": diff})

@app.post("/api/v1/shifts/cash-move")
@need_device
def shift_cash_move():
    """Petty cash in/out against the device's open shift — counted in expected_cash."""
    d = request.device; c = db(); j = request.json or {}
    s = c.execute("SELECT * FROM shifts WHERE device_id=? AND status='OPEN' ORDER BY id DESC LIMIT 1",
                  (d["id"],)).fetchone()
    if not s: return jsonify({"error": "no open shift"}), 400
    kind = j.get("kind")
    if kind not in ("in", "out"): return jsonify({"error": "kind must be in|out"}), 400
    amount = float(j.get("amount") or 0)
    if amount <= 0: return jsonify({"error": "amount must be positive"}), 400
    uname = j.get("cashier_name") or d["device_name"]
    c.execute("INSERT INTO cash_movements(shift_id,device_id,kind,amount,note,user_name,created_at) VALUES(?,?,?,?,?,?,?)",
              (s["id"], d["id"], kind, round(amount, 2), j.get("note", ""), uname, utcnow()))
    audit(c, "shift.cash_move", f"{d['device_name']} {kind} {amount} · {j.get('note','')}")
    c.commit(); return jsonify({"ok": True})

@app.get("/api/v1/shifts/cash-moves")
@need_device
def shift_cash_moves():
    s = db().execute("SELECT * FROM shifts WHERE device_id=? AND status='OPEN' ORDER BY id DESC LIMIT 1",
                     (request.device["id"],)).fetchone()
    if not s: return jsonify([])
    return jsonify(rows(db(), "SELECT kind,amount,note,user_name,created_at FROM cash_movements WHERE shift_id=? ORDER BY id", (s["id"],)))

@app.get("/api/customers")
@need_login
def customers_list():
    return jsonify(rows(db(), "SELECT id,name,phone,balance FROM customers ORDER BY name"))

@app.post("/api/customers/<int:cid>/pay")
@need_login
def customer_pay(cid):
    """Receive a payment against a customer's outstanding credit balance."""
    c = db(); j = request.json or {}
    cust = c.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    if not cust: return jsonify({"error": "not found"}), 404
    amount = round(float(j.get("amount") or 0), 2)
    if amount <= 0: return jsonify({"error": "amount must be positive"}), 400
    c.execute("INSERT INTO credit_payments(uuid,customer_id,sale_id,kind,amount,note,created_at) VALUES(?,?,?,?,?,?,?)",
              (str(uuid.uuid4()), cid, None, "payment", amount, j.get("note", ""), utcts()))
    c.execute("UPDATE customers SET balance=MAX(0,balance-?) WHERE id=?", (amount, cid))
    audit(c, "customer.credit_payment", f"{cust['name']} paid {amount}")
    c.commit()
    return jsonify({"ok": True, "balance": round(max(0.0, (cust["balance"] or 0) - amount), 2)})

@app.get("/api/customers/<int:cid>/ledger")
@need_login
def customer_ledger(cid):
    return jsonify(rows(db(), """SELECT kind,amount,note,created_at FROM credit_payments
        WHERE customer_id=? ORDER BY id DESC LIMIT 100""", (cid,)))

@app.route("/api/v1/customers", methods=["GET", "POST"])
@need_device
def device_customers():
    c = db()
    if request.method == "POST":
        j = request.json or {}
        if not (j.get("name") or "").strip(): return jsonify({"error": "name required"}), 400
        c.execute("INSERT INTO customers(name,phone,created_at) VALUES(?,?,?)",
                  (j["name"].strip(), (j.get("phone") or "").strip(), utcnow()))
        c.commit(); return jsonify({"ok": True, "id": c.execute("SELECT last_insert_rowid()").fetchone()[0]})
    return jsonify(rows(c, "SELECT id,name,phone,balance FROM customers ORDER BY name"))

@app.route("/api/promos", methods=["GET", "POST"])
@need_admin
def promos():
    c = db()
    if request.method == "POST":
        j = request.json or {}
        try:
            c.execute("INSERT INTO promos(code,kind,value,min_total,active,created_at) VALUES(?,?,?,?,1,?)",
                      ((j.get("code") or "").strip().upper(), j.get("kind", "pct"),
                       float(j.get("value") or 0), float(j.get("min_total") or 0), utcnow()))
        except sqlite3.IntegrityError:
            return jsonify({"error": "That promo code already exists"}), 400
        c.commit(); return jsonify({"ok": True})
    return jsonify(rows(c, "SELECT * FROM promos ORDER BY id DESC"))

@app.post("/api/promos/<int:pid>/delete")
@need_admin
def promo_del(pid):
    c = db(); c.execute("UPDATE promos SET active=0 WHERE id=?", (pid,)); c.commit()
    return jsonify({"ok": True})

@app.get("/api/v1/promos")
@need_device
def device_promos():
    return jsonify(rows(db(), "SELECT code,kind,value,min_total FROM promos WHERE active=1"))

@app.get("/api/v1/settings")
@need_device
def device_settings():
    """Till-relevant settings for devices — tax rate drives offline VAT math."""
    s = {r["k"]: r["v"] for r in db().execute("SELECT * FROM settings")}
    return jsonify({"tax_rate": float(s.get("tax_rate") or 0), "currency": s.get("currency") or "KSh ",
                    "store_name": s.get("store_name") or ""})

# ---------- Synchronization (§8) ----------
@app.get("/api/sync/conflicts")
@need_admin
def conflicts_list():
    return jsonify(rows(db(), """SELECT * FROM sync_conflicts WHERE resolved=0 ORDER BY id DESC LIMIT 200"""))

@app.post("/api/sync/conflicts/<int:cid>/resolve")
@need_admin
def conflict_resolve(cid):
    c = db()
    if not c.execute("SELECT 1 FROM sync_conflicts WHERE id=?", (cid,)).fetchone():
        return jsonify({"error": "not found"}), 404
    c.execute("UPDATE sync_conflicts SET resolved=1 WHERE id=?", (cid,))
    audit(c, "sync.conflict_resolved", f"conflict {cid}")
    c.commit(); return jsonify({"ok": True})

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
            c.execute("""INSERT OR IGNORE INTO sync_outbox(event_id,event_type,entity_id,payload,created_at)
                         VALUES(?,?,?,?,?)""",
                      (eid, e["event_type"], str(e.get("entity_id") or ""),
                       json.dumps(e.get("payload") or {}), utcnow()))  # relay device → cloud
            accepted.append({"event_id": eid, "server_sequence": r[0]})
            try:
                apply_incoming_event(c, dev, e)
            except Exception as ex:  # event is durable — record, don't lose it
                _conflict(c, e, "apply_failed", {"error": str(ex)[:300], "event_type": e["event_type"]})
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
    if not (dev or "uid" in session): return jsonify({"error": "auth"}), 401
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
    with urllib.request.urlopen(req, json.dumps(payload).encode() if payload is not None else None, timeout=120) as r:
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
    if not pending:  # still pull — cloud/web events arrive even when outbox is empty
        pulled = _cloud_pull(c); c.commit()
        return jsonify({"ok": True, "pushed": 0, "pulled": pulled})
    def _ent(v):  # cloud sync_events.entity_id is uuid-typed — coerce local refs
        s = str(v or "")
        try: uuid.UUID(s); return s
        except ValueError: return str(uuid.uuid5(uuid.NAMESPACE_DNS, s)) if s else None
    events = [{"event_id": p["event_id"], "event_type": p["event_type"], "entity_id": _ent(p["entity_id"]),
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
        if c.execute("SELECT 1 FROM sync_events WHERE event_id=?", (e["event_id"],)).fetchone():
            cur = max(cur, e["server_sequence"]); continue  # our own events echo back — skip
        # The cloud's server_sequence is a different counter domain — allocate a
        # local sequence or LAN devices past that cursor would never see the event.
        seq = c.execute("UPDATE sync_streams SET next_sequence=next_sequence+1 WHERE branch_id=? RETURNING next_sequence-1",
                        (DEFAULT_BRANCH,)).fetchone()
        if not seq:
            c.execute("INSERT INTO sync_streams(branch_id,next_sequence) VALUES(?,2)", (DEFAULT_BRANCH,)); seq = (1,)
        payload = dict(e.get("payload") or {}); payload["_cloud_seq"] = e["server_sequence"]
        ins = c.execute("""INSERT OR IGNORE INTO sync_events(event_id,business_id,branch_id,device_id,
            device_sequence,event_type,schema_version,entity_id,device_created_at,payload,
            server_received_at,server_sequence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (e["event_id"], DEFAULT_BUSINESS, DEFAULT_BRANCH, str(e.get("device_id") or ""),
             e.get("device_sequence"), e["event_type"], e.get("schema_version", 1),
             e.get("entity_id"), e.get("device_created_at"), json.dumps(payload),
             e.get("server_received_at"), seq[0]))
        if ins.rowcount:
            try:
                apply_incoming_event(c, {"id": e.get("device_id"), "device_name": "cloud",
                                         "business_id": DEFAULT_BUSINESS, "branch_id": DEFAULT_BRANCH},
                                     {**e, "payload": payload})
            except Exception as ex:
                _conflict(c, e, "apply_failed", {"error": str(ex)[:300], "event_type": e.get("event_type")})
        n += ins.rowcount or 0
        cur = max(cur, e["server_sequence"])
    c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES('cloud_pull_seq',?)", (str(cur),))
    return n

# ---------- Backup & diagnostics (§15) ----------
@app.get("/api/admin/backup")
@need_admin
def backup():
    import tempfile
    from flask import send_file, after_this_request
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    src = db(); dst = sqlite3.connect(tmp.name); src.backup(dst); dst.close(); src.close()
    ac = db(); audit(ac, "admin.backup", "snapshot"); ac.commit(); ac.close()
    @after_this_request
    def _cleanup(response):
        try: os.remove(tmp.name)  # fd is already open — unlink is safe on POSIX
        except OSError: pass
        return response
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
