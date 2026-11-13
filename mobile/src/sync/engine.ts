// Sync engine (spec §11): prefer hub, fall back to cloud; dedupe + cursors; backoff with jitter.
import { getDb, tx, all, one, run } from "../db/database";
import { seedProducts, setState } from "../db/repos";
import { hub, creds } from "../lib/api";
import { useStore } from "../store/store";

let delay = 3000, timer: any = null;
const jitter = () => Math.random() * 1000;

async function applyEvent(d: any, e: any) {
  // inbound events are stored + deduped by event_id before this is called
  if (e.event_type === "PRODUCT_CREATED" || e.event_type === "PRODUCT_UPDATED") {
    const p = e.payload;
    await run(d, "ALTER TABLE products ADD COLUMN price_wholesale_cents REAL").catch(() => {});
    await run(d, "ALTER TABLE products ADD COLUMN parent_id TEXT").catch(() => {});
    await run(d, "ALTER TABLE products ADD COLUMN variant_label TEXT").catch(() => {});
    await run(d, "ALTER TABLE products ADD COLUMN pack_size INTEGER").catch(() => {});
    await run(d, "ALTER TABLE products ADD COLUMN pack_price_cents INTEGER").catch(() => {});
    await run(d, `INSERT OR REPLACE INTO products(id,business_id,barcode,name,price_cents,price_wholesale_cents,cost_cents,stock,taxable,parent_id,variant_label,pack_size,pack_price_cents,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`, [e.entity_id, e.business_id, p.barcode, p.name,
      Math.round((p.price || 0) * 100), p.price_wholesale != null ? Math.round(p.price_wholesale * 100) : null,
      Math.round((p.cost || 0) * 100), p.stock ?? 0, p.taxable ?? 1, p.parent_id ?? null, p.variant_label ?? null,
      p.pack_size ?? 0, p.pack_price != null ? Math.round(p.pack_price * 100) : null, new Date().toISOString()]);
  }
  else if (e.event_type === "PRODUCT_DELETED") {
    await run(d, "DELETE FROM products WHERE id=?", [e.entity_id]);
  }
  else if (e.event_type === "TRANSFER_CREATED") {
    const p = e.payload;
    await run(d, `INSERT OR IGNORE INTO transfers(id,business_id,from_branch_id,to_branch_id,status,note,created_at)
      VALUES(?,?,?,?,?,?,?)`, [p.transfer_id || e.entity_id, e.business_id, e.branch_id, p.to_branch, "DRAFT", p.note || "", e.device_created_at]);
    for (const i of p.items || [])
      await run(d, "INSERT OR IGNORE INTO transfer_items(id,transfer_id,product_id,qty_sent) VALUES(?,?,?,?)",
        [`${e.event_id}:${i.product_id}`, p.transfer_id || e.entity_id, i.product_id, i.qty]);
  }
  else if (e.event_type === "TRANSFER_DISPATCH") {
    // status only — receiving branch never takes stock from a dispatch event (spec §10)
    await run(d, "UPDATE transfers SET status='DISPATCHED',dispatched_at=? WHERE id=?",
      [e.device_created_at, e.payload.transfer_id || e.entity_id]);
  }
  else if (e.event_type === "TRANSFER_RECEIVE") {
    const p = e.payload, tid = p.transfer_id || e.entity_id;
    for (const r of p.receipts || [])
      await run(d, "UPDATE transfer_items SET qty_received=qty_received+?, qty_damaged=qty_damaged+? WHERE transfer_id=? AND product_id=?",
        [r.qty || 0, r.damaged || 0, tid, r.product_id]);
    await run(d, "UPDATE transfers SET status=?,received_at=? WHERE id=?",
      [p.status || "RECEIVED", e.device_created_at, tid]);
  }
  else if (e.event_type === "SALE_CREATED") {
    // project a remote sale: items, payments, stock decrement. Idempotent by sale id.
    const p = e.payload, sid = p.sale_id || p.sale_uuid || e.entity_id;
    const exists = await one(d, "SELECT 1 x FROM sales WHERE id=? OR receipt_no=?", [sid, p.receipt_no || p.invoice_no || ""]);
    if (!exists) {
      const cents = p.total_cents != null;
      const f = (v: any) => cents ? Math.round(v || 0) : Math.round((v || 0) * 100);
      const total = f(p.total_cents ?? p.total);
      await run(d, `INSERT INTO sales(id,receipt_no,business_id,branch_id,device_id,subtotal_cents,
        discount_cents,tax_cents,total_cents,status,created_at,cashier_name,customer_name)
        VALUES(?,?,?,?,?,?,?,?,?,'completed',?,?,?)`,
        [sid, p.receipt_no || p.invoice_no || "EXT-" + String(sid).slice(0, 8), e.business_id, e.branch_id,
         e.device_id, f(p.subtotal_cents ?? p.subtotal ?? p.total_cents ?? p.total),
         f(p.discount_cents ?? p.discount), f(p.tax_cents ?? p.vat ?? p.tax), total,
         e.device_created_at || new Date().toISOString(), p.cashier_name || null, p.customer_name || null]);
      for (const i of p.items || []) {
        const pid = String(i.product_id ?? i.product_uuid ?? "");
        const lt = i.total_cents != null ? i.total_cents : Math.round((i.total || 0) * 100);
        const up = i.unit_price_cents != null ? i.unit_price_cents : Math.round((i.unit_price ?? (i.total || 0) / Math.max(i.qty || 1, 1)) * 100);
        await run(d, `INSERT INTO sale_items(id,sale_id,product_id,name,qty,unit_price_cents,total_cents)
          VALUES(?,?,?,?,?,?,?)`, [`${e.event_id}:${pid}:${i.name || ""}`, sid, pid, i.name || "item", i.qty || 0, up, lt]);
        const prod = await one(d, "SELECT 1 x FROM products WHERE id=?", [pid]);
        if (prod && (i.qty || 0) > 0) {
          await run(d, "UPDATE products SET stock=stock-? WHERE id=?", [i.qty, pid]);
          await run(d, `INSERT INTO stock_balances(business_id,branch_id,product_id,on_hand) VALUES(?,?,?,?)
            ON CONFLICT(business_id,branch_id,product_id) DO UPDATE SET on_hand=on_hand+excluded.on_hand`,
            [e.business_id, e.branch_id, pid, -i.qty]);
        }
      }
      for (const pay of p.payments || []) {
        const amt = pay.amount_cents != null ? pay.amount_cents : Math.round((pay.amount || 0) * 100);
        await run(d, "INSERT INTO payments(id,sale_id,method,amount_cents,created_at) VALUES(?,?,?,?,?)",
          [`${e.event_id}:${pay.method || "cash"}`, sid, pay.method || "cash", amt,
           e.device_created_at || new Date().toISOString()]);
      }
    }
  }
  else if (e.event_type === "SALE_VOIDED") {
    const p = e.payload, sid = p.sale_uuid || p.sale_id || e.entity_id;
    const s = await one<any>(d, "SELECT id FROM sales WHERE (id=? OR receipt_no=?) AND status='completed'",
      [sid, p.invoice_no || p.receipt_no || ""]);
    if (s) {
      await run(d, "UPDATE sales SET status='void' WHERE id=?", [s.id]);
      for (const i of await all<any>(d, "SELECT product_id,qty FROM sale_items WHERE sale_id=?", [s.id])) {
        await run(d, "UPDATE products SET stock=stock+? WHERE id=?", [i.qty, i.product_id]);
        await run(d, `INSERT INTO stock_balances(business_id,branch_id,product_id,on_hand) VALUES(?,?,?,?)
          ON CONFLICT(business_id,branch_id,product_id) DO UPDATE SET on_hand=on_hand+excluded.on_hand`,
          [e.business_id, e.branch_id, i.product_id, i.qty]);
      }
    }
  }
  else if (e.event_type === "STOCK_MOVED") {
    const p = e.payload, pid = String(p.product_id ?? p.product_uuid ?? "");
    const qty = Number(p.quantity_delta || 0);
    const prod = await one(d, "SELECT 1 x FROM products WHERE id=?", [pid]);
    if (prod) {
      await run(d, "UPDATE products SET stock=stock+? WHERE id=?", [qty, pid]);
      await run(d, `INSERT INTO stock_balances(business_id,branch_id,product_id,on_hand) VALUES(?,?,?,?)
        ON CONFLICT(business_id,branch_id,product_id) DO UPDATE SET on_hand=on_hand+excluded.on_hand`,
        [e.business_id, e.branch_id, pid, qty]);
      await run(d, `INSERT OR IGNORE INTO stock_movements(id,business_id,branch_id,product_id,movement_type,
        quantity_delta,reference_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)`,
        [p.movement_uuid || e.entity_id || e.event_id, e.business_id, e.branch_id, pid,
         p.movement_type || "STOCK_ADJUSTMENT", qty, e.entity_id, p.note || p.ref_no || "",
         e.device_created_at || new Date().toISOString()]);
    } else {
      await run(d, "INSERT INTO sync_conflicts(event_id,reason,detail,created_at) VALUES(?,?,?,?)",
        [e.event_id, "unmapped_product", JSON.stringify({ product_id: pid }), new Date().toISOString()]);
    }
  }
  else if (e.event_type === "RETURN_POSTED" || e.event_type === "PURCHASE_RECEIVED") {
    const p = e.payload, rid = p.return_uuid || p.purchase_uuid || e.entity_id;
    const inb = e.event_type === "RETURN_POSTED" ? "returns" : "purchases";
    const itb = e.event_type === "RETURN_POSTED" ? "return_items" : "purchase_items";
    const exists = await one(d, `SELECT 1 x FROM ${inb} WHERE id=?`, [rid]);
    if (!exists) {
      if (e.event_type === "RETURN_POSTED")
        await run(d, "INSERT INTO returns(id,sale_id,reason,total_cents,created_at) VALUES(?,?,?,?,?)",
          [rid, p.sale_uuid || null, p.reason || "", Math.round((p.total || 0) * 100), e.device_created_at]);
      else
        await run(d, "INSERT INTO purchases(id,supplier_id,total_cents,note,created_at) VALUES(?,?,?,?,?)",
          [rid, null, Math.round((p.total || 0) * 100), p.note || "", e.device_created_at]);
      for (const i of p.items || []) {
        const pid = String(i.product_id ?? i.product_uuid ?? ""), qty = Number(i.qty || 0);
        await run(d, `INSERT INTO ${itb}(id,${inb === "returns" ? "return_id" : "purchase_id"},product_id,qty${inb === "returns" ? ",total_cents" : ",cost_cents"})
          VALUES(?,?,?,?,?)`, [`${e.event_id}:${pid}`, rid, pid, qty,
          inb === "returns" ? Math.round((i.total || 0) * 100) : Math.round((i.cost || 0) * 100)]);
        await run(d, "UPDATE products SET stock=stock+? WHERE id=?", [qty, pid]);
        await run(d, `INSERT INTO stock_balances(business_id,branch_id,product_id,on_hand) VALUES(?,?,?,?)
          ON CONFLICT(business_id,branch_id,product_id) DO UPDATE SET on_hand=on_hand+excluded.on_hand`,
          [e.business_id, e.branch_id, pid, qty]);
      }
    }
  }
  else if (e.event_type === "EXPENSE_POSTED") {
    const p = e.payload;
    await run(d, "INSERT OR IGNORE INTO expenses(id,category,amount_cents,note,created_at) VALUES(?,?,?,?,?)",
      [p.expense_uuid || e.entity_id || e.event_id, p.category || "General",
       Math.round((p.amount || 0) * 100), p.note || "", e.device_created_at || new Date().toISOString()]);
  }
  // anything unknown stays durable in inbox for a later projector
}

