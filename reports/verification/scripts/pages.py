# -*- coding: utf-8 -*-
"""页面可用性检查：匿名访问应 302，登录后渲染应 200。"""

from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

def _project_root(start: Path) -> Path:
    """向上找到含 app.py 与 campusclaw/ 的项目根。

    脚本归档到 reports/verification/scripts/ 之后，不能再用固定层级推算，
    否则工作目录与解释器路径都会指错。
    """
    for candidate in [start, *start.parents]:
        if (candidate / "app.py").exists() and (candidate / "campusclaw").is_dir():
            return candidate
    return start


ROOT = _project_root(Path(__file__).resolve().parent)
HOME = ROOT / ".acc" / "appdata"
PORT = 8098
BASE = f"http://127.0.0.1:{PORT}"
PY = Path(sys.executable)  # 用当前解释器：venv 位置因机器而异，不能硬拼

for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
            "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
    os.environ.pop(key, None)

ENV = {**os.environ, "CAMPUSCLAW_HOME": str(HOME), "PORT": str(PORT),
       "MCP_AUTH_TOKEN": "acc-token-2026"}

PAGES = ["/qa", "/qa/faq", "/qa/stats", "/materials", "/tutor", "/swagger/index.html"]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def start():
    log = open(ROOT / ".acc" / "page-check.log", "a", encoding="utf-8")
    proc = subprocess.Popen([str(PY), "app.py"], cwd=str(ROOT), env=ENV,
                            stdout=log, stderr=subprocess.STDOUT)
    for _ in range(90):
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as resp:
                if resp.status == 200:
                    return proc
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise RuntimeError("应用未就绪")


def anon_status(path: str) -> int:
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(BASE + path, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> None:
    proc = start()
    try:
        result = {"anonymous": {}, "authed": {}}
        for page in PAGES:
            result["anonymous"][page] = anon_status(page)
            print(f"匿名 {page:<22} {result['anonymous'][page]}")

        # Cookie 会话登录：先取登录页 CSRF，再提交表单
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        html = opener.open(BASE + "/login", timeout=10).read().decode("utf-8", "replace")
        token = ""
        for marker in ('name="csrf_token"', 'id="csrf-token"'):
            idx = html.find(marker)
            if idx != -1:
                chunk = html[idx: idx + 300]
                for quote in ('"', "'"):
                    if f'value={quote}' in chunk:
                        token = chunk.split(f'value={quote}')[1].split(quote)[0]
                        break
                if token:
                    break
        if not token:
            import re
            match = re.search(r'csrf[^>]{0,80}?content="([^"]+)"', html, re.I)
            token = match.group(1) if match else ""

        body = urllib.parse.urlencode({
            "username": "teacher_a", "password": "TeacherA#2026", "csrf_token": token,
        }).encode()
        opener.open(urllib.request.Request(BASE + "/login", data=body, method="POST"),
                    timeout=10)
        for page in PAGES:
            try:
                with opener.open(BASE + page, timeout=15) as resp:
                    payload = resp.read()
                    result["authed"][page] = (resp.status, len(payload))
            except urllib.error.HTTPError as exc:
                result["authed"][page] = (exc.code, 0)
            print(f"登录 {page:<22} {result['authed'][page]}")

        (ROOT / ".acc" / "pages-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
