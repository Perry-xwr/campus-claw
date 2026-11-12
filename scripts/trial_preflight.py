# -*- coding: utf-8 -*-
"""试用前技术预检：按 user-trial-record.md 里的任务，走一遍真实接口。

目的不是替用户试用，而是把「技术故障」和「产品问题」分开：
地址不通、账号登不进、上传后检索不到，这类问题不该记到试用者账上。

判定分三类，结论只由前两类决定：

- **阻断**：试用无法进行（登录失败、页面 5xx、上传后检索不到）。任一出现即退出码 1。
- **未覆盖**：依赖未配置的外部服务（缺 ``CHAT_MODEL`` 时提问返回 503 等）。
  记为 ``SKIP``，不算失败，报告里对应任务标「本轮未覆盖」。
- **通过**：其余。

用法::

    python scripts/trial_preflight.py                      # 默认 http://localhost:8080
    python scripts/trial_preflight.py http://192.168.1.5:8080
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apitest"))

from common import Client  # noqa: E402

ACCOUNTS = {
    "teacher_a": "TeacherA#2026",
    "student_a1": "StudentA1#2026",
    "student_b1": "StudentB1#2026",
}

BLOCKERS: list[str] = []
SKIPS: list[str] = []
PASSED: list[str] = []


def record(kind: str, name: str, detail: str) -> None:
    if kind == "block":
        BLOCKERS.append(f"{name}：{detail}")
    elif kind == "skip":
        SKIPS.append(f"{name}：{detail}")
    else:
        PASSED.append(f"{name}：{detail}")
    print(f"[{kind.upper():5s}] {name} — {detail}")


def is_unconfigured(payload: object) -> bool:
    """503 且带明确的「不可用」错误码，属于未覆盖而不是故障。

    服务端的错误体是嵌套的：``{"error": {"code": "RETRIEVAL_UNAVAILABLE", ...}}``，
    不能直接对 ``payload["error"]`` 取字符串比对。
    """
    if not isinstance(payload, dict):
        return False
    err = payload.get("error")
    code = err.get("code") if isinstance(err, dict) else err
    return str(code or payload.get("code") or "") in {
        "RETRIEVAL_UNAVAILABLE", "MODEL_UNAVAILABLE", "CHAT_UNAVAILABLE",
    }


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
    print(f"预检目标：{base}\n")

    teacher = Client(base)
    student_a = Client(base)
    student_b = Client(base)

    # 任务 1：三个账号都要能登录
    for name, client in (("teacher_a", teacher), ("student_a1", student_a),
                         ("student_b1", student_b)):
        status = client.login(name, ACCOUNTS[name])
        if status == 200 and client.token:
            record("pass", f"登录 {name}", f"HTTP {status}")
        else:
            record("block", f"登录 {name}", f"HTTP {status}，拿不到令牌")

    if BLOCKERS:
        print("\n登录就失败，后面的任务没有意义，提前结束。")
        return 1

    # 任务 2：教师上传
    probe = f"TRIAL_PROBE_{int(time.time())}"
    body = f"# 试用预检材料\n\n含标记 {probe}，用于验证上传与检索链路。\n".encode()
    status, payload = teacher.upload("trial_probe.md", body, title="试用预检材料")
    material_id = None
    if status == 201 and isinstance(payload, dict):
        material_id = payload.get("material_id") or payload.get("id")
        record("pass", "教师上传材料", f"HTTP {status}，id={material_id}")
    else:
        record("block", "教师上传材料", f"HTTP {status}")

    # 学生上传应被拒：这是设计，不是缺陷
    status, _ = student_a.json("POST", "/api/materials/upload", raw=b"x",
                               headers={"Content-Type": "multipart/form-data; boundary=x"})
    if status in (401, 403):
        record("pass", "学生上传被拒（设计如此）", f"HTTP {status}")
    else:
        record("block", "学生上传应被拒", f"实际 HTTP {status}")

    # 任务 3：上传后能在检索里命中（DEF-05 的验收点，必须真等）
    if material_id:
        hit = 0
        for _ in range(10):
            time.sleep(2)
            status, payload = student_a.json("POST", "/api/search",
                                             {"query": probe, "mode": "keyword"})
            hits = payload.get("hits", []) if isinstance(payload, dict) else []
            hit = len(hits)
            if hit:
                break
        if hit:
            record("pass", "上传后关键词检索命中", f"命中 {hit} 条")
        else:
            record("block", "上传后关键词检索命中", "等待 20 秒仍 0 命中")

    # 任务 4：跨班隔离
    status, payload = student_b.json("POST", "/api/search",
                                     {"query": probe, "mode": "keyword"})
    hits = payload.get("hits", []) if isinstance(payload, dict) else []
    if status == 200 and not hits:
        record("pass", "跨班隔离（B 班搜不到 A 班材料）", "0 命中")
    else:
        record("block", "跨班隔离", f"HTTP {status}，命中 {len(hits)} 条")

    # 任务 5：教师面板
    for path in ("/dashboard", "/api/observability"):
        status, _ = teacher.page(path)
        if status == 200:
            record("pass", f"教师巡检 {path}", f"HTTP {status}")
        else:
            record("block", f"教师巡检 {path}", f"HTTP {status}")

    # 可选任务：混合检索与提问，依赖模型配置
    for name, path, payload_body in (
        ("混合检索", "/api/search", {"query": probe, "mode": "hybrid"}),
        ("提问", "/api/ask", {"question": "这份材料讲了什么？"}),
    ):
        status, payload = student_a.json("POST", path, payload_body)
        if status == 200:
            record("pass", name, f"HTTP {status}")
        elif status == 503 and is_unconfigured(payload):
            record("skip", name, "503 未配置模型，本轮不覆盖")
        else:
            record("block", name, f"HTTP {status}")

    status, _ = student_a.page("/qa/faq")
    record("pass" if status == 200 else "block", "FAQ 页面可打开", f"HTTP {status}")

    # 清理预检材料
    if material_id:
        status, _ = teacher.json("DELETE", f"/api/materials/{material_id}")
        record("pass" if status in (200, 204) else "block", "清理预检材料", f"HTTP {status}")

    print("\n" + "=" * 56)
    print(f"通过 {len(PASSED)} ｜ 阻断 {len(BLOCKERS)} ｜ 未覆盖 {len(SKIPS)}")
    for line in BLOCKERS:
        print("  阻断 ·", line)
    for line in SKIPS:
        print("  未覆盖 ·", line)
    print("结论：", "可以开始试用" if not BLOCKERS else "先修阻断项，不要开始试用")
    return 0 if not BLOCKERS else 1


if __name__ == "__main__":
    raise SystemExit(main())
