#!/usr/bin/env python
"""容器配置静态校验：在 Docker 装上之前先把配置类错误挡掉。

第 10 课判据「环境可复现」的完整验证是 ``docker compose up -d`` 实跑，但实跑之前
有一整类错误**不需要 Docker 就能查**：``depends_on`` 指向不存在的服务、``COPY`` 的
源文件在仓库里没有、启动命令的可执行文件不在依赖清单里、健康检查探的路径根本不存在、
镜像的解释器版本与 ``requires-python`` 对不上。

这些错误的共同点是「配置写完了、语法也对、只有真正构建时才炸」，而构建一次要几分钟。
先静态查一遍，实跑那一步就只剩真环境问题。

用法::

    python scripts/check_compose.py                  # 校验并打印
    python scripts/check_compose.py --out x.json     # 另存 JSON 证据

任一检查项不通过即退出码 1。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
COMPOSE = _ROOT / "docker-compose.yml"
DOCKERFILE = _ROOT / "Dockerfile"
REQUIREMENTS = _ROOT / "requirements.txt"
PYPROJECT = _ROOT / "pyproject.toml"


class Checker:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, cid: str, title: str, ok: bool, detail: str, fix: str = "") -> None:
        self.items.append(
            {"id": cid, "title": title, "ok": bool(ok), "detail": detail, "fix": fix}
        )

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [i for i in self.items if not i["ok"]]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _load_compose(chk: Checker) -> dict[str, Any]:
    if not COMPOSE.exists():
        chk.add("compose.exists", "docker-compose.yml 存在", False, "文件不存在")
        return {}
    try:
        import yaml
    except ImportError:
        # pyyaml 由 langchain-core 传递引入（已固定在 uv.lock），`uv sync --locked`
        # 或 `pip install -r requirements.txt` 之后必然存在，因此不单独声明依赖。
        chk.add("compose.yaml", "docker-compose.yml 可解析", False,
                "环境缺 pyyaml，无法静态解析", "pip install pyyaml")
        return {}
    try:
        data = yaml.safe_load(_read(COMPOSE))
    except Exception as exc:
        chk.add("compose.yaml", "docker-compose.yml 可解析", False, f"YAML 解析失败：{exc}")
        return {}
    ok = isinstance(data, dict) and bool(data.get("services"))
    chk.add("compose.yaml", "docker-compose.yml 可解析", ok,
            f"服务 {len(data.get('services') or {})} 个" if ok else "顶层缺 services")
    return data if isinstance(data, dict) else {}


def _parse_requires_python(text: str) -> tuple[int, int] | None:
    m = re.search(r'>=\s*(\d+)\.(\d+)', text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _parse_upper_python(text: str) -> tuple[int, int] | None:
    m = re.search(r'<\s*(\d+)\.(\d+)', text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _copy_sources(dockerfile: str) -> list[str]:
    """提取 COPY 的源路径；多阶段与 --from 的 COPY 跳过。"""
    sources: list[str] = []
    for line in dockerfile.splitlines():
        line = line.strip()
        if not line.upper().startswith("COPY "):
            continue
        if "--from" in line:
            continue
        parts = line.split()[1:]
        parts = [p for p in parts if not p.startswith("--")]
        if len(parts) < 2:
            continue
        sources.extend(parts[:-1])
    return sources


def _expanded_vars(value: str) -> str:
    """把 ${VAR:-default} 展开成 default，便于比较端口常量。"""
    return re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", value)


def check_all() -> Checker:
    chk = Checker()
    compose = _load_compose(chk)
    services: dict[str, Any] = compose.get("services") or {}
    dockerfile = _read(DOCKERFILE)
    requirements = _read(REQUIREMENTS)
    pyproject = _read(PYPROJECT)

    # 1. 项目名固定：不固定时目录改名会让卷被当成新项目重建，Qdrant 向量"消失"。
    name = compose.get("name")
    chk.add("compose.name", "固定了 Compose 项目名", bool(name),
            f"name={name}" if name else "未设置 name，卷名会随目录名变化",
            "在 compose 顶层加 name: campusclaw")

    # 2. depends_on 必须指向存在的服务。
    missing_deps: list[str] = []
    for svc, cfg in services.items():
        for dep in (cfg or {}).get("depends_on") or []:
            dep_name = dep if isinstance(dep, str) else next(iter(dep or {}), "")
            if dep_name and dep_name not in services:
                missing_deps.append(f"{svc}→{dep_name}")
    chk.add("compose.depends_on", "depends_on 均指向已定义服务", not missing_deps,
            f"悬空依赖：{'、'.join(missing_deps)}" if missing_deps else
            f"{len(services)} 个服务依赖闭合")

    # 3. build 上下文存在且含 Dockerfile。
    bad_build: list[str] = []
    for svc, cfg in services.items():
        build = (cfg or {}).get("build")
        if build is None:
            continue
        ctx = build if isinstance(build, str) else (build or {}).get("context", ".")
        df = (build or {}).get("dockerfile", "Dockerfile") if isinstance(build, dict) else "Dockerfile"
        if not (_ROOT / ctx / df).exists():
            bad_build.append(f"{svc}({ctx}/{df})")
    chk.add("dockerfile.exists", "build 上下文与 Dockerfile 存在", not bad_build,
            f"缺失：{'、'.join(bad_build)}" if bad_build else "全部存在")

    # 4. Dockerfile 的 COPY 源在仓库里必须存在（否则 build 阶段才报错）。
    absent = [s for s in _copy_sources(dockerfile) if not (_ROOT / s).exists()]
    chk.add("dockerfile.copy", "COPY 源文件均存在", not absent,
            f"仓库中不存在：{'、'.join(absent)}" if absent else "COPY 源齐备",
            "补齐文件或从 Dockerfile 删除该行")

    # 5. 启动命令的可执行文件在依赖清单里（gunicorn 不在 requirements 就会 build 通过、run 失败）。
    cmds: list[str] = []
    m = re.search(r'CMD\s*\[\s*"([^"]+)"', dockerfile)
    if m:
        cmds.append(m.group(1))
    for cfg in services.values():
        c = (cfg or {}).get("command")
        if isinstance(c, list) and c:
            cmds.append(str(c[0]))
    missing_bins = []
    for binary in set(cmds):
        if binary in ("python", "sh", "bash"):
            continue
        if not re.search(rf"^{re.escape(binary)}[=<>~]", requirements, re.MULTILINE):
            missing_bins.append(binary)
    chk.add("deps.entrypoint", "启动命令的可执行文件在依赖清单中", not missing_bins,
            f"requirements.txt 缺：{'、'.join(missing_bins)}" if missing_bins
            else f"命令 {sorted(set(cmds))} 均有来源")

    # 6. `python -m <模块>` 的模块在仓库里必须存在。
    modules: list[str] = []
    for cfg in services.values():
        c = (cfg or {}).get("command") or []
        if isinstance(c, list) and len(c) >= 3 and c[0] == "python" and c[1] == "-m":
            modules.append(str(c[2]))
    missing_mods = []
    for mod in modules:
        rel = mod.replace(".", "/")
        cands = [_ROOT / rel, _ROOT / f"{rel}.py", _ROOT / "mcp-server" / rel,
                 _ROOT / "mcp-server" / f"{rel}.py"]
        if not any(p.exists() for p in cands):
            missing_mods.append(mod)
    chk.add("compose.module", "python -m 的模块在仓库中存在", not missing_mods,
            f"找不到：{'、'.join(missing_mods)}" if missing_mods
            else (f"模块 {'、'.join(modules)} 齐备" if modules else "无 -m 启动项"))

    # 7. 健康检查探的路径必须是应用真实存在的路由。
    health_paths: set[str] = set()
    for cfg in services.values():
        hc = (cfg or {}).get("healthcheck") or {}
        test = hc.get("test")
        blob = " ".join(test) if isinstance(test, list) else str(test or "")
        health_paths.update(re.findall(r"https?://[^'\"]*?(/[A-Za-z0-9_./-]*)", blob))
    route_ok = True
    routes_note = "未配置健康检查"
    if health_paths:
        try:
            import os
            import tempfile

            os.environ.setdefault("CAMPUSCLAW_HOME", tempfile.mkdtemp(prefix="compose-check-"))
            sys.path.insert(0, str(_ROOT))
            import campusclaw

            app = campusclaw.create_app(env=dict(os.environ))
            rules = {str(r.rule) for r in app.url_map.iter_rules()}
            absent_paths = sorted(p for p in health_paths if p not in rules)
            route_ok = not absent_paths
            routes_note = (f"健康检查路径不在路由表：{'、'.join(absent_paths)}"
                           if absent_paths else f"健康检查路径 {'、'.join(sorted(health_paths))} 已注册")
        except Exception as exc:  # pragma: no cover
            route_ok = False
            routes_note = f"无法加载应用路由：{exc}"
    chk.add("compose.healthcheck", "健康检查路径是真实路由", route_ok, routes_note,
            "把健康检查改成应用实际暴露的路径")

    # 8. 容器端口映射与 EXPOSE 一致性（只查 app 服务，避免 bind 端口写错无人发现）。
    # 一行可声明多个端口（EXPOSE 8080 8090），要全取；只取第一个会误报。
    expose = {
        int(n)
        for line in dockerfile.splitlines()
        if line.strip().upper().startswith("EXPOSE")
        for n in re.findall(r"\d+", line)
    }
    port_mismatch: list[str] = []
    for svc, cfg in services.items():
        for mapping in (cfg or {}).get("ports") or []:
            text = _expanded_vars(str(mapping))
            tail = text.rsplit(":", 1)[-1].split("/")[0]
            if not tail.isdigit():
                continue
            cport = int(tail)
            if expose and cport not in expose and (cfg or {}).get("build"):
                port_mismatch.append(f"{svc}:{cport} 不在 EXPOSE {sorted(expose)}")
    chk.add("dockerfile.expose", "端口映射与 EXPOSE 一致", not port_mismatch,
            "；".join(port_mismatch) if port_mismatch else f"EXPOSE {sorted(expose) or '未声明'}")

    # 9. 镜像的 Python 版本必须落在 requires-python 区间内。
    m = re.search(r"^FROM\s+python:(\d+)\.(\d+)", dockerfile, re.MULTILINE)
    lower = _parse_requires_python(pyproject)
    upper = _parse_upper_python(pyproject)
    if m and lower:
        img = (int(m.group(1)), int(m.group(2)))
        ok = img >= lower and (upper is None or img < upper)
        chk.add("python.version", "镜像 Python 版本符合 requires-python", ok,
                f"镜像 {img[0]}.{img[1]}；声明 >={lower[0]}.{lower[1]}"
                + (f",<{upper[0]}.{upper[1]}" if upper else ""),
                "镜像与本地验收环境统一到同一小版本")
    else:
        chk.add("python.version", "镜像 Python 版本符合 requires-python", True,
                "未使用 python 官方镜像或无 requires-python，跳过")

    return chk


def main() -> int:
    parser = argparse.ArgumentParser(description="容器配置静态校验")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    chk = check_all()
    passed = len(chk.items) - len(chk.failed)

    print("=== 容器配置静态校验（不需要 Docker）===")
    print(f"检查项：{len(chk.items)}，通过：{passed}，未通过：{len(chk.failed)}")
    print("")
    print(f"{'项':<24}{'检查内容':<34}{'结果':<8}说明")
    for item in chk.items:
        mark = "通过" if item["ok"] else "未通过"
        print(f"{item['id']:<24}{item['title']:<34}{mark:<8}{item['detail']}")
    if chk.failed:
        print("")
        print("修复建议：")
        for item in chk.failed:
            print(f"  - {item['id']}：{item['fix'] or item['detail']}")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "passed": passed,
                    "failed": len(chk.failed),
                    "items": chk.items,
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        print("")
        print(f"已写入 {args.out}")

    return 1 if chk.failed else 0


if __name__ == "__main__":
    sys.exit(main())
