"""追踪回查 · GET /api/audit/trace/<request_id>

第 10 课观测三支柱的第三根：指标说明「发生了多少」，审计说明「谁做了什么」，
追踪说明「这一次具体走了哪几步」。判据不是「日志里有 request_id」，而是
**拿一个 request_id 能把这次请求的路段按顺序取回来**。

判定四件事：

1. 能回查：真实请求的 request_id 能取回至少一段，且时间段与动作对得上。
2. 顺序正确：多段时按时间升序——顺序错了，链路就是假的。
3. 权限正确：明细带操作人与路径，学生不可读。
4. 空值不撒谎：查不到就 found=false，不许返回 200 加一个编造的段。
"""

from apitest.common import record

CASE = {
    "name": "追踪回查：能取回、顺序对、权限挡得住",
    "kind": "反例",
    "method": "GET",
    "path": "/api/audit/trace/<request_id>",
    "premise": "teacher_a 与 student_a1 已登录；已产生至少一次写请求",
}


def run(ctx):
    results = []

    # 先制造一段真实链路：写请求会落 api.request 链路段。
    status, payload = ctx.teacher.json(
        "POST", "/api/qa/questions",
        {"title": "追踪回查演示", "body": "用于验证 request_id 能把这次写请求取回来。"},
    )
    rid = (ctx.teacher.last_headers.get("X-Request-Id") or "").strip()
    results.append(record(
        name="写请求带出 request_id",
        premise="teacher_a 已登录",
        action="POST /api/qa/questions",
        expected="HTTP 201；响应头 X-Request-Id 非空",
        actual=f"HTTP {status}，X-Request-Id={rid or '（缺失）'}",
        ok=status == 201 and bool(rid),
        kind="正常",
    ))

    trace_status, trace = ctx.teacher.json("GET", f"/api/audit/trace/{rid}")
    steps = trace.get("steps") or []
    first = steps[0] if steps else {}
    results.append(record(
        name="按 request_id 取回本次请求",
        premise=f"request_id={rid}",
        action="GET /api/audit/trace/<request_id>",
        expected="HTTP 200；found=true；至少一段；首段动作是本次 POST，状态 201",
        actual=(
            f"HTTP {trace_status}，found={trace.get('found')}，{len(steps)} 段，"
            f"首段 {first.get('action')} {first.get('method')} {first.get('path')} "
            f"结果 {first.get('outcome')}"
        ),
        ok=(
            trace_status == 200
            and trace.get("found") is True
            and len(steps) >= 1
            and first.get("action") == "api.request"
            and first.get("method") == "POST"
            and first.get("path") == "/api/qa/questions"
            and str(first.get("status")) == "201"
        ),
        kind="正常",
    ))

    times = [s.get("at") or "" for s in steps]
    results.append(record(
        name="链路段按时间升序",
        premise="同上",
        action="检查 steps 的时间序列",
        expected="时间戳单调不减——顺序错了链路就不可读",
        actual=f"{len(times)} 段时间戳{'单调不减' if times == sorted(times) else '乱序'}",
        ok=times == sorted(times),
        kind="正常",
    ))

    status, payload = ctx.student.json("GET", f"/api/audit/trace/{rid}")
    code = payload.get("error", {}).get("code") if isinstance(payload.get("error"), dict) else None
    results.append(record(
        name="学生回查链路被拒",
        premise="student_a1 已登录（合法身份，走不该走的路）",
        action="GET /api/audit/trace/<request_id>",
        expected="HTTP 403 ROLE_FORBIDDEN，不返回任何链路段",
        actual=f"HTTP {status}，错误码 {code}，是否含 steps {'是' if 'steps' in payload else '否'}",
        ok=status == 403 and code == "ROLE_FORBIDDEN" and "steps" not in payload,
    ))

    status, payload = ctx.teacher.json("GET", "/api/audit/trace/req-does-not-exist")
    results.append(record(
        name="查不到的 request_id 如实返回空",
        premise="teacher_a 已登录",
        action="GET /api/audit/trace/req-does-not-exist",
        expected="HTTP 200；found=false；count=0；steps 为空数组",
        actual=(
            f"HTTP {status}，found={payload.get('found')}，"
            f"count={payload.get('count')}，steps={payload.get('steps')}"
        ),
        ok=(
            status == 200
            and payload.get("found") is False
            and payload.get("count") == 0
            and payload.get("steps") == []
        ),
        kind="正常",
    ))

    long_id = "r" * 65
    status, payload = ctx.teacher.json("GET", f"/api/audit/trace/{long_id}")
    code = payload.get("error", {}).get("code") if isinstance(payload.get("error"), dict) else None
    results.append(record(
        name="超长 request_id 被挡",
        premise="teacher_a 已登录",
        action="GET /api/audit/trace/<65 个字符>",
        expected="HTTP 400 INVALID_INPUT——外部输入不得撑坏日志字段",
        actual=f"HTTP {status}，错误码 {code}",
        ok=status == 400 and code == "INVALID_INPUT",
    ))

    return results
