import json
import os
import statistics
import time
import urllib.request

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)

B = "http://127.0.0.1:8097"


def timed(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(B + path, data=data, headers=headers, method=method)
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
        status = resp.status
    return status, (time.perf_counter() - start) * 1000


payload = json.loads(
    urllib.request.urlopen(urllib.request.Request(
        B + "/api/login", data=json.dumps({"username": "teacher_a",
                                           "password": "TeacherA#2026"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST"), timeout=30
    ).read().decode())
token = payload["token"]

cases = {
    "GET /health": ("GET", "/health", None),
    "GET /api/materials": ("GET", "/api/materials", None),
    "POST /api/search(keyword)": ("POST", "/api/search",
                                  {"query": "示例讲义", "mode": "keyword", "limit": 5}),
    "POST /api/qa/questions(列表)": ("GET", "/api/qa/questions", None),
    "GET /api/tasks/observations": ("GET", "/api/tasks/observations", None),
}

print(f"{'接口':<32}{'样本':<6}{'均值ms':<10}{'P95ms':<10}{'最大ms':<10}")
summary = {}
for name, (method, path, body) in cases.items():
    samples = []
    for _ in range(15):
        status, ms = timed(method, path, body, token)
        samples.append(ms)
    samples.sort()
    p95 = samples[int(0.95 * (len(samples) - 1))]
    summary[name] = {"mean_ms": round(statistics.mean(samples), 2),
                     "p95_ms": round(p95, 2), "max_ms": round(max(samples), 2),
                     "status": status}
    print(f"{name:<32}{len(samples):<6}{statistics.mean(samples):<10.2f}{p95:<10.2f}{max(samples):<10.2f}")

with open("D:/campus-claw/.verify/perf.json", "w", encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=2)
print("\n已写入 .verify/perf.json")
