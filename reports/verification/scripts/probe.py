"""探测脚本：确认关键接口的真实响应结构（用于设计断言）。"""
import json
import os
import urllib.error
import urllib.request

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

BASE = "http://127.0.0.1:8097"


def call(method, path, body=None, token=None, raw=False):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8")
            return r.status, text
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def show(label, status, text, limit=600):
    print(f"\n### {label} -> {status}")
    print(text[:limit])


st, body = call("POST", "/api/login", {"username": "teacher_a", "password": "TeacherA#2026"})
show("login teacher_a", st, body)
token = json.loads(body).get("token") if st == 200 else None
print("token:", (token or "")[:20], "...")

st, body = call("GET", "/api/me", token=token)
show("me", st, body)

st, body = call("GET", "/api/materials", token=token)
show("materials", st, body)

st, body = call("POST", "/api/search", {"query": "示例讲义", "mode": "keyword", "limit": 5}, token=token)
show("search keyword", st, body, 900)

st, body = call("POST", "/api/search", {"query": "示例讲义", "mode": "vector", "limit": 5}, token=token)
show("search vector(no embedding)", st, body)

st, body = call("GET", "/api/qa/stats", token=token)
show("qa stats", st, body)

st, body = call("GET", "/api/mcp/servers", token=token)
show("mcp servers", st, body)

st, body = call("GET", "/api/tasks/observations", token=token)
show("task observations", st, body)

st, body = call("GET", "/openapi.json")
doc = json.loads(body) if st == 200 else {}
print(f"\n### openapi -> {st}, paths={len(doc.get('paths', {}))}, title={doc.get('info', {}).get('title')}")

# 未登录
st, body = call("GET", "/api/materials")
show("materials(anon)", st, body)
