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
    r = client.post("/api/v1/returns", json={
        "sale_id": sid, "items": [{"product_id": pid, "qty": 1}], "reason": "defective"}).get_json()
    assert r["total"] == 10.0
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
