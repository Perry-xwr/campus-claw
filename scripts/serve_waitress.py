"""等待验收/压测用的服务器：waitress 起服务，跑满 ``--seconds`` 后**优雅关闭**。

为什么需要它：验收要反复起停服务，而直接结束进程会在写事务中途终止，
SQLite 可能留下结构异常——本轮实测出现过 ``integrity_check`` 报
``Page 84: never used`` 与 ``wrong # of entries in index``，随后整库不可读，
下一轮压测拿到一堆 500，把结论带偏。用 ``create_server`` + ``close()``
正常收尾，压测完的库还是干净的。

两种用法：

    # 压测：两轮用同一份数据目录、同一台机器、同一套参数
    CAMPUSCLAW_HOME=<数据目录> python scripts/serve_waitress.py --port 8121 --seconds 340
    python scripts/bench.py --base http://127.0.0.1:8121 --vus 20 --duration 60

    # 验收走查：给 skill_demo.py / H5 演示提供一个真跑 waitress 的实例
    python scripts/serve_waitress.py --port 8110 --seconds 600

waitress 不是运行期依赖（生产用 gunicorn），只为验收与压测安装：

    pip install waitress
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

try:
    from waitress import create_server
except ImportError:  # pragma: no cover - 环境准备问题，给出可执行的一步
    print("缺少 waitress：请先 pip install waitress（仅压测用，不进运行期依赖）", file=sys.stderr)
    raise SystemExit(2)

# 直接 `python scripts/bench_server.py` 时 sys.path[0] 是 scripts/，得把项目根补进来。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app  # noqa: E402  —— 先校验依赖，再触发应用启动


def main() -> int:
    parser = argparse.ArgumentParser(description="压测用服务器（到时优雅关闭）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8121)
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--seconds", type=float, default=300.0,
                        help="监听时长；到点自动 close()，不在写事务中途硬杀进程")
    args = parser.parse_args()

    server = create_server(app, host=args.host, port=args.port, threads=args.threads)
    worker = threading.Thread(target=server.run, daemon=True)
    worker.start()
    print(f"listening http://{args.host}:{args.port} threads={args.threads} "
          f"for {args.seconds:g}s", flush=True)
    try:
        time.sleep(args.seconds)
    finally:
        # close() 会让 run() 退出：连接被 drain，写事务正常结束。
        server.close()
        worker.join(timeout=10)
        print("closed cleanly", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
