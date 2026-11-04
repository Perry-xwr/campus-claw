# 资产类基线 · 密钥扫描与依赖审计 · 第 8 课

> 归档命令与输出原文，不只写结论。生成时间 `2026-11-04T10:28:07+00:00`；原始 JSON：`reports/evidence/security-baseline.json`。
> 入口：`make check-security`（Windows 等价 `pwsh -File scripts/check-all.ps1 -Mode security`）。

## SEC-05 密钥明文泄漏扫描

**命令**

```powershell
uv run python scripts/check_security.py --out reports/evidence/security-baseline.json
# 或 make check-security
```

**扫描范围**：全量提交历史（`git rev-list --all` 逐个提交 `git grep`）、前端产物（`campusclaw/templates`、`docs`、`scripts`、`apitest`、`mcp-server` 与仓库根文件）、运行日志（含被 `.gitignore` 忽略的 `.run/logs/*.log`）。

**输出原文（关键行）**

```
=== CampusClaw 第 8 课安全基线 · make check-security ===
生成时间：2026-11-04T10:28:07+00:00
[SEC-05 密钥明文泄漏扫描] 扫描提交 10 个、前端产物 137 个文件、运行日志 6 个文件
  扫描提交历史 …… 通过（0 命中）
  扫描前端产物 …… 通过（0 命中）
  扫描运行日志 …… 通过（0 命中）
  真实密钥明文命中：0
  公开演示常量（已登记，不计入）：2
  判定：绿
CHECK_EXIT=0
```

> 注：安全自查脚本运行时的前端产物计数为 **139**（比本次基线多 2 个，因验收脚本与本报告相关文件陆续落盘）；两次运行的真实密钥命中数均为 **0**。以各自 JSON 中记录的数字为准，不合并成一个数。

**命中明细与处置（2 条公开演示/测试常量，均非第三方密钥）**

| 文件 | 行 | 内容 | 判定 |
| --- | --- | --- | --- |
| `docs/上手教程.md` | 537 | ``$env:MCP_AUTH_TOKEN = "campusclaw-mcp-demo-token"`` | 文档示例固定值，非密钥；登记备查，不轮换 |
| `scripts/acceptance_compose.py` | 71 | `SECRET_KEY = "campusclaw-verify-secret-key-0123456789abcdef"` | 验收脚本固定值，仅容器验收用；登记备查，不轮换 |

扫描器把这两类值显式列入 `DEMO_CONSTANT` 白名单并单独输出，**不是静默过滤**；占位符（`sk-xxx`、`...`、`<...>`、`${...}`、`synthetic-*`）另有 `PLACEHOLDER` 规则。真实模型密钥（`CHAT_API_KEY` / `EMBEDDING_API_KEY` / `MCP_AUTH_TOKEN`）只存于本机 `.env`，`.gitignore` 已忽略且从未进入提交历史（全历史 `git log -p -- .env` 为空）。

**判定**：真实密钥明文 **0 命中**，绿。若将来出现真实命中，必须立刻轮换并把明文从历史中清掉，本课「只记录不修复」的规则对密钥明文不适用。

## SEC-06 依赖漏洞基线

**命令**：`make check-security` 的依赖审计部分。脚本先探测 `python -m pip_audit --version`；可用则执行 `pip-audit --format json -r requirements.txt` 在线比对并统计高危/严重数量；不可用则走下面的离线登记分支。

**输出原文（关键行）**

```
[SEC-06 依赖漏洞基线] 离线依赖清单基线（未完成在线漏洞库比对）
  声明依赖 10 项，本机已安装 9 项
  高危/严重：未知（未在线比对）
  处置：本机未安装 pip-audit 且离线，无法给出高危/严重数量；
        按任务清单「高危清零，或书面登记处置方式」中的后一种处理：
        依赖全部按 requirements.txt / uv.lock 钉死版本，
        仅内部部署、无对外输入面；后续课次联网跑 pip-audit 后复测并更新本报告。
    - bcrypt==4.2.1
    - Flask==3.1.1
    - langchain-mcp-adapters==0.3.2
    - langchain-openai==1.4.1
    - langchain-text-splitters==1.1.3
    - mcp==1.30.0
    - qdrant-client==1.19.1
    - uvicorn==0.54.0
    - Werkzeug==3.1.8
```

**降级如实标注**：本机未安装 `pip-audit`，且本课不联网，**未完成在线漏洞库比对**，因此高危/严重数量记为「未知」，不写「高危 0」。`gunicorn==23.0.0` 在 `pyproject.toml` 中带 `sys_platform != 'win32'` 标记，Windows 本机未安装，故「声明 10 项 / 已安装 9 项」的差异是预期行为，不是缺失依赖。

**书面登记的处置方式**：

1. 直接依赖全部在 `requirements.txt` 钉死版本，传递依赖由 `pyproject.toml` 的 `constraint-dependencies` 与 `uv.lock` 锁定，不做浮动升级。
2. 部署形态为课程演示的单机内网实例，无对外输入面；模型密钥不进镜像层。
3. 后续课次联网后执行 `pip-audit -r requirements.txt`，把高危/严重数量与逐条处置结论补进本文件，并复跑 `make check-security` 更新 JSON。

**判定**：绿（走「高危清零，**或**书面登记处置方式」的后一种分支）。

## 一键入口与归档

| 命令 | 输出 |
| --- | --- |
| `make check-security` | 本文件对应的 `reports/evidence/security-baseline.json` |
| `make check-async` | `reports/evidence/async-acceptance.json` |
| `make check` | 以上两项 |
| `pwsh -File scripts/check-all.ps1` | Windows 等价入口，自动探测项目 `.venv` |

入口已在 `README.md` 的「第 8 课：异步任务、安全自查与代码审核」一节注明。最终项目报告「审核记录」与「门禁」两节可直接复跑本命令，输出对不上即查不实。
