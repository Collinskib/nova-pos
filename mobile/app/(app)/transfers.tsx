import { useEffect, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, FlatList, Alert, StyleSheet, Modal, ScrollView } from "react-native";
import { listTransfers, createTransfer, dispatchTransfer, receiveTransfer, searchProducts } from "../../src/db/repos";
import { useStore } from "../../src/store/store";

const STATUS: Record<string, [string, string]> = {
  DRAFT: ["Draft", "#9a93c2"], DISPATCHED: ["Dispatched", "#f0a51f"],
  IN_TRANSIT: ["In transit", "#f0a51f"], RECEIVED: ["Received", "#3ecf8e"], CANCELLED: ["Cancelled", "#e05a5a"]};

export default function Transfers() {
  const { ctx } = useStore();
  const [rows, setRows] = useState<any[]>([]);
  const [show, setShow] = useState(false);
  const [rcv, setRcv] = useState<any | null>(null);
  const [qtys, setQtys] = useState<Record<string, { got: string; dmg: string }>>({});
  const [note, setNote] = useState("");
  const [toBranch, setToBranch] = useState("");
  const [pick, setPick] = useState<any[]>([]);
  const [prods, setProds] = useState<any[]>([]);
  const [q, setQ] = useState("");

  const reload = () => listTransfers().then(setRows);
  useEffect(() => { reload(); }, []);
  useEffect(() => { if (show) searchProducts(q).then(setProds); }, [q, show]);

  const create = async () => {
    if (!ctx || !toBranch.trim() || !pick.length) return;
    try {
      await createTransfer(ctx, toBranch.trim(), pick.map(p => ({ product_id: p.id, qty: p.qty })), note);
      setShow(false); setPick([]); setNote(""); setToBranch(""); reload();
    } catch (e: any) { Alert.alert("Transfer failed", e.message); }
  };

  const dispatch = async (t: any) => {
    await dispatchTransfer(ctx, t.id); reload();
    Alert.alert("Dispatched", `${t.id.slice(0, 8)}… is now in transit.`);
  };

  const receive = async () => {
    const receipts = Object.entries(qtys)
      .map(([product_id, v]) => ({ product_id, qty: parseFloat(v.got) || 0, damaged: parseFloat(v.dmg) || 0 }))
      .filter(r => r.qty > 0 || r.damaged > 0);
    if (!receipts.length) return setRcv(null);
    const full = await receiveTransfer(ctx, rcv.id, receipts);
    setRcv(null); reload();
    Alert.alert(full ? "Received complete" : "Partial receipt recorded");
  };

  return (
    <View style={s.c}>
      <View style={s.hdr}>
        <Text style={s.brand}>Transfers</Text>
        <TouchableOpacity style={s.btn} onPress={() => setShow(true)}><Text style={s.btnT}>+ New</Text></TouchableOpacity>
      </View>
      <FlatList data={rows} keyExtractor={t => t.id} contentContainerStyle={{ padding: 10 }}
        ListEmptyComponent={<Text style={s.sub}>No transfers yet.</Text>}
        renderItem={({ item: t }) => {
          const [label, col] = STATUS[t.status] || [t.status, "#9a93c2"];
          const items = JSON.parse(t.items || "[]");
          const incoming = t.to_branch_id === ctx?.branch;
          return (
            <View style={s.card}>
              <View style={s.row}>
                <Text style={s.tn}>{incoming ? "←" : "→"} {t.id.slice(0, 8)}…</Text>
                <Text style={[s.st, { color: col }]}>{label}</Text>
              </View>
              <Text style={s.ts}>{incoming ? `from ${t.from_branch_id}` : `to ${t.to_branch_id}`}{t.note ? ` · ${t.note}` : ""}</Text>
              {items.map((i: any) => (
                <Text key={i.product_id} style={s.ti}>{i.name} — sent {i.qty_sent}, received {i.qty_received}{i.qty_damaged ? `, damaged ${i.qty_damaged}` : ""}</Text>))}
              {!incoming && t.status === "DRAFT" &&
                <TouchableOpacity style={[s.act, { backgroundColor: "#45209f" }]} onPress={() => dispatch(t)}>
                  <Text style={s.actT}>Dispatch</Text></TouchableOpacity>}
              {incoming && (t.status === "DISPATCHED" || t.status === "IN_TRANSIT") &&
                <TouchableOpacity style={[s.act, { backgroundColor: "#3ecf8e" }]}
                  onPress={() => { setRcv(t); setQtys(Object.fromEntries(items.map((i: any) =>
                    [i.product_id, { got: String(i.qty_sent - i.qty_received), dmg: "0" }]))); }}>
                  <Text style={s.actT}>Receive</Text></TouchableOpacity>}
            </View>);
        }} />

      {/* create */}
      <Modal visible={show} transparent animationType="slide"><View style={s.mo}><View style={s.ms}>
        <Text style={s.msH}>New transfer</Text>
        <TextInput style={s.in} placeholder="To branch ID/name" placeholderTextColor="#8b86a8" value={toBranch} onChangeText={setToBranch} />
        <TextInput style={s.in} placeholder="Note (optional)" placeholderTextColor="#8b86a8" value={note} onChangeText={setNote} />
        <TextInput style={s.in} placeholder="Search products…" placeholderTextColor="#8b86a8" value={q} onChangeText={setQ} />
        <ScrollView style={{ maxHeight: 220 }}>
          {prods.filter(p => !pick.find(x => x.id === p.id)).slice(0, 15).map(p => (
            <TouchableOpacity key={p.id} style={s.li} onPress={() => setPick([...pick, { ...p, qty: 1 }])}>
              <Text style={s.ln}>{p.name} <Text style={s.ls}>{p.stock} in stock</Text></Text><Text style={s.add}>+</Text>
            </TouchableOpacity>))}
          {pick.map(p => (
            <View key={p.id} style={s.li}>
              <Text style={s.ln}>{p.name}</Text>
              <View style={s.qr}>
                <TouchableOpacity onPress={() => setPick(pick.map(x => x.id === p.id ? { ...x, qty: Math.max(1, x.qty - 1) } : x))}><Text style={s.qb}>−</Text></TouchableOpacity>
                <Text style={s.qq}>{p.qty}</Text>
                <TouchableOpacity onPress={() => setPick(pick.map(x => x.id === p.id ? { ...x, qty: Math.min(x.qty + 1, p.stock) } : x))}><Text style={s.qb}>+</Text></TouchableOpacity>
              </View>
            </View>))}
        </ScrollView>
        <TouchableOpacity style={s.btn} onPress={create}><Text style={s.btnT}>Create draft ({pick.length})</Text></TouchableOpacity>
        <TouchableOpacity onPress={() => setShow(false)}><Text style={s.cancel}>Cancel</Text></TouchableOpacity>
      </View></View></Modal>

      {/* receive */}
      <Modal visible={!!rcv} transparent animationType="slide"><View style={s.mo}><View style={s.ms}>
        <Text style={s.msH}>Receive {rcv?.id.slice(0, 8)}…</Text>
        {rcv && JSON.parse(rcv.items || "[]").map((i: any) => (
          <View key={i.product_id} style={s.li}>
            <Text style={s.ln}>{i.name}<Text style={s.ls}> sent {i.qty_sent}, already got {i.qty_received}</Text></Text>
            <View style={s.qr}>
              <TextInput style={s.qi} placeholder="got" placeholderTextColor="#8b86a8" keyboardType="decimal-pad"
                value={qtys[i.product_id]?.got} onChangeText={v => setQtys({ ...qtys, [i.product_id]: { ...qtys[i.product_id], got: v } })} />
              <TextInput style={s.qi} placeholder="damaged" placeholderTextColor="#8b86a8" keyboardType="decimal-pad"
                value={qtys[i.product_id]?.dmg} onChangeText={v => setQtys({ ...qtys, [i.product_id]: { ...qtys[i.product_id], dmg: v } })} />
            </View>
          </View>))}
        <Text style={s.ls}>Unsent/damaged quantities are recorded as discrepancies — stock only moves for what physically arrives.</Text>
        <TouchableOpacity style={s.btn} onPress={receive}><Text style={s.btnT}>Record receipt</Text></TouchableOpacity>
        <TouchableOpacity onPress={() => setRcv(null)}><Text style={s.cancel}>Cancel</Text></TouchableOpacity>
      </View></View></Modal>
    </View>
  );
}

