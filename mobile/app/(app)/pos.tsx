import { useEffect, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, FlatList, Alert, StyleSheet, Modal, Image, Share, ScrollView } from "react-native";
import { searchProducts, checkout, CartItem, Product } from "../../src/db/repos";
import { refreshCatalog } from "../../src/sync/engine";
import { hub, creds } from "../../src/lib/api";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useStore } from "../../src/store/store";
import { fmt } from "../_layout";

export default function Pos() {
  const [q, setQ] = useState("");
  const [prods, setProds] = useState<Product[]>([]);

  const [sheet, setSheet] = useState(false);
  const { cart, addToCart, setQty, clearCart, cartTotal, ctx, set } = useStore();

  const [scanning, setScanning] = useState(false);
  const [perm, requestPerm] = useCameraPermissions();
  const openScan = async () => {
    if (!perm?.granted) { const r = await requestPerm(); if (!r.granted) return; }
    setScanning(true);
  };
  const onBarcode = ({ data }: { data: string }) => {
    setScanning(false); setQ(data);   // search filters by barcode — exact match adds via tap
  };
  const [refreshing, setRefreshing] = useState(false);
  const [rc, setRc] = useState<any>(null);
  const [pays, setPays] = useState<{ m: string; a: string }[]>([{ m: "cash", a: "" }]);
  const paidC = () => pays.reduce((a, p) => a + Math.round((parseFloat(p.a) || 0) * 100), 0);
  const [dT, setDT] = useState<"pct" | "abs">("pct");
  const [dV, setDV] = useState("");
  const discC = () => dT === "pct"
    ? Math.min(total, Math.round(total * (parseFloat(dV) || 0) / 100))
    : Math.min(total, Math.round((parseFloat(dV) || 0) * 100));
  const eff = () => Math.max(0, total - discC());
  const [plist, setPlist] = useState<"retail" | "wholesale">("retail");
  const pp = (p: any) => plist === "wholesale" && p.price_wholesale_cents ? p.price_wholesale_cents : p.price_cents;
  const [vkids, setVkids] = useState<any[] | null>(null);
  const kids = (p: any) => prods.filter(x => x.parent_id != null && String(x.parent_id) === String(p.id));
  const [cust, setCust] = useState<string | null>(null);
  const [custs, setCusts] = useState<any[]>([]);
  const [newC, setNewC] = useState("");
  const [promo, setPromo] = useState("");
  const [promoCode, setPromoCode] = useState<string | null>(null);
  const [promoMsg, setPromoMsg] = useState("");
  const [promos, setPromos] = useState<any[]>([]);
  const applyPromo = () => {
    const p = promos.find(x => x.code === promo.trim().toUpperCase());
    if (!p) { setPromoMsg("Invalid code"); return; }
    if ((p.min_total || 0) * 100 > total) { setPromoMsg(`Needs ${fmt(p.min_total * 100)} minimum`); return; }
    setDT(p.kind === "abs" ? "abs" : "pct"); setDV(String(p.value));
    setPromoCode(p.code); setPromoMsg(`Applied ${p.code}`);
  };
  useEffect(() => {
    if (!sheet) return;
    (async () => { try { const c = await creds.load(); if (!c) return;
      const b = await hub.base(); setCusts(await hub.customers(b, c.device_key));
      setPromos(await hub.promos(b, c.device_key).catch(() => [])); } catch {} })();
  }, [sheet]);
  const reload = () => searchProducts(q).then(setProds);
  useEffect(() => { reload(); }, [q]);
  const pullRefresh = async () => {
    setRefreshing(true);
    try { await refreshCatalog(); } catch {}  // hub may be unreachable — keep local data
    await reload(); setRefreshing(false);
  };
  useEffect(() => { pullRefresh(); }, []);   // refresh catalog on screen open
  const items = Object.values(cart);
  const total = cartTotal();

  const charge = async () => {
    if (!ctx) return;
    try {
      const r = await checkout(ctx, items, pays.map(p => ({ method: p.m, amount: parseFloat(p.a) || 0 })), cust || undefined, discC(), promoCode || undefined);
      const paid = paidC();
      const lines = items.map(i => ({ name: i.name, qty: i.qty,
        total: Math.round(i.price_cents * i.qty * (1 - (i.discount_qty && i.qty >= i.discount_qty ? (i.discount_pct || 0) / 100 : 0))) }));
      setRc({ no: r.receipt_no, lines, total: r.total_cents, paid,
        tax: lines.filter(l => items.find(i => i.name === l.name)?.taxable).reduce((a, l) => a + Math.round(l.total * 0.16 / 1.16), 0),
        change: Math.max(0, paid - r.total_cents), cashier: ctx.cashier_name || "—",
        cust: cust || "Walk-in", disc: discC(), promo: promoCode, at: new Date().toLocaleString() });
      clearCart(); setSheet(false); setPays([{ m: "cash", a: "" }]); setCust(null); setDV(""); setPromo(""); setPromoCode(null); setPromoMsg("");
      set({ pending: useStore.getState().pending + 1 });
    } catch (e: any) { Alert.alert("Cannot complete sale", e.message); }
  };

  return (
    <View style={s.c}>
      <View style={s.top}>
        <Text style={s.brand}>ShujaaPOS</Text>
        <View style={{ flexDirection: "row", gap: 6, marginBottom: 8 }}>
          {(["retail", "wholesale"] as const).map(m => (
            <TouchableOpacity key={m} onPress={() => setPlist(m)} style={[s.plc, plist === m && s.plcOn]}>
              <Text style={[s.plcT, plist === m && { color: "#fff" }]}>{m === "retail" ? "Retail" : "Wholesale"}</Text>
            </TouchableOpacity>))}
        </View>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <TextInput style={[s.search, { flex: 1 }]} placeholder="Search or scan barcode…" placeholderTextColor="#8b86a8"
            value={q} onChangeText={setQ} autoCapitalize="none" />
          <TouchableOpacity style={s.cam} onPress={openScan}><Text style={{ fontSize: 18 }}>📷</Text></TouchableOpacity>
        </View>
      </View>
      <FlatList data={prods.filter(p => !p.parent_id)} keyExtractor={p => p.id} numColumns={2} contentContainerStyle={{ padding: 8 }}
        refreshing={refreshing} onRefresh={pullRefresh}
        renderItem={({ item: p }) => (
          <TouchableOpacity style={s.tile} disabled={p.stock <= 0}
            onPress={() => { const k = kids(p); const o = (p.pack_size || 0) > 1 ? [...k, { ...p, _pack: 1 }] : k;
              o.length ? setVkids(o) : addToCart({ ...p, price_cents: pp(p) }); }}>
            {p.image
              ? <Image source={{ uri: p.image }} style={s.img} resizeMode="cover" />
              : <View style={[s.img, s.imgPh]}><Text style={s.imgPhT}>{p.name.slice(0, 2).toUpperCase()}</Text></View>}
            <Text style={s.nm} numberOfLines={2}>{p.name}</Text>
            <Text style={s.pr}>{fmt(pp(p))}</Text>
            <Text style={[s.st, p.stock <= 10 && { color: "#f0a51f" }, p.stock <= 0 && { color: "#e05a5a" }]}>
              {p.stock <= 0 ? "out" : `${p.stock} left`}{cart[p.id] ? `  ×${cart[p.id].qty}` : ""}</Text>
          </TouchableOpacity>)} />
      {items.length > 0 && (
        <View style={s.tray}>
          <FlatList data={items} horizontal keyExtractor={i => i.id} showsHorizontalScrollIndicator={false}
            renderItem={({ item: i }) => (
              <View style={s.ci}>
                <Text style={s.ciN} numberOfLines={1}>{i.name}</Text>
                <View style={s.ciR}>
                  <TouchableOpacity onPress={() => setQty(i.id, i.qty - 1)}><Text style={s.ciB}>−</Text></TouchableOpacity>
                  <Text style={s.ciQ}>{i.qty}</Text>
                  <TouchableOpacity onPress={() => setQty(i.id, i.qty + 1)}><Text style={s.ciB}>+</Text></TouchableOpacity>
                </View>
              </View>)} />
          <View style={s.pay}>
            <Text style={s.payT}>{fmt(total)}</Text>
            <TouchableOpacity style={s.btn} onPress={() => setSheet(true)}>
              <Text style={s.btnT}>Charge</Text></TouchableOpacity>
          </View>
        </View>)}
      <Modal visible={scanning} animationType="slide">
        <View style={{ flex: 1, backgroundColor: "#000" }}>
          <CameraView style={{ flex: 1 }} facing="back"
            barcodeScannerSettings={{ barcodeTypes: ["ean13", "ean8", "upc_a", "upc_e", "code128", "code39", "qr", "itf14", "datamatrix"] }}
            onBarcodeScanned={onBarcode} />
          <TouchableOpacity style={{ position: "absolute", bottom: 50, alignSelf: "center", padding: 14 }}
            onPress={() => setScanning(false)}><Text style={{ color: "#fff", fontWeight: "700" }}>Cancel</Text></TouchableOpacity>
        </View>
      </Modal>
      <Modal visible={!!vkids} transparent animationType="fade">
        <View style={s.mo}><View style={s.ms}>
          <Text style={s.msH}>Choose variant</Text>
          {vkids?.map(v => (
            <TouchableOpacity key={v._pack ? "pack" : v.id} disabled={v.stock <= 0}
              style={[s.pchip, { marginBottom: 6, flexDirection: "row", justifyContent: "space-between" }]}
              onPress={() => {
                if (v._pack) { const u = Math.round((v.pack_price_cents ?? pp(v) * v.pack_size) / v.pack_size);
                  addToCart({ ...v, price_cents: u }); setQty(v.id, v.pack_size); }
                else addToCart({ ...v, price_cents: pp(v), name: v.variant_label ? `${v.name} · ${v.variant_label}` : v.name });
                setVkids(null); }}>
              <Text style={s.pchipT}>{v._pack ? `Pack ×${v.pack_size}` : v.variant_label || v.name}</Text>
              <Text style={s.pchipT}>{v._pack ? fmt(v.pack_price_cents ?? pp(v) * v.pack_size) : fmt(pp(v))}{v.stock <= 0 ? " · out" : ` · ${v.stock}`}</Text>
            </TouchableOpacity>))}
          <TouchableOpacity onPress={() => setVkids(null)}><Text style={s.cancel}>Cancel</Text></TouchableOpacity>
        </View></View>
      </Modal>
      <Modal visible={sheet} transparent animationType="slide">
        <View style={s.mo}><View style={s.ms}>
          <Text style={s.msH}>Total {fmt(eff())}</Text>
          <Text style={{ color: "#6d6790", fontSize: 12, marginBottom: 4 }}>Discount</Text>
          <View style={{ flexDirection: "row", gap: 6, marginBottom: 8 }}>
            {(["pct", "abs"] as const).map(t => (
              <TouchableOpacity key={t} onPress={() => setDT(t)} style={[s.pchip, dT === t && s.pchipOn]}>
                <Text style={[s.pchipT, dT === t && { color: "#fff" }]}>{t === "pct" ? "%" : "KSh"}</Text></TouchableOpacity>))}
            <TextInput style={[s.cash, { flex: 1, marginBottom: 0, padding: 10, fontSize: 14 }]}
              placeholder={dT === "pct" ? "e.g. 10" : "e.g. 50"} placeholderTextColor="#8b86a8"
              keyboardType="decimal-pad" value={dV} onChangeText={setDV} />
            {discC() > 0 && <Text style={{ alignSelf: "center", color: "#3ecf8e", fontWeight: "700" }}>−{fmt(discC())}</Text>}
          </View>
          <Text style={{ color: "#6d6790", fontSize: 12, marginBottom: 4 }}>Promo code</Text>
          <TextInput style={[s.cash, { marginBottom: 4, padding: 10, fontSize: 14 }]} placeholder="e.g. KARIBU10"
            placeholderTextColor="#8b86a8" autoCapitalize="characters" value={promo} onChangeText={setPromo}
            onSubmitEditing={applyPromo} onBlur={promo ? applyPromo : undefined} returnKeyType="done" />
          {promoMsg ? <Text style={{ color: promoCode ? "#3ecf8e" : "#e05a5a", fontSize: 12, marginBottom: 6 }}>{promoMsg}</Text> : null}
          <Text style={{ color: "#6d6790", fontSize: 12, marginBottom: 4 }}>Customer</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 6 }}>
            <TouchableOpacity onPress={() => setCust(null)} style={[s.pchip, !cust && s.pchipOn]}>
              <Text style={[s.pchipT, !cust && { color: "#fff" }]}>Walk-in</Text></TouchableOpacity>
            {custs.map(c => (
              <TouchableOpacity key={c.id} onPress={() => setCust(c.name)}
                style={[s.pchip, cust === c.name && s.pchipOn, { marginLeft: 6 }]}>
                <Text style={[s.pchipT, cust === c.name && { color: "#fff" }]}>{c.name}</Text></TouchableOpacity>))}
            <TextInput style={[s.cash, { width: 130, marginBottom: 0, marginLeft: 6, padding: 10, fontSize: 13 }]}
              placeholder="+ new" placeholderTextColor="#8b86a8" value={newC} onChangeText={setNewC}
              onSubmitEditing={async () => {
                if (!newC.trim()) return;
                try { const c = await creds.load(); if (!c) return; const b = await hub.base();
                  const r = await hub.addCustomer(b, c.device_key, { name: newC.trim() });
                  setCusts([...custs, { id: r.id, name: newC.trim() }]); setCust(newC.trim()); setNewC("");
                } catch {}
              }} />
          </ScrollView>
          {pays.map((p, i) => (
            <View key={i} style={{ flexDirection: "row", gap: 6, marginBottom: 8 }}>
              {["cash", "mpesa", "card", "credit"].map(m => (
                <TouchableOpacity key={m} onPress={() => { const q = [...pays]; q[i] = { ...q[i], m }; setPays(q); }}
                  style={[s.pchip, p.m === m && s.pchipOn]}>
                  <Text style={[s.pchipT, p.m === m && { color: "#fff" }]}>
                    {m === "mpesa" ? "M-Pesa" : m[0].toUpperCase() + m.slice(1)}</Text>
                </TouchableOpacity>))}
              <TextInput style={[s.cash, { flex: 1, marginBottom: 0 }]} placeholder="Amount"
                placeholderTextColor="#8b86a8" keyboardType="decimal-pad" value={p.a} autoFocus={i === 0}
                onChangeText={v => { const q = [...pays]; q[i] = { ...q[i], a: v }; setPays(q); }} />
            </View>))}
          {pays.length < 2
            ? <TouchableOpacity onPress={() => setPays([...pays, { m: "mpesa", a: ((eff() - paidC()) / 100).toFixed(2) }])}>
                <Text style={{ color: "#8b5cf6", fontWeight: "700", marginBottom: 8 }}>+ Split payment</Text></TouchableOpacity>
            : <TouchableOpacity onPress={() => setPays([pays[0]])}>
                <Text style={{ color: "#6d6790", marginBottom: 8 }}>Remove split</Text></TouchableOpacity>}
          <Text style={s.chg}>{paidC() < eff() ? `Remaining ${fmt(eff() - paidC())}` : `Change ${fmt(paidC() - eff())}`}</Text>
          <TouchableOpacity style={s.btn} onPress={charge}><Text style={s.btnT}>Complete sale</Text></TouchableOpacity>
          <TouchableOpacity onPress={() => setSheet(false)}><Text style={s.cancel}>Cancel</Text></TouchableOpacity>
        </View></View>
      </Modal>
      <Modal visible={!!rc} transparent animationType="fade">
        <View style={s.mo}><View style={s.ms}>
          <ScrollView style={{ maxHeight: 420 }}>
            <Text style={s.rcT}>SHUJAAPOS</Text>
            <Text style={s.rcS}>RECEIPT {rc?.no}</Text>
            <Text style={s.rcS}>{rc?.at} · {rc?.cashier}</Text>
            <View style={s.rcD} />
            {rc?.lines.map((l: any, i: number) => (
              <View key={i} style={s.rcR}>
                <Text style={s.rcN}>{l.name} <Text style={s.rcS}>×{l.qty}</Text></Text>
                <Text style={s.rcN}>{fmt(l.total)}</Text>
              </View>))}
            <View style={s.rcD} />
            <View style={s.rcR}><Text style={s.rcS}>Customer</Text><Text style={s.rcS}>{rc?.cust || "Walk-in"}</Text></View>
            <View style={s.rcR}><Text style={s.rcS}>VAT incl. (16%)</Text><Text style={s.rcS}>{fmt(rc?.tax || 0)}</Text></View>
            {rc?.promo && <View style={s.rcR}><Text style={s.rcS}>Promo</Text><Text style={s.rcS}>{rc.promo}</Text></View>}
            {rc?.disc > 0 && <View style={s.rcR}><Text style={s.rcS}>Discount</Text><Text style={s.rcS}>−{fmt(rc.disc)}</Text></View>}
            <View style={s.rcR}><Text style={s.rcTot}>TOTAL</Text><Text style={s.rcTot}>{fmt(rc?.total || 0)}</Text></View>
            <View style={s.rcR}><Text style={s.rcS}>Cash tendered</Text><Text style={s.rcS}>{fmt(rc?.paid || 0)}</Text></View>
            <View style={s.rcR}><Text style={s.rcS}>Change</Text><Text style={s.rcS}>{fmt(rc?.change || 0)}</Text></View>
            <View style={s.rcD} />
            <Text style={[s.rcS, { marginVertical: 4 }]}>Thank you!</Text>
          </ScrollView>
          <TouchableOpacity style={s.btn} onPress={() => Share.share({ message: rcText(rc) })}>
            <Text style={s.btnT}>Share receipt</Text></TouchableOpacity>
          <TouchableOpacity onPress={() => setRc(null)}><Text style={s.cancel}>Done</Text></TouchableOpacity>
        </View></View>
      </Modal>
    </View>
  );
}

