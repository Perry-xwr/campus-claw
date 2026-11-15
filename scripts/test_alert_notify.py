#!/usr/bin/env python3
"""Isolated SQLite/API and mock-webhook tests for alert_notify."""

from __future__ import annotations

import contextlib
import datetime as dt
import http.server
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from werkzeug.serving import make_server

from alert_notify import NotifyError, run_once, send_webhook
from campusclaw import create_app, db as dbmod
from unittest.mock import patch


class _WebhookHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.messages.append(payload)  # type: ignore[attr-defined]
        self.send_response(self.server.response_status)  # type: ignore[attr-defined]
        self.end_headers()
        self.wfile.write(b"mock")

    def log_message(self, fmt: str, *args: Any) -> None:
        return


class AlertNotifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="campusclaw-alert-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        app = create_app(
            env={"CAMPUSCLAW_HOME": str(self.root / "app"), "SECRET_KEY": "alert-test-only"}
        )
        self.settings = app.extensions["campusclaw"]["settings"]
        self.app_server = make_server("127.0.0.1", 0, app, threaded=True)
        self.app_thread = threading.Thread(target=self.app_server.serve_forever, daemon=True)
        self.app_thread.start()
        self.addCleanup(self._stop_app)
        self.alerts_url = f"http://127.0.0.1:{self.app_server.server_port}/api/health/alerts"

        self.webhook = http.server.HTTPServer(("127.0.0.1", 0), _WebhookHandler)
        self.webhook.messages = []  # type: ignore[attr-defined]
        self.webhook.response_status = 200  # type: ignore[attr-defined]
        self.webhook_thread = threading.Thread(target=self.webhook.serve_forever, daemon=True)
        self.webhook_thread.start()
        self.addCleanup(self._stop_webhook)
        self.webhook_url = f"http://127.0.0.1:{self.webhook.server_port}/hook?token=mock-only"
        self.state_path = self.root / "run" / "notify-state.json"
        self.env = {
            "CAMPUSCLAW_ALERT_WEBHOOK_URL": self.webhook_url,
            "CAMPUSCLAW_ALERTS_URL": self.alerts_url,
            "CAMPUSCLAW_ALERT_STATE_FILE": str(self.state_path),
            "CAMPUSCLAW_ALERT_TIMEOUT_SECONDS": "3",
        }
        self.material_id = self._create_material()

    def _stop_app(self) -> None:
        self.app_server.shutdown()
        self.app_thread.join(timeout=3)
        self.app_server.server_close()

    def _stop_webhook(self) -> None:
        self.webhook.shutdown()
        self.webhook_thread.join(timeout=3)
        self.webhook.server_close()

    def _create_material(self) -> int:
        conn = dbmod.connect(self.settings.db_path)
        try:
            teacher = conn.execute("SELECT id,class_id FROM users WHERE role='teacher' ORDER BY id LIMIT 1").fetchone()
            self.assertIsNotNone(teacher)
            stamp = dt.datetime.now(dt.timezone.utc).isoformat()
            cur = conn.execute(
                "INSERT INTO materials(class_id,uploaded_by,title,original_filename,storage_key,"
                "size_bytes,status,created_at,updated_at) VALUES(?,?,?,?,?,0,'active',?,?)",
                (teacher["class_id"], teacher["id"], "synthetic alert fixture", "fixture.md",
                 "synthetic-alert-fixture", stamp, stamp),
            )
            material_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO material_index(material_id,status,updated_at) VALUES(?,'ready',?)",
                (material_id, stamp),
            )
            conn.commit()
            return material_id
        finally:
            conn.close()

    def _set_failed(self, failed: bool) -> None:
        conn = dbmod.connect(self.settings.db_path)
        try:
            conn.execute(
                "UPDATE material_index SET status=?,updated_at=? WHERE material_id=?",
                ("failed" if failed else "ready", dt.datetime.now(dt.timezone.utc).isoformat(), self.material_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _run(self) -> int:
        return run_once(self.env)

    def test_normal_critical_dedup_and_recovery(self) -> None:
        self.assertEqual(self._run(), 0)
        self.assertEqual(self.webhook.messages, [])

        self._set_failed(True)
        self.assertEqual(self._run(), 0)
        self.assertEqual(len(self.webhook.messages), 1)
        event = self.webhook.messages[-1]
        self.assertEqual(event["event"], "critical")
        self.assertEqual(event["alerts"][0]["type"], "index_failed")
        self.assertIn("教学材料索引失败", event["summary"])
        dt.datetime.fromisoformat(event["detected_at"])
        self.assertNotIn("mock-only", json.dumps(event))
        self.assertNotIn("synthetic alert fixture", json.dumps(event))

        self.assertEqual(self._run(), 0)
        self.assertEqual(len(self.webhook.messages), 1)

        self._set_failed(False)
        self.assertEqual(self._run(), 0)
        self.assertEqual(len(self.webhook.messages), 2)
        self.assertEqual(self.webhook.messages[-1]["event"], "recovered")
        self.assertEqual(json.loads(self.state_path.read_text(encoding="utf-8"))["critical_ids"], [])

    def test_delivery_errors_keep_state_for_retry(self) -> None:
        self._set_failed(True)
        self.webhook.response_status = 503  # type: ignore[attr-defined]
        with self.assertRaisesRegex(NotifyError, "webhook returned HTTP 503"):
            self._run()
        self.assertFalse(self.state_path.exists())

        self.webhook.response_status = 200  # type: ignore[attr-defined]
        self.assertEqual(self._run(), 0)
        self.assertEqual(json.loads(self.state_path.read_text(encoding="utf-8"))["critical_ids"], ["index_failed"])

    def test_connection_failure_is_reported_without_state_change(self) -> None:
        self._set_failed(True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            unused_port = sock.getsockname()[1]
        env = dict(self.env, CAMPUSCLAW_ALERT_WEBHOOK_URL=f"http://127.0.0.1:{unused_port}/hook")
        with self.assertRaisesRegex(NotifyError, "webhook connection failed"):
            run_once(env)
        self.assertFalse(self.state_path.exists())

    def test_webhook_timeout_is_reported_without_exposing_url(self) -> None:
        with patch("alert_notify._open", side_effect=socket.timeout()):
            with self.assertRaisesRegex(NotifyError, "webhook delivery timed out") as caught:
                send_webhook(self.webhook_url, {"event": "critical"}, 2)
        self.assertNotIn("mock-only", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
