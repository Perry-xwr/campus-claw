"""UTC 时间工具：所有入库时间统一为带 Z 的 ISO 8601 字符串。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().strftime(ISO_FORMAT)


def to_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(ISO_FORMAT)


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, ISO_FORMAT).replace(tzinfo=timezone.utc)


def parse_iso_loose(value: str) -> datetime:
    """宽容解析：同时接受 ``...Z`` 与 ``...+00:00`` 两种写入口径。

    为什么需要这个：库里两种格式并存——``timeutil.now_iso()`` 写 ``...Z``，
    而 ``retrieval_db.utc_now()`` 用 ``datetime.isoformat()`` 写出 ``...+00:00``。
    严格按一种格式解析，另一类记录就会被当成「解析失败」静默跳过，
    而调用方通常只会看到一个「算不出来」的默认值，很难发现是格式没对上。
    （索引卡住判断最初就是这样静默失效的。）
    """
    try:
        return parse_iso(value)
    except (TypeError, ValueError):
        pass
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def plus_hours(moment: datetime, hours: int) -> datetime:
    return moment + timedelta(hours=hours)


def to_local_display(value: str) -> str:
    """把入库的 UTC ISO 时间转成本地时区的可读串，仅用于页面展示。

    解析失败时原样返回，展示层不得影响数据本身。
    """
    try:
        moment = parse_iso(value).astimezone()
    except (ValueError, TypeError):
        return value
    return moment.strftime("%Y-%m-%d %H:%M")
