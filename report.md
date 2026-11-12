# CampusClaw 最终项目报告

> 口径：本文件只写**结论与指向**，细节全部落在 `reports/`，可当场打开复核。
> 对应课件：第 9 课《安全检查与审计》、第 10 课《测试、交付与运行验证》。
>
> 代码版本：`f73a73e`（`main`）。仓库：https://github.com/Perry-xwr/campus-claw

## 一、第 9 课：安全检查与审计

五条判据**全部实测为绿**，两条原本是红、真修掉后才转绿。

| # | 判据 | 结论 | 证据指向 |
| --- | --- | --- | --- |
| 1 | 学生改不了技能与提示词 | 通过：`POST` 技能 / 提示词类接口 **403 / 403**，`class_prompts` 数据未变 | `reports/security-fix-log.md` SEC-03 |
| 2 | 学生取不到他班数据 | 通过：跨班讲义 **404**，跨班检索 **0 条** | `reports/security-fix-log.md` SEC-02、`reports/risk-authz.md` |
| 3 | 技能调用可回查（七列） | 通过：操作人 / 时间 / 类型 / 对象 / 结果 / 技能标识 / 用量与耗时，七列齐备，另加拒绝留痕 | `reports/audit-recheck.md` |
| 4 | 资产类两项清零 | 通过：密钥扫描 **0 命中**；依赖 **4 条 PYSEC → 0 条**（Flask 3.1.1→3.1.3、Werkzeug 3.1.8→3.1.9） | `reports/security-baseline.md`、`reports/security-fix-log.md` |
| 5 | 注入三件套有反例且为绿 | 通过：SQL / XSS / CSRF 三条反例，套件 **20/20**，且已进常驻门禁 | `reports/gate-red-green.md`、`apitest/cases/` |

**SEC-08 提示词注入实验：部分**。第四步（工具执行层，课件规定「唯一必须为绿」）已实测为绿——
学生身份直调两个写入接口 **403 / 403**，`index_jobs` 2 → 2，拒绝留痕；但一、二、三步需要真实
模型产出回答，本轮未配 `CHAT_MODEL` / `EMBEDDING_*`，**未执行**。
详见 `reports/sec08-experiment.md`（含四步表与重跑条件）。

## 二、第 10 课：测试、交付与运行验证

**1 通过 / 4 部分 / 1 未执行。** 严格按课件原文逐条对照，不把「有配置」算成「已验证」。

| # | 判据 | 结论 | 差在哪 | 证据指向 |
| --- | --- | --- | --- | --- |
| 1 | 一键测试挡得住坏提交 | **通过** | — | `reports/gate-red-green.md` |
| 2 | 环境可复现 | **部分** | 换目录启动缺 `.env` 时 mcp `Exited (2)`；`make check` 因网络超时未在换目录后复现 | `reports/boot-reproduce.md` |
| 3 | 推送即构建 | **部分** | 流程 / 测试 / 反查提交都达标，**未产出镜像** | `reports/pipeline.md` |
| 4 | 面板看得见技能 | **部分** | 有面板无曲线；指标无技能维度；路径 `/dashboard` 非 `/claw/`；无部署域名与外发通知 | `reports/observe-alert.md` |
| 5 | 压测有前后对比 | **部分** | 两轮同脚本同参数齐，但改进项是「换 WSGI 服务器」不是课件要的缓存或索引 | `reports/bench.md` |
| 6 | 真实用户 | **未执行** | 0 / 3 人 | `reports/feedback.md` |

### 1. 门禁与演示

`make check` 六项：security / async / apitest / audit / observe / compose。
**先红后绿四样齐**：改坏处 `7f9af27`（CSRF 校验被跳过）→ 本地 `18/20`、退出码 **1** →
修复 `f73a73e` → 本地 `20/20`、退出码 **0**。CI 同步：run #6 `failure`、run #7 `success`。
全文见 `reports/gate-red-green.md`，流水线运行记录见 `reports/pipeline.md`。

**部署地址**：当前仅有本机实例 `http://localhost:8080`（`docker compose up -d` 四服务），
**没有对外域名**。演示四步（登录取令牌 → 提交作业 202 → 轮询 pending/running/succeeded →
换班查别班 404）的走查口径见 `reports/feedback.md` 第二节。

