#!/usr/bin/env python3
"""Localize POS to Kenya: KSh pricing, Nairobi store, real product images via Open Food Facts."""
import sqlite3, json, urllib.request, urllib.parse, time

DB = "/home/collins/Documents/nova-pos/pos.db"
QUERIES = {  # product name -> OFF search term
 "Cola 330ml": "coca cola 330ml", "Orange Juice 1L": "orange juice",
 "Potato Chips 150g": "potato chips", "Chocolate Bar": "chocolate bar",
 "Whole Milk 1L": "whole milk", "Greek Yogurt 500g": "greek yogurt",
 "Dish Soap 750ml": "dish soap", "Paper Towels 6pk": "paper towels",
 "Hand Sanitizer 250ml": "hand sanitizer", "Shampoo 400ml": "shampoo"}

def off_image(term):
    q = urllib.parse.urlencode({"search_terms": term, "search_simple": 1, "action": "process",
                                "json": 1, "page_size": 5, "fields": "image_front_small_url,image_url"})
    try:
        with urllib.request.urlopen(f"https://world.openfoodfacts.org/cgi/search.pl?{q}", timeout=15) as r:
            for p in json.loads(r.read()).get("products", []):
                u = p.get("image_front_small_url") or p.get("image_url")
                if u: return u
    except Exception as e:
        print("  !", term, e)
    return None

c = sqlite3.connect(DB)
cols = [r[1] for r in c.execute("PRAGMA table_info(products)")]
if "image" not in cols:
    c.execute("ALTER TABLE products ADD COLUMN image TEXT")

# Kenyan pricing (KSh) + images
prices = {"Cola 330ml": (150, 90), "Orange Juice 1L": (320, 210), "Potato Chips 150g": (180, 100),
          "Chocolate Bar": (210, 130), "Whole Milk 1L": (160, 110), "Greek Yogurt 500g": (380, 270),
          "Dish Soap 750ml": (420, 260), "Paper Towels 6pk": (550, 360),
          "Hand Sanitizer 250ml": (300, 170), "Shampoo 400ml": (650, 440)}
for name, q in QUERIES.items():
    img = off_image(q)
    pr, co = prices[name]
    c.execute("UPDATE products SET price=?, cost=?, image=COALESCE(?, image) WHERE name=?", (pr, co, img, name))
    print(f"{name}: {'img ok' if img else 'NO IMG'} -> KSh {pr}")
    time.sleep(0.4)

for k, v in {"store_name": "Nova Mart", "store_address": "Moi Avenue, Nairobi, Kenya",
             "store_phone": "+254 712 345 678", "tax_rate": "0", "currency": "KSh "}.items():
    c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, v))
c.commit(); c.close(); print("done")
