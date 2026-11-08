import { Tabs } from "expo-router";
import { Text } from "react-native";
import { useStore } from "../../src/store/store";

const I = ({ c, t }: { c: any; t: string }) =>
  <Text style={{ fontSize: 18, color: c === "#45209f" ? "#8b5cf6" : c }}>{t}</Text>;

export default function TabsLayout() {
  const syncState = useStore(s => s.syncState);
  const dot = { offline: "#e05a5a", pending: "#f0a51f", syncing: "#8b5cf6", synced: "#3ecf8e", error: "#e05a5a" }[syncState];
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarStyle: { backgroundColor: "#1e1840", borderTopColor: "#2a2350" },
      tabBarActiveTintColor: "#8b5cf6", tabBarInactiveTintColor: "#9a93c2" }}>
      <Tabs.Screen name="pos" options={{ title: "POS", tabBarIcon: ({ color }) => <I c={color} t="🧾" />,
        tabBarBadge: undefined, headerRight: () => null }} />
      <Tabs.Screen name="dashboard" options={{ title: "Today", tabBarIcon: ({ color }) => <I c={color} t="📊" /> }} />
      <Tabs.Screen name="sales" options={{ title: "Sales", tabBarIcon: ({ color }) => <I c={color} t="📋" /> }} />
      <Tabs.Screen name="transfers" options={{ title: "Transfers", tabBarIcon: ({ color }) => <I c={color} t="⇄" /> }} />
      <Tabs.Screen name="sync" options={{ title: "Sync", tabBarBadge: syncState === "synced" ? undefined : "•",
        tabBarBadgeStyle: { color: dot, fontSize: 22 }, tabBarIcon: ({ color }) => <I c={color} t="⇅" /> }} />
    </Tabs>
  );
}