const s = StyleSheet.create({
  c: { flex: 1, backgroundColor: "#14102b", paddingTop: 56 },
  hdr: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: 14 },
  brand: { color: "#fff", fontSize: 22, fontWeight: "800" },
  sub: { color: "#9a93c2", textAlign: "center", marginTop: 30 },
  card: { backgroundColor: "#1e1840", borderRadius: 14, padding: 14, marginBottom: 10 },
  row: { flexDirection: "row", justifyContent: "space-between" },
  tn: { color: "#ece9f8", fontWeight: "700" },
  st: { fontWeight: "700", fontSize: 13 },
  ts: { color: "#9a93c2", fontSize: 12, marginVertical: 4 },
  ti: { color: "#cfc6ee", fontSize: 13, marginTop: 3 },
  act: { borderRadius: 10, padding: 11, alignItems: "center", marginTop: 10 },
  actT: { color: "#fff", fontWeight: "700" },
  mo: { flex: 1, backgroundColor: "#000a", justifyContent: "flex-end" },
  ms: { backgroundColor: "#fff", borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 22, maxHeight: "88%" },
  msH: { fontSize: 20, fontWeight: "800", color: "#14102b", marginBottom: 12 },
  in: { borderWidth: 1, borderColor: "#e7e3f4", borderRadius: 12, padding: 13, fontSize: 15, marginBottom: 10, color: "#14102b" },
  li: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 9, borderBottomWidth: 1, borderBottomColor: "#f0edf8" },
  ln: { color: "#14102b", fontWeight: "600", flex: 1 },
  ls: { color: "#8b86a8", fontSize: 12 },
  add: { color: "#45209f", fontSize: 20, fontWeight: "800", paddingHorizontal: 8 },
  qr: { flexDirection: "row", alignItems: "center", gap: 8 },
  qb: { color: "#45209f", fontSize: 20, fontWeight: "800", paddingHorizontal: 8 },
  qq: { fontWeight: "800", color: "#14102b" },
  qi: { borderWidth: 1, borderColor: "#e7e3f4", borderRadius: 8, padding: 8, width: 64, textAlign: "center", color: "#14102b" },
  btn: { backgroundColor: "#45209f", borderRadius: 12, padding: 15, alignItems: "center", marginTop: 12 },
  btnT: { color: "#fff", fontWeight: "800" },
  cancel: { textAlign: "center", color: "#6d6790", padding: 14 },
});
