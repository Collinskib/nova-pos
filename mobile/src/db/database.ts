import * as SQLite from "expo-sqlite";
import { MIGRATIONS } from "./schema";

let db: SQLite.SQLiteDatabase | null = null;

export async function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (db) return db;
  db = await SQLite.openDatabaseAsync("nova_pos.db");
  await db.execAsync("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;");
  const { user_version } = (await db.getFirstAsync<{ user_version: number }>("PRAGMA user_version"))!;
  for (let v = user_version; v < MIGRATIONS.length; v++) {
    await db.withTransactionAsync(async () => {
      await db!.execAsync(MIGRATIONS[v]);
      await db!.execAsync(`PRAGMA user_version=${v + 1}`);
    });
  }
  return db;
}

/** Atomic multi-statement write — all or nothing (§7.1). */
export async function tx<T>(fn: (d: SQLite.SQLiteDatabase) => Promise<T>): Promise<T> {
  const d = await getDb();
  let out!: T;
  await d.withExclusiveTransactionAsync(async () => { out = await fn(d); });
  return out;
}

export const all = <T>(d: SQLite.SQLiteDatabase, q: string, p: any[] = []) =>
  d.getAllAsync<T>(q, p);
export const one = <T>(d: SQLite.SQLiteDatabase, q: string, p: any[] = []) =>
  d.getFirstAsync<T>(q, p);
export const run = (d: SQLite.SQLiteDatabase, q: string, p: any[] = []) =>
  d.runAsync(q, p);
