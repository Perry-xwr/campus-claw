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

**5 通过 / 0 部分 / 1 未执行。** 严格按课件原文逐条对照，不把「有配置」算成「已验证」。

| # | 判据 | 结论 | 差在哪 | 证据指向 |
| --- | --- | --- | --- | --- |
| 1 | 一键测试挡得住坏提交 | **通过** | — | `reports/gate-red-green.md` |
| 2 | 环境可复现 | **通过** | 干净目录（`git archive`）+ 全新 venv + 装依赖后门禁退出码 0（5 通过 + 1 跳过）；字面 `make check` 未敲（本机无 GNU make），跑的是它唯一一行等价命令 | `reports/boot-reproduce.md`、`reports/evidence/gate-clean-dir.md` |
| 3 | 推送即构建 | **通过** | 流程 → 测试 → `docker build -t campusclaw:<SHA>`，镜像带 revision 标签可反查提交；无镜像仓库推送 | `reports/pipeline.md` |
| 4 | 面板看得见技能 | **通过** | 四条曲线按技能分线在 `/claw/` 上出图；**无公网域名**，告警仍无外发通知 | `reports/observe-alert.md` |
| 5 | 压测有前后对比 | **通过** | 同一脚本同一参数（vus=20、60s）缓存前后两轮：吞吐 +49.2%、P95 −34.5%；余量卡在审计写入 | `reports/bench.md` |
| 6 | 真实用户 | **未执行** | 0 / 3 人 | `reports/feedback.md` |

### 1. 门禁与演示

`make check` 六项：security / async / apitest / audit / observe / compose。六项的步骤名、参数、顺序只写在一处（`scripts/check_all.py`），`Makefile` 与 CI 都指向它。
**先红后绿四样齐**：改坏处 `7f9af27`（CSRF 校验被跳过）→ 本地 `18/20`、退出码 **1** →
修复 `f73a73e` → 本地 `20/20`、退出码 **0**。CI 同步：run #6 `failure`、run #7 `success`。
全文见 `reports/gate-red-green.md`，流水线运行记录见 `reports/pipeline.md`。

**部署地址**：当前仅有本机实例 `http://localhost:8080`（`docker compose up -d` 四服务）
与局域网地址（`http://<本机 IP>:8110/claw/`），**没有对外域名**。

**四条曲线**：面板挂在 `/claw/`（`/dashboard` 保留兼容），三条图四条线——技能调用量、
每技能错误率、接口 P95、队列深度，数据全部来自上一课的审计七列，可按 1h / 6h / 当天 / 7 天
缩放。实测三个技能 8 次真实调用、4 次失败，队列深度 0 → 4。

**轻量端**：手机浏览器打开 `/m`，复用同一套接口走完四步（登录 → 202 + 任务标识 →
轮询 pending/running/succeeded → 跨班 404），跨源按 `CORS_ORIGINS` 白名单声明。
命令行实测全绿，真机未打开——见 `reports/h5-lightweight.md`。

### 2. 复盘：两次返工

**第一次（压测口径）**：第一轮用 `python app.py`（Flask 内置服务器），出现大量 `status=0`。
逐项核对后确认**不是服务端错误**：同机单发与 5 / 10 路并发均 100% 200，瓶颈在内置服务器
按 HTTP/1.0 应答、短连接把 Windows 动态端口吃进 TIME_WAIT。改用 `waitress` 复测后归零。
那组数据回答的是「部署方式对并发的影响」，只作背景，判据 5 的前后对比另有缓存两轮。

**第二次（数据可信度）**：缓存两轮第一次跑时 `/api/search` 出现 15,568 个 500、`/api/conversations`
全 500。读日志是 `database disk image is malformed`——反复硬杀服务进程，写事务在提交中途被终止，
库结构留下异常。修法是新增 `scripts/serve_waitress.py` 到点**优雅关闭**，两轮各用独立数据目录副本；
改完后两个库 `integrity_check` 均为 `ok`，500 归零。**先证明数据是真的，再谈前后对比。**

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
| 真机打开轻量端 | 未验证 | 页面与接口已就绪，缺一次手机浏览器打开；与上一条绑在一起做 |
| 公网部署域名 | 未做 | 需要对外可达的机器与域名；当前只有本机 + 局域网地址 |
| 告警外发通知 | 未做 | 有判定、有退出码，没有邮件/IM/webhook 渠道；接入点见 `reports/observe-alert.md` 第六节 |
| 镜像推到镜像仓库 | 未做 | 本轮只在本机构建并校验标签；推 GHCR 需要仓库写权限与登录 |
| 审计写入批量化 | 未做 | 压测显示吞吐天花板在此（约 100 次/秒）；属新一轮改进，不塞进本轮 |
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
| `reports/bench.md` | 缓存改进前后两轮数字（同脚本同参数）、归因与一次数据返工 |
| `reports/h5-lightweight.md` | 轻量端页面、四步走查、跨源声明实测 |
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
**五条通过、一条未执行**——环境可复现、镜像、曲线、缓存改进、轻量端都已落地并实测，
剩下的只有一个真实用户，以及域名与通知这类外部条件。
**不把「文件写好了」当「跑绿过」，也不拿自测冒充用户。**
