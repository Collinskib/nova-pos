import { create } from "zustand";
import type { CartItem, Product } from "../db/repos";

export type Sync = "offline" | "pending" | "syncing" | "synced" | "error";
export type Ctx = { device: string; business: string; branch: string;
                    cashier_id?: string; cashier_name?: string; role?: string };

type State = {
  ctx: Ctx | null;
  cart: Record<string, CartItem>;
  syncState: Sync; pending: number; hubUp: boolean; lastSync: string | null;
  syncError: "repair" | "net" | null;
  set: (p: Partial<State>) => void;
  addToCart: (p: Product) => void;
  setQty: (id: string, qty: number) => void;
  clearCart: () => void;
  cartTotal: () => number;
};

export const useStore = create<State>((set, get) => ({
  ctx: null, cart: {}, syncState: "offline", pending: 0, hubUp: false, lastSync: null, syncError: null,
  set: p => set(p),
  addToCart: p => set(s => ({ cart: { ...s.cart, [p.id]: { ...p, qty: (s.cart[p.id]?.qty || 0) + 1 } } })),
  setQty: (id, qty) => set(s => { const c = { ...s.cart };
    if (qty <= 0) delete c[id]; else c[id] = { ...c[id], qty }; return { cart: c }; }),
  clearCart: () => set({ cart: {} }),
  cartTotal: () => Object.values(get().cart).reduce((a, i) =>
    a + Math.round(i.price_cents * i.qty * (1 - (i.discount_qty && i.qty >= i.discount_qty ? (i.discount_pct || 0) / 100 : 0))), 0),
}));
