"""补充验证：页面可访问性 + 零模型环境下的索引链路。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(key, None)

BASE = "http://127.0.0.1:8097"
ROOT = Path("D:/campus-claw")
PY = ROOT / ".venv/Scripts/python.exe"
HOME = "D:/campus-claw/.verify/appdata"

results = []


def rec(name, ok, expected, actual, detail=""):
    results.append({"name": name, "expected": expected, "actual": actual,
                    "verdict": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name:<30} 期望={expected:<18} 实际={actual}")
    if detail and not ok:
        print("       ", detail[:300])


def api(method, path, body=None, token=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def upload(filename, content, title, token):
    boundary = "----probe7d3f"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f'Content-Type: text/markdown\r\n\r\n'.encode() + content.encode() + b"\r\n"
        + f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\n'.encode()
        + title.encode() + b"\r\n"
        + f"--{boundary}--\r\n".encode()
    )
    req = urllib.request.Request(
        BASE + "/api/materials/upload", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


# ---------- 1. 页面可访问性（Cookie 会话） ----------
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
html = opener.open(BASE + "/login", timeout=20).read().decode()
token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
opener.open(urllib.request.Request(
    BASE + "/login",
    data=urllib.parse.urlencode({"username": "teacher_a", "password": "TeacherA#2026",
                                 "csrf_token": token}).encode(), method="POST"), timeout=20)

pages = ["/materials", "/knowledge", "/tutor", "/tutor/settings", "/mcp",
         "/qa", "/qa/faq", "/qa/stats", "/swagger/index.html", "/openapi.json"]
for page in pages:
    try:
        resp = opener.open(BASE + page, timeout=30)
        code, length = resp.status, len(resp.read())
        rec(f"页面 {page}", code == 200, "200", f"{code} ({length}B)")
    except urllib.error.HTTPError as exc:
        rec(f"页面 {page}", False, "200", f"{exc.code}")

# 未登录访问受保护页面应 302
anon = urllib.request.build_opener()
for page in ("/tutor", "/qa/stats", "/mcp"):
    try:
        anon.open(BASE + page, timeout=20)
        rec(f"匿名 {page}", False, "302", "200")
    except urllib.error.HTTPError as exc:
        rec(f"匿名 {page}", exc.code == 302, "302", str(exc.code))

# ---------- 2. 零模型环境索引链路 ----------
status, login_body = api("POST", "/api/login", {"username": "teacher_a",
                                                "password": "TeacherA#2026"})
tk = login_body.get("token")
status, up = upload("zero-model.md",
                    "# 零模型验证\n\n本材料含关键词 ZERO_MODEL_MARKER，用于验证无嵌入配置时的索引链路。\n",
                    "零模型索引验证", tk)
mid = up.get("material_id")
rec("上传新材料", status == 201 and bool(mid), "201", f"{status} id={mid}")

status, st = api("GET", f"/api/materials/{mid}/index-status", token=tk)
rec("上传后索引状态", status == 200, "200", f"{status} {st.get('status')}")

env = dict(os.environ)
env.update({"CAMPUSCLAW_HOME": HOME, "PYTHONPATH": str(ROOT)})
run = subprocess.run([str(PY), "-m", "campusclaw.index_worker", "--once"],
                     cwd=str(ROOT), env=env, capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=180)
rec("运行索引 worker（无模型配置）", True, "记录实际结果",
    f"exit={run.returncode}",
    detail=(run.stdout or "")[-200:] + (run.stderr or "")[-300:])

status, st2 = api("GET", f"/api/materials/{mid}/index-status", token=tk)
rec("worker 后索引状态", True, "记录实际结果",
    f"{st2.get('status')} err={str(st2.get('last_error'))[:40]}")

status, search = api("POST", "/api/search",
                     {"query": "ZERO_MODEL_MARKER", "mode": "keyword", "limit": 5}, token=tk)
hits = search.get("hits") or []
hit_titles = [h.get("title") for h in hits]
rec("零模型下新材料可检索", bool(hits), "命中新上传材料",
    f"{len(hits)} 条 {hit_titles}")

status, search2 = api("POST", "/api/search",
                      {"query": "示例讲义", "mode": "keyword", "limit": 5}, token=tk)
rec("种子材料仍可检索", bool(search2.get("hits")), "命中种子材料",
    f"{len(search2.get('hits') or [])} 条")

out = Path(__file__).with_name("extra-result.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n共 {len(results)} 项，PASS {sum(1 for r in results if r['verdict'] == 'PASS')}")
print("已写入", out)
