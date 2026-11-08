import { useEffect, useState } from "react";
import { View, Text, FlatList, TouchableOpacity, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { hub, creds } from "../../src/lib/api";

export default function Devices() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [me, setMe] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    (async () => {
      try {
        const c = await creds.load(); if (!c) throw new Error("not paired");
        setMe(c);
        const b = await hub.base();
        setRows(await hub.devices(b, c.device_key));
      } catch (e: any) { setErr(e.message); }
    })();
  }, []);
  return (
    <View style={s.c}>
      <TouchableOpacity onPress={() => router.back()}><Text style={s.back}>‹ Admin</Text></TouchableOpacity>
      <Text style={s.brand}>Devices</Text>
      <FlatList data={rows} keyExtractor={d => String(d.id)} contentContainerStyle={{ paddingVertical: 10 }}
        renderItem={({ item: d }) => (
          <View style={s.li}>
            <View style={{ flex: 1 }}>
              <Text style={s.ln}>{d.device_name}{String(d.id) === String(me?.device) ? " · this device" : ""}</Text>
              <Text style={s.ls}>{d.device_type || "device"} · last seen {(d.last_seen_at || "never").slice(0, 16).replace("T", " ")}</Text>
            </View>
            <Text style={[s.badge, d.active ? s.on : s.off]}>{d.active ? "active" : "revoked"}</Text>
          </View>)}
        ListEmptyComponent={<Text style={s.sub}>{err ? `Couldn't reach the hub: ${err}` : "No devices paired."}</Text>} />
    </View>
  );
}

const s = StyleSheet.create({
  c: { flex: 1, backgroundColor: "#14102b", padding: 16, paddingTop: 56 },
  back: { color: "#8b5cf6", fontSize: 15, fontWeight: "600", marginBottom: 4 },
  brand: { color: "#fff", fontSize: 22, fontWeight: "800", marginBottom: 10 },
  li: { flexDirection: "row", alignItems: "center", backgroundColor: "#1e1840", borderRadius: 12, padding: 13, marginBottom: 6 },
  ln: { color: "#ece9f8", fontWeight: "600" },
  ls: { color: "#9a93c2", fontSize: 12, marginTop: 2 },
  badge: { fontWeight: "800", fontSize: 12, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8, overflow: "hidden" },
  on: { color: "#3ecf8e", backgroundColor: "#1f3a2f" },
  off: { color: "#e05a5a", backgroundColor: "#3a1f1f" },
  sub: { color: "#9a93c2", marginTop: 20, textAlign: "center" },
});
