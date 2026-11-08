#!/usr/bin/env python3
"""ShujaaPOS cloud API (BUILD.md Phase 5) — event ingestion into Supabase.

Mirrors the hub sync contract: POST /api/v1/sync/push, GET /api/v1/sync/pull,
POST /api/v1/sync/ack, GET /api/v1/sync/status. Hub authenticates with
X-Hub-Key; Supabase is reached via PostgREST with the service key — which
never leaves this process (§4.3).
"""
import os, json, urllib.request, urllib.error, uuid, time
import uuid, time
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from functools import wraps

app = Flask(__name__, static_folder="web", static_url_path="")
URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HUB_KEY = os.environ.get("CLOUD_API_KEY", "change-me")

def utcnow(): return datetime.now(timezone.utc).isoformat(timespec="seconds")

def pg(method, path, data=None, params=""):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}{params}", method=method,
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                 "Content-Type": "application/json", "Prefer": "return=representation"})
    try:
        with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None) as r:
            body = r.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "detail": e.read().decode()[:400]}

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Hub-Key"
    r.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return r

@app.route("/api/<path:p>", methods=["OPTIONS"])
def _opt(p): return ("", 204)

def authed_user():
    """Verify a Supabase user JWT via GoTrue → auth user dict or None."""
    tok = (request.headers.get("Authorization") or "").replace("Bearer ", "")
    if not tok: return None
    req = urllib.request.Request(f"{URL}/auth/v1/user",
        headers={"apikey": KEY, "Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req) as r: return json.loads(r.read())
    except Exception: return None

@app.get("/api/me")
def me():
    u = authed_user()
    if not u: return jsonify({"error": "unauthorized"}), 401
    ms = pg("GET", "business_memberships",
            params=f"?user_id=eq.{u['id']}&select=role,businesses(name,id)")
    if isinstance(ms, dict) and ms.get("_error"): return jsonify({"error": "server"}), 500
    return jsonify({"email": u.get("email"), "id": u["id"], "memberships": ms or []})

@app.post("/api/onboarding")
def onboarding():
    """First-run tenant creation: business + branch + admin membership."""
    u = authed_user()
    if not u: return jsonify({"error": "unauthorized"}), 401
    existing = pg("GET", "business_memberships", params=f"?user_id=eq.{u['id']}&select=business_id&limit=1")
    if existing: return jsonify({"error": "already onboarded"}), 409
    j = request.json or {}
    name = (j.get("business_name") or "").strip()
    if not name: return jsonify({"error": "business name required"}), 400
    uid = u["id"]
    pg("POST", "profiles", {"id": uid,
        "display_name": (u.get("user_metadata") or {}).get("full_name") or u.get("email")})
    biz = pg("POST", "businesses", {"name": name})
    if isinstance(biz, dict) and biz.get("_error"): return jsonify(biz), 500
    bid = biz[0]["id"]
    br = pg("POST", "branches", {"business_id": bid, "name": (j.get("branch_name") or "Main").strip()})
    if isinstance(br, dict) and br.get("_error"): return jsonify(br), 500
    brid = br[0]["id"]
    pg("POST", "business_memberships", {"business_id": bid, "user_id": uid, "role": "admin"})
    pg("POST", "branch_memberships", {"business_id": bid, "branch_id": brid, "user_id": uid})
    return jsonify({"ok": True, "business_id": bid, "branch_id": brid})

@app.post("/api/branches")
def add_branch():
    """Create a branch — caller must hold an admin membership in that business."""
    u = authed_user()
    if not u: return jsonify({"error": "unauthorized"}), 401
    j = request.json or {}
    bid, name = j.get("business_id"), (j.get("name") or "").strip()
    if not bid or not name: return jsonify({"error": "branch name required"}), 400
    ms = pg("GET", "business_memberships",
            params=f"?user_id=eq.{u['id']}&business_id=eq.{bid}&role=eq.admin&select=role&limit=1")
    if not ms: return jsonify({"error": "admin only"}), 403
    br = pg("POST", "branches", {"business_id": bid, "name": name, "address": j.get("address")})
    if isinstance(br, dict) and br.get("_error"): return jsonify(br), 500
    pg("POST", "branch_memberships", {"business_id": bid, "branch_id": br[0]["id"], "user_id": u["id"]})
    return jsonify({"ok": True, "branch": br[0]})

def need_hub(f):
    @wraps(f)
    def w(*a, **k):
        if request.headers.get("X-Hub-Key") != HUB_KEY:
            return jsonify({"error": "bad_hub_key"}), 401
        return f(*a, **k)
    return w

EVENT_TYPES = {"SALE_CREATED","SALE_VOIDED","STOCK_MOVED","PRODUCT_CREATED","PRODUCT_UPDATED",
               "PRODUCT_DELETED","RETURN_POSTED","PURCHASE_RECEIVED","EXPENSE_POSTED",
               "TRANSFER_CREATED","TRANSFER_DISPATCH","TRANSFER_RECEIVE"}

def apply_event(e):
    """Project an accepted event into central records (spec §3 cloud API role).
    Idempotent where the record carries a unique constraint; skipped types are
    kept in sync_events for a later projector."""
    t, p, bid, brid = e["event_type"], e.get("payload") or {}, e["business_id"], e["branch_id"]
    if t == "SALE_CREATED":
        sale = pg("POST", "sales", {"business_id": bid, "branch_id": brid, "device_id": e["device_id"],
            "receipt_number": p.get("invoice_no", e["event_id"][:12]), "subtotal": p.get("total", 0),
            "discount_total": p.get("discount", 0), "tax_total": p.get("vat", 0),
            "total": p.get("total", 0), "created_at": e.get("device_created_at") or utcnow()})
        if isinstance(sale, list) and sale:
            sid = sale[0]["id"]
            for i in p.get("items", []):
                pg("POST", "sale_items", {"sale_id": sid, "business_id": bid,
                    "product_id": i.get("product_uuid") or uuid.uuid5(uuid.NAMESPACE_DNS, str(i.get("product_id"))).hex and str(uuid.uuid5(uuid.NAMESPACE_DNS, str(i.get("product_id")))),
                    "quantity": i.get("qty", 0), "unit_price": i.get("total", 0) / max(i.get("qty", 1), 1),
                    "line_total": i.get("total", 0)})
                pg("POST", "stock_movements", {"business_id": bid, "branch_id": brid,
                    "product_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, str(i.get("product_id")))),
                    "movement_type": "SALE", "quantity_delta": -float(i.get("qty", 0)),
                    "device_id": e["device_id"], "created_at": e.get("device_created_at") or utcnow()})
    elif t == "STOCK_MOVED":
        pu = p.get("product_uuid") or str(uuid.uuid5(uuid.NAMESPACE_DNS, str(p.get("product_id"))))
        pg("POST", "stock_movements", {"business_id": bid, "branch_id": brid, "product_id": pu,
            "movement_type": p.get("movement_type", "STOCK_ADJUSTMENT"), "quantity_delta": p.get("quantity_delta", 0),
            "device_id": e["device_id"], "note": p.get("ref_no", ""), "created_at": e.get("device_created_at") or utcnow()})
        cur = pg("GET", "stock_balances", params=f"?product_id=eq.{pu}&branch_id=eq.{brid}&select=on_hand") or []
        have = (cur[0]["on_hand"] if cur else 0) + float(p.get("quantity_delta", 0))
        pg("POST", "stock_balances", {"business_id": bid, "branch_id": brid, "product_id": pu,
            "on_hand": have, "rebuilt_at": utcnow()}, "?on_conflict=business_id,branch_id,product_id")
    elif t in ("PRODUCT_CREATED", "PRODUCT_UPDATED"):
        pg("POST", "products", {"business_id": bid, "name": p.get("name"), "barcode": p.get("barcode"),
            "selling_price": p.get("price", 0), "cost_price": p.get("cost", 0),
            "id": p.get("product_uuid") or str(uuid.uuid5(uuid.NAMESPACE_DNS, str(p.get("product_id"))))},
            "?on_conflict=id")
    elif t == "SALE_VOIDED":
        pg("PATCH", "sales", {"status": "void"}, f"?receipt_number=eq.{p.get('invoice_no')}&branch_id=eq.{brid}")
    elif t == "RETURN_POSTED":
        for pid_, qty in [(i.get("product_id"), i.get("qty")) for i in p.get("items", [])]:
            pg("POST", "stock_movements", {"business_id": bid, "branch_id": brid,
                "product_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, str(pid_))),
                "movement_type": "SALE_RETURN", "quantity_delta": float(qty or 0),
                "device_id": e["device_id"], "created_at": e.get("device_created_at") or utcnow()})
    elif t == "PURCHASE_RECEIVED":
        for i in p.get("items", []):
            pg("POST", "stock_movements", {"business_id": bid, "branch_id": brid,
                "product_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, str(i.get("product_id")))),
                "movement_type": "PURCHASE_RECEIVED", "quantity_delta": float(i.get("qty", 0)),
                "device_id": e["device_id"], "created_at": e.get("device_created_at") or utcnow()})
    elif t == "TRANSFER_CREATED":
        tr = pg("POST", "stock_transfers", {"business_id": bid, "from_branch_id": brid,
                "to_branch_id": p.get("to_branch") if _is_uuid(p.get("to_branch")) else brid,
                "status": "DRAFT", "note": p.get("note", ""), "id": p.get("transfer_id")})
        tid = tr[0]["id"] if isinstance(tr, list) and tr else p.get("transfer_id")
        for i in p.get("items", []):
            pg("POST", "stock_transfer_items", {"transfer_id": tid,
                "product_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, str(i.get("product_id")))),
                "qty_sent": i.get("qty", 0)})
    elif t == "TRANSFER_DISPATCH":
        tid = p.get("transfer_id") or e.get("entity_id")
        pg("PATCH", "stock_transfers", {"status": "DISPATCHED", "dispatched_at": e.get("device_created_at") or utcnow()},
           f"?id=eq.{tid}")
        items = pg("GET", "stock_transfer_items", params=f"?transfer_id=eq.{tid}&select=product_id,qty_sent") or []
        for i in items:   # TRANSFER_OUT on the dispatching branch (spec §10)
            pg("POST", "stock_movements", {"business_id": bid, "branch_id": brid, "product_id": i["product_id"],
                "movement_type": "TRANSFER_OUT", "quantity_delta": -float(i["qty_sent"]),
                "reference_id": tid, "device_id": e["device_id"], "created_at": e.get("device_created_at") or utcnow()})
    elif t == "TRANSFER_RECEIVE":
        tid = p.get("transfer_id") or e.get("entity_id")
        for r in p.get("receipts", []):
            pu = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(r.get("product_id"))))
            cur = pg("GET", "stock_transfer_items", params=f"?transfer_id=eq.{tid}&product_id=eq.{pu}&select=id,qty_received") or []
            if cur:
                pg("PATCH", "stock_transfer_items",
                   {"qty_received": (cur[0]["qty_received"] or 0) + float(r.get("qty", 0)),
                    "qty_damaged": (cur[0].get("qty_damaged") or 0) + float(r.get("damaged", 0))},
                   f"?id=eq.{cur[0]['id']}")
            if r.get("qty", 0) > 0:   # TRANSFER_IN only when goods physically arrive (spec §10)
                pg("POST", "stock_movements", {"business_id": bid, "branch_id": brid, "product_id": pu,
                    "movement_type": "TRANSFER_IN", "quantity_delta": float(r["qty"]),
                    "reference_id": tid, "device_id": e["device_id"], "created_at": e.get("device_created_at") or utcnow()})
        pg("PATCH", "stock_transfers", {"status": p.get("status", "RECEIVED"), "received_at": e.get("device_created_at") or utcnow()},
           f"?id=eq.{tid}")

