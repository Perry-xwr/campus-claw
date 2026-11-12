"""第 10 课判据「面板看得见技能」：造出按技能分线的真实调用。

面板的曲线不能靠编数据：``mcp_tool_calls`` 里的每一行都必须来自一次真实调用。
本脚本按最短路把调用链路走通，供验收时复跑：

    登记 MCP 服务器 → 连接（发现工具）→ 建三个技能（各绑不同工具）
    → 学生提问（触发技能）→ run_skill_tools 实际调用 → 审计落库

``--rounds N`` 控制每个技能触发几次；``--fail`` 会在中途断开服务器再触发一次，
让某个技能多出 ``denied`` 记录——错误率那条线要有非零值才算被看见，不能只演成功。

用法（需先启动主应用与 mcp-server）::

    MCP_AUTH_TOKEN=demo-token python -m mcp_server          # mcp-server/ 下，默认 8090
    python scripts/skill_demo.py --base http://127.0.0.1:8100 \
        --mcp http://127.0.0.1:8101 --token demo-token --rounds 3 --fail round-2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# 本机调用必须绕过企业代理，否则 127.0.0.1 也会被转发出去。
for _key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"):
    os.environ.pop(_key, None)

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

#: 三个技能：名字 / 适用条件（触发词）/ 工具引用 / 说明 / 验收时的提问
#:
#: 触发词刻意互不重叠、提问也只命中自己那一条：``select_skill`` 按 id 顺序取
#: 第一个命中的技能，触发词若有交叉，第三行永远落在别人名下，三条线就画不出来。
SKILLS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "公式提示",
        "公式,面积",
        "formula_hint@campus-tools",
        "按关键词给出公式或解题步骤提示，不直接给最终答案。",
        "长方形面积公式是什么",
    ),
    (
        "单位换算",
        "换算",
        "unit_convert@campus-tools",
        "在米与厘米、千克与克之间换算，并说明换算依据。",
        "帮我把 5 米换算成厘米",
    ),
    (
        "公式加换算",
        "综合,练习",
        "formula_hint@campus-tools, unit_convert@campus-tools",
        "综合题：先给公式提示，再做单位换算。",
        "综合练习的步骤是什么",
    ),
)


def call(base: str, method: str, path: str, body=None, token: str | None = None,
         timeout: float = 120.0) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        status = exc.code
    try:
        return status, json.loads(text or "{}")
    except json.JSONDecodeError:
        # SSE 流不是 JSON：只要 HTTP 200 就算触发成功，正文用前 200 字留痕。
        return status, {"_sse": text[:200]}


def login(base: str, username: str, password: str) -> str:
    status, payload = call(base, "POST", "/api/login",
                           {"username": username, "password": password})
    if status != 200:
        raise SystemExit(f"登录失败：{username} → {status} {payload}")
    return payload["token"]


def ensure_server(base: str, teacher: str, mcp_url: str, mcp_token: str) -> tuple[int, bool]:
    """返回 (server_id, 是否已连接)；同名服务器已存在就复用。"""
    status, payload = call(base, "GET", "/api/mcp/servers", token=teacher)
    if status != 200:
        raise SystemExit(f"列服务器失败：{status} {payload}")
    for server in payload.get("servers") or []:
        if server["name"] == "campus-tools":
            return int(server["id"]), bool(server.get("connected"))
    status, payload = call(base, "POST", "/api/mcp/servers",
                           {"name": "campus-tools", "base_url": mcp_url,
                            "auth_token": mcp_token}, token=teacher)
    # 创建接口把对象包在 "server" 里；早期脚本读顶层 "id" 会 KeyError，这里两种都认。
    server = payload.get("server") if isinstance(payload, dict) else None
    if status in (200, 201) and isinstance(server, dict) and server.get("id"):
        return int(server["id"]), bool(server.get("connected"))
    # 并发或上一次中断留下的同名记录：重新列一次，按名取回，不把冲突当失败。
    status, payload = call(base, "GET", "/api/mcp/servers", token=teacher)
    for server in payload.get("servers") or []:
        if server["name"] == "campus-tools":
            return int(server["id"]), bool(server.get("connected"))
    raise SystemExit(f"建服务器失败：{status} {payload}")


def connect(base: str, teacher: str, server_id: int) -> list[str]:
    status, payload = call(base, "POST", f"/api/mcp/servers/{server_id}/connect", token=teacher)
    if status != 200:
        raise SystemExit(f"连接失败：{status} {payload}")
    return [tool.get("name") or tool.get("tool_name") for tool in payload.get("tools") or []]


def ensure_skills(base: str, teacher: str) -> None:
    """按名字对齐三个技能：缺的新建，触发词或工具变了就整份更新。

    只建不改会让第二次跑留下上一次的触发词——重复执行的脚本必须幂等，
    否则「同一命令得到同样结果」在技能这一层就不成立。
    """
    status, payload = call(base, "GET", "/api/skills", token=teacher)
    existing = {item["name"]: item for item in (payload.get("skills") or [])} if status == 200 else {}
    for name, trigger, tools, description, _question in SKILLS:
        source = (
            f"名称：{name}\n适用条件：{trigger}\n工具：{tools}\n资料：数学\n启用：是\n\n{description}"
        )
        current = existing.get(name)
        if current is None:
            status, payload = call(base, "POST", "/api/skills", {"source": source}, token=teacher)
            print(f"  建技能 {name}: {status}" + ("" if status < 400 else f" {payload}"))
            continue
        if current.get("trigger") == trigger and list(current.get("tools") or []) == \
                [item.strip() for item in tools.split(",")]:
            print(f"  技能 {name} 已是最新，跳过")
            continue
        status, payload = call(base, "PUT", f"/api/skills/{current['id']}",
                               {"source": source}, token=teacher)
        print(f"  更新技能 {name}: {status}" + ("" if status < 400 else f" {payload}"))


def ask(base: str, student: str, question: str) -> int:
    status, payload = call(base, "POST", "/api/conversations",
                           {"title": f"面板验证 {time.strftime('%H:%M:%S')}"}, token=student)
    conversation_id = payload.get("id")
    if status not in (200, 201) or not conversation_id:
        print(f"  建会话失败：{status} {payload}")
        return status or 0
    status, _payload = call(base, "POST", f"/api/conversations/{conversation_id}/messages",
                            {"content": question, "mode": "guide"}, token=student)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="造出按技能分线的真实调用")
    parser.add_argument("--base", default="http://127.0.0.1:8100")
    parser.add_argument("--mcp", default="http://127.0.0.1:8101")
    parser.add_argument("--token", default="demo-token", help="MCP 服务器令牌")
    parser.add_argument("--user", default="teacher_a")
    parser.add_argument("--password", default="TeacherA#2026")
    parser.add_argument("--student", default="student_a1")
    parser.add_argument("--student-password", default="StudentA1#2026")
    parser.add_argument("--rounds", type=int, default=1, help="每个技能触发几轮")
    parser.add_argument("--interval", type=float, default=0.0, help="轮间隔秒数")
    parser.add_argument("--fail", default="", choices=("", "round-1", "round-2", "round-3"),
                        help="在第 N 轮前断开服务器，制造 denied 记录")
    parser.add_argument("--dry-run", action="store_true", help="只看计划，不发请求")
    args = parser.parse_args()

    if args.dry_run:
        for name, _trigger, tools, _description, question in SKILLS:
            print(f"{name:<8} 工具={tools:<52} 提问={question}")
        return 0

    teacher = login(args.base, args.user, args.password)
    student = login(args.base, args.student, args.student_password)
    server_id, connected = ensure_server(args.base, teacher, args.mcp, args.token)
    if not connected:
        tools = connect(args.base, teacher, server_id)
        print(f"已连接 campus-tools，工具：{tools}")
    ensure_skills(args.base, teacher)

    for round_index in range(1, args.rounds + 1):
        if args.fail == f"round-{round_index}":
            status, payload = call(args.base, "POST",
                                   f"/api/mcp/servers/{server_id}/disconnect", token=teacher)
            print(f"  第 {round_index} 轮前断开服务器：{status}")
        for name, _trigger, _tools, _description, question in SKILLS:
            status = ask(args.base, student, question)
            print(f"  round {round_index} · {name} → 提问 HTTP {status}")
        if args.fail == f"round-{round_index}":
            connect(args.base, teacher, server_id)
            print("  已重新连接服务器")
        if args.interval:
            time.sleep(args.interval)
    print("完成。打开 /claw/ 看三条线是否各自动了几格。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
