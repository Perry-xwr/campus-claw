"""CSRF 反例 · PUT /api/prompt

第 9 课要求：从另一个页面伪造表单提交（带着浏览器自动附上的 Cookie 会话），
期望因缺少一次性令牌被拒（403）。两道防线分别验证：Cookie 的 SameSite 属性（浏览器侧），
以及服务端逐次校验的一次性令牌（服务端侧）。
"""

from apitest.common import record

CASE = {
    "name": "CSRF：Cookie 会话缺令牌改写提示词",
    "kind": "反例",
    "method": "PUT",
    "path": "/api/prompt",
    "premise": "teacher_a 已建立 Cookie 会话；写接口要求一次性令牌；Bearer 请求不在此列",
}

PROBE = "CSRF_PROBE_9B 伪造写入"


def run(ctx):
    results = []
    client = ctx.teacher_cookie

    login = ctx.cookie_login("teacher_a")
    login_headers = dict(getattr(client, "last_headers", {}) or {})
    cookie_header = " ".join(
        value for key, value in login_headers.items() if key.lower() == "set-cookie")
    results.append(record(
        name="CSRF 前置：Cookie 会话建立且带 SameSite",
        premise="GET /login 取令牌 → POST /login 建立会话",
        action="检查登录响应的 Set-Cookie 属性",
        expected="HTTP 302/200，且会话 Cookie 带 SameSite 属性（浏览器侧第一道）",
        actual=f"HTTP {login}；Set-Cookie {'含 SameSite=Lax' if 'samesite=lax' in cookie_header.lower() else '未见 SameSite'}",
        ok=login in (200, 302) and "samesite=lax" in cookie_header.lower(),
    ))

    status, before = ctx.teacher.json("GET", "/api/prompt")
    body_before = before.get("body", "")

    token = client.csrf_token("/materials")
    status, payload = client.json("PUT", "/api/prompt", {"body": PROBE})
    code = payload.get("error", {}).get("code") if isinstance(payload.get("error"), dict) else None
    results.append(record(
        name="CSRF：缺令牌的写请求被拒",
        premise=f"Cookie 会话有效；已取到一次性令牌（长度 {len(token)}），但本次故意不带",
        action=f'PUT /api/prompt {{"body": "{PROBE}"}}，仅携带 Cookie，无 X-CSRF-Token',
        expected="HTTP 403，错误码 CSRF_INVALID",
        actual=f"HTTP {status}，错误码 {code}",
        ok=status == 403,
    ))

    _, after = ctx.teacher.json("GET", "/api/prompt")
    body_after = after.get("body", "")
    results.append(record(
        name="CSRF：被拒请求无写入副作用",
        premise="上一步的伪造请求已被拒",
        action="GET /api/prompt 比对被拒前后的正文",
        expected="正文与拒绝前完全一致",
        actual="正文未变" if body_after == body_before else f"正文被改写为 {body_after[:40]!r}",
        ok=body_after == body_before,
    ))

    status, _text = client.request("PUT", "/api/prompt", body={"body": PROBE},
                                   headers={"X-CSRF-Token": token})
    _, final = ctx.teacher.json("GET", "/api/prompt")
    changed = final.get("body", "") == PROBE
    results.append(record(
        name="CSRF：带正确令牌的写请求放行",
        premise="同一 Cookie 会话，补上服务端签发的一次性令牌",
        action=f'PUT /api/prompt，携带 X-CSRF-Token（长度 {len(token)}）',
        expected="HTTP 200 且正文更新——证明挡住上一步的确实是令牌校验，而非其他判定",
        actual=f"HTTP {status}，正文{'已更新' if changed else '未更新'}",
        ok=status == 200 and changed,
        kind="正常",
    ))
    return results
