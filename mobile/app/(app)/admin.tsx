import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { useStore } from "../../src/store/store";

const ITEMS = [
  { href: "/products", icon: "📦", title: "Products & Stock", sub: "Catalogue, prices and on-hand inventory" },
  { href: "/reports", icon: "📈", title: "Reports", sub: "Daily revenue, top sellers, full sales list" },
  { href: "/users", icon: "👥", title: "Staff", sub: "Everyone who can use the till" },
  { href: "/devices", icon: "📱", title: "Devices", sub: "Paired tills and their status" },
];

export default function Admin() {
  const router = useRouter();
  const who = useStore(s => s.ctx?.cashier_name);
  return (
    <View style={s.c}>
      <Text style={s.brand}>Admin <Text style={s.loc}>· {who || "signed-in user"}</Text></Text>
      {ITEMS.map(i => (
        <TouchableOpacity key={i.href} style={s.card} onPress={() => router.push(i.href as any)} activeOpacity={0.75}>
          <Text style={s.icon}>{i.icon}</Text>
          <View style={{ flex: 1 }}>
            <Text style={s.t}>{i.title}</Text>
            <Text style={s.sub}>{i.sub}</Text>
          </View>
          <Text style={s.chev}>›</Text>
        </TouchableOpacity>
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  c: { flex: 1, backgroundColor: "#14102b", padding: 16, paddingTop: 56 },
  brand: { color: "#fff", fontSize: 22, fontWeight: "800", marginBottom: 16 },
  loc: { color: "#9a93c2", fontSize: 13, fontWeight: "400" },
  card: { flexDirection: "row", alignItems: "center", gap: 14, backgroundColor: "#1e1840",
    borderRadius: 14, padding: 16, marginBottom: 10 },
  icon: { fontSize: 22 },
  t: { color: "#ece9f8", fontWeight: "700", fontSize: 16 },
  sub: { color: "#9a93c2", fontSize: 12, marginTop: 3 },
  chev: { color: "#8b5cf6", fontSize: 24, fontWeight: "300" },
});
