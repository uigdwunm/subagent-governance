#!/usr/bin/env python3
"""Read-only checks for development/stable/runtime plugin separation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path


PLUGIN_NAME = "subagent-governance"
START_MARKER = "<!-- subagent-governance:start -->"
END_MARKER = "<!-- subagent-governance:end -->"


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"插件目录中不允许符号链接：{path}")
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root)
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(oct(path.stat().st_mode & 0o777).encode("ascii"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def ordinary_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"{label} 必须是普通目录且不能是符号链接：{path}")
    metadata = path.stat()
    getuid = getattr(os, "getuid", None)
    if getuid is not None and getattr(metadata, "st_uid", getuid()) != getuid():
        raise PermissionError(f"{label} 必须由当前用户拥有：{path}")
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o022:
        raise PermissionError(f"{label} 不能允许组用户或其他用户写入：{path}")


def instruction_block(text: str) -> str | None:
    if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
        return None
    start = text.index(START_MARKER)
    end_start = text.index(END_MARKER)
    if end_start < start:
        return None
    end = end_start + len(END_MARKER)
    return text[start:end].strip()


def cache_inventory(
    cache_parent: Path,
    current_cache: Path,
) -> tuple[list[str], list[str], list[dict[str, str]]]:
    """Separate retained immutable caches from unsafe cache entries."""

    retained: list[str] = []
    invalid: list[str] = []
    invalid_details: list[dict[str, str]] = []
    for entry in sorted(cache_parent.iterdir(), key=lambda path: path.name):
        if entry == current_cache:
            continue
        try:
            ordinary_directory(entry, "版本化兼容缓存")
            tree_digest(entry)
        except (OSError, RuntimeError) as exc:
            invalid.append(str(entry))
            invalid_details.append({"path": str(entry), "error": str(exc)})
            continue
        retained.append(str(entry))
    return retained, invalid, invalid_details


def manifest_version(stable: Path) -> str:
    manifest_path = stable / ".codex-plugin/plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取稳定发布源 Manifest：{manifest_path}；原因：{exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError(f"稳定发布源 Manifest 根节点必须是对象：{manifest_path}")
    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError(f"稳定发布源 Manifest version 必须是非空字符串：{manifest_path}")
    return version.strip()


def version_directory_name(version: str, label: str) -> str:
    value = version.strip()
    if not value or value in {".", ".."} or Path(value).name != value:
        raise ValueError(f"{label} 必须是单个非空版本目录名：{version!r}")
    return value


def failure_report(exc: Exception) -> dict[str, object]:
    return {
        "runtime_healthy": False,
        "deployment_in_sync": False,
        "development_rules_in_sync": None,
        "retention_policy_satisfied": None,
        "release_ready": None,
        "release_readiness_status": "not_evaluated",
        "runtime_issues": ["check_failed"],
        "deployment_issues": ["check_failed"],
        "warnings": ["release_readiness_not_evaluated"],
        "fatal_error": {
            "type": type(exc).__name__,
            "message": str(exc),
        },
    }


def config_references_hook(config_path: Path, hook_path: Path) -> bool:
    if not config_path.exists():
        return False
    text = config_path.read_text(encoding="utf-8")
    candidates = {str(hook_path)}
    if hook_path.exists() or hook_path.is_symlink():
        candidates.add(str(hook_path.resolve()))
    return any(candidate in text for candidate in candidates)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--development-root",
        type=Path,
        default=Path.home() / "workspace" / PLUGIN_NAME,
    )
    parser.add_argument("--stable-root", type=Path, default=Path.home() / "plugins" / PLUGIN_NAME)
    parser.add_argument(
        "--cache-parent",
        type=Path,
        default=Path.home() / ".codex/plugins/cache/personal" / PLUGIN_NAME,
    )
    parser.add_argument("--agents-file", type=Path, default=Path.home() / ".codex/AGENTS.md")
    parser.add_argument("--legacy-hook", type=Path, default=Path.home() / ".codex/hooks/subagent_policy.py")
    parser.add_argument("--active-hooks-config", type=Path, default=Path.home() / ".codex/hooks.json")
    parser.add_argument("--require-development-sync", action="store_true")
    parser.add_argument("--require-retention-policy", action="store_true")
    parser.add_argument(
        "--expected-previous-version",
        help="发布前记录的升级前实际 installed/current 版本，用于确认唯一 N-1 身份",
    )
    args = parser.parse_args()

    try:
        development_path = args.development_root.expanduser().absolute()
        stable_path = args.stable_root.expanduser().absolute()
        cache_parent_path = args.cache_parent.expanduser().absolute()
        ordinary_directory(development_path, "开发仓库")
        ordinary_directory(stable_path, "稳定发布源")
        ordinary_directory(cache_parent_path, "插件缓存父目录")
        development = development_path.resolve()
        stable = stable_path.resolve()

        version = manifest_version(stable)
        cache_path = cache_parent_path / version
        ordinary_directory(cache_path, "当前版本缓存")
        cache = cache_path.resolve()
        installation_paths_separated = len({development, stable, cache}) == 3
        retained_caches, invalid_cache_entries, invalid_cache_details = cache_inventory(
            cache_parent_path,
            cache_path,
        )
        expected_previous_version = (
            version_directory_name(args.expected_previous_version, "预期上一版本")
            if args.expected_previous_version is not None
            else None
        )
        if expected_previous_version == version:
            raise ValueError("预期上一版本必须不同于当前稳定版本")
        expected_previous_cache = (
            str(cache_parent_path / expected_previous_version)
            if expected_previous_version is not None
            else None
        )

        stable_digest = tree_digest(stable)
        cache_digest = tree_digest(cache)
        development_asset = development / "assets/agents-governance.md"
        stable_asset = stable / "assets/agents-governance.md"
        agents_path = args.agents_file.expanduser().absolute()
        development_block = (
            instruction_block(development_asset.read_text(encoding="utf-8"))
            if development_asset.is_file() else None
        )
        expected_block = (
            instruction_block(stable_asset.read_text(encoding="utf-8"))
            if stable_asset.is_file() else None
        )
        active_block = (
            instruction_block(agents_path.read_text(encoding="utf-8"))
            if agents_path.is_file() else None
        )
        legacy_hook = args.legacy_hook.expanduser().absolute()
        active_hooks_config = args.active_hooks_config.expanduser().absolute()
        legacy_hook_present = legacy_hook.exists() or legacy_hook.is_symlink()
        legacy_hook_mounted = config_references_hook(active_hooks_config, legacy_hook)

        runtime_checks = {
            "installation_paths_separated": installation_paths_separated,
            "stable_matches_cache": stable_digest == cache_digest,
            "agents_matches_stable_asset": expected_block is not None and active_block == expected_block,
            "cache_entries_safe": not invalid_cache_entries,
            "legacy_hook_unmounted": not legacy_hook_mounted,
        }
        deployment_checks = {
            "stable_matches_cache": runtime_checks["stable_matches_cache"],
            "agents_matches_stable_asset": runtime_checks["agents_matches_stable_asset"],
        }
        development_rules_in_sync = (
            development_block is not None
            and expected_block is not None
            and development_block == expected_block
        )
        retained_previous_cache_matches_expected = (
            retained_caches == [expected_previous_cache]
            if expected_previous_cache is not None
            else None
        )
        retention_policy_satisfied = (
            len(retained_caches) <= 1
            and retained_previous_cache_matches_expected is not False
        )
        runtime_issues = [name for name, passed in runtime_checks.items() if not passed]
        deployment_issues = [name for name, passed in deployment_checks.items() if not passed]
        warnings = ["codex_registration_not_checked", "hook_trust_not_checked", "release_readiness_not_evaluated"]
        if not development_rules_in_sync:
            warnings.append("development_rules_not_deployed")
        if len(retained_caches) > 1:
            warnings.append("retention_window_exceeded")
        if retained_previous_cache_matches_expected is False:
            warnings.append("retained_previous_cache_mismatch")
        if legacy_hook_present and not legacy_hook_mounted:
            warnings.append("legacy_hook_present_but_unmounted")

        report = {
            "development_root": str(development),
            "stable_root": str(stable),
            "runtime_cache": str(cache),
            "version": version,
            "stable_digest": stable_digest,
            "cache_digest": cache_digest,
            "retained_compatibility_caches": retained_caches,
            "retained_cache_count": len(retained_caches),
            "expected_previous_version": expected_previous_version,
            "expected_previous_cache": expected_previous_cache,
            "retained_previous_cache_matches_expected": retained_previous_cache_matches_expected,
            "invalid_cache_entries": invalid_cache_entries,
            "invalid_cache_details": invalid_cache_details,
            **runtime_checks,
            "runtime_healthy": not runtime_issues,
            "runtime_issues": runtime_issues,
            "deployment_in_sync": not deployment_issues,
            "deployment_issues": deployment_issues,
            "development_rules_in_sync": development_rules_in_sync,
            "retention_policy_satisfied": retention_policy_satisfied,
            "release_ready": None,
            "release_readiness_status": "not_evaluated",
            "runtime_health_scope": "filesystem_cache_global_rules_and_legacy_mount",
            "codex_registration_checked": False,
            "hook_trust_checked": False,
            "warnings": warnings,
            "active_hooks_config": str(active_hooks_config),
            "legacy_hook_present": legacy_hook_present,
            "legacy_hook_mounted": legacy_hook_mounted,
        }
    except (OSError, RuntimeError, ValueError) as exc:
        report = failure_report(exc)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not report["runtime_healthy"]:
        return 1
    if args.require_development_sync and not report["development_rules_in_sync"]:
        return 1
    if args.require_retention_policy and not report["retention_policy_satisfied"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
