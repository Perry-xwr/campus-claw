"""临时校验：reindex 的 400 到底从哪来、重复提交会不会积压重复任务。跑完即删。"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="reidx-"))
os.environ["CAMPUSCLAW_DATA_DIR"] = str(tmp / "data")
os.environ["CAMPUSCLAW_UPLOAD_DIR"] = str(tmp / "uploads")
os.environ.setdefault("CAMPUSCLAW_SECRET_KEY", "x" * 40)

from campusclaw import create_app  # noqa: E402

app = create_app()
app.config["TESTING"] = True
c = app.test_client()

ok = True


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok
    ok = ok and cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


html = c.get("/login").get_data(as_text=True)
token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
r = c.post("/login", data={"csrf_token": token, "username": "teacher_a", "password": "TeacherA#2026"})
check("教师登录 302", r.status_code == 302, str(r.status_code))

page = c.get("/materials").get_data(as_text=True)
csrf = re.search(r'name="csrf-token" content="([^"]+)"|csrf-token"\s+content="([^"]+)"', page)
token = (csrf.group(1) or csrf.group(2)) if csrf else None
if token is None:
    m2 = re.search(r'name="csrf_token" value="([^"]+)"', page)
    token = m2.group(1) if m2 else ""

# 材料编号从库里取：页面上第一个 #数字 可能是已删除的条目
import sqlite3  # noqa: E402

conn2 = sqlite3.connect(str(tmp / "data" / "app.db"))
mid = conn2.execute(
    "SELECT id FROM materials WHERE class_id = "
    "(SELECT class_id FROM users WHERE username='teacher_a') AND status='active' "
    "ORDER BY id LIMIT 1"
).fetchone()[0]
conn2.close()
check("库里有本班活跃材料", bool(mid))
print("  material id =", mid, "| csrf =", (token or "")[:12])

hdr = {"X-CSRF-Token": token}
before = None

# 1. 完全没有 body：应默认策略，不再 400
r = c.post(f"/api/materials/{mid}/reindex", headers=hdr)
body = r.get_json() if r.is_json else {}
check("无 body 也能重建（202）", r.status_code == 202, f"{r.status_code} {body}")
first_job = body.get("job_id")

# 2. 空 JSON 对象
r = c.post(f"/api/materials/{mid}/reindex", json={}, headers=hdr)
body = r.get_json() if r.is_json else {}
check("空 JSON 也 202", r.status_code == 202, str(r.status_code))
check("同一材料复用同一个任务（幂等）", body.get("job_id") == first_job, f"{body.get('job_id')} vs {first_job}")

# 3. 非法策略：仍要拦住，且错误码要说清楚
r = c.post(f"/api/materials/{mid}/reindex", json={"strategy": "bogus"}, headers=hdr)
body = r.get_json() if r.is_json else {}
check("非法策略 400", r.status_code == 400, str(r.status_code))
check("错误码是 INVALID_STRATEGY", (body.get("error") or {}).get("code") == "INVALID_STRATEGY", str(body))

# 4. 审计里那条 400 必须记下真实错误码，不能再是 ERROR
import sqlite3  # noqa: E402

conn2 = sqlite3.connect(str(tmp / "data" / "app.db"))
rows = conn2.execute(
    "SELECT status, code FROM audit_events WHERE path LIKE '%/reindex' ORDER BY ts"
).fetchall()
conn2.close()
print("  审计:", rows)
check("审计留了 reindex 记录", bool(rows))
check(
    "400 那条记的是 INVALID_STRATEGY 而非 ERROR",
    any(st == 400 and code == "INVALID_STRATEGY" for st, code in rows),
    str(rows),
)

# 5. /api/csrf 能发新令牌（前端自愈重试用）
r = c.get("/api/csrf")
data = r.get_json() if r.is_json else {}
check("GET /api/csrf 200", r.status_code == 200, str(r.status_code))
check("返回 csrf_token", bool(data.get("csrf_token")), str(data))

print()
print("结果：" + ("全部通过" if ok else "有失败项"))
raise SystemExit(0 if ok else 1)
