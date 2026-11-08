import * as SecureStore from "expo-secure-store";

const DEFAULT_HUB = "http://192.168.1.100:5050";
const DEFAULT_CLOUD = "https://bpwbwvaimwofjkxjestv.supabase.co";
const CLOUD_API = "http://127.0.0.1:5060"; // dev cloud API; prod = hosted URL

const TIMEOUT = 8000;
const withTimeout = <T,>(p: Promise<T>) =>
  Promise.race([p, new Promise<never>((_, r) => setTimeout(() => r(new Error("timeout")), TIMEOUT))]);

async function req<T>(base: string, path: string, opts: any = {}, key?: string | null): Promise<T> {
  const r = await withTimeout(fetch(base + path, {
    ...opts,
    headers: { "Content-Type": "application/json",
      ...(key ? { "X-Device-Key": key } : {}), ...(opts.headers || {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  }));
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(j.error || `HTTP ${r.status}`), { status: r.status });
  return j as T;
}

export const hub = {
  base: () => SecureStore.getItemAsync("hub_url").then(v => v || DEFAULT_HUB),
  async ping() { try { await withTimeout(fetch((await this.base()) + "/", { method: "HEAD" })); return true; } catch { return false; } },
  pair: (token: string, name: string) => req(`${""}`, "", {}), // replaced below
  push: (base: string, events: any[], key: string) => req<{ accepted: any[]; duplicates: string[]; rejected: any[] }>(base, "/api/v1/sync/push", { method: "POST", body: { events } }, key),
  pull: (base: string, after: number, key: string) => req<{ events: any[] }>(base, `/api/v1/sync/pull?after_sequence=${after}&limit=500`, {}, key),
  ack: (base: string, seq: number, key: string) => req(base, "/api/v1/sync/ack", { method: "POST", body: { last_sequence: seq } }, key),
  products: (base: string, key: string) => req<any[]>(base, "/api/v1/products", {}, key),
  users: (base: string, key: string) => req<any[]>(base, "/api/v1/users", {}, key),
  dashboard: (base: string, key: string) => req<any>(base, "/api/v1/dashboard", {}, key),
  reports: (base: string, key: string, d?: string) => req<any>(base, `/api/v1/reports${d ? `?date=${d}` : ""}`, {}, key),
  devices: (base: string, key: string) => req<any[]>(base, "/api/v1/devices", {}, key),
  shiftCurrent: (b: string, k: string) => req<{ shift: any }>(b, "/api/v1/shifts/current", {}, k),
  shiftOpen: (b: string, k: string, body: any) => req(b, "/api/v1/shifts/open", { method: "POST", body }, k),
  shiftClose: (b: string, k: string, count: number) => req<any>(b, "/api/v1/shifts/close", { method: "POST", body: { count } }, k),
  customers: (b: string, k: string) => req<any[]>(b, "/api/v1/customers", {}, k),
  addCustomer: (b: string, k: string, body: any) => req<any>(b, "/api/v1/customers", { method: "POST", body }, k),
  doPair: (base: string, token: string, name: string) => req<{ ok: boolean; device_id: number; device_key: string; business_id: string; branch_id: string; error?: string }>(
    base, "/api/v1/devices/pair", { method: "POST", body: { token, device_name: name, device_type: "mobile" } }),
  status: (base: string, key: string) => req<any>(base, "/api/v1/sync/status", {}, key),
};

export const creds = {
  save: (d: { device_key: string; device: string; business: string; branch: string;
              cashier_id?: any; cashier_name?: string; role?: string }) =>
    Promise.all([SecureStore.setItemAsync("device_key", d.device_key),
      SecureStore.setItemAsync("device_id", String(d.device)),
      SecureStore.setItemAsync("business", String(d.business)), SecureStore.setItemAsync("branch", String(d.branch)),
      d.cashier_id != null ? SecureStore.setItemAsync("cashier_id", String(d.cashier_id)) : Promise.resolve(0 as any),
      d.cashier_name ? SecureStore.setItemAsync("cashier_name", d.cashier_name) : Promise.resolve(0 as any),
      d.role ? SecureStore.setItemAsync("role", d.role) : Promise.resolve(0 as any)]),
  load: async () => {
    const [k, id, b, br, cid, cn, ro] = await Promise.all(
      ["device_key", "device_id", "business", "branch", "cashier_id", "cashier_name", "role"].map(k => SecureStore.getItemAsync(k)));
    return k ? { device_key: k, device: id!, business: b!, branch: br!,
                 cashier_id: cid ?? undefined, cashier_name: cn ?? undefined, role: ro ?? undefined } : null;
  },
  clear: () => Promise.all(["device_key", "device_id", "business", "branch", "hub_url",
      "cashier_id", "cashier_name", "role"].map(k => SecureStore.deleteItemAsync(k))),
};
