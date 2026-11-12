# -*- coding: utf-8 -*-
"""补测：索引失败后显式重建入口（POST /api/materials/{id}/reindex）的真实行为。"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / ".acc" / "appdata"
DB = HOME / "data" / "app.db"
PORT = 8099
BASE = f"http://127.0.0.1:{PORT}"
PY = ROOT / ".venv" / "Scripts" / "python.exe"

for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
            "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
    os.environ.pop(key, None)

ENV = {**os.environ, "CAMPUSCLAW_HOME": str(HOME), "PORT": str(PORT),
       "MCP_AUTH_TOKEN": "acc-token-2026"}


def call(method, path, body=None, token=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw or "{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:200]}


def start():
    log = open(ROOT / ".acc" / "reindex-check.log", "a", encoding="utf-8")
    proc = subprocess.Popen([str(PY), "app.py"], cwd=str(ROOT), env=ENV,
                            stdout=log, stderr=subprocess.STDOUT)
    for _ in range(90):
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as resp:
                if resp.status == 200:
                    return proc
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise RuntimeError("应用未就绪")


def db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


proc = start()
try:
    code, payload = call("POST", "/api/login",
                         {"username": "teacher_a", "password": "TeacherA#2026"})
    token = payload["token"]

    code, status = call("GET", "/api/materials/3/index-status", token=token)
    print("重建前状态:", code, status.get("status"), "gen=", status.get("active_generation"))

    code, resp = call("POST", "/api/materials/3/reindex", {"strategy": "hierarchy"},
                      token=token)
    print("调用 reindex:", code, resp)

    out = subprocess.run([str(PY), "-m", "campusclaw.index_worker", "--once"],
                         cwd=str(ROOT), env=ENV, capture_output=True, text=True, timeout=180)
    tail = (out.stdout or "") + (out.stderr or "")
    print("worker exit=", out.returncode, "|", [l for l in tail.splitlines() if "failed" in l][:3])

    conn = db()
    for row in conn.execute("SELECT material_id,active_generation,status,last_error "
                            "FROM material_index WHERE material_id=3"):
        print("重建后状态:", dict(row))
    for row in conn.execute("SELECT generation,index_status,COUNT(*) n FROM knowledge_chunks "
                            "WHERE material_id=3 GROUP BY generation,index_status"):
        print("  切片:", dict(row))
    conn.close()

    code, hits = call("POST", "/api/search",
                      {"query": "第二条FAQ答案正文", "mode": "keyword", "limit": 5}, token)
    items = hits.get("hits") or hits.get("items") or []
    print("重建后检索命中:", len(items), "条")
finally:
    proc.terminate()
    try:
        proc.wait(15)
    except subprocess.TimeoutExpired:
        proc.kill()
