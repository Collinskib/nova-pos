import { useEffect, useState } from "react";
import { View, Text, TextInput, FlatList, TouchableOpacity, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { hub, creds } from "../../src/lib/api";

const money = (v: any) => `KSh ${Number(v || 0).toFixed(2)}`;

export default function Products() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    (async () => {
      try {
        const c = await creds.load(); if (!c) throw new Error("not paired");
        const b = await hub.base();
        setRows(await hub.products(b, c.device_key));
      } catch (e: any) { setErr(e.message); }
    })();
  }, []);
  const data = rows.filter(p => (p.name + (p.barcode || "")).toLowerCase().includes(q.toLowerCase()));
  const low = (p: any) => Number(p.stock) <= 10;
  return (
    <View style={s.c}>
      <TouchableOpacity onPress={() => router.back()}><Text style={s.back}>‹ Admin</Text></TouchableOpacity>
      <Text style={s.brand}>Products & Stock</Text>
      <TextInput style={s.search} placeholder="Search name or barcode…" placeholderTextColor="#8b86a8"
        value={q} onChangeText={setQ} />
      <FlatList data={data} keyExtractor={p => String(p.id)} contentContainerStyle={{ paddingVertical: 10 }}
        renderItem={({ item: p }) => (
          <View style={s.li}>
            <View style={{ flex: 1 }}>
              <Text style={s.ln}>{p.name}</Text>
              <Text style={s.ls}>{p.barcode || "—"} · {money(p.price)}</Text>
            </View>
            <Text style={[s.badge, low(p) ? s.low : s.ok]}>{p.stock} left</Text>
          </View>)}
        ListEmptyComponent={<Text style={s.sub}>{err ? `Couldn't reach the hub: ${err}` : "No products."}</Text>} />
    </View>
  );
}

const s = StyleSheet.create({
  c: { flex: 1, backgroundColor: "#14102b", padding: 16, paddingTop: 56 },
  back: { color: "#8b5cf6", fontSize: 15, fontWeight: "600", marginBottom: 4 },
  brand: { color: "#fff", fontSize: 22, fontWeight: "800", marginBottom: 10 },
  search: { backgroundColor: "#1e1840", borderRadius: 12, padding: 13, color: "#fff" },
  li: { flexDirection: "row", alignItems: "center", backgroundColor: "#1e1840", borderRadius: 12, padding: 13, marginBottom: 6 },
  ln: { color: "#ece9f8", fontWeight: "600" },
  ls: { color: "#9a93c2", fontSize: 12, marginTop: 2 },
  badge: { fontWeight: "800", fontSize: 12, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8, overflow: "hidden" },
  ok: { color: "#3ecf8e", backgroundColor: "#1f3a2f" },
  low: { color: "#f0a51f", backgroundColor: "#3a2f1f" },
  sub: { color: "#9a93c2", marginTop: 20, textAlign: "center" },
});