const rcText = (rc: any) => rc ? [
  "SHUJAAPOS", `RECEIPT ${rc.no}`, `${rc.at} · ${rc.cashier}`, "-".repeat(32),
  ...rc.lines.map((l: any) => `${l.name} x${l.qty}  KSh ${(l.total / 100).toFixed(2)}`),
  "-".repeat(32), `TOTAL   KSh ${(rc.total / 100).toFixed(2)}`,
  `Cash    KSh ${(rc.paid / 100).toFixed(2)}`, `Change  KSh ${(rc.change / 100).toFixed(2)}`,
  "-".repeat(32), "Thank you!"].join("\n") : "";

const s = StyleSheet.create({
  c: { flex: 1, backgroundColor: "#14102b", paddingTop: 56 },
  top: { paddingHorizontal: 14 },
  brand: { color: "#fff", fontSize: 20, fontWeight: "800", marginBottom: 8 },
  search: { backgroundColor: "#1e1840", borderRadius: 12, padding: 13, color: "#fff", fontSize: 15 },
  cam: { backgroundColor: "#45209f", borderRadius: 12, paddingHorizontal: 14, justifyContent: "center" },
  tile: { flex: 1, backgroundColor: "#1e1840", borderRadius: 14, margin: 5, padding: 13 },
  img: { width: "100%", height: 72, borderRadius: 9, marginBottom: 8 },
  imgPh: { backgroundColor: "#2a2350", alignItems: "center", justifyContent: "center" },
  imgPhT: { color: "#8b5cf6", fontWeight: "800", fontSize: 20 },
  nm: { color: "#ece9f8", fontWeight: "600", minHeight: 34 },
  pr: { color: "#8b5cf6", fontWeight: "800", marginTop: 5, fontSize: 15 },
  st: { color: "#9a93c2", fontSize: 12, marginTop: 3 },
  tray: { backgroundColor: "#1e1840", borderTopLeftRadius: 18, borderTopRightRadius: 18, paddingTop: 10 },
  ci: { backgroundColor: "#2a2350", borderRadius: 10, padding: 10, marginHorizontal: 5, width: 140 },
  ciN: { color: "#ece9f8", fontSize: 13 },
  ciR: { flexDirection: "row", alignItems: "center", marginTop: 6, gap: 10 },
  ciB: { color: "#8b5cf6", fontSize: 20, fontWeight: "800", paddingHorizontal: 6 },
  ciQ: { color: "#fff", fontWeight: "700", fontSize: 15 },
  pay: { flexDirection: "row", alignItems: "center", padding: 14, gap: 14 },
  payT: { flex: 1, color: "#fff", fontSize: 20, fontWeight: "800" },
  btn: { backgroundColor: "#45209f", borderRadius: 12, paddingVertical: 14, paddingHorizontal: 26, alignItems: "center" },
  btnT: { color: "#fff", fontWeight: "800", fontSize: 16 },
  mo: { flex: 1, backgroundColor: "#000a", justifyContent: "flex-end" },
  ms: { backgroundColor: "#fff", borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 24 },
  msH: { fontSize: 22, fontWeight: "800", color: "#14102b", marginBottom: 14 },
  cash: { borderWidth: 1, borderColor: "#e7e3f4", borderRadius: 12, padding: 15, fontSize: 18, marginBottom: 8, color: "#14102b" },
  chg: { color: "#3ecf8e", fontWeight: "700", marginBottom: 12, fontSize: 16 },
  cancel: { textAlign: "center", color: "#6d6790", padding: 14 },
  pchip: { backgroundColor: "#ece9f8", borderRadius: 9, paddingVertical: 12, paddingHorizontal: 10 },
  pchipOn: { backgroundColor: "#45209f" },
  pchipT: { color: "#14102b", fontWeight: "700", fontSize: 12 },
  plc: { backgroundColor: "#1e1840", borderRadius: 9, paddingVertical: 6, paddingHorizontal: 12 },
  plcOn: { backgroundColor: "#45209f" },
  plcT: { color: "#9a93c2", fontWeight: "700", fontSize: 12 },
  rcT: { fontSize: 20, fontWeight: "800", color: "#14102b", textAlign: "center" },
  rcS: { color: "#6d6790", fontSize: 12, textAlign: "center" },
  rcD: { borderTopWidth: 1, borderStyle: "dashed", borderColor: "#d8d2ef", marginVertical: 8 },
  rcR: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 3 },
  rcN: { color: "#14102b", fontSize: 14 },
  rcTot: { color: "#14102b", fontSize: 17, fontWeight: "800" },
});
