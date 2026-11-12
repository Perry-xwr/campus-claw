"""页面访问控制 · GET /dashboard

第 10 课判据「运行观测」落地面板。教师能看，学生看不到——
面板上会露出操作人、请求路径这类运维信息，学生可见就是越权。

三层都要测：教师 200 且渲染出关键区块、学生被挡、未登录被挡。
只测教师 200 是不够的——授权判定缺失时，教师照样 200。
"""

from apitest.common import Client, record

CASE = {
    "name": "运行观测面板：教师可看，学生与匿名被挡",
    "kind": "反例",
    "method": "GET",
    "path": "/dashboard",
    "premise": "teacher_a 与 student_a1 均存在且可登录；面板已部署",
}


def run(ctx):
    results = []

    teacher = ctx.cookie_client("teacher_a")
    status, html = teacher.request("GET", "/dashboard")
    # 关键区块：标题、告警区、规则明细表。缺任何一个说明模板没真正渲染。
    markers = ["运行观测", "告警", "规则明细", "数据出口"]
    missing = [m for m in markers if m not in html]
    results.append(record(
        name="教师访问面板",
        premise="teacher_a 已用 Cookie 会话登录",
        action="GET /dashboard",
        expected="HTTP 200，页面含「运行观测 / 告警 / 规则明细 / 数据出口」",
        actual=f"HTTP {status}，缺失区块 {missing or '无'}",
        ok=status == 200 and not missing,
        kind="正常",
    ))

    student = ctx.cookie_client("student_a1")
    status, body = student.request("GET", "/dashboard", follow=False)
    location = student.last_headers.get("Location", "")
    results.append(record(
        name="学生访问面板被挡",
        premise="student_a1 已用 Cookie 会话登录（合法身份，走不该走的路）",
        action="GET /dashboard（不跟随重定向）",
        expected="HTTP 302 且重定向到教学材料页，不回面板内容",
        actual=f"HTTP {status}，Location={location or '（无）'}",
        ok=status == 302 and "/materials" in location,
    ))

    else_anon = Client(ctx.base_url)  # 全新客户端：无 Cookie、无令牌
    status, body = else_anon.request("GET", "/dashboard", follow=False)
    location = else_anon.last_headers.get("Location", "")
    results.append(record(
        name="未登录访问面板被挡",
        premise="全新客户端，既无 Cookie 会话也无 Bearer 令牌",
        action="GET /dashboard（不跟随重定向）",
        expected="HTTP 302 且重定向到登录页",
        actual=f"HTTP {status}，Location={location or '（无）'}",
        ok=status in (302, 401) and ("/login" in location or status == 401),
    ))

    return results
