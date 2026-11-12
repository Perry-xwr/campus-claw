"""CampusClaw 端到端功能检查（验证用，不修改被测代码）。

前置：被测实例已在 8097 运行，MCP 服务已在 8096 运行。
输出：.verify/e2e-result.json + 控制台明细。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(key, None)

BASE = "http://127.0.0.1:8097"
MCP_BASE = "http://127.0.0.1:8096"
MCP_TOKEN = "verify-token-2026"
JSON_API = "application/json, text/event-stream"

if os.name == "nt":
    ROOT = Path("D:/campus-claw")
    PY = ROOT / ".venv/Scripts/python.exe"
    HOME = "D:/campus-claw/.verify/appdata"
else:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    PY = ROOT / ".venv/bin/python"
    HOME = str(ROOT / ".verify/appdata")

RESULTS: list[dict] = []


def record(group: str, name: str, ok: bool, expected: str, actual: str, detail: str = "") -> None:
    RESULTS.append(
        {"group": group, "name": name, "expected": expected, "actual": actual,
         "verdict": "PASS" if ok else "FAIL", "detail": detail}
    )
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {group:<8} {name:<34} 期望={expected:<22} 实际={actual}")
    if detail and not ok:
        print(f"        detail: {detail[:400]}")


class Client:
    """Bearer 为主的最小 HTTP 客户端。"""

    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def request(self, method: str, path: str, body=None, *, headers=None, raw=False,
                base: str = BASE, timeout: int = 60):
        data = None
        hdrs = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        if self.token:
            hdrs["Authorization"] = "Bearer " + self.token
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(base + path, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
                return resp.status, (text if raw else _maybe_json(text))
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            return exc.code, (text if raw else _maybe_json(text))

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body if body is not None else {}, **kw)

    def patch(self, path, body, **kw):
        return self.request("PATCH", path, body, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    def upload(self, filename: str, content: str, title: str | None = None):
        boundary = "----campusclawverify7d3f"
        parts: list[bytes] = []
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: text/markdown\r\n\r\n'.encode()
            + content.encode("utf-8") + b"\r\n"
        )
        if title is not None:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\n'.encode()
                + title.encode("utf-8") + b"\r\n"
            )
        parts.append(f"--{boundary}--\r\n".encode())
        payload = b"".join(parts)
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": "Bearer " + (self.token or ""),
        }
        req = urllib.request.Request(BASE + "/api/materials/upload", data=payload,
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, _maybe_json(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            return exc.code, _maybe_json(exc.read().decode("utf-8", "replace"))

    def sse(self, path: str, body: dict, timeout: int = 90):
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream",
                   "Authorization": "Bearer " + (self.token or "")}
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")


def _maybe_json(text: str):
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_raw": text[:400]}


def dig(payload, *keys, default=None):
    cur = payload
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event, data_lines = "message", []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if data_lines:
            try:
                events.append((event, json.loads("\n".join(data_lines))))
            except json.JSONDecodeError:
                events.append((event, {"_raw": "\n".join(data_lines)[:300]}))
    return events


def login(username: str, password: str) -> tuple[int, str | None]:
    status, payload = Client().post("/api/login", {"username": username, "password": password})
    return status, dig(payload, "token")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def _no_redirect_status(path: str) -> tuple[int, str]:
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(BASE + path, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


teacher_a_token = student_a1_token = student_b1_token = teacher_b_token = None


def main() -> int:
    health = Client()
    code, body = health.get("/health")
    record("A-健康检查", "GET /health", code == 200 and dig(body, "status") == "ok",
           "200 status=ok", f"{code} {dig(body, 'status')}")

    code, _ = _no_redirect_status("/materials")
    record("A-健康检查", "匿名访问 /materials", code == 302, "302 重定向登录页", str(code))

    code, body = health.get("/api/materials")
    record("A-健康检查", "匿名访问 /api/materials", code == 401,
           "401 AUTH_REQUIRED", f"{code} {dig(body, 'error', 'code')}")

    code, body = health.get("/openapi.json")
    paths = len(dig(body, "paths", default={}) or {})
    record("A-健康检查", "OpenAPI 文档", code == 200 and paths >= 30,
           "200 且 paths>=30", f"{code} paths={paths}")

    global teacher_a_token, student_a1_token, student_b1_token, teacher_b_token
    creds = {
        "teacher_a": "TeacherA#2026", "student_a1": "StudentA1#2026",
        "student_b1": "StudentB1#2026", "teacher_b": "TeacherB#2026",
    }
    tokens = {}
    for user, pwd in creds.items():
        code, token = login(user, pwd)
        tokens[user] = token
        record("B-认证", f"登录 {user}", code == 200 and bool(token),
               "200 且返回 token", f"{code} token={'有' if token else '无'}")
    teacher_a_token, student_a1_token = tokens["teacher_a"], tokens["student_a1"]
    student_b1_token, teacher_b_token = tokens["student_b1"], tokens["teacher_b"]

    code, body = Client().post("/api/login", {"username": "teacher_a", "password": "wrong-pass"})
    record("B-认证", "错误口令登录", code == 401, "401", f"{code} {dig(body, 'error', 'code')}")

    ta = Client(teacher_a_token)
    code, body = ta.get("/api/me")
    record("B-认证", "GET /api/me 身份", code == 200 and dig(body, "role") == "teacher"
           and dig(body, "class_name") == "A",
           "200 role=teacher class=A",
           f"{code} role={dig(body, 'role')} class={dig(body, 'class_name')}")

    sa = Client(student_a1_token)
    code, body = sa.get("/api/tasks/observations")
    record("B-认证", "学生访问教师接口", code == 403, "403 ROLE_FORBIDDEN",
           f"{code} {dig(body, 'error', 'code')}")

    # --- C 组：Cookie 会话 + CSRF ---
    cookie_jar = urllib.request.HTTPCookieProcessor()
    opener = urllib.request.build_opener(cookie_jar)
    try:
        html = opener.open(BASE + "/login", timeout=30).read().decode()
        import re as _re
        match = _re.search(r'name="csrf_token" value="([^"]+)"', html)
        form_token = match.group(1) if match else ""
        req = urllib.request.Request(
            BASE + "/login",
            data=urllib.parse.urlencode({"username": "teacher_a",
                                         "password": "TeacherA#2026",
                                         "csrf_token": form_token}).encode(),
            method="POST",
        )
        resp = opener.open(req, timeout=30)
        cookie_login_ok = resp.status == 200
        failed_csrf = None
        try:
            opener.open(urllib.request.Request(
                BASE + "/api/qa/questions",
                data=json.dumps({"title": "CSRF-无令牌写入尝试",
                                 "body": "若此问题被创建，说明写接口未校验 CSRF。"}).encode(),
                headers={"Content-Type": "application/json"}, method="POST"), timeout=30)
            failed_csrf = 200
        except urllib.error.HTTPError as exc:
            failed_csrf = exc.code
        record("C-CSRF", "Cookie 会话登录", cookie_login_ok, "200", str(resp.status))
        record("C-CSRF", "写接口缺 CSRF 令牌", failed_csrf == 403, "403", str(failed_csrf))

        # 登录后会轮换 CSRF 令牌，须从登录后的页面重新取
        page = opener.open(BASE + "/materials", timeout=30).read().decode()
        rotated = _re.search(r"const csrf = '([^']+)'", page)
        live_token = rotated.group(1) if rotated else ""
        try:
            opener.open(urllib.request.Request(
                BASE + "/api/qa/questions",
                data=json.dumps({"title": "CSRF-带令牌写入",
                                 "body": "携带 X-CSRF-Token 的写入应被接受。"}).encode(),
                headers={"Content-Type": "application/json",
                         "X-CSRF-Token": live_token}, method="POST"), timeout=30)
            with_csrf = 200
        except urllib.error.HTTPError as exc:
            with_csrf = exc.code
        record("C-CSRF", "写接口带 CSRF 令牌", with_csrf in (200, 201) and bool(live_token),
               "200/201", f"{with_csrf} token={'有' if live_token else '无'}")
    except Exception as exc:  # noqa: BLE001
        record("C-CSRF", "Cookie 会话登录", False, "200", f"异常 {exc}")

    # --- D 组：材料管理 ---
    code, before = ta.get("/api/materials")
    a_before = len(dig(before, "items", default=[]) or [])
    code, up = ta.upload("verify-note.md", "# 验证材料\n\n本材料用于功能检测，关键词 VERIFY_MARKER_2026。\n",
                         title="验证用材料")
    new_id = dig(up, "material_id")
    record("D-材料", "教师上传 .md", code == 201 and bool(new_id), "201 且返回 material_id",
           f"{code} id={new_id}")

    code, after = ta.get("/api/materials")
    a_after = len(dig(after, "items", default=[]) or [])
    record("D-材料", "上传后本班列表可见", a_after == a_before + 1,
           f"{a_before + 1} 条", f"{a_after} 条")

    code, body = sa.get(f"/api/materials/{new_id}")
    record("D-材料", "同班学生可读材料", code == 200, "200", f"{code}")

    sb = Client(student_b1_token)
    code, body = sb.get(f"/api/materials/{new_id}")
    record("D-材料", "跨班读取材料", code == 404, "404 MATERIAL_NOT_FOUND",
           f"{code} {dig(body, 'error', 'code')}")

    code, body = sb.get(f"/api/materials/{new_id}/index-status")
    record("D-材料", "跨班查索引状态", code == 404, "404", f"{code}")

    code, body = sa.upload("student.md", "# 学生尝试上传\n", title="学生材料")
    record("D-材料", "学生上传被拒", code == 403, "403 ROLE_FORBIDDEN",
           f"{code} {dig(body, 'error', 'code')}")

    code, body = ta.upload("bad.pdf", "%PDF-1.4 fake")
    record("D-材料", "拒绝非 txt/md 扩展名", code in (400, 415), "400/415",
           f"{code} {dig(body, 'error', 'code')}")

    code, body = ta.patch(f"/api/materials/{new_id}", {"title": "验证用材料-改名"})
    code2, detail = ta.get(f"/api/materials/{new_id}")
    record("D-材料", "教师改标题", code == 200 and dig(detail, "material", "title") == "验证用材料-改名",
           "200 且标题更新", f"{code} title={dig(detail, 'material', 'title')}")

    code, body = ta.get(f"/api/materials/{new_id}/index-status")
    record("D-材料", "新上传材料索引状态（观察）", True,
           "记录实际状态", f"{code} {json.dumps(body, ensure_ascii=False)[:160]}")

    # --- E 组：检索 ---
    code, body = ta.post("/api/search", {"query": "示例讲义", "mode": "keyword", "limit": 5})
    hits = dig(body, "hits", default=[]) or []
    first = hits[0] if hits else {}
    fields_ok = all(k in first for k in ("material_id", "chunk_index", "start_offset",
                                         "end_offset", "title", "material_url", "excerpt"))
    record("E-检索", "关键词检索命中且带来源", code == 200 and hits and fields_ok,
           "200 且含 material_id/chunk/区间/链接",
           f"{code} hits={len(hits)} 字段齐全={fields_ok}")

    a_ids = {item["id"] for item in (dig(after, "items", default=[]) or [])}
    leaked = [h for h in hits if h.get("material_id") not in a_ids]
    record("E-检索", "检索结果限本班", not leaked, "0 条跨班命中", f"{len(leaked)} 条越界")

    code, body = sb.post("/api/search", {"query": "A_ONLY_SEED", "mode": "keyword", "limit": 5})
    b_hits = dig(body, "hits", default=[]) or []
    b_ids = {item["id"] for item in (dig(sb.get("/api/materials")[1], "items", default=[]) or [])}
    record("E-检索", "B 班搜索 A 班专属标记", all(h.get("material_id") in b_ids for h in b_hits),
           "无 A 班材料命中", f"hits={len(b_hits)} 越界={sum(1 for h in b_hits if h.get('material_id') not in b_ids)}")

    code, body = ta.post("/api/search", {"query": "示例讲义", "mode": "vector", "limit": 5})
    record("E-检索", "未配嵌入时 vector 模式", code == 503, "503 RETRIEVAL_UNAVAILABLE",
           f"{code} {dig(body, 'error', 'code')}")

    code, body = ta.post("/api/search", {"query": "", "mode": "keyword"})
    record("E-检索", "空查询校验", code == 400, "400 INVALID_QUERY", f"{code} {dig(body, 'error', 'code')}")

    code, body = ta.post("/api/search", {"query": "示例", "mode": "keyword", "limit": 999})
    record("E-检索", "limit 越界校验", code == 400, "400", f"{code}")

    # --- F 组：解题助手（用学生身份创建并提问，验证会话归属） ---
    code, conv = sa.post("/api/conversations", {"title": "验证会话"})
    conv_id = (dig(conv, "id") or dig(conv, "conversation", "id")
               or dig(conv, "conversation_id"))
    record("F-助手", "创建会话", code in (200, 201) and bool(conv_id),
           "201 且返回会话 id", f"{code} id={conv_id}")

    sse_ok = False
    mode_seen = None
    events: list = []
    if conv_id:
        try:
            status, text = sa.sse(f"/api/conversations/{conv_id}/messages",
                                  {"content": "示例讲义里讲了什么？", "mode": "guide"})
            events = parse_sse(text)
            mode_seen = next((dig(d, "meta", "retrieval_mode") for e, d in events
                              if e == "meta" or dig(d, "meta") is not None), None)
            sse_ok = status == 200 and bool(events)
            record("F-助手", "SSE 流式回答", sse_ok, "200 且有多条 SSE 事件",
                   f"{status} events={len(events)} retrieval_mode={mode_seen}")
        except Exception as exc:  # noqa: BLE001
            record("F-助手", "SSE 流式回答", False, "200 且有多条 SSE 事件", f"异常 {exc}")

    if conv_id:
        code, _ = sa.delete(f"/api/conversations/{conv_id}")
        record("F-助手", "删除会话", code in (200, 204), "200/204", f"{code}")

    code, listing = sa.get("/api/conversations")
    record("F-助手", "会话列表可读", code == 200 and isinstance(
        dig(listing, "conversations", default=listing), list),
        "200", f"{code}")

    # --- G 组：答疑广场 ---
    code, q = sa.post("/api/qa/questions", {"title": "验证提问标题",
                                            "body": "验证用问题正文，关键词 VERIFY_QA。"})
    qid = dig(q, "id") or dig(q, "question", "id")
    record("G-答疑", "学生提问", code in (200, 201) and bool(qid),
           "201 OPEN", f"{code} id={qid} status={dig(q, 'status') or dig(q, 'question', 'status')}")

    reply_id = None
    if qid:
        code, rep = sa.post(f"/api/qa/questions/{qid}/replies", {"body": "验证用回复正文。"})
        reply_id = dig(rep, "id") or dig(rep, "reply", "id")
        code2, detail = sa.get(f"/api/qa/questions/{qid}")
        st = dig(detail, "status") or dig(detail, "question", "status")
        record("G-答疑", "回复后状态 ANSWERED", code in (200, 201) and st == "ANSWERED",
               "状态 ANSWERED", f"{code} status={st} reply_id={reply_id}")

    if qid and reply_id:
        code, body = ta.post(f"/api/qa/questions/{qid}/accept", {"reply_id": reply_id})
        code2, detail = ta.get(f"/api/qa/questions/{qid}")
        st = dig(detail, "status") or dig(detail, "question", "status")
        record("G-答疑", "教师采纳后 ACCEPTED", code in (200, 201) and st == "ACCEPTED",
               "状态 ACCEPTED", f"{code} status={st}")

    if qid:
        code, body = ta.post(f"/api/qa/questions/{qid}/close", {})
        code2, detail = ta.get(f"/api/qa/questions/{qid}")
        st = dig(detail, "status") or dig(detail, "question", "status")
        record("G-答疑", "教师关闭后 CLOSED", code in (200, 201) and st == "CLOSED",
               "状态 CLOSED", f"{code} status={st}")

    code, body = sb.get(f"/api/qa/questions/{qid}")
    record("G-答疑", "跨班读问题", code == 404, "404", f"{code}")

    code, stats = ta.get("/api/qa/stats")
    total = dig(stats, "total")
    parts = sum(dig(stats, k, default=0) or 0 for k in
                ("pending", "resolved", "closed_unresolved"))
    record("G-答疑", "统计恒等式", total == parts,
           "pending+resolved+closed_unresolved == total", f"total={total} 分项和={parts}")

    if qid:
        code, faq = ta.post("/api/qa/faqs", {"question_id": qid,
                                             "question_text": "验证提问标题",
                                             "answer_text": "验证用回复正文。"})
        faq_ok = code in (200, 201)
        code2, mats = ta.get("/api/materials")
        record("G-答疑", "FAQ 发布沉淀为材料", faq_ok and any(
            "FAQ" in (m.get("title") or "") or "faq" in (m.get("original_filename") or "").lower()
            for m in (dig(mats, "items", default=[]) or [])),
            "201 且本班材料新增 FAQ 材料",
            f"{code} 材料数={len(dig(mats, 'items', default=[]) or [])}")

    # --- H 组：异步批改 ---
    code, sub1 = ta.post("/api/submissions", {"assignment_ref": "HW-VERIFY-01",
                                              "content": "验证用作答内容。"})
    task_id = dig(sub1, "task_id") if isinstance(sub1, dict) else None
    has_score = isinstance(sub1, dict) and any(
        k in json.dumps(sub1) for k in ('"score"', '"grade"', '"result"'))
    record("H-异步", "提交返回 202 且不含评分", code == 202 and bool(task_id) and not has_score,
           "202 + task_id，无评分字段", f"{code} task_id={task_id} 含评分={has_score}")

    if task_id:
        env = dict(os.environ)
        env.update({"CAMPUSCLAW_HOME": HOME, "PYTHONPATH": str(ROOT)})
        for key in ("SECRET_KEY",):
            env.pop(key, None)
        run = subprocess.run([str(PY), "-m", "campusclaw.task_worker", "--once"],
                             cwd=str(ROOT), env=env, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=180)
        code, body = ta.get(f"/api/tasks/{task_id}")
        st = dig(body, "status")
        record("H-异步", "消费者执行后完成", code == 200 and st in ("succeeded", "done"),
               "状态 succeeded", f"{code} status={st} worker_exit={run.returncode}")

    code, sub2 = ta.post("/api/submissions", {"assignment_ref": "HW-VERIFY-01",
                                              "content": "验证用作答内容。"})
    second_id = dig(sub2, "task_id") if isinstance(sub2, dict) else None
    record("H-异步", "重复提交幂等", bool(task_id) and second_id == task_id,
           f"同一 task_id {task_id}", f"第二次={second_id}")

    code, body = ta.post("/api/submissions", {"assignment_ref": "HW-VERIFY-02",
                                              "content": "x", "score": 100})
    record("H-异步", "拒绝合同外字段", code == 400, "400 TASK_INPUT_INVALID",
           f"{code} {dig(body, 'error', 'code')}")

    if task_id:
        code, body = sb.get(f"/api/tasks/{task_id}")
        record("H-异步", "跨班查任务", code == 404, "404", f"{code}")

    code, body = ta.get("/api/tasks/observations")
    record("H-异步", "队列观测接口", code == 200 and "pending" in (body or {}),
           "200 含 pending/dead 等指标", f"{code} keys={list((body or {}).keys())[:6]}")

    # --- I 组：MCP ---
    code, body = Client().get("/health", base=MCP_BASE)
    record("I-MCP", "MCP 服务健康", code == 200 and dig(body, "service") == "campus-tools",
           "200 service=campus-tools", f"{code} {dig(body, 'service')}")

    req = urllib.request.Request(
        MCP_BASE + "/mcp",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(),
        headers={"Content-Type": "application/json", "Accept": JSON_API}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            no_token_code = resp.status
    except urllib.error.HTTPError as exc:
        no_token_code = exc.code
    record("I-MCP", "MCP 无令牌被拒", no_token_code == 401, "401", str(no_token_code))

    code, body = sa.post("/api/mcp/servers", {"name": "verify-tools",
                                              "base_url": MCP_BASE,
                                              "auth_token": MCP_TOKEN})
    record("I-MCP", "学生登记 MCP 被拒", code == 403, "403", f"{code} {dig(body, 'error', 'code')}")

    code, body = ta.post("/api/mcp/servers", {"name": "verify-tools",
                                              "base_url": MCP_BASE,
                                              "auth_token": MCP_TOKEN})
    server_id = dig(body, "server", "id") or dig(body, "id")
    record("I-MCP", "教师登记 MCP 服务器", code in (200, 201) and bool(server_id),
           "201 且返回 id", f"{code} id={server_id} 回显令牌={('auth_token' in (body or {})) or ('auth_token' in json.dumps(dig(body, 'server', default={}) or {}))}")

    if server_id:
        code, body = ta.post(f"/api/mcp/servers/{server_id}/connect", {})
        tools = dig(body, "tools", default=[]) or []
        names = [t.get("name") for t in tools]
        record("I-MCP", "连接并发现工具", code == 200 and len(tools) >= 2,
               "200 且 >=2 个工具", f"{code} tools={names}")

        code, body = ta.get(f"/api/mcp/servers/{server_id}/tools")
        record("I-MCP", "工具清单缓存", code == 200 and len(dig(body, "tools", default=[]) or []) >= 2,
               "200 且缓存非空", f"{code} n={len(dig(body, 'tools', default=[]) or [])}")

        code, body = ta.get("/api/mcp/tool-calls")
        record("I-MCP", "调用审计接口", code == 200, "200", f"{code}")

    # --- J 组：严格模式 ---
    strict_env = dict(os.environ)
    strict_env.update({"CAMPUSCLAW_HOME": "D:/campus-claw/.verify/strictdata",
                       "CAMPUSCLAW_STRICT_CONFIG": "1", "PORT": "8098",
                       "PYTHONPATH": str(ROOT)})
    for key in ("SECRET_KEY", "SEED_TEACHER_A_PASSWORD", "SEED_STUDENT_A1_PASSWORD",
                "SEED_STUDENT_B1_PASSWORD", "SEED_TEACHER_B_PASSWORD"):
        strict_env.pop(key, None)
    proc = subprocess.Popen([str(PY), "app.py"], cwd=str(ROOT), env=strict_env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    try:
        out, _ = proc.communicate(timeout=25)
        exited = proc.returncode not in (None, 0)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        exited = False
    record("J-严格模式", "缺密钥时拒绝启动", exited, "非零退出", f"exit={proc.returncode}",
           detail=out[-300:] if out else "")

    # 汇总
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["verdict"] == "PASS")
    failed = total - passed
    print(f"\n=== 合计 {total} 项：PASS {passed} / FAIL {failed} ===")
    out_path = Path(__file__).with_name("e2e-result.json")
    out_path.write_text(json.dumps(
        {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "summary": {"total": total, "pass": passed, "fail": failed},
         "checks": RESULTS}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已写入", out_path)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
