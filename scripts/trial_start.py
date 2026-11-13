#!/usr/bin/env python
"""真实用户试用：一条命令起服务并打印「给试用者的信息卡」。

为什么单独写一个脚本，而不是让人记住 ``python scripts/serve_waitress.py
--host 0.0.0.0 --port 8080``：试用是有现场感的——使用者坐在你旁边或者
刚拿到地址的五分钟之内。这时候最常出问题的不是服务本身，而是三件小事：

1. 服务起来没起来（8080 被上一个实例占着，新起的悄悄失败）；
2. 该给对方哪个地址（给 ``127.0.0.1`` 对方一定打不开）；
3. 账号和口令记串了（四个账号、三个角色、两个班级）。

所以这个脚本只做三件事：查端口 → 起服务 → 打一张能照着念的卡。

用法::

    python scripts/trial_start.py              # 打印信息卡并前台起服务
    python scripts/trial_start.py --print-only  # 只打印，不起服务
    python scripts/trial_start.py --port 8080 --threads 16

按 Ctrl+C 结束（走 waitress 的 ``close()``，让 SQLite 的写事务收尾，
不要直接关窗口硬杀——本项目已经因为硬杀损坏过一次数据库）。
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: 开发内置账号。与 ``reports/user-trial-record.md`` 保持一致，改一处要改两处。
ACCOUNTS = [
    ("teacher_a", "TeacherA#2026"),
    ("student_a1", "StudentA1#2026"),
    ("student_b1", "StudentB1#2026"),
    ("teacher_b", "TeacherB#2026"),
]

#: 这些网段不是「同一张内网里别人能访问到的地址」，不能给试用者。
_NOT_LAN_PREFIXES = ("127.", "169.254.", "28.")


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.6)
        return probe.connect_ex((host, port)) == 0


def _lan_addresses() -> list[str]:
    """挑出试用者可能用到的本机地址，排掉回环与沙箱桩。"""
    found: list[str] = []
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip and not ip.startswith(_NOT_LAN_PREFIXES) and ip not in found:
                found.append(ip)
    except OSError:
        pass

    # 出站地址最接近「对方要用的那个」：热点或 Wi-Fi 的网卡地址。
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("223.5.5.5", 53))  # 不真的发包，只为让内核选网卡
            outbound = s.getsockname()[0]
            if outbound and not outbound.startswith(_NOT_LAN_PREFIXES):
                found.insert(0, outbound)
        except OSError:
            pass

    seen: set[str] = set()
    return [ip for ip in found if not (ip in seen or seen.add(ip))]


def _hotspot_hint(ip: str) -> str | None:
    """172.20.10.0/28 是 iOS 个人热点的固定网段，值得单独提醒。"""
    if ip.startswith("172.20.10."):
        return "这是手机热点网段：对方必须连**同一个热点**才打得开，换 Wi-Fi 就不通。"
    return None


def _print_card(port: int, lan: list[str]) -> None:
    bar = "=" * 62
    print(bar)
    print("  给试用者的信息卡（照这张念，或者直接转发下面「给对方的话」）")
    print(bar)
    print()
    print(f"  你自己的浏览器先验一遍：http://127.0.0.1:{port}")
    if lan:
        print()
        print("  给对方的地址（按顺序试，第一个不通再试第二个）：")
        for ip in lan:
            print(f"    http://{ip}:{port}")
            hint = _hotspot_hint(ip)
            if hint:
                print(f"      ↳ {hint}")
    else:
        print()
        print("  ⚠ 没查出局域网地址。若对方不在本机，需要先确认两台设备在同一张网里。")
    print()
    print("  账号（只给账号与口令，不要说谁是什么角色、哪个班）：")
    for user, secret in ACCOUNTS:
        print(f"    {user:<12} {secret}")
    print()
    print("  给对方的话（可直接复制）：")
    print("  " + "-" * 58)
    print("  帮我看个东西，大约 10 分钟。地址和账号如下，进去随便点点，")
    print("  卡住不用问我，卡住本身就是我要的信息——记一下卡在哪一步就行。")
    print()
    # 转发只给一个地址：给一串反而会让人逐个试，第一个不通就以为坏了。
    primary = lan[0] if lan else "<本机地址>"
    print(f"    地址：http://{primary}:{port}")
    print()
    print("    账号（几选一，都试试也行）：")
    for user, secret in ACCOUNTS:
        print(f"      {user}  /  {secret}")
    print()
    print("  最后有三个问题问你，两分钟能答完。")
    print("  " + "-" * 58)
    print()
    print(bar)


def main() -> int:
    parser = argparse.ArgumentParser(description="真实用户试用：起服务并打印信息卡")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0（对方才连得上）")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="只打印信息卡，不起服务（服务已经在别处跑着时用）",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=0.0,
        help="到时自动优雅关闭；0 表示一直跑（默认）。试用批次约 15 分钟一位，可设 3600",
    )
    args = parser.parse_args()

    lan = _lan_addresses()
    _print_card(args.port, lan)

    if args.print_only:
        print("--print-only：未起服务。")
        return 0

    if _port_in_use("127.0.0.1", args.port):
        print(f"⚠ 端口 {args.port} 已被占用：可能已经有一个实例在跑。", file=sys.stderr)
        print("  先用浏览器开一下上面的地址确认；确实是旧实例，关掉它再重跑本脚本。", file=sys.stderr)
        print("  只想看信息卡：加 --print-only", file=sys.stderr)
        return 1

    # 延迟导入：--print-only 时不需要把 app 拉起来，也不该因缺依赖而失败。
    from waitress import create_server  # noqa: PLC0415

    from campusclaw import create_app  # noqa: PLC0415

    app = create_app()
    server = create_server(app, host=args.host, port=args.port, threads=args.threads)

    # 定时关闭也走 close()，和 Ctrl+C 同一条收尾路径：硬杀会让 SQLite 的写事务
    # 停在提交中途，本项目已经因此坏过两个库（见 reports/bench.md 的返工复盘）。
    timer = None
    if args.seconds > 0:
        import threading  # noqa: PLC0415

        timer = threading.Timer(args.seconds, server.close)
        timer.daemon = True
        timer.start()

    print(f"服务已启动：http://{args.host}:{args.port} threads={args.threads}")
    if args.seconds > 0:
        print(f"将在 {args.seconds:.0f} 秒后自动关闭。")
    print("让试用者开始操作。按 Ctrl+C 结束（优雅关闭，不会损坏数据库）。")
    print()
    try:
        server.run()
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在关闭……")
    finally:
        if timer is not None:
            timer.cancel()
        try:
            server.close()
        except Exception:  # noqa: BLE001 - 关闭阶段的异常不该盖住退出信息
            pass
        print("已关闭。记得把结果填进 reports/feedback.md 与 reports/user-trial-record.md。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
