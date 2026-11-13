# 干净目录跑门禁：5 通过 / 1 跳过 / 0 未通过，退出码 0

**时间**：2026-11-13 21:14
**代码**：`git archive HEAD` 导出（提交 `550f56a`）
**环境**：全新 `venv`（本机 CPython 3.11）+ 清华镜像装依赖，用时 3 分 8 秒
**命令**：`.venv/Scripts/python.exe scripts/check_all.py`

## 怎么造出这个环境

```bash
cd /d/campus-claw
mkdir -p .acc10/clean-check2 && git archive HEAD | tar -x -C .acc10/clean-check2
cd .acc10/clean-check2
"<本机 CPython 3.11>" -m venv .venv
.venv/Scripts/python.exe -m pip install -q \
    -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt PyYAML==6.0.3
```

新目录里没有 `.venv`、没有 `data/`、没有 `.env`；依赖全部现装，不继承源目录任何包。

## 完整输出

```text
[门禁] security   SEC-05 密钥扫描 + SEC-06 依赖基线 …
[门禁] async      第 8 课三条判据 …
[门禁] apitest    第 9 课注入三件套 …
[门禁] audit      SEC-07 审计七列回查 …
[门禁] observe    第 10 课运行观测判定 …
[门禁] compose    容器配置静态校验 …
跳过的项没有产出证据（例：库里还没有可回查的调用），不得在报告里计为通过。

-----------------------------------------------
步骤         项                         结果       耗时
-----------------------------------------------
security   SEC-05 密钥扫描 + SEC-06 依赖基线 通过         9.7s
async      第 8 课三条判据                 通过        21.6s
apitest    第 9 课注入三件套                通过        13.8s
audit      SEC-07 审计七列回查             跳过         1.1s
observe    第 10 课运行观测判定              通过         1.1s
compose    容器配置静态校验                  通过         8.6s
-----------------------------------------------
合计 6 项，通过 5，跳过 1，未通过 0
```

退出码 **0**（同一命令连跑两次结果一致，第一次 3 分 8 秒建环境、第二次直接跑 60 秒）。

## 为什么 `audit` 是「跳过」

这个库是门禁当场按 schema 建的，`mcp_tool_calls` 与 `audit_events` 都是 0 条——没有可回查的调用。

修复前（DEF-10），这里会写出「绿灯：七列齐备」，而同一份报告的表格里七列全标「缺」；更糟的是它会**覆盖**仓库里那份真实的回查记录。现在它判定「跳过（无样本）」，汇总表单列一栏，且不写文件。

## 反证：它没有冲掉那 8 条证据

跑完之后，干净目录里的 `reports/audit-recheck.md` 仍是提交里那份 **230 行、8 条调用、35 条拒绝** 的记录，一个字节没变：

```text
$ wc -l < reports/audit-recheck.md
230
$ head -6 reports/audit-recheck.md
# 审计日志回查（SEC-07）

- 生成时间：2026-11-13 21:10:24
- 数据库：`data/app.db`
- 时间窗：不限（全部历史，原文只列最近 5 条）
- 技能调用记录：8 条，七列齐备 8 条
```

而那个目录的库确实是空的：

```text
$ python -c "import sqlite3; c=sqlite3.connect('data/app.db'); \
  print('mcp_tool_calls:', c.execute('select count(*) from mcp_tool_calls').fetchone()[0]); \
  print('audit_events:', c.execute('select count(*) from audit_events').fetchone()[0])"
mcp_tool_calls: 0
audit_events: 0
```

## 这一跑证明了什么、没证明什么

**证明**：一份不带 `data/`、不带 `.venv`、不带 `.env` 的干净代码，按依赖清单装完就能把门禁跑到退出码 0；六项里没有一项因为「文件缺失」而跳过（跳过的那项是因为库里没有数据，不是文件缺失）。

**没证明**：字面执行 `make check`。本机没有 GNU make，跑的是 `Makefile` 里 `check:` 目标的唯一一行 `python scripts/check_all.py`。另外依赖来自清华镜像，官方 PyPI 在本机超时——这属于外部网络条件，不影响「依赖清单是否完整」的结论。
