#!/usr/bin/env python3
"""ShujaaPOS desktop launcher — runs the local hub and opens a native window.

Works offline: SQLite lives in the user data dir, hub on :5050.
Phones/tablets on the same Wi-Fi pair to it over LAN (Devices → Pair), so the
window is bound to 0.0.0.0 — set POS_HOST=127.0.0.1 to keep it local-only.
Falls back to the system browser if pywebview isn't available.
"""
import os, sys, threading, time, urllib.request

# Bundled app: keep the DB in a writable user dir, not next to the binary.
_data = os.getenv("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
DB_DIR = os.path.join(_data, "ShujaaPOS")
os.makedirs(DB_DIR, exist_ok=True)
os.environ.setdefault("POS_DB", os.path.join(DB_DIR, "pos.db"))
os.environ.setdefault("POS_HOST", "0.0.0.0")
os.environ.setdefault("POS_PORT", "5050")

if getattr(sys, "frozen", False):  # running inside PyInstaller bundle
    os.chdir(sys._MEIPASS)

import app as hub  # noqa: E402  — hub module; env vars set before import

BASE = "http://127.0.0.1:5050"

def serve():
    from waitress import serve as ws
    ws(hub.app, host=os.environ.get("POS_HOST", "0.0.0.0"), port=5050, threads=8)

if __name__ == "__main__":
    threading.Thread(target=serve, daemon=True).start()
    for _ in range(100):  # wait for the hub to come up
        try:
            urllib.request.urlopen(BASE + "/", timeout=0.5)
            break
        except Exception:
            time.sleep(0.1)
    try:
        import webview
        webview.create_window("ShujaaPOS", BASE, width=1200, height=820, min_size=(900, 600))
        webview.start()
    except ImportError:
        import webbrowser
        webbrowser.open(BASE)
        print("ShujaaPOS running at", BASE, "— close this window to quit.")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
