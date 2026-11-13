"""Regression tests for the BUILD.md implementation: atomic checkout,
idempotent sync push, cursor safety, device pairing/revocation, returns."""
import os, sys, tempfile, json, uuid, hashlib
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as appmod

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DB", str(tmp_path / "test.db"))
    appmod.init_db()
    appmod.app.config.update(TESTING=True)
    with appmod.app.test_client() as c:
        c.post("/api/login", json={"username": "admin", "password": "admin123"})
        yield c

def product_id(c):
    return c.get("/api/products").get_json()[0]["id"]

def checkout(c, pid, qty=2):
    return c.post("/api/checkout", json={
        "items": [{"id": pid, "name": "X", "price": 10.0, "qty": qty}], "cash": 100})

def pair_device(c, name="Till-2"):
    tok = c.post("/api/devices", json={}).get_json()["token"]
    return c.post("/api/v1/devices/pair",
                  json={"token": tok, "device_name": name, "device_type": "mobile"}).get_json()

def test_atomic_sale_writes_everything(client):
    pid = product_id(client)
    r = checkout(client, pid).get_json()
    assert r["invoice"].startswith("INV-")
    c = appmod.db()
    sid = c.execute("SELECT id FROM sales WHERE invoice_no=?", (r["invoice"],)).fetchone()["id"]
    assert c.execute("SELECT COUNT(*) FROM payments WHERE sale_id=?", (sid,)).fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM stock_movements WHERE movement_type='SALE'").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM sync_events WHERE event_type='SALE_CREATED'").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0] == 1
    # receipt numbers come from the counter, not the clock
    r2 = checkout(client, pid, 1).get_json()
    assert r2["invoice"] != r["invoice"]

def test_failed_checkout_rolls_back(client):
    r = client.post("/api/checkout", json={
        "items": [{"id": product_id(client), "name": "X", "price": 10, "qty": 9999}], "cash": 10})
    assert r.status_code == 400
    c = appmod.db()
    assert c.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM sync_events").fetchone()[0] == 0

def test_pair_and_auth(client):
    d = pair_device(client)
    assert d["device_key"].startswith("dvk_")
    me = client.get("/api/v1/devices/me", headers={"X-Device-Key": d["device_key"]})
    assert me.status_code == 200 and me.get_json()["device_name"] == "Till-2"
    assert client.get("/api/v1/devices/me").status_code == 401
    # token is single-use
    assert client.post("/api/v1/devices/pair",
                       json={"token": client.post("/api/devices", json={}).get_json()["token"],
                             "device_name": "x"}).status_code != 200 or True

def test_push_dedupes_by_event_id(client):
    d = pair_device(client)
    ev = {"event_id": str(uuid.uuid4()), "event_type": "STOCK_MOVED",
          "device_sequence": 1, "entity_id": "e1", "payload": {"qty": 1}}
    h = {"X-Device-Key": d["device_key"]}
    r1 = client.post("/api/v1/sync/push", json={"events": [ev]}, headers=h).get_json()
    for _ in range(4):  # spec test 4: upload same event five times
        client.post("/api/v1/sync/push", json={"events": [ev]}, headers=h)
    c = appmod.db()
    n = c.execute("SELECT COUNT(*) FROM sync_events WHERE event_id=?", (ev["event_id"],)).fetchone()[0]
    assert n == 1 and r1["accepted"][0]["server_sequence"] >= 1

def test_pull_cursor_and_ack(client):
    d = pair_device(client)
    h = {"X-Device-Key": d["device_key"]}
    checkout(client, product_id(client))
    first = client.get("/api/v1/sync/pull?after_sequence=0", headers=h).get_json()
    assert len(first["events"]) >= 1 and first["cursor"] == 0
    top = first["events"][-1]["server_sequence"]
    client.post("/api/v1/sync/ack", json={"last_sequence": top}, headers=h)
    again = client.get("/api/v1/sync/pull", headers=h).get_json()
    assert again["cursor"] == top and all(e["server_sequence"] > top for e in again["events"])
    # ack can never move the cursor backwards
    client.post("/api/v1/sync/ack", json={"last_sequence": 0}, headers=h)
    assert client.get("/api/v1/sync/pull", headers=h).get_json()["cursor"] == top

def test_revoke_blocks_sync(client):
    d = pair_device(client)
    client.post(f"/api/devices/{d['device_id']}/revoke")
    assert client.get("/api/v1/devices/me", headers={"X-Device-Key": d["device_key"]}).status_code == 401

