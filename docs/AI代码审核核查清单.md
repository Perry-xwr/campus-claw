> 本文件是第 8 课新增的 Harness 核查清单；本仓库根目录 `AGENTS.md` 中的组长规则（含提交/推送授权）同样生效，二者同时遵守。

# AI 代码审核核查清单（Harness 规则 · 第 8 课）

本仓库的 Harness 规则。AI 生成代码前必须读完；人工审核按本文件逐条判定；审核中发现的规则与坑必须回写本文件（见第 5 节「沉淀反哺」）。

## 1. 仓库是什么 / 技术栈 / 运行入口

- **CampusClaw**：班级教学材料管理与可追溯知识库检索系统。材料按班级隔离、回答由检索结果驱动、引用可点回原文；附带解题助手、班级答疑广场、MCP 工具接入。
- **技术栈**：Python 3.11 / Flask 3.1 / SQLite（FTS5 中文二元组切词）/ SSE / 原生内联模板；可选 Qdrant 向量库与 OpenAI 兼容模型。零模型配置也能完整跑通（关键词检索 + 确定性本地流式回退）。
- **运行入口**：`uv run python app.py`（依赖以 `pyproject.toml` + `uv.lock` 为准），浏览器开 `http://127.0.0.1:8080/login`。
- **必须在项目根目录启动**：`config.py` 以 `Path.cwd()` 为 home，`data/app.db`、`uploads/`、`.env` 全按 cwd 解析；在别处启动会新建空库、读不到 `.env`。
- **`.env` 不入库**：`.gitignore` 已忽略 `.env` / `data/` / `uploads/`。`SECRET_KEY`、`CHAT_API_KEY`、`EMBEDDING_API_KEY`、`MCP_AUTH_TOKEN`、`SEED_*_PASSWORD` 只放根目录 `.env`，绝不提交、绝不写进代码或日志。
- **全仓无 `before_request`**：认证、角色、CSRF、班级过滤全部靠视图显式调用 `campusclaw/request_context.py`，新增视图不会自动获得任何保护。

## 2. AI 生成代码的准入规则

**每份 AI 代码必须注明生成范围**：哪个文件、哪一段、由哪次生成产生，写在评审表表头「生成范围」一栏；范围不明的 AI 代码一律不受理。

四步准入流程（缺一步即流程违规）：

1. **AI 生成初稿**：注明生成范围，不直接合入。
2. **自己逐段审核**：按第 3 节「七类拆解核查清单」+ `docs/AI代码审核评审表.md` 七维度逐项核对，高风险场景写专项记录。
3. **交叉评审**：交同学 / 组内另一人评审，意见留痕归档到 `docs/` 与 `reports/`。
4. **合入 `main`**：仅在测试通过、证据归档之后；`make check` 与 `make check-security` 的输出归档在 `reports/`。

**红线：未经审核的 AI 原生代码不得合入 `main`。跳过审核按流程违规记录，与代码缺陷同等处理。**

三分法结论（写进评审表，决定后续动作）：

| 结论 | 判定 | 后续动作 |
| --- | --- | --- |
| `可用` | 逻辑正确、符合规约与安全要求 | 补测试，交同学评审 |
| `待修改` | 方向对但有缺陷或偏离需求 | 列出具体修改项，改完重新审核 |
| `风险无效` | 存在越权、数据错乱等风险或与需求无关 | 直接丢弃重写，不接受改一改凑合用 |

固定流程：工具批量扫描（代码规范、数据库查询检查、依赖漏洞检测，整库跑一遍）→ 人工重点复核（权限、并发、事务、数据一致性逐行读并写下依据）→ 沉淀反哺（把规则与坑回写本文件，在生成阶段就拦住）。

## 3. 七类拆解核查清单（逐条勾选）

审核时逐条打勾；每条都要能回答对应的提问，不能只写「已看」。

### 3.1 接口入口
- [ ] 传进来的参数都检查了吗？（类型、范围、必填、未知字段）
- [ ] 除了「登录了没有」，有没有检查这份数据属于当前用户？（`class_id` 归属，跨班一律 404）
- [ ] 返回内容里有没有多余字段？（内部 `_` 前缀字段、`storage_key`、`last_error`、哈希、路径不外泄）

