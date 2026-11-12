"""XSS 反例 · POST /api/materials/upload

第 9 课要求：在讲义标题位置存入 `<img onerror=...>`，打开列表页后页面源码中
该内容已转义、无脚本执行。判定看两处——「没弹窗」只是表象，「源码已转义」才是判定。
"""

import re

from apitest.common import record

CASE = {
    "name": "XSS：讲义标题注入脚本",
    "kind": "反例",
    "method": "POST",
    "path": "/api/materials/upload",
    "premise": "teacher_a 已登录；列表页由服务端模板渲染（Jinja），标题直出到 HTML",
    "marker": "XSS_PROBE_9A",
}

MARKER = "XSS_PROBE_9A"
TITLE = f"<img src=x onerror=alert('{MARKER}')>"


def run(ctx):
    results = []

    status, payload = ctx.teacher.upload(
        "xss-probe.md",
        "# XSS 反例素材\n\n用于验证输出转义，正文不含脚本。\n".encode("utf-8"),
        title=TITLE,
    )
    material_id = payload.get("material_id")
    results.append(record(
        name="XSS 前置：注入内容成功入库",
        premise="teacher_a 已登录，可上传讲义",
        action=f'POST /api/materials/upload，title = {TITLE}',
        expected="HTTP 201，返回 material_id（内容入库才能验证输出位置）",
        actual=f"HTTP {status}，material_id={material_id}",
        ok=status == 201 and bool(material_id),
        kind="正常",
    ))

    login = ctx.cookie_login("teacher_a")
    page_status, html = ctx.teacher_cookie.page("/materials")
    escaped = "&lt;img" in html and MARKER in html
    raw_present = bool(re.search(r"<img\s+src=x\s+onerror=", html, re.I))

    results.append(record(
        name="XSS：列表页源码已转义",
        premise=f"Cookie 会话登录成功（HTTP {login}）；列表页 /materials 渲染全部讲义标题",
        action="打开 /materials，检查页面源码中该标题的出现形式",
        expected="标题以 &lt;img 形式出现，源码中不存在可执行的 <img src=x onerror=",
        actual=(f"HTTP {page_status}，页面 "
                f"{'含' if escaped else '不含'}转义形式 &lt;img，"
                f"{'存在' if raw_present else '不存在'}原始可执行标签"),
        ok=page_status == 200 and escaped and not raw_present,
    ))
    return results
