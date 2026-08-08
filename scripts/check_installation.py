#!/usr/bin/env python3
"""Read-only checks for development/stable/runtime plugin separation."""

from __future__ import annotations

import argparse
import hashlib
import json
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


def instruction_block(text: str) -> str | None:
    if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
        return None
    start = text.index(START_MARKER)
    end = text.index(END_MARKER, start) + len(END_MARKER)
    return text[start:end].strip()


def cache_inventory(cache_parent: Path, current_cache: Path) -> tuple[list[str], list[str]]:
    """Separate retained immutable caches from unsafe cache entries."""

    retained: list[str] = []
    invalid: list[str] = []
    for entry in sorted(cache_parent.iterdir(), key=lambda path: path.name):
        if entry == current_cache:
            continue
        if entry.is_symlink() or not entry.is_dir():
            invalid.append(str(entry))
        else:
            retained.append(str(entry))
    return retained, invalid


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
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()

    development_path = args.development_root.expanduser().absolute()
    stable_path = args.stable_root.expanduser().absolute()
    cache_parent = args.cache_parent.expanduser().absolute()
    ordinary_directory(development_path, "开发仓库")
    ordinary_directory(stable_path, "稳定发布源")
    development = development_path.resolve()
    stable = stable_path.resolve()
    if development == stable:
        raise RuntimeError("开发仓库和稳定发布源不能是同一目录")

    manifest = json.loads((stable / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    version = str(manifest["version"])
    cache_path = cache_parent / version
    ordinary_directory(cache_path, "当前版本缓存")
    cache = cache_path.resolve()
    retained_caches, invalid_cache_entries = cache_inventory(cache_parent, cache_path)

    stable_digest = tree_digest(stable)
    cache_digest = tree_digest(cache)
    development_asset = development / "assets/agents-governance.md"
    stable_asset = stable / "assets/agents-governance.md"
    agents_path = args.agents_file.expanduser().absolute()
    development_block = (
        instruction_block(development_asset.read_text(encoding="utf-8"))
        if development_asset.is_file() else None
    )
    expected_block = instruction_block(stable_asset.read_text(encoding="utf-8")) if stable_asset.is_file() else None
    active_block = instruction_block(agents_path.read_text(encoding="utf-8")) if agents_path.is_file() else None
    legacy_hook = args.legacy_hook.expanduser().absolute()
    active_hooks_config = args.active_hooks_config.expanduser().absolute()
    legacy_hook_present = legacy_hook.exists() or legacy_hook.is_symlink()
    legacy_hook_mounted = config_references_hook(active_hooks_config, legacy_hook)
    checks = {
        "stable_matches_cache": stable_digest == cache_digest,
        "separated": development != stable,
        "agents_matches_stable_asset": expected_block is not None and active_block == expected_block,
        "development_asset_matches_stable_asset": (
            development_block is not None and expected_block is not None and development_block == expected_block
        ),
        "cache_entries_safe": not invalid_cache_entries,
        "legacy_hook_unmounted": not legacy_hook_mounted,
    }
    issues = [name for name, passed in checks.items() if not passed]
    report = {
        "development_root": str(development),
        "stable_root": str(stable),
        "runtime_cache": str(cache),
        "version": version,
        "stable_digest": stable_digest,
        "cache_digest": cache_digest,
        "retained_compatibility_caches": retained_caches,
        "invalid_cache_entries": invalid_cache_entries,
        **checks,
        "agents_matches_asset": checks["agents_matches_stable_asset"],
        "active_hooks_config": str(active_hooks_config),
        "legacy_hook_present": legacy_hook_present,
        "legacy_hook_absent": not legacy_hook_present,
        "legacy_hook_mounted": legacy_hook_mounted,
        "clean": not issues,
        "issues": issues,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not report["stable_matches_cache"]:
        return 1
    return 1 if args.require_clean and issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
