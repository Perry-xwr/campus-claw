# 审计日志回查（SEC-07）

- 生成时间：2026-11-13 23:47:11
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
    "id": 117,
    "ts": "2026-11-13T15:33:11.707684+00:00",
    "request_id": "req-5f3f17f7cc55",
    "actor": "student_b1",
    "actor_id": 3,
    "class_id": 2,
    "action": "api.request",
    "object_id": "POST /api/conversations/9/messages",
    "method": "POST",
    "path": "/api/conversations/9/messages",
    "status": 200,
    "code": "OK",
    "duration_ms": 17
  },
  {
    "id": 116,
    "ts": "2026-11-13T15:33:11.202858+00:00",
    "request_id": "req-2440ac289066",
    "actor": "student_b1",
    "actor_id": 3,
    "class_id": 2,
    "action": "api.request",
    "object_id": "POST /api/conversations",
    "method": "POST",
    "path": "/api/conversations",
    "status": 201,
    "code": "OK",
    "duration_ms": 12
  },
  {
    "id": 115,
    "ts": "2026-11-13T15:33:00.148230+00:00",
    "request_id": "req-7ab82f5af43a",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.reject",
    "object_id": "GET /api/materials/8/file",
    "method": "GET",
    "path": "/api/materials/8/file",
    "status": 404,
    "code": "MATERIAL_NOT_FOUND",
    "duration_ms": 2
  },
  {
    "id": 114,
    "ts": "2026-11-13T15:32:59.730245+00:00",
    "request_id": "req-516543eddc3d",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 3
  },
  {
    "id": 113,
    "ts": "2026-11-13T15:32:59.630499+00:00",
    "request_id": "req-2d22e1c2c224",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.reject",
    "object_id": "GET /api/materials/8",
    "method": "GET",
    "path": "/api/materials/8",
    "status": 404,
    "code": "MATERIAL_NOT_FOUND",
    "duration_ms": 3
  },
  {
    "id": 112,
    "ts": "2026-11-13T15:32:50.592804+00:00",
    "request_id": "req-718ea58bebc7",
    "actor": "student_b1",
    "actor_id": 3,
    "class_id": 2,
    "action": "api.reject",
    "object_id": "POST /api/qa/questions/1/replies",
    "method": "POST",
    "path": "/api/qa/questions/1/replies",
    "status": 404,
    "code": "NOT_FOUND",
    "duration_ms": 1
  },
  {
    "id": 111,
    "ts": "2026-11-13T15:32:49.958814+00:00",
    "request_id": "req-f3433aa7fd39",
    "actor": "student_b1",
    "actor_id": 3,
    "class_id": 2,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 2
  },
  {
    "id": 110,
    "ts": "2026-11-13T15:32:39.226795+00:00",
    "request_id": "req-620d2443f0b0",
    "actor": "student_b1",
    "actor_id": 3,
    "class_id": 2,
    "action": "api.reject",
    "object_id": "GET /api/qa/questions/2",
    "method": "GET",
    "path": "/api/qa/questions/2",
    "status": 404,
    "code": "NOT_FOUND",
    "duration_ms": 2
  }
]
```

## 判定

**绿**：七列齐备，拒绝尝试有留痕，按技能标识加时间窗可回查。
