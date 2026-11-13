import { useEffect, useState } from "react";
import { View, Text, TextInput, FlatList, StyleSheet } from "react-native";
import { recentSales, Sale } from "../../src/db/repos";
import { fmt } from "../_layout";

export default function Sales() {
  const [rows, setRows] = useState<Sale[]>([]);
  const [q, setQ] = useState("");
  useEffect(() => { recentSales(200).then(setRows); }, []);
  const data = rows.filter(r => r.receipt_no.includes(q.toUpperCase()));
  return (
    <View style={s.c}>
      <Text style={s.brand}>Sales history <Text style={s.loc}>(device-local)</Text></Text>
      <TextInput style={s.search} placeholder="Search receipt no…" placeholderTextColor="#8b86a8"
        value={q} onChangeText={setQ} autoCapitalize="characters" />
      <FlatList data={data} keyExtractor={(r, i) => `${r.id}:${i}`} contentContainerStyle={{ paddingVertical: 10 }}
        renderItem={({ item: r }) => (
          <View style={s.li}>
            <View>
              <Text style={s.ln}>{r.receipt_no}</Text>
              <Text style={s.ls}>{new Date(r.created_at).toLocaleString()}</Text>
            </View>
            <View style={{ alignItems: "flex-end" }}>
              <Text style={[s.lt, r.status === "void" && { color: "#e05a5a" }]}>
                {r.status === "void" ? "void" : fmt(r.total_cents)}</Text>
              {r.paid_cents != null && r.status !== "void" &&
                <Text style={s.ls}>Paid {fmt(r.paid_cents)} · Change {fmt(Math.max(0, r.paid_cents - r.total_cents))}</Text>}
            </View>
          </View>)}
        ListEmptyComponent={<Text style={s.sub}>No sales recorded on this device.</Text>} />
    </View>
  );
}

const s = StyleSheet.create({
  c: { flex: 1, backgroundColor: "#14102b", padding: 16, paddingTop: 56 },
  brand: { color: "#fff", fontSize: 22, fontWeight: "800", marginBottom: 10 },
  loc: { color: "#9a93c2", fontSize: 13, fontWeight: "400" },
  search: { backgroundColor: "#1e1840", borderRadius: 12, padding: 13, color: "#fff" },
  li: { flexDirection: "row", justifyContent: "space-between", backgroundColor: "#1e1840", borderRadius: 12, padding: 13, marginBottom: 6 },
  ln: { color: "#ece9f8", fontWeight: "600" },
  ls: { color: "#9a93c2", fontSize: 12, marginTop: 2 },
  lt: { color: "#3ecf8e", fontWeight: "800" },
  sub: { color: "#9a93c2", marginTop: 20, textAlign: "center" },
});
