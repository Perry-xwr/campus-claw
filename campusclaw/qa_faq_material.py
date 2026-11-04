"""把本班已发布 FAQ 汇总成一份真实材料，复用既有索引流水线。

检索层强绑 ``materials``（``knowledge_chunks.material_id`` 非空外键、
``material_index`` 一材料一条、Qdrant payload 带 material_id、引用链接固定
``/api/materials/{id}``），FAQ 不是材料，无法直接插进检索。这里选择成本最低、
且不改检索代码的一条路：**把 FAQ 汇总写成一份真实的 ``.md`` 材料**。

要点：

- 文件必须真的写。``GET /api/materials/{id}/file`` 会读文件，缺文件会 500，
  材料列表也会出现幽灵条目。
- ``knowledge_entries.material_id`` 是 UNIQUE，后续变更只能 ``UPDATE``，
  不能重复 ``INSERT``。
- 重建失败不影响 FAQ 本身的读写：调用方吞掉异常并记日志，下次变更重试。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from campusclaw import db as dbmod
from campusclaw import qa_db, retrieval_db, storage
from campusclaw.config import Settings
from campusclaw.timeutil import now_iso

logger = logging.getLogger(__name__)

FAQ_MATERIAL_TITLE = "本班 FAQ 汇总（自动生成）"
FAQ_MATERIAL_FILENAME = "faq.md"
EMPTY_NOTICE = "本班当前没有已发布的 FAQ。"


def render(faqs: list[dict[str, Any]]) -> str:
    """渲染汇总正文。按 ``hierarchy`` 策略切分时，每条 FAQ 落成一个可引用切片。"""
    lines = ["# 本班 FAQ 汇总", "", "以下内容由教师确认后沉淀，可作为答疑依据。", ""]
    if not faqs:
        lines.append(EMPTY_NOTICE)
        return "\n".join(lines) + "\n"
    for index, faq in enumerate(faqs, 1):
        question = (faq.get("question_text") or "").strip().splitlines()
        title = question[0] if question else f"FAQ {index}"
        lines.append(f"## {title}")
        lines.append("")
        lines.append((faq.get("question_text") or "").strip())
        lines.append("")
        lines.append("答：" + (faq.get("answer_text") or "").strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _active_material(conn: sqlite3.Connection, material_id: int, class_id: int):
    return conn.execute(
        "SELECT * FROM materials WHERE id = ? AND class_id = ? AND status = 'active'",
        (material_id, class_id),
    ).fetchone()


def _create_material(
    conn: sqlite3.Connection, settings: Settings, class_id: int, teacher_id: int, text: str
) -> int:
    storage_key = storage.new_storage_key("md")
    stamp = now_iso()
    with dbmod.transaction(conn):
        cursor = conn.execute(
            "INSERT INTO materials(class_id, uploaded_by, title, original_filename, "
            "storage_key, size_bytes, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
            (
                class_id,
                teacher_id,
                FAQ_MATERIAL_TITLE,
                FAQ_MATERIAL_FILENAME,
                storage_key,
                len(text.encode("utf-8")),
                stamp,
                stamp,
            ),
        )
        material_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO knowledge_entries(material_id, class_id, body_text, created_at) "
            "VALUES (?, ?, ?, ?)",
            (material_id, class_id, text, stamp),
        )
    return material_id


def _update_material(
    conn: sqlite3.Connection, material_id: int, class_id: int, text: str
) -> None:
    stamp = now_iso()
    with dbmod.transaction(conn):
        conn.execute(
            "UPDATE materials SET size_bytes = ?, updated_at = ?, deleted_at = NULL, "
            "status = 'active' WHERE id = ? AND class_id = ?",
            (len(text.encode("utf-8")), stamp, material_id, class_id),
        )
        updated = conn.execute(
            "UPDATE knowledge_entries SET body_text = ? WHERE material_id = ? AND class_id = ?",
            (text, material_id, class_id),
        )
        if updated.rowcount == 0:
            conn.execute(
                "INSERT INTO knowledge_entries(material_id, class_id, body_text, created_at) "
                "VALUES (?, ?, ?, ?)",
                (material_id, class_id, text, stamp),
            )


def _write_file(settings: Settings, class_id: int, storage_key: str, text: str) -> Path:
    target = storage.material_file_path(settings.upload_dir, class_id, storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    # 显式 newline=""：Windows 默认把 \n 转成 \r\n，会让文件内容与
    # knowledge_entries.body_text 不一致，切片位置随之偏移。
    target.write_text(text, encoding="utf-8", newline="")
    return target


def rebuild(
    conn: sqlite3.Connection, settings: Settings, class_id: int, teacher_id: int
) -> int | None:
    """重建本班 FAQ 汇总材料并触发索引重建；返回材料编号。

    任何失败都被记日志并返回 None，不向上抛：FAQ 的发布/编辑/撤销不应因为
    索引侧问题而失败。
    """
    try:
        faqs = qa_db.class_published_faqs(conn, class_id)
        text = render(faqs)
        material_id = qa_db.faq_material_id(conn, class_id)
        material = _active_material(conn, material_id, class_id) if material_id else None

        if material is None:
            material_id = _create_material(conn, settings, class_id, teacher_id, text)
            qa_db.set_faq_material_id(conn, class_id, material_id)
            storage_key = conn.execute(
                "SELECT storage_key FROM materials WHERE id = ?", (material_id,)
            ).fetchone()["storage_key"]
        else:
            material_id = int(material["id"])
            storage_key = material["storage_key"]
            _update_material(conn, material_id, class_id, text)

        _write_file(settings, class_id, storage_key, text)
        retrieval_db.enqueue(conn, material_id, {"strategy": "hierarchy"})
        return material_id
    except Exception:
        logger.exception("rebuild FAQ material failed for class %s", class_id)
        return None
