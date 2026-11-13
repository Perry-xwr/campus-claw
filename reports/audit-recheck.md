# 审计日志回查（SEC-07）

- 生成时间：2026-11-13 23:21:29
- 数据库：`data/app.db`
- 时间窗：不限（全部历史，原文只列最近 5 条）
- 技能调用记录：8 条，七列齐备 8 条
- 最近一条调用：`2026-11-12T16:09:02.936108+00:00`（距今 23 小时）
- 拒绝尝试记录：50 条
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
    "id": 105,
    "ts": "2026-11-13T15:10:32.072197+00:00",
    "request_id": "req-f67f38dada16",
    "actor": "teacher_b",
    "actor_id": 4,
    "class_id": 2,
    "action": "api.request",
    "object_id": "PUT /api/prompt",
    "method": "PUT",
    "path": "/api/prompt",
    "status": 200,
    "code": "OK",
    "duration_ms": 12
  },
  {
    "id": 104,
    "ts": "2026-11-13T15:10:00.248531+00:00",
    "request_id": "req-2ff8b26cf8b3",
    "actor": "teacher_b",
    "actor_id": 4,
    "class_id": 2,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 3
  },
  {
    "id": 103,
    "ts": "2026-11-13T15:09:59.890963+00:00",
    "request_id": "req-4ece242e135e",
    "actor": "teacher_b",
    "actor_id": 4,
    "class_id": 2,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 3
  },
  {
    "id": 102,
    "ts": "2026-11-13T15:09:53.803739+00:00",
    "request_id": "req-15a886e45de4",
    "actor": "teacher_b",
    "actor_id": 4,
    "class_id": 2,
    "action": "api.request",
    "object_id": "POST /api/materials/8/reindex",
    "method": "POST",
    "path": "/api/materials/8/reindex",
    "status": 202,
    "code": "OK",
    "duration_ms": 13
  },
  {
    "id": 101,
    "ts": "2026-11-13T15:09:43.009491+00:00",
    "request_id": "req-61a5f2f13e70",
    "actor": "teacher_b",
    "actor_id": 4,
    "class_id": 2,
    "action": "api.request",
    "object_id": "POST /api/materials/upload",
    "method": "POST",
    "path": "/api/materials/upload",
    "status": 201,
    "code": "OK",
    "duration_ms": 14
  },
  {
    "id": 100,
    "ts": "2026-11-13T15:09:42.759986+00:00",
    "request_id": "req-f8dcdb640a4a",
    "actor": "teacher_b",
    "actor_id": 4,
    "class_id": 2,
    "action": "api.request",
    "object_id": "POST /login",
    "method": "POST",
    "path": "/login",
    "status": 302,
    "code": "OK",
    "duration_ms": 206
  },
  {
    "id": 99,
    "ts": "2026-11-13T15:09:28.132156+00:00",
    "request_id": "req-af2f1cd6e851",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/qa/faqs",
    "method": "POST",
    "path": "/api/qa/faqs",
    "status": 201,
    "code": "OK",
    "duration_ms": 19
  },
  {
    "id": 98,
    "ts": "2026-11-13T15:09:19.362159+00:00",
    "request_id": "req-9954eeb643d2",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/qa/questions/2/accept",
    "method": "POST",
    "path": "/api/qa/questions/2/accept",
    "status": 200,
    "code": "OK",
    "duration_ms": 13
  }
]
```

## 判定

**绿**：七列齐备，拒绝尝试有留痕，按技能标识加时间窗可回查。
