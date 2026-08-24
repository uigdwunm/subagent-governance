"""Session hook domain operations; these return domain results, never Hook JSON."""
from __future__ import annotations

import time
from typing import Any, Callable

try:
    from scripts.governance_lifecycle import reconcile_pending_actions
    from scripts.governance_prepared_store import PreparedContractStore, prepared_root_for_store
    from scripts.governance_semantics import STOP_READ_ATTEMPTS, STOP_READ_RETRY_DELAY_SECONDS, SESSION_SUMMARY_CONTEXT_LIMIT, SESSION_SUMMARY_FIELD_LIMIT, SESSION_SUMMARY_RECORD_LIMIT
    from scripts.governance_views import action_required_records, recent_activity_records, work_item_views
except ModuleNotFoundError:
    from governance_lifecycle import reconcile_pending_actions
    from governance_prepared_store import PreparedContractStore, prepared_root_for_store
    from governance_semantics import STOP_READ_ATTEMPTS, STOP_READ_RETRY_DELAY_SECONDS, SESSION_SUMMARY_CONTEXT_LIMIT, SESSION_SUMMARY_FIELD_LIMIT, SESSION_SUMMARY_RECORD_LIMIT
    from governance_views import action_required_records, recent_activity_records, work_item_views


def _bounded(value: Any, fallback: str = "") -> str: return str(value or fallback).strip()[:600]


def reconcile_prepared_dispatches(session_id: str, *, state_store: Any, prepared_store: Any) -> dict[str, int]:
    """Session maintenance entry point.

    Prepared dispatch reconciliation remains intentionally conservative here:
    v6 records are inspected by their owning dispatch transaction at claim time;
    this hook only establishes that the prepared store is safely readable.
    """
    records = prepared_store.list_records(session_id)
    return {"prepared_records": len(records)}


