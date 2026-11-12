# 换目录启动复现 · 第 10 课 · 环境可复现

> 课件第 10 课判据原文：**干净目录执行 `docker compose up -d`**，三服务健康检查全过
> （`docker compose ps`），`make check` 退出码 0。证据文件名固定为
> `reports/boot-reproduce.md`，判定口径是「**无需口头补充任何步骤**」。
>
> 本次实测时间：2026-11-12 23:09–23:20，实跑记录如下，**含一个未达标项**。

## 一、怎么造出「干净目录」

不用拷贝当前工作区（那样会把 `.venv`、`.env`、`data/`、`uploads/` 一起带走，
等于什么都没验证），而是只导出**仓库里有的东西**：

```bash
git archive HEAD | tar -x -C D:/bootrepro
```

导出后确认新目录的起点：

| 项 | 原目录 `D:/campus-claw` | 新目录 `D:/bootrepro` |
| --- | --- | --- |
| `.env`（含 `MCP_AUTH_TOKEN`） | 有（3543 字节，被 `.gitignore` 排除） | **无** |
| `data/`（含 `app.db` 与演示数据） | 有 | **无** |
| `.venv/` | 有 | **无** |
| 代码 | HEAD | HEAD（同一提交） |

这份差异正是「换机器」的真实起点。

## 二、第一次启动：三个服务起来，第四个退出

```bash
cd D:/bootrepro
docker compose up -d
```

`docker compose ps` 实测输出：

| 服务 | 状态 |
| --- | --- |
| `campusclaw-app` | **Up (healthy)**，`0.0.0.0:8080->8080/tcp` |
| `campusclaw-qdrant-1` | Up，`127.0.0.1:6333->6333/tcp` |
| `campusclaw-worker-1` | Up |
| `campusclaw-mcp-1` | **Exited (2)** |

mcp 退出原因（`docker logs campusclaw-mcp-1`）：

```
启动失败：缺少环境变量 MCP_AUTH_TOKEN。
请先设置非空白的 Bearer 令牌后再启动，例如：
    MCP_AUTH_TOKEN=<你的令牌> python -m mcp_server
```

这是**设计使然，不是崩溃**：mcp 服务缺令牌时 fail-closed，拒绝以无鉴权状态启动。
但它同时暴露了一个真实的可复现性缺口——

**`MCP_AUTH_TOKEN` 只存在于 `.env`，而 `.env` 被 `.gitignore` 排除；`.env.example`
第 68 行的 `MCP_AUTH_TOKEN=` 是空值。而当时的 `README.md` 从头到尾没有提到
`cp .env.example .env` 这一步。**

结论：严格按「无需口头补充任何步骤」判定，**这条不成立**——拿到仓库的人照着
README 走，第四个服务必然停在 `Exited (2)`，且不知道原因。

## 三、补上那一步之后：四个服务全起

```bash
cp .env.example .env      # 填一个非空 MCP_AUTH_TOKEN
docker compose up -d
```

`docker compose ps`：

| 服务 | 状态 |
| --- | --- |
| `campusclaw-app` | Up (healthy) |
| `campusclaw-mcp-1` | **Up**，`127.0.0.1:8090->8090/tcp` |
| `campusclaw-qdrant-1` | Up |
| `campusclaw-worker-1` | Up |

健康检查与首次初始化：

| 检查 | 实测 |
| --- | --- |
| `curl http://localhost:8080/health` | `{"status":"ok"}` |
| `data/` 是否自动创建 | 是，`app.db` **319,488 字节**（与原目录同尺寸，说明是同一套 schema 初始化） |
| `uploads/` 是否自动创建 | 是（空目录） |
| 预置账号登录 | `teacher_a` / `TeacherA#2026` → **HTTP 200，落点 `/materials`** |

也就是说：**只要补上 `.env` 这一步，新目录不需要任何口头补充就能跑起来并登录。**

## 四、`make check`：本轮未复现（如实标注）

课件判据要求干净目录下 `make check` 退出码 0。本次在新目录执行：

```bash
python -m uv sync --locked     # 需要先装依赖，新目录没有 .venv
```

两次尝试均因本机网络超时被中断：

| 次数 | 超时上限 | 结果 |
| --- | --- | --- |
| 1 | 420s | 退出码 124（仍在下载 grpcio / numpy / cryptography） |
| 2 | 500s | 退出码 124（已下完 openai、pydantic-core，剩余未完成） |

因此 **`make check` 未能在换目录后跑出 0**，此项标注为**未复现**，不写成通过。
原因是本机到 PyPI 的下载速度，不是代码或锁文件问题——`uv.lock` 已改为官方源，
`uv lock --check` 与 `uv sync --locked`（原目录）此前均通过。

替代证据（**不等同于本条判据**，仅说明同一份代码在容器里是绿的）：原目录已实跑
`docker compose up -d --build`，并在 `campusclaw-app` 容器内跑通 `security` /
`async` / `audit` / `observe` 四项（`apitest` 与 `compose` 依赖仓库文件，
运行时镜像里没有，属不适用，见 `reports/evidence/docker-acceptance.md`）。

## 五、判定与待办

| 检查点 | 结果 |
| --- | --- |
| 干净目录 `docker compose up -d` 一次成功 | **否**：缺 `.env` 时 mcp `Exited (2)` |
| 补 `.env` 后四服务全起 | 是 |
| 健康检查全过 | 是（app healthy、`/health` = ok） |
| 空库自动初始化 + 预置账号可登录 | 是 |
| 干净目录 `make check` 退出码 0 | **未复现**（网络超时） |

**修复项（文档侧，不改代码）**：`README.md` 的「快速启动」需要明确写出
`cp .env.example .env` 并生成 `MCP_AUTH_TOKEN`，否则「一键启动」在干净环境里
必然少一个服务。已在本轮补入 README。

> 口径说明：mcp 的 fail-closed 是**正确的安全设计**，不能为了「更绿」把它改成
> 无令牌也启动——那等于用放松安全换一个好看的 `ps`。该改的是文档与样例，
> 让人按文档走就能得到四服务全起。
