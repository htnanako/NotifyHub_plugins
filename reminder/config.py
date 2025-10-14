import os
import json
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from notifyhub.controller.server import server

class ReminderConfig(BaseModel):
    id: str
    title: str
    content: str
    reminder_type: str
    reminder_time: str
    status: bool
    notify_route: str


config_floder = os.path.join("data", "conf", "reminder")
config_file = os.path.join(config_floder, "config.json")
os.makedirs(config_floder, exist_ok=True)
if not os.path.exists(config_file):
    with open(config_file, "w") as f:
        f.write("[]")


def _read_all() -> List[Dict[str, Any]]:
    if not os.path.exists(config_file):
        return []
    try:
        with open(config_file, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
            return data if isinstance(data, list) else []
    except Exception:
        # Return empty list if file is empty or invalid JSON
        return []


def _write_all(items: List[Dict[str, Any]]) -> None:
    with open(config_file, "w", encoding="utf-8") as file_handle:
        json.dump(items, file_handle, ensure_ascii=False, indent=2)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "on", "yes", "enabled", "enable"}
    return False


def _coerce_to_model(raw: Dict[str, Any]) -> ReminderConfig:
    data: Dict[str, Any] = {
        "id": (raw.get("id") or uuid.uuid4().hex),
        "title": (raw.get("title") or "").strip(),
        "content": (raw.get("content") or "").strip(),
        "reminder_type": (raw.get("reminder_type") or "").strip().lower(),
        "reminder_time": (raw.get("reminder_time") or "").strip(),
        "status": _to_bool(raw.get("status")),
        "notify_route": (raw.get("notify_route") or "").strip(),
    }
    return ReminderConfig(**data)


def list_configs() -> List[Dict[str, Any]]:
    # 统一通过模型清洗后再输出 dict，保证前后端字段一致
    items = _read_all()
    models: List[ReminderConfig] = []
    for it in items:
        if isinstance(it, dict):
            try:
                models.append(_coerce_to_model(it))
            except Exception:
                continue
    return [m.model_dump() for m in models]


def get_config_by_id(config_id: str) -> Optional[Dict[str, Any]]:
    for item in _read_all():
        if isinstance(item, dict) and item.get("id") == config_id:
            try:
                return _coerce_to_model(item).model_dump()
            except Exception:
                return None
    return None


def add_config(config_item: Dict[str, Any]) -> Dict[str, Any]:
    items = _read_all()
    if not isinstance(config_item, dict):
        raise ValueError("config_item must be a dict")
    model = _coerce_to_model(config_item)
    items.append(model.model_dump())
    _write_all(items)
    return model.model_dump()


def update_config(config_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    items = _read_all()
    updated_item: Optional[Dict[str, Any]] = None
    new_items: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and item.get("id") == config_id:
            merged_raw = {**item, **(updates or {}), "id": config_id}
            try:
                model = _coerce_to_model(merged_raw)
            except Exception:
                return None
            updated_item = model.model_dump()
            new_items.append(updated_item)
        else:
            new_items.append(item)
    if updated_item is None:
        return None
    _write_all(new_items)
    return updated_item


def remove_config(config_id: str) -> bool:
    items = _read_all()
    new_items = [item for item in items if not (isinstance(item, dict) and item.get("id") == config_id)]
    if len(new_items) == len(items):
        return False
    _write_all(new_items)
    return True


def replace_configs(config_items: List[Dict[str, Any]]) -> None:
    if not isinstance(config_items, list):
        raise ValueError("config_items must be a list of dicts")
    _write_all(config_items)


def get_notify_route_list() -> List[Dict[str, Any]]:
    return server.router_list