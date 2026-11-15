#!/usr/bin/env python3
"""Poll CampusClaw's health alert endpoint and notify a configured webhook."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALERTS_URL = "http://127.0.0.1:8080/api/health/alerts"
MAX_RESPONSE_BYTES = 1_000_000
ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")
RULE_SUMMARIES = {
    "db_probe": "数据库健康检查失败。",
    "index_failed": "有教学材料索引失败。",
    "tasks_pending": "待处理任务积压超过配置阈值。",
    "http_p95_ms": "请求延迟超过配置阈值。",
    "audit_denials": "拒绝请求数超过配置阈值。",
    "alert_evaluation_failed": "健康接口无法完成告警规则判定。",
    "unknown_critical": "发现未登记的 critical 健康规则。",
}


class NotifyError(Exception):
    """Safe-to-log operational failure; never includes configured URLs."""


def _validate_url(value: str, name: str, *, webhook: bool = False) -> str:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        _ = parsed.port  # Force validation of malformed ports.
    except ValueError:
        raise NotifyError(f"{name} is not a valid HTTP URL") from None
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise NotifyError(f"{name} must be an HTTP(S) URL without embedded credentials")
    if parsed.fragment:
        raise NotifyError(f"{name} must not contain a URL fragment")
    if webhook and parsed.scheme != "https" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise NotifyError("webhook URL must use HTTPS (HTTP is allowed only for loopback tests)")
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        # In particular, never forward a webhook payload to a redirect target.
        return None


def _open(request: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def fetch_alerts(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with _open(request, timeout) as response:
            if not 200 <= response.status < 300:
                raise NotifyError(f"alerts endpoint returned HTTP {response.status}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise NotifyError(f"alerts endpoint returned HTTP {exc.code}") from None
    except (TimeoutError, socket.timeout):
        raise NotifyError("alerts endpoint timed out") from None
    except urllib.error.URLError:
        raise NotifyError("alerts endpoint connection failed") from None
    except OSError:
        raise NotifyError("alerts endpoint connection failed") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise NotifyError("alerts endpoint response exceeded the size limit")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise NotifyError("alerts endpoint returned invalid JSON") from None
    if not isinstance(data, dict) or data.get("status") not in {"ok", "degraded", "critical"}:
        raise NotifyError("alerts endpoint returned an invalid status")
    alerts = data.get("alerts", [])
    if not isinstance(alerts, list) or any(not isinstance(item, dict) for item in alerts):
        raise NotifyError("alerts endpoint returned an invalid alert list")
    critical_ids: set[str] = set()
    for item in alerts:
        if item.get("level") != "critical":
            continue
        rule_id = item.get("id")
        if not isinstance(rule_id, str) or not ID_RE.fullmatch(rule_id):
            raise NotifyError("alerts endpoint returned an invalid critical alert type")
        critical_ids.add(rule_id if rule_id in RULE_SUMMARIES else "unknown_critical")
    if data["status"] == "critical" and not critical_ids:
        # health_views deliberately returns this shape if rule evaluation raises.
        critical_ids.add("alert_evaluation_failed")
    if data["status"] != "critical" and critical_ids:
        raise NotifyError("alerts endpoint returned critical rules with a non-critical status")
    return {"status": data["status"], "critical_ids": sorted(critical_ids)}


def send_webhook(url: str, payload: dict[str, Any], timeout: float) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with _open(request, timeout) as response:
            if not 200 <= response.status < 300:
                raise NotifyError(f"webhook returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        raise NotifyError(f"webhook returned HTTP {exc.code}") from None
    except (TimeoutError, socket.timeout):
        raise NotifyError("webhook delivery timed out") from None
    except urllib.error.URLError:
        raise NotifyError("webhook connection failed") from None
    except OSError:
        raise NotifyError("webhook connection failed") from None


def _load_state(path: Path) -> list[str]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise NotifyError("notification state file cannot be read") from None
    ids = state.get("critical_ids") if isinstance(state, dict) and state.get("version") == 1 else None
    if not isinstance(ids, list) or any(not isinstance(v, str) or not ID_RE.fullmatch(v) for v in ids):
        raise NotifyError("notification state file has an unsupported format")
    return sorted(set(ids))


def _save_state(path: Path, critical_ids: list[str]) -> None:
    encoded = (json.dumps({"version": 1, "critical_ids": critical_ids}, indent=2) + "\n").encode("utf-8")
    temp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=".alert-state-", suffix=".tmp", delete=False
        ) as temp:
            temp_name = temp.name
            temp.write(encoded)
            temp.flush()
            os.fsync(temp.fileno())
        if os.name != "nt":
            os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    except OSError:
        raise NotifyError("notification state could not be saved") from None
    finally:
        if temp_name and os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError:
                pass


@contextlib.contextmanager
def _state_lock(path: Path):
    """Cross-platform non-blocking lock so overlapping schedules cannot double-send."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = path.with_name(path.name + ".lock").open("a+b")
    except OSError:
        raise NotifyError("notification state lock is unavailable") from None
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError:
                raise NotifyError("another alert notification check is already running") from None
        else:
            import fcntl

            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                raise NotifyError("another alert notification check is already running") from None
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def _notification(kind: str, critical_ids: list[str], status: str) -> dict[str, Any]:
    detected_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    safe_alerts = [
        {"type": rule_id, "summary": RULE_SUMMARIES[rule_id]}
        for rule_id in critical_ids
    ]
    if kind == "critical":
        summary = "检测到 critical 告警：" + "；".join(a["summary"] for a in safe_alerts)
    else:
        summary = f"先前通知的 critical 告警已清除；当前状态为 {status}。"
    return {
        "type": "campusclaw.alert",
        "event": kind,
        "detected_at": detected_at,
        "summary": summary,
        "alerts": safe_alerts,
    }


