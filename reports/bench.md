# 压测基线（第 10 课）

> 由 `scripts/bench.py` 生成，原始数据见 `reports/evidence/bench-before-devserver.json`
> 与 `reports/evidence/bench-after.json`。参数：vus=20、时长 60s、同一台机器、
> 同一份数据目录、同一批账号。

## 一、为什么做了两组

第一组用 `python app.py`（Flask 内置开发服务器）跑，第二组用 `waitress`
（生产级 WSGI，16 线程）跑同一份代码。两组之间的差别只有服务器，因此这组
数据回答的是「部署方式对并发能力的影响」，不是「改了哪段业务代码」。

第一组出现大量 `status=0`（连接层失败）。逐项核对后确认**不是服务端错误**：
同机单发与低并发（5 / 10 路）均为 100% 200；原因是 Flask 内置服务器按
HTTP/1.0 应答并回 `Connection: close`，客户端无法保持长连接，20 路并发持续
60 秒会产生大量短连接，Windows 动态端口被 TIME_WAIT 占满，连接建立失败。
换成支持 keep-alive 的 waitress 后归零——这本身就是一个可交付的结论：
**开发服务器不能作为性能结论的依据，也不能承担演示压力。**

## 二、对照数据

### 第一组：Flask 内置开发服务器（`python app.py`）

| 端点 | 请求数 | RPS | P50 (ms) | P95 (ms) | P99 (ms) | 错误 | 错误率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `GET /health` | 10151 | 168.9 | 117.34 | 125.84 | 135.14 | 0 | 0.00% |
| `GET /api/materials` | 8152 | 135.6 | 112.60 | 292.43 | 320.38 | 2015 | 24.72% |
| `POST /api/search` | 9418 | 156.7 | 124.98 | 142.91 | 158.06 | 4 | 0.04% |
| `GET /api/conversations` | 8671 | 144.3 | 109.40 | 273.01 | 347.75 | 1808 | 20.85% |

### 第二组：waitress 16 线程（生产级 WSGI）

| 端点 | 请求数 | RPS | P50 (ms) | P95 (ms) | P99 (ms) | 错误 | 错误率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `GET /health` | 22799 | 379.8 | 52.47 | 62.60 | 67.95 | 0 | 0.00% |
| `GET /api/materials` | 33125 | 551.8 | 36.15 | 38.81 | 48.19 | 0 | 0.00% |
| `POST /api/search` | 30754 | 512.3 | 38.71 | 46.51 | 50.51 | 0 | 0.00% |
| `GET /api/conversations` | 33128 | 551.9 | 36.13 | 39.22 | 48.78 | 0 | 0.00% |

### 差别汇总

| 指标 | 开发服务器 | waitress | 变化 |
| --- | ---: | ---: | --- |
| 吞吐（RPS，四端点均值） | 151.4 | 498.9 | ×3.3 |
| P95（四端点均值） | 208.5 ms | 46.8 ms | −77.5% |
| 错误率（四端点均值） | 11.4% | 0% | 归零 |

## 三、复跑命令

```bash
# 1) 生产级服务器（结论以这一组为准）
python -m uv pip install --python .venv/Scripts/python.exe waitress   # 仅压测用，未进依赖
CAMPUSCLAW_HOME=<数据目录> .venv/Scripts/python.exe -c \
  "from waitress import serve; from app import app; serve(app, host='127.0.0.1', port=8102, threads=16)"

# 2) 压测
.venv/Scripts/python.exe scripts/bench.py --base http://127.0.0.1:8102 \
  --vus 20 --duration 60 --out reports/evidence/bench.json --md reports/bench.md
```

## 四、这组数据不能说明什么

- **不能说明生产容量**：单机、单进程、本地回环、数据集只有 2 份材料；真实部署有
  Nginx、多 worker、真实网络延迟与更大数据量。
- **不能说明长稳**：只跑了 60 秒，没有做 30 分钟以上的稳定性与内存观察。
- **不能说明写入路径**：压的全是读接口。写接口涉及 SQLite 写锁与索引任务入队，
  并发写入的表现未测。
- **waitress 未进项目依赖**：它是为这次压测临时装的，生产部署若采用需正式加入
  依赖并写进 Dockerfile，否则「可复现」不成立。

## 五、已知但未做的优化

1. **SQLite 未启用 WAL**（`campusclaw/db.py:125` 只设了外键与 `busy_timeout`）。
   默认的 rollback journal 读写互斥，写请求会阻塞读。压测只测了读，所以这条没有
   暴露；一旦批改任务与检索并发，是第一个该改的点。
2. **`/api/materials` 的 P95 在开发服务器下明显高于其他端点**（292ms vs 143ms），
   说明这个端点的响应体或查询更重；换 waitress 后差距收窄到 8ms 以内，暂不改。
3. 没有做首页/静态资源压测，页面渲染路径未纳入基线。
