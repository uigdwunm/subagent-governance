#!/usr/bin/env python3
"""Read-only checks for development/stable/runtime plugin separation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PLUGIN_NAME = "subagent-governance"


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root)
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def ordinary_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"{label} 必须是普通目录且不能是符号链接：{path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stable-root", type=Path, default=Path.home() / "plugins" / PLUGIN_NAME)
    parser.add_argument(
        "--cache-parent",
        type=Path,
        default=Path.home() / ".codex/plugins/cache/personal" / PLUGIN_NAME,
    )
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

    stable_digest = tree_digest(stable)
    cache_digest = tree_digest(cache)
    report = {
        "development_root": str(development),
        "stable_root": str(stable),
        "runtime_cache": str(cache),
        "version": version,
        "stable_digest": stable_digest,
        "cache_digest": cache_digest,
        "stable_matches_cache": stable_digest == cache_digest,
        "separated": development != stable,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["stable_matches_cache"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
