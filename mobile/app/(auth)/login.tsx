import { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, Alert, StyleSheet, ScrollView } from "react-native";
import { sb, memberships, Membership } from "../../src/lib/supabase";
import { useStore } from "../../src/store/store";
import { useRouter } from "expo-router";
import * as SecureStore from "expo-secure-store";

export default function Login() {
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [mems, setMems] = useState<Membership[] | null>(null);
  const set = useStore(s => s.set);
  const router = useRouter();

  const login = async () => {
    setBusy(true);
    try {
      const { error } = await sb.auth.signInWithPassword({ email: email.trim(), password: pw });
      if (error) throw error;
      const m = await memberships();
      if (!m.length) throw new Error("No business membership on this account");
      setMems(m);
    } catch (e: any) { Alert.alert("Sign in failed", e.message); }
    finally { setBusy(false); }
  };

  const pick = async (m: Membership, branchId?: string) => {
    const br = branchId ? m.branches.find(b => b.id === branchId)! : m.branches[0];
    if (!br) return Alert.alert("No branch", "You have no branch membership — ask your admin.");
    await Promise.all([
      SecureStore.setItemAsync("auth_business", m.business_id),
      SecureStore.setItemAsync("auth_branch", br.id),
      SecureStore.setItemAsync("auth_branch_name", br.name)]);
    set({ ctx: null });   // force (auth) route → pairing next
    router.replace("/(auth)/pair");
  };

  if (mems) return (
    <ScrollView style={{ flex: 1, backgroundColor: "#14102b" }} contentContainerStyle={s.wrap}>
      <Text style={s.brand}>Mauzo POS</Text>
      {mems.map(m => (
        <View key={m.business_id} style={s.card}>
          <Text style={s.h}>{m.business} <Text style={s.role}>{m.role}</Text></Text>
          <Text style={s.sub}>Choose your branch:</Text>
          {m.branches.map(b => (
            <TouchableOpacity key={b.id} style={s.pick} onPress={() => pick(m, b.id)}>
              <Text style={s.pickT}>{b.name}</Text></TouchableOpacity>))}
          {!m.branches.length && <TouchableOpacity style={s.pick} onPress={() => pick(m)}>
            <Text style={s.pickT}>Continue →</Text></TouchableOpacity>}
        </View>))}
    </ScrollView>);

  return (
    <ScrollView style={{ flex: 1, backgroundColor: "#14102b" }} contentContainerStyle={s.wrap}>
      <Text style={s.brand}>Mauzo POS</Text>
      <View style={s.card}>
        <Text style={s.h}>Sign in</Text>
        <Text style={s.sub}>Use your staff account from your admin.</Text>
        <TextInput style={s.in} placeholder="Email" placeholderTextColor="#8b86a8" autoCapitalize="none"
          keyboardType="email-address" value={email} onChangeText={setEmail} />
        <TextInput style={s.in} placeholder="Password" placeholderTextColor="#8b86a8" secureTextEntry
          value={pw} onChangeText={setPw} />
        <TouchableOpacity style={s.btn} onPress={login} disabled={busy || !email || !pw}>
          <Text style={s.btnT}>{busy ? "Signing in…" : "Sign in"}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/(auth)/pair")}>
          <Text style={s.link}>Skip — pair with a code only</Text>
        </TouchableOpacity>
      </View>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  wrap: { paddingTop: 90, padding: 24 },
  brand: { color: "#fff", fontSize: 28, fontWeight: "800", textAlign: "center", marginBottom: 24 },
  card: { backgroundColor: "#fff", borderRadius: 20, padding: 22, marginBottom: 16 },
  h: { fontSize: 18, fontWeight: "700", color: "#14102b" },
  role: { fontSize: 13, color: "#8b5cf6", fontWeight: "600" },
  sub: { color: "#6d6790", marginVertical: 10 },
  in: { borderWidth: 1, borderColor: "#e7e3f4", borderRadius: 12, padding: 14, fontSize: 15, marginBottom: 12, color: "#14102b" },
  btn: { backgroundColor: "#45209f", borderRadius: 12, padding: 16, alignItems: "center", marginTop: 4 },
  btnT: { color: "#fff", fontWeight: "700", fontSize: 16 },
  link: { color: "#45209f", textAlign: "center", marginTop: 14, fontWeight: "600" },
  pick: { borderWidth: 1, borderColor: "#e7e3f4", borderRadius: 10, padding: 14, marginTop: 8 },
  pickT: { color: "#14102b", fontWeight: "600" },
});