def _is_uuid(v):
    try: uuid.UUID(str(v)); return True
    except (ValueError, TypeError): return False

# ---- Supabase Auth: exchange credentials for a user JWT (§4.3) ----
@app.post("/api/v1/auth/login")
def auth_login():
    d = request.json or {}
    req = urllib.request.Request(f"{URL}/auth/v1/token?grant_type=password", method="POST",
        headers={"apikey": KEY, "Content-Type": "application/json"},
        data=json.dumps({"email": d.get("email"), "password": d.get("password")}).encode())
    try:
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return jsonify({"error": "auth_failed", "detail": e.read().decode()[:200]}), 401
    uid = (body.get("user") or {}).get("id")
    mem = pg("GET", "business_memberships", params=f"?user_id=eq.{uid}&select=business_id,role") or []
    return jsonify({"ok": True, "access_token": body["access_token"],
                    "expires_in": body.get("expires_in"), "memberships": mem})

@app.post("/api/v1/sync/push")
@need_hub
def push():
    """Accept hub events idempotently; dedupe by event_id (§8.2). server_sequence
    comes from the locked per-branch counter row — a single UPDATE, which is
    itself row-locking in Postgres (§8.3)."""
    evs = (request.json or {}).get("events", [])
    accepted, dup, rejected = [], [], []
    for e in evs:
        eid = str(e.get("event_id") or "")
        if not eid or e.get("event_type") not in EVENT_TYPES:
            rejected.append({"event_id": eid, "reason": "bad_envelope"}); continue
        if pg("GET", "sync_events", params=f"?event_id=eq.{eid}&select=event_id"):
            dup.append(eid); continue
        n = pg("POST", "rpc/alloc_sequence", {"p_branch": e["branch_id"]})
        if isinstance(n, dict):  # counter allocation is the correctness core — fail loudly
            rejected.append({"event_id": eid, "reason": "sequence_alloc_failed"}); continue
        row = {"event_id": eid, "business_id": e["business_id"], "branch_id": e["branch_id"],
               "device_id": e["device_id"], "device_sequence": e.get("device_sequence"),
               "event_type": e["event_type"], "schema_version": e.get("schema_version", 1),
               "entity_id": e.get("entity_id") or None, "device_created_at": e.get("device_created_at"),
               "payload": e.get("payload") or {}, "server_sequence": n}
        r = pg("POST", "sync_events", row)
        if isinstance(r, dict) and r.get("_error"):
            if r["_error"] == 409 or "duplicate" in r.get("detail", ""):
                dup.append(eid); continue
            rejected.append({"event_id": eid, "reason": r.get("detail", "write_failed")}); continue
        try: apply_event({**row, "device_id": e.get("device_id"), "event_id": eid})
        except Exception: pass  # durable event is stored; projection retried by a later pass
        accepted.append({"event_id": eid, "server_sequence": n})
    return jsonify({"ok": True, "accepted": accepted, "duplicates": dup, "rejected": rejected})

