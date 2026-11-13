"""Durable indexing worker. Run `python -m campusclaw.index_worker --once` or --loop."""

from __future__ import annotations

import argparse
import json
import logging
import time

from qdrant_client import models

from campusclaw import cache, db as dbmod, retrieval_db, tutor_db
from campusclaw.chunking import split_body
from campusclaw.retrieval import embedding_model, fts_tokens, qdrant
from campusclaw.retrieval_config import RetrievalConfig
from campusclaw.config import load_project_dotenv, load_settings

LOG = logging.getLogger(__name__)


def _ensure_collection(client, config: RetrievalConfig, dimension: int) -> None:
    if client.collection_exists(config.collection):
        details = client.get_collection(config.collection)
        vectors = details.config.params.vectors
        existing = vectors.size if hasattr(vectors, "size") else None
        if existing != dimension:
            raise ValueError("Qdrant collection vector dimension differs from embedding model")
        return
    client.create_collection(
        collection_name=config.collection,
        vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
    )
    client.create_payload_index(config.collection, "class_id", models.PayloadSchemaType.INTEGER)


def _claim(conn) -> dict | None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("""
            SELECT j.* FROM index_jobs j
            JOIN materials m ON m.id=j.material_id
            WHERE j.status='queued' AND m.status='active'
            ORDER BY j.id LIMIT 1
        """).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        stamp = retrieval_db.utc_now()
        conn.execute("UPDATE index_jobs SET status='running',attempts=attempts+1,updated_at=? WHERE id=?",
                     (stamp, row["id"]))
        conn.execute("UPDATE material_index SET status='running',updated_at=? WHERE material_id=?",
                     (stamp, row["material_id"]))
        conn.execute("COMMIT")
        return dict(row)
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _mark_failed(conn, job: dict, generation: int | None, reason: str) -> None:
    stamp = retrieval_db.utc_now()
    message = reason[:120]
    conn.execute("BEGIN IMMEDIATE")
    try:
        if generation is not None:
            conn.execute("UPDATE knowledge_chunks SET index_status='failed' WHERE material_id=? AND generation=?",
                         (job["material_id"], generation))
        conn.execute("UPDATE index_jobs SET status='failed',last_error=?,updated_at=? WHERE id=?",
                     (message, stamp, job["id"]))
        conn.execute("UPDATE material_index SET status='failed',last_error=?,updated_at=? WHERE material_id=?",
                     (message, stamp, job["material_id"]))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _delete_points(client, config: RetrievalConfig, ids: list[int]) -> None:
    if ids and client.collection_exists(config.collection):
        client.delete(
            collection_name=config.collection,
            points_selector=models.PointIdsList(points=ids), wait=True,
        )


def _retire_stale(conn, config: RetrievalConfig, client=None) -> int:
    """Remove deleted or inactive generation points, then their SQLite rows."""
    rows = conn.execute("""
        SELECT c.id,c.material_id FROM knowledge_chunks c
        JOIN materials m ON m.id=c.material_id
        LEFT JOIN material_index mi ON mi.material_id=c.material_id
        WHERE m.status='deleted'
           OR (c.index_status='ready' AND mi.active_generation!=c.generation)
           OR (c.index_status='failed' AND mi.status!='running')
           OR (c.index_status='pending' AND NOT EXISTS (
               SELECT 1 FROM index_jobs j WHERE j.material_id=c.material_id
                 AND j.status='running'))
        ORDER BY c.id LIMIT 512
    """).fetchall()
    if not rows:
        return 0
    client = client or qdrant(config)
    ids = [int(row["id"]) for row in rows]
    _delete_points(client, config, ids)
    conn.execute("BEGIN IMMEDIATE")
    try:
        for cid in ids:
            conn.execute("DELETE FROM knowledge_chunks_fts WHERE rowid=?", (cid,))
            conn.execute("DELETE FROM knowledge_chunks WHERE id=?", (cid,))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return len(ids)


