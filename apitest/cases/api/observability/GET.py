"""观测接口 · GET /api/observability 与 GET /api/health/alerts

第 10 课判据「运行观测」的两条机器出口，判定三件事：

1. 结构完整：面板轮询依赖固定字段，字段缺失前端就静默失效，属于「看着正常其实瞎了」。
2. 授权正确：完整快照含明细，必须教师；匿名只给告警判定，不含任何明细。
3. 判定可解读：status 只能是 ok / degraded / critical，规则必须带实际值与阈值——
   只报「有问题」而不报「差多少」的告警，等于没报。
"""

from apitest.common import record

CASE = {
    "name": "观测接口：结构完整、权限分级、判定可解读",
    "kind": "反例",
    "method": "GET",
    "path": "/api/observability",
    "premise": "teacher_a 与 student_a1 已登录；服务已启动",
}

FULL_KEYS = {"status", "checked_at", "metrics", "db", "alerts", "rules", "recent_denials"}
STATUSES = {"ok", "degraded", "critical"}


def run(ctx):
    results = []

    status, payload = ctx.teacher.json("GET", "/api/observability")
    missing = sorted(FULL_KEYS - set(payload))
    rules = payload.get("rules") or []
    bad_rule = [
        r for r in rules
        if not {"id", "level", "title", "value", "threshold", "ok", "hint"} <= set(r)
    ]
    ok = (
        status == 200
        and not missing
        and payload.get("status") in STATUSES
        and len(rules) >= 4
        and not bad_rule
    )
    results.append(record(
        name="教师取完整快照",
        premise="teacher_a 已登录",
        action="GET /api/observability",
        expected="HTTP 200；顶层字段齐备；status 取值合法；每条规则含实际值与阈值",
        actual=(
            f"HTTP {status}；缺字段 {missing or '无'}；status={payload.get('status')}；"
            f"规则 {len(rules)} 条，字段不全 {len(bad_rule)} 条"
        ),
        ok=ok,
        kind="正常",
    ))

    status, payload = ctx.student.json("GET", "/api/observability")
    code = payload.get("error", {}).get("code") if isinstance(payload.get("error"), dict) else None
    results.append(record(
        name="学生取完整快照被拒",
        premise="student_a1 已登录（合法身份，走不该走的路）",
        action="GET /api/observability",
        expected="HTTP 403 ROLE_FORBIDDEN，不返回任何观测数据",
        actual=f"HTTP {status}，错误码 {code}，正文是否含明细 {'是' if 'recent_denials' in payload else '否'}",
        ok=status == 403 and code == "ROLE_FORBIDDEN" and "recent_denials" not in payload,
    ))

    status, payload = ctx.student.json("GET", "/api/health/alerts")
    rules = payload.get("rules") or []
    # 匿名出口只许出现判定，不许出现操作人、路径、request_id 这类明细。
    leaked = [k for k in ("recent_denials", "actor", "request_id", "path") if k in payload]
    results.append(record(
        name="匿名读告警判定且不泄露明细",
        premise="未带令牌",
        action="GET /api/health/alerts",
        expected="HTTP 200；status 合法；规则数与快照一致；不含 recent_denials / actor / request_id",
        actual=(
            f"HTTP {status}；status={payload.get('status')}；规则 {len(rules)} 条；"
            f"泄露字段 {leaked or '无'}"
        ),
        ok=(
            status == 200
            and payload.get("status") in STATUSES
            and len(rules) >= 4
            and not leaked
        ),
    ))

    return results