@app.get("/api/v1/sync/pull")
@need_hub
def pull():
    br = request.args["branch_id"]; after = int(request.args.get("after_sequence", 0))
    limit = min(int(request.args.get("limit", 200)), 1000)
    evs = pg("GET", "sync_events",
             params=f"?branch_id=eq.{br}&server_sequence=gt.{after}&order=server_sequence&limit={limit}") or []
    return jsonify({"events": evs, "cursor": after})

@app.post("/api/v1/sync/ack")
@need_hub
def ack():
    d = request.json or {}
    pg("POST", "sync_device_cursors",
       {"device_id": d["device_id"], "last_sequence": int(d.get("last_sequence", 0)), "updated_at": utcnow()},
       "?on_conflict=device_id")
    return jsonify({"ok": True})

@app.get("/api/v1/sync/status")
@need_hub
def status():
    evs = pg("GET", "sync_events", params="?select=server_sequence&order=server_sequence.desc&limit=1") or []
    return jsonify({"latest_sequence": evs[0]["server_sequence"] if evs else 0,
                    "open_conflicts": len(pg("GET", "sync_conflicts", params="?resolved=eq.false&select=id") or [])})

def _biz_ctx(uid):
    ms = pg("GET","business_memberships",params=f"?user_id=eq.{uid}&select=business_id&limit=1") or []
    if not ms: return None
    bid = ms[0]["business_id"]
    br = pg("GET","branches",params=f"?business_id=eq.{bid}&select=id&limit=1") or []
    return bid, br[0]["id"]

