import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set

from notifyhub.controller.server import server

from .config import list_configs, update_config

logger = logging.getLogger(__name__)


def _is_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        v = value.strip().lower()
        return v in {"enabled", "enable", "true", "on", "1", "yes"}
    return False


def _parse_int(token: str) -> Optional[int]:
    try:
        return int(token)
    except Exception:
        return None


def _expand_cron_field(field: str, min_v: int, max_v: int) -> Set[int]:
    field = field.strip()
    results: Set[int] = set()

    if field == "*":
        return set(range(min_v, max_v + 1))

    parts = field.split(",")
    for part in parts:
        part = part.strip()
        if part == "*":
            results.update(range(min_v, max_v + 1))
            continue
        if part.startswith("*/"):
            step = _parse_int(part[2:])
            if step and step > 0:
                results.update([i for i in range(min_v, max_v + 1) if (i - min_v) % step == 0])
            continue
        # range with optional step: a-b or a-b/n
        if "-" in part:
            range_part, step_part = part, None
            if "/" in part:
                range_part, step_part = part.split("/", 1)
            start_s, end_s = range_part.split("-", 1)
            start = _parse_int(start_s)
            end = _parse_int(end_s)
            step = _parse_int(step_part) if step_part else 1
            if start is not None and end is not None and step and step > 0:
                if start > end:
                    continue
                start = max(start, min_v)
                end = min(end, max_v)
                results.update(range(start, end + 1, step))
            continue
        # single number
        num = _parse_int(part)
        if num is not None and min_v <= num <= max_v:
            results.add(num)
    return results


def _cron_matches_now(expr: str, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    fields = [f.strip() for f in expr.split()] if expr else []
    if len(fields) != 5:
        return False

    minute_s, hour_s, dom_s, month_s, dow_s = fields

    minutes = _expand_cron_field(minute_s, 0, 59)
    hours = _expand_cron_field(hour_s, 0, 23)
    doms = _expand_cron_field(dom_s, 1, 31)
    months = _expand_cron_field(month_s, 1, 12)

    # Map Python weekday (Mon=0..Sun=6) to cron (Sun=0..Sat=6)
    cron_dow_now = (now.weekday() + 1) % 7
    # Accept 7 as Sunday in expressions → normalize to 0
    dows_raw = _expand_cron_field(dow_s.replace("7", "0"), 0, 6)
    dows = set()
    for d in dows_raw:
        dows.add(0 if d == 7 else d)

    return (
        (now.minute in minutes)
        and (now.hour in hours)
        and (now.day in doms)
        and (now.month in months)
        and (cron_dow_now in dows)
    )


def _onetime_matches_now(time_str: str, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    patterns = [
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%Y.%m.%d %H:%M",
    ]
    for fmt in patterns:
        try:
            dt = datetime.strptime(time_str.strip(), fmt)
            if (
                dt.year == now.year
                and dt.month == now.month
                and dt.day == now.day
                and dt.hour == now.hour
                and dt.minute == now.minute
            ):
                return True
        except Exception:
            continue
    return False


def _send_notify_to_route(route_id: str, title: str, content: str):
    server.send_notify_by_router(route_id, title, content)


class ReminderJob:

    def run(self):
        now = datetime.now()
        items: List[Dict[str, Any]] = list_configs()
        for item in items:
            if not isinstance(item, dict):
                continue
            status = item.get("status")
            if not _is_enabled(status):
                continue

            reminder_type = (item.get("reminder_type") or "").strip().lower()
            reminder_time = (item.get("reminder_time") or "").strip()
            if not reminder_type or not reminder_time:
                continue

            matched = False
            if reminder_type == "onetime":
                matched = _onetime_matches_now(reminder_time, now)
            elif reminder_type == "circle":
                matched = _cron_matches_now(reminder_time, now)
            else:
                continue

            if matched:
                logger.info(
                    "[reminder] matched type=%s time=%s",
                    reminder_type, reminder_time,
                )
                route_id = item.get("notify_route")
                title = item.get("title")
                content = item.get("content")
                _send_notify_to_route(route_id, title, content)
                if reminder_type == "onetime":
                    update_config(item.get("id"), {"status": False})


reminder_job = ReminderJob()
