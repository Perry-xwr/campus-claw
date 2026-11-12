# 修复与复测对照表 · 第 9 课 · 安全检查与审计

> 复测口径：用与发现问题时**完全相同**的三段式记录（前置条件 / 操作 / 可观测结果）重放一遍。
> 修复的完成标志是复测变绿，不是「看起来好了」——因此每一行都必须有两个实际值：发现时的值、修复后的值。

- **基线快照**：`reports/security-precheck.md`（第 8 课，2026-11-04，`HEAD bcc8716`，6 绿 1 红）
- **第一次复测**：2026-11-12，`HEAD 475eb45`，同一条三段式重放 → 5 绿 2 红（SEC-06 从未知转红、SEC-07 仍红）
- **修复后复测**：2026-11-12，本次变更提交，同一条三段式重放 → **7 绿 0 红**
- **原始 JSON**：`reports/evidence/security-recheck-lesson9.json`
- **复现入口**：`python scripts/acceptance_security.py --out reports/evidence/security-recheck-lesson9.json`

## 一、SEC-01 ～ SEC-07 三次快照对照

| 编号 | 检查项 | 缺口类别 | 基线（11-04） | 复测（修复前） | 复测（修复后） | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| SEC-01 | 未登录访问受保护接口 | 授权 | 9 个接口 401 | 9 个接口 401 | 9 个接口 401 | 绿 |
| SEC-02 | 跨班访问与跨班检索 | 授权 | 跨班 GET 404；本班 1 条；跨班检索 0 条 | 同左 | 同左 | 绿 |
| SEC-03 | 学生改技能与提示词 | 授权 | 403/403；技能 2 条未变 | 403/403；`class_prompts` 未变 | 403/403；`class_prompts` 未变 | 绿 |
| SEC-04 | 技能工具绕过鉴权 | 授权 | 403/403；`index_jobs` 2→2 | 同左 | 同左 | 绿 |
| SEC-05 | 密钥明文泄漏扫描 | 资产 | 0 命中 | 0 命中（13 提交 / 53 产物 / 1 日志） | 0 命中 | 绿 |
| SEC-06 | 依赖漏洞基线 | 资产 | 高危数**未知**（未在线比对） | **2 包 4 条 PYSEC，均有补丁** | **0 条漏洞**（`No known vulnerabilities found`） | 红 → **绿** |
| SEC-07 | 审计日志可追溯 | 日志 | 缺 技能标识 / 耗时 / 用量 | 仍缺同样三列 | **七列齐备**，另有拒绝审计与回查脚本 | 红 → **绿** |

## 二、SEC-06：从「未知」到「已知」，再到「清零」

### 2.1 发现（修复前）

基线走的处置分支是「书面登记」，原因是当次环境未装 `pip-audit` 且未联网比对，只能登记「未知」。本次装上工具、对 `requirements.txt` 的声明依赖发起 OSV 在线比对，原始输出 `reports/evidence/pip-audit-osv.log`：

```
Found 4 known vulnerabilities in 2 packages
Name     Version ID              Fix Versions
flask    3.1.1   PYSEC-2026-2151 3.1.3
werkzeug 3.1.8   PYSEC-2026-4312 3.1.9
AUDIT_EXIT=1
```

去重后是 **2 个漏洞编号、2 个包**，两者都有修复版本。核对实际运行版本：声明 `Flask==3.1.1` / `Werkzeug==3.1.8`，`pip list` 也是这两个版本，**三处一致，全部受影响**。

### 2.2 修复动作

| 文件 | 改动 |
| --- | --- |
| `requirements.txt` | `Flask==3.1.1` → `==3.1.3`；`Werkzeug==3.1.8` → `==3.1.9` |
| `pyproject.toml` | 同上一并修改，并在注释里写明对应的两个 PYSEC 编号 |
| `uv.lock` | `uv lock` 重新解析（同时把写死的清华镜像源换成官方源，见 `reports/gate-red-green.md` 的可复现性一节） |

`uv sync --locked` 后实测安装版本：

```
flask 3.1.3
werkzeug 3.1.9
```

### 2.3 复测（修复后）

```
No known vulnerabilities found
AUDIT_EXIT=0
```

原始输出 `reports/evidence/pip-audit-after.log`。**退出码从 1 变 0**，这就是修复的完成标志——不是「我升了版本」，而是「同一条命令不再报漏洞」。

顺带记一条判定口径：**「未知」和「0 高危」必须分开写**。把没比对过的依赖报成「高危清零」，是这一项最容易犯的错；反过来，只写「已升级」而不重跑审计，也无法证明清零。

## 三、SEC-07：补齐七列，并让失败的尝试也留痕

### 3.1 缺口（修复前）

课件要求一条审计记录能独立回答七问：谁、何时、做了什么、对哪一条、结果如何、**用了哪个技能**、**花了多少**。原表 `mcp_tool_calls` 只有前五问，缺后两问（技能标识、用量与耗时），且只记成功的工具调用，被拒绝的越权尝试一条不留。

### 3.2 修复动作

