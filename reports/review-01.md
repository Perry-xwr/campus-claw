# 交叉评审记录 · 01 · 第 8 课

> 最终项目报告「审核记录」一节的第一份。格式固定为四件事：用什么手段查 / 查了什么 / 判据 / 结果。

- **用什么手段查**：照 `reports/security-precheck.md` 的清单，在**独立进程、独立隔离 `CAMPUSCLAW_HOME`** 中重跑 `uv run python scripts/acceptance_security.py`，不读取第一次的结论、不复用第一次的登录令牌与数据库；复现记录见 `reports/evidence/security-precheck-recheck.json`（生成时间 `2026-11-04T10:35:07+00:00`）。
- **查了什么**：SEC-01～SEC-07 中抽 **2 条**——SEC-02（跨班访问与跨班检索）、SEC-03（学生修改技能与提示词），另核对整体红/绿分布。选择理由是这两条分别覆盖「读」与「写」两条越权路径，且判定依赖具体返回码与数据库前后值，不能靠目测得结论。
- **判据**：SEC-02 复现得 404 与空结果（且本班对照有结果）、SEC-03 复现得 403 且配置数据不变，与原记录判定一致才算过。
- **结果**：**两条复现值与原记录一致，判定一致，通过**。整体分布亦一致：原记录 7 条 / 6 绿 1 红，复现 7 条 / 6 绿 1 红，红同样落在 SEC-07。

## 两条逐项对照

| 条目 | 原记录（`security-precheck.json`） | 复现（`security-precheck-recheck.json`） | 是否一致 |
| --- | --- | --- | --- |
| SEC-02 跨班访问 | `GET /api/materials/2 → 404` | `GET /api/materials/2 → 404` | 一致 |
| SEC-02 跨班检索 | A1 搜 `B_ONLY_SEED` → 0 条；B1 搜 `A_ONLY_SEED` → 0 条 | 同左（0 条 / 0 条） | 一致 |
| SEC-02 本班对照 | A1 搜 `A_ONLY_SEED` → 1 条 | 1 条 | 一致 |
| SEC-02 判定 | 绿 | 绿 | 一致 |
| SEC-03 `PUT /api/prompt` | 403 | 403 | 一致 |
| SEC-03 `POST /api/skills` | 403 | 403 | 一致 |
| SEC-03 数据变化 | `class_prompts` 未变、`class_skills` 仍 2 条 | 同左 | 一致 |
| SEC-03 判定 | 绿 | 绿 | 一致 |
| 汇总 | 7 条 / 6 绿 1 红 | 7 条 / 6 绿 1 红 | 一致 |

## 复现命令（原样可跑）

```powershell
# 第一次（原记录）
uv run python scripts/acceptance_security.py --out reports/evidence/security-precheck.json

# 第二次（独立进程复现，换一份隔离目录，不复用上面的输出）
uv run python scripts/acceptance_security.py --out reports/evidence/security-precheck-recheck.json

# 对照两份 JSON 的 records[].可观测结果.当前判定
```

## 审核意见与处置

- **可用**：SEC-01～SEC-06 的记录有具体命令、具体返回码与具体条数，可重复跑出同一个值，判定为绿有依据。
- **待修改**：SEC-06 属降级路径（未在线比对漏洞库），已在 `reports/security-baseline.md` 如实标注并登记处置方式；后续课次联网后需补 `pip-audit` 输出并更新基线。
- **保留的红**：SEC-07 审计日志缺「技能标识 / 耗时 / 用量」，两次复现均为红，**本课不修复**，留给后续课次当堂从红改到绿并归档修复前后证据。

## 诚实声明

本记录由 AI 辅助执行，两次复现是**两个独立进程、两份隔离数据**的真实运行结果，可原样复核；但任务清单要求的「组内另一人」交叉评审仍需由组内同学照清单独立再跑至少 2 条并**签名确认**。本文件是可复核的底稿，签字栏留空，不得冒名填写：

| 角色 | 姓名 | 复现条目 | 日期 | 签名 |
| --- | --- | --- | --- | --- |
| 原记录执行 |  | SEC-01～SEC-07 |  |  |
| 独立复现（组内另一人） |  | SEC-02、SEC-03 |  | 待补 |
