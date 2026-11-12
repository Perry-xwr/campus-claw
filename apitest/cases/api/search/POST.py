"""SQL 注入反例 · POST /api/search

第 9 课要求：在检索词位置提交 `' OR '1'='1`，期望正常返回空结果或报格式错误，
而不是因为条件恒成立返回全表数据。判定依据是「注入进去，系统不接」。
"""

from apitest.common import record

CASE = {
    "name": "SQL 注入：检索词提交恒真条件",
    "kind": "反例",
    "method": "POST",
    "path": "/api/search",
    "premise": "teacher_a 已登录；班级 A 有已建关键词索引的种子讲义；检索能力本身可用",
}

PAYLOAD = "' OR '1'='1"
BASELINE_TERM = "A_ONLY_SEED"


def run(ctx):
    results = []

    # 前置：先证明检索能力可用，避免「命中 0 条」是因为功能本身不可用而误判为绿。
    status, payload = ctx.teacher.json(
        "POST", "/api/search", {"query": BASELINE_TERM, "mode": "keyword", "limit": 10})
    baseline_hits = payload.get("hits") or []
    results.append(record(
        name="前置：本班正常词可检索",
        premise="teacher_a 已登录；关键词索引就绪",
        action=f'POST /api/search {{"query": "{BASELINE_TERM}", "mode": "keyword"}}',
        expected="HTTP 200 且命中至少 1 条",
        actual=f"HTTP {status}，命中 {len(baseline_hits)} 条",
        ok=status == 200 and len(baseline_hits) >= 1,
        kind="正常",
    ))

    status, payload = ctx.teacher.json(
        "POST", "/api/search", {"query": PAYLOAD, "mode": "keyword", "limit": 50})
    hits = payload.get("hits") or []
    code = payload.get("error", {}).get("code") if isinstance(payload.get("error"), dict) else None

    # 绿：明确拒绝（4xx）或正常返回但 0 命中（输入被当成纯文本）。
    # 红：命中数大于 0，尤其命中数达到或超过正常词，说明条件恒成立、返回了不该返回的行。
    if status == 200:
        ok = len(hits) == 0
        actual = f"HTTP 200，命中 {len(hits)} 条（全库可见度基线为 {len(baseline_hits)} 条）"
    elif 400 <= status < 500:
        ok = True
        actual = f"HTTP {status}，错误码 {code}，请求被拒"
    else:
        ok = False
        actual = f"HTTP {status}，非预期响应"

    results.append(record(
        name="SQL 注入：检索词提交恒真条件",
        premise="teacher_a 已登录；检索词字段为唯一注入点",
        action=f'POST /api/search {{"query": "{PAYLOAD}", "mode": "keyword", "limit": 50}}',
        expected="HTTP 200 且 0 命中，或 HTTP 4xx 格式错误；不得返回全表数据",
        actual=actual,
        ok=ok,
    ))
    return results
