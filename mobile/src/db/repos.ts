import { getDb, tx, all, one, run } from "./database";

// RFC4122v4 without crypto.getRandomValues — unique enough for POS entities/events.
const uuid = () => "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
  const r = Math.random() * 16 | 0;
  return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
});

export type Product = { id: string; barcode: string; name: string; price_cents: number;
  stock: number; taxable: number; discount_qty: number | null; discount_pct: number | null; image: string | null };
export type CartItem = Product & { qty: number };
export type Sale = { id: string; receipt_no: string; total_cents: number; status: string; created_at: string;
                     paid_cents?: number | null; pay_method?: string | null };

const now = () => new Date().toISOString();
const money = (n: number) => Math.round(n * 100); // float → minor units (§4.4)

// ---------- settings / device state ----------
export const getState = async (d: any, k: string) =>
  (await one<{ v: string }>(d, "SELECT v FROM device_state WHERE k=?", [k]))?.v ?? null;
export const setState = (d: any, k: string, v: string) =>
  run(d, "INSERT OR REPLACE INTO device_state(k,v) VALUES(?,?)", [k, v]);

// ---------- event emission (§8.4) ----------
async function emit(d: any, ctx: { business: string; branch: string; device: string },
                    type: string, entityId: string, payload: object) {
  const seq = parseInt((await getState(d, "device_seq")) ?? "0", 10) + 1;
  await setState(d, "device_seq", String(seq));
  const eid = uuid();
  await run(d, `INSERT INTO sync_outbox(event_id,business_id,branch_id,device_id,device_sequence,
    event_type,schema_version,entity_id,device_created_at,payload) VALUES(?,?,?,?,?,?,?,?,?,?)`,
    [eid, ctx.business, ctx.branch, ctx.device, seq, type, 1, entityId, now(), JSON.stringify(payload)]);
  return eid;
}

// ---------- catalog ----------
const read = <T>(q: string, p: any[] = []) => getDb().then(d => d.getAllAsync<T>(q, p));
export const searchProducts = (q: string, limit = 60) =>
  read<Product>(`SELECT * FROM products WHERE name LIKE ? OR barcode LIKE ?
    ORDER BY name LIMIT ?`, [`%${q}%`, `%${q}%`, limit]);
export const seedProducts = (ctx: any, items: any[], base = "") =>
  tx(d => Promise.all(items.map(p => {
    const img = p.image ? (/^https?:/.test(p.image) ? p.image : base + p.image) : null;
    return run(d,
    `INSERT OR REPLACE INTO products(id,business_id,barcode,name,price_cents,cost_cents,stock,taxable,discount_qty,discount_pct,image,updated_at)
     VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`,
    [p.uuid || String(p.id) || uuid(), ctx.business, p.barcode, p.name, money(p.price), money(p.cost || 0),
     p.stock, p.taxable ?? 1, p.discount_qty, p.discount_pct, img, now()]);
  })));

// ---------- receipt counter: device-scoped range (§7.3) ----------
async function nextReceipt(d: any) {
  const n = parseInt((await getState(d, "receipt_seq")) ?? "0", 10) + 1;
  await setState(d, "receipt_seq", String(n));
  return `MOB-${String(n).padStart(6, "0")}`;
}

// ---------- atomic checkout (spec §8) ----------
export async function checkout(ctx: any, items: CartItem[], payment: { method: string; amount: number }) {
  return tx(async d => {
    const id = uuid(), receipt = await nextReceipt(d);
    let sub = 0, tax = 0;
    const lines = items.map(i => {
      const disc = i.discount_qty && i.qty >= i.discount_qty ? (i.discount_pct || 0) / 100 : 0;
      const t = Math.round(i.price_cents * i.qty * (1 - disc));
      sub += t;
      if (i.taxable) tax += Math.round(t * 0.16 / 1.16); // VAT-inclusive @16%
      return { product_id: i.id, name: i.name, qty: i.qty, unit_price_cents: i.price_cents, total_cents: t };
    });
    const payCents = money(payment.amount);
    if (payCents < sub) throw new Error("Insufficient payment");
    // offline stock policy: refuse silently-negative stock (spec §9)
    for (const i of items) {
      const p = await one<{ stock: number }>(d, "SELECT stock FROM products WHERE id=?", [i.id]);
      if (!p || p.stock < i.qty) throw new Error(`Insufficient stock: ${i.name}`);
    }
    await run(d, `INSERT INTO sales(id,receipt_no,business_id,branch_id,device_id,subtotal_cents,
      discount_cents,tax_cents,total_cents,created_at,cashier_name) VALUES(?,?,?,?,?,?,?,?,?,?,?)`,
      [id, receipt, ctx.business, ctx.branch, ctx.device, sub, 0, tax, sub, now(), ctx.cashier_name || null]);
    for (const l of lines) {
      await run(d, `INSERT INTO sale_items(id,sale_id,product_id,name,qty,unit_price_cents,total_cents)
        VALUES(?,?,?,?,?,?,?)`, [uuid(), id, l.product_id, l.name, l.qty, l.unit_price_cents, l.total_cents]);
      await run(d, `INSERT INTO stock_movements(id,business_id,branch_id,product_id,movement_type,
        quantity_delta,reference_id,created_at) VALUES(?,?,?,?,?,?,?,?)`,
        [uuid(), ctx.business, ctx.branch, l.product_id, "SALE", -l.qty, id, now()]);
      await run(d, "UPDATE products SET stock=stock-? WHERE id=?", [l.qty, l.product_id]);
      await run(d, `INSERT INTO stock_balances(business_id,branch_id,product_id,on_hand) VALUES(?,?,?,?)
        ON CONFLICT(business_id,branch_id,product_id) DO UPDATE SET on_hand=on_hand+excluded.on_hand`,
        [ctx.business, ctx.branch, l.product_id, -l.qty]);
    }
    await run(d, "INSERT INTO payments(id,sale_id,method,amount_cents,created_at) VALUES(?,?,?,?,?)",
      [uuid(), id, payment.method, payCents, now()]);
    const event_id = await emit(d, ctx, "SALE_CREATED", id,
      { sale_id: id, receipt_no: receipt, total_cents: sub, tax_cents: tax, items: lines,
        cashier_name: ctx.cashier_name || null });
    return { id, receipt_no: receipt, total_cents: sub, event_id };
  });
}

