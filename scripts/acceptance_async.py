"""第 8 课三条判据的自动复现（隔离环境，不触碰项目 data/）。

    uv run python scripts/acceptance_async.py
    uv run python scripts/acceptance_async.py --out reports/evidence/async-acceptance.json

产出的 JSON 与标准输出可直接贴进 reports/risk-concurrency.md 与
reports/risk-transaction.md。全程不依赖外部模型与 Docker。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELAY_MS = 250  # 演示用可控执行耗时，替代真实模型调用


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(0.95 * len(ordered) + 0.5) - 1))
    return ordered[index]


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
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                status, raw = resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read().decode("utf-8")
        elapsed_ms = (time.perf_counter() - start) * 1000
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw[:200]}
        return status, payload, elapsed_ms


def launch_worker(env: dict[str, str], *, wait: bool):
    cmd = [sys.executable, "-m", "campusclaw.task_worker", "--once",
           "--delay-ms", str(DELAY_MS)]
    if wait:
        started = time.perf_counter()
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
        return (time.perf_counter() - started) * 1000, proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return proc, 0, ""


def db_conn(home: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(home / "data" / "app.db"))
    conn.row_factory = sqlite3.Row
    return conn


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=str, default="")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    home = Path(tempfile.mkdtemp(prefix="campusclaw-async-"))
    os.chdir(ROOT)
    env = os.environ.copy()
    env["CAMPUSCLAW_HOME"] = str(home)
    env["CAMPUSCLAW_TUTOR_STUB"] = "1"
    env["CAMPUSCLAW_TASK_DELAY_MS"] = str(DELAY_MS)
    # 隔离外部模型配置：验收不需要网络。
    for key in ("CHAT_API_KEY", "EMBEDDING_API_KEY", "CHAT_BASE_URL", "EMBEDDING_BASE_URL"):
        env.pop(key, None)
    os.environ.update({k: env[k] for k in
                       ("CAMPUSCLAW_HOME", "CAMPUSCLAW_TUTOR_STUB", "CAMPUSCLAW_TASK_DELAY_MS")})
    for key in ("CHAT_API_KEY", "EMBEDDING_API_KEY", "CHAT_BASE_URL", "EMBEDDING_BASE_URL"):
        os.environ.pop(key, None)
    sys.path.insert(0, str(ROOT))

    from campusclaw import create_app
    from werkzeug.serving import make_server

    app = create_app()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = Client(f"http://127.0.0.1:{port}")

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {
            "python": sys.version.split()[0],
            "home": "<隔离临时目录，运行后清理>",
            "task_delay_ms": DELAY_MS,
            "consumer": "python -m campusclaw.task_worker --once",
            "broker": "SQLite 任务表 + 独立消费者进程（课件 queue.html 允许的实现）",
        },
        "criteria": [],
    }

    try:
        # 演示链路：登录取令牌 → 提交返回 202 与任务标识 → 轮询状态。
        status, body, _ = client.call("POST", "/api/login",
                                      {"username": "student_a1", "password": "StudentA1#2026"})
        assert status == 200, (status, body)
        student = body["token"]
        _, body, _ = client.call("POST", "/api/login",
                                 {"username": "teacher_a", "password": "TeacherA#2026"})
        teacher = body["token"]
        _, body, _ = client.call("POST", "/api/login",
                                 {"username": "teacher_b", "password": "TeacherB#2026"})
        teacher_b = body["token"]

        # ---------------- 判据一：请求不再等待执行 ----------------
        timings: list[float] = []
        contracts_ok = True
        for i in range(20):
            code, payload, ms = client.call(
                "POST", "/api/submissions",
                {"assignment_ref": "hw8-p95", "content": f"第 {i} 份作答：因为 A 所以 B，步骤完整。"},
                student,
            )
            timings.append(ms)
            if code != 202 or "task_id" not in payload or "status_url" not in payload:
                contracts_ok = False
            if "score" in payload or "result" in payload or "feedback" in payload:
                contracts_ok = False
        _, rc_worker, worker_log = launch_worker(env, wait=True)
        # 执行耗时取任务记录自身的 started_at / finished_at，不含进程启动开销。
        conn = db_conn(home)
        exec_ms = float(conn.execute("""
            SELECT AVG((julianday(finished_at)-julianday(started_at))*86400000)
            FROM grade_tasks WHERE started_at IS NOT NULL AND finished_at IS NOT NULL
        """).fetchone()[0] or 0.0)
        conn.close()
        value = p95(timings)
        passed = contracts_ok and value < exec_ms / 2 and rc_worker == 0
        report["criteria"].append({
            "id": "判据一", "name": "请求不再等待执行",
            "operation": "消费者停止状态下连续提交 20 次，逐次记录提交响应时间；随后启动消费者一次性执行完 20 条任务测单次执行耗时",
            "observable": {
                "submit_p95_ms": round(value, 2),
                "submit_min_ms": round(min(timings), 2),
                "submit_max_ms": round(max(timings), 2),
                "one_execution_ms": round(exec_ms, 2),
                "ratio": round(exec_ms / max(value, 0.001), 1),
                "all_202_with_task_id_and_no_score": contracts_ok,
                "worker_exit_code": rc_worker,
            },
            "expected": "提交 P95 显著小于一次批改执行时间，且响应体不含评分结果",
            "verdict": "绿" if passed else "红",
        })

        # ---------------- 判据二：任务不因进程终止而丢失 ----------------
        code, submitted, _ = client.call(
            "POST", "/api/submissions",
            {"assignment_ref": "hw8-durability", "content": "停消费者期间提交的作答：因为 X 所以 Y。"},
            student,
        )
        tid = submitted["task_id"]
        before_states = []
        for _ in range(3):
            _, snap, _ = client.call("GET", submitted["status_url"], token=student)
            before_states.append({"status": snap.get("status"), "attempts": snap.get("attempts")})
        proc, _, _ = launch_worker(env, wait=False)
        seen: list[str] = []
        final = {}
        while proc.poll() is None:
            _, snap, _ = client.call("GET", submitted["status_url"], token=student)
            if snap.get("status") and (not seen or seen[-1] != snap["status"]):
                seen.append(snap["status"])
            time.sleep(0.02)
        for _ in range(20):
            _, final, _ = client.call("GET", submitted["status_url"], token=student)
            if final.get("status") == "succeeded":
                break
            time.sleep(0.05)
        worker_output = proc.stdout.read() if proc.stdout else ""
        stopped_pending = all(s["status"] == "pending" and s["attempts"] == 0 for s in before_states)
        passed = (code == 202 and stopped_pending and final.get("status") == "succeeded"
                  and final.get("attempts") == 1 and final.get("result") is not None)
        report["criteria"].append({
            "id": "判据二", "name": "任务不因进程终止而丢失",
            "operation": "消费者未运行时提交并连续查询 3 次；随后启动消费者，轮询直至终态",
            "observable": {
                "submit_status_code": code,
                "task_id": tid,
                "before_consumer": before_states,
                "state_sequence": seen,
                "final_status": final.get("status"),
                "final_attempts": final.get("attempts"),
                "result_present": final.get("result") is not None,
                "required_resubmit": False,
                "worker_log_tail": worker_output.strip().splitlines()[-2:],
            },
            "expected": "提交返回成功、状态停留 pending 且 attempts 不增；消费者启动后自动执行，无需重新提交",
            "verdict": "绿" if passed else "红",
        })

        # ---------------- 判据三：重复不产生重复结果 ----------------
        content = "重复提交与重复投递的同一份作答：因为 P 所以 Q。"
        _, first, _ = client.call("POST", "/api/submissions",
                                  {"assignment_ref": "hw8-idempotency", "content": content}, student)
        _, second, _ = client.call("POST", "/api/submissions",
                                   {"assignment_ref": "hw8-idempotency", "content": content}, student)
        launch_worker(env, wait=True)
        _, after_first, _ = client.call("GET", first["status_url"], token=student)
        # 人为制造重复投递：把这条任务放回 pending，等价于代理未收到 ACK 后重投。
        conn = db_conn(home)
        conn.execute("UPDATE grade_tasks SET status='pending', finished_at=NULL WHERE task_id=?",
                     (first["task_id"],))
        conn.commit()
        launch_worker(env, wait=True)
        rows = conn.execute(
            "SELECT idempotency_key,score,task_id FROM grade_results").fetchall()
        matching = [dict(r) for r in rows if r["task_id"] == first["task_id"]]
        attempts = conn.execute("SELECT attempts,status FROM grade_tasks WHERE task_id=?",
                                (first["task_id"],)).fetchone()
        _, after_redelivery, _ = client.call("GET", first["status_url"], token=student)
        conn.close()
        score_stable = (after_first.get("result") is not None
                        and after_redelivery.get("result") is not None
                        and after_first["result"]["score"] == after_redelivery["result"]["score"])
        passed = (first["task_id"] == second["task_id"] and len(matching) == 1
                  and int(attempts["attempts"]) == 2 and score_stable)
        report["criteria"].append({
            "id": "判据三", "name": "重复不产生重复结果",
            "operation": "同一份提交连发两次；任务完成后把状态放回 pending 模拟代理重复投递，再执行一次消费者",
            "observable": {
                "first_task_id": first["task_id"],
                "second_task_id": second["task_id"],
                "same_task_id": first["task_id"] == second["task_id"],
                "result_rows_for_submission": len(matching),
                "attempts_after_redelivery": int(attempts["attempts"]),
                "score_before": (after_first.get("result") or {}).get("score"),
                "score_after": (after_redelivery.get("result") or {}).get("score"),
            },
            "expected": "结果表中该提交只有一条生效记录，attempts 增加而评分不变",
            "verdict": "绿" if passed else "红",
        })

        # ---------------- 附加：只读状态接口与班级隔离 ----------------
        _, ro1, _ = client.call("GET", first["status_url"], token=student)
        _, ro2, _ = client.call("GET", first["status_url"], token=student)
        cross_code, _, _ = client.call("GET", first["status_url"], token=teacher_b)
        report["checks"] = {
            "status_api_readonly": ro1.get("attempts") == ro2.get("attempts"),
            "cross_class_returns": cross_code,
            "cross_class_expected": 404,
            "observations": None,
        }
        obs_code, obs, _ = client.call("GET", "/api/tasks/observations", token=teacher)
        if obs_code == 200:
            report["checks"]["observations"] = obs

        report["summary"] = {
            "total": len(report["criteria"]),
            "green": sum(1 for c in report["criteria"] if c["verdict"] == "绿"),
            "red": sum(1 for c in report["criteria"] if c["verdict"] == "红"),
        }
        text = json.dumps(report, ensure_ascii=False, indent=2)
        print(text)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8")
            print(f"\n[归档] {out}")
        return 0 if report["summary"]["red"] == 0 else 1
    finally:
        server.shutdown()
        thread.join(timeout=3)
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
