#!/usr/bin/env python3

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.schema_validation import validate_instance

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_context", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class ContextManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = governance.StateStore(self.root / "state" / "sessions")
        self.prepared = governance.PreparedContractStore(self.root / "state" / "prepared")

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def contract(**overrides):
        value = {
            "semantic_name": "context_check",
            "requested_mode": "standard",
            "task_features": {
                "risk": "medium",
                "read_only": False,
                "writes_files": True,
                "destructive": False,
                "production": False,
                "concurrent_write": False,
            },
            "objective": "x",
            "background": "y",
            "work_scope": ["z"],
            "forbidden_scope": [],
            "completion_conditions": ["q"],
            "evidence_requirements": ["e"],
            "relevant_files": [],
            "context_manifest": {"mode": "none"},
            "current_state": None,
            "model": None,
            "reasoning_effort": None,
            "context_strategy": "isolated",
            "context_turns": None,
            "context_reason": None,
        }
        value.update(overrides)
        return value

    def init_repository(self) -> tuple[Path, str]:
        repository = self.root / "repository"
        repository.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(
            ["git", "config", "user.email", "context@example.test"],
            cwd=repository,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Context Test"],
            cwd=repository,
            check=True,
        )
        docs = repository / "docs"
        docs.mkdir()
        (docs / "task.md").write_text("baseline\n", encoding="utf-8")
        subprocess.run(["git", "add", "docs/task.md"], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repository, check=True)
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return repository, revision

    def prepare(self, contract):
        return governance.prepare_dispatch(
            contract,
            "session-1",
            state_store=self.store,
            prepared_store=self.prepared,
            task_id_factory=lambda: "sg-context-task",
        )

    def test_all_model_input_directions_are_required_but_nullable_overrides_are_valid(self):
        normalized = governance._contract_from_input(self.contract())
        self.assertIsNone(normalized.model)
        self.assertIsNone(normalized.reasoning_effort)

        for field_name in (
            "task_features",
            "model",
            "reasoning_effort",
            "context_manifest",
        ):
            with self.subTest(field_name=field_name):
                value = self.contract()
                value.pop(field_name)
                with self.assertRaisesRegex(ValueError, field_name):
                    governance._contract_from_input(value)

    def test_schema_requires_every_task_contract_direction_and_has_manifest_union(self):
        contract_schema = json.loads(
            (ROOT / "schemas" / "task-contract-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        semantics = json.loads(
            (ROOT / "schemas" / "governance-semantics.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            set(contract_schema["required"]),
            set(contract_schema["properties"]),
        )
        self.assertEqual(governance.TASK_CONTRACT_OPTIONAL_FIELDS, ())
        manifest = semantics["$defs"]["context_manifest"]
        self.assertEqual(
            {
                branch["properties"]["mode"]["const"]
                for branch in manifest["oneOf"]
            },
            {"none", "declared"},
        )

    def test_none_manifest_accepts_opaque_business_text_without_semantic_scoring(self):
        result = self.prepare(self.contract())

        self.assertEqual(result["contract"]["context_manifest"], {"mode": "none"})
        self.assertEqual(result["context_verification"], {"mode": "none"})
        self.assertIn("【必需上下文】\n- 无", result["dispatch_prompt"])

    def test_git_commit_manifest_verifies_required_path_and_projects_object_id(self):
        repository, revision = self.init_repository()
        manifest = {
            "mode": "declared",
            "workspace_root": str(repository),
            "baseline": {"kind": "git_commit", "revision": revision},
            "required_paths": [{"path": "docs/task.md", "type": "file"}],
        }

        result = self.prepare(
            self.contract(
                relevant_files=["docs/task.md"],
                context_manifest=manifest,
            )
        )

        verification = result["context_verification"]
        self.assertEqual(verification["baseline"]["revision"], revision)
        self.assertRegex(verification["required_paths"][0]["object_id"], r"^[a-f0-9]{40,64}$")
        self.assertIn(revision, result["dispatch_prompt"])
        self.assertIn("docs/task.md（file，已验证）", result["dispatch_prompt"])

    def test_git_commit_manifest_rejects_uncommitted_required_path_before_state_creation(self):
        repository, revision = self.init_repository()
        (repository / "docs" / "uncommitted.md").write_text("not committed\n", encoding="utf-8")
        manifest = {
            "mode": "declared",
            "workspace_root": str(repository),
            "baseline": {"kind": "git_commit", "revision": revision},
            "required_paths": [{"path": "docs/uncommitted.md", "type": "file"}],
        }

        with self.assertRaisesRegex(governance.DispatchPreparationError, "docs/uncommitted.md"):
            self.prepare(self.contract(context_manifest=manifest))

        state = self.store.read("session-1")
        self.assertEqual(state["tasks"], {})
        self.assertEqual(self.prepared.refs("session-1"), set())

    def test_git_commit_manifest_rejects_dirty_materialized_required_path(self):
        repository, revision = self.init_repository()
        (repository / "docs" / "task.md").write_text("dirty\n", encoding="utf-8")
        manifest = {
            "mode": "declared",
            "workspace_root": str(repository),
            "baseline": {"kind": "git_commit", "revision": revision},
            "required_paths": [{"path": "docs/task.md", "type": "file"}],
        }

        with self.assertRaisesRegex(
            governance.DispatchPreparationError,
            "工作区内容与 Git baseline 不一致",
        ):
            self.prepare(self.contract(context_manifest=manifest))

    def test_git_commit_manifest_requires_current_head_to_equal_baseline(self):
        repository, revision = self.init_repository()
        (repository / "other.txt").write_text("next\n", encoding="utf-8")
        subprocess.run(["git", "add", "other.txt"], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-qm", "next"], cwd=repository, check=True)
        manifest = {
            "mode": "declared",
            "workspace_root": str(repository),
            "baseline": {"kind": "git_commit", "revision": revision},
            "required_paths": [{"path": "docs/task.md", "type": "file"}],
        }

        with self.assertRaisesRegex(
            governance.DispatchPreparationError,
            "HEAD 与声明 baseline 不一致",
        ):
            self.prepare(self.contract(context_manifest=manifest))

    def test_working_tree_change_between_prepare_and_spawn_is_denied(self):
        repository, _revision = self.init_repository()
        manifest = {
            "mode": "declared",
            "workspace_root": str(repository),
            "baseline": {"kind": "working_tree", "revision": None},
            "required_paths": [{"path": "docs/task.md", "type": "file"}],
        }
        prepared = self.prepare(self.contract(context_manifest=manifest))
        (repository / "docs" / "task.md").write_text("changed\n", encoding="utf-8")
        payload = {
            "session_id": "session-1",
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "spawn-context-1",
            "tool_input": dict(prepared["spawn_args"]),
        }

        result = governance.handle(payload, self.store)

        output = result["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("必需上下文", output["permissionDecisionReason"])
        persisted = self.prepared.read("session-1", prepared["task_ref"])
        self.assertFalse(persisted["consumed"])

    def test_working_tree_directory_is_rejected_before_state_creation(self):
        repository, _revision = self.init_repository()
        manifest = {
            "mode": "declared",
            "workspace_root": str(repository),
            "baseline": {"kind": "working_tree", "revision": None},
            "required_paths": [{"path": "docs", "type": "directory"}],
        }

        with self.assertRaisesRegex(
            ValueError,
            "working_tree.*directory.*逐文件.*git_commit",
        ):
            self.prepare(self.contract(context_manifest=manifest))

        self.assertEqual(self.store.read("session-1")["tasks"], {})
        self.assertEqual(self.prepared.refs("session-1"), set())

    def test_git_commit_directory_uses_tree_object_and_rejects_workspace_drift(self):
        repository, revision = self.init_repository()
        manifest = {
            "mode": "declared",
            "workspace_root": str(repository),
            "baseline": {"kind": "git_commit", "revision": revision},
            "required_paths": [{"path": "docs", "type": "directory"}],
        }

        prepared = self.prepare(self.contract(context_manifest=manifest))
        self.assertRegex(
            prepared["context_verification"]["required_paths"][0]["object_id"],
            r"^[a-f0-9]{40,64}$",
        )

        (repository / "docs" / "untracked.md").write_text(
            "drift\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            governance.DispatchPreparationError,
            "工作区内容与 Git baseline 不一致",
        ):
            governance.prepare_dispatch(
                self.contract(context_manifest=manifest),
                "session-2",
                state_store=self.store,
                prepared_store=self.prepared,
                task_id_factory=lambda: "sg-context-directory-drift",
            )

    def test_prepared_contract_rejects_tampered_context_verification(self):
        prepared = self.prepare(self.contract())
        record = self.prepared.read("session-1", prepared["task_ref"])
        record["context_verification"] = {"mode": "none", "claimed": True}

        with self.assertRaisesRegex(
            governance.PreparedContractValidationError,
            "context_verification",
        ):
            governance.PreparedContractStore._validate_record(
                record,
                "session-1",
                prepared["task_ref"],
                self.root / "tampered.json",
            )

    def test_manifest_rejects_path_escape_without_reading_outside_workspace(self):
        repository, _revision = self.init_repository()
        manifest = {
            "mode": "declared",
            "workspace_root": str(repository),
            "baseline": {"kind": "working_tree", "revision": None},
            "required_paths": [{"path": "../outside.txt", "type": "file"}],
        }

        with self.assertRaisesRegex(ValueError, "不能包含"):
            governance._contract_from_input(self.contract(context_manifest=manifest))

    def test_context_manifest_cli_is_transport_neutral_and_read_only(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--verify-context-manifest"],
            input=json.dumps({"mode": "none"}),
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"mode": "none"})
        self.assertEqual(list((self.root / "state" / "sessions").glob("*.json")), [])

    def test_context_manifest_cli_and_schema_reject_working_tree_directory(self):
        semantics = json.loads(
            (ROOT / "schemas" / "governance-semantics.schema.json").read_text(
                encoding="utf-8"
            )
        )
        manifest = {
            "mode": "declared",
            "workspace_root": str(self.root),
            "baseline": {"kind": "working_tree", "revision": None},
            "required_paths": [{"path": "docs", "type": "directory"}],
        }

        self.assertTrue(
            validate_instance(
                manifest,
                semantics["$defs"]["context_manifest"],
                root_schema=semantics,
            )
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--verify-context-manifest"],
            input=json.dumps(manifest),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertRegex(
            result.stderr,
            "working_tree.*directory.*逐文件.*git_commit",
        )


if __name__ == "__main__":
    unittest.main()