/** Re-seed the local catalog from the hub — callable anywhere, not just the sync loop. */
export async function refreshCatalog() {
  const c = await creds.load(); if (!c) return 0;
  const base = await hub.base();
  const prods = await hub.products(base, c.device_key);
  if (prods.length) await seedProducts({ business: c.business }, prods, base);
  try {  // till-relevant settings — tax_rate drives offline VAT math
    const st = await hub.settings(base, c.device_key);
    await setState(await getDb(), "tax_rate", String(st.tax_rate ?? 16));
  } catch {}
  return prods.length;
}

export async function syncOnce() {
  const st = useStore.getState();
  const d = await getDb();
  const c = await creds.load();
  if (!c) return;
  const base = await hub.base();
  const key = c.device_key;

  // 1. push outbox → hub (spec §11.2)
  const pending = await all<any>(d, "SELECT * FROM sync_outbox WHERE cloud_acked=0 ORDER BY id LIMIT 100");
  let pushed = 0;
  try {
    if (pending.length) {
      const r = await hub.push(base, pending.map((p: any) => ({
        event_id: p.event_id, business_id: p.business_id, branch_id: p.branch_id, device_id: p.device_id,
        device_sequence: p.device_sequence, event_type: p.event_type, schema_version: p.schema_version,
        entity_id: p.entity_id, device_created_at: p.device_created_at, payload: JSON.parse(p.payload) })), key);
      const done = new Set([...(r.accepted || []).map((a: any) => a.event_id), ...(r.duplicates || [])]);
      for (const eid of done) {
        await run(d, "UPDATE sync_outbox SET hub_acked=1, cloud_acked=1 WHERE event_id=?", [eid]);
        await run(d, "INSERT OR IGNORE INTO sync_receipts(event_id,destination,acked_at,status) VALUES(?,?,?,?)",
          [eid, "hub", new Date().toISOString(), "accepted"]);
      }
      pushed = done.size;
    }
    st.set({ hubUp: true, syncError: null });
  } catch (e: any) {
    // timeout ≠ failure — events stay queued, retried with same IDs (§11.2).
    // 401/403 means this device's key is gone or revoked — a re-pair, not a retry.
    st.set({ hubUp: false, syncError: (e?.status === 401 || e?.status === 403) ? "repair" : "net" });
  }

  // 2. pull hub events → inbox → apply → ack (§11.3)
  try {
    const cur = (await one<{ last_sequence: number }>(d, "SELECT last_sequence FROM sync_cursors WHERE destination='hub'"))?.last_sequence ?? 0;
    const r = await hub.pull(base, cur, key);
    let top = cur;
    for (const e of r.events || []) {
      const dup = await one(d, "SELECT 1 x FROM sync_inbox WHERE event_id=?", [e.event_id]);
      if (!dup) {
        await run(d, `INSERT INTO sync_inbox(event_id,server_sequence,event_type,entity_id,payload,applied,received_at)
          VALUES(?,?,?,?,?,1,?)`, [e.event_id, e.server_sequence, e.event_type, e.entity_id,
          JSON.stringify(e.payload || {}), new Date().toISOString()]);
        await applyEvent(d, e);   // apply inside same durable step before cursor moves
      }
      top = Math.max(top, e.server_sequence);
    }
    if (top > cur) {
      await run(d, "INSERT OR REPLACE INTO sync_cursors(destination,last_sequence,updated_at) VALUES('hub',?,?)",
        [top, new Date().toISOString()]);
      await hub.ack(base, top, key);
    }
  } catch { /* pull failure: cursor untouched, retry later */ }

  // 3. catalog refresh on its own cycle — product adds/edits must reach devices
  // even when the event pull failed or yielded nothing (production churn, §11.3)
  try {
    const prods = await hub.products(base, key).catch(() => []);
    if (prods.length) await seedProducts({ business: c.business }, prods, base);
  } catch { /* best-effort — local catalog stays usable offline */ }

  const left = (await one<{ n: number }>(d, "SELECT COUNT(*) n FROM sync_outbox WHERE cloud_acked=0"))!.n;
  st.set({ pending: left, syncState: left ? (st.hubUp ? "pending" : "offline") : "synced",
           lastSync: st.hubUp ? new Date().toISOString() : st.lastSync });
  delay = 3000;
  return { pushed, pending: left };
}

export function startSync() {
  stopSync();
  const tick = async () => {
    try { await syncOnce(); } catch { delay = Math.min(delay * 2, 120000); }
    timer = setTimeout(tick, delay + jitter());
  };
  timer = setTimeout(tick, 1500);
}
export const stopSync = () => { if (timer) clearTimeout(timer); timer = null; };