def stop_advisory(payload: dict[str, Any], store: Any, *, sleeper: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    session_id, state, errors = str(payload.get("session_id") or "unknown"), None, []
    for index in range(STOP_READ_ATTEMPTS):
        try:
            state = store.read(session_id); break
        except (OSError, RuntimeError) as exc:
            errors.append(_bounded(exc, "unknown read error"))
            if index < STOP_READ_ATTEMPTS - 1: sleeper(STOP_READ_RETRY_DELAY_SECONDS)
    if state is None:
        return {"continue": True, "system_message": "Subagent Governance 连续三次无法读取 StateStore；当前没有可靠正向证据可用于阻止 parent Stop，已降级放行。最后错误：" + (errors[-1] if errors else "unknown")}
    advisory = action_required_records(state)
    if not advisory: return {"continue": True, "system_message": getattr(store, "last_warning", None)}
    summary = "、".join(f"{item['task_id']}#{item['attempt']}({item.get('_status', 'unknown')})" for item in advisory[:6])
    if len(advisory) > 6: summary += f"，另有 {len(advisory) - 6} 个"
    return {"continue": True, "system_message": f"仍有 action-required 治理子任务：{summary}。当前没有可靠 active freshness 或 parent Stop hard-gate 证据；以上仅作 advisory，未阻止 parent Stop。"}


def _line(view: dict[str, Any]) -> str:
    actions = ",".join(view.get("allowed_actions") or []) or "none"
    notification = view.get("terminal_notification") if isinstance(view.get("terminal_notification"), dict) else {}
    candidates = view.get("execution_candidates") if isinstance(view.get("execution_candidates"), list) else []
    candidate_text = "、".join(f"{item.get('attempt')}({item.get('execution')}/{item.get('identity')}/notification={bool((item.get('notification') or {}).get('observed'))})" for item in candidates)[:SESSION_SUMMARY_FIELD_LIMIT]
    return f"- 工作项 ID：{_bounded(view.get('task_id'), 'unknown')[:SESSION_SUMMARY_FIELD_LIMIT]}｜current attempt：{view.get('current_attempt')}｜lifecycle：{_bounded(view.get('lifecycle'), 'indeterminate')}｜notification：{notification.get('state', 'unknown')}｜allowed_actions：{actions[:SESSION_SUMMARY_FIELD_LIMIT]}｜目标：{_bounded(view.get('objective_summary'), '未记录')[:SESSION_SUMMARY_FIELD_LIMIT]}｜候选 executions：{candidate_text or 'none'}"


def _summary(views: list[dict[str, Any]]) -> str:
    header, footer = "Subagent Governance 会话恢复摘要（work-item 决策视图）：", "不要因 compact/resume 重复创建已有 Agent；使用精确 execution/target 继续等待、对账或处置。\n诊断摘要只展示持久化事实与允许入口，不代表业务授权、验收或自动调度。"
    required = [view for view in views if view.get("action_required") is True]
    recent = [view for view in views if view.get("action_required") is not True and view.get("recent_activity") is True]
    lines = [header]
    for title, values in (("【需要处理】", required), ("【最近活动】", recent)):
        if values:
            lines.append(title)
            for view in values:
                if sum(1 for line in lines if line.startswith("- ")) >= SESSION_SUMMARY_RECORD_LIMIT: break
                candidate = _line(view)
                if len("\n".join([*lines, candidate, footer])) > SESSION_SUMMARY_CONTEXT_LIMIT: break
                lines.append(candidate)
    lines.append(footer)
    return "\n".join(lines)


def _maintenance(session_id: str, store: Any) -> list[str]:
    warnings: list[str] = []
    for label, action in (
        ("prepared reconcile", lambda: reconcile_prepared_dispatches(session_id, state_store=store, prepared_store=PreparedContractStore(prepared_root_for_store(store)))),
        ("pending reconcile", lambda: reconcile_pending_actions(session_id, state_store=store)),
        ("tombstone cleanup", lambda: store.cleanup_expired_tombstones(session_id)),
    ):
        try: action()
        except Exception as exc: warnings.append(f"{label} failed: {_bounded(exc)}")
    return warnings


def session_start(payload: dict[str, Any], store: Any) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    warnings = _maintenance(session_id, store)
    try:
        state = store.read(session_id)
    except Exception as exc:
        return {"continue": True, "system_message": f"Subagent Governance SessionStart degraded：状态不可读，无法确认是否存在待处理任务；请先诊断或恢复 StateStore。错误：{_bounded(exc)}"}
    views, issues, incomplete = work_item_views(state, session_id=session_id)
    if warnings: issues.append({"code": "maintenance_failed", "message": "; ".join(warnings), "context": {"session_id": session_id}})
    if not views and not action_required_records(state) and not recent_activity_records(state):
        return {"continue": True, "system_message": "; ".join(warnings) if warnings else getattr(store, "last_warning", None)}
    message = _summary(views)
    if warnings: message += "\n维护告警：" + "；".join(warnings)
    return {"continue": True, "additional_context": message, "issues": issues, "incomplete": incomplete}


def session_delete_predicate(state: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """Evaluate every deletion fact inside StateStore.delete_if's current snapshot."""
    views, _issues, incomplete = work_item_views(state, session_id=str(state.get("session_id") or ""))
    health = state.get("health") if isinstance(state.get("health"), dict) else {}
    tombstones = state.get("tombstones")
    valid = (
        not incomplete and all(view.get("lifecycle") == "tombstoned" for view in views)
        and not any(view.get("lifecycle") in {"open", "indeterminate"} or view.get("action_required") for view in views)
        and isinstance(tombstones, dict) and not tombstones
        and health.get("status") == "ok" and "initial_preparation_rollback" not in health
    )
    return valid, views


def session_end(payload: dict[str, Any], store: Any) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    warnings = _maintenance(session_id, store)
    preserved: list[dict[str, Any]] = []
    if warnings:
        return {"continue": True, "system_message": "Subagent Governance 会话状态清理失败：" + "；".join(warnings)}
    def delete_if(state: dict[str, Any]) -> bool:
        nonlocal preserved
        allowed, preserved = session_delete_predicate(state)
        return allowed
    try:
        deleted = store.delete_if(session_id, delete_if)
    except Exception as exc:
        return {"continue": True, "system_message": f"Subagent Governance 会话状态清理失败：{_bounded(exc)}"}
    if deleted: return {"continue": True, "system_message": getattr(store, "last_warning", None)}
    unresolved = [view for view in preserved if view.get("lifecycle") != "tombstoned" or view.get("action_required")]
    def describe(view: dict[str, Any]) -> str:
        candidates = view.get("execution_candidates") if isinstance(view.get("execution_candidates"), list) else []
        current = next((item for item in candidates if item.get("attempt") == view.get("current_attempt")), {})
        return f"{view.get('task_id', 'unknown')}({current.get('execution', view.get('lifecycle', 'indeterminate'))})"
    summary = "、".join(describe(view) for view in unresolved[:6])
    tombstones = "仍有 tombstone 处于7天保留期" if not summary else ""
    return {"continue": True, "system_message": f"Subagent Governance 检测到仍需恢复或决策的治理任务，已保留治理状态：{summary or tombstones or 'health 或 work-item 状态未满足删除条件'}。SessionEnd 不会终止子 Agent；恢复同一会话后按 SessionStart 摘要继续处理。"}
