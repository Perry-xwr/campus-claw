"""门禁总入口：一条命令跑完六项检查，任一项非 0 即整体非 0。

存在的理由有两个：

1. **`make check` 只是一层壳**。它依赖 GNU make，而 Windows 默认没有；
   真正跑的是六个 Python 脚本。把「跑哪些、按什么顺序、传什么参数」
   收在这一处，Makefile 与 CI 都指向它，就不会出现「三套清单各说各话」
   ——DEF-07（`make check-compose` 被写成字面量 `/n/t`）正是清单漂移的产物。

2. **缺库时不能假装通过**。`audit_recheck.py` 与 `check_observe.py` 在库不存在时
   会走「无库即跳过」这条分支，退出码仍是 0——步骤名写着「断言」，实际一条都没跑
   （DEF-09 就是这么骗过 CI 的）。所以这里在开跑前先确保 schema 建好，把那条
   最省事的分支堵掉。

用法：
    python scripts/check_all.py                  # 六项全跑
    python scripts/check_all.py --list           # 只列步骤，不执行
    python scripts/check_all.py --only audit,observe
    python scripts/check_all.py --no-init-db     # 明确要求不建库（调试用）

退出码：全部为绿返回 0；任一项非 0 或初始化失败返回 1。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "reports" / "evidence"
DB = ROOT / "data" / "app.db"
PY = sys.executable

# (键, 标题, 参数)  —— 顺序即执行顺序：先结构、后数据，最后是配置静态校验。
STEPS: list[tuple[str, str, list[str]]] = [
    ("security", "SEC-05 密钥扫描 + SEC-06 依赖基线",
     ["scripts/check_security.py", "--out", str(EVIDENCE / "security-baseline.json")]),
    ("async", "第 8 课三条判据",
     ["scripts/acceptance_async.py", "--out", str(EVIDENCE / "async-acceptance.json")]),
    ("apitest", "第 9 课注入三件套",
     ["apitest/run_all.py", "--no-report"]),
    ("audit", "SEC-07 审计七列回查",
     ["scripts/audit_recheck.py", "--db", str(DB), "--out",
      str(ROOT / "reports" / "audit-recheck.md"), "--allow-empty"]),
    ("observe", "第 10 课运行观测判定",
     ["scripts/check_observe.py", "--db", str(DB), "--out", str(EVIDENCE / "observe.json")]),
    ("compose", "容器配置静态校验",
     ["scripts/check_compose.py", "--out", str(EVIDENCE / "compose-static.json")]),
]


def ensure_schema() -> tuple[bool, str]:
    """库不存在就按应用同一套 schema 建一个，避免审计与观测两项空转。"""
    if DB.exists():
        return True, "已存在"
    proc = subprocess.run([PY, "scripts/init_schema.py"], cwd=ROOT,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["（无输出）"]
        return False, tail[0]
    return True, "不存在，已按 schema 建库"


def run_step(key: str, title: str, args: list[str]) -> tuple[str, int, float, str]:
    started = time.perf_counter()
    proc = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True)
    elapsed = time.perf_counter() - started
    output = (proc.stdout or "") + (proc.stderr or "")
    return key, proc.returncode, elapsed, output


def main() -> int:
    parser = argparse.ArgumentParser(description="CampusClaw 门禁总入口")
    parser.add_argument("--list", action="store_true", help="只列出步骤")
    parser.add_argument("--only", default="", help="逗号分隔，只跑指定步骤")
    parser.add_argument("--no-init-db", action="store_true", help="不自动建库")
    parser.add_argument("--verbose", action="store_true", help="输出每一步的完整日志")
    args = parser.parse_args()

    selected = [s for s in STEPS
                if not args.only or s[0] in {k.strip() for k in args.only.split(",") if k.strip()}]
    if not selected:
        print(f"没有匹配的步骤：{args.only}", file=sys.stderr)
        return 1

    if args.list:
        for key, title, _ in selected:
            print(f"{key:<10} {title}")
        return 0

    if not args.no_init_db:
        ok, detail = ensure_schema()
        if not ok:
            print(f"[门禁] 建库失败，中止：{detail}", file=sys.stderr)
            return 1
        if detail != "已存在":
            print(f"[门禁] data/app.db {detail}（否则审计与观测会走「无库即跳过」的假绿分支）")

    results: list[tuple[str, str, int, float]] = []
    for key, title, step_args in selected:
        print(f"[门禁] {key:<10} {title} …", flush=True)
        key, code, elapsed, output = run_step(key, title, step_args)
        results.append((key, title, code, elapsed))
        if args.verbose and output.strip():
            print(output)
        elif code != 0:
            # 失败时必须看到原因，否则只给一个非 0 退出码等于让人去猜。
            tail = "\n".join(output.strip().splitlines()[-15:])
            print(tail, file=sys.stderr)

    width = max(len(t) for _, t, _, _ in results)
    print("\n" + "-" * (width + 22))
    print(f"{'步骤':<10} {'项':<{width}} {'结果':<8} 耗时")
    print("-" * (width + 22))
    for key, title, code, elapsed in results:
        verdict = "通过" if code == 0 else f"未通过({code})"
        print(f"{key:<10} {title:<{width}} {verdict:<8} {elapsed:5.1f}s")
    failed = [r for r in results if r[2] != 0]
    print("-" * (width + 22))
    print(f"合计 {len(results)} 项，通过 {len(results) - len(failed)}，未通过 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