def run_once(
    env: dict[str, str] | None = None,
    *,
    fetcher: Callable[[str, float], dict[str, Any]] = fetch_alerts,
    sender: Callable[[str, dict[str, Any], float], None] = send_webhook,
) -> int:
    config = os.environ if env is None else env
    webhook = config.get("CAMPUSCLAW_ALERT_WEBHOOK_URL", "").strip()
    if not webhook:
        raise NotifyError("CAMPUSCLAW_ALERT_WEBHOOK_URL is not configured")
    webhook = _validate_url(webhook, "webhook URL", webhook=True)
    alerts_url = _validate_url(
        config.get("CAMPUSCLAW_ALERTS_URL", DEFAULT_ALERTS_URL).strip(), "alerts URL"
    )
    try:
        timeout = float(config.get("CAMPUSCLAW_ALERT_TIMEOUT_SECONDS", "8"))
    except ValueError:
        raise NotifyError("CAMPUSCLAW_ALERT_TIMEOUT_SECONDS must be between 1 and 30") from None
    if not 1 <= timeout <= 30:
        raise NotifyError("CAMPUSCLAW_ALERT_TIMEOUT_SECONDS must be between 1 and 30")
    state_path = Path(config.get("CAMPUSCLAW_ALERT_STATE_FILE", str(ROOT / ".run" / "alert-notify-state.json")))

    with _state_lock(state_path):
        verdict = fetcher(alerts_url, timeout)
        current = sorted(set(verdict["critical_ids"]))
        previous = _load_state(state_path)
        if current == previous:
            print("No new critical alert; duplicate notification suppressed." if current else "No critical alerts.")
            return 0
        event = "critical" if current else "recovered"
        payload_ids = current if current else previous
        sender(webhook, _notification(event, payload_ids, verdict["status"]), timeout)
        _save_state(state_path, current)
        print(f"Webhook notification sent: event={event}, alert_types={len(payload_ids)}.")
    return 0


def main() -> int:
    try:
        return run_once()
    except NotifyError as exc:
        print(f"alert_notify: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
