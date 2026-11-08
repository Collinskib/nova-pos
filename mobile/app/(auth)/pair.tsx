import { useState, useRef } from "react";
import { View, Text, TextInput, TouchableOpacity, Alert, StyleSheet, ScrollView, Modal } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { hub, creds } from "../../src/lib/api";
import { useStore } from "../../src/store/store";
import { seedProducts } from "../../src/db/repos";
import { startSync } from "../../src/sync/engine";
import { sb } from "../../src/lib/supabase";
import { useRouter } from "expo-router";
import * as SecureStore from "expo-secure-store";

export default function Pair() {
  const [token, setToken] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [users, setUsers] = useState<any[]>([]);
  const pendingCtx = useRef<any>(null);
  const pickCashier = async (u: any) => {
    const c = { ...pendingCtx.current, cashier_id: u.id, cashier_name: u.name || u.username, role: u.role };
    await creds.save(c); set({ ctx: c }); startSync();
  };
  const [scan, setScan] = useState(false);
  const [perm, requestPerm] = useCameraPermissions();
  const set = useStore(s => s.set);
  const router = useRouter();

  const openScan = async () => {
    if (!perm?.granted) { const r = await requestPerm(); if (!r.granted) return; }
    setScan(true);
  };

  const [scanning, setScanning] = useState(false);
  const [scanProg, setScanProg] = useState("");

  /** Subnet scan: probe every .1-254 host's /api/v1/ping in parallel batches. */
  const autoDetect = async () => {
    setScanning(true); setScanProg("");
    try {
      let subnet = "";
      try {
        const Net = require("expo-network");
        const ip = await Net.getIpAddressAsync();
        if (ip && ip.includes(".")) subnet = ip.split(".").slice(0, 3).join(".");
      } catch {}
      if (!subnet) {  // fallback: subnet of saved/last hub URL
        const m = (url || await SecureStore.getItemAsync("hub_url") || "").match(/(\d+\.\d+\.\d+)\./);
        subnet = m ? m[1] : "192.168.1";
      }
      const probe = async (host: string) => {
        const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 1200);
        try {
          const r = await fetch(`http://${host}:5050/api/v1/ping`, { signal: ctl.signal });
          const j = await r.json();
          return j.service === "nova-pos-hub" ? `http://${host}:5050` : null;
        } catch { return null; } finally { clearTimeout(t); }
      };
      for (let b = 1; b < 255 && !scanProg.includes("found"); b += 32) {
        const batch = await Promise.all(
          Array.from({ length: 32 }, (_, i) => b + i).filter(n => n < 255)
            .map(n => probe(`${subnet}.${n}`)));
        const hit = batch.find(Boolean);
        setScanProg(`·${Math.min(b + 31, 254)}/254`);
        if (hit) { setUrl(hit); setScanProg(`found ${hit}`); break; }
      }
      if (!scanProg.includes("found")) setScanProg("not found — enter URL manually");
    } finally { setScanning(false); }
  };

  const onScan = ({ data }: { data: string }) => {
    setScan(false);
    try {
      const j = JSON.parse(data);              // hub QR: {"u":"http://…:5050","t":"ABCD1234"}
      if (j.u) setUrl(j.u);
      if (j.t) setToken(String(j.t).toUpperCase());
    } catch { setToken(data.trim().toUpperCase()); }  // bare token QR
  };

  const pair = async () => {
    setBusy(true);
    try {
      const base = url.trim() || "http://192.168.1.100:5050";
      await SecureStore.setItemAsync("hub_url", base);
      const r = await hub.doPair(base, token.trim().toUpperCase(), "Mobile POS");
      if (!r.ok) throw new Error(r.error || "pairing failed");
      const c = { device_key: r.device_key, device: String(r.device_id), business: r.business_id, branch: r.branch_id };
      await creds.save(c);
      const prods = await hub.products(base, r.device_key).catch(() => []);
      await seedProducts({ business: r.business_id }, prods, base);
      const staff = await hub.users(base, r.device_key).catch(() => []);
      if (staff.length) setUsers(staff);          // "who's on this till?" picker
      else { set({ ctx: c }); startSync(); }      // no staff list — pair straight through
      pendingCtx.current = c;
    } catch (e: any) { Alert.alert("Pairing failed", e.message); }
    finally { setBusy(false); }
  };

  if (users.length) return (
    <View style={{ flex: 1, backgroundColor: "#14102b", justifyContent: "center", padding: 20 }}>
      <Text style={[s.h, { textAlign: "center" }]}>Who's using this till?</Text>
      <Text style={[s.sub, { textAlign: "center", marginBottom: 16 }]}>Sales on this device will be recorded under this name.</Text>
      {users.map(u => (
        <TouchableOpacity key={u.id} style={s.btn} onPress={() => pickCashier(u)}>
          <Text style={s.btnT}>{u.name || u.username} <Text style={{ fontWeight: "400", opacity: .7 }}>· {u.role}</Text></Text>
        </TouchableOpacity>))}
    </View>);

  return (
    <ScrollView style={{ flex: 1, backgroundColor: "#14102b" }} contentContainerStyle={s.wrap}>
      <Text style={s.brand}>Mauzo POS</Text>
      <View style={s.card}>
        <Text style={s.h}>Pair this device</Text>
        <Text style={s.sub}>On the hub: Devices → Pair a device → enter the code below.</Text>
        <Text style={s.warn}>📶 This phone and the hub computer must be on the <Text style={{ fontWeight: "700" }}>same Wi-Fi / LAN</Text>. Pairing does not work over mobile data or a different network.</Text>
        <TouchableOpacity style={s.scanBtn} onPress={autoDetect} disabled={scanning}>
          <Text style={s.scanT}>{scanning ? `Scanning LAN… ${scanProg}` : "🔍 Find hub automatically"}</Text>
        </TouchableOpacity>
        <TextInput style={s.in} placeholder="Hub URL (e.g. http://192.168.18.9:5050)" placeholderTextColor="#8b86a8"
          value={url} onChangeText={setUrl} autoCapitalize="none" keyboardType="url" />
        <TextInput style={[s.in, { letterSpacing: 3 }]} placeholder="PAIR CODE" placeholderTextColor="#8b86a8"
          value={token} onChangeText={setToken} autoCapitalize="characters" />
        <TouchableOpacity style={s.btn} onPress={pair} disabled={busy || !token.trim()}>
          <Text style={s.btnT}>{busy ? "Pairing…" : "Pair device"}</Text>
        </TouchableOpacity>
        <TouchableOpacity style={s.scanBtn} onPress={openScan}>
          <Text style={s.scanT}>📷 Scan pairing QR</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={async () => { await sb.auth.signOut(); router.replace("/(auth)/login"); }}>
          <Text style={s.link}>← Back to sign in</Text>
        </TouchableOpacity>
      </View>
      <Modal visible={scan} animationType="slide">
        <View style={{ flex: 1, backgroundColor: "#000" }}>
          <CameraView style={{ flex: 1 }} facing="back" barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
            onBarcodeScanned={onScan} />
          <TouchableOpacity style={s.closeScan} onPress={() => setScan(false)}>
            <Text style={{ color: "#fff", fontWeight: "700" }}>Cancel</Text></TouchableOpacity>
        </View>
      </Modal>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  wrap: { paddingTop: 90, padding: 24 },
  brand: { color: "#fff", fontSize: 28, fontWeight: "800", textAlign: "center", marginBottom: 24 },
  card: { backgroundColor: "#fff", borderRadius: 20, padding: 22 },
  h: { fontSize: 18, fontWeight: "700", color: "#14102b" },
  sub: { color: "#6d6790", marginVertical: 10 },
  in: { borderWidth: 1, borderColor: "#e7e3f4", borderRadius: 12, padding: 14, fontSize: 15, marginBottom: 12, color: "#14102b" },
  btn: { backgroundColor: "#45209f", borderRadius: 12, padding: 16, alignItems: "center", marginTop: 4 },
  btnT: { color: "#fff", fontWeight: "700", fontSize: 16 },
  link: { color: "#45209f", textAlign: "center", marginTop: 14, fontWeight: "600" },
  scanBtn: { borderWidth: 1.5, borderColor: "#45209f", borderRadius: 12, padding: 14, alignItems: "center", marginTop: 10 },
  scanT: { color: "#45209f", fontWeight: "700" },
  closeScan: { position: "absolute", bottom: 50, alignSelf: "center", padding: 14 },
  warn: { backgroundColor: "#fff7e0", borderRadius: 10, padding: 11, color: "#8a6410", fontSize: 13, lineHeight: 19, marginBottom: 12 },
});
