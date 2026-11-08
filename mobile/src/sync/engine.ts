// Sync engine (spec §11): prefer hub, fall back to cloud; dedupe + cursors; backoff with jitter.
import { getDb, tx, all, one, run } from "../db/database";
import { seedProducts } from "../db/repos";
import { hub, creds } from "../lib/api";
import { useStore } from "../store/store";

let delay = 3000, timer: any = null;
const jitter = () => Math.random() * 1000;

async function applyEvent(d: any, e: any) {
  // inbound events are stored + deduped by event_id before this is called
  if (e.event_type === "PRODUCT_CREATED" || e.event_type === "PRODUCT_UPDATED") {
    const p = e.payload;
    await run(d, `INSERT OR REPLACE INTO products(id,business_id,barcode,name,price_cents,cost_cents,stock,taxable,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?)`, [e.entity_id, e.business_id, p.barcode, p.name,
      Math.round((p.price || 0) * 100), Math.round((p.cost || 0) * 100), p.stock ?? 0, p.taxable ?? 1, new Date().toISOString()]);
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
  // other types remain durable in inbox for the later projector (documented limitation)
}

/** Re-seed the local catalog from the hub — callable anywhere, not just the sync loop. */
export async function refreshCatalog() {
  const c = await creds.load(); if (!c) return 0;
  const base = await hub.base();
  const prods = await hub.products(base, c.device_key);
  if (prods.length) await seedProducts({ business: c.business }, prods, base);
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
    // catalog refresh — repopulate if pairing-time fetch failed (silent empty)
    const prods = await hub.products(base, key).catch(() => []);
    if (prods.length) await seedProducts({ business: c.business }, prods, base);
  } catch { /* pull failure: cursor untouched, retry later */ }

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
