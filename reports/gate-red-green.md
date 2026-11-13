# 门禁红绿证据 · 第 9 / 10 课

> 课件判定口径：**先红后绿**才能证明门禁真的在挡。只留一次「绿」说明不了任何问题——
> 命令可能根本没在检查。课件明确规定四样齐，缺一即未完成：
> **① 改坏的那处 ② 红的一屏 ③ 修复提交 ④ 绿的一屏**。
>
> 本文件按这个顺序排，四样都在，且红绿两侧各有**本地**与**CI** 两份证据。

## 一、门禁覆盖面（六项）

| # | 目标 | 检查内容 |
| --- | --- | --- |
| 1 | `security` | SEC-05 密钥扫描 + SEC-06 依赖漏洞基线 |
| 2 | `async` | 第 8 课三条异步判据复现 |
| 3 | `apitest` | 第 9 课注入三件套反例（SQL / XSS / CSRF），20 条用例 |
| 4 | `audit` | SEC-07 审计七列结构断言 + 关联键断言 |
| 5 | `observe` | 第 10 课运行观测 5 条告警规则，`critical` 即红 |
| 6 | `compose` | 容器配置静态校验 11 项，不需要 Docker |

入口两条等价：`make check`（Linux / CI）、`pwsh -File scripts/check-all.ps1`（Windows 无 GNU make）。

## 二、① 改坏的那处：提交 `7f9af27`

```diff
--- a/campusclaw/request_context.py
+++ b/campusclaw/request_context.py
@@ def require_csrf() -> None:
-    if using_bearer_auth():
+    if True:  # 必红实验：临时跳过 Cookie 会话的 CSRF 校验（下一提交还原）
         return
     expected = session.get(CSRF_FIELD)
```

只动一个条件分支：原本只有 Bearer 令牌请求免 CSRF，改成**所有请求都免**。
提交号 `7f9af27`（`test(gate): 必红提交——临时跳过 Cookie 会话的 CSRF 校验`），已推送，
可 `git show 7f9af27` 复核。

## 三、② 红的一屏

### 本地（`pwsh -File scripts/check-all.ps1`）

```
=== [3/6] 第 9 课注入三件套（SQL / XSS / CSRF）===
=== 汇总：18/20 为绿，2 条为红；CHECK_EXIT=1 ===
存在未通过项，请查看上面的输出与 reports/evidence/ 中的 JSON
```

**退出码 1**。红的两条是同一处改动的两个侧面：CSRF 缺令牌的写请求本应 403，
实测变成 HTTP 200；更关键的是第二条——**被拒请求应无写入副作用**，实测正文被改写，
即伪造请求真的写进了数据。只看状态码不够，必须核副作用。

### CI（推送 `7f9af27` 后自动触发）

| 项 | 值 |
| --- | --- |
| run # | **6** |
| 提交 | `7f9af27` |
| 结论 | **failure** |
| 运行页 | https://github.com/Perry-xwr/campus-claw/actions/runs/43248188556 |

这一条回答的是课件第 10 课第 ③ 步的另一半要求：**「本地红则推送也失败」**。
本地红、CI 也红，说明挡住它的不是某个人的机器状态，而是入库的判定。

## 四、③ 修复提交：`f73a73e`

```
fix(gate): 还原 CSRF 校验，必红实验结束

上一提交 7f9af27 故意跳过 Cookie 会话的 CSRF 校验，apitest 因此 18/20
（CSRF 两条反例为红），门禁退出码 1。本提交把 require_csrf() 恢复为只对
Bearer 令牌放行，与 7f9af27 之前的代码逐字一致（git diff HEAD~1 为空）。
```

`git diff 7f9af27^ f73a73e -- campusclaw/request_context.py` 为空，
即「改坏 → 修复」之后代码与改坏前**逐字一致**，不是换一种写法把红绕过去。

## 五、④ 绿的一屏

### 本地

```
=== [6/6] 容器配置静态校验（不需要 Docker）===
全部检查通过；证据已归档到 reports/evidence/
=== 汇总：20/20 为绿，0 条为红；CHECK_EXIT=0 ===
```

**退出码 0**。同一条命令、同一份用例，代码状态变了退出码跟着变——这才叫门禁在判定。

### CI

| 项 | 值 |
| --- | --- |
| run # | **7** |
| 提交 | `f73a73e` |
| 结论 | **success**（28 秒） |
| 运行页 | https://github.com/Perry-xwr/campus-claw/actions/runs/43248376283 |

## 六、四样齐的对照

| 课件要求 | 本文件对应 | 是否齐 |
| --- | --- | --- |
| 改坏的那处 | 第二节，diff + `7f9af27` | 齐 |
| 红的一屏 | 第三节，本地 `18/20 CHECK_EXIT=1` + CI run #6 failure | 齐 |
| 修复提交 | 第四节，`f73a73e`，且证明与改坏前逐字一致 | 齐 |
| 绿的一屏 | 第五节，本地 `20/20 CHECK_EXIT=0` + CI run #7 success | 齐 |

## 七、入口收敛后的补充红绿（2026-11-13）

