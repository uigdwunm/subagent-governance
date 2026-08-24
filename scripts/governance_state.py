"""Current persisted-state model and validation."""

from __future__ import annotations

import re
from typing import Any

try:
    from scripts.governance_errors import StateValidationError
    from scripts.governance_semantics import (
        DISPATCH_STATES,
        OBSERVATION_SOURCES,
        OBSERVED_STATES,
        PARENT_ACTIONS,
        PARENT_DISPOSITION_REASON_MAX_LENGTH,
        REQUIRED_CLOSURE_RECORD_FIELDS,
        REQUIRED_DISPATCH_RECORD_FIELDS,
        REQUIRED_EXECUTION_FIELDS,
        REQUIRED_OBSERVATION_RECORD_FIELDS,
        REQUIRED_TASK_CONTAINER_FIELDS,
        REQUIRED_WORK_ITEM_FIELDS,
        SEMANTIC_DEFINITIONS,
        STATE_FORMAT_VERSION,
    )
except ModuleNotFoundError:
    from governance_errors import StateValidationError
    from governance_semantics import (
        DISPATCH_STATES,
        OBSERVATION_SOURCES,
        OBSERVED_STATES,
        PARENT_ACTIONS,
        PARENT_DISPOSITION_REASON_MAX_LENGTH,
        REQUIRED_CLOSURE_RECORD_FIELDS,
        REQUIRED_DISPATCH_RECORD_FIELDS,
        REQUIRED_EXECUTION_FIELDS,
        REQUIRED_OBSERVATION_RECORD_FIELDS,
        REQUIRED_TASK_CONTAINER_FIELDS,
        REQUIRED_WORK_ITEM_FIELDS,
        SEMANTIC_DEFINITIONS,
        STATE_FORMAT_VERSION,
    )


def initial_plane_records() -> dict[str, dict[str, Any]]:
    return {
        "dispatch_record": {
            "dispatch_state": "prepared",
            "tool_use_id": None,
            "dispatch_target": None,
        },
        "observation_record": {
            "source": None,
            "observed_state": "not_observed",
            "observed_at": None,
            "terminal_status": None,
        },
        "closure_record": {
            "reason": None,
            "closed_at": None,
            "parent_action": None,
        },
    }


def _valid_close_reason(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and value.strip()
        and len(value) <= PARENT_DISPOSITION_REASON_MAX_LENGTH
    )


def validate_current_execution_planes(execution: dict[str, Any]) -> None:
    expected = {
        "dispatch_record": REQUIRED_DISPATCH_RECORD_FIELDS,
        "observation_record": REQUIRED_OBSERVATION_RECORD_FIELDS,
        "closure_record": REQUIRED_CLOSURE_RECORD_FIELDS,
    }
    for field_name, required in expected.items():
        record = execution.get(field_name)
        if not isinstance(record, dict):
            raise StateValidationError(
                f"managed execution 缺少 canonical plane {field_name}"
            )
        missing = required - set(record)
        if missing:
            raise StateValidationError(
                f"canonical plane {field_name} 缺少字段 {', '.join(sorted(missing))}"
            )
        unknown = set(record) - required
        if unknown:
            raise StateValidationError(
                f"canonical plane {field_name} 包含未知字段 {', '.join(sorted(unknown))}"
            )

    task_ref = execution.get("task_ref")
    if not isinstance(task_ref, str) or not task_ref:
        raise StateValidationError("managed execution 的 task_ref 无效")

    dispatch = execution["dispatch_record"]
    observation = execution["observation_record"]
    closure = execution["closure_record"]
    for record, field_name, allowed in (
        (dispatch, "dispatch_state", DISPATCH_STATES),
        (observation, "observed_state", OBSERVED_STATES),
    ):
        if record.get(field_name) not in allowed:
            raise StateValidationError(
                f"canonical plane 字段 {field_name} 使用未知枚举值"
            )
    for record, field_name, allowed in (
        (observation, "source", OBSERVATION_SOURCES),
        (closure, "parent_action", PARENT_ACTIONS),
    ):
        value = record.get(field_name)
        if value is not None and value not in allowed:
            raise StateValidationError(
                f"canonical plane 字段 {field_name} 使用未知枚举值"
            )
    for record, field_name in (
        (observation, "observed_at"),
        (closure, "closed_at"),
    ):
        value = record.get(field_name)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise StateValidationError(f"canonical plane 时间字段 {field_name} 无效")

    terminal_status = observation.get("terminal_status")
    if terminal_status is not None and terminal_status not in {
        "completed",
        "stopped",
        "interrupted",
    }:
        raise StateValidationError("observation_record.terminal_status 无效")
    if observation.get("observed_state") == "terminal" and terminal_status is None:
        raise StateValidationError("terminal observation 缺少 terminal_status")

    reason = closure.get("reason")
    closed_at = closure.get("closed_at")
    if reason is not None and not _valid_close_reason(reason):
        raise StateValidationError("closure_record.reason 无效")
    if (reason is None) != (closed_at is None):
        raise StateValidationError(
            "closure_record 的 reason 与 closed_at 必须同时存在或同时为空"
        )


def _execution_key(value: Any) -> int | None:
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
        return None
    return int(value)


def require_current_state_format(value: dict[str, Any]) -> dict[str, Any]:
    version = value.get("state_format_version")
    if isinstance(version, bool) or version != STATE_FORMAT_VERSION:
        raise StateValidationError(
            "unsupported_state_version: "
            f"检测到 {version!r}，当前仅支持 {STATE_FORMAT_VERSION}"
        )
    tasks = value.get("tasks")
    if not isinstance(tasks, dict):
        return value
    task_id_maximum = int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"])
    for task_id, task in tasks.items():
        if not isinstance(task, dict) or task.get("managed") is not True:
            continue
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or len(task_id) > task_id_maximum
        ):
            raise StateValidationError("managed task 的 tasks 键不是合法 task_id")
        missing = REQUIRED_TASK_CONTAINER_FIELDS - set(task)
        if missing:
            raise StateValidationError(
                "managed task 缺少当前字段 " + ", ".join(sorted(missing))
            )
        work_item = task.get("work_item")
        executions = task.get("executions")
        if not isinstance(work_item, dict) or not isinstance(executions, dict):
            raise StateValidationError("managed task 缺少 canonical work_item/executions")
        missing_work_item = REQUIRED_WORK_ITEM_FIELDS - set(work_item)
        if missing_work_item:
            raise StateValidationError(
                "canonical work_item 缺少字段 "
                + ", ".join(sorted(missing_work_item))
            )
        for attempt_key, execution in executions.items():
            if _execution_key(attempt_key) is None:
                raise StateValidationError(
                    f"managed task {task_id} 包含非法 execution 键 {attempt_key}"
                )
            if not isinstance(execution, dict):
                raise StateValidationError(
                    f"managed task {task_id} 的 execution {attempt_key} 必须是对象"
                )
            missing_execution = REQUIRED_EXECUTION_FIELDS - set(execution)
            if missing_execution:
                raise StateValidationError(
                    "canonical execution 缺少字段 "
                    + ", ".join(sorted(missing_execution))
                )
            validate_current_execution_planes(execution)
    return value