### 2. 复盘：一次返工

压测第一轮用 `python app.py`（Flask 内置服务器），出现大量 `status=0`。逐项核对后确认
**不是服务端错误**：同机单发与 5 / 10 路并发均 100% 200，瓶颈在内置服务器本身。改用
`waitress` 复测后数据正常。结论：那组对比回答的是「部署方式对并发的影响」，
不是「改了哪段业务代码」——这也是判据 5 判「部分」的原因。详见 `reports/bench.md`。

### 3. 高风险三查

| 面 | 记录 |
| --- | --- |
| 权限（跨班越权） | `reports/risk-authz.md`（SEC-02 一条按四件事写全，复测命令可当场复跑） |
| 并发 | `reports/risk-concurrency.md` |
| 事务 | `reports/risk-transaction.md` |

### 4. AI 使用与审核记录

| 面 | 记录 |
| --- | --- |
| AI 代码审核 | `reports/review-01.md`（含七类核查清单的实际使用与结论） |
| 协作规则 | `AGENTS.md` |
| 审核清单 / 评审表 | `docs/AI代码审核核查清单.md`、`docs/AI代码审核评审表.md` |

## 三、未完成清单（不做替代性判绿）

| 项 | 状态 | 为什么不做 / 什么时候做 |
| --- | --- | --- |
| 真实用户 ≥3 人 | 未执行 | 需要真人。模板与账号已备，见 `reports/feedback.md` |
| 流水线产出镜像 | 未做 | 需在工作流加 `docker build -t campusclaw:${{ github.sha }}`，见 `reports/pipeline.md` 第四节 |
| 面板曲线与 `/claw/` 路径 | 未做 | 需改页面与路由；当前只有数字与表格 |
| 压测的代码级改进 | 未做 | 需落一项缓存或索引并复测，重写 `reports/bench.md` 的改进节 |
| H5 轻量端 | 未做 | 课件第 ⑥ 步要求，当前 12 个模板全为桌面页 |
| SEC-08 一、二、三步 | 未执行 | 需配 `CHAT_*` / `EMBEDDING_*`，素材已在 `reports/sec08-materials/` |
| 干净目录 `make check` | 未复现 | 本机到 PyPI 下载超时（两次 420s / 500s 中断） |
| 主干分支保护 | 未开启 | 需仓库管理员在 GitHub 设置里勾选 |

## 四、证据索引

| 文件 | 内容 |
| --- | --- |
| `reports/gate-red-green.md` | 门禁红绿四样齐（六项门禁 + 本地与 CI 双侧） |
| `reports/boot-reproduce.md` | 换目录启动实测（含 mcp 缺令牌退出的缺口） |
| `reports/pipeline.md` | 7 次 CI 运行与提交对应、DEF-09 空转问题、镜像缺口 |
| `reports/observe-alert.md` | 面板路径、5 条告警规则文本、一次真触发（ok → critical） |
| `reports/bench.md` | 压测基线与复测两轮数字、归因 |
| `reports/feedback.md` | 真实用户记录表（空表，未执行） |
| `reports/security-fix-log.md` | SEC-01～07 修复前后两个实际值 |
| `reports/security-baseline.md` | 密钥扫描与依赖审计当日快照 |
| `reports/sec08-experiment.md` | SEC-08 四步：第四步绿，前三步未执行 |
| `reports/risk-authz.md` / `risk-concurrency.md` / `risk-transaction.md` | 高风险三查 |
| `reports/review-01.md` | AI 代码审核记录 |
| `reports/evidence/` | 机器可读证据（JSON、日志、补丁） |
| `reports/验收与测试流程报告-2026-11-12.md` | 逐条判据的过程记录与缺陷修复经过（本文件的详细版） |

## 五、一句话结论

安全这一课（第 9 课）**五条判据全绿，两条红是真修掉的**；交付这一课（第 10 课）
**一条通过、四条部分、一条未执行**——缺的不是配置，是三段实现（镜像、曲线、代码级改进）
和一个真实用户。**不把「文件写好了」当「跑绿过」，也不拿自测冒充用户。**
