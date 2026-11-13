"""临时校验：材料列表的索引状态可见性与卡住告警。跑完即删。"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="idxui-"))
data_dir = tmp / "data"
os.environ["CAMPUSCLAW_DATA_DIR"] = str(data_dir)
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


def csrf_from(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "页面没有 csrf_token"
    return m.group(1)


# 1. 教师登录
html = c.get("/login").get_data(as_text=True)
r = c.post(
    "/login",
    data={"csrf_token": csrf_from(html), "username": "teacher_a", "password": "TeacherA#2026"},
    follow_redirects=True,
)
check("教师登录并进入材料页", r.status_code == 200, str(r.status_code))
token = csrf_from(r.get_data(as_text=True))

# 2. 上传一份材料
r = c.post(
    "/api/materials/upload",
    data={
        "csrf_token": token,
        "title": "索引状态验证讲义",
        "file": (BytesIO("# 二元一次方程组\n\n移项忘记变号是常见错误。\n".encode()), "a.md"),
    },
    content_type="multipart/form-data",
    headers={"X-CSRF-Token": token},
)
check("上传 201", r.status_code == 201, f"{r.status_code} {r.get_data(as_text=True)[:80]}")

# 3. 排队中
html = c.get("/materials").get_data(as_text=True)
check("列表显示「索引排队中」", "索引排队中" in html)
check("刚上传不误报卡住", "索引服务可能没有运行" not in html)

# 4. 把刚上传那份的状态改老，模拟 worker 没跑
conn = sqlite3.connect(str(data_dir / "app.db"))
mid = conn.execute("SELECT MAX(id) FROM materials").fetchone()[0]
conn.execute(
    "UPDATE material_index SET status='pending', updated_at='2026-11-13T00:00:00+00:00' WHERE material_id=?",
    (mid,),
)
conn.commit()
conn.close()

html = c.get("/materials").get_data(as_text=True)
check("卡住时出现告警条", "索引服务可能没有运行" in html)
check("告警里给出启动命令", "campusclaw.index_worker" in html)
m = re.search(r"已 (\d+) 分钟没有进展", html)
check("告警里带等待分钟数", bool(m), (m.group(1) + " 分钟") if m else "未匹配")

# 5. 真跑一次 worker，状态应变 ready
env = dict(os.environ)
env.update({
    "CAMPUSCLAW_DATA_DIR": str(data_dir),
    "CAMPUSCLAW_UPLOAD_DIR": str(tmp / "uploads"),
})
proc = subprocess.run(
    [sys.executable, "-m", "campusclaw.index_worker", "--once"],
    cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=180,
)
out = (proc.stdout or "") + (proc.stderr or "")
check("worker --once 正常退出", proc.returncode == 0, f"rc={proc.returncode}")
check("worker 走了关键词降级", "Keyword fallback rebuilt" in out,
      (out.strip().splitlines() or ["(无输出)"])[-1][:90])

html = c.get("/materials").get_data(as_text=True)
check("建好后显示「已建索引」", "已建索引" in html)
check("建好后告警消失", "索引服务可能没有运行" not in html)

print()
print("结果：" + ("全部通过" if ok else "有失败项"))
raise SystemExit(0 if ok else 1)
