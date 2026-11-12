"""apitest 公共设施：隔离实例、身份登录、HTTP 客户端、三段式记录。

设计约定（对齐第 9 课「反例用例」要求）：
- 每个用例模块位于 ``apitest/cases/<接口路径>/<方法>.py``，暴露 ``CASE`` 元信息与 ``run(ctx)``。
- 每条用例返回三段式记录：前置条件 premise / 操作 action / 可观测结果 actual，外加期望 expected 与判定 verdict。
- 用例只读不建：不改产品代码，不触碰项目 ``data/``，实例数据落在 ``apitest/.runtime/``。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(__file__).resolve().parent / ".runtime"

DEMO_ACCOUNTS = {
    "teacher_a": "TeacherA#2026",
    "student_a1": "StudentA1#2026",
    "student_b1": "StudentB1#2026",
    "teacher_b": "TeacherB#2026",
}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _StopRedirect(urllib.request.HTTPRedirectHandler):
    """不跟随重定向：登录的 Set-Cookie 只在 302 那一条响应上，跟丢就查不到 SameSite。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _NoProxy:
    """本机请求一律绕过 HTTP(S)_PROXY，避免企业代理把 127.0.0.1 也转发出去。"""

    def __init__(self, cookiejar: CookieJar | None = None, follow: bool = True):
        handlers = [urllib.request.ProxyHandler({})]
        if cookiejar is not None:
            handlers.append(urllib.request.HTTPCookieProcessor(cookiejar))
        if not follow:
            handlers.append(_StopRedirect())
        self._opener = urllib.request.build_opener(*handlers)

    def send(self, request: urllib.request.Request, timeout: float = 30.0):
        return self._opener.open(request, timeout=timeout)


class Client:
    """Bearer 令牌客户端；传 with_cookies=True 则同时维护 Cookie 会话（用于 CSRF/XSS 检查）。"""

    def __init__(self, base_url: str, with_cookies: bool = False):
        self.base_url = base_url.rstrip("/")
        self.cookies = CookieJar() if with_cookies else None
        self._http = _NoProxy(self.cookies)
        self._http_raw = _NoProxy(self.cookies, follow=False)
        self.token: str | None = None
        self.last_headers: dict[str, str] = {}

    def request(self, method: str, path: str, body=None, token: str | None = None,
                headers: dict | None = None, raw: bytes | None = None,
                follow: bool = True):
        url = self.base_url + path
        data = raw
        hdrs = dict(headers or {})
        if raw is None and body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        auth = token or self.token
        if auth:
            hdrs["Authorization"] = "Bearer " + auth
        request = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        http = self._http if follow else self._http_raw
        try:
            response = http.send(request)
            payload = response.read().decode("utf-8", "replace")
            self.last_headers = dict(response.headers)
            return response.status, payload
        except urllib.error.HTTPError as exc:
            self.last_headers = dict(exc.headers or {})
            return exc.code, exc.read().decode("utf-8", "replace")

    def json(self, method: str, path: str, body=None, token: str | None = None, **kwargs):
        status, text = self.request(method, path, body=body, token=token, **kwargs)
        try:
            return status, json.loads(text or "{}")
        except json.JSONDecodeError:
            return status, {"_raw": text}

    def login(self, username: str, password: str) -> int:
        status, payload = self.json("POST", "/api/login",
                                    {"username": username, "password": password})
        self.token = payload.get("token")
        return status

    def upload(self, filename: str, content: bytes, title: str | None = None,
               token: str | None = None):
        boundary = "----apitest-boundary"
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{filename}\"\r\nContent-Type: text/markdown\r\n\r\n".encode("utf-8"),
            content,
            b"\r\n",
        ]
        if title is not None:
            parts += [
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n".encode("utf-8"),
                title.encode("utf-8"),
                b"\r\n",
            ]
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        return self.json("POST", "/api/materials/upload",
                         raw=b"".join(parts),
                         token=token,
                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def page(self, path: str) -> tuple[int, str]:
        return self.request("GET", path)

    def csrf_token(self, path: str = "/materials") -> str:
        """从服务端渲染的页面里取一次性令牌；登录后令牌会轮换，必须重取。"""
        status, html = self.page(path)
        if status != 200:
            return ""
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        if match:
            return match.group(1)
        match = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
        return match.group(1) if match else ""


# ---------------------------------------------------------------- 实例孵化


class Server:
    """按需启动一个隔离实例：独立 CAMPUSCLAW_HOME、随机端口、跑完即停。"""

    def __init__(self):
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._process: subprocess.Popen | None = None
        self.data_home = RUNTIME / "appdata"
        self.log_path = RUNTIME / "app.log"

    def __enter__(self) -> "Server":
        RUNTIME.mkdir(parents=True, exist_ok=True)
        if self.data_home.exists():
            shutil.rmtree(self.data_home, ignore_errors=True)
        env = dict(os.environ)
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
            env.pop(key, None)
        env.update({
            "CAMPUSCLAW_HOME": str(self.data_home),
            "PORT": str(self.port),
            "MCP_AUTH_TOKEN": "apitest-mcp-demo-token",
        })
        self._process = subprocess.Popen(
            [sys.executable, "app.py"], cwd=str(ROOT), env=env,
            stdout=self.log_path.open("wb"), stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 60
        while time.time() < deadline:
            if self._probe():
                return self
            if self._process.poll() is not None:
                raise RuntimeError(f"实例启动失败，见 {self.log_path}")
            time.sleep(0.4)
        raise RuntimeError(f"实例 60 秒内未就绪，见 {self.log_path}")

    def _probe(self) -> bool:
        try:
            with urllib.request.urlopen(self.base_url + "/health", timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def __exit__(self, *exc_info) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()


class Context:
    """传给用例的上下文：地址 + 预置身份客户端。"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.teacher = Client(base_url)
        self.teacher.login("teacher_a", DEMO_ACCOUNTS["teacher_a"])
        self.student = Client(base_url)
        self.student.login("student_a1", DEMO_ACCOUNTS["student_a1"])
        self.student_b = Client(base_url)
        self.student_b.login("student_b1", DEMO_ACCOUNTS["student_b1"])
        # Cookie 会话客户端：用于 CSRF 与页面渲染检查（Bearer 走不了页面）
        self.teacher_cookie = Client(base_url, with_cookies=True)

    def cookie_login(self, username: str = "teacher_a", password: str | None = None):
        client = self.teacher_cookie
        token = client.csrf_token("/login")
        form = urllib.parse.urlencode({
            "csrf_token": token,
            "username": username,
            "password": password or DEMO_ACCOUNTS[username],
        }).encode("utf-8")
        status, _ = client.request("POST", "/login", raw=form, follow=False,
                                   headers={"Content-Type": "application/x-www-form-urlencoded"})
        return status

    def cookie_client(self, username: str = "teacher_a", password: str | None = None):
        """新建一个已登录的 Cookie 会话客户端（页面渲染检查用，Bearer 进不了页面）。"""
        client = Client(self.base_url, with_cookies=True)
        token = client.csrf_token("/login")
        form = urllib.parse.urlencode({
            "csrf_token": token,
            "username": username,
            "password": password or DEMO_ACCOUNTS[username],
        }).encode("utf-8")
        client.request("POST", "/login", raw=form, follow=False,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
        return client


def record(name: str, premise: str, action: str, expected: str, actual: str,
           ok: bool, kind: str = "反例") -> dict:
    return {
        "name": name,
        "kind": kind,
        "premise": premise,
        "action": action,
        "expected": expected,
        "actual": actual,
        "verdict": "PASS" if ok else "FAIL",
    }