def process_one(conn, config: RetrievalConfig, *, embedder_factory=embedding_model,
                client_factory=qdrant) -> bool:
    job = _claim(conn)
    if job is None:
        return False
    generation: int | None = None
    inserted_ids: list[int] = []
    client = None
    try:
        material = conn.execute("""
            SELECT m.id,m.class_id,k.id AS knowledge_entry_id,k.body_text
            FROM materials m JOIN knowledge_entries k ON k.material_id=m.id
            WHERE m.id=? AND m.status='active'
        """, (job["material_id"],)).fetchone()
        if material is None:
            raise ValueError("material is no longer active")
        strategy = json.loads(job["strategy_json"])
        pieces = split_body(material["body_text"], strategy)
        if not pieces:
            raise ValueError("no nonempty chunks")
        generation = int(conn.execute(
            "SELECT COALESCE(MAX(generation),0)+1 FROM knowledge_chunks WHERE material_id=?",
            (job["material_id"],)).fetchone()[0])
        stamp = retrieval_db.utc_now()
        conn.execute("BEGIN IMMEDIATE")
        try:
            for chunk in pieces:
                cursor = conn.execute("""
                    INSERT INTO knowledge_chunks(
                        knowledge_entry_id,material_id,class_id,generation,chunk_index,
                        start_offset,end_offset,offset_basis,strategy_json,chunk_text,index_status,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?)
                """, (
                    material["knowledge_entry_id"], material["id"], material["class_id"],
                    generation, chunk.index, chunk.start, chunk.end, chunk.offset_basis,
                    job["strategy_json"], chunk.text, stamp,
                ))
                inserted_ids.append(int(cursor.lastrowid))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

        embedder = embedder_factory(config)
        client = client_factory(config)
        for offset in range(0, len(pieces), 32):
            batch = pieces[offset:offset + 32]
            vectors = embedder.embed_documents([c.text for c in batch])
            if len(vectors) != len(batch) or not vectors:
                raise ValueError("embedding count mismatch")
            dimension = len(vectors[0])
            if not dimension or any(len(v) != dimension for v in vectors):
                raise ValueError("embedding dimension mismatch")
            _ensure_collection(client, config, dimension)
            points = []
            for position, (chunk, vector) in enumerate(zip(batch, vectors), offset):
                cid = inserted_ids[position]
                points.append(models.PointStruct(
                    id=cid, vector=vector,
                    payload={
                        "class_id": int(material["class_id"]),
                        "material_id": int(material["id"]),
                        "knowledge_entry_id": int(material["knowledge_entry_id"]),
                        "chunk_id": cid, "chunk_index": chunk.index,
                    },
                ))
            client.upsert(config.collection, points=points, wait=True)

        conn.execute("BEGIN IMMEDIATE")
        try:
            # Deleted during embedding: never activate a stale material.
            active = conn.execute("SELECT status FROM materials WHERE id=?",
                                  (material["id"],)).fetchone()
            if active is None or active["status"] != "active":
                raise ValueError("material deleted while indexing")
            for cid, chunk in zip(inserted_ids, pieces):
                conn.execute("INSERT INTO knowledge_chunks_fts(rowid,token_text) VALUES (?,?)",
                             (cid, fts_tokens(chunk.text)))
            conn.execute("UPDATE knowledge_chunks SET index_status='ready' WHERE material_id=? AND generation=?",
                         (material["id"], generation))
            conn.execute("""
                UPDATE material_index SET active_generation=?,status='ready',
                strategy_json=?,last_error=NULL,updated_at=? WHERE material_id=?
            """, (generation, job["strategy_json"], retrieval_db.utc_now(), material["id"]))
            conn.execute("UPDATE index_jobs SET status='done',last_error=NULL,updated_at=? WHERE id=?",
                         (retrieval_db.utc_now(), job["id"]))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        # 切片从 pending 变 ready，同一查询此刻起能多检索到内容，旧缓存必须作废。
        cache.invalidate_class(int(material["class_id"]))
        try:
            _retire_stale(conn, config, client)
        except Exception:
            LOG.warning("Inactive vector cleanup will retry", exc_info=True)
        return True
    except Exception as exc:
        if client is not None and inserted_ids:
            try:
                _delete_points(client, config, inserted_ids)
            except Exception:
                LOG.warning("Failed vectors will be cleaned on a later pass", exc_info=True)
        _mark_failed(conn, job, generation, type(exc).__name__)
        LOG.warning("Index task %s failed: %s", job["id"], type(exc).__name__)
        # DEF-05：失败后立刻补建关键词就绪代次，而不是等下一次 app 启动。
        # 原实现的补建只挂在 create_app 里，容器长时间运行时新上传的材料会一直
        # 检索不到（要重启才自愈）；这里让「向量失败 → 关键词兜底」在同一个进程内闭合。
        try:
            rebuilt = tutor_db.backfill_keyword_ready(conn)
            if rebuilt:
                LOG.info("Keyword fallback rebuilt %s material(s) after failure", rebuilt)
        except Exception:
            LOG.warning("Keyword fallback after failure will retry on next pass", exc_info=True)
        return True


def run(*, once: bool = False, interval: float = 2.0, use_dotenv: bool = True) -> None:
    if use_dotenv:
        load_project_dotenv()  # 与 app 共用同一份项目根 .env
    settings = load_settings()
    config = RetrievalConfig.from_env()
    conn = dbmod.connect(settings.db_path)
    try:
        retrieval_db.ensure_schema(conn)
        conn.execute("UPDATE index_jobs SET status='queued' WHERE status='running'")
        if not once and config.embedding_ready:
            while True:
                try:
                    qdrant(config).get_collections()
                    break
                except Exception:
                    LOG.info("Waiting for Qdrant before claiming index tasks")
                    time.sleep(interval)
        elif not once:
            # 等 Qdrant 只在真要写向量时才有意义。没配 embedding 时向量压根建不出来，
            # 这一等就是个死循环：任务永远不被认领，那条「向量失败 → 重建关键词索引」的
            # 降级路径也就永远轮不到执行。此时直接开始认领，让 process_one 走既有降级。
            LOG.info(
                "Embedding not configured; claiming tasks without waiting for Qdrant "
                "(vector indexing degrades to keyword-only)"
            )
        while True:
            worked = process_one(conn, config)
            try:
                retired = _retire_stale(conn, config)
            except Exception:
                retired = 0
                LOG.debug("Vector cleanup will retry", exc_info=True)
            if once:
                if not worked:
                    break
            elif not worked and not retired:
                time.sleep(interval)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run(once=args.once, use_dotenv=True)
