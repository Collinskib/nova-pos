import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView } from "react-native";
import { todayTotals, recentSales } from "../../src/db/repos";
import { useStore } from "../../src/store/store";
import { fmt } from "../_layout";

const LABEL: Record<string, [string, string]> = {
  offline: ["Offline — working locally", "#e05a5a"],
  pending: ["Sync pending — changes queued", "#f0a51f"],
  syncing: ["Syncing…", "#8b5cf6"],
  synced: ["Synced — all acknowledged", "#3ecf8e"],
  error: ["Sync error — attention needed", "#e05a5a"],
};

export default function Dashboard() {
  const [t, setT] = useState({ count: 0, total: 0 });
  const [recent, setRecent] = useState<any[]>([]);
  const { syncState, pending, ctx, lastSync } = useStore();
  useEffect(() => {
    const load = () => { todayTotals().then(setT); recentSales(5).then(setRecent); };
    load(); const i = setInterval(load, 5000); return () => clearInterval(i);
  }, []);

  const [label, color] = LABEL[syncState] ?? LABEL.offline;
  return (
    <ScrollView style={s.c}>
      <Text style={s.brand}>Today</Text>
      <View style={[s.pill, { borderColor: color }]}><View style={[s.dot, { backgroundColor: color }]} />
        <Text style={{ color }}>{label}{pending ? ` · ${pending} queued` : ""}</Text></View>
      {lastSync && <Text style={s.sub}>Last sync {new Date(lastSync).toLocaleTimeString()} · device-local figures</Text>}
      <View style={s.row}>
        <View style={s.kpi}><Text style={s.kv}>{t.count}</Text><Text style={s.kk}>Transactions</Text></View>
        <View style={s.kpi}><Text style={s.kv}>{fmt(t.total)}</Text><Text style={s.kk}>Collected</Text></View>
        <View style={s.kpi}><Text style={s.kv}>{pending}</Text><Text style={s.kk}>Unsynced</Text></View>
      </View>
      <Text style={s.h}>Recent transactions</Text>
      {recent.map((r, i) => (
        <View key={`${r.id}:${i}`} style={s.li}>
          <View><Text style={s.ln}>{r.receipt_no}</Text>
            <Text style={s.ls}>{new Date(r.created_at).toLocaleTimeString()}</Text></View>
          <Text style={[s.lt, r.status === "void" && { color: "#e05a5a" }]}>
            {r.status === "void" ? "void" : fmt(r.total_cents)}</Text>
        </View>))}
      {!recent.length && <Text style={s.sub}>No sales yet today.</Text>}
      <Text style={s.sub}>Branch {ctx?.branch} · Device {ctx?.device}</Text>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  c: { flex: 1, backgroundColor: "#14102b", padding: 16, paddingTop: 56 },
  brand: { color: "#fff", fontSize: 22, fontWeight: "800", marginBottom: 10 },
  pill: { flexDirection: "row", alignItems: "center", gap: 8, borderWidth: 1, borderRadius: 20, padding: 10, alignSelf: "flex-start" },
  dot: { width: 8, height: 8, borderRadius: 4 },
  sub: { color: "#9a93c2", fontSize: 12, marginTop: 10 },
  row: { flexDirection: "row", gap: 10, marginVertical: 16 },
  kpi: { flex: 1, backgroundColor: "#1e1840", borderRadius: 14, padding: 14 },
  kv: { color: "#fff", fontSize: 18, fontWeight: "800" },
  kk: { color: "#9a93c2", fontSize: 12, marginTop: 4 },
  h: { color: "#ece9f8", fontWeight: "700", fontSize: 15, marginBottom: 8 },
  li: { flexDirection: "row", justifyContent: "space-between", backgroundColor: "#1e1840", borderRadius: 12, padding: 13, marginBottom: 6 },
  ln: { color: "#ece9f8", fontWeight: "600" },
  ls: { color: "#9a93c2", fontSize: 12, marginTop: 2 },
  lt: { color: "#3ecf8e", fontWeight: "800" },
});
