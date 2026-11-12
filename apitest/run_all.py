"""apitest 套件入口：发现 cases 下的用例、孵化隔离实例、聚合判定。

用法：
    python apitest/run_all.py            # 跑全部并归档 JSON
    python apitest/run_all.py --no-report # 只跑不归档（make check-apitest 用）

退出码：全部为绿返回 0，任一条为红返回 1——门禁据此挡住合并。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apitest.common import Context, Server  # noqa: E402

CASES_DIR = Path(__file__).resolve().parent / "cases"
EVIDENCE = Path(__file__).resolve().parents[1] / "reports" / "evidence" / "apitest-result.json"


def discover() -> list[Path]:
    return sorted(p for p in CASES_DIR.rglob("*.py") if p.name != "__init__.py")


def load_case(path: Path):
    relative = path.relative_to(CASES_DIR).with_suffix("")
    module_name = "apitest_cases." + ".".join(relative.parts)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载用例 {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "run") or not hasattr(module, "CASE"):
        raise RuntimeError(f"用例缺少 CASE 或 run：{path}")
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CampusClaw 接口反例与回归套件")
    parser.add_argument("--no-report", action="store_true", help="不写 reports/evidence")
    parser.add_argument("--base-url", default="", help="复用已运行实例，为空则自起隔离实例")
    args = parser.parse_args(argv)

    paths = discover()
    if not paths:
        print("没有发现任何用例，检查 apitest/cases 目录")
        return 1

    results: list[dict] = []
    server: Server | None = None
    try:
        if args.base_url:
            base_url = args.base_url
        else:
            server = Server().__enter__()
            base_url = server.base_url
        print(f"=== apitest 套件 · 实例 {base_url} · 用例 {len(paths)} 条 ===")
        context = Context(base_url)
        for path in paths:
            module = load_case(path)
            label = module.CASE.get("path", "")
            try:
                outcome = module.run(context)
            except Exception as exc:  # noqa: BLE001
                outcome = [{
                    "name": module.CASE.get("name", path.stem),
                    "kind": module.CASE.get("kind", "反例"),
                    "premise": module.CASE.get("premise", ""),
                    "action": f"执行 {path.name}",
                    "expected": "用例正常跑完并给出判定",
                    "actual": f"异常退出：{type(exc).__name__}: {exc}",
                    "verdict": "FAIL",
                }]
            items = outcome if isinstance(outcome, list) else [outcome]
            for item in items:
                item.setdefault("file", str(path.relative_to(CASES_DIR.parents[1])).replace("\\", "/"))
                item["endpoint"] = module.CASE.get("method", "") + " " + label
                results.append(item)
                mark = "绿" if item["verdict"] == "PASS" else "红"
                print(f"  [{mark}] {item['name']}")
                print(f"        操作：{item['action']}")
                print(f"        实测：{item['actual']}")
    finally:
        if server is not None:
            server.__exit__(None, None, None)

    passed = sum(1 for item in results if item["verdict"] == "PASS")
    failed = len(results) - passed
    summary = {"total": len(results), "pass": passed, "fail": failed}
    print(f"=== 汇总：{passed}/{len(results)} 为绿，{failed} 条为红；CHECK_EXIT={0 if failed == 0 else 1} ===")

    if not args.no_report:
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE.write_text(json.dumps({"summary": summary, "checks": results},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"证据已写入 {EVIDENCE.relative_to(Path(__file__).resolve().parents[1])}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
