#!/usr/bin/env python3
"""POS & Inventory Management System — Flask + SQLite."""
import sqlite3, hashlib, secrets, json, os
from datetime import datetime, date
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
    u = db().execute("SELECT * FROM users WHERE username=? AND pw=?", (d["username"], h)).fetchone()
    if not u: return jsonify({"error": "Invalid username or password"}), 401
    session.update(uid=u["id"], name=u["name"], role=u["role"])
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
    c.commit(); return jsonify({"ok": True})

@app.put("/api/products/<int:pid>")
@need_admin
def product_edit(pid):
    d = request.json; c = db()
    c.execute("UPDATE products SET barcode=?,name=?,category_id=?,brand_id=?,price=?,stock=?,cost=?,taxable=?,discount_qty=?,discount_pct=?,expiry=?,image=? WHERE id=?",
              (d["barcode"], d["name"], d.get("category_id"), d.get("brand_id"), d["price"], d["stock"], d.get("cost",0), d.get("taxable",1), d.get("discount_qty",0), d.get("discount_pct",0), d.get("expiry") or None, d.get("image") or None, pid))
    c.commit(); return jsonify({"ok": True})

@app.delete("/api/products/<int:pid>")
@need_admin
def product_del(pid):
    c = db(); c.execute("DELETE FROM products WHERE id=?", (pid,)); c.commit(); return jsonify({"ok": True})

