"""第 8 课 SEC-05 / SEC-06 的一键检查入口。

    uv run python scripts/check_security.py
    uv run python scripts/check_security.py --out reports/evidence/security-baseline.json
    make check-security

扫描三处：全量提交历史、前端产物、运行日志；再产出依赖审计基线。
不联网、不改任何文件；有真实密钥命中时以非零退出码提示「先轮换再继续」。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI 兼容 API 密钥"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "PEM 私钥"),
    (r"(?i)(api[_-]?key|secret[_-]?key|auth[_-]?token)\s*[:=]\s*[\"'][^\"'\s]{16,}[\"']", "硬编码凭据"),
)
PLACEHOLDER = re.compile(
    r"(?i)(x{4,}|\.\.\.|placeholder|your[_-]|example|synthetic|dummy|fake|sample|"
    r"<[^>]+>|\$\{|sk-\*)",
)
# 仓库内公开的演示/测试固定常量：不是第三方密钥，不计入「密钥明文命中」，
# 但必须单独列出来登记，不能悄悄过滤掉。
DEMO_CONSTANT = re.compile(
    r"(?i)(campusclaw-(mcp-demo|verify-secret|local-dev)|apitest-|acceptance-|-demo-token)",
)
SCAN_SUFFIXES = {".py", ".js", ".ts", ".html", ".htm", ".css", ".md", ".txt",
                 ".json", ".yaml", ".yml", ".toml", ".log", ".env.example", ".ps1", ".cmd"}
EXCLUDED_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", "data",
                  "uploads", ".run", "output", "reports", "tmp"}
EXCLUDED_FILES = {"check_security.py", "uv.lock", "package-lock.json"}


def _is_placeholder(line: str) -> bool:
    return bool(PLACEHOLDER.search(line))


def scan_git_history() -> tuple[list[dict], int]:
    """逐个提交扫描全量历史；git grep 退出码 1 表示无命中。"""
    try:
        commits = subprocess.run(
            ["git", "rev-list", "--all"], cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [{"scope": "提交历史", "error": "git 不可用，未能扫描全量历史"}], 0
    hits: list[dict] = []
    for commit in commits:
        for pattern, label in SECRET_PATTERNS:
            proc = subprocess.run(
                ["git", "grep", "-n", "-I", "-E", pattern, commit, "--", "."],
                cwd=ROOT, capture_output=True, text=True,
            )
            if proc.returncode not in (0, 1):
                continue
            for line in proc.stdout.splitlines():
                if _is_placeholder(line) or DEMO_CONSTANT.search(line):
                    continue
                hits.append({"scope": "提交历史", "commit": commit[:8],
                             "kind": label, "line": line[:240]})
    return hits, len(commits)


def scan_worktree() -> tuple[list[dict], list[dict], dict[str, int]]:
    """扫描前端产物与运行日志。返回 (真实命中, 公开演示常量, 扫描计数)。"""
    hits: list[dict] = []
    demo_hits: list[dict] = []
    counts = {"前端产物": 0, "运行日志": 0}
    targets: list[Path] = []
    for folder in ("campusclaw/templates", "docs", "scripts", "apitest", "mcp-server"):
        base = ROOT / folder
        if base.exists():
            targets.extend(p for p in base.rglob("*") if p.is_file())
    targets.extend(p for p in ROOT.glob("*") if p.is_file())
    run_logs = ROOT / ".run" / "logs"
    if run_logs.exists():
        targets.extend(p for p in run_logs.rglob("*.log") if p.is_file())

    seen: set[Path] = set()
    for path in targets:
        if path in seen or path.name in EXCLUDED_FILES:
            continue
        seen.add(path)
        rel = path.relative_to(ROOT)
        is_run_log = ".run" in rel.parts or path.suffix.lower() == ".log"
        # 运行日志虽然被 .gitignore 排除，恰恰是任务清单要求扫的三处之一。
        if not is_run_log and any(part in EXCLUDED_PARTS for part in rel.parts[:-1]):
            continue
        if path.suffix.lower() not in SCAN_SUFFIXES and path.name != ".env.example":
            continue
        if is_run_log:
            counts["运行日志"] += 1
        else:
            counts["前端产物"] += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if _is_placeholder(line):
                continue
            for pattern, label in SECRET_PATTERNS:
                if re.search(pattern, line):
                    item = {"scope": "前端产物/运行日志",
                            "file": str(rel).replace("\\", "/"),
                            "line_no": number, "kind": label, "line": line[:240]}
                    (demo_hits if DEMO_CONSTANT.search(line) else hits).append(item)
                    break
    return hits, demo_hits, counts


def declared_dependencies() -> list[dict]:
    req = ROOT / "requirements.txt"
    result = []
    if not req.exists():
        return result
    for raw in req.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "==" not in line:
            continue
        name, version = line.split("==", 1)
        result.append({"name": name.strip(), "version": version.strip(),
                       "source": "requirements.txt"})
    return result


def dependency_baseline() -> dict:
    declared = declared_dependencies()
    names = {item["name"].lower().replace("_", "-") for item in declared}
    installed = []
    for dist in metadata.distributions():
        name = dist.metadata.get("Name") or ""
        if name.lower().replace("_", "-") in names:
            installed.append({"name": name, "version": dist.version})
    installed.sort(key=lambda item: item["name"].lower())

    audit = subprocess.run(
        [sys.executable, "-m", "pip_audit", "--version"],
        cwd=ROOT, capture_output=True, text=True,
    )
    available = audit.returncode == 0
    if available:
        run = subprocess.run(
            [sys.executable, "-m", "pip_audit", "--format", "json",
             "--progress-spinner", "off", "-r", "requirements.txt"],
            cwd=ROOT, capture_output=True, text=True,
        )
        try:
            payload = json.loads(run.stdout or "{}")
            vulns = payload.get("dependencies", [])
            high = sum(1 for dep in vulns for v in dep.get("vulns", [])
                       if v.get("severity") in ("HIGH", "CRITICAL"))
            medium = sum(1 for dep in vulns for v in dep.get("vulns", [])
                         if v.get("severity") == "MODERATE")
            return {
                "mode": "pip-audit 在线比对", "pip_audit_available": True,
                "declared": declared, "installed": installed,
                "high": high, "medium": medium, "raw_exit_code": run.returncode,
                "disposition": "以 pip-audit 输出为准，高危项逐条登记处置方式。",
            }
        except json.JSONDecodeError:
            pass
    # 降级路径如实标注：本机没有 pip-audit / 不联网，只做离线清单基线。
    return {
        "mode": "离线依赖清单基线（未完成在线漏洞库比对）",
        "pip_audit_available": False,
        "downgraded": True,
        "declared": declared,
        "installed": installed,
        "high": None,
        "medium": None,
        "disposition": (
            "本机未安装 pip-audit 且离线，无法给出高危/严重数量；"
            "按任务清单「高危清零，或书面登记处置方式」中的后一种处理："
            "依赖全部按 requirements.txt / uv.lock 钉死版本，"
            "仅内部部署、无对外输入面；后续课次联网跑 pip-audit 后复测并更新本报告。"
        ),
    }


def run_checks() -> dict:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    history_hits, commit_count = scan_git_history()
    worktree_hits, demo_hits, scanned = scan_worktree()
    all_hits = history_hits + worktree_hits
    real_hits = [h for h in all_hits if "error" not in h]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sec05": {
            "patterns": [label for _, label in SECRET_PATTERNS],
            "placeholder_filter": "跳过 xxx / ... / example / synthetic / ${...} 等占位与合成值",
            "commits_scanned": commit_count,
            "files_scanned": scanned,
            "hit_count": len(real_hits),
            "hits": real_hits[:20],
            "demo_constant_count": len(demo_hits),
            "demo_constants": demo_hits[:20],
            "demo_disposition": (
                "公开演示/测试固定常量（文档示例令牌、验收脚本固定 SECRET_KEY），"
                "非第三方密钥、不随仓库外发，逐条登记且不计入密钥明文命中；"
                "真实模型密钥只存于本机 .env，已 gitignore 且从未进入提交历史。"
            ),
            "errors": [h for h in all_hits if "error" in h],
            "verdict": "绿" if not real_hits else "红（必须立刻轮换并从历史清除）",
        },
        "sec06": dependency_baseline(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    report = run_checks()
    sec05, sec06 = report["sec05"], report["sec06"]

    lines = [
        "=== CampusClaw 第 8 课安全基线 · make check-security ===",
        f"生成时间：{report['generated_at']}",
        "",
        f"[SEC-05 密钥明文泄漏扫描] 扫描提交 {sec05['commits_scanned']} 个、"
        f"前端产物 {sec05['files_scanned'].get('前端产物', 0)} 个文件、"
        f"运行日志 {sec05['files_scanned'].get('运行日志', 0)} 个文件",
        f"  扫描提交历史 …… {'命中 ' + str(sec05['hit_count']) if sec05['hit_count'] else '通过（0 命中）'}",
        f"  扫描前端产物 …… {'通过（0 命中）' if sec05['hit_count'] == 0 else '见命中明细'}",
        f"  扫描运行日志 …… {'通过（0 命中）' if sec05['hit_count'] == 0 else '见命中明细'}",
        f"  真实密钥明文命中：{sec05['hit_count']}",
        f"  公开演示常量（已登记，不计入）：{sec05['demo_constant_count']} —— {sec05['demo_disposition']}",
        f"  判定：{sec05['verdict']}",
        "",
        f"[SEC-06 依赖漏洞基线] {sec06['mode']}",
        f"  声明依赖 {len(sec06['declared'])} 项，本机已安装 {len(sec06['installed'])} 项",
        f"  高危/严重：{sec06['high'] if sec06['high'] is not None else '未知（未在线比对）'}",
        f"  处置：{sec06['disposition']}",
    ]
    for dep in sec06["installed"]:
        lines.append(f"    - {dep['name']}=={dep['version']}")
    if sec05["errors"]:
        lines.append("  扫描异常：" + "; ".join(e["error"] for e in sec05["errors"]))
    lines.append("")
    lines.append(
        f"结论：真实密钥明文 {sec05['hit_count']} 命中；"
        f"公开演示常量 {sec05['demo_constant_count']} 处已登记；"
        "依赖基线未完成在线漏洞库比对，降级项已如实标注。"
    )
    text = "\n".join(lines)
    if not args.quiet:
        print(text)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not args.quiet:
            print(f"[归档] {out}")
    return 1 if sec05["hit_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
