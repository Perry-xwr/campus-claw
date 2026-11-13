# 审计日志回查（SEC-07）

- 生成时间：2026-11-13 21:10:24
- 数据库：`data/app.db`
- 时间窗：不限（全部历史，原文只列最近 5 条）
- 技能调用记录：8 条，七列齐备 8 条
- 最近一条调用：`2026-11-12T16:09:02.936108+00:00`（距今 21 小时）
- 拒绝尝试记录：35 条
- 关联键断言：通过（有用户名的记录均带 actor_id）
- 表结构断言：通过（七列齐备）

## 七列断言

| 列 | 含义 | 首条记录取值 | 判定 |
| --- | --- | --- | --- |
| `actor` | 操作人 | `student_a1` | 有 |
| `created_at` | 操作时间 | `2026-11-12T16:09:02.936108+00:00` | 有 |
| `action` | 操作类型 | `skill.invoke` | 有 |
| `object_id` | 操作对象 | `6` | 有 |
| `status` | 结果状态 | `ok` | 有 |
| `skill_id` | 技能标识 | `公式加换算` | 有 |
| `duration_ms` | 用量与耗时 | `37` | 有 |

## 回查原文（技能调用）

```json
[
  {
    "id": 8,
    "created_at": "2026-11-12T16:09:02.936108+00:00",
    "action": "skill.invoke",
    "object_id": "6",
    "status": "ok",
    "skill_id": "公式加换算",
    "duration_ms": 37,
    "tokens": null,
    "request_id": "req-bf242df4363a",
    "tool_ref": "unit_convert@campus-tools",
    "actor": "student_a1",
    "server_name": "campus-tools"
  },
  {
    "id": 7,
    "created_at": "2026-11-12T16:09:02.895612+00:00",
    "action": "skill.invoke",
    "object_id": "6",
    "status": "ok",
    "skill_id": "公式加换算",
    "duration_ms": 35,
    "tokens": null,
    "request_id": "req-bf242df4363a",
    "tool_ref": "formula_hint@campus-tools",
    "actor": "student_a1",
    "server_name": "campus-tools"
  },
  {
    "id": 6,
    "created_at": "2026-11-12T16:09:02.786302+00:00",
    "action": "skill.invoke",
    "object_id": "5",
    "status": "ok",
    "skill_id": "单位换算",
    "duration_ms": 37,
    "tokens": null,
    "request_id": "req-b1fa71452184",
    "tool_ref": "unit_convert@campus-tools",
    "actor": "student_a1",
    "server_name": "campus-tools"
  },
  {
    "id": 5,
    "created_at": "2026-11-12T16:09:02.703790+00:00",
    "action": "skill.invoke",
    "object_id": "4",
    "status": "ok",
    "skill_id": "公式提示",
    "duration_ms": 41,
    "tokens": null,
    "request_id": "req-7ea17d78b4f1",
    "tool_ref": "formula_hint@campus-tools",
    "actor": "student_a1",
    "server_name": "campus-tools"
  },
  {
    "id": 4,
    "created_at": "2026-11-12T16:08:42.533738+00:00",
    "action": "skill.invoke",
    "object_id": "3",
    "status": "denied",
    "skill_id": "公式加换算",
    "duration_ms": 0,
    "tokens": null,
    "request_id": "req-6acd44a1d034",
    "tool_ref": "unit_convert@campus-tools",
    "actor": "student_a1",
    "server_name": "campus-tools"
  }
]
```

## 回查原文（被拒绝的尝试）

```json
[
  {
    "id": 35,
    "ts": "2026-11-12T16:16:15.732633+00:00",
    "request_id": "req-2b0cbc75cb81",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/submissions",
    "method": "POST",
    "path": "/api/submissions",
    "status": 202,
    "code": "OK",
    "duration_ms": 8
  },
  {
    "id": 34,
    "ts": "2026-11-12T16:16:15.718768+00:00",
    "request_id": "req-14f3df9e845d",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/submissions",
    "method": "POST",
    "path": "/api/submissions",
    "status": 202,
    "code": "OK",
    "duration_ms": 8
  },
  {
    "id": 33,
    "ts": "2026-11-12T16:16:15.693617+00:00",
    "request_id": "req-21c1000fa54c",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/submissions",
    "method": "POST",
    "path": "/api/submissions",
    "status": 202,
    "code": "OK",
    "duration_ms": 7
  },
  {
    "id": 32,
    "ts": "2026-11-12T16:16:15.682193+00:00",
    "request_id": "req-c0ee59fb8e3c",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/submissions",
    "method": "POST",
    "path": "/api/submissions",
    "status": 202,
    "code": "OK",
    "duration_ms": 7
  },
  {
    "id": 31,
    "ts": "2026-11-12T16:16:09.399211+00:00",
    "request_id": "req-70d4ccd187ff",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /login",
    "method": "POST",
    "path": "/login",
    "status": 302,
    "code": "OK",
    "duration_ms": 208
  },
  {
    "id": 30,
    "ts": "2026-11-12T16:13:51.022567+00:00",
    "request_id": "req-f221bcdbecb0",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 4
  },
  {
    "id": 29,
    "ts": "2026-11-12T16:13:51.012985+00:00",
    "request_id": "req-982e140aa3dc",
    "actor": "teacher_b",
    "actor_id": 4,
    "class_id": 2,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 4
  },
  {
    "id": 28,
    "ts": "2026-11-12T16:13:50.991047+00:00",
    "request_id": "req-52bf01d8a5dd",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 4
  }
]
```

## 判定

**绿**：七列齐备，拒绝尝试有留痕，按技能标识加时间窗可回查。
