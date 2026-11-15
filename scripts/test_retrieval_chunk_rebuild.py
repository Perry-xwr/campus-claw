"""隔离验证 Chunk 策略提交、无 Embedding 关键词重建与页面回显。"""

from __future__ import annotations

import json
import gc
import os
import re
import subprocess
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from campusclaw import create_app, db as dbmod, retrieval, retrieval_db
from campusclaw.chunking import split_body
from campusclaw.index_worker import process_one
from campusclaw.retrieval_config import RetrievalConfig


BODY = "\n\n".join(
    [
        "# Linux 命令\nLinux 常用命令与文件权限。 quasar container permissions。 "
        + "命令说明和课堂检索内容。 " * 28,
        "## Docker 容器\nDocker 容器隔离进程与网络。 " + "Docker image container。 " * 24,
        "## Python 服务\nPython 应用使用虚拟环境。 " + "Python interpreter package。 " * 20,
    ]
)


class ChunkRebuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="campusclaw-chunks-")
        cls.app = create_app(env={"CAMPUSCLAW_HOME": cls.tmp.name})
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()
        login = cls.client.post(
            "/api/login", json={"username": "teacher_a", "password": "TeacherA#2026"}
        )
        cls.teacher_a = login.get_json()["token"]
        login_b = cls.client.post(
            "/api/login", json={"username": "student_b1", "password": "StudentB1#2026"}
        )
        cls.student_b = login_b.get_json()["token"]
        cls.headers = {"Authorization": f"Bearer {cls.teacher_a}"}
        cls.conn = dbmod.connect(cls.app.extensions["campusclaw"]["settings"].db_path)
        cls.config = RetrievalConfig.from_env()
        if cls.config.embedding_ready:
            raise AssertionError("测试环境意外检测到 Embedding 配置；拒绝执行外部请求测试")
        # 仅排空临时数据库中的预置队列；正式数据库/Worker 不参与。
        while process_one(cls.conn, cls.config):
            pass

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()
        cls.client = None
        cls.app = None
        gc.collect()
        cls.tmp.cleanup()

    def _upload(self) -> int:
        response = self.client.post(
            "/api/materials/upload",
            headers=self.headers,
            data={"file": (BytesIO(BODY.encode("utf-8")), "chunk-fixture.md", "text/markdown")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return int(response.get_json()["material_id"])

    def _reindex(self, material_id: int, payload: dict) -> dict:
        response = self.client.post(
            f"/api/materials/{material_id}/reindex", json=payload, headers=self.headers
        )
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        return response.get_json()

    def _run_worker(self) -> None:
        self.assertTrue(process_one(self.conn, self.config))

    def _page_client(self):
        page_client = self.app.test_client()
        login_page = page_client.get("/login").get_data(as_text=True)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', login_page).group(1)
        page_client.post("/login", data={
            "csrf_token": csrf, "username": "teacher_a", "password": "TeacherA#2026"
        })
        return page_client

    def _chunks(self, material_id: int) -> list:
        state = retrieval_db.index_status(self.conn, material_id)
        return self.conn.execute(
            "SELECT * FROM knowledge_chunks WHERE material_id=? AND generation=? "
            "AND index_status='ready' ORDER BY chunk_index",
            (material_id, state["active_generation"]),
        ).fetchall()

    def test_auto_hierarchy_custom_chunking_and_keyword_search(self) -> None:
        # 固定长文本直接验证 auto 默认 800/80 与可调 auto 的真实边界。
        default_auto = split_body("x" * 2000, {"strategy": "auto"})
        self.assertEqual(
            [(chunk.start, chunk.end) for chunk in default_auto],
            [(0, 800), (720, 1520), (1440, 2000)],
        )
        adjusted_auto = split_body(
            "x" * 1000,
            {"strategy": "auto", "chunk_size": 320, "overlap_ratio": 0.2},
        )
        self.assertEqual(
            [(chunk.start, chunk.end) for chunk in adjusted_auto],
            [(0, 320), (256, 576), (512, 832), (768, 1000)],
        )

        material_id = self._upload()

        # auto 缺省仍是 800/80；无 embedding 也能完成 FTS 索引。
        auto = self._reindex(material_id, {"strategy": "auto"})
        self.assertEqual(auto["status"], "queued")
        self._run_worker()
        state = retrieval_db.index_status(self.conn, material_id)
        self.assertEqual(state["status"], "ready")
        auto_chunks = self._chunks(material_id)
        self.assertGreaterEqual(len(auto_chunks), 1)
        self.assertTrue(all(len(row["chunk_text"]) <= 800 for row in auto_chunks))
        self.assertTrue(all(
            json.loads(row["strategy_json"]) == {
                "strategy": "auto", "chunk_size": 800, "overlap_ratio": 0.1
            } for row in auto_chunks
        ))
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks_fts f JOIN knowledge_chunks c ON c.id=f.rowid "
            "WHERE c.material_id=? AND c.generation=?", (material_id, state["active_generation"])
        ).fetchone()[0], len(auto_chunks))

        # auto 可调整参数但策略身份仍为 auto，设置落入真实切片和活动代次。
        auto_tuned = self._reindex(
            material_id, {"strategy": "auto", "chunk_size": 320, "overlap_ratio": 0.2}
        )
        self._run_worker()
        auto_state = retrieval_db.index_status(self.conn, material_id)
        self.assertEqual(auto_state["active_strategy"], {
            "strategy": "auto", "chunk_size": 320, "overlap_ratio": 0.2
        })
        tuned_auto_chunks = self._chunks(material_id)
        self.assertGreater(len(tuned_auto_chunks), len(auto_chunks))
        self.assertTrue(all(len(row["chunk_text"]) <= 320 for row in tuned_auto_chunks))
        self.assertTrue(all(
            json.loads(row["strategy_json"]) == auto_state["active_strategy"]
            for row in tuned_auto_chunks
        ))
        for row in tuned_auto_chunks:
            self.assertEqual(BODY[int(row["start_offset"]):int(row["end_offset"])], row["chunk_text"])
            self.assertEqual(int(row["end_offset"]) - int(row["start_offset"]), len(row["chunk_text"]))
        self.assertEqual(auto_tuned["strategy"]["strategy"], "auto")

        # 标题策略的边界应保留 Markdown 标题段。
        self._reindex(material_id, {"strategy": "hierarchy"})
        self._run_worker()
        hierarchy = self._chunks(material_id)
        self.assertGreaterEqual(len(hierarchy), 3)
        self.assertTrue(any("## Docker 容器" in row["chunk_text"] for row in hierarchy))

        # 自定义参数要反映到真实 chunks、偏移与 FTS，而不只是状态字段。
        submitted = {"strategy": "custom", "chunk_size": 240, "overlap_ratio": 0.2}
        self._reindex(material_id, submitted)
        pending_state = retrieval_db.index_status(self.conn, material_id)
        old_generation = pending_state["active_generation"]
        self.assertEqual(pending_state["pending"]["strategy"]["chunk_size"], 240)
        self.assertEqual(pending_state["active_generation"], old_generation)
        self._run_worker()
        state = retrieval_db.index_status(self.conn, material_id)
        self.assertEqual(state["status"], "ready")
        self.assertGreater(state["active_generation"], old_generation)
        custom_chunks = self._chunks(material_id)
        self.assertGreater(len(custom_chunks), len(auto_chunks))
        self.assertTrue(all(0 < len(row["chunk_text"]) <= 240 for row in custom_chunks))
        self.assertTrue(all(
            json.loads(row["strategy_json"])["chunk_size"] == 240 for row in custom_chunks
        ))
        print(
            "chunk evidence:",
            {"auto_count": len(auto_chunks), "hierarchy_count": len(hierarchy),
             "custom_count": len(custom_chunks),
             "custom_lengths": [len(row["chunk_text"]) for row in custom_chunks],
             "custom_offsets": [(row["start_offset"], row["end_offset"]) for row in custom_chunks]},
        )
        for row in custom_chunks:
            self.assertEqual(BODY[int(row["start_offset"]):int(row["end_offset"])], row["chunk_text"])
            self.assertEqual(int(row["end_offset"]) - int(row["start_offset"]), len(row["chunk_text"]))
        fts_count = self.conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks_fts f JOIN knowledge_chunks c ON c.id=f.rowid "
            "WHERE c.material_id=? AND c.generation=?", (material_id, state["active_generation"])
        ).fetchone()[0]
        self.assertEqual(fts_count, len(custom_chunks))
        hits = retrieval.keyword_search(self.conn, "quasar container permissions", 1, 5)
        self.assertTrue(any(hit["material_id"] == material_id for hit in hits), hits)
        current_ids = {int(row["id"]) for row in custom_chunks}
        self.assertTrue(all(int(hit["chunk_id"]) in current_ids for hit in hits))
        # 旧代次保留且不可冒充当前活动代次；B 班查询不得看到 A 班切片。
        old_ready = self.conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE material_id=? AND generation=? AND index_status='ready'",
            (material_id, old_generation),
        ).fetchone()[0]
        self.assertGreater(old_ready, 0)
        self.assertEqual(retrieval.keyword_search(self.conn, "quasar container permissions", 2, 5), [])

    def test_saved_configuration_page_echo_and_queue_semantics(self) -> None:
        material_id = self._upload()
        page_client = self._page_client()
        initial_html = page_client.get("/knowledge").get_data(as_text=True)
        size_tag = re.search(r'<input class="input" data-role="size"[^>]*>', initial_html).group(0)
        self.assertIn('value="800"', size_tag)
        self.assertNotIn("disabled", size_tag)

        # auto 的调整值刷新后仍回显，并且请求策略没有被改写为 custom。
        auto_result = self._reindex(
            material_id, {"strategy": "auto", "chunk_size": 360, "overlap_ratio": 0.25}
        )
        self.assertEqual(auto_result["strategy"], {
            "strategy": "auto", "chunk_size": 360, "overlap_ratio": 0.25
        })
        self._run_worker()
        auto_refreshed = page_client.get("/knowledge").get_data(as_text=True)
        self.assertRegex(auto_refreshed, r'<option value="auto" selected>自动切分</option>')
        self.assertRegex(auto_refreshed, r'data-role="size"[^>]*value="360"')
        self.assertRegex(auto_refreshed, r'data-role="overlap"[^>]*value="0.25"')

        first = self._reindex(material_id, {"strategy": "custom", "chunk_size": 240, "overlap_ratio": 0.2})
        second = self._reindex(material_id, {"strategy": "custom", "chunk_size": 300, "overlap_ratio": 0.1})
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertTrue(second["updated_existing"])
        status = self.client.get(f"/api/materials/{material_id}/index-status", headers=self.headers).get_json()
        self.assertEqual(status["pending"]["strategy"]["chunk_size"], 300)
        # Cookie-authenticated page renders the saved pending strategy on first load.
        page = page_client.get("/knowledge")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertRegex(html, rf'<option value="custom" selected>自定义切分</option>')
        self.assertRegex(html, r'data-role="size"[^>]*value="300"')
        size_tag = re.search(r'<input class="input" data-role="size"[^>]*>', html).group(0)
        self.assertNotIn("disabled", size_tag)

        # 旧队列无进展时提示 worker；运行中的任务不接受不同参数并返回 409。
        self.conn.execute("UPDATE index_jobs SET updated_at='2000-01-01T00:00:00+00:00' WHERE id=?", (first["job_id"],))
        stale = self.client.get(f"/api/materials/{material_id}/index-status", headers=self.headers).get_json()
        self.assertTrue(stale["worker_stalled"])
        self.assertIn("python -m campusclaw.index_worker", html)
        self.conn.execute("UPDATE index_jobs SET status='running' WHERE id=?", (first["job_id"],))
        self.conn.execute("UPDATE material_index SET status='running' WHERE material_id=?", (material_id,))
        conflict = self.client.post(
            f"/api/materials/{material_id}/reindex",
            json={"strategy": "custom", "chunk_size": 500, "overlap_ratio": 0.1},
            headers=self.headers,
        )
        self.assertEqual(conflict.status_code, 409, conflict.get_data(as_text=True))
        self.assertEqual(self.conn.execute("SELECT strategy_json FROM index_jobs WHERE id=?", (first["job_id"],)).fetchone()[0], json.dumps({"strategy": "custom", "chunk_size": 300, "overlap_ratio": 0.1, "separator": "blankline", "remove_urls": False, "remove_emails": False, "collapse_whitespace": False}, sort_keys=True))

        # 运行状态是可见的，恢复队列后由 Worker 真实完成该待执行策略。
        self.conn.execute("UPDATE index_jobs SET status='queued',updated_at=? WHERE id=?", (retrieval_db.utc_now(), first["job_id"]))
        self.conn.execute("UPDATE material_index SET status='pending' WHERE material_id=?", (material_id,))
        self._run_worker()
        final = retrieval_db.index_status(self.conn, material_id)
        self.assertEqual(final["status"], "ready")
        self.assertEqual(final["active_strategy"]["chunk_size"], 300)
        page_client.get("/knowledge")  # Reload now reads the active saved strategy.
        refreshed = page_client.get("/knowledge").get_data(as_text=True)
        self.assertRegex(refreshed, r'data-role="size"[^>]*value="300"')

    def test_worker_module_once_consumes_only_isolated_queue(self) -> None:
        material_id = self._upload()
        job = self.conn.execute(
            "SELECT id FROM index_jobs WHERE material_id=? AND status='queued' ORDER BY id DESC LIMIT 1",
            (material_id,),
        ).fetchone()
        self.assertIsNotNone(job)
        settings = self.app.extensions["campusclaw"]["settings"]
        self.conn.close()
        env = os.environ.copy()
        env.update({
            "CAMPUSCLAW_HOME": str(settings.home),
            "CAMPUSCLAW_DATA_DIR": str(settings.data_dir),
            "CAMPUSCLAW_UPLOAD_DIR": str(settings.upload_dir),
            "EMBEDDING_BASE_URL": "",
            "EMBEDDING_MODEL": "",
            "EMBEDDING_API_KEY": "",
        })
        for name in ("QDRANT_URL", "QDRANT_COLLECTION"):
            env.pop(name, None)
        result = subprocess.run(
            [sys.executable, "-m", "campusclaw.index_worker", "--once"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.conn = dbmod.connect(settings.db_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        stored = self.conn.execute("SELECT status,attempts FROM index_jobs WHERE id=?", (job["id"],)).fetchone()
        self.assertEqual((stored["status"], stored["attempts"]), ("done", 1))
        status = retrieval_db.index_status(self.conn, material_id)
        self.assertEqual(status["status"], "ready")
        self.assertGreater(status["active_generation"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
