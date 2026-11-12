# 门禁红绿证据 · 第 9 / 10 课

> 判定口径：**先红后绿**才能证明门禁真的在挡。只留一次"绿"说明不了任何问题——命令可能根本没在检查。
> 归档命令与输出原文，不只写结论。

- **基线提交**：`475eb45aee68eead668cfe0cbcc9667ed8f3e334`（`Merge pull request #3 from Perry-xwr/docs/project-documentation-refresh`）
- **门禁命令**：`make check`（本机无 GNU make，等价入口 `pwsh -File scripts/check-all.ps1`）
- **门禁覆盖面**：SEC-05 密钥扫描 + SEC-06 依赖基线 → 第 8 课三条异步判据 → 第 9 课注入三件套（本次新接入）
- **原始日志**：`reports/evidence/gate-green.log`、`reports/evidence/gate-red.log`、`reports/evidence/gate-green-after-fix.log`

## 一、三次运行

| 次序 | 代码状态 | 提交号 | 退出码 | 用例结果 | 判定 |
| --- | --- | --- | --- | --- | --- |
| ① 基线 | 未改动 | `475eb45` | **0** | apitest 8/8 绿；SEC-05 0 命中；异步判据全绿 | 绿 |
| ② 必红提交 | 故意跳过 CSRF 校验（工作区改动，未提交） | `475eb45` + `red-submit.patch` | **1** | apitest **6/8**，`CSRF：缺令牌的写请求被拒`、`CSRF：被拒请求无写入副作用` 两条变红 | 红（符合预期） |
| ③ 还原后 | `git checkout -- campusclaw/request_context.py` | `475eb45` | **0** | apitest 8/8 绿 | 绿 |

①与③同为 0、②为 1，退出码随代码状态变化，说明门禁确实在执行判定，而不是恒定返回 0。

## 二、必红改动内容

来源：`reports/evidence/red-submit.patch`

```diff
--- a/campusclaw/request_context.py
+++ b/campusclaw/request_context.py
@@ -132,7 +132,7 @@ def require_csrf() -> None:
      Bearer 令牌请求不要求 CSRF：令牌由客户端显式携带，不随浏览器自动发送，
      不存在跨站伪造面；Cookie 会话仍强制校验。
      """
-    if using_bearer_auth():
+    if True:  # 必红实验：临时跳过 Cookie 会话的 CSRF 校验
         return
     expected = session.get(CSRF_FIELD)
     provided = submitted_csrf_token()
```

改动只动一个条件分支，语义是"所有请求都跳过 CSRF 校验"。**该改动实验后已用 `git checkout` 还原，未进入任何提交**，因此没有独立的必红提交号，改用基线提交号 + patch 文件反查。

## 三、②必红运行的实测输出（关键行）

```
[红] CSRF：缺令牌的写请求被拒
      实测：HTTP 200，错误码 None
[红] CSRF：被拒请求无写入副作用
      实测：正文被改写为 'CSRF_PROBE_9B 伪造写入'
=== 汇总：6/8 为绿，2 条为红；CHECK_EXIT=1 ===
```

两处红是同一处改动的两个侧面：伪造请求从"应被 403 拒绝"变成"放行并真的写入了数据"——正是 `require_csrf` 被跳过后的预期表现。

## 四、顺带修复的入口缺陷（DEF-02）

首次执行一键入口时门禁在第一项就中断，退出码为空：

```
& : 无法加载文件 ...\scripts\check-all.ps1，因为在此系统上禁止运行脚本
```

放开执行策略后仍然中断，真正的成因是脚本内的 `$ErrorActionPreference = "Stop"`：

```
python.exe : 127.0.0.1 - - [12/Nov/2026 09:24:10] "POST /api/login HTTP/1.1" 200 -
    + FullyQualifiedErrorId : NativeCommandError
```

Windows PowerShell 5.1 把原生命令写入 stderr 的内容（Flask 的访问日志）当成**终止错误**，`Stop` 直接把它升级成中断，脚本没走到汇总就退出。PowerShell 7 下不会出现，所以开发机器上看不见。

处置：在 `scripts/check-all.ps1` 中加一层 `Invoke-Check`，调用原生命令期间临时把 `$ErrorActionPreference` 放宽为 `Continue`，判定仍只看 `$LASTEXITCODE`。修复后三次运行均正常返回退出码。

同一处还发现一个覆盖缺口：原脚本 `check` 只包含 security + async 两项，第 9 课的反例三件套不在门禁内。已在 `Makefile` 的 `check` 目标与 `check-all.ps1` 的 `all` 模式中补入第三项。

## 五、还没做到的（如实标注）

| 课件要求 | 现状 |
| --- | --- |
| 门禁挂进 CI、主干分支保护 | **未接入**。仓库无 `.github/`、`.gitlab-ci.yml` 或 Jenkinsfile，门禁只能靠人手动执行 |
| 推送即构建 | **未实现**。无 CI 触发、无镜像产物、镜像编号无法反查提交 |
| `make check` 直接可用 | 本机无 GNU make，只有 PowerShell 等价入口；Linux/CI 环境可直接用 `make check` |

也就是说，当前只是"一条命令红了挡住合并"的**脚本级门禁**，距离课件定义的"门禁"（挂进 CI 且主干保护、退出码非 0 就进不去）还差接入那一步。这条差距不能靠脚本本身补齐。
