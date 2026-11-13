"""第 9 课 SEC-07：审计日志七列回查（并入 make check）。

课件判据「任选一次技能调用，事后回查」：本脚本按技能标识加时间窗查
``mcp_tool_calls``，逐列断言七列齐备，并把回查原文写入
``reports/audit-recheck.md``。任一列缺失即退出码 1，让门禁挡住。

两种「不是红」要分清：
    * **绿**：时间窗内有记录，且七列齐备、拒绝尝试有留痕。
    * **跳过（无样本）**：时间窗内一条记录都没有。说明这一项本轮什么都没验，
      不能算绿。``--allow-empty`` 只是让门禁在干净环境放行（首次启动前库里
      本来就没有调用），此时**不覆盖**已有的回查报告。

七列口径：
    操作人 / 操作时间 / 操作类型 / 操作对象 / 结果状态 / 技能标识 / 用量与耗时

被拒绝的尝试（401/403/404）另在 ``audit_events``，本脚本一并核对。

用法：
    python scripts/audit_recheck.py [--db path] [--out reports/audit-recheck.md]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 脚本在 scripts/ 下运行，默认 sys.path 只有 scripts/；补上项目根才能 import campusclaw。
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

#: 七列断言：字段名 -> 中文名。任一为空即判红。
SEVEN_COLUMNS: tuple[tuple[str, str], ...] = (
    ("actor", "操作人"),
    ("created_at", "操作时间"),
    ("action", "操作类型"),
    ("object_id", "操作对象"),
    ("status", "结果状态"),
    ("skill_id", "技能标识"),
    ("duration_ms", "用量与耗时"),
)

#: 回查时间窗：0 表示不限时间，取全部历史。
#:
#: 判据原文是「任选一次技能调用，**事后**回查」——事后隔多久都算，回查的价值
#: 也不取决于记录有多新。早先默认值写成 120 分钟，结果第二天再跑就一条都查不到，
#: 证据自己过期了，还被判成绿（假绿）。要看「最近这段有没有留痕」是观测的活，
#: 不是审计回查的活。
WINDOW_MINUTES = 0

#: 退出码：0 绿 / 1 红 / 75 跳过（无样本）。门禁按 75 显示「跳过」，既不算红也不算绿。
SKIP_CODE = 75


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}（先启动一次应用完成初始化）")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")}


def assert_schema(conn: sqlite3.Connection) -> list[str]:
    """结构断言：七列在表里必须存在。缺列即红，与有没有数据无关。"""
    problems: list[str] = []
    if not _has_table(conn, "mcp_tool_calls"):
        return ["mcp_tool_calls 表不存在"]
    cols = _columns(conn, "mcp_tool_calls")
    # 操作人落 user_id（JOIN 出 username），其余六列直接落表。
    required = {
        "user_id": "操作人",
        "created_at": "操作时间",
        "action": "操作类型",
        "object_id": "操作对象",
        "status": "结果状态",
        "skill_id": "技能标识",
        "duration_ms": "用量与耗时",
    }
    for col, zh in required.items():
        if col not in cols:
            problems.append(f"mcp_tool_calls 缺列 {col}（{zh}）")
    if not _has_table(conn, "audit_events"):
        problems.append("audit_events 表不存在（被拒绝的尝试无处落库）")
    return problems


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _display_path(path: Path) -> str:
    """报告里写相对项目根的路径。

    绝对路径写进证据有两个坏处：换台机器或换个目录复核时对不上；把本机用户名、
    盘符带进版本库。项目外的路径（临时测试库）才退回绝对形式。
    """
    try:
        return path.resolve().relative_to(_ROOT).as_posix()
    except ValueError:
        return str(path)


def query_skill_calls(conn: sqlite3.Connection, window_start: str | None) -> list[dict]:
    """按技能标识加时间窗回查调用审计；``window_start`` 为 None 表示不限时间。"""
    where = "WHERE c.created_at >= ?" if window_start else ""
    params: tuple[object, ...] = (window_start,) if window_start else ()
    rows = conn.execute(
        f"""
        SELECT c.id, c.created_at, c.action, c.object_id, c.status, c.skill_id,
               c.duration_ms, c.tokens, c.request_id, c.tool_ref,
               u.username AS actor, s.name AS server_name
        FROM mcp_tool_calls c
        LEFT JOIN users u ON u.id = c.user_id
        LEFT JOIN mcp_servers s ON s.id = c.server_id
        {where}
        ORDER BY c.id DESC
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def query_rejections(conn: sqlite3.Connection, window_start: str | None) -> list[dict]:
    if not _has_table(conn, "audit_events"):
        return []
    where = "WHERE ts >= ?" if window_start else ""
    params: tuple[object, ...] = (window_start,) if window_start else ()
    rows = conn.execute(
        f"""
        SELECT id, ts, request_id, actor, actor_id, class_id, action, object_id,
               method, path, status, code, duration_ms
        FROM audit_events
        {where}
        ORDER BY id DESC
        LIMIT 50
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def _age_hint(stamp) -> str:
    """把「最近一条记录有多久」写成一句人话。

    回查不要求记录新鲜（「事后回查」本来就可能是几天后），但复核的人需要知道
    这条证据是什么时候留下的。
    """
    if not stamp:
        return ""
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    minutes = int((datetime.now(timezone.utc) - when).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} 分钟"
    if minutes < 1440:
        return f"{minutes // 60} 小时"
    return f"{minutes // 1440} 天"


def main() -> int:
    parser = argparse.ArgumentParser(description="SEC-07 审计七列回查")
    parser.add_argument("--db", default=".acc10/appdata/data/app.db")
    parser.add_argument("--out", default="reports/audit-recheck.md")
    parser.add_argument(
        "--window-minutes", type=int, default=WINDOW_MINUTES,
        help="只看最近 N 分钟；0（默认）表示不限时间，取全部历史",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="库里还没有技能调用记录时不判红（门禁里用：干净环境不可能先有调用）",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        if args.allow_empty:
            print(f"数据库不存在（{db_path}），跳过回查：结构断言留给首次启动后的运行")
            return 0
        raise SystemExit(f"数据库不存在：{db_path}（先启动一次应用完成初始化）")

    conn = _connect(db_path)
    if args.window_minutes > 0:
        window_start: str | None = (
            datetime.now(timezone.utc) - timedelta(minutes=args.window_minutes)
        ).isoformat()
        window_label = f"最近 {args.window_minutes} 分钟"
    else:
        window_start = None
        window_label = "不限（全部历史，原文只列最近 5 条）"

    # 老库升级：本地已有的 data/app.db 是旧结构，缺 SEC-07 的列。这里跑一次与应用
    # 启动完全相同的幂等迁移（只加列/建表，不删数据），否则回查 SQL 无法执行。
    migrated_from: set[str] = set()
    if _has_table(conn, "mcp_tool_calls"):
        migrated_from = _columns(conn, "mcp_tool_calls")
    try:
        from campusclaw import audit_db, mcp_db

        mcp_db.ensure_schema(conn)
        audit_db.ensure_schema(conn)
    except Exception as exc:  # pragma: no cover - 迁移失败时如实报告
        print(f"迁移失败：{exc}", file=sys.stderr)

    schema_problems = assert_schema(conn)
    calls = query_skill_calls(conn, window_start)
    rejections = query_rejections(conn, window_start)

    failures: list[str] = list(schema_problems)
    # 「时间窗内没有样本」与「七列齐备」是两件事。前者说明这一项本轮什么都没验，
    # 不能据此判绿——否则表结构断言过的表在空库里也会显示「绿：七列齐备」，
    # 而同一份报告的表格里七列全是「缺」，自相矛盾（DEF-09 同一类：缺输入时走最省事分支）。
    no_sample = not calls
    if no_sample and not args.allow_empty:
        failures.append(
            "时间窗内没有技能调用记录：需先跑一次技能调用（绑定 MCP 工具的技能提问一次）"
        )

    # 逐条核对七列，任一条完整即可判定通过；同时记录整体完整率。
    complete_rows = 0
    for row in calls:
        missing = [zh for key, zh in SEVEN_COLUMNS if _blank(row.get(key))]
        if not missing:
            complete_rows += 1
        else:
            failures.append(f"调用 #{row.get('id')} 缺列：{'、'.join(missing)}")
    if calls and complete_rows == 0:
        failures.append("没有任何一条调用记录七列齐备")

    # 拒绝尝试也要有记录（失败尝试同样留痕），只在完整回查模式下要求。
    if not rejections and not args.allow_empty:
        failures.append("audit_events 为空：被拒绝的请求未留痕（重放一次越权请求后重跑）")

    # 关联键断言：有用户名的记录必须有 user_id。
    #
    # 这条断言来自一次真实缺陷：``_actor_snapshot`` 曾取 ``user["id"]``，而会话上下文
    # 返回的键是 ``user_id``，KeyError 被吞掉后 ``actor_id`` 恒为 NULL。用户名照常有值，
    # 表格看上去「七列齐备」，但审计与 users 表的关联键断了——只能按名字模糊匹配，
    # 用户改名或多班同名就无法定位到人。只查「列在不在」抓不到这种空值，必须查取值。
    orphan_actors = [
        r for r in rejections if not _blank(r.get("actor")) and r.get("actor_id") is None
    ]
    if orphan_actors:
        failures.append(
            f"{len(orphan_actors)} 条拒绝记录有用户名但 actor_id 为空："
            f"#{'、#'.join(str(r.get('id')) for r in orphan_actors[:5])}"
        )

    lines: list[str] = []
    lines.append("# 审计日志回查（SEC-07）")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 数据库：`{_display_path(db_path)}`")
    lines.append(f"- 时间窗：{window_label}")
    lines.append(f"- 技能调用记录：{len(calls)} 条，七列齐备 {complete_rows} 条")
    if calls:
        age = _age_hint(calls[0].get("created_at"))
        lines.append(f"- 最近一条调用：`{calls[0].get('created_at')}`（距今 {age}）")
    lines.append(f"- 拒绝尝试记录：{len(rejections)} 条")
    lines.append(
        "- 关联键断言："
        + ("通过（有用户名的记录均带 actor_id）" if not orphan_actors
           else f"未通过（{len(orphan_actors)} 条 actor_id 为空）")
    )
    if migrated_from:
        after = _columns(conn, "mcp_tool_calls")
        added = sorted(after - migrated_from)
        if added:
            lines.append(f"- 老库迁移：本次补列 {'、'.join(added)}")
    lines.append(
        "- 表结构断言：" + ("通过（七列齐备）" if not schema_problems else "未通过：" + "、".join(schema_problems))
    )
    lines.append("")
    lines.append("## 七列断言")
    lines.append("")
    lines.append("| 列 | 含义 | 首条记录取值 | 判定 |")
    lines.append("| --- | --- | --- | --- |")
    head = calls[0] if calls else {}
    for key, zh in SEVEN_COLUMNS:
        value = head.get(key)
        if no_sample:
            lines.append(f"| `{key}` | {zh} | — | —（无样本） |")
            continue
        verdict = "缺" if _blank(value) else "有"
        lines.append(f"| `{key}` | {zh} | `{value}` | {verdict} |")
    lines.append("")
    lines.append("## 回查原文（技能调用）")
    lines.append("")
    if calls:
        lines.append("```json")
        lines.append(json.dumps(calls[:5], ensure_ascii=False, indent=2))
        lines.append("```")
    else:
        lines.append("_无记录_")
    lines.append("")
    lines.append("## 回查原文（被拒绝的尝试）")
    lines.append("")
    if rejections:
        lines.append("```json")
        lines.append(json.dumps(rejections[:8], ensure_ascii=False, indent=2))
        lines.append("```")
    else:
        lines.append("_无记录_")
    lines.append("")
    lines.append("## 判定")
    lines.append("")
    if failures:
        lines.append("**红**：")
        lines.append("")
        for item in failures:
            lines.append(f"- {item}")
    elif no_sample:
        lines.append("**跳过（无样本）**：时间窗内没有技能调用记录，本轮未验证七列齐备。")
        lines.append("")
        lines.append(
            "门禁为干净环境放行（`--allow-empty`），但这一项**不构成证据**，不得据此判绿。"
        )
    else:
        lines.append("**绿**：七列齐备，拒绝尝试有留痕，按技能标识加时间窗可回查。")

    out = Path(args.out)
    # 无样本且放行时不写文件：干净环境跑一次门禁，不该把上一次真实回查的证据
    # 覆盖成一份「什么都没验」的空表——那等于用一次空跑销毁掉有数据的记录。
    skipped_write = no_sample and not failures
    if not skipped_write:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines[:14]))
    if skipped_write:
        print(f"\n未写入 {out}（保留上一份有数据的记录）")
        print("判定：跳过（无样本）— 时间窗内无技能调用，本轮不构成证据")
        # 75 = 约定的「跳过」码：不是红（干净环境本来就还没有调用），但也不是绿——
        # 门禁汇总表要能把它显示成「跳过」，不能和「通过」混在一行里。
        return SKIP_CODE
    print(f"\n已写入 {out}")
    if failures:
        print("判定：红 — " + "；".join(failures), file=sys.stderr)
        return 1
    print("判定：绿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