// ---------- history / dashboard ----------
export const recentSales = (limit = 50) =>
  read<Sale>(`SELECT s.*, p.amount_cents paid_cents, p.method pay_method FROM sales s
    LEFT JOIN payments p ON p.sale_id=s.id ORDER BY s.created_at DESC LIMIT ?`, [limit]);
export const todayTotals = async () => ({
  count: ((await read<{ n: number }>("SELECT COUNT(*) n FROM sales WHERE date(created_at)=date('now') AND status='completed'"))[0])!.n,
  total: ((await read<{ t: number | null }>("SELECT SUM(total_cents) t FROM sales WHERE date(created_at)=date('now') AND status='completed'"))[0])!.t ?? 0,
});
export const pendingOutbox = () =>
  read("SELECT * FROM sync_outbox WHERE cloud_acked=0 ORDER BY id LIMIT 200");
export const saleItems = (saleId: string) =>
  read("SELECT * FROM sale_items WHERE sale_id=?", [saleId]);

// ---------- transfers (spec §10): DRAFT → DISPATCHED → IN_TRANSIT → RECEIVED ----------
export const listTransfers = () =>
  read<any>(`SELECT t.*, (SELECT json_group_array(json_object('name',p.name,'qty_sent',ti.qty_sent,
    'qty_received',ti.qty_received,'qty_damaged',ti.qty_damaged,'product_id',ti.product_id))
    FROM transfer_items ti JOIN products p ON p.id=ti.product_id WHERE ti.transfer_id=t.id) items
    FROM transfers t ORDER BY t.created_at DESC`);

export async function createTransfer(ctx: any, toBranch: string, items: { product_id: string; qty: number }[], note = "") {
  return tx(async d => {
    const id = uuid();
    await run(d, `INSERT INTO transfers(id,business_id,from_branch_id,to_branch_id,status,note,created_at)
      VALUES(?,?,?,?,?,?,?)`, [id, ctx.business, ctx.branch, toBranch, "DRAFT", note, now()]);
    for (const i of items)
      await run(d, "INSERT INTO transfer_items(id,transfer_id,product_id,qty_sent) VALUES(?,?,?,?)",
        [uuid(), id, i.product_id, i.qty]);
    await emit(d, ctx, "TRANSFER_CREATED", id, { transfer_id: id, to_branch: toBranch, items });
    return id;
  });
}

export async function dispatchTransfer(ctx: any, transferId: string) {
  return tx(async d => {
    const items = await all<any>(d, "SELECT * FROM transfer_items WHERE transfer_id=?", [transferId]);
    for (const i of items) {   // TRANSFER_OUT on dispatch — never touch receiving stock (§10)
      await run(d, `INSERT INTO stock_movements(id,business_id,branch_id,product_id,movement_type,
        quantity_delta,reference_id,created_at) VALUES(?,?,?,?,?,?,?,?)`,
        [uuid(), ctx.business, ctx.branch, i.product_id, "TRANSFER_OUT", -i.qty_sent, transferId, now()]);
      await run(d, "UPDATE products SET stock=stock-? WHERE id=?", [i.qty_sent, i.product_id]);
    }
    await run(d, "UPDATE transfers SET status='DISPATCHED',dispatched_at=? WHERE id=?", [now(), transferId]);
    await emit(d, ctx, "TRANSFER_DISPATCH", transferId, { transfer_id: transferId, items });
  });
}

export async function receiveTransfer(ctx: any, transferId: string,
                                      receipts: { product_id: string; qty: number; damaged?: number }[]) {
  return tx(async d => {
    let full = true;
    for (const r of receipts) {
      await run(d, "UPDATE transfer_items SET qty_received=qty_received+?, qty_damaged=qty_damaged+? WHERE transfer_id=? AND product_id=?",
        [r.qty, r.damaged || 0, transferId, r.product_id]);
      if (r.qty > 0) {   // TRANSFER_IN only on physical receipt (§10)
        await run(d, `INSERT INTO stock_movements(id,business_id,branch_id,product_id,movement_type,
          quantity_delta,reference_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)`,
          [uuid(), ctx.business, ctx.branch, r.product_id, "TRANSFER_IN", r.qty, transferId,
           r.damaged ? `damaged:${r.damaged}` : "", now()]);
        await run(d, "UPDATE products SET stock=stock+? WHERE id=?", [r.qty, r.product_id]);
      }
    }
    const open = await all<any>(d, "SELECT qty_sent,qty_received,qty_damaged FROM transfer_items WHERE transfer_id=?", [transferId]);
    full = open.every(i => (i.qty_received + i.qty_damaged) >= i.qty_sent);
    await run(d, "UPDATE transfers SET status=?,received_at=? WHERE id=?",
      [full ? "RECEIVED" : "IN_TRANSIT", now(), transferId]);
    await emit(d, ctx, "TRANSFER_RECEIVE", transferId,
      { transfer_id: transferId, receipts, status: full ? "RECEIVED" : "IN_TRANSIT" });
    return full;
  });
}
