# 审计日志回查（SEC-07）

- 生成时间：2026-11-13 22:14:30
- 数据库：`data/app.db`
- 时间窗：不限（全部历史，原文只列最近 5 条）
- 技能调用记录：8 条，七列齐备 8 条
- 最近一条调用：`2026-11-12T16:09:02.936108+00:00`（距今 22 小时）
- 拒绝尝试记录：45 条
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
    "id": 45,
    "ts": "2026-11-13T14:13:30.660728+00:00",
    "request_id": "req-02bae143b1d2",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "DELETE /api/materials/4",
    "method": "DELETE",
    "path": "/api/materials/4",
    "status": 204,
    "code": "OK",
    "duration_ms": 119
  },
  {
    "id": 44,
    "ts": "2026-11-13T14:12:33.043474+00:00",
    "request_id": "req-d71df469e8c9",
    "actor": "student_a1",
    "actor_id": 2,
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
    "id": 43,
    "ts": "2026-11-13T14:12:26.816472+00:00",
    "request_id": "req-c99d0a5f8591",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/materials/upload",
    "method": "POST",
    "path": "/api/materials/upload",
    "status": 201,
    "code": "OK",
    "duration_ms": 13
  },
  {
    "id": 42,
    "ts": "2026-11-13T14:12:09.438524+00:00",
    "request_id": "req-ecdcc2ecdafd",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /login",
    "method": "POST",
    "path": "/login",
    "status": 302,
    "code": "OK",
    "duration_ms": 212
  },
  {
    "id": 41,
    "ts": "2026-11-13T14:12:00.048064+00:00",
    "request_id": "req-8c5ac9268c2e",
    "actor": "",
    "actor_id": null,
    "class_id": null,
    "action": "api.reject",
    "object_id": "POST /login",
    "method": "POST",
    "path": "/login",
    "status": 403,
    "code": "CSRF_INVALID",
    "duration_ms": 2
  },
  {
    "id": 40,
    "ts": "2026-11-13T14:09:28.129379+00:00",
    "request_id": "req-cd0a6ee7edbd",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "DELETE /api/materials/3",
    "method": "DELETE",
    "path": "/api/materials/3",
    "status": 204,
    "code": "OK",
    "duration_ms": 98
  },
  {
    "id": 39,
    "ts": "2026-11-13T14:08:57.290093+00:00",
    "request_id": "req-72051828bbf3",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 503,
    "code": "ERROR",
    "duration_ms": 5
  },
  {
    "id": 38,
    "ts": "2026-11-13T14:08:57.263722+00:00",
    "request_id": "req-d1919cab9c53",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 503,
    "code": "ERROR",
    "duration_ms": 4
  }
]
```

## 判定

**绿**：七列齐备，拒绝尝试有留痕，按技能标识加时间窗可回查。
