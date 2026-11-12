# DEF-06 收敛记录：Qdrant 客户端与服务端版本跨度

- 判定时间：2026-11-12
- 结论：**已修**（客户端侧收敛，并把它做成静态门禁的第 11 项）
- 环境：Docker 29.9.3；镜像 `campusclaw:latest`；服务端 `qdrant/qdrant:v1.15.5`

## 1. 问题复现

修前客户端 `qdrant-client==1.19.1`，服务端 `1.15.5`，差 4 个次版本。客户端在建立连接时自己做兼容性判定并告警：

```
/usr/local/lib/python3.11/site-packages/qdrant_client/qdrant_remote.py:284: UserWarning:
Qdrant client version 1.19.1 is incompatible with server version 1.15.5.
Major versions should match and minor version difference must not exceed 1.
Set check_compatibility=False to skip version check.
```

这条不是提示性文字，是客户端按自己的矩阵判定为「不兼容」。另外 `QdrantClient.search()` 在 1.16 已移除，本项目用的是 `query_points()`，所以功能面暂时没崩——但跨 4 个版本后服务端行为无保证。

## 2. 为什么从客户端侧收敛

升服务端镜像这条路的验证条件不具备：`docker manifest inspect qdrant/qdrant:v1.19.1` 返回

```
failed to configure transport: error pinging v2 registry: Get "https://registry-1.docker.io/v2/": Bad Gateway
```

连已存在的 `v1.15.5` 也拉不动。**拿不到验证条件就不动版本**，避免「改完看起来对、其实没验证过」。改从客户端侧降版本，服务端镜像 tag 不动，不触发向量数据迁移。

改前先查两个版本在 OSV 上的已知漏洞，确认降版本不会换回漏洞：

| 版本 | OSV 命中 |
| --- | --- |
| qdrant-client 1.15.1 | 0 |
| qdrant-client 1.19.1 | 0 |

## 3. 改动

| 文件 | 改动 |
| --- | --- |
| `requirements.txt` | `qdrant-client==1.19.1` → `==1.15.1`（附注释说明与服务端同次版本） |
| `pyproject.toml` | 同上，并注明由 `check_compose.py` 的 `qdrant.version` 静态把关 |
| `uv.lock` | `uv lock` 重解析，仅 `qdrant-client` 一条变动（含 wheel hash） |
| `scripts/check_compose.py` | 新增第 11 项 `qdrant.version` |

锁文件一致性（CI 走 `uv sync --locked`，锁不同步会直接失败）：

```
$ uv lock --check
Resolved 75 packages in 1ms        # 退出码 0

$ uv sync --locked --dry-run
 - qdrant-client==1.19.1
 + qdrant-client==1.15.1
SYNC_EXIT=0
```

## 4. 修后验证

在 `campusclaw-app` 容器内，把 `UserWarning` 提升为异常（最严格口径），再跑一次完整往返：

```
client 1.15.1
server 1.15.5
ROUNDTRIP_OK_NO_WARNING
```

往返覆盖的调用面，正是 `campusclaw/retrieval.py` 与 `campusclaw/index_worker.py` 实际用到的那些：

| 步骤 | 对应生产代码 | 结果 |
| --- | --- | --- |
| `create_collection` + `VectorParams` | `index_worker.ensure_collection` | 通过 |
| `create_payload_index(class_id, INTEGER)` | `index_worker` 建索引 | 通过 |
| `upsert` 2 个点（`PointStruct`） | 索引任务写入 | 通过 |
| `query_points` + `FieldCondition(class_id=7)` + `score_threshold` | `retrieval.vector_search` | 命中 1 点（共 2 点），score 1.0 |
| `delete(PointIdsList)` | 重建索引时清理 | 通过，计数 1 |
| `delete_collection` | 测试清理 | 通过 |

`warnings.simplefilter("error", UserWarning)` 期间实例化客户端未抛异常，即兼容性告警消失。

## 5. 加的一道闸：`qdrant.version`

只改版本号不够——下次任一侧单独升级，同样的问题会以「运行期才告警」的形式回来。把判据写进静态校验，口径与客户端自身一致（主版本相同、次版本差 ≤1）：

```python
gap = abs(cli[1] - srv[1])
gap_ok = cli[0] == srv[0] and gap <= 1
```

红绿（红侧用临时副本改回 1.19.1，不动工作文件）：

| 侧 | 输入 | 该项判定 | 退出码 |
| --- | --- | --- | --- |
| 红 | `qdrant-client==1.19.1` | 未通过：客户端 1.19.1；服务端 1.15.5，次版本相差 4（要求 ≤1） | 1 |
| 绿 | `qdrant-client==1.15.1` | 通过：客户端 1.15.1；服务端 1.15.5 | 0 |

## 6. 全量门禁

宿主机（`scripts/check-all.ps1`，六项）：全部通过，apitest 20/20，静态校验 11/11。

容器内（`docker exec campusclaw-app`）：

| 项 | 退出码 | 说明 |
| --- | --- | --- |
| security | 0 | — |
| async | 0 | — |
| apitest | 2 | 不适用：`apitest/` 未进运行时镜像（镜像只含 `campusclaw/` 与 `mcp_server`） |
| audit | 0 | — |
| observe | 0 | — |
| compose | 1 | 不适用：`docker-compose.yml` / `Dockerfile` / `requirements.txt` 未进镜像，`compose.exists`、`compose.name` 判红 |

容器内可跑的 4 项全绿；`apitest` 与 `compose` 针对的是仓库，不是运行时镜像，属**不适用**而非通过。二者在宿主机的结论见上。