@app.post("/api/products/import")
@need_admin
def products_import():
    import csv, io
    rdr = csv.DictReader(io.StringIO(request.json.get("csv", "")))
    c = db(); created = updated = skipped = 0; errors = []
    def lk(table, name):
        name = (name or "").strip()
        if not name: return None
        r = c.execute(f"SELECT id FROM {table} WHERE name=?", (name,)).fetchone()
        if r: return r["id"]
        c.execute(f"INSERT INTO {table}(name) VALUES(?)", (name,))
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]
    for n, raw in enumerate(rdr, 2):
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
            if bc and c.execute("SELECT 1 FROM products WHERE barcode=?", (bc,)).fetchone():
                c.execute("""UPDATE products SET name=?,category_id=?,brand_id=?,price=?,stock=?,cost=?,taxable=?,discount_qty=?,discount_pct=?,expiry=?,image=COALESCE(?,image) WHERE barcode=?""",
                          (name, vals[2], vals[3], price, vals[5], vals[6], vals[7], vals[8], vals[9], vals[10], vals[11], bc))
                updated += 1
            else:
                c.execute("""INSERT INTO products(barcode,name,category_id,brand_id,price,stock,cost,taxable,discount_qty,discount_pct,expiry,image)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", vals)
                created += 1
        except Exception as e:
            skipped += 1; errors.append(f"row {n}: {e}")
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
    rate = float(c.execute("SELECT v FROM settings WHERE k='tax_rate'").fetchone()["v"] or 0)
    vat = total = gross = 0.0
    for i in items:
        p2 = c.execute("SELECT taxable,discount_qty,discount_pct,stock,name FROM products WHERE id=?", (i["id"],)).fetchone()
        if not p2 or p2["stock"] < i["qty"]:
            return jsonify({"error": f"Not enough stock: {p2['name'] if p2 else i['id']}"}), 400
        gross += i["price"] * i["qty"]
        line = round(i["price"] * i["qty"] * (1 - (p2["discount_pct"] or 0) / 100 if p2["discount_qty"] and i["qty"] >= p2["discount_qty"] else 1), 2)
        i["line_total"] = line
        total += line
        if p2["taxable"]:
            vat += round(line * rate / (100 + rate), 2)  # VAT-inclusive pricing
    total = round(total, 2)
    cash = round(float(d.get("cash", total)), 2)
    if cash < total: return jsonify({"error": "Insufficient cash"}), 400
    inv = "INV-" + datetime.now().strftime("%y%m%d%H%M%S")
    c.execute("INSERT INTO sales(invoice_no,total,cash,change_due,vat,discount,user_id,created) VALUES(?,?,?,?,?,?,?,?)",
              (inv, total, cash, round(cash - total, 2), round(vat, 2), round(gross - total, 2), session["uid"], datetime.now().isoformat(timespec="seconds")))
    sid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    for i in items:
        c.execute("INSERT INTO sale_items(sale_id,product_id,name,price,qty,total) VALUES(?,?,?,?,?,?)",
                  (sid, i["id"], i["name"], i["price"], i["qty"], i["line_total"]))
        c.execute("UPDATE products SET stock=stock-? WHERE id=?", (i["qty"], i["id"]))
    c.commit()
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
    return jsonify(rows(c, """SELECT s.*, u.name cashier, (SELECT COUNT(*) FROM sale_items si WHERE si.sale_id=s.id) items
        FROM sales s LEFT JOIN users u ON u.id=s.user_id WHERE date(s.created)=? ORDER BY s.id DESC""", (d,)))

@app.post("/api/sales/<int:sid>/void")
@need_admin
def sale_void(sid):
    c = db()
    s = c.execute("SELECT * FROM sales WHERE id=? AND status='completed'", (sid,)).fetchone()
    if not s: return jsonify({"error": "Sale not found or already void"}), 400
    c.execute("UPDATE sales SET status='void' WHERE id=?", (sid,))
    for i in c.execute("SELECT product_id,qty FROM sale_items WHERE sale_id=?", (sid,)):
        c.execute("UPDATE products SET stock=stock+? WHERE id=?", (i["qty"], i["product_id"]))
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
    kind = "in" if float(d["qty"]) >= 0 else "adjust"
    ref = d.get("ref_no") or ("STK-" + datetime.now().strftime("%y%m%d%H%M%S"))
    c.execute("INSERT INTO stock_entries(ref_no,product_id,qty,kind,note,supplier_id,created) VALUES(?,?,?,?,?,?,?)",
              (ref, d["product_id"], d["qty"], kind, d.get("note",""), d.get("supplier_id"), datetime.now().isoformat(timespec="seconds")))
    c.execute("UPDATE products SET stock=stock+? WHERE id=?", (d["qty"], d["product_id"]))
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
@app.get("/api/reports")
@need_login
def reports():
    d = request.args.get("date", date.today().isoformat()); c = db()
    return jsonify({
        "daily": rows(c, """SELECT s.invoice_no, s.total, s.status, s.created, u.name cashier FROM sales s
            LEFT JOIN users u ON u.id=s.user_id WHERE date(s.created)=? ORDER BY s.id DESC""", (d,)),
        "top": rows(c, """SELECT si.name, SUM(si.qty) qty, SUM(si.total) revenue FROM sale_items si
            JOIN sales s ON s.id=si.sale_id WHERE s.status='completed' GROUP BY si.product_id ORDER BY qty DESC LIMIT 8"""),
        "totals": dict(c.execute("""SELECT COALESCE(SUM(total),0) total, COUNT(*) orders FROM sales
            WHERE date(created)=? AND status='completed'""", (d,)).fetchone()),
    })

@app.get("/api/dashboard")
@need_login
def dashboard():
    c = db(); t = date.today().isoformat()
    return jsonify({
        "today": dict(c.execute("SELECT COALESCE(SUM(total),0) revenue, COUNT(*) orders FROM sales WHERE date(created)=? AND status='completed'", (t,)).fetchone()),
        "products": c.execute("SELECT COUNT(*) n FROM products").fetchone()["n"],
        "stock_value": dict(c.execute("SELECT COALESCE(SUM(stock*cost),0) v FROM products").fetchone()),
        "low_stock": rows(c, "SELECT id,name,stock FROM products WHERE stock<=10 ORDER BY stock LIMIT 6"),
        "expiring": rows(c, """SELECT id,name,expiry,stock FROM products WHERE expiry IS NOT NULL AND expiry!=''
            AND date(expiry)<=date('now','+30 days') ORDER BY expiry LIMIT 6"""),
        "recent": rows(c, """SELECT s.invoice_no,s.total,s.created,s.status,u.name cashier FROM sales s
            LEFT JOIN users u ON u.id=s.user_id ORDER BY s.id DESC LIMIT 6"""),
        "top": rows(c, """SELECT si.name, SUM(si.qty) qty FROM sale_items si JOIN sales s ON s.id=si.sale_id
            WHERE s.status='completed' GROUP BY si.product_id ORDER BY qty DESC LIMIT 5"""),
    })

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
        c.commit(); return jsonify({"ok": True})
    return jsonify(rows(c, "SELECT id,username,name,role FROM users ORDER BY id"))

@app.delete("/api/users/<int:uid>")
@need_admin
def user_del(uid):
    if uid == session["uid"]: return jsonify({"error": "Can't delete yourself"}), 400
    c = db(); c.execute("DELETE FROM users WHERE id=?", (uid,)); c.commit(); return jsonify({"ok": True})

@app.post("/api/users/<int:uid>/password")
@need_login
def user_pw(uid):
    if uid != session["uid"] and session.get("role") != "admin": return jsonify({"error": "forbidden"}), 403
    c = db(); c.execute("UPDATE users SET pw=?, must_change=0 WHERE id=?", (hashlib.sha256(request.json["password"].encode()).hexdigest(), uid)); c.commit()
    return jsonify({"ok": True})

@app.route("/api/settings", methods=["GET", "PUT"])
@need_login
def settings():
    c = db()
    if request.method == "PUT":
        if session.get("role") != "admin": return jsonify({"error": "admin only"}), 403
        for k, v in request.json.items(): c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, str(v)))
        c.commit()
    return jsonify({r["k"]: r["v"] for r in c.execute("SELECT * FROM settings")})

if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5050, debug=False)
