import "react-native-url-polyfill/auto";
import { useEffect, useState } from "react";
import { Stack, useRouter, useSegments, useRootNavigationState } from "expo-router";
import { getDb } from "../src/db/database";
import { creds } from "../src/lib/api";
import { sb } from "../src/lib/supabase";
import { useStore } from "../src/store/store";
import { startSync } from "../src/sync/engine";

export const unstable_settings = { initialRouteName: "index" };

export default function Root() {
  const ctx = useStore(s => s.ctx);
  const set = useStore(s => s.set);
  const seg = useSegments(), router = useRouter();
  const [session, setSession] = useState<boolean | null>(null);
  const navReady = useRootNavigationState()?.key != null;

  useEffect(() => {
    (async () => {
      await getDb();
      const c = await creds.load();
      if (c) { set({ ctx: c }); startSync(); }
      const { data } = await sb.auth.getSession();
      setSession(!!data.session || !!c);   // device-only pairing also allowed
    })();
    const { data: sub } = sb.auth.onAuthStateChange((_e, s) => setSession(!!s));
    return () => sub.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (session === null || !navReady) return;
    const inAuth = seg[0] === "(auth)";
    if (!ctx) {
      if (!inAuth) router.replace(session ? "/(auth)/pair" : "/(auth)/login");
    } else if (inAuth) router.replace("/(app)/pos");
  }, [ctx, seg, session, navReady]);

  return <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: "#14102b" } }} />;
}

export const fmt = (cents: number) => `KSh ${(cents / 100).toFixed(2)}`;
