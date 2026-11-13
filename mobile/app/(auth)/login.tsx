import { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, Alert, StyleSheet, ScrollView } from "react-native";
import { sb, memberships, onboard, Membership } from "../../src/lib/supabase";
import { useStore } from "../../src/store/store";
import { useRouter } from "expo-router";
import * as SecureStore from "expo-secure-store";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";

WebBrowser.maybeCompleteAuthSession();

export default function Login() {
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [signUp, setSignUp] = useState(false);
  const [mems, setMems] = useState<Membership[] | null>(null);
  const [noBiz, setNoBiz] = useState(false);
  const [biz, setBiz] = useState("");
  const [branch, setBranch] = useState("Main");
  const set = useStore(s => s.set);
  const router = useRouter();

  const login = async () => {
    setBusy(true);
    try {
      const r = signUp
        ? await sb.auth.signUp({ email: email.trim(), password: pw })
        : await sb.auth.signInWithPassword({ email: email.trim(), password: pw });
      if (r.error) throw r.error;
      if (signUp && !r.data.session) {
        Alert.alert("Check your email", "Tap the verification link, then sign in.");
        setSignUp(false); return;
      }
      const m = await memberships();
      if (m.length) setMems(m);          // else fall through to onboarding form below
      else setNoBiz(true);
    } catch (e: any) { Alert.alert(signUp ? "Sign up failed" : "Sign in failed", e.message); }
    finally { setBusy(false); }
  };

  const afterAuth = async () => {
    const m = await memberships();
    if (m.length) setMems(m); else setNoBiz(true);
  };

  const finishGoogle = async (rawUrl: string) => {
    const url = new URL(rawUrl.replace("#", "?"));
    const code = url.searchParams.get("code");
    if (code) {
      const { error } = await sb.auth.exchangeCodeForSession(code);
      if (error) throw error;
    } else {
      const access_token = url.searchParams.get("access_token");
      const refresh_token = url.searchParams.get("refresh_token");
      if (!access_token) throw new Error("No session returned");
      const { error } = await sb.auth.setSession({ access_token, refresh_token: refresh_token ?? "" });
      if (error) throw error;
    }
    await afterAuth();
  };

  const google = async () => {
    setBusy(true);
    let done = false, sub: { remove: () => void } | null = null;
    const finish = async (u: string) => {
      if (done) return; done = true;
      sub?.remove();
      try { await finishGoogle(u); }
      catch (e: any) { Alert.alert("Google sign-in failed", e.message); }
      finally { setBusy(false); }
    };
    try {
      const redirectTo = Linking.createURL("/");
      // Fallback: if the browser hands the exp:// redirect to the OS instead of
      // back to openAuthSessionAsync, the deep link still completes sign-in.
      sub = Linking.addEventListener("url", ({ url }) => { if (url.includes("code=") || url.includes("access_token=")) finish(url); });
      const { data, error } = await sb.auth.signInWithOAuth({
        provider: "google", options: { redirectTo, skipBrowserRedirect: true } });
      if (error) throw error;
      const res = await WebBrowser.openAuthSessionAsync(data.url!, redirectTo);
      if (res.type === "success") await finish(res.url);
      else if (res.type === "cancel" || res.type === "dismiss") { sub.remove(); setBusy(false); }
    } catch (e: any) {
      sub?.remove();
      Alert.alert("Google sign-in failed", e.message);
      setBusy(false);
    }
  };

  const doOnboard = async () => {
    setBusy(true);
    try {
      const r = await onboard(biz.trim(), branch.trim() || "Main");
      if (r.error) throw new Error(r.error);
      const m = await memberships();
      if (!m.length) throw new Error("Onboarding failed — try again");
      setMems(m);
    } catch (e: any) { Alert.alert("Setup failed", e.message); }
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
      <Text style={s.brand}>ShujaaPOS</Text>
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

  if (noBiz) return (
    <ScrollView style={{ flex: 1, backgroundColor: "#14102b" }} contentContainerStyle={s.wrap}>
      <Text style={s.brand}>ShujaaPOS</Text>
      <View style={s.card}>
        <Text style={s.h}>Set up your store</Text>
        <Text style={s.sub}>This becomes your business — you can add branches after.</Text>
        <TextInput style={s.in} placeholder="Store / business name" placeholderTextColor="#8b86a8"
          value={biz} onChangeText={setBiz} />
        <TextInput style={s.in} placeholder="First branch" placeholderTextColor="#8b86a8"
          value={branch} onChangeText={setBranch} />
        <TouchableOpacity style={s.btn} onPress={doOnboard} disabled={busy || !biz.trim()}>
          <Text style={s.btnT}>{busy ? "Creating…" : "Create my store"}</Text>
        </TouchableOpacity>
      </View>
    </ScrollView>);

  return (
    <ScrollView style={{ flex: 1, backgroundColor: "#14102b" }} contentContainerStyle={s.wrap}>
      <Text style={s.brand}>ShujaaPOS</Text>
      <View style={s.card}>
        <Text style={s.h}>{signUp ? "Create account" : "Sign in"}</Text>
        <Text style={s.sub}>Use your staff account from your admin.</Text>
        <TextInput style={s.in} placeholder="Email" placeholderTextColor="#8b86a8" autoCapitalize="none"
          keyboardType="email-address" value={email} onChangeText={setEmail} />
        <TextInput style={s.in} placeholder="Password" placeholderTextColor="#8b86a8" secureTextEntry
          value={pw} onChangeText={setPw} />
        <TouchableOpacity style={s.btn} onPress={login} disabled={busy || !email || !pw}>
          <Text style={s.btnT}>{busy ? "…" : (signUp ? "Create account" : "Sign in")}</Text>
        </TouchableOpacity>
        <TouchableOpacity style={s.gbtn} onPress={google} disabled={busy}>
          <Text style={s.gbtnT}>Continue with Google</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => setSignUp(!signUp)}>
          <Text style={s.link}>{signUp ? "Have an account? Sign in" : "New here? Create account"}</Text>
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
  gbtn: { borderWidth: 1, borderColor: "#e7e3f4", borderRadius: 12, padding: 16, alignItems: "center", marginTop: 12 },
  gbtnT: { color: "#14102b", fontWeight: "600" },
  btnT: { color: "#fff", fontWeight: "700", fontSize: 16 },
  link: { color: "#45209f", textAlign: "center", marginTop: 14, fontWeight: "600" },
  pick: { borderWidth: 1, borderColor: "#e7e3f4", borderRadius: 10, padding: 14, marginTop: 8 },
  pickT: { color: "#14102b", fontWeight: "600" },
});