2026-11-13 把门禁入口从「三套清单」收敛成单一 `scripts/check_all.py`（提交 `baf68b0`，
`Makefile` 的 `check:` 与六个单项目标都改为 `--only` 转发）。收敛本身也要证明「它还挡得住」，
所以又做了两侧验证。

### 7.1 红：把 compose 配置改坏

在干净副本的 `docker-compose.yml` 末尾追加一行不闭合的 YAML：

```yaml
  bad_indent: [unclosed
```

跑 `scripts/check_all.py --only compose`：

```
expected ',' or ']', but got '<stream end>'
  in "<unicode string>", line 115, column 1:

步骤         项                         结果       耗时
compose    容器配置静态校验             未通过(1)   0.5s
合计 1 项，通过 0，未通过 1              → 退出码 1
```

### 7.2 绿：干净目录里跑全套

`git archive HEAD` 导出干净目录 + 全新 venv + 清华镜像装依赖（3 分 8 秒），随后跑门禁：

| 步骤 | 项 | 结果 |
| --- | --- | --- |
| security | SEC-05 密钥扫描 + SEC-06 依赖基线 | 通过 |
| async | 第 8 课三条判据 | 通过 |
| apitest | 第 9 课注入三件套 | 通过 |
| audit | SEC-07 审计七列回查 | **跳过** |
| observe | 第 10 课运行观测判定 | 通过 |
| compose | 容器配置静态校验 | 通过 |

**合计 6 项，通过 5，跳过 1，未通过 0，退出码 0。** 原文见 `reports/evidence/gate-clean-dir.md`。

### 7.3 第三个状态：跳过（DEF-10）

上表里 `audit` 是「跳过」而不是「通过」，这是 2026-11-13 修掉的缺陷带来的变化。

**修之前**：`audit_recheck.py` 在 `--allow-empty` 下遇到「时间窗内 0 条记录」不追加失败项，
判定段只有「有失败 → 红 / 否则 → 绿」两个分支，于是写出 `**绿**：七列齐备，拒绝尝试有留痕`。
而同一份报告的表格里，七列全标「缺」。更要紧的是它会**覆盖**仓库里那份真实的回查记录
（229 行 → 33 行，`git diff` 是 −222 行）。

**修之后**：三态 + 退出码约定 + 无样本不覆盖。三条分支实测：

| 场景 | 命令 | 判定 | 退出码 | 写不写文件 |
| --- | --- | --- | --- | --- |
| 无样本 + 放行（门禁默认路径） | `--db data/app.db --allow-empty` | 跳过（无样本） | **0** | 不写 |
| 有样本 | `--db data/app.db`（默认不限窗口） | 绿（8 条，七列齐备 8 条） | **0** | 写 |
| 无样本 + 不放行 | `--window-minutes 1` | 红（无调用 + `audit_events` 为空） | **1** | 写 |

**反证**：干净目录那次跑完，`reports/audit-recheck.md` 仍是提交里那份 **230 行、8 条调用、
35 条拒绝** 的记录，一个字节没变；而那个目录的库确实是空的（`mcp_tool_calls` 0 条、
`audit_events` 0 条）。修之前，这一跑就会把它清空。

## 八、历史：四项门禁时期的红绿（第 9 课，保留原文结论）

第 9 课当时门禁只有四项（security / async / apitest / audit），同样做过 0 → 1 → 0：

| 次序 | 代码状态 | 提交号 | 退出码 | 结果 |
| --- | --- | --- | --- | --- |
| ① 基线 | 未改动 | `e60801c` | **0** | apitest 8/8 绿 |
| ② 必红 | 临时跳过 CSRF（未提交） | `e60801c` + `red-submit.patch` | **1** | apitest 6/8，两条 CSRF 变红 |
| ③ 还原后 | `git checkout --` | `e60801c` | **0** | apitest 8/8 绿 |

当时的必红改动**没有单独提交**（用 patch 文件反查），不满足课件「修复提交」一项；
本轮已补成真实提交对。原始日志仍在 `reports/evidence/gate-green.log`、
`gate-red.log`、`gate-green-after-fix.log`、`red-submit.patch`。

顺带记录的入口缺陷（DEF-02）：Windows PowerShell 5.1 把原生命令写 stderr 的 Flask
访问日志当成终止错误，`$ErrorActionPreference = "Stop"` 让脚本在第一项就中断。
处置：`scripts/check-all.ps1` 里加 `Invoke-Check`，调用原生命令期间放宽为
`Continue`，判定只看 `$LASTEXITCODE`。

> 该脚本已于 2026-11-13 入口收敛时删除（`check_all.py` 用 `subprocess` 直接取返回码，
> 不经过 PowerShell 的错误偏好，这个坑随之消失）。此段保留，作为「为什么要收敛入口」的旁证。

## 九、仍未做到的一项

| 项 | 现状 |
| --- | --- |
| 主干分支保护（合并前必须绿） | **未开启**。需要在 GitHub 仓库设置里手动勾选，代码侧无法完成 |

门禁本身已经会红会绿、CI 已在跑；但「不绿就不许合入」这一层要仓库管理员在设置里开。
