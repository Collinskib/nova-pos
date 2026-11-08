import { useEffect, useState } from "react";
import { View, Text, ScrollView, TouchableOpacity, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { hub, creds } from "../../src/lib/api";

const money = (v: any) => `KSh ${Number(v || 0).toFixed(2)}`;
const iso = (d: Date) => d.toISOString().slice(0, 10);

export default function Reports() {
  const router = useRouter();
  const [day, setDay] = useState(iso(new Date()));
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState("");
  const shift = (n: number) => { const d = new Date(day); d.setDate(d.getDate() + n); setDay(iso(d)); };
  useEffect(() => {
    (async () => {
      setErr(""); setR(null);
      try {
        const c = await creds.load(); if (!c) throw new Error("not paired");
        const b = await hub.base();
        setR(await hub.reports(b, c.device_key, day));
      } catch (e: any) { setErr(e.message); }
    })();
  }, [day]);
  const t = r?.totals || {};
  return (
    <ScrollView style={s.c} contentContainerStyle={{ paddingBottom: 30 }}>
      <TouchableOpacity onPress={() => router.back()}><Text style={s.back}>‹ Admin</Text></TouchableOpacity>
      <View style={s.hdr}>
        <Text style={s.brand}>Reports</Text>
        <View style={s.dpick}>
          <TouchableOpacity onPress={() => shift(-1)}><Text style={s.dbtn}>‹</Text></TouchableOpacity>
          <Text style={s.dtxt}>{day}</Text>
          <TouchableOpacity onPress={() => shift(1)}><Text style={s.dbtn}>›</Text></TouchableOpacity>
        </View>
      </View>
      {err ? <Text style={s.sub}>Couldn't reach the hub: {err}</Text> : !r ? <Text style={s.sub}>Loading…</Text> : (<>
        <View style={s.kpis}>
          <View style={s.kpi}><Text style={s.kv}>{money(t.total)}</Text><Text style={s.kk}>Revenue</Text></View>
          <View style={s.kpi}><Text style={s.kv}>{t.orders ?? 0}</Text><Text style={s.kk}>Orders</Text></View>
          <View style={s.kpi}><Text style={s.kv}>{t.orders ? money(t.total / t.orders) : "—"}</Text><Text style={s.kk}>Avg sale</Text></View>
        </View>
        <Text style={s.h}>Top selling</Text>
        {(r.top || []).map((i: any, x: number) => (
          <View key={x} style={s.li}>
            <Text style={s.ln}>{i.name}</Text>
            <Text style={s.lt}>{i.qty}× · {money(i.revenue)}</Text>
          </View>))}
        <Text style={s.h}>Sales</Text>
        {(r.daily || []).map((x: any, i: number) => (
          <View key={i} style={s.li}>
            <View style={{ flex: 1 }}>
              <Text style={s.ln}>{x.invoice_no}</Text>
              <Text style={s.ls}>{x.cashier || "—"} · {(x.created || "").slice(11, 16)}</Text>
            </View>
            <Text style={[s.lt, x.status === "void" && { color: "#e05a5a" }]}>
              {x.status === "void" ? "void" : money(x.total)}</Text>
          </View>))}
        {!(r.daily || []).length && <Text style={s.sub}>No sales on {day}.</Text>}
      </>)}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  c: { flex: 1, backgroundColor: "#14102b", padding: 16, paddingTop: 56 },
  back: { color: "#8b5cf6", fontSize: 15, fontWeight: "600", marginBottom: 4 },
  hdr: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 14 },
  brand: { color: "#fff", fontSize: 22, fontWeight: "800" },
  dpick: { flexDirection: "row", alignItems: "center", gap: 10 },
  dbtn: { color: "#8b5cf6", fontSize: 22, fontWeight: "700", paddingHorizontal: 6 },
  dtxt: { color: "#ece9f8", fontWeight: "600" },
  kpis: { flexDirection: "row", gap: 8, marginBottom: 18 },
  kpi: { flex: 1, backgroundColor: "#1e1840", borderRadius: 12, padding: 12, alignItems: "center" },
  kv: { color: "#3ecf8e", fontWeight: "800", fontSize: 16 },
  kk: { color: "#9a93c2", fontSize: 11, marginTop: 3, textTransform: "uppercase" },
  h: { color: "#fff", fontWeight: "800", fontSize: 16, marginBottom: 8, marginTop: 4 },
  li: { flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    backgroundColor: "#1e1840", borderRadius: 12, padding: 13, marginBottom: 6 },
  ln: { color: "#ece9f8", fontWeight: "600" },
  ls: { color: "#9a93c2", fontSize: 12, marginTop: 2 },
  lt: { color: "#3ecf8e", fontWeight: "800" },
  sub: { color: "#9a93c2", marginTop: 20, textAlign: "center" },
});
