"""第 10 课轻量端走查：按 H5 页面上的四步跑一遍，不经过浏览器。

轻量端复用桌面端的接口，因此「四步能不能走完」可以在命令行验证——
页面只是这四步的界面。脚本逐条打印实际状态码，任一条不符预期即非零退出：

    1) 登录拿令牌
    2) 提交作业 → 202 + 任务标识（响应体不含分数）
    3) 轮询任务 → pending → running → succeeded
    4) 换别班账号取本班材料 → 404（不存在与无权不可区分）

用法::

    python scripts/h5_walkthrough.py --base http://127.0.0.1:8110
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

for _key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"):
    os.environ.pop(_key, None)

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(base: str, method: str, path: str, body=None, token: str | None = None,
         timeout: float = 60.0) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace")
            return response.status, json.loads(text or "{}")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(text or "{}")
        except json.JSONDecodeError:
            return exc.code, {"_raw": text[:200]}


def login(base: str, username: str, password: str) -> str:
    status, payload = call(base, "POST", "/api/login",
                           {"username": username, "password": password})
    print(f"  1) 登录 {username}: HTTP {status}")
    if status != 200:
        raise SystemExit(f"登录失败：{status} {payload}")
    return payload["token"]


def main() -> int:
    parser = argparse.ArgumentParser(description="轻量端四步走查")
    parser.add_argument("--base", default="http://127.0.0.1:8110")
    parser.add_argument("--username", default="student_a1")
    parser.add_argument("--password", default="StudentA1#2026")
    parser.add_argument("--other", default="student_b1",
                        help="另班账号，用来验证跨班 404")
    parser.add_argument("--other-password", default="StudentB1#2026")
    parser.add_argument("--polls", type=int, default=6)
    args = parser.parse_args()

    failures: list[str] = []
    token = login(args.base, args.username, args.password)

    status, payload = call(args.base, "GET", "/api/materials", token=token)
    items = payload.get("items") or []
    print(f"  2) 材料列表: HTTP {status}，{len(items)} 份")
    if status != 200:
        failures.append("材料列表不为 200")

    held = items[0]["id"] if items else None
    status, payload = call(args.base, "POST", "/api/submissions",
                           {"assignment_ref": f"轻量端走查 {time.strftime('%H:%M:%S')}",
                            "content": "设未知数为 x，列方程后求解。"}, token=token)
    task_id = payload.get("task_id") or ""
    leaked = "score" in json.dumps(payload, ensure_ascii=False)
    print(f"  3) 提交作业: HTTP {status}，task_id={task_id or '—'}，响应含分数={leaked}")
    if status != 202 or not task_id or leaked:
        failures.append("提交未按 202 + 任务标识返回，或响应体泄露评分")

    seen: list[str] = []
    for _round in range(args.polls):
        status, payload = call(args.base, "GET", f"/api/tasks/{task_id}", token=token)
        state = payload.get("status") or f"HTTP {status}"
        seen.append(state)
        print(f"  4) 轮询: HTTP {status}，状态 {state}")
        if state in ("succeeded", "failed", "dead"):
            break
        time.sleep(0.8)
    if "succeeded" not in seen:
        failures.append("轮询未到达 succeeded：" + " → ".join(seen))

    other = login(args.base, args.other, args.other_password)
    if held is None:
        print("  5) 跨班校验: 本班没有材料，跳过")
    else:
        status, payload = call(args.base, "GET", f"/api/materials/{held}", token=other)
        body = json.dumps(payload, ensure_ascii=False)
        print(f"  5) 别班账号取材料 {held}: HTTP {status}，响应={body[:80]}")
        if status != 404:
            failures.append(f"跨班取材料应 404，实际 {status}")
        # 404 的响应体里也不允许出现本班标题——状态码对、内容泄露同样是失败。
        titles = [item["title"] for item in items if item.get("title")]
        if any(title and title in body for title in titles):
            failures.append("404 响应体泄露了本班材料标题")

    if failures:
        print("\n走查未通过：")
        for item in failures:
            print("  - " + item)
        return 1
    print("\n四步全部符合预期（登录 → 202 → 轮询到 succeeded → 跨班 404）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
