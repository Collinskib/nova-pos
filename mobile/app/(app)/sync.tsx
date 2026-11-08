import { useEffect, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ScrollView } from "react-native";
import { getDb, all, one } from "../../src/db/database";
import { syncOnce, stopSync } from "../../src/sync/engine";
import { creds, hub } from "../../src/lib/api";
import { useStore } from "../../src/store/store";
import * as SecureStore from "expo-secure-store";

export default function Sync() {
  const [out, setOut] = useState<any[]>([]);
  const [conf, setConf] = useState<any[]>([]);
  const [cursor, setCursor] = useState(0);
  const [hubUrl, setHubUrl] = useState("");
  const [staff, setStaff] = useState<any[]>([]);
  const { syncState, pending, hubUp, lastSync, ctx, syncError, set } = useStore();

  const reload = async () => {
    const d = await getDb();
    setOut(await all(d, "SELECT * FROM sync_outbox WHERE cloud_acked=0 ORDER BY id DESC LIMIT 50"));
    setConf(await all(d, "SELECT * FROM sync_conflicts WHERE resolved=0"));
    setCursor((await one<{ last_sequence: number }>(d, "SELECT last_sequence FROM sync_cursors WHERE destination='hub'"))?.last_sequence ?? 0);
    setHubUrl((await SecureStore.getItemAsync("hub_url")) || "");
  };
  useEffect(() => { reload(); const i = setInterval(reload, 5000); return () => clearInterval(i); }, []);

  return (
    <ScrollView style={s.c}>
      <Text style={s.brand}>Sync status</Text>
      <View style={s.card}>
        <Row k="State" v={syncState} />
        <Row k="Hub" v={hubUp ? "connected" : syncError === "repair" ? "device rejected — re-pair" : "unreachable"} c={hubUp ? "#3ecf8e" : "#e05a5a"} />
        <Row k="Pending events" v={String(pending)} c={pending ? "#f0a51f" : "#3ecf8e"} />
        <Row k="Hub cursor" v={String(cursor)} />
        <Row k="Last sync" v={lastSync ? new Date(lastSync).toLocaleTimeString() : "never"} />
        <Row k="Device" v={`${ctx?.device} · ${ctx?.branch}`} />
      </View>
      <Text style={s.h}>Hub address</Text>
      <View style={s.row}>
        <TextInput style={[s.in, { flex: 1 }]} value={hubUrl} onChangeText={setHubUrl}
          autoCapitalize="none" placeholder="http://192.168.x.x:5050" placeholderTextColor="#8b86a8" />
        <TouchableOpacity style={s.btn} onPress={async () => { await SecureStore.setItemAsync("hub_url", hubUrl); }}>
          <Text style={s.btnT}>Save</Text></TouchableOpacity>
      </View>
      <TouchableOpacity style={[s.btn, { marginVertical: 12 }]} onPress={async () => { await syncOnce(); reload(); }}>
        <Text style={s.btnT}>Sync now</Text></TouchableOpacity>
      <TouchableOpacity style={[s.btn, { marginBottom: 8 }]}
        onPress={async () => {
          try {
            const c = await creds.load(); if (!c) return;
            const base = await hub.base();
            setStaff(await hub.users(base, c.device_key));
          } catch {}
        }}>
        <Text style={s.btnT}>Switch till user {ctx?.cashier_name ? `(${ctx.cashier_name})` : ""}</Text></TouchableOpacity>
      {staff.map(u => (
        <TouchableOpacity key={u.id} style={[s.btn, { marginBottom: 6, backgroundColor: "#2a2350" }]}
          onPress={async () => {
            const c = await creds.load(); if (!c) return;
            const n = { ...c, cashier_id: u.id, cashier_name: u.name || u.username, role: u.role };
            await creds.save(n); set({ ctx: n }); setStaff([]);
          }}>
          <Text style={s.btnT}>{u.name || u.username} · {u.role}</Text></TouchableOpacity>))}
      <TouchableOpacity style={[s.btn, { borderColor: "#e05a5a" }]}
        onPress={async () => { stopSync(); await creds.clear(); set({ ctx: null, syncError: null }); }}>
        <Text style={[s.btnT, { color: "#e05a5a" }]}>Sign out & re-pair</Text></TouchableOpacity>
      <Text style={s.h}>Outbox ({out.length})</Text>
      {out.map(e => <View key={e.event_id} style={s.li}>
        <Text style={s.ln}>{e.event_type} <Text style={s.ls}>#{e.device_sequence}</Text></Text>
        <Text style={s.ls}>{e.event_id.slice(0, 8)}… hub:{e.hub_acked ? "✓" : "·"} cloud:{e.cloud_acked ? "✓" : "·"}</Text>
      </View>)}
      {!!conf.length && <><Text style={[s.h, { color: "#e05a5a" }]}>Conflicts ({conf.length})</Text>
        {conf.map(x => <View key={x.id} style={s.li}><Text style={s.ln}>{x.reason}</Text><Text style={s.ls}>{x.detail}</Text></View>)}</>}
    </ScrollView>
  );
}
const Row = ({ k, v, c }: any) => <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 5 }}>
  <Text style={{ color: "#9a93c2" }}>{k}</Text><Text style={{ color: c || "#ece9f8", fontWeight: "700" }}>{v}</Text></View>;
const s = StyleSheet.create({
  c: { flex: 1, backgroundColor: "#14102b", padding: 16, paddingTop: 56 },
  brand: { color: "#fff", fontSize: 22, fontWeight: "800", marginBottom: 10 },
  card: { backgroundColor: "#1e1840", borderRadius: 14, padding: 14, marginBottom: 12 },
  h: { color: "#ece9f8", fontWeight: "700", fontSize: 15, marginVertical: 8 },
  row: { flexDirection: "row", gap: 8, alignItems: "center" },
  in: { backgroundColor: "#1e1840", borderRadius: 10, padding: 12, color: "#fff" },
  btn: { backgroundColor: "#45209f", borderRadius: 10, padding: 13, paddingHorizontal: 18 },
  btnT: { color: "#fff", fontWeight: "700" },
  li: { backgroundColor: "#1e1840", borderRadius: 10, padding: 11, marginBottom: 5 },
  ln: { color: "#ece9f8", fontWeight: "600" },
  ls: { color: "#9a93c2", fontSize: 12, marginTop: 2 },
});
