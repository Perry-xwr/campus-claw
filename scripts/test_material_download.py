"""隔离回归测试：材料下载的 Unicode 文件名、内容与访问控制。"""

from __future__ import annotations

import tempfile
import sys
import unittest
from io import BytesIO
from pathlib import Path

from werkzeug.http import parse_options_header

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from campusclaw import create_app


class MaterialDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_home = tempfile.TemporaryDirectory(prefix="campusclaw-download-")
        cls.app = create_app(env={"CAMPUSCLAW_HOME": cls._temporary_home.name})
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()
        cls.teacher_a = cls._login("teacher_a", "TeacherA#2026")
        cls.teacher_b = cls._login("teacher_b", "TeacherB#2026")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary_home.cleanup()

    @classmethod
    def _login(cls, username: str, password: str) -> str:
        response = cls.client.post(
            "/api/login", json={"username": username, "password": password}
        )
        if response.status_code != 200:
            raise AssertionError(f"isolated test login failed: {username}")
        return response.get_json()["token"]

    def _upload(self, filename: str, content: bytes, token: str) -> int:
        response = self.client.post(
            "/api/materials/upload",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (BytesIO(content), filename, "text/markdown")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        return response.get_json()["material_id"]

    def test_chinese_and_english_filenames_download_exact_bytes(self) -> None:
        for filename in ("Docker 中文讲义.md", "docker-notes.md"):
            with self.subTest(filename=filename):
                content = f"# {filename}\n内容保持逐字节一致。\n".encode("utf-8")
                material_id = self._upload(filename, content, self.teacher_a)

                response = self.client.get(
                    f"/api/materials/{material_id}/file",
                    headers={"Authorization": f"Bearer {self.teacher_a}"},
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, content)
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                disposition, parameters = parse_options_header(
                    response.headers["Content-Disposition"]
                )
                self.assertEqual(disposition, "attachment")
                self.assertEqual(parameters.get("filename"), filename)

    def test_download_requires_authentication(self) -> None:
        material_id = self._upload("private.md", b"private", self.teacher_a)
        response = self.client.get(f"/api/materials/{material_id}/file")
        self.assertEqual(response.status_code, 401)

    def test_cross_class_and_missing_material_return_404(self) -> None:
        material_id = self._upload("class-a.md", b"class A", self.teacher_a)
        cross_class = self.client.get(
            f"/api/materials/{material_id}/file",
            headers={"Authorization": f"Bearer {self.teacher_b}"},
        )
        missing = self.client.get(
            "/api/materials/999999/file",
            headers={"Authorization": f"Bearer {self.teacher_a}"},
        )
        self.assertEqual(cross_class.status_code, 404)
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
