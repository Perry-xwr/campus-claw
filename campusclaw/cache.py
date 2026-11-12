"""第 10 课压测改进项：检索结果缓存。

课件给的改进方向是「缓存或索引」，并强调「缓存减少的是重复计算，不是单次计算
本身的耗时」。本项目的重复计算在检索链路里：一次 ``/api/search`` 要跑
FTS 匹配 + 多个 JOIN，再对每个候选回查一次切片（N+1）；关键词检索又是无状态的
纯函数，同样的 ``(班级, 模式, 查询, 条数)`` 必然得到同样的结果，天然适合缓存。

四条边界：

* **键含班级**：``class_id`` 是键的一部分，跨班不会命中别人的结果。这是 SEC-02
  的隔离要求，缓存不能成为新的绕过口。
* **写入即失效**：材料上传 / 改名 / 删除 / 索引换代都调 :func:`invalidate_class`。
  TTL 只是兜底——多进程部署时另一个进程的写入不会通知到本进程，最坏情况陈旧
  一个 TTL。
* **有界**：LRU + 上限，不因为查询参数花样多就把内存吃光。
* **可关**：``CAMPUSCLAW_RETRIEVAL_CACHE=0`` 关闭。压测的「改进前」就是用这个
  开关跑出来的，两轮走的是同一份代码、同一套参数，差别只有缓存。
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from typing import Any, Hashable

#: 缓存开关与容量。读环境变量放在模块导入时，运行期不再变化。
ENABLED = os.environ.get("CAMPUSCLAW_RETRIEVAL_CACHE", "1").strip() not in ("0", "false", "False")
TTL_SECONDS = float(os.environ.get("CAMPUSCLAW_RETRIEVAL_CACHE_TTL", "60") or 60)
MAX_ENTRIES = int(os.environ.get("CAMPUSCLAW_RETRIEVAL_CACHE_SIZE", "512") or 512)

_LOCK = threading.Lock()
_STORE: "OrderedDict[Hashable, tuple[float, Any]]" = OrderedDict()
#: 每个班一个版本号：写入即 +1，旧键自然作废，不必遍历删除。
_EPOCH: dict[int, int] = {}
_STATS = {"hits": 0, "misses": 0, "evictions": 0, "invalidations": 0}


def make_key(class_id: int, mode: str, query: str, limit: int) -> tuple:
    """键里带版本号：同一班级写入后版本变了，旧条目不再被命中。"""
    with _LOCK:
        epoch = _EPOCH.get(int(class_id), 0)
    return (int(class_id), epoch, mode, query, int(limit))


def get(key: Hashable) -> Any | None:
    """命中返回值；过期、缺失或关闭缓存都返回 ``None``（调用方回源）。"""
    if not ENABLED:
        return None
    now = time.monotonic()
    with _LOCK:
        item = _STORE.get(key)
        if item is None:
            _STATS["misses"] += 1
            return None
        expires_at, value = item
        if expires_at <= now:
            _STORE.pop(key, None)
            _STATS["misses"] += 1
            return None
        _STORE.move_to_end(key)
        _STATS["hits"] += 1
        return value


def put(key: Hashable, value: Any) -> None:
    if not ENABLED:
        return
    with _LOCK:
        _STORE[key] = (time.monotonic() + TTL_SECONDS, value)
        _STORE.move_to_end(key)
        while len(_STORE) > MAX_ENTRIES:
            _STORE.popitem(last=False)
            _STATS["evictions"] += 1


def invalidate_class(class_id: int | None) -> None:
    """材料或索引发生变化时调用：该班旧条目立即作废。"""
    if class_id is None:
        return
    with _LOCK:
        _EPOCH[int(class_id)] = _EPOCH.get(int(class_id), 0) + 1
        _STATS["invalidations"] += 1


def clear() -> None:
    """测试与压测用：清空存储但保留命中统计口径（统计由 :func:`reset_stats` 归零）。"""
    with _LOCK:
        _STORE.clear()
        _EPOCH.clear()


def reset_stats() -> None:
    with _LOCK:
        for key in _STATS:
            _STATS[key] = 0


def stats() -> dict[str, Any]:
    """命中率供面板与压测报告引用；分母为 0 时给 0 而不是 NaN。"""
    with _LOCK:
        hits, misses = _STATS["hits"], _STATS["misses"]
        total = hits + misses
        return {
            "enabled": ENABLED,
            "ttl_seconds": TTL_SECONDS,
            "max_entries": MAX_ENTRIES,
            "entries": len(_STORE),
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hits / total, 4) if total else 0.0,
            "evictions": _STATS["evictions"],
            "invalidations": _STATS["invalidations"],
        }
