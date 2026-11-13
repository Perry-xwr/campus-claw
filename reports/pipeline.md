# 流水线运行记录 · 第 10 课 · 推送即构建

> 课件第 10 课判据原文：**push 一次提交自动构建流程执行、测试通过、产出镜像，
> 编号能反查提交**。证据文件名固定为 `reports/pipeline.md`，内容判定是
> 「一次成功构建的编号与对应提交，镜像编号能反查提交」。
>
> **先说结论：流程执行 ✅、测试通过 ✅、产出镜像 ✅、编号反查提交 ✅。**
> 镜像带 `org.opencontainers.image.revision` 标签，标签值就是提交 SHA，
> 离开仓库后仍能回答「这是哪次提交做的」。第四、五节是实测记录。

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
| 11 | **构建镜像** | `docker build -t campusclaw:${GITHUB_SHA} -t campusclaw:run-${GITHUB_RUN_NUMBER} .` |
| 12 | 归档证据 | `actions/upload-artifact@v4`（`check-evidence`） |

构建步骤**放在测试之后**是有意的：门禁没绿就构建出一个镜像，等于给坏提交发通行证。
构建完成后做三件事——打印镜像 ID 与大小、断言镜像里的 `revision` 标签等于当前 SHA、
用 `docker run --rm <image> python -c "import campusclaw"` 冒烟确认依赖装齐；
三行结果写进 step summary，运行页可直接看到。

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
| 8 | `3283417` | 补齐课件归档与口径下调 | success | 38s | — |
| **9** | **`53e8636`** | **B 档：镜像 + 曲线 + 缓存 + 轻量端** | **success** | **1m53s** | — |
| 10 | `519cf79` | 报告口径改为 4/1/1 | success | 1m36s | 28.7 KB |

运行页：
[run #6（红）](https://github.com/Perry-xwr/campus-claw/actions/runs/43248188556) ·
[run #7（绿）](https://github.com/Perry-xwr/campus-claw/actions/runs/43248376283) ·
[run #9（产出镜像）](https://github.com/Perry-xwr/campus-claw/actions/runs/43256692919) ·
[run #10（纯文档）](https://github.com/Perry-xwr/campus-claw/actions/runs/43259012680) ·
[全部运行](https://github.com/Perry-xwr/campus-claw/actions)

> 这张表停在 run #10。此后的纯文档提交仍走同一流程（运行页可查），不再逐次补行——
> 表格的用途是「证明编号能反查提交」，不是流水账。

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

## 四、产出镜像：构建了什么，怎么反查

### ① CI 上的构建（run #9，第 12 步）

```
镜像 ID sha256:...，大小 497,899,761 字节
镜像内 revision 标签：53e8636537adbdc3675081c0902d7bc7a5313097
import ok
```

该步耗时 **78 秒**（16:16:09 → 16:17:27），整个 job **1 分 53 秒**、13 个实质步骤全绿。
镜像打了两个标签：`campusclaw:<GITHUB_SHA>` 与 `campusclaw:run-<GITHUB_RUN_NUMBER>`，
前者是「反查提交」用的，后者是「这一次运行」用的。

### ② 本地复现（同一份代码，同一份 Dockerfile）

```bash
SHA=$(git rev-parse --short HEAD)
docker build --build-arg GIT_SHA=$SHA --build-arg BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  -t campusclaw:$SHA .
docker image inspect campusclaw:$SHA \
  --format 'revision={{index .Config.Labels "org.opencontainers.image.revision"}} id={{.Id}} size={{.Size}}'
docker run --rm campusclaw:$SHA python -c "import campusclaw; print('import ok')"
```

实测（本机，提交 `53e8636`）：

```
revision=53e8636 id=sha256:33c7a71daa5d8a3c3e3fefa29238b17681bed0dc0be34ed826046fcd7f504277 size=497899761
import ok
```

`Dockerfile` 里两个构建参数 `GIT_SHA` / `BUILD_TIME` 落到
`org.opencontainers.image.revision` 与 `.created` 两个标签上。不传时默认 `unknown`——
宁可标注「不知道」，也不要留一个看起来像真的默认提交号。

### ③ 编号反查链条

| 你要查的 | 怎么查 |
| --- | --- |
| 某次运行对应哪个提交 | run 页标题 + `head_sha`；上表已列 |
| 某个提交有没有跑过 | `https://api.github.com/repos/Perry-xwr/campus-claw/actions/runs?head_sha=<sha>` |
| **某个镜像对应哪个提交** | `docker image inspect campusclaw:<sha> --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'` |
| 该次运行产出了什么 | run 页底部 `check-evidence` artifact + step summary 里的镜像 ID/大小 |

仍需说明的是：**镜像只在 runner 上构建，没有推到镜像仓库**（`docker push` 需要仓库写权限
与登录凭据）。所以「编号反查提交」在 CI 日志与本机构建两处成立，但别人拿不到那个镜像文件。
要真正交付，下一步是推 GHCR 并给 digest 打标签——这属于部署环节，不在本轮范围。

## 五、判定

| 课件要求 | 实际 | 判定 |
| --- | --- | --- |
| 自动构建流程执行 | 9 次运行，全部由 push 触发 | 达标 |
| 测试通过 | run #9 success，13 个实质步骤无一跳过 | 达标 |
| **产出镜像** | run #9 第 12 步 `docker build -t campusclaw:<SHA>`，78 秒，镜像 497.9 MB | 达标 |
| **编号能反查提交** | 镜像标签 `campusclaw:53e8636` + `revision` 标签同值 + 上表与 API 查询 | 达标 |
| 本地红则推送也失败 | run #6 failure | 达标 |
| 镜像推送到仓库 | 未做（需仓库凭据） | 不计入本判据 |
| 主干分支保护 | 未开启（需仓库设置） | 不达标 |

结论：**通过**。这一条从「流程跑完就结束」补成了「流程跑完产出可追溯的制品」：
镜像编号就是提交 SHA，镜像元数据里也写着同一个值，两条路都能反查。

## 六、本轮新增的两次运行（2026-11-13 23:48 / 23:55）

| run # | 提交 | 结论 | 耗时 | 说明 |
| --- | --- | --- | --- | --- |
| [#12](https://github.com/Perry-xwr/campus-claw/actions/runs/43456320346) | `d9383e9` | **failure** | 36s | 挂在「SEC-07 审计七列结构断言」，报 `exit code 75` |
| [#13](https://github.com/Perry-xwr/campus-claw/actions/runs/43456789114) | `d0abef1` | **success** | 4m 22s | 工作流显式接受 75（打 notice），其余退出码照旧失败；镜像照旧构建 |

run #12 的红**不是坏提交，是门禁口径在 CI 上没跟上**：DEF-10 把 `audit_recheck.py`
改成三态（0 通过 / 1 红 / 75 跳过），本地 `check_all.py` 认得 75，但工作流那一步是
直接调脚本，于是干净 runner 上「没有样本可查」被当成了「查出问题」——这正是 DEF-10
要修的那个错，只是换到了 CI 上。

修法保持同一个原则：**跳过不是绿的另一种写法**。工作流里显式判断 75 并打出
`::notice::空库没有调用样本，SEC-07 判「跳过」而不是「通过」`，其余退出码仍然让整条失败。
本地按 CI 同样的空库环境验过（`init_schema` 后直接跑）：审计步 75 且**不写文件**
（上一份 230 行真证据没被冲掉，即 DEF-10 的修复仍生效）、`check_observe` 0、`check_compose` 0。

这一对红绿说明的是同一件事的两面：**红灯能定位到具体步骤和退出码，绿灯才有意义**。
