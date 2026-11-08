import "react-native-url-polyfill/auto";
import { createClient } from "@supabase/supabase-js";
import AsyncStorage from "@react-native-async-storage/async-storage";

// Publishable anon key only — privileged ops go through the hub/cloud API (spec §6).
export const sb = createClient(
  "https://bpwbwvaimwofjkxjestv.supabase.co",
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJwd2J3dmFpbXdvZmpreGplc3R2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTM5NTM1NTYsImV4cCI6MjEwOTUyOTU1Nn0.q1p1hpCQQ9HTQAP1325fjuZ83LSu-nkuBkS5tPoUXpQ",
  { auth: { storage: AsyncStorage, persistSession: true, autoRefreshToken: true, detectSessionInUrl: false } });

export type Membership = { business_id: string; role: string; business: string; branches: { id: string; name: string }[] };

export async function memberships(): Promise<Membership[]> {
  const { data, error } = await sb.from("business_memberships").select("business_id, role");
  if (error) throw error;
  const out: Membership[] = [];
  for (const m of data || []) {
    const [b, bs] = await Promise.all([
      sb.from("businesses").select("name").eq("id", m.business_id).single(),
      sb.from("branch_memberships").select("branch_id").eq("business_id", m.business_id)
        .then(async r => {
          const ids = (r.data || []).map((x: any) => x.branch_id);
          if (!ids.length) {
            const all = await sb.from("branches").select("id,name").eq("business_id", m.business_id);
            return all.data || [];
          }
          const named = await sb.from("branches").select("id,name").in("id", ids);
          return named.data || [];
        })]);
    out.push({ business_id: m.business_id, role: m.role, business: b.data?.name || m.business_id, branches: bs });
  }
  return out;
}
