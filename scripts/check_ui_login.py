"""临时校验：登录失败回登录页（HTML）而不是 JSON。跑完即删。"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="loginchk-"))
os.environ["CAMPUSCLAW_DATA_DIR"] = str(tmp / "data")
os.environ["CAMPUSCLAW_UPLOAD_DIR"] = str(tmp / "uploads")
os.environ.setdefault("CAMPUSCLAW_SECRET_KEY", "x" * 40)

from campusclaw import create_app  # noqa: E402

app = create_app()
app.config["TESTING"] = True
c = app.test_client()


def csrf_from(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "登录页没有 csrf_token"
    return m.group(1)


ok = True


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok
    ok = ok and cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


# 1. 登录页可打开
r = c.get("/login")
html = r.get_data(as_text=True)
check("GET /login 200", r.status_code == 200, str(r.status_code))
check("登录页含预置账号", "预置账号" in html)
token = csrf_from(html)

# 2. 密码错误 → 401 + HTML 人话
r = c.post("/login", data={"csrf_token": token, "username": "student_a1", "password": "wrong"})
body = r.get_data(as_text=True)
check("错密码 401", r.status_code == 401, str(r.status_code))
check("返回 HTML 而非 JSON", "text/html" in r.headers.get("Content-Type", ""), r.headers.get("Content-Type", ""))
check("页面出现'账号或密码错误'", "账号或密码错误" in body)
check("不再泄漏 error.code JSON", '"error"' not in body and "INVALID_CREDENTIALS" not in body)
check("账号已回填", 'value="student_a1"' in body)

# 3. 空口令 → 400
token = csrf_from(body)
r = c.post("/login", data={"csrf_token": token, "username": "student_a1", "password": ""})
body = r.get_data(as_text=True)
check("空口令 400", r.status_code == 400, str(r.status_code))
check("空口令给人话", "请输入账号和密码" in body)

# 4. CSRF 失效 → 403 回登录页
r = c.post("/login", data={"csrf_token": "bogus", "username": "student_a1", "password": "StudentA1#2026"})
body = r.get_data(as_text=True)
check("CSRF 失效 403", r.status_code == 403, str(r.status_code))
check("CSRF 失效回登录页", "页面已过期" in body and "text/html" in r.headers.get("Content-Type", ""))

# 5. 正确口令 → 302 到材料页
token = csrf_from(body)
r = c.post("/login", data={"csrf_token": token, "username": "student_a1", "password": "StudentA1#2026"})
check("正确口令 302", r.status_code == 302, str(r.status_code))
check("跳转 /materials", "/materials" in (r.headers.get("Location") or ""), r.headers.get("Location", ""))

# 6. 审计仍然留痕（页面分流不能绕过 SEC-07；400 按设计不记，只记 401/403/404）
import sqlite3  # noqa: E402

conn = sqlite3.connect(str(tmp / "data" / "app.db"))
rows = conn.execute(
    "SELECT status, code FROM audit_events WHERE path = '/login' AND status IN (401,403)"
).fetchall()
conn.close()
codes = {r[1] for r in rows}
check("拒绝仍写审计（401/403）", {"INVALID_CREDENTIALS", "CSRF_INVALID"} <= codes, f"{rows}")

# 7. API 登录分支仍是 JSON（不能把程序调用也改成 HTML）
r = c.post("/api/login", json={"username": "student_a1", "password": "wrong"})
check("API 登录仍返回 JSON", "application/json" in r.headers.get("Content-Type", ""), r.headers.get("Content-Type", ""))
check("API 登录 401", r.status_code == 401, str(r.status_code))

print()
print("结果：" + ("全部通过" if ok else "有失败项"))
raise SystemExit(0 if ok else 1)
