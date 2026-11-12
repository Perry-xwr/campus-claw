# -*- coding: utf-8 -*-
"""CampusClaw 验收测试

覆盖三层：
  A/B/C —— 正常路径 / 失败路径 / 越权路径
  S1~S5 —— 选题报告「五、实施计划与验收标准」中的五个关键验收样例
  D     —— 数据库一致性（服务端返回与库内事实对齐）

运行前置：隔离数据目录 .acc/appdata，不触碰项目 data/。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

def _project_root(start: Path) -> Path:
    """向上找到含 app.py 与 campusclaw/ 的项目根。

    脚本归档到 reports/verification/scripts/ 之后，不能再用固定层级推算，
    否则工作目录与解释器路径都会指错。
    """
    for candidate in [start, *start.parents]:
        if (candidate / "app.py").exists() and (candidate / "campusclaw").is_dir():
            return candidate
    return start


ROOT = _project_root(Path(__file__).resolve().parent)
WORK = ROOT / ".acc"
HOME = WORK / "appdata"
PORT = 8098
BASE = f"http://127.0.0.1:{PORT}"
PY = Path(sys.executable)  # 用当前解释器：venv 位置因机器而异，不能硬拼
DB_PATH = HOME / "data" / "app.db"

for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
            "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
    os.environ.pop(key, None)

ENV = {**os.environ, "CAMPUSCLAW_HOME": str(HOME), "PORT": str(PORT),
       "MCP_AUTH_TOKEN": "acc-token-2026"}

checks: list[dict] = []
PROC: subprocess.Popen | None = None


# --------------------------------------------------------------------------- 记录

def rec(group: str, name: str, kind: str, expected: str, actual: str, ok: bool,
        evidence: str = "") -> bool:
    checks.append({"group": group, "name": name, "kind": kind, "expected": expected,
                   "actual": actual, "verdict": "PASS" if ok else "FAIL",
                   "evidence": evidence})
    print(f"{'PASS' if ok else 'FAIL'} | {group} | {name} | 期望 {expected} | 实际 {actual}")
    return ok


# --------------------------------------------------------------------------- 进程

def start_app() -> None:
    global PROC
    WORK.mkdir(parents=True, exist_ok=True)
    log = open(WORK / "app.log", "a", encoding="utf-8")
    PROC = subprocess.Popen([str(PY), "app.py"], cwd=str(ROOT), env=ENV,
                            stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise RuntimeError("应用未在 120s 内就绪，见 .acc/app.log")


def stop_app() -> None:
    global PROC
    if PROC is not None and PROC.poll() is None:
        PROC.terminate()
        try:
            PROC.wait(20)
        except subprocess.TimeoutExpired:
            PROC.kill()
            PROC.wait(10)
    PROC = None


def run_worker() -> tuple[int, str]:
    """零模型环境下跑一次索引 worker（不配置 EMBEDDING_*）。"""
    out = subprocess.run([str(PY), "-m", "campusclaw.index_worker", "--once"],
                         cwd=str(ROOT), env=ENV, capture_output=True, text=True,
                         timeout=180)
    return out.returncode, (out.stdout or "") + (out.stderr or "")


# --------------------------------------------------------------------------- HTTP

class Client:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def call(self, method: str, path: str, body=None, timeout: int = 90):
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw, code = resp.read().decode("utf-8", "replace"), resp.status
        except urllib.error.HTTPError as exc:
            raw, code = exc.read().decode("utf-8", "replace"), exc.code
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            payload = {"raw": raw[:400]}
        return code, payload


def err_code(payload) -> str:
    if not isinstance(payload, dict):
        return "-"
    err = payload.get("error")
    if isinstance(err, dict):
        return str(err.get("code") or "-")
    return str(payload.get("code") or "-")


def login(username: str, password: str) -> Client:
    code, payload = Client().call("POST", "/api/login",
                                  {"username": username, "password": password})
    if code != 200:
        raise RuntimeError(f"登录失败 {username}: {code} {payload}")
    return Client(payload["token"])


# --------------------------------------------------------------------------- DB

def q(sql: str, args=()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


# --------------------------------------------------------------------------- 主流程

def main() -> int:
    shutil.rmtree(HOME, ignore_errors=True)
    (WORK / "app.log").unlink(missing_ok=True)
    start_app()

    ta = login("teacher_a", "TeacherA#2026")
    sa = login("student_a1", "StudentA1#2026")
    tb = login("teacher_b", "TeacherB#2026")
    sb = login("student_b1", "StudentB1#2026")

    # ================================================================= A 正常路径
    code, q1 = sa.call("POST", "/api/qa/questions",
                       {"title": "分层切片索引策略为什么不生效",
                        "body": "我在本班材料里找不到对应段落，想确认索引链路。"})
    q1_id = q1.get("id")
    rec("A-正常", "A 班学生发帖", "正常", "201 且返回问题 id",
        f"{code} id={q1_id}", code == 201 and bool(q1_id))

    code, listing = sa.call("GET", "/api/qa/questions")
    titles = [item.get("title") for item in (listing.get("items") or [])]
    rec("A-正常", "发帖后出现在本班列表", "正常", "200 且列表含该帖",
        f"{code} 共 {len(titles)} 条，命中={'是' if q1.get('title') in titles else '否'}",
        code == 200 and q1.get("title") in titles)

    # ================================================================= B 失败路径
    code, empty_title = sa.call("POST", "/api/qa/questions", {"title": "   ", "body": "正文"})
    rec("B-失败", "空标题被拒", "失败", "400 QA_TITLE_INVALID",
        f"{code} {err_code(empty_title)}",
        code == 400 and err_code(empty_title) == "QA_TITLE_INVALID")

    code, empty_body = sa.call("POST", "/api/qa/questions",
                               {"title": "有标题", "body": ""})
    rec("B-失败", "空正文被拒", "失败", "400 QA_BODY_INVALID",
        f"{code} {err_code(empty_body)}",
        code == 400 and err_code(empty_body) == "QA_BODY_INVALID")

    code, missing = sa.call("GET", "/api/qa/questions/999999")
    rec("B-失败", "读取不存在的问题", "失败", "404 NOT_FOUND",
        f"{code} {err_code(missing)}", code == 404)

    code, bad_reply = ta.call("POST", f"/api/qa/questions/{q1_id}/accept",
                              {"reply_id": 999999})
    rec("B-失败", "采纳不属于该问题的回复", "失败", "400 QA_REPLY_NOT_IN_QUESTION",
        f"{code} {err_code(bad_reply)}",
        code == 400 and err_code(bad_reply) == "QA_REPLY_NOT_IN_QUESTION")

    code, bad_page = sa.call("GET", "/api/qa/questions?page=0")
    rec("B-失败", "非法分页参数", "失败", "400 QA_PAGE_INVALID",
        f"{code} {err_code(bad_page)}",
        code == 400 and err_code(bad_page) == "QA_PAGE_INVALID")

    # ================================================================= C 越权路径
    code, _ = sa.call("POST", f"/api/qa/questions/{q1_id}/accept", {"reply_id": 1})
    rec("C-越权", "学生采纳回复", "越权", "403 ROLE_FORBIDDEN", f"{code}", code == 403)

    code, _ = sa.call("POST", f"/api/qa/questions/{q1_id}/close")
    rec("C-越权", "学生关闭问题", "越权", "403 ROLE_FORBIDDEN", f"{code}", code == 403)

    code, denied_faq = sa.call("POST", "/api/qa/faqs",
                               {"question_id": q1_id, "question_text": "问", "answer_text": "答"})
    rec("C-越权", "学生发布 FAQ", "越权", "403 ROLE_FORBIDDEN",
        f"{code} {err_code(denied_faq)}", code == 403)

    code, _ = sa.call("GET", "/api/qa/stats")
    rec("C-越权", "学生查看教师统计", "越权", "403 ROLE_FORBIDDEN", f"{code}", code == 403)

    # ================================================================= S1 班级可见性
    code, cross_tb = tb.call("GET", f"/api/qa/questions/{q1_id}")
    rec("S1-仅本班可见", "B 班教师读 A 班帖子", "越权",
        "404（跨班与不存在同码）", f"{code} {err_code(cross_tb)}", code == 404)

    code, cross_sb = sb.call("GET", f"/api/qa/questions/{q1_id}")
    rec("S1-仅本班可见", "B 班学生读 A 班帖子", "越权", "404", f"{code}", code == 404)

    code, b_list = tb.call("GET", "/api/qa/questions")
    b_titles = [item.get("title") for item in (b_list.get("items") or [])]
    rec("S1-仅本班可见", "B 班列表不含 A 班帖子", "正常", "200 且列表为空",
        f"{code} B 班共 {len(b_titles)} 条", code == 200 and q1.get("title") not in b_titles)

    code, cross_reply = sb.call("POST", f"/api/qa/questions/{q1_id}/replies",
                                {"body": "跨班回复尝试"})
    rec("S1-仅本班可见", "B 班学生回复 A 班帖子", "越权", "404", f"{code}", code == 404)

    # ================================================================= S2 回复与采纳权限
    code, teacher_reply = ta.call("POST", f"/api/qa/questions/{q1_id}/replies",
                                  {"body": "教师回复：答案正文含关键字 分层切片索引策略 ，"
                                           "索引需要 worker 处理后再检索。"})
    rec("S2-回复与采纳", "教师回复学生帖子", "正常", "201",
        f"{code} reply_id={teacher_reply.get('id')}", code == 201)

    code, detail = sa.call("GET", f"/api/qa/questions/{q1_id}")
    status_after = (detail.get("question") or {}).get("status")
    rec("S2-回复与采纳", "回复后状态转 ANSWERED", "正常", "ANSWERED",
        f"{code} status={status_after}",
        code == 200 and status_after == "ANSWERED")

    # 学生对教师发帖回复，验证「同学与教师都可回复」
    code, tq = ta.call("POST", "/api/qa/questions",
                       {"title": "教师公告帖：本周答疑安排", "body": "有问题请在此回复。"})
    tq_id = tq.get("id")
    code, stu_reply = sa.call("POST", f"/api/qa/questions/{tq_id}/replies",
                              {"body": "同学回复：收到。"})
    rec("S2-回复与采纳", "学生回复教师帖子", "正常", "201",
        f"{code} reply_id={stu_reply.get('id')}", code == 201)

    code, non_teacher_accept = sa.call("POST", f"/api/qa/questions/{q1_id}/accept",
                                       {"reply_id": teacher_reply.get("id")})
    rec("S2-回复与采纳", "学生不能伪造教师采纳", "越权", "403",
        f"{code} {err_code(non_teacher_accept)}", code == 403)

    code, accepted = ta.call("POST", f"/api/qa/questions/{q1_id}/accept",
                             {"reply_id": teacher_reply.get("id")})
    question = accepted.get("question") if "question" in accepted else accepted
    acc_reply = question.get("accepted_reply_id")
    acc_status = question.get("status")
    rec("S2-回复与采纳", "教师采纳后状态 ACCEPTED", "正常",
        "200 且 accepted_reply_id 指向该回复",
        f"{code} status={acc_status} accepted_reply_id={acc_reply}",
        code == 200 and acc_status == "ACCEPTED" and acc_reply == teacher_reply.get("id"))

    # ================================================================= S3 FAQ 发布 + 检索命中
    faq_marker = "分层切片索引策略"
    code, faq = ta.call("POST", "/api/qa/faqs",
                        {"question_id": q1_id,
                         "question_text": "索引链路为什么不生效？",
                         "answer_text": f"本次答疑确认：{faq_marker}需要在 worker 完成后生效。"})
    faq_id = faq.get("id")
    rec("S3-FAQ可检索", "教师发布 FAQ", "正常", "201 且返回 FAQ",
        f"{code} faq_id={faq_id}", code == 201 and bool(faq_id))

    faq_material = q("SELECT material_id FROM qa_faq_materials WHERE class_id = 1")
    rec("S3-FAQ可检索", "FAQ 沉淀为真实材料", "正常", "生成 1 份 FAQ 汇总材料",
        f"material_id={[r['material_id'] for r in faq_material]}",
        len(faq_material) == 1)

    # 零模型：靠启动补建关键词索引（不跑 worker 的路径）
    stop_app()
    start_app()
    faq_material_id = faq_material[0]["material_id"] if faq_material else None

    code, hits = sa.call("POST", "/api/search",
                         {"query": faq_marker, "mode": "keyword", "limit": 5})
    items = hits.get("hits") or hits.get("items") or []
    hit_material = [h.get("material_id") for h in items]
    hit_title = [h.get("title") for h in items]
    rec("S3-FAQ可检索", "本班检索命中 FAQ 内容", "正常",
        "200 且命中 FAQ 汇总材料",
        f"{code} 命中 {len(items)} 条 material={hit_material} title={hit_title}",
        code == 200 and faq_material_id in hit_material)

    has_source = bool(items) and all(
        h.get("material_id") and (h.get("snippet") or h.get("text") or h.get("chunk_id"))
        for h in items)
    rec("S3-FAQ可检索", "命中结果带材料来源可追溯", "正常",
        "每条命中含 material_id 与切片定位",
        f"字段={sorted(items[0].keys()) if items else '无命中'}",
        has_source)

    # ================================================================= S4 重复发布不重复入库
    code, dup = ta.call("POST", "/api/qa/faqs",
                        {"question_id": q1_id, "question_text": "重复发布",
                         "answer_text": "重复发布"})
    rec("S4-去重", "同一问题重复发布 FAQ", "失败", "409 QA_FAQ_EXISTS",
        f"{code} {err_code(dup)}",
        code == 409 and err_code(dup) == "QA_FAQ_EXISTS")

    mat_count = len(q("SELECT id FROM materials WHERE title = '本班 FAQ 汇总（自动生成）' "
                      "AND status = 'active'"))
    entry_count = len(q("SELECT material_id FROM knowledge_entries WHERE material_id = ?",
                        (faq_material_id,)))
    rec("S4-去重", "重复发布不产生重复知识条目", "正常",
        "活跃 FAQ 材料 1 份、知识正文 1 条",
        f"材料 {mat_count} 份、知识条目 {entry_count} 条",
        mat_count == 1 and entry_count == 1)

    code, updated = ta.call("PUT", f"/api/qa/faqs/{faq_id}",
                            {"question_text": "索引链路为什么不生效？",
                             "answer_text": f"本次答疑确认：{faq_marker}需在 worker 完成后生效（已修订）。"})
    after_mat = q("SELECT material_id FROM qa_faq_materials WHERE class_id = 1")
    rec("S4-去重", "编辑 FAQ 不新建材料", "正常",
        "200 且 faq_material_id 不变",
        f"{code} material_id={[r['material_id'] for r in after_mat]}",
        code == 200 and after_mat[0]["material_id"] == faq_material_id)
    entry_after = len(q("SELECT material_id FROM knowledge_entries WHERE material_id = ?",
                        (faq_material_id,)))
    rec("S4-去重", "编辑 FAQ 不新增知识条目", "正常", "knowledge_entries 仍为 1 条",
        f"{entry_after} 条", entry_after == 1)

    # ================================================================= S5 索引失败与重建
    code, q2 = sa.call("POST", "/api/qa/questions",
                       {"title": "worker 失败后 FAQ 还能检索吗",
                        "body": "验证索引失败路径。"})
    q2_id = q2.get("id")
    code, r2 = ta.call("POST", f"/api/qa/questions/{q2_id}/replies",
                       {"body": "教师回复：这是第二条 FAQ 的答案正文。"})
    ta.call("POST", f"/api/qa/questions/{q2_id}/accept", {"reply_id": r2.get("id")})
    second_marker = "第二条FAQ答案正文"
    code, faq2 = ta.call("POST", "/api/qa/faqs",
                         {"question_id": q2_id,
                          "question_text": "worker 失败后 FAQ 还能检索吗？",
                          "answer_text": f"这是{second_marker}，用于验证索引失败与重建。"})
    rec("S5-失败可重建", "发布第二条 FAQ（触发重建任务）", "正常", "201",
        f"{code} faq_id={faq2.get('id')}", code == 201)

    pending = q("SELECT material_id, status, COUNT(*) AS n FROM index_jobs "
                "GROUP BY material_id, status")
    rec("S5-失败可重建", "FAQ 变更后入队索引任务", "正常", "FAQ 汇总材料存在待处理任务",
        f"任务分布={[dict(r) for r in pending]}", bool(pending))

    rc, worker_out = run_worker()
    failed_idx = q("SELECT material_id, status, last_error FROM material_index "
                   "WHERE material_id = ?", (faq_material_id,))
    idx_status = failed_idx[0]["status"] if failed_idx else "-"
    rec("S5-失败可重建", "零模型下 worker 记录失败状态", "失败",
        "material_index.status = failed 且 last_error 有值",
        f"exit={rc} status={idx_status} err={(failed_idx[0]['last_error'] or '')[:60] if failed_idx else ''}",
        idx_status == "failed")

    keep_mat = q("SELECT id, status, size_bytes FROM materials WHERE id = ?", (faq_material_id,))
    keep_entry = q("SELECT length(body_text) AS n FROM knowledge_entries WHERE material_id = ?",
                   (faq_material_id,))
    body_len = keep_entry[0]["n"] if keep_entry else 0
    rec("S5-失败可重建", "索引失败保留材料与正文", "正常",
        "材料仍 active、知识正文非空",
        f"材料 status={keep_mat[0]['status'] if keep_mat else '-'}、正文 {body_len} 字符",
        bool(keep_mat) and keep_mat[0]["status"] == "active" and body_len > 0)

    code, miss = sa.call("POST", "/api/search",
                         {"query": second_marker, "mode": "keyword", "limit": 5})
    miss_items = miss.get("hits") or miss.get("items") or []
    rec("S5-失败可重建", "未索引内容不谎称可检索", "正常",
        "检索不命中（如实反映未就绪）",
        f"{code} 命中 {len(miss_items)} 条", code == 200 and not miss_items)

    code, old_hits = sa.call("POST", "/api/search",
                             {"query": faq_marker, "mode": "keyword", "limit": 5})
    old_items = old_hits.get("hits") or old_hits.get("items") or []
    rec("S5-失败可重建", "一次失败不影响既有 FAQ 检索", "正常",
        "第一条 FAQ 仍可命中",
        f"{code} 命中 {len(old_items)} 条",
        code == 200 and bool(old_items))

    # 恢复路径：重启触发启动补建
    stop_app()
    start_app()
    recovered = q("SELECT status, active_generation, last_error FROM material_index "
                  "WHERE material_id = ?", (faq_material_id,))
    rec_status = recovered[0]["status"] if recovered else "-"
    rec("S5-失败可重建", "重启后自动重建索引（恢复路径）", "正常",
        "status 回到 ready 且内容可检索",
        f"status={rec_status} gen={recovered[0]['active_generation'] if recovered else '-'}",
        rec_status == "ready")

    code, re_hits = sa.call("POST", "/api/search",
                            {"query": second_marker, "mode": "keyword", "limit": 5})
    re_items = re_hits.get("hits") or re_hits.get("items") or []
    rec("S5-失败可重建", "恢复后第二条 FAQ 可检索", "正常", "命中 1 条以上",
        f"{code} 命中 {len(re_items)} 条", bool(re_items))

    # ================================================================= D 数据一致性
    orphan_reply = q("SELECT r.id FROM qa_replies r "
                     "LEFT JOIN qa_questions q ON q.id = r.question_id WHERE q.id IS NULL")
    rec("D-数据一致性", "回复无孤儿记录", "数据", "0 条孤儿回复",
        f"{len(orphan_reply)} 条", not orphan_reply)

    bad_accept = q("SELECT q.id FROM qa_questions q JOIN qa_replies r "
                   "ON r.id = q.accepted_reply_id WHERE r.question_id <> q.id")
    rec("D-数据一致性", "采纳关系指向本问题的回复", "数据", "0 条错配",
        f"{len(bad_accept)} 条", not bad_accept)

    bad_status = q("SELECT id FROM qa_questions "
                   "WHERE status = 'ACCEPTED' AND accepted_reply_id IS NULL")
    rec("D-数据一致性", "ACCEPTED 必有采纳记录", "数据", "0 条矛盾",
        f"{len(bad_status)} 条", not bad_status)

    class_mismatch = q("SELECT k.material_id FROM knowledge_entries k "
                       "JOIN materials m ON m.id = k.material_id "
                       "WHERE k.class_id <> m.class_id")
    rec("D-数据一致性", "知识正文与材料班级一致", "数据", "0 条跨班错配",
        f"{len(class_mismatch)} 条", not class_mismatch)

    chunk_mismatch = q("SELECT c.id FROM knowledge_chunks c "
                       "JOIN materials m ON m.id = c.material_id "
                       "WHERE c.class_id <> m.class_id")
    rec("D-数据一致性", "检索切片与材料班级一致", "数据", "0 条跨班切片",
        f"{len(chunk_mismatch)} 条", not chunk_mismatch)

    faq_owner = q("SELECT f.id FROM qa_faqs f JOIN users u ON u.id = f.created_by "
                  "WHERE f.class_id <> u.class_id")
    rec("D-数据一致性", "FAQ 发布人属于本班", "数据", "0 条跨班发布",
        f"{len(faq_owner)} 条", not faq_owner)

    code, stats = ta.call("GET", "/api/qa/stats")
    total = stats.get("total")
    parts = [stats.get("pending"), stats.get("resolved"), stats.get("closed_unresolved")]
    db_total = q("SELECT COUNT(*) AS n FROM qa_questions WHERE class_id = "
                 "(SELECT class_id FROM users WHERE username = 'teacher_a')")[0]["n"]
    rec("D-数据一致性", "统计数字与库内一致", "数据",
        f"total = 库内 {db_total}，且三分项之和等于 total",
        f"total={total} 分项={parts} 和={sum(p for p in parts if p is not None)}",
        total == db_total and sum(p or 0 for p in parts) == total)

    # 操作人与时间留痕
    trace = q("SELECT created_by, created_at FROM qa_faqs LIMIT 1")
    rec("D-数据一致性", "FAQ 保留操作人与时间", "数据", "created_by 与 created_at 均非空",
        f"created_by={trace[0]['created_by'] if trace else '-'} "
        f"created_at={trace[0]['created_at'] if trace else '-'}",
        bool(trace) and trace[0]["created_by"] and trace[0]["created_at"])

    stop_app()

    passed = sum(1 for c in checks if c["verdict"] == "PASS")
    summary = {"total": len(checks), "pass": passed, "fail": len(checks) - passed}
    print("\n=== 汇总 ===")
    print(summary)
    for c in checks:
        if c["verdict"] != "PASS":
            print(f"FAIL: [{c['group']}] {c['name']} 期望={c['expected']} 实际={c['actual']}")

    out = WORK / "acceptance-result.json"
    out.write_text(json.dumps({"summary": summary, "checks": checks,
                               "worker_output": worker_out[-2000:]},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print("结果写入", out)
    return 0 if summary["fail"] == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        stop_app()
