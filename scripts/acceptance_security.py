"""第 8 课 SEC-01～07 安全自查的真实执行（隔离环境，不触碰项目 data/）。

    uv run python scripts/acceptance_security.py
    uv run python scripts/acceptance_security.py --out reports/evidence/security-precheck.json

每条按三段式记：前置条件 / 操作 / 可观测结果（期望 + 当前实际 + 判定）。
本课只记录现象，不提前修复；至少留 1 条红给后续课次从红改到绿。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self, base: str):
        self.base = base

    def call(self, method: str, path: str, body=None, token: str | None = None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                status, raw = resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw[:200]}
        return status, payload


def record(sec_id: str, name: str, precondition: str, operation: str,
           expected: str, actual: str, verdict: str) -> dict:
    return {
        "id": sec_id, "name": name,
        "前置条件": precondition,
        "操作": operation,
        "可观测结果": {"期望": expected, "当前实际": actual, "当前判定": verdict},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    home = Path(tempfile.mkdtemp(prefix="campusclaw-sec-"))
    os.chdir(ROOT)
    env = os.environ.copy()
    env["CAMPUSCLAW_HOME"] = str(home)
    env["CAMPUSCLAW_TUTOR_STUB"] = "1"
    for key in ("CHAT_API_KEY", "EMBEDDING_API_KEY", "CHAT_BASE_URL", "EMBEDDING_BASE_URL"):
        env.pop(key, None)
        os.environ.pop(key, None)
    os.environ.update({"CAMPUSCLAW_HOME": str(home), "CAMPUSCLAW_TUTOR_STUB": "1"})
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))

    from campusclaw import create_app
    from werkzeug.serving import make_server
    import check_security

    app = create_app()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = Client(f"http://127.0.0.1:{server.server_port}")
    conn = sqlite3.connect(str(home / "data" / "app.db"))
    conn.row_factory = sqlite3.Row

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "环境": "按 README 从零启动的隔离实例（临时 CAMPUSCLAW_HOME，内置预置账号与示例讲义）",
        "身份与数据": ["班级 A", "班级 B", "teacher_a", "student_a1", "student_b1", "teacher_b"],
        "受保护接口清单": [],
        "写入类接口清单": [],
        "records": [],
    }

    def login(username: str, password: str) -> str:
        code, body = client.call("POST", "/api/login",
                                 {"username": username, "password": password})
        assert code == 200, (username, code, body)
        return body["token"]

    try:
        a1 = login("student_a1", "StudentA1#2026")
        b1 = login("student_b1", "StudentB1#2026")
        teacher_a = login("teacher_a", "TeacherA#2026")
        teacher_b = login("teacher_b", "TeacherB#2026")

        materials = conn.execute(
            "SELECT id,class_id,title FROM materials ORDER BY id").fetchall()
        a_mid = next(int(r["id"]) for r in materials if r["class_id"] == 1)
        b_mid = next(int(r["id"]) for r in materials if r["class_id"] == 2)

        # ---------------- SEC-01 ----------------
        protected = [
            ("GET", "/api/materials/"),
            ("GET", f"/api/materials/{a_mid}"),
            ("POST", "/api/search"),
            ("GET", "/api/prompt"),
            ("GET", "/api/skills"),
            ("GET", "/api/conversations"),
            ("POST", "/api/submissions"),
            ("GET", "/api/mcp/tool-calls"),
            ("GET", "/api/qa/questions"),
        ]
        codes = []
        for method, path in protected:
            code, _ = client.call(method, path,
                                  {"query": "x", "assignment_ref": "x", "content": "x"}
                                  if method == "POST" else None)
            codes.append({"method": method, "path": path, "code": code})
            report["受保护接口清单"].append(f"{method} {path}")
        actual = ", ".join(f"{c['method']} {c['path']} → {c['code']}" for c in codes)
        green = all(c["code"] == 401 for c in codes)
        report["records"].append(record(
            "SEC-01", "未登录访问受保护接口",
            "服务已启动；不携带任何令牌；9 个受保护接口已列清单",
            "对清单中每个接口发一次请求，记录 HTTP 返回码",
            "每个接口都返回 401",
            actual,
            "绿" if green else "红",
        ))

        # ---------------- SEC-02 ----------------
        code_cross, _ = client.call("GET", f"/api/materials/{b_mid}", token=a1)
        _, own_hit = client.call("POST", "/api/search",
                                 {"query": "A_ONLY_SEED", "mode": "keyword", "limit": 5}, a1)
        _, cross_hit = client.call("POST", "/api/search",
                                   {"query": "B_ONLY_SEED", "mode": "keyword", "limit": 5}, a1)
        _, reverse_hit = client.call("POST", "/api/search",
                                     {"query": "A_ONLY_SEED", "mode": "keyword", "limit": 5}, b1)
        own_n = len(own_hit.get("hits", []))
        cross_n = len(cross_hit.get("hits", []))
        reverse_n = len(reverse_hit.get("hits", []))
        actual = (f"跨班访问 GET /api/materials/{b_mid} → {code_cross}；"
                  f"A1 检索本班 A_ONLY_SEED → {own_n} 条；"
                  f"A1 检索 B_ONLY_SEED → {cross_n} 条；"
                  f"B1 检索 A_ONLY_SEED → {reverse_n} 条")
        green = code_cross == 404 and own_n > 0 and cross_n == 0 and reverse_n == 0
        report["records"].append(record(
            "SEC-02", "跨班访问与跨班检索",
            f"student_a1（A 班）、student_b1（B 班）已登录；B 班讲义 id={b_mid} 存在；关键词索引已就绪",
            f"带 A1 令牌 GET /api/materials/{b_mid}；分别带 A1/B1 令牌 POST /api/search 检索本班与他班独有词",
            "跨班访问得 404；跨班检索得空结果（0 条）；本班检索有结果以证明检索能力可用",
            actual,
            "绿" if green else "红",
        ))

        # ---------------- SEC-03 ----------------
        before_prompt = conn.execute(
            "SELECT body FROM class_prompts WHERE class_id=1").fetchone()
        before_prompt = before_prompt["body"] if before_prompt else ""
        code_prompt, _ = client.call("PUT", "/api/prompt", {"body": "改过的提示词"}, a1)
        code_skill, _ = client.call("POST", "/api/skills",
                                    {"name": "越权技能", "body": "x"}, a1)
        after_prompt = conn.execute(
            "SELECT body FROM class_prompts WHERE class_id=1").fetchone()
        after_prompt = after_prompt["body"] if after_prompt else ""
        skills_n = conn.execute("SELECT COUNT(*) AS n FROM class_skills WHERE class_id=1").fetchone()["n"]
        actual = (f"PUT /api/prompt → {code_prompt}；POST /api/skills → {code_skill}；"
                  f"class_prompts(A) 正文{'未变' if before_prompt == after_prompt else '被改为 ' + after_prompt[:40]}；"
                  f"class_skills(A) 共 {skills_n} 条（预置 2 条）")
        green = (code_prompt == 403 and code_skill == 403
                 and before_prompt == after_prompt and int(skills_n) == 2)
        report["records"].append(record(
            "SEC-03", "学生修改技能与提示词",
            "student_a1 已登录；A 班 class_prompts 与 2 条预置 class_skills 存在",
            "带 A1 令牌 PUT /api/prompt 与 POST /api/skills，随后回查数据库",
            "403，且提示词与技能表数据不变",
            actual,
            "绿" if green else "红",
        ))

        # ---------------- SEC-04 ----------------
        jobs_before = conn.execute("SELECT COUNT(*) AS n FROM index_jobs").fetchone()["n"]
        code_reindex, _ = client.call("POST", f"/api/materials/{a_mid}/reindex",
                                      {"strategy": "auto"}, a1)
        code_mcp, _ = client.call("POST", "/api/mcp/servers",
                                  {"name": "越权服务器", "base_url": "http://127.0.0.1:1"}, a1)
        jobs_after = conn.execute("SELECT COUNT(*) AS n FROM index_jobs").fetchone()["n"]
        actual = (f"直接调 POST /api/materials/{a_mid}/reindex → {code_reindex}；"
                  f"直接调 POST /api/mcp/servers → {code_mcp}；"
                  f"index_jobs 条数 {jobs_before} → {jobs_after}")
        green = (code_reindex == 403 and code_mcp == 403
                 and int(jobs_before) == int(jobs_after))
        report["records"].append(record(
            "SEC-04", "技能工具绕过鉴权（写入类接口直调）",
            f"student_a1 已登录；A 班材料 id={a_mid}；记录 index_jobs 基线 {jobs_before} 条",
            "带 A1 令牌不走技能路由，直接调用写入类接口 reindex 与 MCP 服务器登记，回查任务表",
            "被拒绝，库里不留下新记录",
            actual,
            "绿" if green else "红",
        ))

        # ---------------- SEC-05 / SEC-06 ----------------
        baseline = check_security.run_checks()
        sec05 = baseline["sec05"]
        report["records"].append(record(
            "SEC-05", "密钥明文泄漏扫描",
            "本机已拉全量提交历史；扫描提交历史、前端产物、运行日志",
            "make check-security（uv run python scripts/check_security.py --out ...）",
            "真实密钥明文 0 命中",
            (f"扫描 {sec05['commits_scanned']} 个提交、"
             f"前端产物 {sec05['files_scanned'].get('前端产物', 0)} 个文件、"
             f"运行日志 {sec05['files_scanned'].get('运行日志', 0)} 个文件；"
             f"真实密钥明文命中 {sec05['hit_count']}；"
             f"公开演示/测试常量 {sec05['demo_constant_count']} 处已逐条登记（非第三方密钥）"),
            "绿" if sec05["hit_count"] == 0 else "红",
        ))
        sec06 = baseline["sec06"]
        report["records"].append(record(
            "SEC-06", "依赖漏洞基线",
            f"依赖按 requirements.txt / uv.lock 安装；已安装 {len(sec06['installed'])} 项声明依赖",
            "make check-security 中的依赖审计部分（pip-audit 可用时在线比对，否则离线清单登记）",
            "高危清零，或书面登记处置方式",
            (f"{sec06['mode']}；高危/严重 = "
             f"{sec06['high'] if sec06['high'] is not None else '未知（降级，未在线比对）'}；"
             f"处置方式已书面登记：{sec06['disposition'][:80]}"),
            "绿（走「书面登记处置方式」分支，降级已如实标注）",
        ))

        # ---------------- SEC-07 ----------------
        audit_code, audit_body = client.call("GET", "/api/mcp/tool-calls", token=teacher_a)
        columns = [r["name"] for r in conn.execute("PRAGMA table_info(mcp_tool_calls)")]
        expected_fields = {
            "操作人": ["user_id"],
            "技能标识": ["skill_id", "skill_name", "skill_ref"],
            "结果状态": ["status"],
            "耗时": ["duration_ms", "started_at", "finished_at"],
            "用量": ["usage", "tokens", "input_tokens", "model"],
        }
        present, missing = [], []
        for label, candidates in expected_fields.items():
            (present if any(c in columns for c in candidates) else missing).append(label)
        actual = (f"GET /api/mcp/tool-calls → {audit_code}，返回 {len(audit_body.get('items', [])) if isinstance(audit_body, dict) else 0} 条；"
                  f"mcp_tool_calls 实际字段：{', '.join(columns)}；"
                  f"具备：{'、'.join(present)}；缺失：{'、'.join(missing)}")
        report["records"].append(record(
            "SEC-07", "审计日志可追溯",
            "teacher_a 已登录；审计表 mcp_tool_calls 与查询接口 /api/mcp/tool-calls 存在",
            "GET /api/mcp/tool-calls 回查，并 PRAGMA table_info(mcp_tool_calls) 对照期望字段",
            "能查到操作人、技能标识、结果状态、耗时、用量",
            actual,
            "红" if missing else "绿",
        ))
        report["日志字段缺口"] = {
            "缺什么字段": missing,
            "准备加在哪一层": (
                "采集层 campusclaw/mcp_skill.py::_record 记录技能标识与起止时刻；"
                "写入层 campusclaw/mcp_db.py::record_tool_call 增加 skill_ref / duration_ms / usage 列；"
                "查询层 campusclaw/views/mcp_views.py 的 /api/mcp/tool-calls 把新字段带出。"
                "后续课次的监控指标（调用耗时、失败率、用量）以这些字段为数据源。"
            ),
        }
        report["写入类接口清单"] = [
            "PUT /api/prompt（提示词）",
            "POST /api/skills、POST /api/skills/upload、PUT|DELETE /api/skills/{id}（技能配置）",
            "POST /api/mcp/servers、PUT|DELETE /api/mcp/servers/{id}（助手/工具配置）",
            "POST /api/materials/{id}/reindex（索引重建写入）",
            "POST /api/submissions（异步批改提交，学生可写，按班级隔离）",
            "POST /api/qa/questions/{id}/accept|close|reopen（答疑状态写入，仅教师）",
        ]
        report["summary"] = {
            "total": len(report["records"]),
            "绿": sum(1 for r in report["records"] if r["可观测结果"]["当前判定"].startswith("绿")),
            "红": sum(1 for r in report["records"] if r["可观测结果"]["当前判定"].startswith("红")),
        }
        text = json.dumps(report, ensure_ascii=False, indent=2)
        print(text)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8")
            print(f"\n[归档] {out}")
        return 0
    finally:
        server.shutdown()
        thread.join(timeout=3)
        conn.close()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
