# -*- coding: utf-8 -*-
"""列出当前数据库所有表（开发辅助脚本）"""
import sqlite3

conn = sqlite3.connect(r"./data/app.db")
rows = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("TABLES(%d):" % len(rows))
print("  " + "\n  ".join(rows))
conn.close()
