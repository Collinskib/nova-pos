import { useEffect, useState } from "react";
import { View, Text, FlatList, TouchableOpacity, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { hub, creds } from "../../src/lib/api";

export default function Users() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [err, setErr] = useState("");
  useEffect(() => {
    (async () => {
      try {
        const c = await creds.load(); if (!c) throw new Error("not paired");
        const b = await hub.base();
        setRows(await hub.users(b, c.device_key));
      } catch (e: any) { setErr(e.message); }
    })();
  }, []);
  return (
    <View style={s.c}>
      <TouchableOpacity onPress={() => router.back()}><Text style={s.back}>‹ Admin</Text></TouchableOpacity>
      <Text style={s.brand}>Staff</Text>
      <FlatList data={rows} keyExtractor={u => String(u.id)} contentContainerStyle={{ paddingVertical: 10 }}
        renderItem={({ item: u }) => (
          <View style={s.li}>
            <View style={{ flex: 1 }}>
              <Text style={s.ln}>{u.name || u.username}</Text>
              <Text style={s.ls}>@{u.username}</Text>
            </View>
            <Text style={[s.badge, u.role === "admin" ? s.admin : s.cash]}>{u.role}</Text>
          </View>)}
        ListEmptyComponent={<Text style={s.sub}>{err ? `Couldn't reach the hub: ${err}` : "No staff."}</Text>} />
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
  admin: { color: "#8b5cf6", backgroundColor: "#2a2350" },
  cash: { color: "#3ecf8e", backgroundColor: "#1f3a2f" },
  sub: { color: "#9a93c2", marginTop: 20, textAlign: "center" },
});