### 3.2 业务逻辑
- [ ] 和需求文档、验收场景一条条对过吗？
- [ ] 状态怎么流转，有没有漏掉中间状态？（`queued → running → done/failed`；`pending → running → ready/failed`）
- [ ] 有没有违反本组定的规范？（OpenSpec 规约、错误码表、索引代次机制、状态与标记分离）

### 3.3 数据库操作
- [ ] 需要连续写多处的地方是不是放在同一个事务里？（`BEGIN IMMEDIATE` … `COMMIT` / 异常 `ROLLBACK`）
- [ ] 唯一性是用数据库约束保证的，还是靠「先查一遍」？（`UNIQUE` / 部分唯一索引 vs `SELECT 1` 再 `INSERT`）

### 3.4 公共函数
- [ ] 是不是把同一段逻辑复制到多个文件？（认证、CSRF、`class_id` 过滤、错误体、时间戳）
- [ ] 出错时是悄悄吞掉，还是明确报出来？（`except: pass` / 宽泛 `try` 吞异常 vs `raise ApiError`）

### 3.5 错误处理
- [ ] 每种失败情况都有出口吗？（401 / 403 / 404 / 400 / 503 / 500 各就位）
- [ ] 报错信息有没有把内部结构、路径、配置暴露出去？（SQL、堆栈、绝对路径、密钥、他班内容）

### 3.6 安全与隐私
- [ ] 敏感字段有没有脱敏？（口令、sid、Bearer 令牌、API Key 遮盖）
- [ ] 用户输入有没有先校验再使用？（长度、类型、白名单、身份字段拒绝）
- [ ] 返回给用户的内容有没有先转义？（模板输出，避免 XSS）

### 3.7 性能
- [ ] 有没有在循环里逐条查数据库？（N+1）
- [ ] 查询条件有没有用到索引？（`class_id`、`status`、`(material_id,generation)` 复合索引）
- [ ] 列表接口有没有分页？（`page` / `size` 上限）

### 3.8 四步拆解法

对每一处「它保证了什么」都按四步问一遍：

1. **它想保证什么**：写出不变量，例如「一份材料同时最多一个进行中索引任务」。
2. **它实际靠什么保证**：靠应用层 `SELECT` 检查、靠视图鉴权、靠事务，还是靠数据库 `UNIQUE` 约束？
3. **什么情况下失效**：并发请求、多进程 / 多 worker、绕过视图直调函数、异常被吞、状态值漏判。
4. **挡得住的写法**：把不变量交给数据库约束或事务，冲突按既定语义返回，而不是靠「先查一遍」。

### 3.9 反例与正例（本仓库 SQLite / Flask 语境）

**反例（网页典型：`先 SELECT 1 ... 再 INSERT`，并发下产生重复）** —— `campusclaw/retrieval_db.py` 的 `enqueue()` 现状：靠「先查有没有 busy 再插入」维持「一材料一个进行中任务」，`index_jobs` 表上没有对应的 `UNIQUE` 约束。这就是网页反例。

```python
# 反例：唯一性由应用层的 SELECT 承担，数据库不拦
def enqueue(conn: sqlite3.Connection, material_id: int, strategy: dict) -> int:
    stamp = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        busy = conn.execute(
            "SELECT id FROM index_jobs WHERE material_id=? "
            "AND status IN ('queued','running') LIMIT 1",
            (material_id,),
        ).fetchone()
        if busy:
            conn.execute("ROLLBACK")
            return int(busy["id"])
        cursor = conn.execute(
            "INSERT INTO index_jobs(material_id,strategy_json,status,created_at,updated_at) "
            "VALUES (?,?,'queued',?,?)",
            (material_id, payload, stamp, stamp),
        )
        conn.execute("COMMIT")
        return int(cursor.lastrowid)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
```

**正例（数据库唯一索引 + 冲突按既定语义返回）** —— 不变量下沉到 SQLite 部分唯一索引，写入不再「先查一遍」：

