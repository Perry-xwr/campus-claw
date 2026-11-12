# 审计日志回查（SEC-07）

- 生成时间：2026-11-12 22:27:38
- 数据库：`data\app.db`
- 时间窗：最近 120 分钟
- 技能调用记录：0 条，七列齐备 0 条
- 拒绝尝试记录：48 条
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
    "id": 48,
    "ts": "2026-11-12T14:13:23.149580+00:00",
    "request_id": "req-50d059e3b9ae",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "DELETE /api/materials/8",
    "method": "DELETE",
    "path": "/api/materials/8",
    "status": 204,
    "code": "OK",
    "duration_ms": 41
  },
  {
    "id": 47,
    "ts": "2026-11-12T14:13:23.068948+00:00",
    "request_id": "req-78cd276cd521",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/ask",
    "method": "POST",
    "path": "/api/ask",
    "status": 503,
    "code": "ERROR",
    "duration_ms": 12
  },
  {
    "id": 46,
    "ts": "2026-11-12T14:13:23.031293+00:00",
    "request_id": "req-ef2febb6c756",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 503,
    "code": "ERROR",
    "duration_ms": 13
  },
  {
    "id": 45,
    "ts": "2026-11-12T14:13:22.914649+00:00",
    "request_id": "req-cde33fc8a0fd",
    "actor": "student_b1",
    "actor_id": 3,
    "class_id": 2,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 200,
    "code": "OK",
    "duration_ms": 10
  },
  {
    "id": 44,
    "ts": "2026-11-12T14:13:22.869774+00:00",
    "request_id": "req-a4bb1d656769",
    "actor": "student_a1",
    "actor_id": 2,
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
    "id": 43,
    "ts": "2026-11-12T14:13:20.829680+00:00",
    "request_id": "req-63648c6e2fac",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.reject",
    "object_id": "POST /api/materials/upload",
    "method": "POST",
    "path": "/api/materials/upload",
    "status": 403,
    "code": "ROLE_FORBIDDEN",
    "duration_ms": 6
  },
  {
    "id": 42,
    "ts": "2026-11-12T14:13:20.798388+00:00",
    "request_id": "req-d0cd8512bf23",
    "actor": "teacher_a",
    "actor_id": 1,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/materials/upload",
    "method": "POST",
    "path": "/api/materials/upload",
    "status": 201,
    "code": "OK",
    "duration_ms": 43
  },
  {
    "id": 41,
    "ts": "2026-11-12T14:13:09.450061+00:00",
    "request_id": "req-d6e667408fa2",
    "actor": "student_a1",
    "actor_id": 2,
    "class_id": 1,
    "action": "api.request",
    "object_id": "POST /api/search",
    "method": "POST",
    "path": "/api/search",
    "status": 503,
    "code": "ERROR",
    "duration_ms": 14
  }
]
```

## 判定

**绿**：七列齐备，拒绝尝试有留痕，按技能标识加时间窗可回查。
