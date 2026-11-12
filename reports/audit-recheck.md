# 审计日志回查（SEC-07）

- 生成时间：2026-11-12 21:35:19
- 数据库：`data\app.db`
- 时间窗：最近 120 分钟
- 技能调用记录：0 条，七列齐备 0 条
- 拒绝尝试记录：14 条
- 关联键断言：通过（有用户名的记录均带 actor_id）
- 表结构断言：通过（七列齐备）

## 七列断言

| 列 | 含义 | 首条记录取值 | 判定 |
| --- | --- | --- | --- |
| `actor` | 操作人 | `None` | 缺 |
| `created_at` | 操作时间 | `None` | 缺 |
| `action` | 操作类型 | `None` | 缺 |
| `object_id` | 操作对象 | `None` | 缺 |
| `status` | 结果状态 | `None` | 缺 |
| `skill_id` | 技能标识 | `None` | 缺 |
| `duration_ms` | 用量与耗时 | `None` | 缺 |

## 回查原文（技能调用）

_无记录_

## 回查原文（被拒绝的尝试）

```json
[
  {
    "id": 14,
    "ts": "2026-11-12T13:33:51.310465+00:00",
    "request_id": "req-6e7f924c38f3",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 14
  },
  {
    "id": 13,
    "ts": "2026-11-12T13:33:46.249463+00:00",
    "request_id": "req-77f657585a09",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 15
  },
  {
    "id": 12,
    "ts": "2026-11-12T13:33:42.200725+00:00",
    "request_id": "req-39f32dc38abb",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 14
  },
  {
    "id": 11,
    "ts": "2026-11-12T13:33:36.159463+00:00",
    "request_id": "req-fa3abf538f77",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/materials/upload",
    "method": "POST",
    "path": "/api/materials/upload",
    "status": 201,
    "code": "OK",
    "duration_ms": 45
  },
  {
    "id": 10,
    "ts": "2026-11-12T13:33:00.812753+00:00",
    "request_id": "req-aaa6466825ba",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 11
  },
  {
    "id": 9,
    "ts": "2026-11-12T13:32:48.759900+00:00",
    "request_id": "req-7cc4ae1a88b2",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/materials/upload",
    "method": "POST",
    "path": "/api/materials/upload",
    "status": 201,
    "code": "OK",
    "duration_ms": 44
  },
  {
    "id": 8,
    "ts": "2026-11-12T13:32:04.071416+00:00",
    "request_id": "req-83a2b9cd4b31",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 19
  },
  {
    "id": 7,
    "ts": "2026-11-12T13:31:07.264373+00:00",
    "request_id": "req-a8bac6b38eab",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 503,
    "code": "ERROR",
    "duration_ms": 12
  }
]
```

## 判定

**绿**：七列齐备，拒绝尝试有留痕，按技能标识加时间窗可回查。