def _web_device(bid, brid):
    dev = pg("GET","devices",params=f"?business_id=eq.{bid}&branch_id=eq.{brid}&device_name=eq.Web%20till&select=id&limit=1") or []
    if dev: return dev[0]["id"]
    return pg("POST","devices",{"business_id":bid,"branch_id":brid,"device_name":"Web till","device_type":"web"})[0]["id"]

@app.get("/api/web/products")
def web_products():
    u = authed_user()
    if not u: return jsonify({"error": "unauthorized"}), 401
    ctx = _biz_ctx(u["id"])
    if not ctx: return jsonify({"error":"no store"}), 400
    bid, brid = ctx
    prods = pg("GET","products",params=f"?business_id=eq.{bid}&active=eq.true&order=name") or []
    bals = pg("GET","stock_balances",params=f"?business_id=eq.{bid}&branch_id=eq.{brid}&select=product_id,on_hand") or []
    qty = {b["product_id"]: float(b["on_hand"]) for b in bals}
    for p in prods: p["stock"] = qty.get(p["id"], 0)
    return jsonify(prods)

@app.post("/api/web/sale")
def web_sale():
    u = authed_user()
    if not u: return jsonify({"error": "unauthorized"}), 401
    ctx = _biz_ctx(u["id"])
    if not ctx: return jsonify({"error":"no store"}), 400
    bid, brid = ctx
    d = request.get_json(force=True)
    items, pays = d.get("items") or [], d.get("payments") or []
    if not items: return jsonify({"error":"empty sale"}), 400
    disc = float(d.get("discount") or 0)
    sub = sum(float(i["unit_price"])*float(i["qty"]) for i in items)
    total = max(0.0, round(sub - disc, 2))
    tax = round(total*16/116, 2)
    now = datetime.now(timezone.utc).isoformat()
    sid, receipt = str(uuid.uuid4()), "WEB-" + str(int(time.time()))
    pg("POST","sales",{"id":sid,"business_id":bid,"branch_id":brid,"device_id":_web_device(bid,brid),
       "receipt_number":receipt,"subtotal":round(sub,2),"discount_total":disc,"tax_total":tax,
       "total":total,"status":"completed","created_at":now})
    pg("POST","sale_items",[{"sale_id":sid,"business_id":bid,"product_id":i["product_id"],
       "quantity":i["qty"],"unit_price":i["unit_price"],"line_total":round(float(i["unit_price"])*float(i["qty"]),2)} for i in items])
    if pays:
        pg("POST","payments",[{"sale_id":sid,"business_id":bid,"method":p["method"],"amount":p["amount"],"created_at":now} for p in pays])
    for i in items:
        bal = pg("GET","stock_balances",params=f"?business_id=eq.{bid}&branch_id=eq.{brid}&product_id=eq.{i['product_id']}&select=id,on_hand&limit=1") or []
        if bal: pg("PATCH","stock_balances",{"on_hand": float(bal[0]["on_hand"])-float(i["qty"])},params=f"?id=eq.{bal[0]['id']}")
        else: pg("POST","stock_balances",{"business_id":bid,"branch_id":brid,"product_id":i["product_id"],"on_hand":-float(i["qty"])})
    return jsonify({"ok":True,"receipt":receipt,"total":total})

