# 流水线运行记录 · 第 10 课 · 推送即构建

> 课件第 10 课判据原文：**push 一次提交自动构建流程执行、测试通过、产出镜像，
> 编号能反查提交**。证据文件名固定为 `reports/pipeline.md`，内容判定是
> 「一次成功构建的编号与对应提交，镜像编号能反查提交」。
>
> **先说结论：流程执行 ✅、测试通过 ✅、编号反查提交 ✅、产出镜像 ❌。**
> 这一条按课件原文只能算**部分通过**——原因与改法写在第四节。

## 一、流水线做了什么

`.github/workflows/check.yml`，触发条件 `push` / `pull_request` / `workflow_dispatch`：

| # | 步骤 | 命令 |
| --- | --- | --- |
| 1 | 检出代码 | `actions/checkout@v4` |
| 2 | 安装 uv | `astral-sh/setup-uv@v5` |
| 3 | 安装依赖（按锁文件，验证可复现） | `uv sync --locked` |
| 4 | 初始化数据库结构（否则审计与观测两步空转） | `python scripts/init_schema.py --db data/app.db` |
| 5 | SEC-05 密钥扫描 + SEC-06 依赖基线 | `uv run python scripts/check_security.py` |
| 6 | 第 8 课三条判据 | `uv run python scripts/acceptance_async.py` |
| 7 | 第 9 课注入三件套 | `uv run python apitest/run_all.py --no-report` |
| 8 | SEC-07 审计七列结构断言 | `uv run python scripts/audit_recheck.py --allow-empty` |
| 9 | 第 10 课运行观测告警判定 | `uv run python scripts/check_observe.py` |
| 10 | 容器配置静态校验 | `uv run python scripts/check_compose.py` |
| 11 | 归档证据 | `actions/upload-artifact@v4`（`check-evidence`） |

**没有 `docker build`。** 全文件检索 `docker|build|registry|image` 只命中
第 15 行的 `push:` 触发条件，一个构建步骤都没有。

## 二、运行记录（每次都能反查提交）

| run # | 提交 | 触发描述 | 结论 | 耗时 | 证据产物 |
| --- | --- | --- | --- | --- | --- |
| 1 | `c152577` | 首次推送 | success | 31s | 24,996 B |
| 2 | `a0814ec` | 补建库步骤（DEF-09） | success | 34s | **27,571 B** |
| 3 | `7855f12` | 报告转口径 | success | 37s | — |
| 4 | `8269770` | 证据补充 | success | 33s | — |
| 5 | `488e7d7` | README 接验收章节 | success | 33s | 28,011 B |
| **6** | **`7f9af27`** | **必红提交（跳过 CSRF）** | **failure** | 31s | — |
| 7 | `f73a73e` | 还原 CSRF | success | 28s | — |

运行页：
[run #6（红）](https://github.com/Perry-xwr/campus-claw/actions/runs/43248188556) ·
[run #7（绿）](https://github.com/Perry-xwr/campus-claw/actions/runs/43248376283) ·
[全部运行](https://github.com/Perry-xwr/campus-claw/actions)

**run #6 是刻意的红**：本地把 CSRF 校验改坏、`make check` 退出码 1，推送后 CI 同样
failure。这同时满足课件第 ③ 步的另一半要求「本地红则推送也失败」，四样齐的完整
对照见 `reports/gate-red-green.md`。

### 顺带修掉的一个真问题（DEF-09）

run #1 一次就绿，但三步只用了 1 秒。查下去发现：`.gitignore` 排除 `data/` 与 `*.db`，
干净 runner 上**没有数据库**，于是 `audit_recheck.py` 与 `check_observe.py` 见库不存在
直接 `return 0`——步骤名写着「审计七列结构断言」「观测告警判定」，实际一条都没执行。

补了第 4 步建库后，run #2 的产物从 24,996 涨到 27,571 字节，那两步才真的产出判定表。
**这条判据的依据是 run #2 之后，不是 run #1**——只看「第一次推就绿了」会留下一份
从没执行过断言的验收记录。

## 三、编号反查提交

| 你要查的 | 怎么查 |
| --- | --- |
| 某次运行对应哪个提交 | run 页标题 + `head_sha`；上表已列 |
| 某个提交有没有跑过 | `https://api.github.com/repos/Perry-xwr/campus-claw/actions/runs?head_sha=<sha>` |
| 该次运行产出了什么 | run 页底部 `check-evidence` artifact（含 `security-baseline.json`、`observe.json`、`compose-static.json`、`audit-recheck.md`） |

这一项**达标**：每次运行都能定位到提交，每个提交都能查到运行。

## 四、没做到的一项：产出镜像

课件要求「**产出镜像，编号能反查提交**」。当前流水线只跑测试，不构建镜像，
因此没有镜像编号，也没有「镜像 ↔ 提交」的对应关系。

容器镜像目前是**本地构建**的：`docker compose build`（`campusclaw:latest`，约 498MB），
与 CI 运行没有关联。这意味着：

- 课件要的「构建产物可追溯」不成立——`campusclaw:latest` 是个浮动标签，相同标签可能对应不同提交；
- 但「同一份代码在容器里是绿的」这一点是实测过的（`reports/evidence/docker-acceptance.md`）。

**改法（B 档，需改工作流）**：在门禁之后加一步

```yaml
- name: 构建镜像并打提交标签
  run: docker build -t campusclaw:${{ github.sha }} .
```

需要推镜像仓库时再补 `docker push` 与登录步骤。打完标签后，`campusclaw:<sha>`
即可反查提交，本判据才真正成立。

## 五、判定

| 课件要求 | 实际 | 判定 |
| --- | --- | --- |
| 自动构建流程执行 | 7 次运行，全部由 push 触发 | 达标 |
| 测试通过 | run #7 success，12 个实质步骤无一跳过 | 达标 |
| 编号能反查提交 | 上表 + API 查询方式 | 达标 |
| **产出镜像** | **无 `docker build`** | **不达标** |
| 本地红则推送也失败 | run #6 failure | 达标 |
| 主干分支保护 | 未开启（需仓库设置） | 不达标 |

结论：**部分通过**。缺的那一项是流水线的最后一段（构建并打标签），
不是配置写错，而是这一步还没写。
