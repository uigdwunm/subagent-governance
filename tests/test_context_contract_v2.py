#!/usr/bin/env python3

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import governance_semantics as semantics
from scripts.governance_contracts import contract_from_input
from scripts.governance_diagnostics import status
from scripts.governance_dispatch import claim_spawn, confirm_dispatch
from scripts.governance_dispatch_rendering import spawn_args
from scripts.governance_errors import DispatchPreparationError
from scripts.governance_hook import handle_hook
from scripts.governance_protocol import prepare_dispatch
from scripts.governance_state_store import StateStore
from tests.schema_validation import validate_instance


class ContextContractV2Tests(unittest.TestCase):
    def test_documented_handoffs_validate_and_reach_native_spawn_message(self):
        reference = Path(__file__).resolve().parents[1] / (
            "skills/subagent-governance/references/task-handoff.md"
        )
        examples = re.findall(r"```json\n(.*?)\n```", reference.read_text(encoding="utf-8"), re.S)
        self.assertTrue(examples, "交接参考缺少可验证的契约示例")
        for example in examples:
            raw = json.loads(example)
            with self.subTest(objective=raw.get("objective")):
                self.assertEqual(validate_instance(
                    raw, semantics.SEMANTIC_DEFINITIONS["task_contract_input"],
                    root_schema=semantics.MACHINE_SEMANTICS,
                ), [])
                contract = contract_from_input(raw)
                for interface in ("collaboration_turns", "fork_context"):
                    message = spawn_args(
                        contract, "sg_standard_handoff_t_abcdefabcdef", None,
                        native_interface=interface,
                    )["message"]
                    self.assertIn(contract.objective, message)
                    if contract.context["summary"]:
                        self.assertIn(contract.context["summary"], message)
                    for field in ("scope", "forbidden_scope", "completion", "evidence"):
                        for item in getattr(contract, field):
                            self.assertIn(item, message, (interface, field))
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    store = StateStore(root / "sessions")
                    prepared = prepare_dispatch(
                        raw, "handoff-recovery", native_interface="collaboration_turns",
                        state_store=store, now=100,
                    )
                    claim_spawn(
                        "handoff-recovery", prepared["task_ref"], "handoff-call",
                        prepared["spawn_args"], state_store=store, now=101,
                    )
                    identity = {key: prepared[key] for key in ("task_id", "task_ref")}
                    confirm_dispatch(
                        "handoff-recovery", {**identity, "target": "/root/handoff"},
                        state_store=store, now=102,
                    )
                    del store, prepared, raw
                    recovered = status("handoff-recovery", root, **identity)["tasks"][0]
                    self.assertEqual(recovered["phase"], "bound")
                    self.assertEqual(recovered["contract_summary"], contract.business_record())

    @staticmethod
    def verified_contract(workspace: Path, baseline: dict, required_paths: list[dict]) -> dict:
        return {
            "profile": "strict",
            "objective": "Verify exact material",
            "scope": ["verified context"],
            "forbidden_scope": ["external systems"],
            "completion": ["prepared"],
            "evidence": ["content identity"],
            "context": {
                "verified": {
                    "mode": "declared",
                    "workspace_root": str(workspace),
                    "baseline": baseline,
                    "required_paths": required_paths,
                }
            },
        }

    def test_ordinary_paths_are_hints_and_do_not_read_files(self):
        contract = contract_from_input(
            {
                "objective": "Use path hints",
                "scope": ["tests"],
                "completion": ["prepared"],
                "context": {"paths": ["missing/file.py"]},
            }
        )
        self.assertEqual(contract.context["paths"], ["missing/file.py"])
        self.assertIsNone(contract.context["verified"])

    def test_explicit_verified_working_tree_is_checked_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            (workspace / "input.txt").write_text("stable", encoding="utf-8")
            state = StateStore(Path(directory) / "state")
            prepared = prepare_dispatch(
                {
                    "profile": "strict",
                    "objective": "Verify exact material",
                    "scope": ["input.txt"],
                    "forbidden_scope": ["external systems"],
                    "completion": ["prepared"],
                    "evidence": ["sha256"],
                    "context": {
                        "verified": {
                            "mode": "declared",
                            "workspace_root": str(workspace),
                            "baseline": {"kind": "working_tree", "revision": None},
                            "required_paths": [{"path": "input.txt", "type": "file"}],
                        }
                    },
                },
                "verified-session",
                native_interface="fork_context",
                state_store=state,
                task_id_factory=lambda: "verified-task",
                now=10,
            )
            verification = state.read("verified-session")["tasks"][prepared["task_id"]]["prepared"]["context_verification"]
            self.assertEqual(verification["required_paths"][0]["sha256"], "f379ccb92b9116442dc65bdc35648a85d3786b34779db7f704a901fa07b00cb6")

    def test_schema_and_runtime_reject_working_tree_directory_before_state_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            (workspace / "docs").mkdir()
            manifest = {
                "mode": "declared",
                "workspace_root": str(workspace),
                "baseline": {"kind": "working_tree", "revision": None},
                "required_paths": [{"path": "docs", "type": "directory"}],
            }
            schema_errors = validate_instance(
                manifest,
                semantics.SEMANTIC_DEFINITIONS["verified_context"],
                root_schema=semantics.MACHINE_SEMANTICS,
            )
            self.assertTrue(schema_errors)

            state = StateStore(Path(directory) / "state")
            contract = self.verified_contract(
                workspace,
                {"kind": "working_tree", "revision": None},
                [{"path": "docs", "type": "directory"}],
            )
            with self.assertRaisesRegex(
                DispatchPreparationError, "working_tree.*directory"
            ):
                prepare_dispatch(contract, "directory-session", native_interface="fork_context", state_store=state)
            self.assertEqual(list(state.root.glob("*.json")), [])

    def test_git_commit_directory_uses_tree_object_and_rejects_workspace_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.name", "Test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.email", "test@example.com"],
                check=True,
            )
            (workspace / "docs").mkdir()
            (workspace / "docs" / "input.txt").write_text("stable", encoding="utf-8")
            subprocess.run(["git", "-C", str(workspace), "add", "docs/input.txt"], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "commit", "-q", "-m", "fixture"],
                check=True,
            )
            revision = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            contract = self.verified_contract(
                workspace,
                {"kind": "git_commit", "revision": revision},
                [{"path": "docs", "type": "directory"}],
            )
            state = StateStore(Path(directory) / "state")
            prepared = prepare_dispatch(
                contract,
                "git-directory-session",
                native_interface="fork_context",
                state_store=state,
                task_id_factory=lambda: "git-directory-task",
                now=10,
            )
            object_id = prepared["context_verification"]["required_paths"][0][
                "object_id"
            ]
            expected = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", f"{revision}:docs"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(object_id, expected)

            (workspace / "docs" / "input.txt").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(
                DispatchPreparationError, "工作区内容与 Git baseline 不一致"
            ):
                prepare_dispatch(
                    contract,
                    "dirty-directory-session",
                    native_interface="fork_context",
                    state_store=state,
                )

    def test_git_verification_does_not_refresh_index(self):
        import os
        from scripts.governance_context import verify_context_manifest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.run(["git", "-C", str(root), *args], check=True,
                                      capture_output=True, text=True).stdout.strip()
            git("init", "-q")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.com")
            material = root / "input.txt"
            material.write_text("stable")
            git("add", "input.txt")
            git("commit", "-q", "-m", "fixture")
            manifest = self.verified_contract(root, {"kind": "git_commit", "revision": git("rev-parse", "HEAD")},
                [{"path": "input.txt", "type": "file"}])["context"]["verified"]
            metadata = material.stat()
            os.utime(material, ns=(metadata.st_atime_ns, metadata.st_mtime_ns - 10_000_000_000))
            index = root / ".git" / "index"
            before = index.read_bytes()
            self.assertEqual(verify_context_manifest(manifest)["mode"], "declared")
            self.assertEqual(index.read_bytes(), before)

    def test_git_material_drift_at_claim_is_a_conflict_and_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            subprocess.run(["git", "-C", str(workspace), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(workspace), "config", "user.email", "test@example.com"], check=True)
            (workspace / "input.txt").write_text("stable", encoding="utf-8")
            subprocess.run(["git", "-C", str(workspace), "add", "input.txt"], check=True)
            subprocess.run(["git", "-C", str(workspace), "commit", "-q", "-m", "fixture"], check=True)
            revision = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            contract = self.verified_contract(
                workspace,
                {"kind": "git_commit", "revision": revision},
                [{"path": "input.txt", "type": "file"}],
            )
            state = StateStore(Path(directory) / "state")
            prepared = prepare_dispatch(
                contract,
                "git-claim-session",
                native_interface="fork_context",
                state_store=state,
                task_id_factory=lambda: "git-claim-task",
                now=10,
            )
            (workspace / "input.txt").write_text("changed", encoding="utf-8")
            result = handle_hook(
                {
                    "session_id": "git-claim-session",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "spawn_agent",
                    "tool_use_id": "git-claim-call",
                    "tool_input": prepared["spawn_args"],
                    "now": 11,
                },
                state,
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("材料冲突", result["hookSpecificOutput"]["permissionDecisionReason"])
            self.assertEqual(state.read("git-claim-session")["tasks"][prepared["task_id"]]["phase"], "prepared")


if __name__ == "__main__":
    unittest.main()
