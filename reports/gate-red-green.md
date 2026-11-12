# 门禁红绿证据 · 第 9 / 10 课

> 判定口径：**先红后绿**才能证明门禁真的在挡。只留一次「绿」说明不了任何问题——命令可能根本没在检查。
> 归档命令与输出原文，不只写结论。

- **提交基线**：`e60801c`（`feat(gate): 门禁扩到四项并接入 CI，补注入三件套与压测基线`）
- **门禁命令**：`make check`（本机无 GNU make，等价入口 `pwsh -File scripts/check-all.ps1`）
- **门禁覆盖面（四项）**：
  1. `check-security` — SEC-05 密钥扫描 + SEC-06 依赖基线
  2. `check-async` — 第 8 课三条异步判据
  3. `check-apitest` — 第 9 课注入三件套（SQL / XSS / CSRF）
  4. `check-audit` — SEC-07 审计七列回查（结构断言 + 数据断言）
- **原始日志**：`reports/evidence/gate-green.log`、`reports/evidence/gate-red.log`、`reports/evidence/gate-green-after-fix.log`

## 一、三次运行

| 次序 | 代码状态 | 提交号 | 退出码 | 用例结果 | 判定 |
| --- | --- | --- | --- | --- | --- |
| ① 基线 | 未改动 | `e60801c` | **0** | apitest 8/8 绿；SEC-05 真实密钥 0 命中；异步判据全绿；审计七列齐备 | 绿 |
| ② 必红 | 临时跳过 CSRF 校验（未提交） | `e60801c` + `red-submit.patch` | **1** | apitest **6/8**，两条 CSRF 用例变红 | 红（符合预期） |
| ③ 还原后 | `git checkout -- campusclaw/request_context.py` | `e60801c` | **0** | apitest 8/8 绿 | 绿 |

①与③为 0、②为 1，退出码随代码状态变化，说明门禁确实在执行判定，而不是恒定返回 0。①与③代码状态相同，因此两份日志内容一致（均归档，便于逐行比对）。

## 二、必红改动内容

来源：`reports/evidence/red-submit.patch`（本次为干净补丁，只含这一处改动）

```diff
--- a/campusclaw/request_context.py
+++ b/campusclaw/request_context.py
@@ -137,7 +137,7 @@ def require_csrf() -> None:
     Bearer 令牌请求不要求 CSRF：令牌由客户端显式携带，不随浏览器自动发送，
     不存在跨站伪造面；Cookie 会话仍强制校验。
     """
-    if using_bearer_auth():
+    if True:  # 必红实验：临时跳过 Cookie 会话的 CSRF 校验
         return
     expected = session.get(CSRF_FIELD)
     provided = submitted_csrf_token()
```

改动只动一个条件分支，语义是「所有请求都跳过 CSRF 校验」。**实验后已用 `git checkout` 还原，未进入任何提交**，因此没有独立的必红提交号，用基线提交号 + patch 文件反查。

## 三、②必红运行的实测输出（关键行）

```
  [红] CSRF：缺令牌的写请求被拒
        实测：HTTP 200，错误码 None
  [红] CSRF：被拒请求无写入副作用
        实测：正文被改写为 'CSRF_PROBE_9B 伪造写入'
=== 汇总：6/8 为绿，2 条为红；CHECK_EXIT=1 ===
```

两处红是同一处改动的两个侧面：伪造请求从「应被 403 拒绝」变成「放行并真的写入了数据」。注意第二条——**只看状态码不够**，必须核副作用是否发生，否则「放行但没写进去」会被误判为绿。

## 四、顺带修复的入口缺陷（DEF-02）

首次执行一键入口时门禁在第一项就中断，退出码为空：

```
& : 无法加载文件 ...\scripts\check-all.ps1，因为在此系统上禁止运行脚本
```

放开执行策略后仍然中断，真正成因是脚本内的 `$ErrorActionPreference = "Stop"`：

```
python.exe : 127.0.0.1 - - [12/Nov/2026 09:24:10] "POST /api/login HTTP/1.1" 200 -
    + FullyQualifiedErrorId : NativeCommandError
```

Windows PowerShell 5.1 把原生命令写入 stderr 的内容（Flask 访问日志）当成**终止错误**，`Stop` 直接把它升级成中断，脚本没走到汇总就退出。PowerShell 7 下不出现，所以开发机上永远看不见。

处置：在 `scripts/check-all.ps1` 中加 `Invoke-Check`，调用原生命令期间临时把 `$ErrorActionPreference` 放宽为 `Continue`，判定仍只看 `$LASTEXITCODE`。

## 五、门禁覆盖面变化

| 版本 | 覆盖面 | 退出码实测 |
| --- | --- | --- |
| 第 8 课 | security + async（2 项） | 未做红绿实验 |
| 第 9 课中途 | security + async + apitest（3 项） | 0 → 1 → 0 |
| **本次** | security + async + apitest + **audit**（4 项） | **0 → 1 → 0** |

新增的第四项（`check-audit`）在干净环境用 `--allow-empty` 跳过数据断言、只做结构断言；在有运行库的环境（`CAMPUSCLAW_AUDIT_DB` 指向它）则连数据一起断言。这样 CI 与本地都能跑同一条命令。

## 六、CI 接入状态（如实标注）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 工作流文件 | **已写入** | `.github/workflows/check.yml`，push / PR / 手动触发，步骤与 `make check` 一一对应 |
| 依赖安装 | 已用 `uv sync --locked` | 锁文件已改为官方源，「换机器能装上」重新成立 |
| 证据归档 | 已用 `upload-artifact@v4` | 上传 `reports/evidence/` 与 `reports/audit-recheck.md` |
| **在 GitHub 上真跑过一次** | **没有** | 本机无 `gh`、无远端写权限，只能确认配置文件语法正确，无法确认 Actions 实际通过 |
| 主干分支保护 | **没有** | 需要在 GitHub 仓库设置里手动开启，代码侧无法完成 |

这一点必须写清楚：**「工作流文件写好了」和「推送即构建验证过」是两件事**。前者是配置，后者是证据。当前只有前者。

## 七、还没做到的

| 课件要求 | 现状 |
| --- | --- |
| CI 实跑记录（绿色运行页链接） | 缺。需要推到 GitHub 之后才有运行记录 |
| 主干分支保护 | 缺。需仓库管理员在设置里开启 |
| `make check` 直接可用 | 本机无 GNU make，只有 PowerShell 等价入口；Linux/CI 环境可直接 `make check` |