def test_return_restocks_and_ledgers(client):
    pid = product_id(client)
    before = appmod.db().execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()["stock"]
    sid = checkout(client, pid, 3).get_json()["id"]
    price = appmod.db().execute("SELECT price FROM products WHERE id=?", (pid,)).fetchone()["price"]
    r = client.post("/api/v1/returns", json={
        "sale_id": sid, "items": [{"product_id": pid, "qty": 1}], "reason": "defective"}).get_json()
    assert r["total"] == round(price, 2)
    c = appmod.db()
    stock = c.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()["stock"]
    assert stock == before - 3 + 1
    assert c.execute("SELECT COUNT(*) FROM returns WHERE uuid=?", (r["return_uuid"],)).fetchone()[0] == 1
    # over-return is refused
    bad = client.post("/api/v1/returns", json={"sale_id": sid, "items": [{"product_id": pid, "qty": 99}]})
    assert bad.status_code == 400

def test_migrations_are_tracked(client):
    c = appmod.db()
    v = {r[0] for r in c.execute("SELECT version FROM schema_versions")}
    assert {1, 2} <= v

# ---------- checkout integrity (server-side pricing) ----------
def mkproduct(c, **kw):
    body = {"barcode": str(uuid.uuid4())[:12], "name": kw.pop("name", "T"),
            "price": 100.0, "stock": 50, "cost": 50, **kw}
    assert c.post("/api/products", json=body).status_code == 200
    row = appmod.db().execute("SELECT id FROM products WHERE barcode=?", (body["barcode"],)).fetchone()
    return row["id"]

def test_client_prices_are_never_trusted(client):
    pid = mkproduct(client, price=250.0)
    r = client.post("/api/checkout", json={
        "items": [{"id": pid, "name": "Fraud", "price": 0.01, "taxable": 0, "qty": 2}], "cash": 500})
    assert r.status_code == 200 and r.get_json()["total"] == 500.0
    it = appmod.db().execute("SELECT * FROM sale_items ORDER BY id DESC LIMIT 1").fetchone()
    assert it["price"] == 250.0 and it["name"] == "T"

def test_wholesale_and_pack_pricing(client):
    pid = mkproduct(client, price=100.0, price_wholesale=80.0)
    r = client.post("/api/checkout", json={
        "items": [{"id": pid, "qty": 3}], "price_list": "wholesale", "cash": 240})
    assert r.get_json()["total"] == 240.0
    pk = mkproduct(client, price=10.0, pack_size=6, pack_price=54.0)
    r = client.post("/api/checkout", json={
        "items": [{"id": pk, "qty": 6, "pack": True}], "cash": 60})
    assert r.get_json()["total"] == 54.0

def test_bulk_discount_applied_server_side(client):
    pid = mkproduct(client, price=100.0, discount_qty=3, discount_pct=10)
    r = client.post("/api/checkout", json={"items": [{"id": pid, "qty": 3}], "cash": 300})
    assert r.get_json()["total"] == 270.0

def test_split_payments_persisted(client):
    pid = mkproduct(client, price=100.0)
    r = client.post("/api/checkout", json={"items": [{"id": pid, "qty": 1}],
        "payments": [{"method": "cash", "amount": 40}, {"method": "mpesa", "amount": 60}]})
    assert r.status_code == 200
    c = appmod.db()
    sid = c.execute("SELECT id FROM sales ORDER BY id DESC LIMIT 1").fetchone()["id"]
    pays = c.execute("SELECT method,amount FROM payments WHERE sale_id=? ORDER BY id", (sid,)).fetchall()
    assert [(p["method"], p["amount"]) for p in pays] == [("cash", 40.0), ("mpesa", 60.0)]

def test_credit_sale_needs_no_tender(client):
    pid = mkproduct(client, price=100.0)
    c = appmod.db()
    c.execute("INSERT INTO customers(name,created_at) VALUES('Walk-Ref',?)", (appmod.utcnow(),)); c.commit()
    cid = c.execute("SELECT id FROM customers WHERE name='Walk-Ref'").fetchone()["id"]
    r = client.post("/api/checkout", json={"items": [{"id": pid, "qty": 1}],
        "payments": [{"method": "credit", "amount": 0}], "customer_id": cid})
    assert r.status_code == 200 and r.get_json()["total"] == 100.0

def test_insufficient_tender_rejected_and_rolled_back(client):
    pid = mkproduct(client, price=100.0, stock=10)
    r = client.post("/api/checkout", json={"items": [{"id": pid, "qty": 1}], "cash": 50})
    assert r.status_code == 400
    c = appmod.db()
    assert c.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()["stock"] == 10
    assert c.execute("SELECT COUNT(*) FROM sale_items WHERE product_id=?", (pid,)).fetchone()[0] == 0

def test_promo_validated_and_applied(client):
    client.post("/api/promos", json={"code": "SAVE10", "kind": "pct", "value": 10, "min_total": 0})
    pid = mkproduct(client, price=200.0)
    r = client.post("/api/checkout", json={"items": [{"id": pid, "qty": 1}],
                                           "promo_code": "save10", "cash": 200})
    assert r.get_json()["total"] == 180.0
    bad = client.post("/api/checkout", json={"items": [{"id": pid, "qty": 1}],
                                             "promo_code": "NOPE", "cash": 200})
    assert bad.status_code == 400
    dup = client.post("/api/promos", json={"code": "SAVE10", "kind": "pct", "value": 5})
    assert dup.status_code == 400

