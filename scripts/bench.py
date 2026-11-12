"""第 10 课：接口压测基线（纯标准库实现，不依赖 k6）。

课件判据是「压测前后对比」。本机没有 k6，也不该为了压测引入一个二进制依赖，
因此用 ``concurrent.futures`` 起固定并发做固定时长压测，输出 P50/P95/P99 与错误率。

用法（先启动一个实例）：

    python scripts/bench.py --base http://127.0.0.1:8099 --vus 20 --duration 60

结果写入 ``--out``（默认 ``reports/evidence/bench.json``），并在 ``--md`` 指定的
Markdown 里追加一节。压测只发读请求，不写数据，可重复执行。
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

# 本机压测必须绕过企业代理，否则 127.0.0.1 也会被转发出去。
for _key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"):
    os.environ.pop(_key, None)

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

#: 被压的端点：(名称, 方法, 路径, 是否需要令牌, 请求体)
ENDPOINTS: tuple[tuple[str, str, str, bool, dict | None], ...] = (
    ("健康检查", "GET", "/health", False, None),
    ("材料列表", "GET", "/api/materials", True, None),
    ("关键词检索", "POST", "/api/search", True, {"query": "示例讲义", "mode": "keyword", "limit": 5}),
    ("会话列表", "GET", "/api/conversations", True, None),
)


# 每线程复用一个 keep-alive 连接。
# 用 urllib 逐请求新建连接时，Windows 的动态端口会被 TIME_WAIT 迅速吃光，
# 45 秒 20 并发的量级就会开始 connect 失败——那是压测客户端的瓶颈，不是服务端的。
_local = threading.local()


def _connection(base: str) -> http.client.HTTPConnection:
    parts = urlsplit(base)
    key = (parts.hostname, parts.port or 80)
    conn = getattr(_local, "conn", None)
    if conn is None or getattr(_local, "key", None) != key:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        conn = http.client.HTTPConnection(key[0], key[1], timeout=30)
        _local.conn = conn
        _local.key = key
    return conn


def _request(base: str, method: str, path: str, token: str | None, body: dict | None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    # 不显式声明 keep-alive：Werkzeug 开发服务器按 HTTP/1.0 应答并回 Connection: close，
    # 客户端再声明 keep-alive 只会让复用的 socket 与对端状态不一致（大量 RemoteDisconnected）。
    # 由响应头决定是否复用，是唯一稳妥的做法。
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    started = time.perf_counter()
    # Werkzeug 开发服务器在响应里回 Connection: close（HTTP/1.0），必须遵守：
    # 复用一条已被对端关闭的连接只会得到 RemoteDisconnected。因此每次检查响应头，
    # 声明 close 就丢弃连接；另外对连接层异常重试一次，避免把客户端问题算成服务端错误。
    for attempt in (0, 1):
        conn = _connection(base)
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            resp.read()  # 必须读完才能复用连接
            status = resp.status
            if (resp.getheader("Connection") or "").lower() == "close":
                try:
                    conn.close()
                except Exception:
                    pass
                _local.conn = None
            return status, (time.perf_counter() - started) * 1000
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            _local.conn = None
            if attempt == 1:
                # status=0 表示两次尝试都失败，属于连接层问题，需单独归因。
                return 0, (time.perf_counter() - started) * 1000
    return 0, (time.perf_counter() - started) * 1000


def login(base: str, username: str, password: str) -> str | None:
    """取一个教师令牌；失败返回 None（压测需要鉴权，没令牌就没法压）。"""
    conn = _connection(base)
    try:
        conn.request(
            "POST",
            "/api/login",
            body=json.dumps({"username": username, "password": password}).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        payload = resp.read().decode("utf-8", "replace")
        if resp.status != 200:
            return None
        return json.loads(payload)["token"]
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None
        return None


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] * (1 - (pos - low)) + ordered[high] * (pos - low)


def run_endpoint(base: str, token: str | None, spec, vus: int, duration: float) -> dict:
    name, method, path, need_auth, body = spec
    auth = token if need_auth else None
    latencies: list[float] = []
    status_counts: dict[int, int] = {}
    lock = threading.Lock()
    deadline = time.perf_counter() + duration

    def worker() -> None:
        local_lat: list[float] = []
        local_status: dict[int, int] = {}
        while time.perf_counter() < deadline:
            status, ms = _request(base, method, path, auth, body)
            local_lat.append(ms)
            local_status[status] = local_status.get(status, 0) + 1
        with lock:
            latencies.extend(local_lat)
            for code, n in local_status.items():
                status_counts[code] = status_counts.get(code, 0) + n

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=vus) as pool:
        for _ in range(vus):
            pool.submit(worker)
    elapsed = time.perf_counter() - started

    total = len(latencies)
    # 只有 2xx/3xx 算成功；4xx/5xx/连接失败都计入 errors。
    errors = sum(n for code, n in status_counts.items() if code < 200 or code >= 400)
    return {
        "name": name,
        "method": method,
        "path": path,
        "vus": vus,
        "duration_s": round(elapsed, 2),
        "requests": total,
        "rps": round(total / elapsed, 1) if elapsed > 0 else 0.0,
        "errors": errors,
        "error_rate": round(errors / total, 4) if total else 0.0,
        "status_counts": {str(k): v for k, v in sorted(status_counts.items())},
        "p50_ms": round(percentile(latencies, 0.50), 2),
        "p95_ms": round(percentile(latencies, 0.95), 2),
        "p99_ms": round(percentile(latencies, 0.99), 2),
        "mean_ms": round(statistics.fmean(latencies), 2) if latencies else 0.0,
        "max_ms": round(max(latencies), 2) if latencies else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="CampusClaw 接口压测基线")
    parser.add_argument("--base", default="http://127.0.0.1:8099")
    parser.add_argument("--vus", type=int, default=20)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--user", default="teacher_a")
    parser.add_argument("--password", default="TeacherA#2026")
    parser.add_argument("--out", default="reports/evidence/bench.json")
    parser.add_argument("--md", default="reports/bench.md")
    parser.add_argument("--label", default="压测", help="写入 Markdown 的小节标题前缀")
    args = parser.parse_args()

    token = login(args.base, args.user, args.password)
    if token is None:
        print("登录失败，压测中止（检查账号口令与实例是否就绪）", file=sys.stderr)
        return 2

    results = []
    for spec in ENDPOINTS:
        print(f"压测 {spec[0]} {spec[1]} {spec[2]} vus={args.vus} {args.duration}s ...")
        results.append(run_endpoint(args.base, token, spec, args.vus, args.duration))
        row = results[-1]
        print(
            f"  rps={row['rps']} p50={row['p50_ms']}ms p95={row['p95_ms']}ms "
            f"p99={row['p99_ms']}ms err={row['errors']}"
        )

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base": args.base,
        "vus": args.vus,
        "duration_s": args.duration,
        "endpoints": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = Path(args.md)
    md.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"## {args.label}（vus={args.vus}，{args.duration:g}s，{time.strftime('%Y-%m-%d %H:%M')}）",
        "",
        "| 端点 | 请求数 | RPS | P50 (ms) | P95 (ms) | P99 (ms) | 错误 | 状态码分布 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in results:
        codes = "、".join(f"{k}×{v}" for k, v in row.get("status_counts", {}).items())
        lines.append(
            f"| `{row['method']} {row['path']}` | {row['requests']} | {row['rps']} | "
            f"{row['p50_ms']} | {row['p95_ms']} | {row['p99_ms']} | {row['errors']} | {codes} |"
        )
    lines.append("")
    header = f"# 压测基线\n\n> 由 `scripts/bench.py` 生成，原始数据见 `{args.out}`。\n"
    existing = md.read_text(encoding="utf-8") if md.exists() else header
    md.write_text(existing.rstrip() + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")

    print(f"已写入 {out} 与 {md}")
    return 0 if all(r["errors"] == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