def _emit(bid, brid, dev, etype, payload):
    eid = str(uuid.uuid4())
    n = pg("POST","rpc/alloc_sequence",{"p_branch":brid})
    if isinstance(n, dict): return None
    row = {"event_id":eid,"business_id":bid,"branch_id":brid,"device_id":dev,"event_type":etype,
           "schema_version":1,"device_created_at":utcnow(),"payload":payload,"server_sequence":n}
    if isinstance(pg("POST","sync_events",row), dict): return None
    try: apply_event({**row,"device_id":dev,"event_id":eid})
    except Exception: pass
    return eid

@app.post("/api/web/product")
def web_product():
    u = authed_user()
    if not u: return jsonify({"error":"unauthorized"}), 401
    ctx = _biz_ctx(u["id"])
    if not ctx: return jsonify({"error":"no store"}), 400
    bid, brid = ctx
    d = request.get_json(force=True)
    pid = d.get("id") or str(uuid.uuid4())
    upd = bool(d.get("id"))
    eid = _emit(bid, brid, _web_device(bid, brid), "PRODUCT_UPDATED" if upd else "PRODUCT_CREATED",
        {"product_id": pid, "product_uuid": pid, "name": d.get("name"), "barcode": d.get("barcode"),
         "price": float(d.get("price") or 0), "cost": float(d.get("cost") or 0)})
    return jsonify({"ok": bool(eid), "id": pid}) if eid else (jsonify({"error":"emit failed"}), 500)

@app.post("/api/web/stock")
def web_stock():
    u = authed_user()
    if not u: return jsonify({"error":"unauthorized"}), 401
    ctx = _biz_ctx(u["id"])
    if not ctx: return jsonify({"error":"no store"}), 400
    bid, brid = ctx
    d = request.get_json(force=True)
    eid = _emit(bid, brid, _web_device(bid, brid), "STOCK_MOVED",
        {"product_id": d["product_id"], "product_uuid": d["product_id"],
         "movement_type": "STOCK_ADJUSTMENT", "quantity_delta": float(d.get("delta") or 0),
         "ref_no": d.get("note") or "web"})
    return jsonify({"ok": bool(eid)}) if eid else (jsonify({"error":"emit failed"}), 500)

@app.get("/")
def web_index():
    return app.send_static_file("index.html")

@app.errorhandler(404)
def fallback(e):
    p = request.path.lstrip("/")
    if p and not p.startswith("api/"):
        for cand in (p, p + ".html", p + "/index.html"):
            if os.path.isfile(os.path.join(app.static_folder, cand)):
                return app.send_static_file(cand)
    return jsonify({"error": "not found"}), 404

@app.get("/health")
def health(): return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT") or os.environ.get("CLOUD_API_PORT", 5060)))
