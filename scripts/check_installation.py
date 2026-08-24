#!/usr/bin/env python3
"""Read-only checks for the current plugin and one restart-compatibility cache."""

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
    return text[start : end_start + len(END_MARKER)].strip()


def manifest_version(stable: Path) -> str:
    manifest_path = stable / ".codex-plugin/plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"无法读取稳定发布源 Manifest：{manifest_path}；原因：{exc}"
        ) from exc
    if not isinstance(manifest, dict):
        raise RuntimeError(f"稳定发布源 Manifest 根节点必须是对象：{manifest_path}")
    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError(
            f"稳定发布源 Manifest version 必须是非空字符串：{manifest_path}"
        )
    return version.strip()


def rolling_cache_set(
    cache_parent: Path, current_cache: Path
) -> tuple[Path | None, str | None, str | None, list[str], bool]:
    """Validate an optional compatibility cache without assigning platform roles.

    The current cache is established by the stable Manifest.  A second safe
    directory is merely retained for old sessions; directory names and ordering
    never establish registered/current identity.
    """
    compatibility: list[tuple[Path, str, str]] = []
    invalid_entries: list[str] = []
    for entry in sorted(cache_parent.iterdir(), key=lambda path: path.name):
        if entry == current_cache:
            continue
        try:
            ordinary_directory(entry, "兼容插件缓存")
            version = manifest_version(entry)
            if version != entry.name:
                raise RuntimeError("兼容插件缓存 Manifest version 必须与目录名一致")
            compatibility.append((entry, version, tree_digest(entry)))
        except (OSError, RuntimeError, ValueError):
            invalid_entries.append(str(entry))

    valid = not invalid_entries and len(compatibility) <= 1
    unexpected = invalid_entries[:]
    if len(compatibility) > 1:
        unexpected.extend(str(entry) for entry, _, _ in compatibility)
    if not valid or not compatibility:
        return None, None, None, unexpected, valid
    cache, version, digest = compatibility[0]
    return cache, version, digest, unexpected, valid


def failure_report(exc: Exception) -> dict[str, object]:
    return {
        "runtime_healthy": False,
        "deployment_in_sync": False,
        "development_rules_in_sync": None,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--development-root",
        type=Path,
        default=Path.home() / "workspace" / PLUGIN_NAME,
    )
    parser.add_argument(
        "--stable-root", type=Path, default=Path.home() / "plugins" / PLUGIN_NAME
    )
    parser.add_argument(
        "--cache-parent",
        type=Path,
        default=Path.home() / ".codex/plugins/cache/personal" / PLUGIN_NAME,
    )
    parser.add_argument(
        "--agents-file", type=Path, default=Path.home() / ".codex/AGENTS.md"
    )
    parser.add_argument("--require-development-sync", action="store_true")
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
        (
            retained_previous,
            retained_previous_version,
            retained_previous_digest,
            unexpected_caches,
            rolling_cache_set_valid,
        ) = rolling_cache_set(cache_parent_path, cache_path)

        stable_digest = tree_digest(stable)
        cache_digest = tree_digest(cache)
        development_asset = development / "assets/agents-governance.md"
        stable_asset = stable / "assets/agents-governance.md"
        agents_path = args.agents_file.expanduser().absolute()
        development_block = (
            instruction_block(development_asset.read_text(encoding="utf-8"))
            if development_asset.is_file()
            else None
        )
        expected_block = (
            instruction_block(stable_asset.read_text(encoding="utf-8"))
            if stable_asset.is_file()
            else None
        )
        active_block = (
            instruction_block(agents_path.read_text(encoding="utf-8"))
            if agents_path.is_file()
            else None
        )

        runtime_checks = {
            "installation_paths_separated": installation_paths_separated,
            "current_cache_present": True,
            "current_cache_matches_stable": stable_digest == cache_digest,
            "agents_matches_stable_asset": (
                expected_block is not None and active_block == expected_block
            ),
            "rolling_cache_set_valid": rolling_cache_set_valid,
        }
        deployment_checks = {
            "current_cache_matches_stable": runtime_checks[
                "current_cache_matches_stable"
            ],
            "agents_matches_stable_asset": runtime_checks[
                "agents_matches_stable_asset"
            ],
        }
        development_rules_in_sync = (
            development_block is not None
            and expected_block is not None
            and development_block == expected_block
        )
        runtime_issues = [name for name, passed in runtime_checks.items() if not passed]
        deployment_issues = [
            name for name, passed in deployment_checks.items() if not passed
        ]
        warnings = [
            "codex_registration_not_checked",
            "hook_trust_not_checked",
            "release_readiness_not_evaluated",
        ]
        if not development_rules_in_sync:
            warnings.append("development_rules_not_deployed")
        if unexpected_caches:
            warnings.append("unexpected_extra_cache")

        report = {
            "development_root": str(development),
            "stable_root": str(stable),
            "runtime_cache": str(cache),
            "version": version,
            "stable_digest": stable_digest,
            "cache_digest": cache_digest,
            "current_cache_present": runtime_checks["current_cache_present"],
            "current_cache_matches_stable": runtime_checks[
                "current_cache_matches_stable"
            ],
            "compatibility_cache_count": len(
                [entry for entry in cache_parent_path.iterdir() if entry != cache_path]
            ),
            "rolling_cache_set_valid": rolling_cache_set_valid,
            "retained_previous_cache": (
                str(retained_previous) if retained_previous is not None else None
            ),
            "retained_previous_version": retained_previous_version,
            "retained_previous_digest": retained_previous_digest,
            "unexpected_cache_entries": unexpected_caches,
            **runtime_checks,
            "runtime_healthy": not runtime_issues,
            "runtime_issues": runtime_issues,
            "deployment_in_sync": not deployment_issues,
            "deployment_issues": deployment_issues,
            "development_rules_in_sync": development_rules_in_sync,
            "release_ready": None,
            "release_readiness_status": "not_evaluated",
            "runtime_health_scope": "filesystem_current_cache_and_global_rules",
            "codex_registration_checked": False,
            "hook_trust_checked": False,
            "warnings": warnings,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
