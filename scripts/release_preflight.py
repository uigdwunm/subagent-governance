#!/usr/bin/env python3
"""Portable release checks for source trees and git-archive candidates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

PLUGIN_NAME = "subagent-governance"
MANIFEST_PATH = Path(".codex-plugin/plugin.json")
MARKETPLACE_PATH = Path(".agents/plugins/marketplace.json")
SKILL_PATH = Path("skills/subagent-governance/SKILL.md")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\."
    r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_PUBLIC_FILES = (
    Path("LICENSE"),
    Path("README.md"),
    Path("README.zh-CN.md"),
    Path("CONTRIBUTING.md"),
    Path("SECURITY.md"),
    Path("hooks/hooks.json"),
    Path(".github/ISSUE_TEMPLATE/bug_report.yml"),
    Path(".github/ISSUE_TEMPLATE/feature_request.yml"),
    Path(".github/pull_request_template.md"),
)
TEXT_SUFFIXES = {
    "",
    ".json",
    ".md",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
}
MANIFEST_KEYS = {
    "id",
    "name",
    "version",
    "description",
    "skills",
    "apps",
    "mcpServers",
    "interface",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
}
AUTHOR_KEYS = {"name", "email", "url"}
INTERFACE_KEYS = {
    "displayName",
    "shortDescription",
    "longDescription",
    "developerName",
    "category",
    "capabilities",
    "websiteURL",
    "privacyPolicyURL",
    "termsOfServiceURL",
    "brandColor",
    "composerIcon",
    "logo",
    "logoDark",
    "screenshots",
    "defaultPrompt",
    "default_prompt",
}


class PreflightFailure(RuntimeError):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a Subagent Governance source or release tree."
    )
    parser.add_argument("--root", default=".", help="Source or extracted archive root")
    parser.add_argument(
        "--mode",
        choices=("development", "archive", "release"),
        default="development",
    )
    parser.add_argument(
        "--tag",
        help="Git tag for release mode; must equal v<manifest public version>",
    )
    return parser.parse_args(argv)


def load_json_object(root: Path, relative: Path) -> dict[str, Any]:
    path = root / relative
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PreflightFailure(f"missing required JSON file: {relative}") from exc
    except json.JSONDecodeError as exc:
        raise PreflightFailure(f"invalid JSON in {relative}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PreflightFailure(f"{relative} must contain a JSON object")
    return payload


def require_non_empty_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PreflightFailure(f"{label}.{key} must be a non-empty string")
    return value.strip()


def reject_unknown_keys(
    payload: dict[str, Any], allowed: set[str], label: str
) -> None:
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise PreflightFailure(
            f"{label} contains unsupported field(s): {', '.join(unexpected)}"
        )


def require_https_url(payload: dict[str, Any], key: str, label: str) -> None:
    value = payload.get(key)
    if value is None:
        return
    if not isinstance(value, str):
        raise PreflightFailure(f"{label}.{key} must be an absolute https:// URL")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise PreflightFailure(f"{label}.{key} must be an absolute https:// URL")


def public_version(version: str) -> str:
    return version.split("+", 1)[0]


def validate_manifest(root: Path) -> tuple[dict[str, Any], str, str]:
    manifest = load_json_object(root, MANIFEST_PATH)
    reject_unknown_keys(manifest, MANIFEST_KEYS, "plugin.json")
    name = require_non_empty_string(manifest, "name", "plugin.json")
    if name != PLUGIN_NAME:
        raise PreflightFailure(
            f"plugin.json name must be {PLUGIN_NAME!r}, got {name!r}"
        )
    version = require_non_empty_string(manifest, "version", "plugin.json")
    if SEMVER_RE.fullmatch(version) is None:
        raise PreflightFailure(f"plugin.json version is not strict semver: {version!r}")
    require_non_empty_string(manifest, "description", "plugin.json")
    if manifest.get("skills") != "./skills/":
        raise PreflightFailure("plugin.json skills must be './skills/'")
    if "hooks" in manifest:
        raise PreflightFailure(
            "plugin.json must not declare hooks; hooks/hooks.json is auto-discovered"
        )
    if manifest.get("license") != "MIT":
        raise PreflightFailure("plugin.json license must be MIT")
    for field_name in ("homepage", "repository"):
        require_https_url(manifest, field_name, "plugin.json")
    author = manifest.get("author")
    if not isinstance(author, dict):
        raise PreflightFailure("plugin.json.author must be an object")
    reject_unknown_keys(author, AUTHOR_KEYS, "plugin.json.author")
    require_non_empty_string(author, "name", "plugin.json.author")
    for field_name in ("email", "url"):
        if field_name in author and not isinstance(author[field_name], str):
            raise PreflightFailure(
                f"plugin.json.author.{field_name} must be a non-empty string"
            )
    if "email" in author and not author["email"].strip():
        raise PreflightFailure("plugin.json.author.email must be a non-empty string")
    if "url" in author:
        require_https_url(author, "url", "plugin.json.author")
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        raise PreflightFailure("plugin.json interface must be an object")
    reject_unknown_keys(interface, INTERFACE_KEYS, "plugin.json.interface")
    for field in (
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
        "defaultPrompt",
    ):
        require_non_empty_string(interface, field, "plugin.json.interface")
    capabilities = interface.get("capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(value, str) and value.strip() for value in capabilities
    ):
        raise PreflightFailure(
            "plugin.json interface.capabilities must be a non-empty string array"
        )
    for field_name in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
        require_https_url(interface, field_name, "plugin.json.interface")
    return manifest, version, public_version(version)


def parse_simple_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PreflightFailure(f"missing Skill entrypoint: {path}") from exc
    if not text.startswith("---\n"):
        raise PreflightFailure(f"{path} must start with YAML frontmatter")
    closing = text.find("\n---", 4)
    if closing < 0:
        raise PreflightFailure(f"{path} has unterminated YAML frontmatter")
    result: dict[str, str] = {}
    for line in text[4:closing].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise PreflightFailure(f"unsupported frontmatter line in {path}: {line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise PreflightFailure(f"empty frontmatter key or value in {path}: {line!r}")
        result[key] = value
    return result


def validate_skill(root: Path) -> None:
    frontmatter = parse_simple_frontmatter(root / SKILL_PATH)
    unexpected = set(frontmatter) - {
        "name",
        "description",
        "license",
        "allowed-tools",
        "metadata",
    }
    if unexpected:
        raise PreflightFailure(
            f"unexpected Skill frontmatter fields: {', '.join(sorted(unexpected))}"
        )
    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    if name != PLUGIN_NAME or SKILL_NAME_RE.fullmatch(name) is None:
        raise PreflightFailure(f"Skill name must be {PLUGIN_NAME!r}")
    if not description or len(description) > 1024 or "<" in description or ">" in description:
        raise PreflightFailure(
            "Skill description must be non-empty, <=1024 characters, and contain no angle brackets"
        )


def validate_marketplace(root: Path, public: str, mode: str, tag: str | None) -> str:
    marketplace = load_json_object(root, MARKETPLACE_PATH)
    if marketplace.get("name") != PLUGIN_NAME:
        raise PreflightFailure(f"marketplace name must be {PLUGIN_NAME!r}")
    entries = marketplace.get("plugins")
    if not isinstance(entries, list) or len(entries) != 1:
        raise PreflightFailure("marketplace must contain exactly one plugin entry")
    entry = entries[0]
    if not isinstance(entry, dict) or entry.get("name") != PLUGIN_NAME:
        raise PreflightFailure("marketplace plugin entry name is invalid")
    source = entry.get("source")
    if not isinstance(source, dict):
        raise PreflightFailure("marketplace plugin source must be an object")
    if source.get("source") != "url":
        raise PreflightFailure("public marketplace source must use source='url'")
    if source.get("url") != "https://github.com/uigdwunm/subagent-governance.git":
        raise PreflightFailure("public marketplace repository URL is invalid")
    ref = source.get("ref")
    expected_tag = f"v{public}"
    if mode == "release":
        if not tag:
            raise PreflightFailure("release mode requires --tag")
        if tag != expected_tag:
            raise PreflightFailure(
                f"release tag must be {expected_tag!r} for the Manifest version, got {tag!r}"
            )
        if ref != tag:
            raise PreflightFailure(
                f"release marketplace ref must equal the release tag {tag!r}, got {ref!r}"
            )
    elif ref not in {"main", expected_tag}:
        raise PreflightFailure(
            f"development marketplace ref must be 'main' or {expected_tag!r}, got {ref!r}"
        )
    policy = entry.get("policy")
    if policy != {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}:
        raise PreflightFailure("marketplace policy must use AVAILABLE and ON_INSTALL")
    if entry.get("category") != "Developer Tools":
        raise PreflightFailure("marketplace category must be 'Developer Tools'")
    return str(ref)


def validate_public_files(root: Path, mode: str) -> None:
    missing = [str(path) for path in REQUIRED_PUBLIC_FILES if not (root / path).is_file()]
    if missing:
        raise PreflightFailure(
            "missing public release files: " + ", ".join(sorted(missing))
        )
    raw_reports = sorted((root / "docs").glob("private-platform-evidence-*.md"))
    if mode == "archive" and raw_reports:
        relative = [str(path.relative_to(root)) for path in raw_reports]
        raise PreflightFailure(
            "git archive contains private platform evidence: " + ", ".join(relative)
        )


def iter_text_files(root: Path) -> Iterable[Path]:
    excluded_parts = {".git", "__pycache__", ".pytest_cache"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in excluded_parts for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.name.startswith("private-platform-evidence-") and path.suffix == ".md":
            continue
        yield path


def validate_public_text(root: Path) -> None:
    scanner_path = (root / "scripts/release_preflight.py").resolve()
    findings: list[str] = []
    secret_patterns = (
        ("private key", re.compile("-----BEGIN " + r"(?:[A-Z ]+ )?PRIVATE KEY-----")),
        ("GitHub classic token", re.compile("gh" + r"p_[A-Za-z0-9]{20,}")),
        ("GitHub fine-grained token", re.compile("github_" + r"pat_[A-Za-z0-9_]{20,}")),
        ("AWS access key", re.compile("AK" + r"IA[0-9A-Z]{16}")),
    )
    host_path_patterns = (
        re.compile("/" + r"Users/[^/\s`]+"),
        re.compile("/" + r"home/[^/\s`]+"),
        re.compile(r"\.codex/sessions/.+rollout-"),
    )
    for path in iter_text_files(root):
        if path.resolve() == scanner_path:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(root)
        for pattern in host_path_patterns:
            if pattern.search(text):
                findings.append(f"host-specific path in {relative}")
                break
        for label, pattern in secret_patterns:
            if pattern.search(text):
                findings.append(f"possible {label} in {relative}")
    if findings:
        raise PreflightFailure("; ".join(sorted(set(findings))))


def run_preflight(root: Path, mode: str, tag: str | None = None) -> dict[str, Any]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise PreflightFailure(f"root is not a directory: {root}")
    validate_public_files(root, mode)
    _, version, public = validate_manifest(root)
    validate_skill(root)
    marketplace_ref = validate_marketplace(root, public, mode, tag)
    validate_public_text(root)
    return {
        "status": "passed",
        "mode": mode,
        "manifest_version": version,
        "public_version": public,
        "expected_tag": f"v{public}",
        "marketplace_ref": marketplace_ref,
        "tag": tag,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run_preflight(Path(args.root), args.mode, args.tag)
    except PreflightFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
