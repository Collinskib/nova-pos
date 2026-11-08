import { useEffect, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, FlatList, Alert, StyleSheet, Modal, Image, Share, ScrollView } from "react-native";
import { searchProducts, checkout, CartItem, Product } from "../../src/db/repos";
import { refreshCatalog } from "../../src/sync/engine";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useStore } from "../../src/store/store";
import { fmt } from "../_layout";

export default function Pos() {
  const [q, setQ] = useState("");
  const [prods, setProds] = useState<Product[]>([]);
  const [cash, setCash] = useState("");
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
      const r = await checkout(ctx, items, { method: "cash", amount: parseFloat(cash) || total / 100 });
      const paid = Math.round((parseFloat(cash) || total / 100) * 100);
      const lines = items.map(i => ({ name: i.name, qty: i.qty,
        total: Math.round(i.price_cents * i.qty * (1 - (i.discount_qty && i.qty >= i.discount_qty ? (i.discount_pct || 0) / 100 : 0))) }));
      setRc({ no: r.receipt_no, lines, total: r.total_cents, paid,
        tax: lines.filter(l => items.find(i => i.name === l.name)?.taxable).reduce((a, l) => a + Math.round(l.total * 0.16 / 1.16), 0),
        change: Math.max(0, paid - r.total_cents), cashier: ctx.cashier_name || "—",
        at: new Date().toLocaleString() });
      clearCart(); setSheet(false); setCash("");
      set({ pending: useStore.getState().pending + 1 });
    } catch (e: any) { Alert.alert("Cannot complete sale", e.message); }
  };

  return (
    <View style={s.c}>
      <View style={s.top}>
        <Text style={s.brand}>Nova POS</Text>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <TextInput style={[s.search, { flex: 1 }]} placeholder="Search or scan barcode…" placeholderTextColor="#8b86a8"
            value={q} onChangeText={setQ} autoCapitalize="none" />
          <TouchableOpacity style={s.cam} onPress={openScan}><Text style={{ fontSize: 18 }}>📷</Text></TouchableOpacity>
        </View>
      </View>
      <FlatList data={prods} keyExtractor={p => p.id} numColumns={2} contentContainerStyle={{ padding: 8 }}
        refreshing={refreshing} onRefresh={pullRefresh}
        renderItem={({ item: p }) => (
          <TouchableOpacity style={s.tile} onPress={() => addToCart(p)} disabled={p.stock <= 0}>
            {p.image
              ? <Image source={{ uri: p.image }} style={s.img} resizeMode="cover" />
              : <View style={[s.img, s.imgPh]}><Text style={s.imgPhT}>{p.name.slice(0, 2).toUpperCase()}</Text></View>}
            <Text style={s.nm} numberOfLines={2}>{p.name}</Text>
            <Text style={s.pr}>{fmt(p.price_cents)}</Text>
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
      <Modal visible={sheet} transparent animationType="slide">
        <View style={s.mo}><View style={s.ms}>
          <Text style={s.msH}>Total {fmt(total)}</Text>
          <TextInput style={s.cash} placeholder="Cash received" placeholderTextColor="#8b86a8"
            keyboardType="decimal-pad" value={cash} onChangeText={setCash} autoFocus />
          {cash !== "" && <Text style={s.chg}>Change {fmt(Math.max(0, Math.round(parseFloat(cash || "0") * 100) - total))}</Text>}
          <TouchableOpacity style={s.btn} onPress={charge}><Text style={s.btnT}>Complete sale</Text></TouchableOpacity>
          <TouchableOpacity onPress={() => setSheet(false)}><Text style={s.cancel}>Cancel</Text></TouchableOpacity>
        </View></View>
      </Modal>
      <Modal visible={!!rc} transparent animationType="fade">
        <View style={s.mo}><View style={s.ms}>
          <ScrollView style={{ maxHeight: 420 }}>
            <Text style={s.rcT}>NOVA POS</Text>
            <Text style={s.rcS}>RECEIPT {rc?.no}</Text>
            <Text style={s.rcS}>{rc?.at} · {rc?.cashier}</Text>
            <View style={s.rcD} />
            {rc?.lines.map((l: any, i: number) => (
              <View key={i} style={s.rcR}>
                <Text style={s.rcN}>{l.name} <Text style={s.rcS}>×{l.qty}</Text></Text>
                <Text style={s.rcN}>{fmt(l.total)}</Text>
              </View>))}
            <View style={s.rcD} />
            <View style={s.rcR}><Text style={s.rcS}>VAT incl. (16%)</Text><Text style={s.rcS}>{fmt(rc?.tax || 0)}</Text></View>
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
  "NOVA POS", `RECEIPT ${rc.no}`, `${rc.at} · ${rc.cashier}`, "-".repeat(32),
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
  rcT: { fontSize: 20, fontWeight: "800", color: "#14102b", textAlign: "center" },
  rcS: { color: "#6d6790", fontSize: 12, textAlign: "center" },
  rcD: { borderTopWidth: 1, borderStyle: "dashed", borderColor: "#d8d2ef", marginVertical: 8 },
  rcR: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 3 },
  rcN: { color: "#14102b", fontSize: 14 },
  rcTot: { color: "#14102b", fontSize: 17, fontWeight: "800" },
});