```python
# 迁移：把不变量交给数据库（放在 ensure_schema 内，幂等）
conn.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_index_jobs_active
    ON index_jobs(material_id)
    WHERE status IN ('queued','running')
""")

# 写入：直接 INSERT，冲突由数据库拦下并按既定语义返回既有 job_id
def enqueue(conn: sqlite3.Connection, material_id: int, strategy: dict) -> int:
    payload = json.dumps(strategy, ensure_ascii=False, sort_keys=True)
    stamp = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "INSERT INTO index_jobs(material_id,strategy_json,status,created_at,updated_at) "
            "VALUES (?,?,'queued',?,?)",
            (material_id, payload, stamp, stamp),
        )
        conn.execute("UPDATE material_index SET status='pending',strategy_json=?,"
                     "last_error=NULL,updated_at=? WHERE material_id=?",
                     (payload, stamp, material_id))
        conn.execute("COMMIT")
        return int(cursor.lastrowid)
    except sqlite3.IntegrityError:
        # 唯一约束拦下：按既定语义复用既有任务，不新建、不吞掉
        row = conn.execute(
            "SELECT id FROM index_jobs WHERE material_id=? "
            "AND status IN ('queued','running') LIMIT 1",
            (material_id,),
        ).fetchone()
        conn.execute("ROLLBACK")
        return int(row["id"])
    except BaseException:
        conn.execute("ROLLBACK")
        raise
```

> 正例里的 `SELECT` 只用于冲突后取回既有 `job_id`（既定语义），不再承担唯一性判断；唯一性由 `uq_index_jobs_active` 保证。

## 4. 本仓库的具体红线

1. **身份只从服务端会话取**：`rc.current_user()` 从不透明 sid / Bearer 令牌还原 `user["class_id"]`、`user["role"]`；客户端传的 `class_id` / `user_id` / `role` / `uploaded_by` 一律不信任，`reject_identity_fields()` / `upload_identity_check()` 命中即 `400 IDENTITY_FIELD_FORBIDDEN`。
2. **所有查询按 `class_id` 过滤，跨班与不存在统一 404**：`materials.get_active_material(conn, id, class_id)` 用 `WHERE id=? AND class_id=? AND status='active'`；不得用 403 区分存在性，不靠前端隐藏。
3. **写接口显式校验**：教师写用 `rc.require_write()`、任意登录用户写用 `rc.require_write_any()`，内部顺序为 认证 → 角色 → CSRF（`require_csrf()`）；Cookie 会话写请求必须带 `X-CSRF-Token`，Bearer 写请求按约定免 CSRF。**全仓无 `before_request`，靠视图显式调用，新增视图必须自己加校验**，不得假设有全局钩子兜底。
4. **写入多处放同一事务**：`BEGIN IMMEDIATE` 起、`COMMIT` 收，异常 `ROLLBACK` 并 `raise`；`materials` / `knowledge_entries` / `material_index` / `index_jobs` 的连续写入不得半提交。
5. **唯一性靠 `UNIQUE` 约束**：`classes.name`、`users.username`、`materials.storage_key`、`knowledge_entries.material_id`、`knowledge_chunks(material_id,generation,chunk_index)`、`mcp_servers(class_id,name)` 等均由 `UNIQUE` / 部分唯一索引保证；禁止把「先查一遍」当唯一手段，冲突按 `sqlite3.IntegrityError` 既定语义返回。
6. **密钥只在 `.env`，日志不打密钥**：`.env` 不入库；`app.py` 启动横幅对来自环境变量的口令打 `********`；日志禁止出现密钥、sid、令牌、口令哈希、SQL、异常堆栈、绝对路径或他班内容。
7. **错误体统一**：所有 JSON 错误必须是 `{"error":{"code":...,"message":...}}`（`campusclaw/errors.py` 的 `error_body()` / `raise_api()`）；`message` 取 `MESSAGES` 固定文案；未知异常统一 `500 INTERNAL_ERROR`，细节只进服务端日志。

## 5. 沉淀反哺

- 审核中发现的规则、坑、反例**必须回写本文件**（第 3 节清单或第 4 节红线），让生成阶段就按新规则拦住，而不是只在这次评审里记一笔。
- 高风险部分（并发 / 事务 / 权限 / 数据一致性）复核记录必须写清三件事：**查了什么、依据哪条规约、结论是什么**；`docs/AI代码审核评审表.md` 里这几节不允许跳过。
- 评审表与审核证据归档位置：`docs/` 与 `reports/`；`make check` / `make check-security` 的输出归档在 `reports/`。