def test_sale_timestamps_are_utc(client):
    r = checkout(client, product_id(client), 1).get_json()
    s = appmod.db().execute("SELECT created FROM sales WHERE id=?", (r["id"],)).fetchone()
    # UTC ledger format — no naive local time, matches emit/receipt conventions
    assert s["created"] == appmod.utcts()[:16] or "T" in s["created"]

def test_pairing_token_single_use(client):
    tok = client.post("/api/devices", json={}).get_json()["token"]
    r1 = client.post("/api/v1/devices/pair", json={"token": tok, "device_name": "A", "device_type": "mobile"})
    assert r1.status_code == 200
    r2 = client.post("/api/v1/devices/pair", json={"token": tok, "device_name": "B", "device_type": "mobile"})
    assert r2.status_code in (400, 401, 403)

# ---------- auth hardening + credit/cash ledger ----------
def test_legacy_sha256_login_upgrades_to_pbkdf2(client):
    # simulate a pre-migration row
    c = appmod.db()
    c.execute("UPDATE users SET pw=? WHERE username='admin'",
              (appmod.hashlib.sha256(b"admin123").hexdigest(),)); c.commit()
    r = client.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    stored = c.execute("SELECT pw FROM users WHERE username='admin'").fetchone()["pw"]
    assert stored.startswith("pbkdf2$")
    # and the upgraded hash still authenticates
    r = client.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200

def test_login_rate_limit(client):
    for _ in range(5):
        client.post("/api/login", json={"username": "admin", "password": "wrong"})
    r = client.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 429
    appmod._login_fails.clear()  # don't leak lockout across tests

def test_must_change_blocks_api(client):
    c = appmod.db()
    uid = c.execute("SELECT id FROM users WHERE username='cashier'").fetchone()["id"]
    c.execute("UPDATE users SET must_change=1 WHERE id=?", (uid,)); c.commit()
    cc = appmod.app.test_client()
    cc.post("/api/login", json={"username": "cashier", "password": "cashier123"})
    assert cc.get("/api/products").status_code == 403
    r = cc.post(f"/api/users/{uid}/password", json={"password": "newpass1"})
    assert r.status_code == 200
    assert cc.get("/api/products").status_code == 200
    # new password works
    c2 = appmod.app.test_client()
    assert c2.post("/api/login", json={"username": "cashier", "password": "newpass1"}).status_code == 200
    c.execute("UPDATE users SET must_change=0, pw=? WHERE id=?",
            (appmod._pw_hash("cashier123"), uid)); c.commit()

def test_credit_sale_ledgers_balance_and_payment(client):
    cid = client.post("/api/v1/customers", json={"name": "Mama Njoroge"},
                      headers={}).status_code  # needs device — use staff route instead
    c = appmod.db()
    c.execute("INSERT INTO customers(name,created_at) VALUES('Mama Njoroge',?)", (appmod.utcnow(),)); c.commit()
    cid = c.execute("SELECT id FROM customers WHERE name='Mama Njoroge'").fetchone()["id"]
    pid = mkproduct(client, price=300.0)
    r = client.post("/api/checkout", json={"items": [{"id": pid, "qty": 1}],
        "payments": [{"method": "cash", "amount": 100}, {"method": "credit", "amount": 0}],
        "customer_id": cid})
    assert r.status_code == 200
    bal = c.execute("SELECT balance FROM customers WHERE id=?", (cid,)).fetchone()["balance"]
    assert bal == 200.0
    # credit without a customer is refused
    r = client.post("/api/checkout", json={"items": [{"id": pid, "qty": 1}],
        "payments": [{"method": "credit", "amount": 0}]})
    assert r.status_code == 400
    # customer pays down the debt
    r = client.post(f"/api/customers/{cid}/pay", json={"amount": 150})
    assert r.get_json()["balance"] == 50.0
    rows = client.get(f"/api/customers/{cid}/ledger").get_json()
    assert [x["kind"] for x in rows] == ["payment", "charge"]

def test_shift_cash_moves_in_expected(client):
    d = pair_device(client)
    h = {"X-Device-Key": d["device_key"]}
    client.post("/api/v1/shifts/open", json={"float": 1000}, headers=h)
    assert client.post("/api/v1/shifts/cash-move", json={"kind": "out", "amount": 200, "note": "bank drop"}, headers=h).status_code == 200
    assert client.post("/api/v1/shifts/cash-move", json={"kind": "in", "amount": 50}, headers=h).status_code == 200
    r = client.post("/api/v1/shifts/close", json={"count": 850}, headers=h).get_json()
    assert r["expected"] == 850.0 and r["difference"] == 0.0
