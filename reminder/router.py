from fastapi import APIRouter
from typing import Any, Dict, Optional
from datetime import datetime

from notifyhub.common.response import data_to_json, json_with_status

from .config import (
    list_configs,
    add_config,
    update_config,
    remove_config,
    get_config_by_id,
    get_notify_route_list,
)


reminder_router = APIRouter(prefix="/reminder", tags=["reminder"])


def _to_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return int(val) == 1
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "on", "yes", "enabled", "enable"}
    return False


def _validate_onetime_not_past(time_str: str) -> bool:
    patterns = ["%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y.%m.%d %H:%M"]
    now = datetime.now()
    for fmt in patterns:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt >= now.replace(second=0, microsecond=0)
        except Exception:
            continue
    return False


def _validate_cron(expr: str) -> bool:
    parts = [p for p in (expr or "").split() if p]
    return len(parts) == 5


def _normalize_payload(payload: Dict[str, Any], is_update: bool = False) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    title = (payload.get("title") or "").strip()
    content = (payload.get("content") or "").strip()
    reminder_type = (payload.get("reminder_type") or "").strip().lower()
    reminder_time = (payload.get("reminder_time") or "").strip()
    status = _to_bool(payload.get("status"))
    notify_route = (payload.get("notify_route") or "").strip()

    if not title or not content or not reminder_type or not reminder_time or not notify_route:
        return None
    if reminder_type == "onetime":
        if not _validate_onetime_not_past(reminder_time):
            return None
    elif reminder_type == "circle":
        if not _validate_cron(reminder_time):
            return None
    else:
        return None

    # 校验通知通道是否存在
    try:
        route_values = {str(i.get("value")) for i in (get_notify_route_list() or [])}
    except Exception:
        route_values = set()
    if route_values and (notify_route not in route_values):
        return None

    normalized: Dict[str, Any] = {
        "title": title,
        "content": content,
        "status": status,
        "reminder_type": reminder_type,
        "reminder_time": reminder_time,
        "notify_route": notify_route,
    }
    # 允许透传 id（仅更新时使用）
    if is_update and payload.get("id"):
        normalized["id"] = payload.get("id")
    return normalized


@reminder_router.get("/notify_route")
async def get_notify_route():
    return data_to_json(data=get_notify_route_list())


@reminder_router.get("/tasks")
async def list_tasks():
    return data_to_json(data=list_configs())


@reminder_router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    item = get_config_by_id(task_id)
    if not item:
        return json_with_status(404, message="task not found")
    return data_to_json(data=item)


@reminder_router.post("/tasks")
async def create_task(payload: Dict[str, Any]):
    normalized = _normalize_payload(payload, is_update=False)
    if not normalized:
        return json_with_status(400, message="invalid payload")
    created = add_config(normalized)
    return data_to_json(data=created)


@reminder_router.put("/tasks/{task_id}")
async def update_task(task_id: str, payload: Dict[str, Any]):
    if not get_config_by_id(task_id):
        return json_with_status(404, message="task not found")
    payload = dict(payload or {})
    payload["id"] = task_id
    normalized = _normalize_payload(payload, is_update=True)
    if not normalized:
        return json_with_status(400, message="invalid payload")
    updated = update_config(task_id, normalized)
    if not updated:
        return json_with_status(500, message="update failed")
    return data_to_json(data=updated)


@reminder_router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    if not get_config_by_id(task_id):
        return json_with_status(404, message="task not found")
    ok = remove_config(task_id)
    if not ok:
        return json_with_status(500, message="delete failed")
    return data_to_json(data={"id": task_id})