| 层 | 文件 | 改动 |
| --- | --- | --- |
| 表结构 | `campusclaw/mcp_db.py` | `mcp_tool_calls` 新增 `action` / `object_id` / `skill_id` / `duration_ms` / `tokens` / `request_id` 六列；新增 `_ensure_tool_call_columns()` 做**幂等增量迁移**（老库缺列自动 ALTER，不删数据） |
| 采集 | `campusclaw/mcp_skill.py` | `_record()` 补 `skill_id` / `duration_ms` / `object_id`；每次工具调用用 `time.perf_counter()` 实测耗时；`request_id` 从请求上下文取 |
| 采集（新表） | `campusclaw/audit_db.py` | 新增 `audit_events` 表，记录 401 / 403 / 404 拒绝尝试（操作人、时间、动作、对象、状态、错误码、request_id、耗时） |
| 出口 | `campusclaw/request_context.py` | 每请求生成 `request_id` 并回写响应头 `X-Request-Id`；统一错误出口处落拒绝审计（best-effort，失败不影响响应）；`after_request` 记录指标 |
| 查询 | `campusclaw/views/audit_views.py` | 新增 `GET /api/audit/events`，仅教师可读、按本班隔离，支持 `status` / `actor` / `skill_id` 过滤 |
| 回查 | `scripts/audit_recheck.py` | 按技能标识加时间窗回查，逐列断言七列，任一列空即退出码 1；输出 `reports/audit-recheck.md` |

### 3.3 复测（修复后）

真实跑一次技能调用取证：注册 MCP 服务器 → 连接发现工具（`formula_hint`、`unit_convert`）→ 建技能绑定 `unit_convert@calc` → 学生提问 → `run_skill_tools` 实际调用。

回查结果（`reports/audit-recheck.md`）：

| 列 | 含义 | 实际取值 |
| --- | --- | --- |
| `actor` | 操作人 | `student_a1` |
| `created_at` | 操作时间 | `2026-11-12T02:01:52.222940+00:00` |
| `action` | 操作类型 | `skill.invoke` |
| `object_id` | 操作对象 | 会话 id |
| `status` | 结果状态 | `ok` |
| `skill_id` | 技能标识 | `单位换算引导` |
| `duration_ms` | 用量与耗时 | 实测毫秒数 |

拒绝尝试同样留痕，4 条实测记录：

| 场景 | 状态码 | 错误码 | 操作人 |
| --- | --- | --- | --- |
| 学生越权建技能 | 403 | `ROLE_FORBIDDEN` | `student_a1` |
| 学生删材料 | 403 | `ROLE_FORBIDDEN` | `student_a1` |
| B 班教师读 A 班材料 | 404 | `MATERIAL_NOT_FOUND` | `teacher_b` |
| 未认证访问材料列表 | 401 | `AUTH_REQUIRED` | （空） |

**关于 `tokens` 列**：MCP 工具调用不返回模型用量，故该列在有值时记录、无值时留空（不是漏记，是无值可记）。课件对本项目的口径是「模型返回的 tokens」——本项目这条链路上没有模型参与，留空是可核实的诚实做法，不填 0 假装记了。

### 3.4 为什么这次是真的修好了

判断依据不是「表里多了几列」，而是三件事同时成立：

1. 七列**在同一行**上都有值（不是分散在不同记录里凑出来）；
2. 拒绝的尝试也落了库，能按学生加时间窗查到；
3. 回查写成了脚本并进了门禁（`make check-audit`），下次改坏会直接变红。

## 四、注入三件套：从盲区到有反例

第 8 课自查里没有 SQL / XSS / CSRF 反例，它们既不是红也不是绿——是**盲区**。本次按课件要求各补一条，落在 `apitest/cases/<接口路径>/<方法>` 下，随 `make check` 常驻。

| 类型 | 用例位置 | 反例操作 | 期望 | 实测 | 判定 |
| --- | --- | --- | --- | --- | --- |
| SQL 注入 | `apitest/cases/api/search/POST.py` | `POST /api/search` 检索词 `' OR '1'='1` | 空结果或格式错误，不得返回全表 | **400 `INVALID_QUERY`**；前置对照本班正常词命中 1 条 | 绿 |
| XSS | `apitest/cases/api/materials/upload/POST.py` | 标题存入 img 标签形式的脚本（`img src=x onerror=alert(...)`），再看 `/materials` 源码 | 源码已转义、无可执行标签 | 201 入库；页面含 `&lt;img` 转义形式，无原始标签 | 绿 |
| CSRF | `apitest/cases/api/prompt/PUT.py` | 带 Cookie 会话、不带 `X-CSRF-Token` 的 `PUT /api/prompt` | 403 且无写入副作用 | **403 `CSRF_INVALID`，正文未变**；补令牌后 200 | 绿 |

三件套连前置共 8 条断言，`python apitest/run_all.py` 一次跑完，**8/8 绿**。

两条判定细节：SQL 注入必须先跑正常词做前置对照（功能整体坏掉时同样命中 0 条，会被误判为绿）；XSS 要看页面源码而不是看弹窗（不弹窗只是表象）。

## 五、门禁覆盖变化

| 版本 | `make check` 覆盖面 | 退出码实测 |
| --- | --- | --- |
| 第 8 课 | security + async（2 项） | 未做红绿实验 |
| 第 9 课修复前 | security + async + apitest（3 项） | 0 → 1 → 0 |
| 本次修复后 | security + async + apitest + **audit**（4 项） | 0（四项全绿） |

先红后绿的完整证据（含必红 patch 与三次退出码）见 `reports/gate-red-green.md`。

## 六、仍未完成的一项

| 项 | 现状 | 补的位置 |
| --- | --- | --- |
| SEC-08 提示词注入实验 | **未执行**。素材已备（`reports/sec08-materials/`），但本机未配置 `CHAT_MODEL`，助手链路产不出真实回答，做了也只能记「链路不可用」 | 配好模型后按四步实验法做，记录归档 `reports/sec08-experiment.md` |

SEC-08 没有硬凑：这一项判的是「模型会不会被文档里的指令带走」，没有真实模型就没有可观测的回答，写出来的任何结论都是编的。缺条件时标注未执行，比补一份假记录诚实。
