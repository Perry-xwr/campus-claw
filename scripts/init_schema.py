"""在空库上建出完整表结构，让门禁里的结构断言有对象可查。

为什么需要这个脚本
------------------
仓库的 ``.gitignore`` 排除了 ``data/`` 与 ``*.db``，因此干净 runner 上
**没有数据库**。此时：

* ``audit_recheck.py --allow-empty`` 在库不存在时直接 ``return 0``，
  ``assert_schema()`` 一条断言都没跑；
* ``check_observe.py`` 同样 ``return 0``。

两个步骤在 CI 上显示为绿色，但实际是空转。这个脚本先按应用启动时的
同一套 ``apply_schema`` + 各模块 ``ensure_schema`` 建出结构，那两步才
真正有检查对象。

它只建结构、不灌数据：CI 里没有运产生成的调用记录，数据侧的判定仍由
本地实跑覆盖，报告里单独说明。

用法：
    python scripts/init_schema.py [--db data/app.db]

退出码：建表后必需表仍缺失即 1。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="建立门禁所需的数据库结构")
    parser.add_argument("--db", default="data/app.db", help="目标库路径")
    args = parser.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    from campusclaw import audit_db, db as dbmod, mcp_db, qa_db, retrieval_db
    from campusclaw import task_db, tutor_db

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        dbmod.apply_schema(conn)
        # 以下 ensure_schema 都是幂等的增量迁移（加列 / 建扩展表），
        # 与应用启动时走的完全一致，避免门禁看到的结构与线上不同。
        for module in (audit_db, mcp_db, qa_db, retrieval_db, task_db, tutor_db):
            module.ensure_schema(conn)
        conn.commit()

        missing = dbmod.missing_tables(conn)
        tables = sorted(dbmod.existing_tables(conn))
        cols = [str(r[1]) for r in conn.execute("PRAGMA table_info(mcp_tool_calls)")]
    finally:
        conn.close()

    print(f"数据库：{db_path}")
    print(f"表数量：{len(tables)}")
    print(f"mcp_tool_calls 列（{len(cols)}）：{'、'.join(cols)}")

    if missing:
        print("缺少必需表：" + "、".join(missing), file=sys.stderr)
        return 1

    print("必需表齐备")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
