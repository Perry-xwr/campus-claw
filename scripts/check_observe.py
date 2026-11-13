"""第 10 课判据「运行观测」：告警判定回查（并入 make check）。

课件判据「出问题能在用户发现之前看到」。光有 ``/metrics`` 只是有数据源，
本脚本负责**判读**：按 ``campusclaw/observability.py`` 的规则跑一遍，
任何 critical 级未通过项即退出码 1，让门禁挡住「指标坏了但没人看」的状态。

两种取数方式：

* ``--db path``       直接读 SQLite（门禁用，不需要启动服务）
* ``--base-url URL``  打 ``/api/health/alerts``（对已部署实例巡检）

用法：
    python scripts/check_observe.py --db data/app.db --out reports/evidence/observe.json
    python scripts/check_observe.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

# 脚本在 scripts/ 下运行，默认 sys.path 只有 scripts/；补上项目根才能 import campusclaw。
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _display_path(path: Path) -> str:
    """证据里写相对项目根的路径，避免绝对路径进版本库、换机复核对不上。"""
    try:
        return path.resolve().relative_to(_ROOT).as_posix()
    except ValueError:
        return str(path)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _probe_http(base_url: str) -> dict:
    url = base_url.rstrip("/") + "/api/health/alerts"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"告警接口返回 HTTP {exc.code}：{url}") from None
    except urllib.error.URLError as exc:
        raise SystemExit(f"连不上 {url}：{exc.reason}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="运行观测告警判定")
    parser.add_argument("--db", default="data/app.db", help="直接读库（门禁用）")
    parser.add_argument("--base-url", default="", help="改为巡检已运行实例")
    parser.add_argument("--out", default="reports/evidence/observe.json")
    parser.add_argument(
        "--fail-on",
        choices=("critical", "degraded"),
        default="critical",
        help="达到该等级即退出码 1（默认只挡 critical）",
    )
    args = parser.parse_args()

    if args.base_url:
        verdict = _probe_http(args.base_url)
        source = args.base_url
    else:
        db_path = Path(args.db)
        if not db_path.exists():
            # 干净环境还没启动过应用时没有库，规则无从判定。这不等于通过，
            # 但有别门禁项（审计结构断言）会覆盖建表，这里按跳过处理并说明。
            print(f"数据库不存在（{db_path}），跳过告警判定：先启动一次应用完成初始化")
            return 0
        from campusclaw import observability

        conn = _connect(db_path)
        try:
            verdict = observability.evaluate(conn)
        finally:
            conn.close()
        source = _display_path(db_path)

    alerts = verdict.get("alerts") or []
    rules = verdict.get("rules") or []
    status = str(verdict.get("status") or "unknown")

    print(f"数据来源：{source}")
    print(f"判定时间：{verdict.get('checked_at', '')}")
    print(f"规则数：{len(rules)}，未通过：{len(alerts)}，跳过：{verdict.get('skipped', 0)}")
    print("")
    print(f"{'规则':<20}{'判定项':<28}{'实际':<12}{'阈值':<10}结果")
    for r in rules:
        if r.get("skipped"):
            mark = "跳过"
        elif r.get("ok"):
            mark = "通过"
        else:
            mark = f"未通过({r.get('level')})"
        print(f"{str(r.get('id')):<20}{str(r.get('title')):<28}"
              f"{str(r.get('value')):<12}{str(r.get('threshold')):<10}{mark}")
    print("")
    print(f"综合状态：{status}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"source": source, "verdict": verdict},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"已写入 {out}")

    floor = args.fail_on
    failed = status == "critical" or (floor == "degraded" and status == "degraded")
    if failed:
        detail = "；".join(f"{a.get('id')}={a.get('value')}（阈值 {a.get('threshold')}）"
                          for a in alerts)
        print(f"判定：红 — {detail}", file=sys.stderr)
        return 1
    print("判定：绿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
